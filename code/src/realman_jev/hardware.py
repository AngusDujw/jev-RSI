"""RM75 API2 + aligned RealSense RGB-D. Never move on connect/reset/observe.

SDK unit conversion/arm-angle IK follows inspect-robots-realman's MIT backend.
This adapter uses arm-angle-constrained IK and controller-planned small joint moves;
it does not stream CANFD from an API-paced Python loop.
"""
import json
import time
from contextlib import suppress
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from filelock import FileLock
from .contracts import CameraFrame,Observation


def check(code,name):
    if code!=0:
        raise RuntimeError(f"RealMan {name}: status {code}")


def rigid(T):
    T=np.asarray(T,float)
    if T.shape!=(4,4) or not np.isfinite(T).all() or not np.allclose(T[3],[0,0,0,1]) or not np.allclose(T[:3,:3].T@T[:3,:3],np.eye(3),atol=1e-4) or abs(np.linalg.det(T[:3,:3])-1)>.001:
        raise ValueError("Invalid rigid calibration transform")
    return T


class RealSense:
    def __init__(self,cameras,calibration):
        import pyrealsense2 as rs
        self.rs,self.streams,self.calibration=rs,[],calibration
        try:
            for c in cameras:
                pipeline=rs.pipeline(); config=rs.config()
                config.enable_device(c["serial"])
                config.enable_stream(rs.stream.depth,c["width"],c["height"],rs.format.z16,30)
                config.enable_stream(rs.stream.color,c["width"],c["height"],rs.format.rgb8,30)
                profile=pipeline.start(config)
                scale=profile.get_device().first_depth_sensor().get_depth_scale()
                self.streams.append((c,pipeline,rs.align(rs.stream.color),scale))
        except BaseException:
            self.close(); raise

    def read(self,T_base_tool):
        import cv2
        frames={}
        for c,pipeline,align,scale in self.streams:
            # Flush queued frames: timestamp is host acquisition, not request start.
            for _ in range(3):
                raw=pipeline.wait_for_frames(timeout_ms=1500)
            aligned=align.process(raw)
            color=aligned.get_color_frame(); depth=aligned.get_depth_frame()
            if not color or not depth:
                raise RuntimeError("Missing RGB-D frame")
            intrinsic=color.profile.as_video_stream_profile().intrinsics
            K=np.array([[intrinsic.fx,0,intrinsic.ppx],[0,intrinsic.fy,intrinsic.ppy],[0,0,1.]])
            rgb=np.asanyarray(color.get_data()).copy(); z=np.asanyarray(depth.get_data()).astype(float)*scale
            coeffs=np.array(intrinsic.coeffs)
            if np.any(coeffs):
                if intrinsic.model not in (self.rs.distortion.brown_conrady,self.rs.distortion.modified_brown_conrady):
                    raise ValueError("Unsupported color distortion; calibrate/rectify before motion")
                maps=cv2.initUndistortRectifyMap(K,coeffs,None,K,(c["width"],c["height"]),cv2.CV_32FC1)
                rgb=cv2.remap(rgb,*maps,cv2.INTER_LINEAR)
                z=cv2.remap(z,*maps,cv2.INTER_NEAREST)
            cal=self.calibration.get(c["name"],{})
            T=None
            if cal.get("T_base_camera") is not None:
                T=rigid(cal["T_base_camera"])
            elif cal.get("T_tool_camera") is not None:
                T=T_base_tool@rigid(cal["T_tool_camera"])
            frames[c["name"]]=CameraFrame(c["name"],rgb,z,K,T,time.monotonic())
        return frames

    def close(self):
        for _,p,_,_ in self.streams:
            with suppress(Exception): p.stop()
        self.streams=[]


class RealMan:
    def __init__(self,cfg,execute=False):
        self.cfg,self.execute_enabled=cfg,execute
        self.arm=None; self.cameras=None; self.commanded=False; self.sequence=0
        Path(cfg["lock_file"]).parent.mkdir(parents=True,exist_ok=True)
        self.lock=FileLock(cfg["lock_file"])
        self.lock.acquire(timeout=0)
        try:
            self.cal=json.loads(Path(cfg["calibration_file"]).read_text())
            if execute:
                self.validate_calibration()
            from Robotic_Arm.rm_robot_interface import RoboticArm,rm_thread_mode_e
            self.arm=RoboticArm(rm_thread_mode_e.RM_TRIPLE_MODE_E)
            h=self.arm.rm_create_robot_arm(cfg["ip"],cfg.get("port",8080),3)
            if h.id<=0: raise RuntimeError("Cannot connect to RM75")
            code,info=self.arm.rm_get_robot_info(); check(code,"robot info")
            if info.get("arm_dof")!=7 or info.get("arm_model")!="RM_75":
                raise ValueError("Expected seven-axis RM75")
            self.frames={}
            for label,method in (("tool",self.arm.rm_get_current_tool_frame),("work",self.arm.rm_get_current_work_frame)):
                code,value=method(); check(code,label+" frame"); self.frames[label]=value
                if execute and value.get("name")!=cfg["expected_"+label+"_frame"]:
                    raise ValueError("Controller coordinate frame differs from calibrated configuration")
            self.cameras=RealSense(cfg["cameras"],self.cal["cameras"])
            self.initial_rotation=None
        except BaseException:
            self.close(); raise

    def validate_calibration(self):
        if not self.cal.get("verified") or self.cal.get("active_arm")!=self.cfg["active_arm"]:
            raise ValueError("Measured calibration must be verified for the active arm")
        if not self.cfg.get("expected_tool_frame") or not self.cfg.get("expected_work_frame"):
            raise ValueError("Set measured tool/work frame names")
        if not self.cfg.get("workspace_verified"):
            raise ValueError("Measure and verify workspace and tool envelope first")
        for c in self.cfg["cameras"]:
            cal=self.cal["cameras"][c["name"]]
            if cal.get("serial")!=c["serial"]:
                raise ValueError("Camera serial does not match calibration")
            rigid(cal.get("T_base_camera") if cal.get("T_base_camera") is not None else cal.get("T_tool_camera"))
        rigid(self.cal["T_tool_grasp"])

    def state(self):
        code,s=self.arm.rm_get_current_arm_state(); check(code,"state")
        if any(str(e) not in ("0","0x0","0x0000","") for e in s.get("err",{}).get("err",[])):
            raise RuntimeError("Controller reports fault")
        q=np.deg2rad(s["joint"]); pose=np.asarray(s["pose"],float)
        if q.shape!=(7,) or pose.shape!=(6,) or not np.isfinite(q).all() or not np.isfinite(pose).all():
            raise ValueError("Malformed robot feedback")
        if np.any(q<np.deg2rad(self.cfg["joint_low_deg"])) or np.any(q>np.deg2rad(self.cfg["joint_high_deg"])):
            raise ValueError("Measured joint limit violation")
        T=np.eye(4); T[:3,3]=pose[:3]; T[:3,:3]=Rotation.from_euler("xyz",pose[3:]).as_matrix()
        code,g=self.arm.rm_get_gripper_state(); check(code,"gripper state")
        if g["status"]!=1 or g["enable_state"]!=1 or g["error"]!=0:
            raise RuntimeError("Gripper offline/disabled/fault")
        return q,pose,T,float(np.clip(g["actpos"]/1000,0,1))

    def observe(self):
        self.sequence+=1
        q,pose,T,opening=self.state()
        frames=self.cameras.read(T)
        q2,pose2,T2,opening=self.state()
        if np.linalg.norm(pose2[:3]-pose[:3])>.001 or np.linalg.norm(q2-q)>.015:
            raise RuntimeError("Robot moved during camera capture; observation not synchronized")
        self.initial_rotation=T2[:3,:3].copy() if self.initial_rotation is None else self.initial_rotation
        grasp=T2@rigid(self.cal.get("T_tool_grasp") or np.eye(4).tolist())
        return Observation(self.sequence,time.monotonic(),pose2[:3],T2[:3,:3],q2,opening,frames,grasp[:3,3])

    def execute(self,action,observation):
        if not self.execute_enabled:
            return {"executed":False,"reason":"observe-only"}
        for label,method in (("tool",self.arm.rm_get_current_tool_frame),("work",self.arm.rm_get_current_work_frame)):
            code,frame=method();check(code,label+" frame before move")
            if frame!=self.frames[label]: raise RuntimeError("Controller frame changed during episode")
        # Re-read after API wait. A delayed decision cannot move from a changed pose.
        q,pose,T,opening=self.state()
        if np.linalg.norm(pose[:3]-observation.tcp)>.002 or np.max(np.abs(q-observation.joints))>.02:
            raise ValueError("Pose changed since decision; discard action")
        if np.linalg.norm(Rotation.from_matrix(T[:3,:3]@self.initial_rotation.T).as_rotvec())>.03:
            raise ValueError("Unexpected tool orientation change")
        target=pose.copy(); target[:3]+=action["delta"]
        delta=np.linalg.norm(action["delta"])
        if delta:
            from Robotic_Arm.rm_robot_interface import rm_inverse_kinematics_params_t
            quat=Rotation.from_matrix(T[:3,:3]).as_quat()
            ik_pose=[*target[:3],quat[3],*quat[:3]]
            code,angle=self.arm.rm_algo_calculate_arm_angle_from_config_rm75(np.rad2deg(q).tolist()); check(code,"arm angle")
            params=rm_inverse_kinematics_params_t(np.rad2deg(q).tolist(),ik_pose,0)
            code,solution=self.arm.rm_algo_inverse_kinematics_rm75_for_arm_angle(params,angle); check(code,"IK")
            if len(solution)!=7 or not np.isfinite(solution).all() or np.any(np.abs(np.array(solution)-np.rad2deg(q))>self.cfg["max_joint_step_deg"]):
                raise ValueError("Unsafe IK branch or malformed solution")
            if np.any(np.array(solution)<self.cfg["joint_low_deg"]) or np.any(np.array(solution)>self.cfg["joint_high_deg"]):
                raise ValueError("IK joint limits")
            # Reject curved joint-space interpolation leaving the small Cartesian
            # neighbourhood, before any command is sent. Uses robot FK only.
            for alpha in np.linspace(0,1,11):
                iq=np.rad2deg(q)*(1-alpha)+np.array(solution)*alpha
                fk=np.asarray(self.arm.rm_algo_forward_kinematics(iq.tolist()),float)
                if fk.shape!=(6,) or not np.isfinite(fk).all():
                    raise ValueError("Malformed FK preview")
                if np.linalg.norm(fk[:3]-(pose[:3]+alpha*np.array(action["delta"])))>.0015:
                    raise ValueError("Joint path deviates from admitted Cartesian segment")
            self.commanded=True
            # MoveL's own RM75 solver may choose another redundant branch. Send
            # the checked arm-angle IK joints instead; do not silently lose them.
            check(self.arm.rm_movej(list(solution),self.cfg["speed_percent"],0,0,0),"movej")
            started=time.monotonic(); settled=0
            while True:
                if Path(self.cfg["stop_file"]).exists():
                    raise RuntimeError("STOP requested")
                q_now,p_now,_,_=self.state()
                if np.max(np.abs(q_now-q))>np.deg2rad(self.cfg["max_joint_step_deg"]):
                    raise RuntimeError("Actual motion exceeded joint-step envelope")
                arrived=np.linalg.norm(p_now[:3]-target[:3])<self.cfg["arrival_tolerance_m"]
                settled=settled+1 if arrived else 0
                if settled>=3: break
                if time.monotonic()-started>self.cfg["motion_timeout_s"]:
                    raise RuntimeError("Controller failed to settle before deadline")
                time.sleep(.05)
        g=action["gripper"]
        if g!="hold":
            self.commanded=True
            check(self.arm.rm_set_gripper_position(1000 if g=="open" else 1,False,1),"gripper")
            # Never retry a timed-out command; verify bounded aperture settling.
            last=None; stable=0; start=time.monotonic()
            while time.monotonic()-start<self.cfg["gripper_timeout_s"]:
                if Path(self.cfg["stop_file"]).exists(): raise RuntimeError("STOP requested")
                _,_,_,opening=self.state()
                stable=stable+1 if last is not None and abs(last-opening)<.01 else 0
                last=opening
                if stable>=4 and ((g=="close" and opening<.85) or (g=="open" and opening>.9)): break
                time.sleep(.1)
            else: raise RuntimeError("Gripper did not settle")
        return {"executed":True,"target_tcp_m":target[:3].tolist(),"gripper":g}

    def evaluation(self):
        return {"physical_success":None,"note":"Real hardware needs recorded observation and human outcome"}

    def close(self):
        if self.arm:
            if self.commanded:
                with suppress(Exception): check(self.arm.rm_set_arm_slow_stop(),"stop")
            with suppress(Exception): self.arm.rm_delete_robot_arm()
            self.arm=None
        if self.cameras:
            self.cameras.close(); self.cameras=None
        self.lock.release()

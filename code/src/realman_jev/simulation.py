"""Panda physics reference; policy receives rendered sensors, never world.observe()."""
import time
import numpy as np
import mujoco
from .contracts import CameraFrame, Observation


class Simulation:
    def __init__(self, cfg, seed=0):
        from embodied_jev.physics import RobotWorld
        self.world=RobotWorld(task=cfg.get("task","transfer"),seed=seed)
        # Explicit experimental physics setting, never a policy observation.
        if "noslip_iterations" in cfg:
            value=cfg["noslip_iterations"]
            if type(value) is not int or not 0<=value<=100:
                raise ValueError("noslip_iterations must be an integer in [0,100]")
            self.world.model.opt.noslip_iterations=value
        self.renderer=mujoco.Renderer(self.world.model,height=480,width=640)
        self.cfg=cfg
        self.sequence=0
        self.camera=mujoco.MjvCamera()
        self.camera.type=mujoco.mjtCamera.mjCAMERA_FREE
        self.camera.lookat[:]=[.43,0,.015]
        self.camera.distance=.85
        self.camera.azimuth=90
        self.camera.elevation=-80

    def frame(self,name,camera):
        self.renderer.disable_depth_rendering()
        self.renderer.update_scene(self.world.data,camera=camera)
        rgb=self.renderer.render().copy()
        c=self.renderer.scene.camera
        pos=(c[0].pos+c[1].pos)/2
        forward=(c[0].forward+c[1].forward)/2
        up=(c[0].up+c[1].up)/2
        forward=forward/np.linalg.norm(forward)
        right=np.cross(forward,up); right/=np.linalg.norm(right)
        up=np.cross(right,forward)
        T=np.eye(4); T[:3,:3]=np.column_stack((right,-up,forward)); T[:3,3]=pos
        fovy=self.world.model.vis.global_.fovy if name=="top" else self.world.model.cam_fovy[self.world.model.camera("wrist_camera").id]
        f=480/(2*np.tan(np.deg2rad(fovy)/2))
        K=np.array([[f,0,319.5],[0,f,239.5],[0,0,1.]])
        self.renderer.enable_depth_rendering()
        depth=self.renderer.render().copy()
        self.renderer.disable_depth_rendering()
        return CameraFrame(name,rgb,depth,K,T,time.monotonic())

    def observe(self):
        self.sequence+=1
        w=self.world
        frames={"top":self.frame("top",self.camera)}
        if self.cfg.get("wrist",True):
            frames["wrist"]=self.frame("wrist","wrist_camera")
        # Only robot encoder/FK quantities. Contact forces/object qpos are excluded.
        opening=sum(float(w.data.qpos[w.model.jnt_qposadr[w.model.joint(n).id]]) for n in ("finger_joint1","finger_joint2"))/.08
        return Observation(self.sequence,time.monotonic(),w.position,w.data.site_xmat[w.tcp].reshape(3,3).copy(),
                           w.data.qpos[w.arm_q].copy(),float(np.clip(opening,0,1)),frames,w.position.copy())

    def execute(self, action, observation):
        target=observation.tcp+np.array(action["delta"])
        g=action["gripper"]
        for _ in self.world.motion(target, None if g=="hold" else g,seconds=self.cfg.get("action_seconds",.4),emit=False):
            pass
        return {"executed":True,"target_tcp_m":target.tolist()}

    def evaluation(self):
        # Called only AFTER policy termination; never returned as observation.
        return {"privileged_evaluation_only":True,"physical_success":self.world.success(),
                "unsafe_contact_ticks":self.world.unsafe_contacts,"sim_seconds":float(self.world.data.time-self.world.start_time)}

    def close(self):
        self.renderer.close()

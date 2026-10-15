"""Reused sensor synchronization for native RoboDojo; no task plan or actor policy."""

import os
from pathlib import Path

import cv2  # Import before Kit adds its extension library paths.
# Kit also imports an unrelated `utils` package. Resolve RoboDojo's own utility
# namespace before native reward/task modules import utils.transformer.
from env.global_configs import ROOT_DIR
import utils
utils.__path__ = [str(Path(ROOT_DIR).resolve() / 'utils')]
import utils.load_file
from isaaclab.app import AppLauncher as _AppLauncher
import isaaclab.app as app_module


class SyncedLauncher(_AppLauncher):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from omni.kit.material.library import material_library

        if (os.environ.get("ROBODOJO_TASK") == "fold_clothes" and
                os.environ.get("ROBODOJO_FOLD_CPU_USD_SYNC_AUDIT") == "1"):
            import carb

            settings = carb.settings.get_settings()
            settings.set_bool("/physics/updateToUsd", True)
            settings.set_bool("/physics/updateParticlesToUsd", True)

        cache = Path(os.environ["ROBODOJO_DECISION_CACHE"]) / "kit_material"
        cache.mkdir(parents=True, exist_ok=True)
        if material_library.material_instance is not None:
            material_library.material_instance._cache_filename = str(cache / "material_cache.json")

        from env.environment.base_env import BaseEnv

        original = BaseEnv.__init__

        def synchronized(env, config, *a, **kw):
            config.use_fabric = True
            # CPU+Fabric skips Garment and Articulation objects at scene load.
            # Cloth fails to initialize under GPU Fabric here; button reward
            # code also converts GPU tensors directly to NumPy. The egg-holder
            # layout uses an articulation and its CPU+Fabric reset omits that
            # object; toaster, laptop and spring-button articulations behave the same way. These
            # tasks need the native CPU non-Fabric path.
            task = os.environ.get("ROBODOJO_TASK")
            cpu_nonfabric_tasks = {"fold_clothes", "press_by_number",
                                   "fill_egg_holder", "make_toast",
                                   "store_laptop_and_headphones", "swap_blocks"}
            press_gpu_fabric_audit = (task == "press_by_number" and
                                      os.environ.get("ROBODOJO_PRESS_GPU_FABRIC_AUDIT") == "1")
            if task in cpu_nonfabric_tasks and not press_gpu_fabric_audit:
                config.device = "cpu"
                config.use_fabric = False
            if press_gpu_fabric_audit:
                config.device = "cuda:0"
                config.use_fabric = True
            return original(env, config, *a, **kw)

        BaseEnv.__init__ = synchronized
        _install_sensor_calibration()
        if os.environ.get("ROBODOJO_SYNC_PUBLIC_WRIST_MOUNTS") == "1":
            _install_public_wrist_mount_sync()
        if os.environ.get("ROBODOJO_PRESS_GPU_FABRIC_AUDIT") == "1":
            _install_gpu_articulation_property_bridge()


app_module.AppLauncher = SyncedLauncher

def _install_sensor_calibration():
    from hybrid_rollout.robodojo.robodojo_server import session as native_session

    native_dispatch = native_session.RoboDojoSession.dispatch

    def sensor_calibration_dispatch(self, op, args):
        """Expose authored RGB K/T; wrist T is propagated from measured LINK6 by client."""
        if (op == 'public_robot_gripper_state' and
                os.environ.get('ROBODOJO_MEASURED_GRIPPER_STATE') == '1'):
            self._check_identity(args['episode_id'],args['step_id'])
            manager=self.env.robot_manager
            arms={r.arm_name.split('_')[0]:r for r in manager.robot_list if r.type=='target'}
            if set(arms) != {'left','right'}:
                raise RuntimeError('Expected two public robot arms')
            measured={}
            for arm,robot in arms.items():
                names=list(robot.gripper_joints_name)
                values=manager.get_end_effector_real_val(robot,env_idx_list=[0])[0]
                if len(names)!=len(values):
                    raise RuntimeError('Gripper joint names/encoder shape mismatch')
                measured[arm]={'joint_names':names,'joint_positions_m':values.tolist(),
                    'source':'Current robot articulation joint_pos, not prev_control command'}
            return {'step_id':self.step_id,'physical_steps':0,'arms':measured,
                'scope':'Robot prismatic joint encoders only; no object state, contacts, force, reward or outcome.'}
        if op != "public_camera_calibration":
            return native_dispatch(self, op, args)
        self._check_identity(args["episode_id"], args["step_id"])
        manager = self.env.camera_manager
        names = {"cam_head": "cam_high", "cam_high": "cam_high",
                 "cam_left_wrist": "cam_left_wrist", "cam_right_wrist": "cam_right_wrist"}
        origin = self.env.scene_manager.env_origins[0].detach().cpu().numpy()
        cameras = {}
        for index, native_name in enumerate(manager.camera_names[0]):
            name = names.get(native_name)
            if name not in native_session.CAMERAS:
                continue
            intrinsic = manager.get_camera_intrinsics(index, 0)
            transform = manager.get_camera_extrinsics(index, 0)
            transform[:3, 3] -= origin
            height, width = self.obs[name].shape[:2]
            cameras[name] = {"intrinsic": intrinsic.tolist(),
                             "camera_to_environment": transform.tolist(),
                             "size": [width, height]}
        if set(cameras) != set(native_session.CAMERAS):
            raise RuntimeError("Current public camera calibration incomplete")
        return {"source": "RoboDojo RGB intrinsics and authored mount transforms; wrist pose requires measured LINK6 propagation",
                "step_id": self.step_id, "cameras": cameras}

    native_session.RoboDojoSession.dispatch = sensor_calibration_dispatch


def _install_public_wrist_mount_sync():
    """Test CPU non-Fabric wrist render mounts against measured robot LINK6.

    This optional sensor repair uses only public robot link state and the
    authored camera mounts. It never reads task object state or evaluation data.
    """
    import numpy as np
    import torch
    from scipy.spatial.transform import Rotation

    from env.observation_manager.obs_manager import ObsManager
    from hybrid_rollout.robodojo.robodojo_server import session as native_session

    original_get_obs = ObsManager.get_obs
    original_observe = native_session.RoboDojoSession._observe

    def transform(pose):
        quaternion = np.asarray(pose[3:7], dtype=float)
        value = np.eye(4)
        value[:3, :3] = Rotation.from_quat(quaternion[[1, 2, 3, 0]]).as_matrix()
        value[:3, 3] = pose[:3]
        return value

    def synced_get_obs(self, env_idx_list=None):
        task=os.environ.get('ROBODOJO_TASK')
        manual_mount=(task=='fold_clothes' or (task=='press_by_number' and
            os.environ.get('ROBODOJO_PRESS_GPU_FABRIC_AUDIT')!='1'))
        # GPU Fabric already propagates mounted cameras through the robot
        # hierarchy. Reapplying the CPU USD repair can move the render view
        # twice even though its USD parent pose agrees with FK propagation.
        if manual_mount:
            camera_manager = self.camera_manager
            robot_manager = self.robot_manager
            if camera_manager is not None and robot_manager is not None:
                anchors = getattr(self, "_codex_wrist_sync_anchor", None)
                if anchors is None:
                    anchors = {}
                    self._codex_wrist_sync_anchor = anchors
                arms = {robot.arm_name.split("_")[0]: robot
                        for robot in robot_manager.robot_list
                        if robot.type == "target" and robot.robot_type == "arm"}
                for arm in ("left", "right"):
                    name = f"cam_{arm}_wrist"
                    if arm not in arms or name not in camera_manager.camera_names[0]:
                        continue
                    index = camera_manager.camera_names[0].index(name)
                    current = transform(robot_manager.get_real_endpose(
                        arms[arm], env_idx_list=[0], is_relative=False)[0])
                    camera = camera_manager.cameras_xform[0][index]
                    if arm not in anchors:
                        anchors[arm] = (current,
                                        camera_manager.get_camera_extrinsics(index, 0))
                    initial_link, initial_camera = anchors[arm]
                    new_camera = current @ np.linalg.inv(initial_link) @ initial_camera
                    quaternion_xyzw = Rotation.from_matrix(new_camera[:3, :3]).as_quat()
                    quaternion_wxyz = quaternion_xyzw[[3, 0, 1, 2]]
                    old_pos, _ = camera.get_world_pose()
                    camera.set_world_pose(
                        position=torch.as_tensor(new_camera[:3, 3], dtype=torch.float32,
                                                 device=old_pos.device),
                        orientation=torch.as_tensor(quaternion_wxyz, dtype=torch.float32,
                                                    device=old_pos.device))
        return original_get_obs(self, env_idx_list=env_idx_list)

    def reset_anchor_before_first_observation(self, record=False):
        if self.step_id == 0 and not getattr(self, "_codex_wrist_mount_reset", False):
            self.env.obs_manager._codex_wrist_sync_anchor = {}
            self._codex_wrist_mount_reset = True
        return original_observe(self, record=record)

    ObsManager.get_obs = synced_get_obs
    native_session.RoboDojoSession._observe = reset_anchor_before_first_observation


def _install_gpu_articulation_property_bridge():
    """Keep Isaac Sim's public DOF metadata readable on a GPU Fabric pilot.

    The installed SingleArticulation property directly assigns CUDA tensors to
    NumPy structured fields. This changes only that metadata conversion in the
    isolated native simulator process; it does not expose button joint state to
    the planner or the decision model.
    """
    import numpy as np
    import torch
    from isaacsim.core.prims.impl.single_articulation import SingleArticulation

    def host(value):
        return value.detach().cpu().numpy() if isinstance(value, torch.Tensor) else value

    def dof_properties(self):
        dtype = np.dtype([
            ("type", int), ("hasLimits", bool), ("lower", float),
            ("upper", float), ("driveMode", int), ("maxVelocity", float),
            ("maxEffort", float), ("stiffness", float), ("damping", float),
        ])
        result = np.zeros(self.num_dof, dtype=dtype)
        view = self._articulation_view
        result["type"] = host(view.get_dof_types()[0])
        limits = host(view.get_dof_limits()[0])
        result["lower"], result["upper"] = limits[:, 0], limits[:, 1]
        result["hasLimits"] = result["lower"] < result["upper"]
        result["driveMode"] = host(view.get_drive_types()[0])
        result["maxEffort"] = host(view.get_max_efforts()[0])
        result["maxVelocity"] = host(view.get_joint_max_velocities()[0])
        stiffness, damping = view.get_gains()
        result["stiffness"] = host(stiffness[0])
        result["damping"] = host(damping[0])
        return result

    SingleArticulation.dof_properties = property(dof_properties)

    from env.reward_manager.func_parser import Func_Parser
    original_init_state = Func_Parser.init_state

    def init_state_with_host_pose(self):
        layout = self.layout_manager
        original_pose = layout.get_instance_pose

        def host_pose(*args, **kwargs):
            pos, rot = original_pose(*args, **kwargs)
            return host(pos), host(rot)

        layout.get_instance_pose = host_pose
        try:
            return original_init_state(self)
        finally:
            layout.get_instance_pose = original_pose

    Func_Parser.init_state = init_state_with_host_pose

from hybrid_rollout.robodojo.robodojo_server.server import main

if __name__ == "__main__":
    main()

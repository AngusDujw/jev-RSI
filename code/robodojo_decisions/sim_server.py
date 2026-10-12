"""Start the existing RoboDojo native RPC server with fresh Fabric RGB frames."""

import os
from pathlib import Path

import cv2  # Import before Kit adds its extension library paths.
from isaaclab.app import AppLauncher as _AppLauncher
import isaaclab.app as app_module


class SyncedLauncher(_AppLauncher):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from omni.kit.material.library import material_library

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
            # code also converts GPU tensors directly to NumPy. Both need the
            # native CPU non-Fabric path for a valid reset.
            if os.environ.get("ROBODOJO_TASK") in {"fold_clothes", "press_by_number"}:
                config.device = "cpu"
                config.use_fabric = False
            return original(env, config, *a, **kw)

        BaseEnv.__init__ = synchronized
        _install_sensor_calibration()


app_module.AppLauncher = SyncedLauncher

def _install_sensor_calibration():
    from hybrid_rollout.robodojo.robodojo_server import session as native_session

    native_dispatch = native_session.RoboDojoSession.dispatch

    def sensor_calibration_dispatch(self, op, args):
        """Expose authored RGB K/T; wrist T is propagated from measured LINK6 by client."""
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

from hybrid_rollout.robodojo.robodojo_server.server import main

if __name__ == "__main__":
    main()

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
            return original(env, config, *a, **kw)

        BaseEnv.__init__ = synchronized


app_module.AppLauncher = SyncedLauncher

from hybrid_rollout.robodojo.robodojo_server.server import main

if __name__ == "__main__":
    main()

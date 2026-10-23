"""Enable the installed camera extension before the original server imports it."""
from pathlib import Path
import json
import runpy
import site
import sys

import cv2
from isaaclab.app import AppLauncher
import isaaclab.app as app_module


class CameraLauncher(AppLauncher):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        import omni.kit.app
        manager = omni.kit.app.get_app().get_extension_manager()
        manager.set_extension_enabled_immediate('isaacsim.sensors.camera', True)
        # The installed headless experience enables fewer Python namespaces
        # than RoboDojo's eager object imports expect (including unused fluids).
        # Expose existing installed extension sources in this process only.
        import isaacsim
        for directory in site.getsitepackages():
            for family in ('exts', 'extsDeprecated'):
                root = Path(directory) / 'isaacsim' / family
                if not root.is_dir():
                    continue
                for extension in root.iterdir():
                    namespace = extension / 'isaacsim'
                    if namespace.is_dir():
                        if str(extension) not in sys.path:
                            sys.path.append(str(extension))
                        if str(namespace) not in isaacsim.__path__:
                            isaacsim.__path__.append(str(namespace))
        # AppLauncher --device does not populate RoboDojo's cfg.sim. Its
        # BaseEnv otherwise silently defaults to CPU/non-Fabric, leaving USD
        # render transforms stale in this installed headless experience.
        # Use the existing GPU/Fabric path for this rigid-object task only.
        from env.environment.base_env import BaseEnv
        native_init = BaseEnv.__init__

        def initialize_synced(env, config, *a, **kw):
            config.device = 'cuda:0'
            config.use_fabric = True
            result = native_init(env, config, *a, **kw)
            if env.device != 'cuda:0' or not env.use_fabric:
                raise RuntimeError('GPU/Fabric synchronization configuration rejected')
            print(json.dumps(dict(event='simulation_sync_config',
                device=env.device, use_fabric=env.use_fabric,
                revision='rigid-gpu-fabric-v1')), flush=True)
            return result

        BaseEnv.__init__ = initialize_synced


app_module.AppLauncher = CameraLauncher
runpy.run_path(str(Path(__file__).with_name('server_entry.py')), run_name='__main__')

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
        # Preserve RoboDojo's native CPU physics and reward implementation.
        # GPU/Fabric reset is incompatible with its NumPy reward initializer.
        # CPU physics needs explicit USD writes in this headless experience;
        # otherwise the measured robot moves but rendered robot/cameras do not.
        import carb
        settings = carb.settings.get_settings()
        settings.set_bool('/physics/updateToUsd', True)
        from env.environment.base_env import BaseEnv
        native_init = BaseEnv.__init__

        def initialize_synced(env, config, *a, **kw):
            config.device = 'cpu'
            config.use_fabric = False
            result = native_init(env, config, *a, **kw)
            if env.device != 'cpu' or env.use_fabric or not settings.get_as_bool('/physics/updateToUsd'):
                raise RuntimeError('CPU/USD synchronization configuration rejected')
            print(json.dumps(dict(event='simulation_sync_config',
                device=env.device, use_fabric=env.use_fabric,
                update_to_usd=True, revision='native-cpu-usd-sync-v1')), flush=True)
            return result

        BaseEnv.__init__ = initialize_synced


app_module.AppLauncher = CameraLauncher
runpy.run_path(str(Path(__file__).with_name('server_entry.py')), run_name='__main__')

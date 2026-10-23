"""Enable the installed camera extension before the original server imports it."""
from pathlib import Path
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


app_module.AppLauncher = CameraLauncher
runpy.run_path(str(Path(__file__).with_name('server_entry.py')), run_name='__main__')

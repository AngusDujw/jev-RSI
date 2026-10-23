"""Enable the installed camera extension before the original server imports it."""
from pathlib import Path
import runpy

import cv2
from isaaclab.app import AppLauncher
import isaaclab.app as app_module


class CameraLauncher(AppLauncher):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        import omni.kit.app
        manager = omni.kit.app.get_app().get_extension_manager()
        manager.set_extension_enabled_immediate('isaacsim.sensors.camera', True)


app_module.AppLauncher = CameraLauncher
runpy.run_path(str(Path(__file__).with_name('server_entry.py')), run_name='__main__')

"""Add camera calibration only; native stepping, observations and scoring unchanged."""
from pathlib import Path
import runpy
import numpy as np
from scipy.spatial.transform import Rotation
from hybrid_rollout.robodojo.robodojo_server.session import RoboDojoSession

original_observe = RoboDojoSession._observe


def observe(self, record=False):
    observation = original_observe(self, record=False)
    manager = self.env.camera_manager
    origin = self.env.env_origins[0]
    if hasattr(origin, 'detach'):
        origin = origin.detach().cpu().numpy()
    origin = np.asarray(origin)
    names = list(manager.camera_names[0])
    aliases = dict(cam_high=('cam_high', 'cam_head', 'head_camera', 'top_camera'),
                   cam_left_wrist=('cam_left_wrist', 'left_camera'),
                   cam_right_wrist=('cam_right_wrist', 'right_camera'))
    cameras = {}
    for label, options in aliases.items():
        index = next(i for i, name in enumerate(names) if name in options)
        camera = manager.cameras[0][index]
        position, quaternion = camera.get_world_pose(camera_axes='ros')
        transform = np.eye(4)
        transform[:3, :3] = Rotation.from_quat(np.asarray(quaternion)[[1, 2, 3, 0]]).as_matrix()
        transform[:3, 3] = np.asarray(position)-origin
        intrinsic = np.asarray(manager.get_camera_intrinsics(index, 0))
        if intrinsic.shape != (3, 3) or not np.isfinite(intrinsic).all() or min(intrinsic[0, 0], intrinsic[1, 1]) < 10:
            raise ValueError('Invalid native camera pixel calibration')
        cameras[label] = dict(K=intrinsic.tolist(), camera_to_world=transform.tolist(),
            image_size=[observation[label].shape[1], observation[label].shape[0]],
            source='Configured camera intrinsics and measured camera mounting pose only',
            convention='Camera X right, Y down, Z forward; environment origin world; meters')
    observation['camera_calibration'] = cameras
    return observation


RoboDojoSession._observe = observe
runpy.run_path(str(Path(__file__).with_name('server_entry.py')), run_name='__main__')

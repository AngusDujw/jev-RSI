"""Project-local RGB-D bridge extension; object truth never leaves vision RPC.

Uses native image-plane depth (meters), not segmentation IDs or object poses.
The existing simulator-only audit remains isolated on disk.
"""
from pathlib import Path
import faulthandler
import json
import os
import time
import numpy as np


def main():
    from env.global_configs import ROOT_DIR
    import utils
    utils.__path__ = [str(Path(ROOT_DIR).resolve() / 'utils')]
    import utils.load_file  # noqa: F401
    from omegaconf import OmegaConf
    original_create = OmegaConf.create
    material_cache_installed = False

    def create(obj=None, *args, **kwargs):
        nonlocal material_cache_installed
        cfg = original_create(obj, *args, **kwargs)
        if isinstance(obj, dict) and all(k in obj for k in ('eval_cfg', 'camera', 'task_env', 'sim')):
            if os.environ.get('COMPANY_MATERIAL_CACHE') and not material_cache_installed:
                from nvidia_material_cache import install
                install(os.environ['COMPANY_MATERIAL_CACHE'])
                material_cache_installed = True
            cfg.eval_cfg.observation.vision.depth = True
            for name in cfg.camera.annotator:
                cfg.camera.annotator[name].depth_capture = dict(type='distance_to_image_plane', device='cpu')
        return cfg

    OmegaConf.create = staticmethod(create)
    from realman_jev.company_bridge import install, array
    install()
    from hybrid_rollout.robodojo.robodojo_server import session
    parent = session.RoboDojoSession

    class RGBDSession(parent):
        def dispatch(self, op, args):
            if op == 'reset':
                started = time.monotonic()
                print(json.dumps(dict(event='reset_started', seed=args['seed'])), flush=True)
                faulthandler.dump_traceback_later(60, repeat=True)
                try:
                    return super().dispatch(op, args)
                finally:
                    faulthandler.cancel_dump_traceback_later()
                    print(json.dumps(dict(event='reset_finished', seconds=time.monotonic()-started)), flush=True)
            if op != 'rgbd_observation':
                return super().dispatch(op, args)
            self._check_identity(args['episode_id'], args['step_id'])
            if self.input_mode != 'vision':
                raise PermissionError('RGB-D experiment requires vision mode')
            raw = self.env.get_obs()
            cm = self.env.camera_manager
            views = {}
            for i, name in enumerate(cm.camera_names[0]):
                alias = 'cam_high' if name in ('cam_head', 'head_camera', 'top_camera') else name
                v = raw['vision'][name]
                depth = np.asarray(v['depth'], dtype=np.float32)
                if not np.isfinite(depth).any():
                    raise ValueError('No finite depth pixels')
                views[alias] = dict(rgb=np.asarray(v['color'], dtype=np.uint8)[..., :3],
                    depth_m=depth, intrinsic=array(cm.get_camera_intrinsics(i, 0)),
                    camera_to_world_opengl=array(cm.get_camera_extrinsics(i, 0)))
            return dict(source='rendered_RGB_D_and_robot_feedback', native_step=self.step_id,
                depth_convention='optical_Z_image_plane_m', cameras=views,
                env_origin=array(self.env.scene_manager.env_origins[0]),
                robot={k: self.obs[k] for k in ('states', 'eef_positions', 'eef_quaternions_wxyz')},
                gripper_bias_m=[float(self.kinematics.robots[a].gripper_bias) for a in ('left', 'right')],
                instruction=raw['instruction'])

    session.RoboDojoSession = RGBDSession
    from hybrid_rollout.robodojo.robodojo_server.server import main as launch
    launch()


if __name__ == '__main__':
    main()

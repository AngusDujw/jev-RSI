"""Bounded RGB-D LIBERO-Plus development rollouts using existing Jev recorder.
No object poses, segmentation IDs, reward or predicates enter the policy.
"""
import argparse
import contextlib
import io
import os
from pathlib import Path
import sys
import time

import cv2
import numpy as np
from run_position_pilot import Recorder, Jev, dump

ROOT = '/root/yekangjie/project/embodied-jev/.sim/LIBERO-plus'

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    p.add_argument('--capture-only', action='store_true')
    p.add_argument('--task-id', type=int, default=0)
    p.add_argument('--seed', type=int, default=0)
    a = p.parse_args()
    out = Path(a.output).resolve()
    cfg = dict(existing_root='/root/yekangjie/project/robodojo-jev',
               api_config='/root/yekangjie/project/robodojo-jev/controller/config/api.company.local.json',
               wall_limit_seconds=900, output_limit_mb=400, max_jev_decisions=120,
               suite='libero_spatial', task_id=a.task_id, seed=a.seed,
               permissions='RGB-D/calibration/robot feedback; NO object truth', deepseek_calls=0)
    rec = Recorder(out, cfg)
    cache = out / 'cache'; cache.mkdir()
    os.environ.update(LIBERO_CONFIG_PATH=ROOT+'/.libero-config', MUJOCO_GL='egl',
                      MUJOCO_EGL_DEVICE_ID='0', TMPDIR=str(cache), XDG_CACHE_HOME=str(cache))
    sys.path.insert(0, ROOT)
    from libero.libero import benchmark
    from libero.libero.envs.env_wrapper import ControlEnv
    from robosuite.utils.camera_utils import get_real_depth_map, get_camera_intrinsic_matrix, get_camera_extrinsic_matrix
    with contextlib.redirect_stdout(io.StringIO()):
        suite = benchmark.get_benchmark_dict()['libero_spatial'](0)
    task = suite.get_task(a.task_id)
    dump(out/'task.json', dict(name=task.name, language=task.language, bddl=suite.get_task_bddl_file_path(a.task_id)))
    env = None
    try:
        env = ControlEnv(bddl_file_name=suite.get_task_bddl_file_path(a.task_id),
             camera_names=['agentview','robot0_eye_in_hand'], camera_heights=384, camera_widths=384,
             camera_depths=True, control_freq=20, horizon=600, controller='OSC_POSE', initialization_noise=None)
        env.seed(a.seed); env.reset()
        obs = env.set_init_state(np.asarray(suite.get_task_init_states(a.task_id)[0],float))
        for _ in range(10): obs, _, _, _ = env.step(np.array([0.,0.,0.,0.,0.,0.,-1.]))
        for cam in ['agentview','robot0_eye_in_hand']:
            rgb = np.ascontiguousarray(obs[cam+'_image'][::-1])
            depth = get_real_depth_map(env.sim,obs[cam+'_depth'])[::-1].squeeze()
            cv2.imwrite(str(out/(cam+'.png')),cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR))
            np.save(out/(cam+'-depth.npy'),depth)
            dump(out/(cam+'-calibration.json'),dict(K=get_camera_intrinsic_matrix(env.sim,cam,384,384),T=get_camera_extrinsic_matrix(env.sim,cam)))
        dump(out/'robot.json',dict(position=obs['robot0_eef_pos'],quaternion=obs['robot0_eef_quat']))
        if a.capture_only:
            rec.finish('capture_only'); return
        raise RuntimeError('Policy not yet implemented; capture first')
    finally:
        if env is not None: env.close()

if __name__ == '__main__': main()

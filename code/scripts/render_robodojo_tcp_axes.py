"""Record six physical RoboDojo TCP-axis demonstrations, without any model call.

Run through the existing Isaac launcher. This is an action-interface diagnostic,
not a benchmark episode result. No scene-object poses or archived experience are read.
"""
import argparse
import importlib
import json
import os
from pathlib import Path
import sys

import numpy as np


def save(path, value):
    path.write_text(json.dumps(value, indent=2, default=lambda x: x.tolist() if isinstance(x, np.ndarray) else float(x)) + '\n')


def main():
    import cv2
    from isaaclab.app import AppLauncher
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    AppLauncher.add_app_launcher_args(parser)
    args = parser.parse_args()
    args.headless, args.enable_cameras = True, True
    args.output.mkdir(parents=True, exist_ok=False)
    app = AppLauncher(args).app
    env = None
    try:
        import carb
        # CPU physics writes transforms to USD; this prevents stale wrist renders.
        carb.settings.get_settings().set_bool('/physics/updateToUsd', True)
        carb.settings.get_settings().set_int('/app/updateOrder/checkForHydraRenderComplete', 1000)
        carb.settings.get_settings().set_bool('/app/renderer/waitIdle', True)
        carb.settings.get_settings().set_bool('/app/hydraEngine/waitIdle', True)
        from omegaconf import OmegaConf
        from scipy.optimize import least_squares
        from scipy.spatial.transform import Rotation as R
        from PIL import Image, ImageDraw, ImageFont
        import imageio.v2 as imageio
        from env.global_configs import ENV_CONFIG_PATH, ROOT_DIR, BENCHMARK
        sys.path.insert(0, str(Path(ROOT_DIR) / 'XPolicyLab'))
        import utils
        utils.__path__ = [str(Path(ROOT_DIR) / 'utils')]
        from utils.load_file import load_yaml
        from utils.pipeline_utils import process_config, process_randomization
        from src.eval_client import eval_env
        from hybrid_rollout.robodojo.robodojo_server.server import NoPolicyConnection
        from hybrid_rollout.robodojo.robodojo_server.session import RoboDojoSession, CAMERAS
        registry = importlib.import_module(f'task.{BENCHMARK}.task_registry')
        root = Path(ENV_CONFIG_PATH)
        ev = load_yaml(str(root / 'arx_x5.yml'))
        ev.update(task_name='general_pickup', num_envs=1, device_id=0, eval_batch=False,
                  policy_name='Pi_05', additional_info='tcp_axis_diagnostic', seed=0,
                  physx_monitor_enabled=False)
        values = {k: load_yaml(str(root / k / (ev['config'][k] + '.yml')))
                  for k in ('sim', 'scene', 'camera', 'robot')}
        values.update(eval_cfg=ev, deploy_cfg=dict(port=1, policy_name='Pi_05'),
                      task_env=load_yaml(registry.task_config_path(str(Path(ROOT_DIR) / 'task' / BENCHMARK / 'config'), 'general_pickup')))
        cfg = OmegaConf.create(values)
        cfg.sim.scene.num_envs = 1
        cfg = process_randomization(cfg)
        cfg, _ = process_config(cfg, task_name='general_pickup')
        cfg.eval_cfg.eval_num = 1
        cfg.camera.default_frequency = cfg.eval_cfg.observation.collect_freq
        cfg.sim.seed = [0]
        cfg.sim.device = 'cpu'
        cfg.sim.use_fabric = False
        for robot in cfg.robot.robots:
            robot.need_planner = False
        old = eval_env.WsModelClient
        try:
            eval_env.WsModelClient = NoPolicyConnection
            env = eval_env.create_eval_env(cfg, app)
        finally:
            eval_env.WsModelClient = old
        print('NATIVE_ENV_CREATED', flush=True)
        carb.settings.get_settings().set_bool('/physics/updateToUsd', True)
        # This is a continuous robot-motion demonstration, not a scored episode.
        # Extend only the diagnostic recording horizon; do not change the scorer.
        original_horizon = int(env.step_lim)
        env.step_lim = max(original_horizon, 2000)
        save(args.output / 'diagnostic_scope.json', dict(benchmark_evaluation=False,
             original_horizon=original_horizon, diagnostic_horizon=int(env.step_lim),
             reset_policy='one native reset; physically return robot to the common pose before each clip'))
        # Use the public inner gripping-face extent, not robot_config's rough bias.
        tcp_offset = np.array([0.15007, 0., 0.])
        records, common, sess = [], None, None
        initial_q = None
        for channel in ('x', 'y', 'z', 'yaw', 'pitch', 'roll'):
            folder = args.output / channel
            folder.mkdir()
            if sess is None:
                sess = RoboDojoSession(env, args.output / 'native', 'general_pickup')
                sess.reset(0, 'tcp_axis_diagnostic', 'tcp-world-pitchX-rollY-v1')
            kin = sess.kinematics
            robot = kin.robots['right']
            key = kin.manager.robot_key[kin.manager.robot_list.index(robot)]
            limits = key.data.soft_joint_pos_limits[0, robot.arm_joint_indices].cpu().numpy()
            base = kin.root('right')
            fk = kin.fk['right']
            q0 = np.array(sess.obs['states'][7:13], float)
            initial_q = q0 if initial_q is None else initial_q
            save(folder / 'initial_robot_geometry.json', dict(joints=q0, root=base, soft_limits=limits))

            def tcp_pose(q):
                t = base @ fk.matrix(q)
                t[:3, 3] += t[:3, :3] @ tcp_offset
                return t

            def solve(position, rotation, seed):
                def residual(q):
                    t = tcp_pose(q)
                    return np.r_[t[:3, 3] - position, .15 * R.from_matrix(rotation @ t[:3, :3].T).as_rotvec()]
                fit = least_squares(residual, seed, bounds=(limits[:, 0] + 1e-5, limits[:, 1] - 1e-5),
                                    max_nfev=350, ftol=1e-10, xtol=1e-10, gtol=1e-10)
                actual = tcp_pose(fit.x)
                if np.linalg.norm(actual[:3, 3] - position) > .0003 or R.from_matrix(rotation @ actual[:3, :3].T).magnitude() > .002:
                    raise ValueError('Requested robot-only TCP pose not reachable')
                return fit.x

            def goal(start, name):
                t = start.copy()
                if name in ('x', 'y', 'z'):
                    t['xyz'.index(name), 3] += .05
                else:
                    axis = {'yaw': 2, 'pitch': 0, 'roll': 1}[name]
                    v = np.zeros(3); v[axis] = np.deg2rad(30)
                    t[:3, :3] = R.from_rotvec(v).as_matrix() @ t[:3, :3]
                return t

            if common is None:
                rotation = R.from_quat([-.5, .5, .5, .5]).as_matrix()
                options = []
                for position in ([.22, -.15, .95], [.22, -.15, .90], [.25, -.20, .95]):
                    for seed in (np.array([.262, 1.76, 1.826, -1.637, 0., .262]), q0):
                        try:
                            q = solve(np.asarray(position), rotation, np.clip(seed, limits[:, 0] + .001, limits[:, 1] - .001))
                            t = tcp_pose(q)
                            targets = {n: solve(goal(t, n)[:3, 3], goal(t, n)[:3, :3], q) for n in ('x','y','z','yaw','pitch','roll')}
                            options.append((float(np.linalg.norm(q-q0)), q, t, targets))
                        except ValueError:
                            pass
                if not options:
                    raise RuntimeError('No common reachable six-axis starting pose')
                _, common_q, common, all_targets = min(options, key=lambda x: x[0])
                save(args.output / 'planned_robot_geometry.json', dict(tcp_offset_link6_m=tcp_offset,
                    common_q=common_q, common_tcp=common, roots=dict(right=base),
                    all_targets_q=all_targets, rotation_axes_world=dict(yaw='Z',pitch='X',roll='Y'),
                    use='robot-only kinematic targets; not executed evidence'))
                print('COMMON_POSE_READY', common[:3, 3].tolist(), flush=True)

            left = np.array(sess.obs['states'][:7], float)
            grip = float(sess.obs['states'][13])
            def step(q):
                action = np.r_[left, q, grip]
                sess.chunk_step([action])

            # Native joint playback with <=0.035 rad per commanded joint increment.
            count = max(1, int(np.ceil(np.max(abs(common_q-q0)) / .035)))
            for alpha in np.linspace(0, 1, count + 1)[1:]:
                step(q0 + alpha * (common_q-q0))
            for _ in range(12): step(common_q)

            def measured():
                p = np.asarray(sess.obs['eef_positions'][1], float)
                r = R.from_quat(np.asarray(sess.obs['eef_quaternions_wxyz'][1])[[1,2,3,0]]).as_matrix()
                t = np.eye(4); t[:3,:3] = r; t[:3,3] = p + r @ tcp_offset
                return t
            start = measured()
            if np.linalg.norm(start[:3,3]-common[:3,3]) > .002:
                raise RuntimeError('Physical common start was not reached')
            target = goal(start, channel)
            # Dense IK path follows a Cartesian line / fixed-TCP rotation, not joint interpolation.
            trajectory = []
            seed = np.asarray(sess.obs['states'][7:13], float)
            for alpha in np.linspace(0, 1, 61)[1:]:
                pos = start[:3,3] + alpha * (target[:3,3]-start[:3,3])
                dr = R.from_matrix(target[:3,:3] @ start[:3,:3].T).as_rotvec()
                rot = R.from_rotvec(alpha*dr).as_matrix() @ start[:3,:3]
                seed = solve(pos, rot, seed)
                trajectory.append(seed)
            try:
                font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 20)
                small = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 16)
            except OSError:
                font, small = ImageFont.load_default(size=20), ImageFont.load_default(size=16)
            writer = imageio.get_writer(str(args.output / (channel + '_positive.mp4')), fps=25,
                codec='libx264', pixelformat='yuv420p', macro_block_size=2,
                output_params=['-movflags', '+faststart'])
            frames_log = []
            def record(phase):
                t = measured(); dp = (t[:3,3]-start[:3,3])*1000
                rv = np.rad2deg(R.from_matrix(t[:3,:3] @ start[:3,:3].T).as_rotvec())
                canvas = Image.new('RGB', (1440, 570), '#111827')
                d = ImageDraw.Draw(canvas)
                title = channel.upper() + (' +50 mm' if channel in 'xyz' else ' +30 deg about WORLD ' + {'yaw':'Z','pitch':'X','roll':'Y'}[channel])
                d.text((18,12),'RoboDojo TCP / RIGHT ARM / '+title+' / '+phase,font=font,fill='white')
                for i,cam in enumerate(CAMERAS):
                    im=Image.fromarray(sess.obs[cam]).resize((480,360))
                    canvas.paste(im,(i*480,60))
                    d.text((i*480+10,430),cam,font=small,fill='white')
                d.text((18,468),'Measured TCP displacement XYZ [mm]: '+np.array2string(dp,precision=2),font=font,fill='#fbbf24')
                d.text((18,502),'Measured world rotation vector XYZ [deg]: '+np.array2string(rv,precision=2),font=font,fill='#93c5fd')
                d.text((18,538),'World +Y: forward from bases | +X: right | +Z: up | yaw:+Z pitch:+X roll:+Y',font=small,fill='white')
                writer.append_data(np.asarray(canvas))
                frames_log.append(dict(phase=phase,step=sess.step_id,tcp=t))
                return canvas
            for _ in range(25): record('START')
            for q in trajectory:
                step(q); record('MOVE')
            for _ in range(15):
                step(trajectory[-1]); record('SETTLE')
            for _ in range(25): record('END')
            writer.close()
            end = measured()
            pos_error = float(np.linalg.norm(end[:3,3]-target[:3,3]))
            rot_error = float(R.from_matrix(target[:3,:3] @ end[:3,:3].T).magnitude())
            row = dict(channel=channel,initial_tcp=start,target_tcp=target,final_tcp=end,
                measured_displacement_m=end[:3,3]-start[:3,3],
                measured_rotation_vector_world_deg=np.rad2deg(R.from_matrix(end[:3,:3] @ start[:3,:3].T).as_rotvec()),
                target_position_error_m=pos_error,target_rotation_error_deg=np.rad2deg(rot_error),
                passed=bool(pos_error<.002 and rot_error<np.deg2rad(1)),native_steps=sess.step_id,
                video=channel+'_positive.mp4')
            save(folder/'measurement.json',row);save(folder/'video_frames.json',frames_log)
            records.append(row);save(args.output/'measurements.json',records)
            print('AXIS_COMPLETED',channel,'position_error_mm',pos_error*1000,'rotation_error_deg',np.rad2deg(rot_error),flush=True)
        sess._write_summary('axis_demonstration_not_benchmark_evaluation')
        if not all(r['passed'] for r in records):
            raise RuntimeError('One or more physical axis demonstrations missed their target')
        print('ALL_SIX_AXES_VERIFIED',flush=True)
    except BaseException:
        import traceback
        (args.output/'error.txt').write_text(traceback.format_exc())
        traceback.print_exc()
        raise
    finally:
        if env: env.close()
        app.close()


if __name__ == '__main__':
    main()

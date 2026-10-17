"""Six independent native OSC motion demonstrations, without model calls."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--libero-root', required=True)
    parser.add_argument('--size', type=int, default=512)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    cache = out / 'cache'
    cache.mkdir()
    os.environ.update(LIBERO_CONFIG_PATH=args.libero_root+'/.libero-config',
                      MUJOCO_GL='egl', MUJOCO_EGL_DEVICE_ID='0',
                      TMPDIR=str(cache), XDG_CACHE_HOME=str(cache))
    sys.path.insert(0, args.libero_root)
    import numpy as np
    from scipy.spatial.transform import Rotation as Rot
    from PIL import Image, ImageDraw, ImageFont
    from libero.libero import benchmark
    from libero.libero.envs.env_wrapper import ControlEnv
    from robosuite.utils.camera_utils import get_camera_intrinsic_matrix, get_camera_extrinsic_matrix

    def save(path, data):
        path.write_text(json.dumps(data, indent=2)+'\n')

    suite = benchmark.get_benchmark_dict()['libero_goal'](0)
    env = ControlEnv(bddl_file_name=suite.get_task_bddl_file_path(1144),
                     camera_names=['agentview', 'robot0_eye_in_hand'],
                     camera_heights=args.size, camera_widths=args.size,
                     camera_depths=False, control_freq=20, horizon=600,
                     controller='OSC_POSE', initialization_noise=None)
    native = env.env
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 22)
    small = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 17)
    specs = [('x', 0, False), ('y', 1, False), ('z', 2, False),
             ('yaw', 2, True), ('pitch', 1, True), ('roll', 0, True)]
    summaries = []
    first_pose = None
    combined = []
    for name, axis, rotate in specs:
        env.seed(0)
        env.reset()
        obs = env.set_init_state(np.asarray(suite.get_task_init_states(1144)[7], float))
        for _ in range(10):
            obs, _, _, _ = env.step(np.array([0., 0, 0, 0, 0, 0, -1]))
        robot = native.robots[0]
        site_id = robot.eef_site_id

        def pose():
            return (native.sim.data.site_xpos[site_id].copy(),
                    native.sim.data.site_xmat[site_id].reshape(3, 3).copy())

        p0, R0 = pose()
        if first_pose is None:
            first_pose = (p0.copy(), R0.copy())
            pads = {}
            for side in ('left_fingerpad', 'right_fingerpad'):
                pads[side] = [native.sim.data.geom_xpos[native.sim.model.geom_name2id(n)].tolist()
                              for n in robot.gripper.important_geoms[side]]
            midpoint = np.mean([np.mean(pads[s], axis=0) for s in pads], axis=0)
            metadata = dict(task=1144, init=7, seed=0, cameras=['agentview', 'robot0_eye_in_hand'],
                gripper=type(robot.gripper).__name__, grip_site=robot.gripper.important_sites['grip_site'],
                grip_site_start=p0.tolist(), grip_site_rotation=R0.tolist(),
                observation_quat_xyzw=obs['robot0_eef_quat'].tolist(),
                site_vs_observation_rotation_deg=float(np.linalg.norm(Rot.from_matrix(
                    R0 @ Rot.from_quat(obs['robot0_eef_quat']).as_matrix().T).as_rotvec())*180/np.pi),
                pad_geometry_centres=pads, pad_midpoint_offset_world_m=(midpoint-p0).tolist(),
                base_position=native.sim.data.get_body_xpos(robot.robot_model.root_body).tolist(),
                base_rotation=native.sim.data.get_body_xmat(robot.robot_model.root_body).tolist(),
                controller=dict(type=type(robot.controller).__name__,
                    output_min=robot.controller.output_min.tolist(), output_max=robot.controller.output_max.tolist()),
                source_note='Only own-robot geometry, proprioception and RGB; no scene-object state.',
                rotation_semantics='world rotation vector; yaw=rz, pitch=ry, roll=rx; no Euler sequence')
            save(out/'setup.json', metadata)
            print(json.dumps(metadata), flush=True)
        reset_dp = float(np.linalg.norm(p0-first_pose[0]))
        reset_dr = float(np.linalg.norm(Rot.from_matrix(R0@first_pose[1].T).as_rotvec()))
        assert reset_dp < 1e-8 and reset_dr < 1e-8, (reset_dp, reset_dr)
        directory = out/name
        directory.mkdir()
        axis_vector = np.eye(3)[axis]
        target_p = p0 if rotate else p0 + .05*axis_vector
        target_R = Rot.from_rotvec(axis_vector*np.pi/6).as_matrix()@R0 if rotate else R0
        records, frames = [], []

        def record(step, action):
            p, R = pose()
            row = dict(step=step, time_s=step/20, grip_site_position=p.tolist(),
                grip_site_rotation=R.tolist(), delta_world_mm=((p-p0)*1000).tolist(),
                delta_rotvec_world_deg=(Rot.from_matrix(R@R0.T).as_rotvec()*180/np.pi).tolist(),
                action=action, obs_eef_pos=obs['robot0_eef_pos'].tolist(),
                obs_eef_quat_xyzw=obs['robot0_eef_quat'].tolist())
            records.append(row)
            canvas = Image.new('RGB', (1024, 700), '#10202b')
            draw = ImageDraw.Draw(canvas)
            title = f'+{name.upper()}: '+('30 degrees about world '+ 'XYZ'[axis] if rotate else '50 mm along world '+'XYZ'[axis])
            draw.text((18, 10), title, font=font, fill='white')
            draw.text((18, 43), 'Independent reset; identical start. Red=X, green=Y, blue=Z. White ring=OSC grip_site.', font=small, fill='white')
            for column, camera in enumerate(('agentview', 'robot0_eye_in_hand')):
                image = Image.fromarray(np.ascontiguousarray(obs[camera+'_image'][::-1])).resize((512,512))
                raw_dir = directory/camera
                raw_dir.mkdir(exist_ok=True)
                image.save(raw_dir/f'{step:04d}.png')
                di = ImageDraw.Draw(image)
                K = get_camera_intrinsic_matrix(native.sim, camera, args.size, args.size)
                T = np.linalg.inv(get_camera_extrinsic_matrix(native.sim, camera))

                def pixel(point):
                    q = T[:3,:3]@point+T[:3,3]
                    if q[2] <= 0:
                        return None
                    v = K@q
                    return tuple((v[:2]/v[2]).tolist())

                center = pixel(p)
                if center is not None:
                    for a, color in enumerate(('#ff5656','#50ef70','#64a8ff')):
                        end = pixel(p+np.eye(3)[a]*.06)
                        if end:
                            di.line([center,end], fill=color, width=3)
                            di.text(end, '+'+'XYZ'[a], fill=color, font=small)
                    x,y = center
                    di.ellipse((x-6,y-6,x+6,y+6), outline='white', width=2)
                canvas.paste(image,(column*512,85))
                draw.text((column*512+12,65), camera, font=small, fill='white')
            draw.text((18,610), f'Actual displacement [X,Y,Z] mm: '+str([round(v,2) for v in row['delta_world_mm']]), font=font, fill='white')
            draw.text((18,640), f'Actual world rotvec [Rx,Ry,Rz] deg: '+str([round(v,2) for v in row['delta_rotvec_world_deg']]), font=font, fill='white')
            draw.text((18,673), f'Native physical step {step}; 20 Hz. Overlays are diagnostic, not policy input.', font=small, fill='white')
            frames.append(canvas)

        record(0, None)
        for step in range(1, 81):
            t = min(step/40, 1.)
            progress = t*t*(3-2*t)
            desired_p = p0 + (target_p-p0)*progress
            desired_R = Rot.from_rotvec(axis_vector*np.pi/6*progress).as_matrix()@R0 if rotate else R0
            p,R = pose()
            dp = .7*(desired_p-p)
            dr = .7*Rot.from_matrix(desired_R@R.T).as_rotvec()
            # Bound native target updates: <=10mm and <=0.10rad per policy step.
            dp *= min(1., .01/max(np.linalg.norm(dp), 1e-12))
            dr *= min(1., .10/max(np.linalg.norm(dr), 1e-12))
            action = np.r_[dp/.05, dr/.5, -1.]
            assert np.max(np.abs(action)) <= 1.
            obs, _, _, _ = env.step(action)
            record(step, action.tolist())
        p,R = pose()
        result = dict(channel=name, world_axis='XYZ'[axis], is_rotation=rotate,
            target_displacement_mm=((target_p-p0)*1000).tolist(),
            measured_displacement_mm=((p-p0)*1000).tolist(),
            measured_rotation_vector_deg=(Rot.from_matrix(R@R0.T).as_rotvec()*180/np.pi).tolist(),
            endpoint_position_error_mm=float(np.linalg.norm(target_p-p)*1000),
            endpoint_orientation_error_deg=float(np.linalg.norm(Rot.from_matrix(target_R@R.T).as_rotvec())*180/np.pi),
            max_position_drift_mm=float(max(np.linalg.norm(np.array(r['delta_world_mm'])) for r in records)) if rotate else None,
            reset_position_difference_m=reset_dp, reset_rotation_difference_rad=reset_dr)
        save(directory/'metrics.json', result)
        (directory/'robot_trace.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
        summaries.append(result)
        print(json.dumps(result), flush=True)
        # Native steps at real 20Hz; repeat only the endpoints for readable pauses.
        sequence = [frames[0]]*20 + frames[1:] + [frames[-1]]*20
        with (directory/'ffmpeg.log').open('w') as log:
            command = ['ffmpeg','-hide_banner','-loglevel','warning','-nostdin','-f','rawvideo',
                '-pixel_format','rgb24','-video_size','1024x700','-framerate','20','-i','pipe:0',
                '-an','-c:v','libx264','-threads','2','-preset','veryfast','-crf','20',
                '-pix_fmt','yuv420p','-movflags','+faststart',str(directory/(name+'.mp4'))]
            child = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
            for frame in sequence:
                child.stdin.write(frame.tobytes())
            child.stdin.close()
            if child.wait():
                raise RuntimeError('Encoder failed')
        frames[0].save(directory/'start.png')
        frames[-1].save(directory/'end.png')
        combined.append(directory/(name+'.mp4'))
    env.close()
    save(out/'metrics.json', summaries)
    listing = out/'concat.txt'
    listing.write_text(''.join("file '"+str(p)+"'\n" for p in combined))
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','warning','-nostdin','-f','concat','-safe','0',
                    '-i',str(listing),'-c','copy','-movflags','+faststart',str(out/'six_independent_motions.mp4')], check=True)
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-i',str(out/'six_independent_motions.mp4'),
                    '-f','null','-'], check=True)
    print('SIX_MOTIONS_COMPLETE', flush=True)


if __name__ == '__main__':
    main()

"""One ledgered Goal episode with fixed local RGB-D perception and runtime Jev.

No automatic retry: every setup or control failure consumes one shared task
attempt. Use a detached project worktree to keep the policy commit immutable.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

SIM_PYTHON = os.environ.get(
    'JEV_RSI_SIM_PYTHON',
    '/root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python')
RECOVERY_TASKS = {1163, 1335, 1458}
SUPERVISOR_TASKS = {1144, 1252, 1423}
KNOB_TASKS = {1383}
DRAWER_TASKS = {1098, 1202}
PUSH_TASKS = {1296}
POLICY_FILES = (
    'run_libero_goal_jev.py',
    'run_position_pilot.py',
    'libero_jev_rollout.py', 'libero_generic_vision.py',
    'libero_goal_local_vision.py', 'libero_grounding_worker.py',
    'local_rgbd_perception.py',
    'libero_jev_recovery.py', 'libero_jev_supervisor.py',
    'libero_robot_geometry.py',
    'libero_goal_rack_geometry.py',
    'libero_goal_knob_vision.py', 'libero_goal_knob_control.py',
    'libero_goal_plate_vision.py', 'libero_goal_drawer_control.py',
    'libero_goal_drawer_vision.py',
    'libero_push_control.py',
    'libero_ten_task_workflows.py',
)


def launch_command(source, task_id, init_index, episode, mode, grasp_profile,
                   approach_mode, entry_side, grasp_hold_ticks, drawer_contact_mode,
                   plate_stage_turn_deg, lift_recheck_mm=0, side_pad_overlap_mm=0,
                   rim_height_mode='top_overlap', rim_tilt_deg=0, rim_axis='short',
                   rim_inset_mm=0,
                   drawer_preorient=False, drawer_clear_to_source=False,
                   empty_hand_fast=False, support_stall_release=False,
                   plate_coast_gate=False, plate_final_overshoot_mm=0,
                   plate_front_margin_px=0, plate_second_rim_contact=False,
                   plate_second_rim_hover_gate=False,
                   plate_second_visible_contact_gate=False,
                   plate_second_preserve_downward=False,
                   plate_second_line_step=False):
    cmd = [SIM_PYTHON, '-B', str(source/'libero_jev_rollout.py'),
           '--suite', 'libero_goal', '--task-id', str(task_id),
           '--init-index', str(init_index), '--camera-size', '768',
           '--max-jev-decisions', '240' if mode == 'push' or task_id == 1202 else '160',
           '--wall-limit-seconds', '1200',
           '--output', str(episode)]
    if mode in ('recovery', 'supervisor'):
        cmd += ['--local-goal-vision', '--geometry-profile', 'observed_surfaces']
    if mode == 'recovery':
        cmd += ['--recovery-supervisor', '--input-organization', 'focused',
                '--grasp-algorithm', 'pad_fit', '--preserve-source',
                '--allow-retry', '--execution-profile', 'adaptive']
        if task_id == 1163:
            cmd += ['--carry-route', 'lateral_first', '--visible-goal-check',
                    '--grasp-hold-ticks', str(grasp_hold_ticks)]
            if lift_recheck_mm:
                cmd += ['--lift-recheck-mm', str(lift_recheck_mm)]
        if task_id == 1458:
            cmd += ['--visible-goal-check']
            if lift_recheck_mm:
                cmd += ['--lift-recheck-mm', str(lift_recheck_mm)]
    elif mode == 'supervisor':
        cmd += ['--jev-supervisor', '--schema', 'focused']
        if task_id == 1423:
            cmd += ['--placement-height-mode', 'occlusion_guarded_bottom']
            if support_stall_release:
                cmd += ['--support-stall-release']
            cmd += ['--grasp-profile', grasp_profile,
                    '--approach-mode', approach_mode,
                    '--entry-side', entry_side]
            if side_pad_overlap_mm:
                cmd += ['--side-pad-overlap-mm', str(side_pad_overlap_mm)]
    elif mode == 'knob':
        cmd += ['--knob-supervisor']
    elif mode == 'push':
        cmd += ['--push-supervisor', '--goal-plate-push']
        if plate_stage_turn_deg:
            cmd += ['--plate-stage-turn-deg', str(plate_stage_turn_deg)]
        if plate_coast_gate:
            cmd += ['--plate-coast-gate']
        if plate_final_overshoot_mm:
            cmd += ['--plate-final-overshoot-mm', str(plate_final_overshoot_mm)]
        if plate_front_margin_px:
            cmd += ['--plate-front-margin-px', str(plate_front_margin_px)]
        if plate_second_rim_contact:
            cmd += ['--plate-second-rim-contact']
        if plate_second_rim_hover_gate:
            cmd += ['--plate-second-rim-hover-gate']
        if plate_second_visible_contact_gate:
            cmd += ['--plate-second-visible-contact-gate']
        if plate_second_preserve_downward:
            cmd += ['--plate-second-preserve-downward']
        if plate_second_line_step:
            cmd += ['--plate-second-line-step']
    else:
        cmd += ['--drawer-supervisor', '--drawer-contact-mode', drawer_contact_mode]
        if task_id == 1202:
            cmd += ['--drawer-bowl-continuation', '--local-goal-vision',
                    '--geometry-profile', 'observed_surfaces',
                    '--input-organization', 'focused',
                    '--grasp-algorithm', 'pad_fit', '--preserve-source',
                    '--execution-profile', 'adaptive', '--allow-retry']
            if rim_height_mode != 'top_overlap':
                cmd += ['--rim-height-mode', rim_height_mode]
            if rim_tilt_deg:
                cmd += ['--rim-tilt-deg', str(rim_tilt_deg)]
            if rim_axis != 'short':
                cmd += ['--rim-axis', rim_axis]
            if rim_inset_mm:
                cmd += ['--rim-inset-mm', str(rim_inset_mm)]
            if drawer_preorient:
                cmd += ['--drawer-preorient']
            if drawer_clear_to_source:
                cmd += ['--drawer-clear-to-source']
            if empty_hand_fast:
                cmd += ['--empty-hand-fast']
    return cmd


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--task-id', type=int, required=True)
    p.add_argument('--init-index', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--egl-device-id', type=int, choices=range(8), default=5)
    p.add_argument('--worker-device-id', type=int, choices=range(8), default=6)
    p.add_argument('--allow-shared-gpu', action='store_true',
                   help='Allow EGL and the vision worker on one GPU; report this resource choice')
    p.add_argument('--cpu-vision', action='store_true',
                   help='Run only local DINO/SAM perception on CPU when CUDA model loading is unavailable')
    p.add_argument('--grasp-profile', choices=['edge','center_if_width_fits'], default='edge')
    p.add_argument('--approach-mode', choices=['top','angled','side'], default='top')
    p.add_argument('--entry-side', choices=['robot_side','receiver_side'], default='robot_side')
    p.add_argument('--grasp-hold-ticks', type=int, choices=[18,24,30,36,42,48], default=18)
    p.add_argument('--lift-recheck-mm', type=int, choices=[0,30], default=0)
    p.add_argument('--side-pad-overlap-mm', type=int, choices=[0,12], default=0)
    p.add_argument('--drawer-contact-mode', choices=['pinch', 'hook', 'top_hook', 'under_hook', 'side_hook', 'tip_hook'],
                   default='top_hook')
    p.add_argument('--rim-height-mode', choices=['top_overlap','visible_sidewall'],
                   default='top_overlap')
    p.add_argument('--rim-tilt-deg', type=int, choices=[0,12,20], default=0)
    p.add_argument('--rim-axis', choices=['short','long'], default='short')
    p.add_argument('--rim-inset-mm', type=int, choices=[0,2,4], default=0)
    p.add_argument('--drawer-preorient', action='store_true')
    p.add_argument('--drawer-clear-to-source', action='store_true')
    p.add_argument('--empty-hand-fast', action='store_true')
    p.add_argument('--support-stall-release', action='store_true')
    p.add_argument('--plate-stage-turn-deg', type=int, choices=[0, 9, 15], default=0)
    p.add_argument('--plate-coast-gate', action='store_true',
                   help='Offer Jev an RGB-only plate coast prediction to end the first push')
    p.add_argument('--plate-final-overshoot-mm', type=int, choices=[0, 10], default=0)
    p.add_argument('--plate-front-margin-px', type=int, choices=[0, 3], default=0)
    p.add_argument('--plate-second-rim-contact', action='store_true')
    p.add_argument('--plate-second-rim-hover-gate', action='store_true')
    p.add_argument('--plate-second-visible-contact-gate', action='store_true',
                   help='Offer Jev a bounded plate-rim contact trial from public RGB-D and own finger feedback')
    p.add_argument('--plate-second-preserve-downward', action='store_true',
                   help='Preserve the own downward wrist on the second rim-push segment')
    p.add_argument('--plate-second-line-step', action='store_true',
                   help='Scale planar Jev-directed push steps with one shared error-proportional gain')
    p.add_argument('--dry-run', action='store_true',
                   help='Print exact launch command without a reservation or filesystem write')
    p.add_argument('--preflight-only', action='store_true',
                   help='Check selected GPU and EGL rendering without reserving an attempt')
    a = p.parse_args()
    if a.dry_run and a.preflight_only:
        p.error('Choose either --dry-run or --preflight-only')
    if a.task_id not in RECOVERY_TASKS | SUPERVISOR_TASKS | KNOB_TASKS | DRAWER_TASKS | PUSH_TASKS or not 0 <= a.init_index < 50:
        p.error('Unsupported Goal task or official init index')
    if a.egl_device_id == a.worker_device_id and not a.allow_shared_gpu:
        p.error('Use --allow-shared-gpu to select the same GPU for EGL and vision')
    repo = Path(__file__).resolve().parents[2]
    source = Path(__file__).resolve().parent
    out = a.output.resolve()
    if not out.is_relative_to(repo/'code/runs') or out.exists():
        p.error('Output must be a new directory under project code/runs')
    mode = ('push' if a.task_id in PUSH_TASKS else
            'drawer' if a.task_id in DRAWER_TASKS else
            'knob' if a.task_id in KNOB_TASKS else
            'recovery' if a.task_id in RECOVERY_TASKS else 'supervisor')
    if a.grasp_profile != 'edge' and a.task_id != 1423:
        p.error('Local grasp profile is currently evaluated only for Goal 1423')
    if a.approach_mode != 'top' and a.task_id != 1423:
        p.error('Alternative approach mode is currently evaluated only for Goal 1423')
    if a.entry_side != 'robot_side' and (a.task_id != 1423 or a.approach_mode == 'top'):
        p.error('Receiver entry side requires an angled or side Goal 1423 approach')
    if a.grasp_hold_ticks != 18 and a.task_id != 1163:
        p.error('Extended closure is currently evaluated only for Goal 1163')
    if a.lift_recheck_mm and a.task_id not in (1163, 1458):
        p.error('Extended lift recheck is currently evaluated only for Goal 1163/1458')
    if a.side_pad_overlap_mm and (a.task_id != 1423 or
                                   a.approach_mode != 'angled' or
                                   a.entry_side != 'receiver_side'):
        p.error('Side pad overlap currently requires angled receiver-side Goal 1423')
    if a.drawer_contact_mode != 'top_hook' and a.task_id not in (1098, 1202):
        p.error('Alternative drawer entry requires a supported drawer task')
    if a.drawer_contact_mode in ('side_hook', 'tip_hook') and a.task_id != 1098:
        p.error('Middle-handle entry mode requires Goal 1098')
    if a.rim_height_mode != 'top_overlap' and a.task_id != 1202:
        p.error('Alternative rim height requires Goal 1202')
    if a.rim_tilt_deg and a.task_id != 1202:
        p.error('Rim tilt requires Goal 1202')
    if a.rim_axis != 'short' and a.task_id != 1202:
        p.error('Alternative rim axis requires Goal 1202')
    if a.rim_inset_mm and a.task_id != 1202:
        p.error('Rim inset requires Goal 1202')
    if a.drawer_preorient and a.task_id != 1202:
        p.error('Drawer preorientation requires Goal 1202')
    if a.drawer_clear_to_source and a.task_id != 1202:
        p.error('Drawer clear-to-source requires Goal 1202')
    if a.empty_hand_fast and a.task_id != 1202:
        p.error('Empty-hand fast profile requires Goal 1202')
    if a.support_stall_release and a.task_id != 1423:
        p.error('Guarded support release trial currently requires Goal 1423')
    if a.plate_stage_turn_deg and a.task_id != 1296:
        p.error('Alternative plate stage is currently evaluated only for Goal 1296')
    if a.plate_coast_gate and a.task_id != 1296:
        p.error('Plate coast gate requires Goal 1296')
    if (a.plate_final_overshoot_mm or a.plate_front_margin_px or
            a.plate_second_rim_contact or a.plate_second_rim_hover_gate or
            a.plate_second_visible_contact_gate or a.plate_second_preserve_downward or
            a.plate_second_line_step) and a.task_id != 1296:
        p.error('Plate final clearance parameters require Goal 1296')
    if a.plate_second_rim_hover_gate and not a.plate_second_rim_contact:
        p.error('Second rim hover gate requires second rim contact')
    if a.plate_second_visible_contact_gate and not (a.plate_second_rim_contact and
                                                    a.plate_second_rim_hover_gate):
        p.error('Visible contact gate requires the second rim and hover gates')
    if a.plate_second_preserve_downward and not a.plate_second_rim_contact:
        p.error('Preserved downward wrist requires second rim contact')
    cmd = launch_command(source,a.task_id,a.init_index,out/'episode',mode,
                         a.grasp_profile,a.approach_mode,a.entry_side,a.grasp_hold_ticks,
                         a.drawer_contact_mode,a.plate_stage_turn_deg,a.lift_recheck_mm,
                         a.side_pad_overlap_mm,a.rim_height_mode,a.rim_tilt_deg,a.rim_axis,
                         a.rim_inset_mm,
                         a.drawer_preorient,a.drawer_clear_to_source,
                         a.empty_hand_fast,a.support_stall_release,a.plate_coast_gate,
                         a.plate_final_overshoot_mm,a.plate_front_margin_px,
                         a.plate_second_rim_contact,a.plate_second_rim_hover_gate,
                         a.plate_second_visible_contact_gate,
                         a.plate_second_preserve_downward,
                         a.plate_second_line_step)
    if a.dry_run:
        print(json.dumps(dict(mode=mode,cmd=cmd),indent=2))
        return
    if shutil.disk_usage(repo).free < 6*1024**3:
        raise RuntimeError('Need >=6GiB project-disk space before episode')
    try:
        visible_devices = sorted({a.egl_device_id, a.worker_device_id})
        gpu_check = subprocess.run(
            ['nvidia-smi', '-i', ','.join(map(str, visible_devices)),
             '--query-gpu=index', '--format=csv,noheader,nounits'],
            capture_output=True, text=True, check=True, timeout=8)
        healthy = {int(line.strip()) for line in gpu_check.stdout.splitlines()}
        if healthy != set(visible_devices):
            raise RuntimeError(f'Selected GPUs not both available: {sorted(healthy)}')
    except (subprocess.SubprocessError, OSError) as exc:
        raise RuntimeError('Selected GPU health preflight failed before attempt reservation') from exc
    # NVML can enumerate a GPU while EGL context creation is blocked by a
    # different failed device. Exercise the same headless path before charging
    # a task attempt; the actual episode still owns its own EGL context.
    egl_probe = (
        'import mujoco; '
        'm=mujoco.MjModel.from_xml_string('
        '"<mujoco><worldbody><geom type=\\"sphere\\" size=\\"0.1\\"/>'
        '</worldbody></mujoco>"); '
        'd=mujoco.MjData(m); r=mujoco.Renderer(m,64,64); '
        'r.update_scene(d); r.render()'
    )
    probe_env = dict(os.environ, MUJOCO_GL='egl',
                     MUJOCO_EGL_DEVICE_ID=str(a.egl_device_id),
                     CUDA_VISIBLE_DEVICES=','.join(map(str, visible_devices)))
    try:
        subprocess.run([SIM_PYTHON, '-B', '-c', egl_probe], env=probe_env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, timeout=20)
    except (subprocess.SubprocessError, OSError) as exc:
        raise RuntimeError('Selected GPU EGL render preflight failed before attempt reservation') from exc
    if a.cpu_vision:
        worker_env = dict(os.environ, JEV_RSI_VISION_DEVICE='-1',
                          HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        worker_python = os.environ.get('JEV_RSI_VISION_PYTHON', SIM_PYTHON)
        try:
            worker_probe = subprocess.run(
                [worker_python, '-B', str(source/'libero_grounding_worker.py')],
                input='{"close":true}\n', capture_output=True, text=True,
                env=worker_env, check=True, timeout=90)
            if not any(json.loads(line).get('ready') for line in worker_probe.stdout.splitlines()):
                raise RuntimeError('CPU vision worker did not report ready')
        except (subprocess.SubprocessError, OSError, ValueError) as exc:
            raise RuntimeError('CPU vision worker preflight failed before attempt reservation') from exc
    if a.preflight_only:
        print(json.dumps(dict(gpu_preflight='passed',
                              egl_device_id=a.egl_device_id,
                              worker_device_id=a.worker_device_id,
                              cpu_vision=a.cpu_vision,
                              attempt_reserved=False)))
        return
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo,
                                     text=True).strip()
    hashes = {name: hashlib.sha256((source/name).read_bytes()).hexdigest()
              for name in POLICY_FILES}
    ledger = repo/'code/runs/libero-supervisor-ledger.jsonl'
    with ledger.open('a+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.seek(0)
        previous = [json.loads(line) for line in stream if line.strip()]
        count = sum(row.get('suite') == 'libero_goal' and
                    row.get('task') == a.task_id for row in previous)
        attempt_limit = 80 if a.task_id in (1098, 1202, 1296) else 50
        if count >= attempt_limit:
            raise RuntimeError(f'Task {a.task_id} already at {attempt_limit} attempts')
        reservation = dict(suite='libero_goal', task=a.task_id,
                           init=a.init_index, attempt=count+1,
                           campaign=out.name, output=str(out),
                           purpose='local_visible_jev_control',
                           model='Jev 1.13', policy_commit=commit)
        stream.write(json.dumps(reservation)+'\n')
        stream.flush()
        os.fsync(stream.fileno())
    out.mkdir()
    episode = out/'episode'  # Recorder creates this directory itself.
    manifest = dict(reservation=reservation, mode=mode,
                    grasp_profile=a.grasp_profile,
                    approach_mode=a.approach_mode,
                    entry_side=a.entry_side,
                    grasp_hold_ticks=a.grasp_hold_ticks,
                    lift_recheck_mm=a.lift_recheck_mm,
                    side_pad_overlap_mm=a.side_pad_overlap_mm,
                    drawer_contact_mode=a.drawer_contact_mode,
                    plate_stage_turn_deg=a.plate_stage_turn_deg,
                    plate_coast_gate=a.plate_coast_gate,
                    plate_final_overshoot_mm=a.plate_final_overshoot_mm,
                    plate_front_margin_px=a.plate_front_margin_px,
                    plate_second_rim_contact=a.plate_second_rim_contact,
                    plate_second_rim_hover_gate=a.plate_second_rim_hover_gate,
                    plate_second_visible_contact_gate=a.plate_second_visible_contact_gate,
                    plate_second_preserve_downward=a.plate_second_preserve_downward,
                    plate_second_line_step=a.plate_second_line_step,
                    support_stall_release=a.support_stall_release,
                    cpu_vision=a.cpu_vision,
                    policy_source_sha256=hashes, git_commit=commit,
                    permissions='public task, rendered RGB-D and calibration, own robot only',
                    runtime_gpt6_calls=0, runtime_deepseek_calls=0,
                    outcome='evaluate only after final robot action')
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    env = dict(os.environ, MUJOCO_EGL_DEVICE_ID=str(a.egl_device_id),
               CUDA_VISIBLE_DEVICES=','.join(map(str, visible_devices)),
               JEV_RSI_VISION_DEVICE=('-1' if a.cpu_vision else
                                      str(visible_devices.index(a.worker_device_id))),
               JEV_RSI_MODEL_BACKEND='jev')
    env.pop('JEV_RSI_JEV_PROXY', None)
    env.pop('JEV_RSI_VISION_PROXY', None)
    start = time.monotonic()
    with (out/'launcher.log').open('w') as log:
        try:
            done = subprocess.run(cmd, env=env, stdout=log,
                                  stderr=subprocess.STDOUT, timeout=1400)
            returncode, termination = done.returncode, None
        except subprocess.TimeoutExpired:
            returncode, termination = 124, '1400s launcher timeout'
    result_file = episode/'result.json'
    result = json.loads(result_file.read_text()) if result_file.exists() else dict(
        success=False, error='No terminal result; inspect launcher.log')
    row = dict(reservation=reservation, returncode=returncode,
               termination=termination, seconds=round(time.monotonic()-start, 3),
               result=result)
    (out/'launcher-result.json').write_text(json.dumps(row, indent=2)+'\n')
    print(json.dumps(row), flush=True)


if __name__ == '__main__':
    main()

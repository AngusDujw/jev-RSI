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

SIM_PYTHON = '/root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python'
RECOVERY_TASKS = {1163, 1335, 1458}
SUPERVISOR_TASKS = {1144, 1252, 1423}
KNOB_TASKS = {1383}
DRAWER_TASKS = {1098, 1202}
PUSH_TASKS = {1296}
POLICY_FILES = (
    'run_libero_goal_jev.py',
    'libero_jev_rollout.py', 'libero_generic_vision.py',
    'libero_goal_local_vision.py', 'libero_grounding_worker.py',
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
                   plate_stage_turn_deg, lift_recheck_mm=0, side_pad_overlap_mm=0):
    cmd = [SIM_PYTHON, '-B', str(source/'libero_jev_rollout.py'),
           '--suite', 'libero_goal', '--task-id', str(task_id),
           '--init-index', str(init_index), '--camera-size', '768',
           '--max-jev-decisions', '240' if mode == 'push' else '160',
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
    elif mode == 'supervisor':
        cmd += ['--jev-supervisor', '--schema', 'focused']
        if task_id == 1423:
            cmd += ['--placement-height-mode', 'occlusion_guarded_bottom']
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
    else:
        cmd += ['--drawer-supervisor', '--drawer-contact-mode', drawer_contact_mode]
    return cmd


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--task-id', type=int, required=True)
    p.add_argument('--init-index', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--egl-device-id', type=int, choices=range(8), default=5)
    p.add_argument('--worker-device-id', type=int, choices=range(8), default=6)
    p.add_argument('--grasp-profile', choices=['edge','center_if_width_fits'], default='edge')
    p.add_argument('--approach-mode', choices=['top','angled','side'], default='top')
    p.add_argument('--entry-side', choices=['robot_side','receiver_side'], default='robot_side')
    p.add_argument('--grasp-hold-ticks', type=int, choices=[18,24,30,36,42,48], default=18)
    p.add_argument('--lift-recheck-mm', type=int, choices=[0,30], default=0)
    p.add_argument('--side-pad-overlap-mm', type=int, choices=[0,12], default=0)
    p.add_argument('--drawer-contact-mode', choices=['top_hook', 'under_hook'],
                   default='top_hook')
    p.add_argument('--plate-stage-turn-deg', type=int, choices=[0, 9], default=0)
    p.add_argument('--dry-run', action='store_true',
                   help='Print exact launch command without a reservation or filesystem write')
    a = p.parse_args()
    if a.task_id not in RECOVERY_TASKS | SUPERVISOR_TASKS | KNOB_TASKS | DRAWER_TASKS | PUSH_TASKS or not 0 <= a.init_index < 50:
        p.error('Unsupported Goal task or official init index')
    if a.egl_device_id == a.worker_device_id:
        p.error('Simulator and local grounding worker need distinct visible devices')
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
    if a.lift_recheck_mm and a.task_id != 1163:
        p.error('Extended lift recheck is currently evaluated only for Goal 1163')
    if a.side_pad_overlap_mm and (a.task_id != 1423 or
                                   a.approach_mode != 'angled' or
                                   a.entry_side != 'receiver_side'):
        p.error('Side pad overlap currently requires angled receiver-side Goal 1423')
    if a.drawer_contact_mode != 'top_hook' and a.task_id != 1098:
        p.error('Alternative drawer entry is currently evaluated only for Goal 1098')
    if a.plate_stage_turn_deg and a.task_id != 1296:
        p.error('Alternative plate stage is currently evaluated only for Goal 1296')
    cmd = launch_command(source,a.task_id,a.init_index,out/'episode',mode,
                         a.grasp_profile,a.approach_mode,a.entry_side,a.grasp_hold_ticks,
                         a.drawer_contact_mode,a.plate_stage_turn_deg,a.lift_recheck_mm,
                         a.side_pad_overlap_mm)
    if a.dry_run:
        print(json.dumps(dict(mode=mode,cmd=cmd),indent=2))
        return
    if shutil.disk_usage(repo).free < 6*1024**3:
        raise RuntimeError('Need >=6GiB project-disk space before episode')
    try:
        subprocess.run(['nvidia-smi', '-L'], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True, timeout=8)
    except (subprocess.SubprocessError, OSError) as exc:
        raise RuntimeError('GPU health preflight failed before attempt reservation') from exc
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
        if count >= 50:
            raise RuntimeError(f'Task {a.task_id} already at 50 attempts')
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
                    policy_source_sha256=hashes, git_commit=commit,
                    permissions='public task, rendered RGB-D and calibration, own robot only',
                    runtime_gpt6_calls=0, runtime_deepseek_calls=0,
                    outcome='evaluate only after final robot action')
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    env = dict(os.environ, MUJOCO_EGL_DEVICE_ID=str(a.egl_device_id),
               CUDA_VISIBLE_DEVICES=f'{a.egl_device_id},{a.worker_device_id}',
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

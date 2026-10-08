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
POLICY_FILES = (
    'libero_jev_rollout.py', 'libero_generic_vision.py',
    'libero_goal_local_vision.py', 'libero_grounding_worker.py',
    'libero_jev_recovery.py', 'libero_jev_supervisor.py',
    'libero_robot_geometry.py',
    'libero_goal_knob_vision.py', 'libero_goal_knob_control.py',
    'libero_goal_plate_vision.py', 'libero_goal_drawer_control.py',
    'libero_ten_task_workflows.py',
)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--task-id', type=int, required=True)
    p.add_argument('--init-index', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--egl-device-id', type=int, choices=range(8), default=5)
    p.add_argument('--worker-device-id', type=int, choices=range(8), default=6)
    a = p.parse_args()
    if a.task_id not in RECOVERY_TASKS | SUPERVISOR_TASKS | KNOB_TASKS or not 0 <= a.init_index < 50:
        p.error('Unsupported Goal task or official init index')
    if a.egl_device_id == a.worker_device_id:
        p.error('Simulator and local grounding worker need distinct visible devices')
    repo = Path(__file__).resolve().parents[2]
    source = Path(__file__).resolve().parent
    out = a.output.resolve()
    if not out.is_relative_to(repo/'code/runs') or out.exists():
        p.error('Output must be a new directory under project code/runs')
    if shutil.disk_usage(repo).free < 6*1024**3:
        raise RuntimeError('Need >=6GiB project-disk space before episode')
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
    mode = ('knob' if a.task_id in KNOB_TASKS else
            'recovery' if a.task_id in RECOVERY_TASKS else 'supervisor')
    manifest = dict(reservation=reservation, mode=mode,
                    policy_source_sha256=hashes, git_commit=commit,
                    permissions='public task, rendered RGB-D and calibration, own robot only',
                    runtime_gpt6_calls=0, runtime_deepseek_calls=0,
                    outcome='evaluate only after final robot action')
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    cmd = [SIM_PYTHON, '-B', str(source/'libero_jev_rollout.py'),
           '--suite', 'libero_goal', '--task-id', str(a.task_id),
           '--init-index', str(a.init_index), '--camera-size', '768',
           '--local-goal-vision', '--geometry-profile', 'observed_surfaces',
           '--max-jev-decisions', '160', '--wall-limit-seconds', '1200',
           '--output', str(episode)]
    if mode == 'recovery':
        cmd += ['--recovery-supervisor', '--input-organization', 'focused',
                '--grasp-algorithm', 'pad_fit', '--preserve-source',
                '--allow-retry', '--execution-profile', 'adaptive']
        if a.task_id == 1163:
            cmd += ['--carry-route', 'lateral_first', '--visible-goal-check']
    elif mode == 'supervisor':
        cmd += ['--jev-supervisor', '--schema', 'focused']
        if a.task_id == 1423:
            cmd += ['--placement-height-mode', 'occlusion_guarded_bottom']
    else:
        cmd += ['--knob-supervisor']
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

"""Replay one archived Jev decision and measure paired local LIBERO XYZ steps.

Development diagnostic only: the Jev decision and visible target come from an
archived rollout, not a fresh model call. Every amplitude starts from the same
official initial state and repeats the archived pre-decision robot command.
This measures a single frozen approach state, not task completion.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time

import numpy as np


LIBERO_ROOT = '/root/yekangjie/project/embodied-jev/.sim/LIBERO-plus'
AMPLITUDES_M = (0., 0.001, 0.002, 0.005, 0.010)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def source_case(run_root, task, init, state):
    if task == 'bowl':
        folder = run_root / '2026-10-02-libero-wrist-frozen20' / f'init-{init:02d}'
        suite_name, task_id, index = 'libero_spatial', 988, init
        decisions = [row for row in read_jsonl(folder / 'decisions.jsonl') if row['stage'] == 'approach']
        decision = (decisions[0] if state == 'far' else min(
            (row for row in decisions if row['metrics']['error_norm_m'] >= .006),
            key=lambda row: abs(row['metrics']['error_norm_m']-.015)))
        prefix = [row for row in read_jsonl(folder / 'branches.jsonl')
                  if row['decision_id'] < decision['decision_id']]
        position = decision['observation']['position_m']
        target = decision['observation']['target_position_m']
        gripper = -1
    else:
        folder = run_root / '2026-10-03-libero-recovery30-focused-v1' / f'libero_object-1066-init-{init}'
        suite_name, task_id, index = 'libero_object', 1066, init
        decisions = read_jsonl(folder / 'decisions.jsonl')
        approaches = [row for row in decisions if row['stage'] == 'approach']
        decision = (approaches[0] if state == 'far' else min(
            (row for row in approaches if row['metrics']['error_norm_m'] >= .006),
            key=lambda row: abs(row['metrics']['error_norm_m']-.015)))
        prefix = [row for row in read_jsonl(folder / 'branches.jsonl') if row['decision_id'] < decision['decision_id']]
        axes = decision['observation']['translation_axes']
        position = [axes[a]['current_coordinate_m'] for a in 'xyz']
        target = [axes[a]['goal_coordinate_m'] for a in 'xyz']
        gripper = -1
    if decision['stage'] != 'approach':
        raise ValueError('Expected archived approach decision')
    cfg = json.loads((folder / 'protocol.json').read_text())
    files = [folder / 'decisions.jsonl', folder / 'branches.jsonl', folder / 'protocol.json']
    return dict(folder=folder, suite=suite_name, task_id=task_id, init_index=index,
                seed=cfg['seed'], decision_id=decision['decision_id'],
                signs=np.asarray(decision['signs'], dtype=float),
                position=np.asarray(position, dtype=float), target=np.asarray(target, dtype=float),
                prefix=prefix, gripper=gripper, state=state,
                sha256={str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in files})


def make_env(case):
    sys.path.insert(0, LIBERO_ROOT)
    from libero.libero import benchmark
    from libero.libero.envs.env_wrapper import ControlEnv
    with contextlib.redirect_stdout(io.StringIO()):
        suite = benchmark.get_benchmark_dict()[case['suite']](0)
    env = ControlEnv(bddl_file_name=suite.get_task_bddl_file_path(case['task_id']),
                     camera_names=['agentview', 'robot0_eye_in_hand'],
                     camera_heights=384, camera_widths=384, camera_depths=True,
                     control_freq=20, horizon=600, controller='OSC_POSE',
                     initialization_noise=None)
    env.seed(case['seed'])
    return env, np.asarray(suite.get_task_init_states(case['task_id'])[case['init_index']], float)


def reset_to_decision(env, initial, case):
    env.reset()
    obs = env.set_init_state(initial)
    for _ in range(10):
        obs, _, _, _ = env.step(np.array([0., 0., 0., 0., 0., 0., -1.]))
    for row in case['prefix']:
        if row['stage'] not in ('select', 'approach'):
            raise ValueError('Only pre-approach archived prefix can be replayed')
        if case['suite'] == 'libero_spatial':
            block = 3
            rotation = np.zeros(3)
            gripper = -1.
        else:
            block = int(row['block_native_ticks'])
            if block not in (3, 6):
                raise ValueError('Unexpected archived action block')
            rotation = np.asarray(row['rotation_signs'], float) * np.minimum(
                .10, (.35 if block == 6 else .5) * np.abs(row['rotation_error_rad']))
            gripper = float(row['executed_gripper'])
        action = np.r_[np.asarray(row['delta'], float)/.05, rotation/.5, gripper]
        for _ in range(block):
            obs, _, _, _ = env.step(action)
        replay_error = float(np.linalg.norm(np.asarray(obs['robot0_eef_pos'])-row['after']))
        if replay_error > .005:
            raise RuntimeError(f'Archived prefix diverged {replay_error*1000:.2f} mm')
    before = np.asarray(obs['robot0_eef_pos'], float)
    mismatch = float(np.linalg.norm(before - case['position']))
    if mismatch > .005:
        raise RuntimeError(f'Archived decision state mismatch {mismatch*1000:.2f} mm > 5 mm')
    return obs, mismatch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--task', choices=('bowl', 'cheese'), required=True)
    parser.add_argument('--init', type=int, required=True)
    parser.add_argument('--state', choices=('far', 'near'), default='far')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--egl-device', type=int, default=4)
    args = parser.parse_args()
    if (args.task == 'bowl' and args.init not in range(1, 21)) or (
            args.task == 'cheese' and args.init not in (7, 8, 9)):
        parser.error('Init must be an archived frozen bowl 1–20 or focused cheese 7–9')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    cache = out / 'cache'
    cache.mkdir()
    os.environ.update(LIBERO_CONFIG_PATH=LIBERO_ROOT+'/.libero-config', MUJOCO_GL='egl',
                      MUJOCO_EGL_DEVICE_ID=str(args.egl_device), TMPDIR=str(cache),
                      XDG_CACHE_HOME=str(cache))
    case = source_case(args.run_root.resolve(), args.task, args.init, args.state)
    info = dict(task=args.task, state=args.state, suite=case['suite'], task_id=case['task_id'],
                init_index=case['init_index'], seed=case['seed'],
                archived_decision=case['decision_id'], archived_signs=case['signs'].astype(int).tolist(),
                archived_position_m=case['position'].tolist(), target_m=case['target'].tolist(),
                amplitudes_m=AMPLITUDES_M, action_ticks=3,
                source_sha256=case['sha256'], model_calls=0,
                note='Existing Jev sign; same official init per branch; local approach step only')
    write_json(out / 'protocol.json', info)
    started = time.monotonic()
    rows = []
    env = None
    try:
        env, initial = make_env(case)
        unit = case['signs'] / np.linalg.norm(case['signs'])
        for amplitude in AMPLITUDES_M:
            obs, mismatch = reset_to_decision(env, initial, case)
            before = np.asarray(obs['robot0_eef_pos'], float)
            command = unit * amplitude
            action = np.r_[command/.05, np.zeros(3), case['gripper']]
            for _ in range(3):
                obs, _, _, _ = env.step(action)
            after = np.asarray(obs['robot0_eef_pos'], float)
            e0 = float(np.linalg.norm(case['target']-before))
            e1 = float(np.linalg.norm(case['target']-after))
            row = dict(amplitude_m=amplitude, before_m=before.tolist(), after_m=after.tolist(),
                       command_delta_m=command.tolist(), actual_delta_m=(after-before).tolist(),
                       error_before_m=e0, error_after_m=e1, progress_m=e0-e1,
                       response_along_command=(float(np.dot(after-before, unit)/amplitude)
                                               if amplitude else None),
                       state_mismatch_m=mismatch, native_ticks=3)
            rows.append(row)
            write_json(out / 'branches.json', rows)
            print(json.dumps(dict(amplitude_m=amplitude, progress_mm=(e0-e1)*1000,
                                  state_mismatch_mm=mismatch*1000)), flush=True)
        write_json(out / 'result.json', dict(status='completed', wall_seconds=time.monotonic()-started,
                                           branch_count=len(rows), model_calls=0))
    except Exception as exc:
        write_json(out / 'result.json', dict(status='crashed', wall_seconds=time.monotonic()-started,
                                           branch_count=len(rows), error_type=type(exc).__name__,
                                           error=str(exc), model_calls=0))
        raise
    finally:
        if env is not None:
            env.close()


if __name__ == '__main__':
    main()

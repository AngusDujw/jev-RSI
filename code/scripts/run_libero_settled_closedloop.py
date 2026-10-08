"""Fixed-goal local closed loops from independently replayed settled states.

The shared scalar step rule is the existing distance_step baseline, capped at
the largest probed amplitude (10 mm). This entry evaluates Jev direction with
adaptive and fixed amplitudes, and direct error signs with adaptive amplitude.
Each arm starts from the same official init and is measured after settling.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

import numpy as np

from reliability_step import distance_step
from run_libero_settled_step import direct_signs, fixed_state, select_case, settle
from run_libero_step_response import make_env, source_case, write_json
from run_position_pilot import Jev, Recorder


MAX_ATTEMPTS = 4
STEP_CAP_M = .010
STEP_GAIN = .7  # Pre-existing distance_step default; not fitted to these held-out states.
FIXED_STEP_M = .005
TOLERANCE_M = {'bowl': .004, 'cheese': .002}


def action_for(error, signs, policy):
    if policy == 'jev_fixed':
        norm = float(np.linalg.norm(signs))
        return np.asarray(signs, float) * FIXED_STEP_M / norm if norm else np.zeros(3)
    return np.asarray(distance_step(error, signs, cap=STEP_CAP_M, gain=STEP_GAIN)['delta_m'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', required=True, type=Path)
    parser.add_argument('--task', required=True, choices=tuple(TOLERANCE_M))
    parser.add_argument('--init', required=True, type=int)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--egl-device', type=int, default=1)
    args = parser.parse_args()
    if (args.task == 'bowl' and args.init not in range(1, 21)) or (
            args.task == 'cheese' and args.init not in (7, 8, 9)):
        parser.error('Init must have an archived frozen trajectory')
    out = args.output.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    cfg = dict(existing_root='/root/yekangjie/project/robodojo-jev',
               api_config='/root/yekangjie/project/robodojo-jev/controller/config/api.company.local.json',
               wall_limit_seconds=900, output_limit_mb=100, max_jev_decisions=8,
               task=args.task, init=args.init, coordinate_frame='world_cartesian_m',
               policies=['jev_adaptive', 'jev_fixed', 'direct_adaptive'],
               max_attempts=MAX_ATTEMPTS, step_cap_m=STEP_CAP_M, step_gain=STEP_GAIN,
               fixed_step_m=FIXED_STEP_M, hold_tolerance_m=TOLERANCE_M[args.task],
               target_radius_m=TOLERANCE_M[args.task], action_ticks=3,
               goal_source='Archived task-specific visible RGB-D target, fixed',
               interpretation='Local approach target, not whole-task success')
    rec = Recorder(out, cfg)
    cache = out / 'cache'
    cache.mkdir()
    os.environ.update(LIBERO_CONFIG_PATH='/root/yekangjie/project/embodied-jev/.sim/LIBERO-plus/.libero-config',
                      MUJOCO_GL='egl', MUJOCO_EGL_DEVICE_ID=str(args.egl_device),
                      TMPDIR=str(cache), XDG_CACHE_HOME=str(cache))
    env = model = None
    started = time.monotonic()
    try:
        first = source_case(args.run_root.resolve(), args.task, args.init, 'pre_near')
        env, initial = make_env(first)
        case, reference, pre_settle, attempts = select_case(
            env, initial, args.run_root.resolve(), args.task, args.init)
        write_json(out / 'candidate_states.json', attempts)
        if case is None:
            write_json(out / 'result.json', dict(status='no_eligible_settled_state',
                                                 jev_calls=0, arms=[]))
            rec.finish('no_eligible_settled_state')
            return
        write_json(out / 'selected_state.json', dict(
            task=args.task, init=args.init, source_decision=case['decision_id'],
            source_sha256=case['sha256'], target_m=case['target'].tolist(),
            start_position_m=reference.tolist(), start_error_m=float(np.linalg.norm(case['target']-reference)),
            pre_settle=pre_settle))
        outcomes = []
        for policy in cfg['policies']:
            obs, replay_error, _ = fixed_state(env, initial, case, pre_settle['ticks'], reference)
            if replay_error > .0001:
                raise RuntimeError('Start state mismatch')
            if policy.startswith('jev') and model is None:
                model = Jev(rec)
            positions = [np.asarray(obs['robot0_eef_pos'], float).tolist()]
            status = 'attempt_budget'
            for attempt in range(MAX_ATTEMPTS):
                rec.check_budget()
                before = np.asarray(obs['robot0_eef_pos'], float)
                error = case['target']-before
                before_norm = float(np.linalg.norm(error))
                if before_norm <= cfg['target_radius_m']:
                    status = 'reached'
                    break
                choice = None
                if policy.startswith('jev'):
                    state = dict(task=case['task_text'], stage='approach',
                                 position_m=before.tolist(), target_position_m=case['target'].tolist(),
                                 hold_tolerance_m=cfg['hold_tolerance_m'],
                                 coordinate_frame='world_cartesian_m',
                                 observation_source='Archived RGB-D goal + live settled robot feedback',
                                 stage_source='externally fixed approach stage',
                                 target_source='Archived visible RGB-D goal, fixed during trial',
                                 orientation_instruction='keep fixed', gripper='open', history=[])
                    choice = model.choose(state, dict(stage='approach', policy=policy,
                                                      attempt=attempt, init=args.init))
                    if choice is None:
                        status = 'model_call_budget'
                        break
                    signs = np.asarray(choice['signs'], int)
                else:
                    signs = direct_signs(error, cfg['hold_tolerance_m'])
                delta = action_for(error, signs, policy)
                if not np.any(delta):
                    status = 'all_hold'
                    rec.branch(dict(policy=policy, attempt=attempt, signs=signs.tolist(),
                                    decision_id=choice['decision_id'] if choice else None,
                                    before_m=before.tolist(), error_before_m=before_norm,
                                    command_delta_m=delta.tolist(), outcome='all_hold'))
                    break
                action = np.r_[delta/.05, np.zeros(3), -1.]
                for _ in range(cfg['action_ticks']):
                    obs, _, _, _ = env.step(action)
                obs, final_settle = settle(env, obs)
                after = np.asarray(obs['robot0_eef_pos'], float)
                after_norm = float(np.linalg.norm(case['target']-after))
                rec.branch(dict(policy=policy, attempt=attempt, signs=signs.tolist(),
                                decision_id=choice['decision_id'] if choice else None,
                                before_m=before.tolist(), after_m=after.tolist(),
                                error_before_m=before_norm, error_after_m=after_norm,
                                command_delta_m=delta.tolist(), actual_delta_m=(after-before).tolist(),
                                progress_m=before_norm-after_norm, final_settle=final_settle,
                                outcome='reached' if after_norm <= cfg['target_radius_m'] else 'continue'))
                positions.append(after.tolist())
                if not final_settle['stable']:
                    status = 'not_stable'
                    break
                if after_norm <= cfg['target_radius_m']:
                    status = 'reached'
                    break
            final_error = float(np.linalg.norm(case['target']-np.asarray(obs['robot0_eef_pos'], float)))
            outcome = dict(policy=policy, status=status, final_error_m=final_error,
                           attempts=sum(r['policy'] == policy and r.get('after_m') is not None for r in rec.rows),
                           jev_calls=sum(d.get('policy') == policy for d in rec.decisions),
                           positions_m=positions)
            outcomes.append(outcome)
            write_json(out / 'result.json', dict(status='running', arms=outcomes,
                                                 jev_calls=len(rec.decisions)))
            print(json.dumps(outcome), flush=True)
        write_json(out / 'result.json', dict(status='completed', arms=outcomes,
                                             jev_calls=len(rec.decisions),
                                             wall_seconds=time.monotonic()-started))
        rec.finish('completed')
    except Exception as exc:
        write_json(out / 'result.json', dict(status='crashed', error_type=type(exc).__name__,
                                             error=str(exc), jev_calls=len(rec.decisions),
                                             wall_seconds=time.monotonic()-started))
        rec.finish('crashed')
        raise
    finally:
        if model is not None:
            model.close()
        if env is not None:
            env.close()


if __name__ == '__main__':
    main()

"""Paired XYZ step response at settled, fixed-goal LIBERO approach states.

Replay archived task-specific RGB-D goals and physical prefixes. Stop the robot,
then make one fresh Jev XYZ request using the same coordinate-only prompt on both
tasks. Compare its signs with direct target-error signs at the same state. Each
amplitude is executed from a separately reset identical state and observed only
after another measured settling period. This is local response, not task success.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import time

import numpy as np

from run_libero_step_response import make_env, reset_to_decision, source_case, write_json
from run_position_pilot import Jev, Recorder


AMPLITUDES_M = (0., .001, .002, .005, .010)
SOURCE_CANDIDATES = (('near', .015), ('pre_near', .040),
                     ('pre_near', .055), ('pre_near', .070))
STABLE_SPEED_M_S = .001
STABLE_ANGULAR_SPEED_RAD_S = .01
CONTROL_SECONDS = .05
STABLE_STREAK = 3
MAX_SETTLE_TICKS = 80


def unit_quaternion_angle(first, second):
    a = np.asarray(first, float)
    b = np.asarray(second, float)
    return 2*math.acos(float(np.clip(abs(np.dot(a, b)/(np.linalg.norm(a)*np.linalg.norm(b))), 0, 1)))


def settle(env, obs, *, exact_ticks=None):
    """Zero-translation command until 3 consecutive low-speed 20 Hz steps."""
    position = np.asarray(obs['robot0_eef_pos'], float)
    quaternion = np.asarray(obs['robot0_eef_quat'], float)
    speeds, angular_speeds = [], []
    count = exact_ticks if exact_ticks is not None else MAX_SETTLE_TICKS
    for tick in range(count):
        obs, _, _, _ = env.step(np.array([0., 0., 0., 0., 0., 0., -1.]))
        new_position = np.asarray(obs['robot0_eef_pos'], float)
        new_quaternion = np.asarray(obs['robot0_eef_quat'], float)
        speeds.append(float(np.linalg.norm(new_position-position)/CONTROL_SECONDS))
        angular_speeds.append(unit_quaternion_angle(quaternion, new_quaternion)/CONTROL_SECONDS)
        position, quaternion = new_position, new_quaternion
        if (exact_ticks is None and len(speeds) >= STABLE_STREAK and
            all(s <= STABLE_SPEED_M_S for s in speeds[-STABLE_STREAK:]) and
            all(s <= STABLE_ANGULAR_SPEED_RAD_S for s in angular_speeds[-STABLE_STREAK:])):
            break
    stable = (len(speeds) >= STABLE_STREAK and
              all(s <= STABLE_SPEED_M_S for s in speeds[-STABLE_STREAK:]) and
              all(s <= STABLE_ANGULAR_SPEED_RAD_S for s in angular_speeds[-STABLE_STREAK:]))
    return obs, dict(stable=stable, ticks=len(speeds),
                     last_speed_m_s=speeds[-1], last_angular_speed_rad_s=angular_speeds[-1],
                     max_last3_speed_m_s=max(speeds[-STABLE_STREAK:]),
                     max_last3_angular_speed_rad_s=max(angular_speeds[-STABLE_STREAK:]))


def direct_signs(error, tolerance):
    return np.where(np.abs(error) <= tolerance, 0, np.sign(error)).astype(int)


def select_case(env, initial, run_root, task, init):
    attempts = []
    seen = set()
    for source_state, desired_error in SOURCE_CANDIDATES:
        case = source_case(run_root, task, init, source_state, target_error_m=desired_error)
        if case['decision_id'] in seen:
            continue
        seen.add(case['decision_id'])
        obs, mismatch = reset_to_decision(env, initial, case)
        obs, settling = settle(env, obs)
        position = np.asarray(obs['robot0_eef_pos'], float)
        error = case['target']-position
        remaining = float(np.linalg.norm(error))
        attempt = dict(archived_decision=case['decision_id'], source_state=source_state,
                       desired_error_m=desired_error,
                       archived_error_m=float(np.linalg.norm(case['target']-case['position'])),
                       replay_mismatch_m=mismatch, settled_error_m=remaining,
                       settled_position_m=position.tolist(), **settling)
        attempts.append(attempt)
        if settling['stable'] and .006 <= remaining <= .040:
            return case, position, settling, attempts
    return None, None, None, attempts


def fixed_state(env, initial, case, stable_ticks, reference):
    obs, mismatch = reset_to_decision(env, initial, case)
    obs, settling = settle(env, obs, exact_ticks=stable_ticks)
    position = np.asarray(obs['robot0_eef_pos'], float)
    equal = float(np.linalg.norm(position-reference))
    if mismatch > .005 or equal > .0001 or not settling['stable']:
        raise RuntimeError(f'Paired state not reproduced: position {equal*1000:.3f} mm, '
                           f'archived {mismatch*1000:.3f} mm, stable={settling["stable"]}')
    return obs, equal, settling


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', required=True, type=Path)
    parser.add_argument('--task', required=True, choices=('bowl', 'cheese'))
    parser.add_argument('--init', required=True, type=int)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--egl-device', type=int, default=1)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    if (args.task == 'bowl' and args.init not in range(1, 21)) or (
            args.task == 'cheese' and args.init not in (7, 8, 9)):
        parser.error('Init must be an archived frozen bowl 1–20 or focused cheese 7–9')
    out = args.output.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    cfg = dict(existing_root='/root/yekangjie/project/robodojo-jev',
               api_config='/root/yekangjie/project/robodojo-jev/controller/config/api.company.local.json',
               wall_limit_seconds=900, output_limit_mb=100, max_jev_decisions=1,
               task=args.task, init=args.init, prepare_only=args.prepare_only,
               coordinate_frame='world_cartesian_m', native_dt_s=CONTROL_SECONDS,
               action_ticks=3, amplitudes_m=AMPLITUDES_M,
               stable_speed_m_s=STABLE_SPEED_M_S,
               stable_angular_speed_rad_s=STABLE_ANGULAR_SPEED_RAD_S,
               stable_streak=STABLE_STREAK, max_settle_ticks=MAX_SETTLE_TICKS,
               candidate_archived_states=SOURCE_CANDIDATES,
               goal_source='Archived task-specific RGB-D approach target, held fixed',
               observation_permission='Archived RGB-D goal and own robot feedback; no scene truth/reward',
               interpretation='Development local response, not complete manipulation')
    rec = Recorder(out, cfg)
    cache = out/'cache'
    cache.mkdir()
    os.environ.update(LIBERO_CONFIG_PATH='/root/yekangjie/project/embodied-jev/.sim/LIBERO-plus/.libero-config',
                      MUJOCO_GL='egl', MUJOCO_EGL_DEVICE_ID=str(args.egl_device),
                      TMPDIR=str(cache), XDG_CACHE_HOME=str(cache))
    env = None
    model = None
    started = time.monotonic()
    try:
        first = source_case(args.run_root.resolve(), args.task, args.init, 'pre_near')
        env, initial = make_env(first)
        case, position, pre_settle, attempts = select_case(
            env, initial, args.run_root.resolve(), args.task, args.init)
        write_json(out/'candidate_states.json', attempts)
        if case is None:
            write_json(out/'result.json', dict(status='no_eligible_settled_state',
                                               candidate_count=len(attempts), model_calls=0))
            rec.finish('no_eligible_settled_state')
            return
        tolerance = .004 if args.task == 'bowl' else .002
        error = case['target']-position
        direct = direct_signs(error, tolerance)
        metadata = dict(source_decision=case['decision_id'], source_sha256=case['sha256'],
                        task=args.task, init=args.init, settled_position_m=position.tolist(),
                        target_m=case['target'].tolist(), error_m=error.tolist(),
                        error_norm_m=float(np.linalg.norm(error)), direct_signs=direct.tolist(),
                        pre_settle=pre_settle,
                        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],
                                                           cwd=Path(__file__).resolve().parents[2],
                                                           text=True).strip())
        write_json(out/'selected_state.json', metadata)
        if args.prepare_only:
            write_json(out/'result.json', dict(status='prepared', model_calls=0,
                                               selected_error_m=metadata['error_norm_m']))
            rec.finish('prepared')
            return
        state = dict(task=case['task_text'], stage='approach',
                     position_m=position.tolist(), target_position_m=case['target'].tolist(),
                     hold_tolerance_m=tolerance, coordinate_frame='world_cartesian_m',
                     observation_source='Archived task-specific RGB-D goal + live settled robot position',
                     stage_source='externally fixed approach stage',
                     target_source='Archived visible RGB-D goal, fixed during paired trial',
                     orientation_instruction='keep fixed', gripper='open', history=[])
        model = Jev(rec)
        choice = model.choose(state, dict(stage='approach', environment='libero_plus',
                                          init=args.init, trial='settled_step_response'))
        jev = np.asarray(choice['signs'], int)
        policies = dict(jev=jev, direct=direct)
        write_json(out/'direction_comparison.json', dict(jev=jev.tolist(), direct=direct.tolist(),
                                                        same=bool(np.array_equal(jev, direct)),
                                                        answers=choice['answers'],
                                                        request_seconds=choice['request_seconds']))
        rows = []
        for policy, signs in policies.items():
            if policy == 'direct' and np.array_equal(jev, direct):
                continue
            norm = float(np.linalg.norm(signs))
            amplitudes = AMPLITUDES_M if policy == 'jev' else AMPLITUDES_M[1:]
            for amplitude in amplitudes:
                obs, equal, _ = fixed_state(env, initial, case, pre_settle['ticks'], position)
                before = np.asarray(obs['robot0_eef_pos'], float)
                command = np.asarray(signs, float)*amplitude/norm if norm else np.zeros(3)
                action = np.r_[command/.05, np.zeros(3), -1.]
                for _ in range(3):
                    obs, _, _, _ = env.step(action)
                obs, final_settle = settle(env, obs)
                after = np.asarray(obs['robot0_eef_pos'], float)
                row = dict(policy=policy, amplitude_m=amplitude,
                           command_delta_m=command.tolist(), before_m=before.tolist(),
                           after_m=after.tolist(), actual_delta_m=(after-before).tolist(),
                           error_before_m=float(np.linalg.norm(case['target']-before)),
                           error_after_m=float(np.linalg.norm(case['target']-after)),
                           progress_m=float(np.linalg.norm(case['target']-before)-
                                            np.linalg.norm(case['target']-after)),
                           position_replay_error_m=equal, start_stable=True,
                           final_settle=final_settle, command_ticks=3)
                rows.append(row)
                write_json(out/'paired_branches.json', rows)
                print(json.dumps(dict(policy=policy, amplitude_m=amplitude,
                                      progress_mm=row['progress_m']*1000,
                                      settled=final_settle['stable'])), flush=True)
        write_json(out/'result.json', dict(status='completed', branch_count=len(rows),
                                          jev_calls=1, directions_equal=bool(np.array_equal(jev,direct)),
                                          all_final_stable=all(r['final_settle']['stable'] for r in rows),
                                          wall_seconds=time.monotonic()-started))
        rec.finish('completed')
    except Exception as exc:
        write_json(out/'result.json', dict(status='crashed', error_type=type(exc).__name__,
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

"""Fresh staged MuJoCo local rollouts with real Jev calls and frozen step rules.

Each policy starts from the same full state, then queries Jev on its own states.
Scaffold trajectories and local reaching success are not whole-task success.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
from run_position_pilot import Recorder, Jev, dump, freeze_world, motion, state_for


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seed', type=int, default=40)
    a = p.parse_args()
    cfg = json.loads(a.config.read_text())
    cfg.update(seed=a.seed, max_jev_decisions=1080, step_rollout_limit=60,
               policies=['distance_07', 'stage_gain', 'feedback'], cap_m=.01,
               stage_gain=dict(approach=1., descend=1., lift=.7, carry=1., lower=1., withdraw=1.))
    sys.path.insert(0, '/root/yekangjie/project/embodied-jev/src')
    from embodied_jev.physics import RobotWorld
    from embodied_jev.planning import baseline_phase, candidates
    rec = Recorder(a.output, cfg)
    dump(rec.folder/'provenance.json', dict(command=sys.argv, python=sys.executable,
        commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()))
    world = RobotWorld('stack', seed=a.seed)
    model = Jev(rec)
    status, failures = 'completed', 0
    results = []
    try:
        for phase_index in range(20):
            stage = baseline_phase(world)
            if stage == 'finish':
                break
            option = candidates(world, stage, preview=False)[0]
            moving = stage in cfg['stage_gain']
            sample = None
            start = world.steps
            ticks = max(1, int(option.seconds/.002))
            for _ in world.motion(option.target, option.gripper, option.seconds, emit=False):
                if moving and sample is None and world.steps-start >= ticks*.5:
                    sample = world.clone()
            if sample is None:
                continue
            prepared = motion(sample, sample.position.copy(), cfg)
            if not prepared['stable']:
                raise RuntimeError('Initial state did not settle')
            target = np.asarray(option.target)
            for policy in cfg['policies']:
                w = sample.clone()
                folder = rec.folder/f'{phase_index:02d}-{stage}-{policy}'
                folder.mkdir()
                freeze_world(w, folder)
                before_calls = len(rec.decisions)
                scale, progress_streak = 1., 0
                success = False
                previous = []
                for step in range(cfg['step_rollout_limit']):
                    rec.check_budget()
                    error = target-w.position
                    if np.max(np.abs(error)) <= cfg['axis_tolerance_m']:
                        success = True
                        break
                    state = state_for(w.position, target, stage, cfg,
                        gripper='closed' if w.closed else 'open',
                        orientation_matrix=w.data.site_xmat[w.tcp].reshape(3, 3).tolist())
                    decision = model.choose(state, dict(stage=stage, seed=a.seed, policy=policy,
                        phase_index=phase_index, rollout_step=step, environment='embodied-jev',
                        trajectory_id=folder.name))
                    freeze_world(w, rec.folder/decision['decision_id'])
                    vector = np.asarray(decision['signs'], float)
                    norm = np.linalg.norm(vector)
                    if norm:
                        vector /= norm
                    gain = cfg['stage_gain'][stage] if policy == 'stage_gain' else .7
                    amplitude = min(cfg['cap_m'], gain*np.linalg.norm(error))*scale
                    before = float(np.linalg.norm(error))
                    outcome = motion(w, w.position+amplitude*vector, cfg)
                    after = float(np.linalg.norm(target-w.position))
                    row = dict(kind='local_closedloop', stage=stage, policy=policy,
                        decision_id=decision['decision_id'], amplitude_m=float(amplitude),
                        goal_error_before_m=before, goal_error_after_m=after,
                        scale_before=scale, **outcome)
                    if policy == 'feedback':
                        if after > before+1e-6:
                            scale, progress_streak = max(.125, scale*.5), 0
                        elif before-after > 1e-6:
                            progress_streak += 1
                            if progress_streak >= 2:
                                scale = min(1.5, scale*1.2)
                                progress_streak = 0
                        else:
                            progress_streak = 0
                    row['scale_next'] = scale
                    rec.branch(row)
                    previous.append(row)
                    if not outcome['stable'] or outcome['forbidden_contacts']:
                        break
                success = bool(np.max(np.abs(target-w.position)) <= cfg['axis_tolerance_m'] and
                               all(r['stable'] and not r['forbidden_contacts'] for r in previous))
                result = dict(stage=stage, policy=policy, seed=a.seed, local_success=success,
                    jev_calls=len(rec.decisions)-before_calls, initial_error_m=float(np.linalg.norm(target-sample.position)),
                    final_error_m=float(np.linalg.norm(target-w.position)),
                    worsening_steps=sum(r['goal_error_after_m']>r['goal_error_before_m']+1e-6 for r in previous),
                    scope='local stage reaching, not complete manipulation')
                results.append(result)
                dump(folder/'result.json', result)
                dump(rec.folder/'rollouts.json', results)
                print(json.dumps(result), flush=True)
                failures = 0 if success else failures+1
                if failures >= 3:
                    status = 'stopped_three_consecutive_nonconverged'
                    return
    except Exception as exc:
        status = 'failed'
        rec.errors.append(dict(type=type(exc).__name__, error=str(exc)))
        raise
    finally:
        model.close()
        rec.finish(status)


if __name__ == '__main__':
    main()

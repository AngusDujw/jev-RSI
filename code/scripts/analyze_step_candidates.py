"""Select only previously executed amplitude branches; never claim closed-loop results.

The entire source batch has already been inspected. The seed split below is a
development split, not an untouched final test set. Runtime selectors use only
current observed distance/stage, never a branch's future outcome.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

AMPLITUDES = (0., .001, .002, .005, .01)


def select(row, gain=None, fixed=None):
    obs = row['observation']
    error = [t-x for t, x in zip(obs['target_position_m'], obs['position_m'])]
    if max(map(abs, error)) <= obs['hold_tolerance_m']:
        return 0.
    if fixed is not None:
        return fixed
    distance = math.sqrt(sum(e*e for e in error))
    return max(a for a in AMPLITUDES if a <= gain*distance)


def evaluate(samples, selector):
    result = dict(states=len(samples), reached_before=0, rejected=0,
                  stalled_outside_tolerance=0, progress=0, worsened=0,
                  unstable=0, forbidden_contacts=0, executed=0,
                  active_progress=0, active_worsened=0, reached_state_drift_count=0)
    normalized, deltas, selected = [], [], defaultdict(int)
    for row, branches in samples:
        amp = selector(row)
        branch = branches[amp]
        selected[str(amp)] += 1
        reached = select(row, fixed=.001) == 0
        result['reached_before'] += reached
        result['stalled_outside_tolerance'] += amp == 0 and not reached
        before = branch['goal_error_before_m']
        if 'goal_error_after_m' not in branch:
            result['rejected'] += 1
            normalized.append(-1.)
            continue
        after = branch['goal_error_after_m']
        result['executed'] += 1
        result['unstable'] += not branch['stable']
        result['forbidden_contacts'] += bool(branch.get('forbidden_contacts'))
        delta = after-before
        result['progress'] += delta < -1e-6
        result['worsened'] += delta > 1e-6
        result['active_progress'] += not reached and delta < -1e-6
        result['active_worsened'] += not reached and delta > 1e-6
        result['reached_state_drift_count'] += reached and abs(delta) > 1e-6
        deltas.append(delta*1000)
        # Shared reaching gate; below-tolerance drift is not fitted as progress.
        normalized.append(0. if reached else max(-1., min(1., (before-after)/max(before, .0005))))
    result.update(mean_normalized_progress=sum(normalized)/len(samples),
                  mean_delta_mm_executed=sum(deltas)/len(deltas) if deltas else None,
                  selected_amplitudes_m=dict(selected))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    samples, hashes = [], {}
    for file in sorted(a.root.rglob('decisions.jsonl')):
        branches_file = file.with_name('branches.jsonl')
        groups = defaultdict(dict)
        for line in branches_file.read_text().splitlines():
            b = json.loads(line)
            if b.get('kind') == 'amplitude':
                if not b['reset_identical']:
                    raise ValueError('Unpaired branch')
                groups[b['decision_id']][b['amplitude_m']] = b
        for line in file.read_text().splitlines():
            r = json.loads(line)
            if set(groups[r['decision_id']]) != set(AMPLITUDES):
                raise ValueError('Incomplete amplitude grid')
            samples.append((r, groups[r['decision_id']]))
        for f in (file, branches_file):
            hashes[str(f)] = hashlib.sha256(f.read_bytes()).hexdigest()
    fit = [s for s in samples if 10 <= s[0]['seed'] < 30]
    validation = [s for s in samples if 30 <= s[0]['seed'] < 40]
    if len(fit) != 600 or len(validation) != 300:
        raise ValueError('Unexpected development split')
    gains = (.1, .2, .3, .4, .5, .7, 1.)
    fitted, search = {}, {}
    for stage in sorted({r['stage'] for r, _ in fit}):
        subset = [s for s in fit if s[0]['stage'] == stage]
        results = {g: evaluate(subset, lambda r, g=g: select(r, gain=g)) for g in gains}
        # No rejected/unstable/forbidden branches allowed in development fit.
        eligible = [g for g in gains if not any(results[g][k] for k in ('rejected', 'unstable', 'forbidden_contacts'))]
        if not eligible:
            raise ValueError(f'No eligible gain for {stage}')
        fitted[stage] = max(eligible, key=lambda g: (results[g]['mean_normalized_progress'], -g))
        search[stage] = results
    selectors = {f'fixed_{a*1000:g}mm_with_shared_stop': lambda r, a=a: select(r, fixed=a) for a in AMPLITUDES[1:]}
    selectors['distance_gain_0.7_grid'] = lambda r: select(r, gain=.7)
    selectors['distance_gain_1.0_grid'] = lambda r: select(r, gain=1.)
    selectors['fitted_stage_distance_grid'] = lambda r: select(r, gain=fitted[r['stage']])
    result = dict(scope='Offline paired single-step branch selection, already-inspected development data; NOT closed-loop or new simulation.',
                  fit_seeds=list(range(10, 30)), development_validation_seeds=list(range(30, 40)),
                  selection_rule='floor gain*observed_error_norm to measured 0/1/2/5/10mm grid; shared per-axis reaching gate',
                  progress_threshold_m=1e-6, fitted_gains=fitted, fit_search=search,
                  metrics={split: {name: evaluate(rows, fn) for name, fn in selectors.items()}
                           for split, rows in [('fit', fit), ('development_validation', validation)]},
                  source_sha256=hashes)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('x') as f:
        json.dump(result, f, indent=2)
    print(json.dumps({k: result[k] for k in ('scope', 'fitted_gains', 'metrics')}, indent=2))


if __name__ == '__main__':
    main()

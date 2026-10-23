#!/usr/bin/env python3
"""Read archived RoboICL proposals over SSH; make no model or simulator calls."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess


REMOTE = r'''
import collections
import json
import math
from pathlib import Path
import sys

root = Path('/home/ykj/project/jev-rsi-roboicl/baseline/roboicl')
payload = json.load(sys.stdin)
groups = collections.defaultdict(lambda: {'translation': [], 'rotation': [], 'rows': 0})
audits = []
rejection_details = collections.Counter()

def add(key, rows, translation_limit, rotation_limit):
    bucket = groups[key]
    for row in rows:
        assert len(row) == 14
        bucket['rows'] += 1
        for offset in (0, 7):
            bucket['translation'].append(math.sqrt(sum(v*v for v in row[offset:offset+3])) / translation_limit)
            bucket['rotation'].append(math.sqrt(sum(v*v for v in row[offset+3:offset+6])) / rotation_limit)

def read_lines(path):
    if not path.exists():
        return []
    with path.open() as handle:
        return [json.loads(line) for line in handle if line.strip()]

for case in payload['cases']:
    folder = root / case['folder']
    harness_paths = list(folder.glob('*/harness.json'))
    decision_paths = list(folder.glob('*/astra/*/decisions.jsonl'))
    assert len(harness_paths) == 1 and len(decision_paths) == 1, str(folder)
    config = json.loads(harness_paths[0].read_text())
    assert config['action_space'] == 'ee_delta'
    tl, rl = config['max_translation_m'], config['max_rotation_rad']
    decisions = read_lines(decision_paths[0])
    for rejected in read_lines(decision_paths[0].with_name('action_rejections.jsonl')):
        rejection_details[rejected.get('detail', 'unspecified')] += 1
    audit = {'folder': case['folder'], 'condition': case['condition'], 'task': case['task'],
             'translation_limit_m': tl, 'rotation_limit_rad': rl, 'decisions': len(decisions),
             'predicted_rows': sum(len(d['requested_tensor']) for d in decisions)}
    for decision in decisions:
        rows = decision['requested_tensor']
        add('all_native/predicted', rows, tl, rl)
        add(case['condition'] + '/predicted', rows, tl, rl)
        if case['condition'] == 'pure':
            add('pure/' + case['task'] + '/predicted', rows, tl, rl)
            add('pure/first_five_proposed', rows[:5], tl, rl)
    if case['condition'] == 'pure':
        receipts = read_lines(decision_paths[0].with_name('tool_results.jsonl'))
        # Released local safety holds have predicted_steps=1 and their own ledger.
        normal = [r for r in receipts if r['predicted_steps'] == 20]
        assert len(normal) == len(decisions), (str(folder), len(normal), len(decisions))
        steps = 0
        for decision, receipt in zip(decisions, normal):
            assert decision['step'] == receipt['executed_step_interval'][0]
            n = receipt['executed_steps']
            assert 0 <= n <= decision['dispatched_steps'] <= 5
            assert len(receipt['full_executed_commands_local_only']) == n
            selected = decision['requested_tensor'][:n]
            add('pure/executed', selected, tl, rl)
            add('pure/' + case['task'] + '/executed', selected, tl, rl)
            steps += n
        holds = sum(r['executed_steps'] for r in receipts if r['predicted_steps'] == 1)
        assert steps + holds <= case['robot_steps'], (str(folder), steps, holds, case['robot_steps'])
        audit.update(executed_gpt_rows=steps, local_hold_rows=holds,
                     native_steps_without_committed_receipt=case['robot_steps']-steps-holds)
    audits.append(audit)

def distribution(values):
    ordered = sorted(values)
    active = [v for v in values if v > 1e-8]
    def pct(threshold, seq):
        return 100 * sum(v >= threshold for v in seq) / len(seq) if seq else None
    def quantile(q):
        return ordered[round((len(ordered)-1)*q)] if ordered else None
    active_ordered = sorted(active)
    def moving_quantile(q):
        return active_ordered[round((len(active_ordered)-1)*q)] if active_ordered else None
    return {'arm_steps': len(values), 'moving_arm_steps': len(active),
            'p50_ratio': quantile(.5), 'p90_ratio': quantile(.9), 'p99_ratio': quantile(.99),
            'moving_p50_ratio': moving_quantile(.5), 'moving_p90_ratio': moving_quantile(.9),
            'max_ratio': max(values, default=0),
            'at_cap_count': sum(v >= 1-1e-4 for v in values),
            'at_cap_pct_all': pct(1-1e-4, values), 'at_cap_pct_moving': pct(1-1e-4, active),
            'at_least_90pct_count': sum(v >= .9 for v in values),
            'at_least_90pct_pct_all': pct(.9, values), 'at_least_90pct_pct_moving': pct(.9, active),
            'above_cap_with_validator_tolerance_count': sum(v > 1+1e-6 for v in values)}

print(json.dumps({'cases': len(audits), 'case_audits': audits,
    'rejected_action_tensors': {'count': sum(rejection_details.values()), 'details': dict(rejection_details)},
    'groups': {k: {'dual_arm_rows': v['rows'], 'translation': distribution(v['translation']),
                   'rotation': distribution(v['rotation'])} for k, v in groups.items()}}, indent=2))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='company-server-2-ykj')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    panel = repo / 'code/runs/2026-10-21-roboicl-pro-evaluation/first-native-panel.json'
    cases = json.loads(panel.read_text())
    result = subprocess.run(
        ['ssh', '-o', 'ConnectTimeout=20', '--', args.host, 'python3 -c ' + shlex.quote(REMOTE)],
        input=json.dumps({'cases': cases}), text=True, capture_output=True,
    )
    if result.returncode:
        raise SystemExit(result.stderr)
    summary = json.loads(result.stdout)
    summary['scope'] = 'First native outcome per condition/task/layout; accepted proposals only. Pure executed prefixes use committed tool receipts; native steps without a committed receipt are explicitly excluded and counted.'
    summary['thresholds'] = {'at_cap': 'norm / configured limit >= 0.9999', 'near_cap': 'norm / configured limit >= 0.90', 'moving': 'norm / configured limit > 1e-8'}
    summary['source_panel'] = str(panel.relative_to(repo))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({'cases': summary['cases'], 'groups': summary['groups']}, indent=2))


if __name__ == '__main__':
    main()

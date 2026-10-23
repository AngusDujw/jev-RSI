#!/usr/bin/env python3
"""Audit completed speed-study artifacts without model or simulator calls."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re


def lines(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def distribution(values, cap):
    active = sorted(x for x in values if x > 1e-10)
    return {
        'arm_steps': len(values), 'moving_arm_steps': len(active),
        'moving_median': active[(len(active)-1)//2] if active else None,
        'maximum': max(values, default=0), 'cap': cap,
        'at_cap': sum(x >= cap*.9999 for x in values),
        'at_least_90pct': sum(x >= cap*.9 for x in values),
    }


def audit(folder):
    case = json.loads((folder/'case.json').read_text())
    aborted = folder/'infrastructure-abort.json'
    final = (json.loads((folder/'finished.json').read_text())
             if (folder/'finished.json').exists() else
             {'native_results': [], 'returncode': None, 'wall_seconds': None})
    harness_paths = list(folder.glob('*/harness.json'))
    assert len(harness_paths) == 1, folder
    harness = json.loads(harness_paths[0].read_text())
    assert harness['action_space'] == 'ee_delta'
    trace_paths = list(folder.rglob('decisions.jsonl'))
    assert len(trace_paths) == 1, folder
    trace = trace_paths[0].parent
    decisions = lines(trace/'decisions.jsonl')
    receipts = lines(trace/'tool_results.jsonl')
    observations = lines(trace/'observations.jsonl')
    horizon = 5 if case['condition'] == 'fast_h5' else 1
    normal = [r for r in receipts if r.get('predicted_steps') == horizon
              and 'executed_step_interval' in r]
    assert len(normal) <= len(decisions), folder
    groups = {name: {'translation': [], 'rotation': []} for name in ('predicted', 'executed')}
    def add(name, rows):
        for row in rows:
            assert len(row) == 14
            for start in (0, 7):
                groups[name]['translation'].append(math.sqrt(sum(x*x for x in row[start:start+3])))
                groups[name]['rotation'].append(math.sqrt(sum(x*x for x in row[start+3:start+6])))
    executed = 0
    events = Counter()
    for index, decision in enumerate(decisions):
        rows = decision['requested_tensor']
        assert len(rows) == horizon
        add('predicted', rows)
        if index < len(normal):
            receipt = normal[index]
            assert decision['step'] == receipt['executed_step_interval'][0]
            count = receipt['executed_steps']
            assert 0 <= count <= horizon
            assert len(receipt['full_executed_commands_local_only']) == count
            add('executed', rows[:count])
            executed += count
            events.update(e.get('type', 'unspecified') for e in receipt.get('controller_events', []))
    holds = sum(len(r.get('full_executed_commands_local_only', []))
                for r in lines(trace/'safety_holds.jsonl'))
    observed_steps = max((r['step'] for r in observations), default=0)
    clients = list(folder.glob('*/client.log'))
    logged_steps = [int(x) for p in clients for x in re.findall(r'env0 step: \x1b\[92m(\d+) / 800', p.read_text(errors='replace'))]
    native_steps = max(logged_steps, default=observed_steps)
    assert executed+holds <= native_steps
    native = final['native_results']
    assert len(native) <= 1
    result = native[0]['result'] if native else {}
    details = result.get('details', {}).get('0', {})
    return {
        'condition': case['condition'], 'layout': case['layout'],
        'infrastructure_aborted': aborted.exists(),
        'scored': bool(native), 'native_success': details.get('success'),
        'score': result.get('score'), 'returncode': final['returncode'],
        'wall_seconds': final['wall_seconds'], 'native_control_steps': native_steps,
        'last_observation_step': observed_steps, 'committed_gpt_steps': executed,
        'committed_other_steps': holds, 'native_steps_without_committed_receipt': native_steps-executed-holds,
        'gpt_attempts': len(lines(trace/'requests.jsonl')),
        'gpt_completed': len(lines(trace/'exchanges.jsonl')),
        'action_validation_rejections': len(lines(trace/'action_rejections.jsonl')),
        'controller_events': dict(events), 'zero_step_receipts': sum(r.get('executed_steps') == 0 for r in normal),
        'jev_attempts': len(lines(trace/'reuse_attempts.jsonl')),
        'horizon': horizon, 'unreceipted_decisions': len(decisions)-len(normal),
        'action_scale': {name: {kind: distribution(values, harness['max_translation_m' if kind == 'translation' else 'max_rotation_rad'])
                               for kind, values in group.items()} for name, group in groups.items()},
        'artifact_folder': str(folder),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cases = [audit(p.parent) for p in sorted(args.root.glob('*/*/case.json'))
             if (p.parent/'finished.json').exists() or (p.parent/'infrastructure-abort.json').exists()]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'cases': cases, 'scope': 'Terminated physical attempts, with infrastructure-aborted cases explicitly unscored; valid delta proposals and committed executed prefixes are separate. Units are meters and radians.'}, indent=2)+'\n')
    print(json.dumps([{k: row[k] for k in ('condition', 'layout', 'native_success', 'native_control_steps', 'gpt_completed', 'native_steps_without_committed_receipt')} for row in cases]))


if __name__ == '__main__':
    main()

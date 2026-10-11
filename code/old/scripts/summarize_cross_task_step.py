"""Summarize archived stack amplitude branches and new paired LIBERO branches.

The stack and LIBERO simulators use different execution horizons. This script
reports them separately; it does not treat their raw progress as exchangeable.
"""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def summary(rows):
    if not rows:
        return dict(n=0)
    progress = [r['progress_m'] * 1000 for r in rows]
    response = [r['response'] for r in rows if r['response'] is not None]
    return dict(n=len(rows), mean_progress_mm=statistics.mean(progress),
                median_progress_mm=statistics.median(progress),
                min_progress_mm=min(progress), max_progress_mm=max(progress),
                progress_fraction=sum(p > .001 for p in progress)/len(rows),
                worsen_fraction=sum(p < -.001 for p in progress)/len(rows),
                mean_response_along_command=statistics.mean(response) if response else None)


def bin_error(error):
    if error <= .005:
        return 'near_0_5mm'
    if error <= .020:
        return '5_20mm'
    if error <= .050:
        return '20_50mm'
    if error <= .150:
        return '50_150mm'
    return 'far_over_150mm'


def response(command, actual):
    size = math.sqrt(sum(x*x for x in command))
    return sum(x*y for x, y in zip(command, actual))/size**2 if size else None


def stack_data(root):
    groups = defaultdict(list)
    decisions = 0
    seeds = set()
    rejected = 0
    for file in sorted((root/'2026-09-29-expanded-v3').rglob('decisions.jsonl')):
        rows = lines(file)
        decisions += len(rows)
        seeds.update(row['seed'] for row in rows)
        by_id = {row['decision_id']: row for row in rows}
        for b in lines(file.with_name('branches.jsonl')):
            if b.get('kind') != 'amplitude' or not b['amplitude_m']:
                continue
            d = by_id[b['decision_id']]
            if 'goal_error_after_m' not in b:
                rejected += 1
                continue
            command = [x-y for x, y in zip(b['command_target_m'], b['before_position_m'])]
            item = dict(progress_m=b['goal_error_before_m']-b['goal_error_after_m'],
                        response=response(command, b['actual_delta_m']))
            amp = str(round(b['amplitude_m']*1000))+'mm'
            groups[('all', amp)].append(item)
            groups[(bin_error(d['metrics']['error_norm_m']), amp)].append(item)
            if d['metrics']['error_norm_m'] >= .15:
                groups[('far_all_stages', amp)].append(item)
    return dict(decisions=decisions, seeds=len(seeds), rejected_branches=rejected,
                by_distance={key: {amp: summary(groups[(key, amp)]) for amp in ('1mm','2mm','5mm','10mm')}
                             for key in ('all','near_0_5mm','5_20mm','20_50mm','50_150mm',
                                         'far_over_150mm','far_all_stages')})


def libero_data(root):
    groups = defaultdict(list)
    sources = defaultdict(list)
    completed = defaultdict(int)
    net_groups = defaultdict(list)
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or not (folder/'protocol.json').exists():
            continue
        protocol = json.loads((folder/'protocol.json').read_text())
        result = json.loads((folder/'result.json').read_text())
        task = protocol['task']
        completed[task] += result['status'] == 'completed'
        sources[task].append(dict(init=protocol['init_index'], decision=protocol['archived_decision'],
                                  source_sha256=protocol['source_sha256']))
        branches = json.loads((folder/'branches.json').read_text())
        zero = next((b for b in branches if b['amplitude_m'] == 0), None)
        for b in branches:
            item = dict(progress_m=b['progress_m'], response=b['response_along_command'])
            groups[(task, str(round(b['amplitude_m']*1000))+'mm')].append(item)
            if zero is not None and b['amplitude_m']:
                command = b['command_delta_m']
                net_actual = [x-y for x, y in zip(b['actual_delta_m'], zero['actual_delta_m'])]
                net_groups[(task, str(round(b['amplitude_m']*1000))+'mm')].append(
                    dict(progress_m=b['progress_m']-zero['progress_m'],
                         response=response(command, net_actual)))
    return {task: dict(completed_inits=completed[task], sources=sources[task],
                       by_amplitude={amp: summary(groups[(task, amp)])
                                     for amp in ('0mm','1mm','2mm','5mm','10mm')},
                       net_vs_zero={amp: summary(net_groups[(task, amp)])
                                    for amp in ('1mm','2mm','5mm','10mm')})
            for task in ('bowl','cheese')}


def archived_jev(root, kind):
    base = root / ('2026-10-02-libero-wrist-frozen20' if kind == 'bowl'
                   else '2026-10-03-libero-recovery30-focused-v1')
    groups = defaultdict(list)
    episodes = 0
    decisions = 0
    for folder in sorted(base.iterdir()):
        if not folder.is_dir() or not (folder/'decisions.jsonl').exists():
            continue
        episodes += 1
        for row in lines(folder/'decisions.jsonl'):
            decisions += 1
            groups[row['stage']].append(row)
    stages = {}
    for stage, rows in sorted(groups.items()):
        active = [r for r in rows if r['metrics']['error_norm_m'] > .006]
        cosine = [r['metrics']['cosine'] for r in active if r['metrics']['cosine'] is not None]
        stages[stage] = dict(decisions=len(rows), active_over_6mm=len(active),
                             positive_cosine_fraction=(sum(c > 0 for c in cosine)/len(cosine)
                                                       if cosine else None),
                             mean_cosine=statistics.mean(cosine) if cosine else None)
    return dict(episodes=episodes, decisions=decisions, by_stage=stages)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', required=True, type=Path)
    parser.add_argument('--paired-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = dict(scope='Development audit: paired stack old states; paired LIBERO new approach states',
                  stack=stack_data(args.run_root), libero_paired=libero_data(args.paired_root),
                  libero_archived_jev={task: archived_jev(args.run_root, task)
                                       for task in ('bowl','cheese')},
                  caveat='No Jev calls in new branches; no closed-loop or unseen-task evaluation. '
                         'Different simulators and execution horizons; branch-level samples are dependent.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False)+'\n')
    print(json.dumps(dict(stack=result['stack']['by_distance'],
                          libero={k:v['by_amplitude'] for k,v in result['libero_paired'].items()},
                          archived_jev=result['libero_archived_jev']), ensure_ascii=False))


if __name__ == '__main__':
    main()

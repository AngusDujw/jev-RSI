"""Post-run truth scoring only. Never import this evaluator into a policy."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
from run_position_pilot import dump, direction_metrics


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('run', type=Path)
    a = p.parse_args()
    cfg = json.loads((a.run/'protocol.json').read_text())
    root = Path(cfg['existing_root'])
    sys.path.insert(0, str(root/'controller/src'))
    from realman_jev.company_geometry import add_block_geometry
    case = json.loads((a.run/'case.json').read_text())
    layout = root/'robodojo'/case['layout']
    snapshots = {}
    initial = json.loads((a.run/'simulator/audit_only/initial.json').read_text())
    snapshots[initial['tick']] = initial
    for line in (a.run/'simulator/audit_only/decisions.jsonl').read_text().splitlines():
        row = json.loads(line)
        for key in ('before', 'after'):
            snapshot = row[key]
            snapshots[snapshot['tick']] = snapshot
    for snapshot in snapshots.values():
        add_block_geometry(snapshot, layout.parents[4]/'Object/RoboDojo', layout)

    def targets(snapshot):
        result = {}
        for obj in snapshot['objects']:
            if obj.get('category') == 'block':
                lo = np.asarray(obj['geometry']['world_bbox_min_m'])
                hi = np.asarray(obj['geometry']['world_bbox_max_m'])
                result[obj['id']] = np.r_[(lo[:2]+hi[:2])/2,hi[2]+.05]
        return result

    trajectory = json.loads((a.run/'visual_trajectory.json').read_text())
    first = np.asarray(trajectory[0]['estimated_target_m'])
    truth = targets(snapshots[trajectory[0]['native_step']])
    identity = min(truth, key=lambda k: np.linalg.norm(truth[k]-first))
    if np.linalg.norm(truth[identity]-first)>.08:
        raise ValueError('Cannot match initial visual target within declared 80mm audit gate')
    decisions = {r['native_step']: r for r in map(json.loads, (a.run/'decisions.jsonl').read_text().splitlines())}
    rows = []
    for state in trajectory:
        target = targets(snapshots[state['native_step']])[identity]
        position = np.asarray(state['position_m'])
        error = target-position
        row = dict(native_step=state['native_step'], estimated_error_m=state['estimated_error_norm_m'],
            actual_error_norm_m=float(np.linalg.norm(error)), actual_error_max_axis_m=float(np.max(np.abs(error))),
            target_estimation_error_m=float(np.linalg.norm(target-state['estimated_target_m'])),
            actual_target_m=target.tolist(), actual_error_xyz_m=error.tolist())
        if state['native_step'] in decisions:
            d = decisions[state['native_step']]
            row['decision_id'] = d['decision_id']
            row['true_metrics'] = direction_metrics(position, target, d['signs'], cfg['axis_tolerance_m'])
            row['estimated_metrics'] = d['metrics']
        rows.append(row)
    measured = [r for r in rows if 'true_metrics' in r]
    report = dict(audit_identity=identity, frames=len(rows), decisions=len(measured),
        axes_correct_against_truth=sum(sum(r['true_metrics']['axis_correct']) for r in measured),
        axes_correct_against_estimate=sum(sum(r['estimated_metrics']['axis_correct']) for r in measured),
        axes=3*len(measured), final_true_within_tolerance=bool(rows[-1]['actual_error_max_axis_m']<=cfg['axis_tolerance_m']),
        estimated_status=json.loads((a.run/'rgbd_reach_result.json').read_text())['status'],
        mean_target_error_mm=float(np.mean([r['target_estimation_error_m'] for r in rows])*1000),
        initial=rows[0], final=rows[-1], rows=rows,
        scope='Post-run geometric audit for approach only; no physical grasp success claim')
    dump(a.run/'posthoc_truth_audit.json', report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('rows','initial')}, default=lambda x:x.tolist()))


if __name__ == '__main__':
    main()

"""Posthoc unit-response proxy only; never imported by the online controller."""
import argparse
import hashlib
import json
from pathlib import Path
from reliability_step import ReliabilityStep, distance_step


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text())['optimizer']
    audit_path = args.run/'posthoc_truth_audit.json'
    audit = json.loads(audit_path.read_text())
    rows, counts, hashes = [], dict(motion_correct=0, motion_axes=0, false_motion_on_hold=0), {}
    for row in audit['rows']:
        if 'decision_id' not in row:
            continue
        path = args.run/row['decision_id']/'decision.json'
        decision = json.loads(path.read_text())
        hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        error = decision['metrics']['error_xyz_m']
        signs = decision['signs']
        for sign, expected in zip(signs, row['true_metrics']['expected_signs']):
            if expected:
                counts['motion_axes'] += 1
                counts['motion_correct'] += int(sign == expected)
            elif sign:
                counts['false_motion_on_hold'] += 1
        proposals = dict(distance07=distance_step(error,signs,cap=cfg['max_step_m']),
            reliability_axis=ReliabilityStep(cfg).propose(error,signs),
            axis_without_reliability_shrink=ReliabilityStep(dict(cfg,direction_probability=1.)).propose(error,signs))
        truth = row['actual_error_xyz_m']
        for proposal in proposals.values():
            proposal['ideal_true_loss_decrease_m2'] = sum(
                x*x-(x-u)**2 for x,u in zip(truth,proposal['delta_m']))/2
        rows.append(dict(decision_id=row['decision_id'], proposals=proposals))
    names = ('distance07','reliability_axis','axis_without_reliability_shrink')
    sums = {name:sum(r['proposals'][name]['ideal_true_loss_decrease_m2'] for r in rows) for name in names}
    result = dict(scope='Correlated historical states; ideal unit-response ONE-step proxy, NOT execution or task success',
        counts=counts, frozen_optimizer=cfg, totals=sums, rows=rows,
        hashes={**hashes,str(audit_path):hashlib.sha256(audit_path.read_bytes()).hexdigest()},
        interpretation='Accuracy prior comes from these same development states; no held-out claim. No feedback state fit from candidate executions.')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(counts=counts,totals=sums)))


if __name__ == '__main__':
    main()

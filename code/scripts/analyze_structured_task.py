"""Offline scoring of stored Jev responses; never imported by online control.

Scores consistency with supplied visual geometry, NOT physical task correctness.
Keep point-dead-zone and conservative uncertainty-interval references separate.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path


def label(error,bound):
    return 'hold' if abs(error)<=bound else ('positive' if error>0 else 'negative')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    rows=[]; sources={}
    for path in sorted(a.run.glob('decision-*/decision.json')):
        sources[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        d=json.loads(path.read_text()); s=d['observation']; b=s['constraints']['dead_zone_m']
        if s['schema']=='numeric':
            geometry=s['geometry']
        else:
            geometry={}
            for edge in s['relations']:
                arm=edge['reference'].split(':')[-1]
                g=geometry.setdefault(arm,dict(target_minus_grasp_m=[0.,0.,0.],uncertainty_m=s['constraints']['uncertainty_m']))
                g['target_minus_grasp_m']['xyz'.index(edge['axis'])]=edge['target_coordinate_m']-edge['current_coordinate_m']
        for arm,g in geometry.items():
            norm=math.sqrt(sum(v*v for v in g['target_minus_grasp_m']))
            bucket=next((name for limit,name in ((.01,'0-10mm'),(.03,'10-30mm'),(.1,'30-100mm')) if norm<limit),'100mm+')
            for axis,error in zip('xyz',g['target_minus_grasp_m']):
                answer=d['answers'][arm+'_'+axis]; choice=answer['choice']
                point=label(error,b); interval=label(error,b+g['uncertainty_m'])
                rows.append(dict(decision=d['decision_id'],native_step=d['native_step'],stage=s['stage'],arm=arm,axis=axis,
                    error_m=error,error_norm_m=norm,error_bin=bucket,dead_zone_m=b,uncertainty_m=g['uncertainty_m'],
                    choice=choice,confidence=answer.get('confidence'),probabilities=answer.get('probabilities'),
                    point_reference=point,interval_reference=interval,point_correct=choice==point,interval_correct=choice==interval,
                    reference_kind='provided_visual_target_not_simulator_truth'))
    def summarize(items):
        motion=[r for r in items if r['point_reference']!='hold']; holds=[r for r in items if r['point_reference']=='hold']
        return dict(axes=len(items),point_correct=sum(r['point_correct'] for r in items),
            interval_correct=sum(r['interval_correct'] for r in items),motion_axes=len(motion),
            motion_correct=sum(r['point_correct'] for r in motion),hold_axes=len(holds),hold_correct=sum(r['point_correct'] for r in holds))
    stages=defaultdict(list); bins=defaultdict(list)
    for r in rows: stages[r['stage']].append(r); bins[r['error_bin']].append(r)
    result_path=a.run/'structured_result.json'
    native=json.loads(result_path.read_text()) if result_path.exists() else dict(status='running_or_incomplete')
    result=dict(interpretation=__doc__,run=str(a.run),sources=sources,native=native,
        completed_decisions=len(sources),total=summarize(rows),by_stage={k:summarize(v) for k,v in stages.items()},
        by_error_bin={k:summarize(v) for k,v in bins.items()},axes=rows)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(completed_decisions=len(sources),total=result['total'],native_status=native['status'])))


if __name__=='__main__': main()

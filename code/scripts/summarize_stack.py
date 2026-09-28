"""Audit native task outcomes separately from Jev direction and execution quality."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import numpy as np


def main():
    p=argparse.ArgumentParser()
    p.add_argument('root',type=Path)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    episodes=[]; groups=defaultdict(list); hashes={}
    for result in sorted(a.root.rglob('stack_result.json')):
        folder=result.parent
        if not (folder/'summary.json').exists(): continue
        run=json.loads(result.read_text()); cfg=json.loads((folder/'protocol.json').read_text())
        run.update(folder=str(folder.relative_to(a.root)),layout_id=cfg['robodojo_layout_id'])
        episodes.append(run)
        decisions=[json.loads(s) for s in (folder/'decisions.jsonl').read_text().splitlines()]
        table={d['decision_id']:d for d in decisions}
        branches=[json.loads(s) for s in (folder/'branches.jsonl').read_text().splitlines()]
        linked=set()
        for b in branches:
            did=b.get('decision_id')
            if did is None: continue
            if did in linked: raise RuntimeError('Repeated execution linked to one decision')
            linked.add(did); d=table[did]
            i=('left','right').index(b['arm'])
            before=np.asarray(b['before']['robot']['nominal_grasp_points_m'][i])
            after=np.asarray(b['after']['robot']['nominal_grasp_points_m'][i])
            target=np.asarray(d['observation']['target_position_m'])
            dq=after-before; signs=np.asarray(d['signs'])
            change=float(np.linalg.norm(after-target)-np.linalg.norm(before-target))
            rotation_before=np.asarray(b['before']['robot']['eef_quaternions_wxyz'][i])
            rotation_after=np.asarray(b['after']['robot']['eef_quaternions_wxyz'][i])
            rotation=2*np.arccos(np.clip(abs(rotation_before@rotation_after),0,1))
            item=dict(axis_correct=sum(d['metrics']['axis_correct']),all_correct=all(d['metrics']['axis_correct']),
                cosine=d['metrics']['cosine'],distance_change_mm=1000*change,rotation_change_deg=float(np.degrees(rotation)),
                actual_vs_requested_cosine=float(dq@signs/(np.linalg.norm(dq)*np.linalg.norm(signs))) if np.linalg.norm(dq)*np.linalg.norm(signs)>0 else None)
            for key in ('all','stage:'+d['stage'],'layout:'+str(cfg['robodojo_layout_id'])): groups[key].append(item)
            for name in ('request.json','response.json','decision.json','native_state.json'):
                f=folder/did/name
                hashes[str(f.relative_to(a.root))]=hashlib.sha256(f.read_bytes()).hexdigest()
        if len(linked)!=len(decisions): raise RuntimeError('Unexecuted model decisions require explicit failure analysis')
    stats={}
    for key,rows in groups.items():
        stats[key]=dict(decisions=len(rows),axis_correct=sum(r['axis_correct'] for r in rows),axes=3*len(rows),
            all_axes_correct=sum(r['all_correct'] for r in rows),positive_cosines=sum(r['cosine'] is not None and r['cosine']>0 for r in rows),
            actual_distance_decreased=sum(r['distance_change_mm']<0 for r in rows),
            actual_distance_increased=sum(r['distance_change_mm']>0 for r in rows),
            increasing_with_rotation_over_1deg=sum(r['distance_change_mm']>0 and r['rotation_change_deg']>1 for r in rows),
            mean_distance_change_mm=float(np.mean([r['distance_change_mm'] for r in rows])))
    output=dict(episodes=episodes,completed=len(episodes),successes=sum(r['native']['success'] for r in episodes),
        groups=stats,scope='Frozen controller repeats on only two existing layouts; development configuration, no vision or autonomous phase planning')
    a.output.mkdir(parents=True,exist_ok=True)
    (a.output/'analysis.json').write_text(json.dumps(output,indent=2)+'\n')
    (a.output/'sha256.json').write_text(json.dumps(hashes,indent=2)+'\n')
    print(json.dumps({k:v for k,v in output.items() if k!='episodes'}))


if __name__=='__main__': main()

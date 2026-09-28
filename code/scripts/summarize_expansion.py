"""Audit completed or ongoing expansion; report denominators and cluster CIs."""
import argparse
from collections import defaultdict, Counter
import hashlib
import json
from pathlib import Path
import numpy as np


def main():
    p=argparse.ArgumentParser()
    p.add_argument('root',type=Path)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    groups=defaultdict(list); runs=[]; hashes={}; branches=[]
    for folder in sorted(a.root.rglob('seed-*')):
        if not folder.is_dir(): continue
        summary=folder/'summary.json'
        if not summary.exists(): continue
        rows=[json.loads(s) for s in (folder/'decisions.jsonl').read_text().splitlines()]
        run=json.loads(summary.read_text()); run['seed']=int(folder.name.split('-')[-1]); runs.append(run)
        for row in rows:
            d=folder/row['decision_id']
            for name in ('request.json','response.json','decision.json','sim_state.npz','sim_metadata.json'):
                f=d/name
                if not f.exists(): raise RuntimeError(f'Missing raw artifact: {f}')
                hashes[str(f.relative_to(a.root))]=hashlib.sha256(f.read_bytes()).hexdigest()
            if 'metrics' not in row: continue
            row['cluster']=run['seed']
            error=row['metrics']['error_norm_m']*1000
            bucket=('<0.5' if error<.5 else '0.5-2' if error<2 else '2-5' if error<5 else '5-20' if error<20 else '>=20')
            row['error_bin_mm']=bucket
            for group in ('all','stage:'+row['stage'],'error:'+bucket,'stage_error:'+row['stage']+':'+bucket):
                groups[group].append(row)
        branches.extend(json.loads(s) for s in (folder/'branches.jsonl').read_text().splitlines())
    stats={}
    for name,rows in groups.items():
        confusion=np.zeros((3,3),int); probs=[]; cluster=defaultdict(lambda:[0,0]); cos=[]
        for row in rows:
            m=row['metrics']
            if m['cosine'] is not None: cos.append(m['cosine'])
            for i,axis in enumerate('xyz'):
                truth=int(m['expected_signs'][i]); pred=int(row['signs'][i])
                confusion[truth+1,pred+1]+=1
                cluster[row['cluster']][0]+=int(truth==pred); cluster[row['cluster']][1]+=1
                answer=row['answers'][axis]['probabilities']
                prob=np.array([answer[x] for x in ('negative','hold','positive')])
                target=np.eye(3)[truth+1]
                probs.append(float(np.sum((prob-target)**2)))
        vals=np.asarray(list(cluster.values())); rng=np.random.default_rng(42)
        samples=vals[rng.integers(len(vals),size=(2000,len(vals)))].sum(axis=1)
        ci=np.quantile(samples[:,0]/samples[:,1],[.025,.975]).tolist() if len(vals)>1 else None
        stats[name]=dict(decisions=len(rows),axes=3*len(rows),axis_correct=int(np.trace(confusion)),
            all_axes_correct=sum(all(r['metrics']['axis_correct']) for r in rows),
            confusion_rows_truth_columns_prediction_negative_hold_positive=confusion.tolist(),
            measurable_cosines=len(cos),positive_cosines=sum(c>0 for c in cos),
            all_hold=sum(r['metrics']['all_hold'] for r in rows),
            mean_multiclass_brier=float(np.mean(probs)),seed_clusters=len(vals),axis_accuracy_seed_bootstrap_95ci=ci)
    amplitude=defaultdict(lambda:dict(n=0,progress=0,unstable=0,delta_mm=[]))
    for b in branches:
        if b.get('kind')!='amplitude': continue
        if 'goal_error_after_m' not in b: continue
        error=b['goal_error_before_m']*1000
        bucket=('<0.5' if error<.5 else '0.5-2' if error<2 else '2-5' if error<5 else '5-20' if error<20 else '>=20')
        g=amplitude[f'{bucket}:{b["amplitude_m"]*1000:g}mm']; g['n']+=1
        delta=(b['goal_error_after_m']-b['goal_error_before_m'])*1000
        g['progress']+=int(delta<0); g['unstable']+=int(not b['stable']); g['delta_mm'].append(delta)
        if not b['reset_identical']: raise RuntimeError('Nonidentical paired initial state')
    for g in amplitude.values(): g['mean_delta_mm']=float(np.mean(g.pop('delta_mm')))
    result=dict(completed_runs=len(runs),runs=runs,groups=stats,amplitudes=dict(amplitude),
                scope='Development trajectory samples, seed-cluster bootstrap; not uniform error coverage or whole-task Jev success')
    a.output.mkdir(parents=True,exist_ok=True)
    (a.output/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    (a.output/'sha256.json').write_text(json.dumps(hashes,indent=2)+'\n')
    print(json.dumps(dict(completed_runs=len(runs),all=stats.get('all'),artifacts=len(hashes))))


if __name__=='__main__': main()

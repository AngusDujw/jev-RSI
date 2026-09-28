"""Two repeated real requests on 90 saved inputs; no new physical states."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
from run_position_pilot import Jev, Recorder, dump


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--config',required=True,type=Path)
    p.add_argument('--source-root',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    cfg=json.loads(a.config.read_text()); cfg.update(max_jev_decisions=180,protocol='exact-input-repeatability-v1')
    cases=[]
    for seed in (10,11,12):
        root=a.source_root/f'seed-{seed}'
        assert json.loads((root/'summary.json').read_text())['decisions']==30
        for f in sorted(root.glob('decision-*/decision.json')):
            row=json.loads(f.read_text())
            cases.extend((f.parent,row,repeat) for repeat in (1,2))
    random.Random(20260929).shuffle(cases)
    rec=Recorder(a.output,cfg)
    dump(rec.folder/'provenance.json',dict(command=sys.argv,python=sys.executable,
        commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),physical_execution=False))
    model=Jev(rec); status='completed'; matches=0; by_source={}
    try:
        for source,old,repeat in cases:
            state=json.loads((source/'request.json').read_text())['state']
            row=model.choose(state,dict(stage=old['stage'],environment='embodied-jev',seed=old['seed'],
                repeat=repeat,source_decision=str(source),source_request_sha256=old['request_sha256'],
                original_signs=old['signs'],physical_execution=False))
            assert row['request_sha256']==old['request_sha256'], 'Repeated input differs'
            matches+=row['signs']==old['signs']
            by_source.setdefault(str(source),[old['signs']]).append(row['signs'])
            for name in ('sim_state.npz','sim_metadata.json'):
                shutil.copy2(source/name,rec.folder/row['decision_id']/name)
        dump(rec.folder/'repeatability.json',dict(original_states=90,repeated_requests=len(rec.decisions),
            exact_sign_match_to_original=matches,
            all_three_sign_vectors_identical=sum(all(v==rows[0] for v in rows) for rows in by_source.values()),
            scope='Same exact input requested three times total; not 270 independent physical states'))
    except Exception as exc:
        status='failed'; rec.errors.append(dict(type=type(exc).__name__,error=str(exc))); raise
    finally:
        model.close(); rec.finish(status)


if __name__=='__main__': main()

"""Frozen 20-initial-state validation, no retries or policy selection."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

root=Path(sys.argv[1]).resolve()
root.mkdir(parents=True,exist_ok=False)
scripts=Path(__file__).resolve().parent
frozen=root/'frozen';frozen.mkdir()
files=['libero_jev_rollout.py','run_position_pilot.py']
for name in files:(frozen/name).write_bytes((scripts/name).read_bytes())
manifest=dict(task_id=988,init_indices=list(range(1,21)),seed=0,policy_changes=False,
              retries=0,expected_episodes=20,source_sha256={n:hashlib.sha256((frozen/n).read_bytes()).hexdigest() for n in files},
              commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
              budget=dict(episode_seconds=960,total_disk_gb=4,jev_per_episode=120,native_steps=550),
              interpretation='held-out initial states of one selected development task; not full benchmark')
(root/'manifest.json').write_text(json.dumps(manifest,indent=2))
rows=[]
for i in manifest['init_indices']:
    output=root/f'init-{i:02d}'
    cmd=[sys.executable,'-B',str(frozen/files[0]),'--task-id','988','--seed','0','--init-index',str(i),'--output',str(output)]
    start=time.monotonic()
    with (root/f'init-{i:02d}.log').open('w') as log:
        try: returncode=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=960).returncode
        except subprocess.TimeoutExpired:returncode=124
    result=json.loads((output/'result.json').read_text()) if (output/'result.json').exists() else dict(success=False,error='no result / setup failure')
    summary=json.loads((output/'summary.json').read_text()) if (output/'summary.json').exists() else {}
    row=dict(init_index=i,returncode=returncode,wall_seconds=time.monotonic()-start,result=result,summary=summary)
    rows.append(row)
    (root/'batch.json').write_text(json.dumps(dict(completed=len(rows),successes=sum(r['result']['success'] for r in rows),rows=rows),indent=2))
    print(json.dumps(dict(init_index=i,success=result['success'],error=result.get('error'),completed=len(rows),successes=sum(r['result']['success'] for r in rows))),flush=True)
    size=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
    if size>4*1024**3: raise RuntimeError('4GiB batch disk budget exceeded')
(root/'finished.json').write_text(json.dumps(dict(completed=20,successes=sum(r['result']['success'] for r in rows))))

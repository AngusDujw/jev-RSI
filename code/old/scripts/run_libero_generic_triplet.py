"""Freeze generic policy and run three predeclared starts, no retries/tuning."""
import hashlib,json,subprocess,sys,time,os
from pathlib import Path
root=Path(sys.argv[1]).resolve();root.mkdir(parents=True,exist_ok=False)
source=Path(__file__).resolve().parent;frozen=root/'frozen';frozen.mkdir()
files=['libero_jev_rollout.py','libero_generic_vision.py','libero_grounding_worker.py','local_rgbd_perception.py','run_position_pilot.py']
for n in files:(frozen/n).write_bytes((source/n).read_bytes())
manifest=dict(task=1062,starts=[2,3,4],seed=0,retries=0,commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),source_sha256={n:hashlib.sha256((frozen/n).read_bytes()).hexdigest() for n in files},protocol='paired development triplet; fixed policy; failures retained')
(root/'manifest.json').write_text(json.dumps(manifest,indent=2));rows=[]
for init in manifest['starts']:
 out=root/f'init-{init}';start=time.monotonic()
 command=[sys.executable,'-B',str(frozen/'libero_jev_rollout.py'),'--generic-vision','--scripted-supervisor','--task-id','1062','--init-index',str(init),'--seed','0','--output',str(out)]
 with (root/f'init-{init}.log').open('w') as log:
  try:code=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=960).returncode
  except subprocess.TimeoutExpired:code=124
 r=json.loads((out/'result.json').read_text()) if (out/'result.json').exists() else dict(success=False,error='no result/setup failure')
 row=dict(init_index=init,returncode=code,seconds=time.monotonic()-start,result=r);rows.append(row)
 (root/'batch.json').write_text(json.dumps(rows,indent=2));print(json.dumps(row),flush=True)
 if sum(p.stat().st_size for p in root.rglob('*') if p.is_file())>2*1024**3:raise RuntimeError('triplet disk guard')
(root/'finished.json').write_text(json.dumps(dict(completed=3,successes=sum(r['result']['success'] for r in rows))))

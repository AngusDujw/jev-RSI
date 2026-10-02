"""Frozen cross-task evaluation; predeclared cases and all first attempts retained."""
import hashlib,json,subprocess,sys,time
from pathlib import Path
root=Path(sys.argv[1]).resolve();root.mkdir(parents=True,exist_ok=False)
source=Path(__file__).resolve().parent;frozen=root/'frozen';frozen.mkdir()
files=['libero_jev_rollout.py','libero_generic_vision.py','libero_grounding_worker.py','local_rgbd_perception.py','run_position_pilot.py']
for n in files:(frozen/n).write_bytes((source/n).read_bytes())
cases=[('libero_spatial',1282),('libero_object',1066),('libero_object',1043)]
manifest=dict(cases=cases,starts=[1,2,3],seed=0,retries=0,commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),source_sha256={n:hashlib.sha256((frozen/n).read_bytes()).hexdigest() for n in files},protocol='same generic policy, no task-specific tuning; single-object pick/place scope')
(root/'manifest.json').write_text(json.dumps(manifest,indent=2));rows=[]
for suite,task in cases:
 for init in [1,2,3]:
  label=f'{suite}-{task}-init-{init}';out=root/label;start=time.monotonic()
  cmd=[sys.executable,'-B',str(frozen/'libero_jev_rollout.py'),'--generic-vision','--suite',suite,'--task-id',str(task),'--init-index',str(init),'--output',str(out)]
  with (root/(label+'.log')).open('w') as log:
   try:code=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=960).returncode
   except subprocess.TimeoutExpired:code=124
  r=json.loads((out/'result.json').read_text()) if (out/'result.json').exists() else dict(success=False,error='setup failure/no result')
  row=dict(suite=suite,task=task,init_index=init,returncode=code,seconds=time.monotonic()-start,result=r);rows.append(row)
  (root/'batch.json').write_text(json.dumps(rows,indent=2));print(json.dumps(row),flush=True)
  if sum(p.stat().st_size for p in root.rglob('*') if p.is_file())>3*1024**3:raise RuntimeError('Batch disk budget')
(root/'finished.json').write_text(json.dumps(dict(completed=9,successes=sum(r['result']['success'] for r in rows))))

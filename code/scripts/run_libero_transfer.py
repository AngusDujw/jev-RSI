"""Three predeclared Spatial transfers, three initial states each; no retries."""
import hashlib,json,subprocess,sys,time
from pathlib import Path
root=Path(sys.argv[1]).resolve();root.mkdir(parents=True,exist_ok=False)
scripts=Path(__file__).resolve().parent;frozen=root/'frozen';frozen.mkdir()
for n in ['libero_jev_rollout.py','run_position_pilot.py']:(frozen/n).write_bytes((scripts/n).read_bytes())
cases=[(1030,'near_ramekin'),(1062,'table_center'),(1282,'near_plate')]
manifest=dict(cases=cases,initial_states=[1,2,3],seed=0,commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
              source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in frozen.iterdir()},
              protocol='fixed small transfer pilot; no retries; task-specific relation adapter; not full benchmark')
(root/'manifest.json').write_text(json.dumps(manifest,indent=2));rows=[]
for task,relation in cases:
 for init in [1,2,3]:
  out=root/f'task-{task}-init-{init}';start=time.monotonic()
  command=[sys.executable,'-B',str(frozen/'libero_jev_rollout.py'),'--task-id',str(task),'--relation',relation,'--init-index',str(init),'--output',str(out)]
  with (root/f'task-{task}-init-{init}.log').open('w') as log:
   try:code=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=960).returncode
   except subprocess.TimeoutExpired:code=124
  result=json.loads((out/'result.json').read_text()) if (out/'result.json').exists() else dict(success=False,error='setup failure / no result')
  row=dict(task=task,relation=relation,init_index=init,returncode=code,seconds=time.monotonic()-start,result=result);rows.append(row)
  (root/'batch.json').write_text(json.dumps(rows,indent=2));print(json.dumps(row),flush=True)
  if sum(p.stat().st_size for p in root.rglob('*') if p.is_file())>3*1024**3:raise RuntimeError('Disk budget')
(root/'finished.json').write_text(json.dumps(dict(completed=len(rows),successes=sum(r['result']['success'] for r in rows))))

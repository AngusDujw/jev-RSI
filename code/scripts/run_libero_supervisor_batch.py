"""Version-frozen Jev-owner experiments. Persistent per-task cap=50 across variants."""
import argparse,json,subprocess,time,hashlib,fcntl,os
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--schema',choices=['numeric','feedback'],required=True);p.add_argument('--tasks',default='libero_spatial:1282,libero_object:1066,libero_object:1043');p.add_argument('--inits',default='1');p.add_argument('--grasp-fraction',type=float,default=.4);p.add_argument('--geometry-profile',choices=['base','observed_surfaces'],default='base');p.add_argument('--camera-size',type=int,default=384);p.add_argument('--approach-mode',choices=['top','side'],default='top');p.add_argument('--max-jev-decisions',type=int,default=120);a=p.parse_args()
root=Path(a.output).resolve();root.mkdir(parents=True,exist_ok=False);source=Path(__file__).resolve().parent;frozen=root/'frozen';frozen.mkdir()
files=['libero_jev_rollout.py','libero_jev_supervisor.py','libero_generic_vision.py','libero_grounding_worker.py','local_rgbd_perception.py','run_position_pilot.py']
for n in files:(frozen/n).write_bytes((source/n).read_bytes())
tasks=[(x.split(':')[0],int(x.split(':')[1])) for x in a.tasks.split(',')];inits=[int(x) for x in a.inits.split(',')]
manifest=dict(tasks=tasks,inits=inits,schema=a.schema,grasp_fraction=a.grasp_fraction,geometry_profile=a.geometry_profile,camera_size=a.camera_size,approach_mode=a.approach_mode,max_jev_decisions=a.max_jev_decisions,commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),source_sha256={n:hashlib.sha256((frozen/n).read_bytes()).hexdigest() for n in files},per_task_cap=50)
(root/'manifest.json').write_text(json.dumps(manifest,indent=2));rows=[]
ledger=source.parent/'runs'/'libero-supervisor-ledger.jsonl'
for suite,task in tasks:
 for init in inits:
  name=f'{suite}-{task}-init-{init}';out=root/name
  with ledger.open('a+') as l:
   fcntl.flock(l,fcntl.LOCK_EX);l.seek(0);past=[json.loads(x) for x in l if x.strip()];count=sum(x['suite']==suite and x['task']==task for x in past)
   if count>=50:raise RuntimeError('Per-task 50 episode limit')
   attempt=count+1;l.write(json.dumps(dict(suite=suite,task=task,attempt=attempt,output=str(out),schema=a.schema))+'\n');l.flush();os.fsync(l.fileno())
  cmd=['/root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python','-B',str(frozen/'libero_jev_rollout.py'),'--jev-supervisor','--schema',a.schema,'--suite',suite,'--task-id',str(task),'--init-index',str(init),'--grasp-fraction',str(a.grasp_fraction),'--geometry-profile',a.geometry_profile,'--camera-size',str(a.camera_size),'--approach-mode',a.approach_mode,'--max-jev-decisions',str(a.max_jev_decisions),'--output',str(out)]
  start=time.monotonic()
  with (root/(name+'.log')).open('w') as log:
   try:rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=960).returncode
   except subprocess.TimeoutExpired:rc=124
  r=json.loads((out/'result.json').read_text()) if (out/'result.json').exists() else dict(success=False,error='setup/no result')
  row=dict(task=task,suite=suite,init=init,attempt=attempt,returncode=rc,seconds=time.monotonic()-start,result=r);rows.append(row);(root/'batch.json').write_text(json.dumps(rows,indent=2));print(json.dumps(row),flush=True)
  if sum(f.stat().st_size for f in root.rglob('*') if f.is_file())>3*1024**3:raise RuntimeError('Batch disk cap')
(root/'finished.json').write_text(json.dumps(dict(episodes=len(rows),successes=sum(x['result']['success'] for x in rows))))

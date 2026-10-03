"""Frozen bounded optimization: <=30 new episodes, original <=50/task persists."""
import argparse
import fcntl
import hashlib
import json
import os
import signal
import shutil
from pathlib import Path
import subprocess
import time

p=argparse.ArgumentParser()
p.add_argument('--output',required=True)
p.add_argument('--tasks',default='libero_object:1066')
p.add_argument('--inits',default='1')
p.add_argument('--frozen-from',help='Reuse an audited prior frozen/ policy snapshot exactly')
p.add_argument('--input-organization',choices=['contract','evidence','local','focused'],default='contract')
p.add_argument('--grasp-algorithm',choices=['legacy_clearance','pad_fit'],default='pad_fit')
p.add_argument('--contact-angle-deg',type=float,default=0.)
p.add_argument('--pad-overlap-mm',type=float,default=6.)
p.add_argument('--table-margin-mm',type=float,default=1.)
p.add_argument('--preserve-source',action='store_true')
p.add_argument('--allow-retry',action='store_true')
p.add_argument('--execution-profile',choices=['baseline','adaptive'],default='baseline')
p.add_argument('--max-jev-decisions',type=int,default=180)
a=p.parse_args()
source=Path(__file__).resolve().parent
root=Path(a.output).resolve();root.mkdir(parents=True,exist_ok=False)
frozen=root/'frozen';frozen.mkdir()
files=['libero_jev_rollout.py','libero_jev_supervisor.py','libero_jev_recovery.py','libero_robot_geometry.py','libero_generic_vision.py','libero_grounding_worker.py','local_rgbd_perception.py','run_position_pilot.py']
snapshot=Path(a.frozen_from).resolve() if a.frozen_from else source
prior=json.loads((snapshot.parent/'manifest.json').read_text()) if a.frozen_from else None
for name in files:
 data=(snapshot/name).read_bytes()
 if prior and hashlib.sha256(data).hexdigest()!=prior['source_sha256'][name]:raise RuntimeError('Frozen source hash mismatch: '+name)
 (frozen/name).write_bytes(data)
runner_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
manifest=dict(options=vars(a),commit=prior['commit'] if prior else runner_commit,runner_commit=runner_commit,source_sha256={n:hashlib.sha256((frozen/n).read_bytes()).hexdigest() for n in files},new_episode_cap=30,per_task_total_cap=50)
(root/'manifest.json').write_text(json.dumps(manifest,indent=2))
ledger=source.parent/'runs'/'libero-supervisor-ledger.jsonl'
campaign=source.parent/'runs'/'libero-recovery30-ledger.jsonl'
rows=[]
for item in a.tasks.split(','):
 suite,task=item.split(':');task=int(task)
 for init in map(int,a.inits.split(',')):
  out=root/f'{suite}-{task}-init-{init}'
  if shutil.disk_usage(root).free<6*1024**3:raise RuntimeError('Shared filesystem guard: need >=6GiB before a new episode')
  with ledger.open('a+') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX);lock.seek(0)
   old=[json.loads(x) for x in lock if x.strip()]
   with campaign.open('a+') as cf:
    cf.seek(0);new=[json.loads(x) for x in cf if x.strip()]
    count=sum(x['suite']==suite and x['task']==task for x in old)
    if count>=50 or len(new)>=30:raise RuntimeError('Authorized episode cap reached')
    reservation=dict(suite=suite,task=task,attempt=count+1,campaign_attempt=len(new)+1,output=str(out),campaign='recovery30',options=vars(a))
    lock.write(json.dumps(reservation)+'\n');lock.flush();os.fsync(lock.fileno())
    cf.write(json.dumps(reservation)+'\n');cf.flush();os.fsync(cf.fileno())
  cmd=['/root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python','-B',str(frozen/'libero_jev_rollout.py'),'--recovery-supervisor','--suite',suite,'--task-id',str(task),'--init-index',str(init),'--geometry-profile','observed_surfaces','--camera-size','768','--max-jev-decisions',str(a.max_jev_decisions),'--input-organization',a.input_organization,'--grasp-algorithm',a.grasp_algorithm,'--contact-angle-deg',str(a.contact_angle_deg),'--pad-overlap-mm',str(a.pad_overlap_mm),'--table-margin-mm',str(a.table_margin_mm),'--output',str(out)]
  if a.preserve_source:cmd.append('--preserve-source')
  if a.allow_retry:cmd.append('--allow-retry')
  if a.execution_profile!='baseline':cmd.extend(['--execution-profile',a.execution_profile])
  start=time.monotonic()
  with (root/f'{suite}-{task}-init-{init}.log').open('w') as log:
   termination_reason=None
   child=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
   while child.poll() is None:
    if time.monotonic()-start>960 or shutil.disk_usage(root).free<4*1024**3:
     termination_reason='Shared filesystem below 4GiB' if shutil.disk_usage(root).free<4*1024**3 else 'Runner timeout 960s'
     child.send_signal(signal.SIGINT)
     try:child.wait(timeout=45)
     except subprocess.TimeoutExpired:child.kill();child.wait()
     break
    try:child.wait(timeout=5)
    except subprocess.TimeoutExpired:pass
   rc=child.returncode
  result=json.loads((out/'result.json').read_text()) if (out/'result.json').exists() else dict(success=False,error='Setup/no result')
  if termination_reason:
   result=dict(result,runner_termination=termination_reason,error=termination_reason)
   (out/'runner-stop.json').write_text(json.dumps(dict(reason=termination_reason,returncode=rc),indent=2))
  row=dict(suite=suite,task=task,init=init,attempt=count+1,campaign_attempt=reservation['campaign_attempt'],seconds=time.monotonic()-start,returncode=rc,result=result)
  rows.append(row);(root/'batch.json').write_text(json.dumps(rows,indent=2));print(json.dumps(row),flush=True)
  if sum(f.stat().st_size for f in root.rglob('*') if f.is_file())>3*1024**3:raise RuntimeError('Batch disk cap')
(root/'finished.json').write_text(json.dumps(dict(episodes=len(rows),native_successes=sum(r['result']['success'] for r in rows),complete_successes=sum(r['result']['success'] and r['result'].get('program_finished',False) for r in rows))))

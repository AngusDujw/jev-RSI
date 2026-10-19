"""Compact native campaign; resource-gated concurrency and independent API bridge."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time


def scheduler(path):
    cfg=json.loads(path.read_text());root=path.parent
    queued=list(cfg['cases']);active={};done=[]
    while queued or active:
        for name,(proc,log) in list(active.items()):
            if proc.poll() is not None:
                log.close();done.append(dict(name=name,returncode=proc.returncode));del active[name]
        limit=json.loads((root/'concurrency.json').read_text())['limit']
        free=int(subprocess.check_output(['nvidia-smi','--id=0','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True).strip())
        available=int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))/1024
        while queued and len(active)<limit and free>2500 and available>5000:
            if shutil.disk_usage(root).free<8*1024**3:raise RuntimeError('DataStorage free-space guard')
            case=queued.pop(0);out=Path(case['output']);out.parent.mkdir(parents=True,exist_ok=True)
            if out.exists():raise FileExistsError(out)
            log=(root/(case['name']+'.log')).open('w')
            env=dict(os.environ,OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',NUMBA_NUM_THREADS='1',
                TMPDIR=str(root/'cache'),XDG_CACHE_HOME=str(root/'cache'),PYTHONDONTWRITEBYTECODE='1',
                MAGICK_HOME=cfg['runtime_libs']+'/usr',
                LD_LIBRARY_PATH=cfg['runtime_libs']+'/usr/lib/x86_64-linux-gnu'+(':'+os.environ['LD_LIBRARY_PATH'] if os.environ.get('LD_LIBRARY_PATH') else ''))
            command=[cfg['python'],'-B',str(Path(cfg['project'])/'code/decision_multimodal/libero_direct_axes.py'),
                '--task',str(case['task']),'--init',str(case['init']),'--gpu','0','--output',case['output'],
                '--plan',case['plan'],'--libero-root',cfg['libero_root'],'--example-bank',cfg['example_bank'],
                '--input-variant',case['variant'],'--grounded','--relation-prompts','--surface-context',
                '--coordinate-questions','--adaptive-steps','--file-transport','--compact']
            if case['variant']!='task_native_frame':command+=['--positive-frame']
            if case.get('record_evidence'):command+=['--record-evidence']
            if case.get('live_surfaces'):command+=['--live-surfaces']
            if case.get('actor_attention'):command+=['--actor-attention']
            if case.get('focused_questions'):command+=['--focused-questions']
            if case.get('relative_step_scale'):command+=['--relative-step-scale']
            if case.get('numeric_xy'):command+=['--numeric-xy']
            if case.get('reference_history'):command+=['--reference-history']
            if case.get('protocol_file'):command+=['--protocol-file',case['protocol_file']]
            if case.get('live_protocol'):command+=['--live-protocol']
            if case.get('pad_outlines'):command+=['--pad-outlines']
            if case.get('visual_near_grasp'):command+=['--visual-near-grasp']
            if case.get('numeric_z'):command+=['--numeric-z']
            if case.get('track_selected'):command+=['--track-selected']
            if case.get('robot_self_mask'):command+=['--robot-self-mask']
            command+=['--execution-steps',str(case.get('execution_steps',4))]
            proc=subprocess.Popen(command,cwd=cfg['project'],env=env,stdout=log,stderr=subprocess.STDOUT)
            active[case['name']]=(proc,log);free-=1500;available-=2000
        status=dict(time=time.time(),active=[dict(name=n,pid=p.pid) for n,(p,_) in active.items()],
            queued=len(queued),finished=done,limit=limit,gpu_free_mib=free,mem_available_mib=available)
        part=root/'status.part';part.write_text(json.dumps(status,indent=2));part.replace(root/'status.json')
        time.sleep(3)


def bridge(path):
    cfg=json.loads(path.read_text());root=path.parent;deadline=time.monotonic()+28800
    while time.monotonic()<deadline:
        command=[sys.executable,'-B',str(Path(__file__).with_name('decision_file_bridge.py')),
            '--host',cfg['host'],'--remote-roots',*[c['output'] for c in cfg['cases']],
            '--key-file',str(Path.cwd()/'.private/du-openai-direct.key'),'--output',str(root/'bridge'),
            '--resume','--compact','--workers',str(cfg.get('api_workers',12)),'--seconds',str(max(1,int(deadline-time.monotonic()))),
            '--control-path',cfg.get('control_path','code/runs/v4090-dm-20261019.sock')]
        with (root/'bridge.log').open('a') as log:result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
        if result.returncode==0:return
        time.sleep(2)
    raise TimeoutError('Campaign bridge wall budget exhausted; results retained')


def main():
    p=argparse.ArgumentParser();p.add_argument('--scheduler',type=Path);p.add_argument('--bridge',type=Path)
    a=p.parse_args()
    if a.scheduler:scheduler(a.scheduler.resolve())
    elif a.bridge:bridge(a.bridge.resolve())
    else:p.error('Choose --scheduler or --bridge')


if __name__=='__main__':main()

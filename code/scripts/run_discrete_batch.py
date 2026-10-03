"""Tracked foreground batch. Trial directories reserve budget before launch."""
import argparse,concurrent.futures,json,os,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
TASKS=['general_pickup','stack_bowls','fold_clothes','press_by_number','match_and_pick_from_conveyor']

def run(task,variant,processing,layout,gpu=None,frozen_from=None,auto_gpu=False):
    folder=ROOT/'code/runs';old=sorted(folder.glob('jev-discrete-'+task+'-[0-9][0-9]'))
    numbers=[int(p.name[-2:]) for p in old];number=max(numbers,default=0)+1
    if number>50:raise RuntimeError('50 trial budget reached '+task)
    if shutil.disk_usage(folder).free<8*1024**3:raise RuntimeError('less than 8 GiB available; do not launch')
    output=folder/f'jev-discrete-{task}-{number:02d}'
    cfg=json.loads((ROOT/f'code/configs/jev-discrete/{task}-{variant}.json').read_text())
    cfg['controller_settings']['processing_variant']=processing;cfg['robodojo_layout_id']=layout
    if gpu is not None:cfg['gpu']=gpu
    if frozen_from:
        reference=Path(frozen_from)
        old_cfg=json.loads((reference/'protocol.json').read_text())
        allowed={'gpu','port','robodojo_layout_id'}
        if {k:v for k,v in cfg.items() if k not in allowed}!={k:v for k,v in old_cfg.items() if k not in allowed}:
            raise RuntimeError('frozen configuration changed beyond layout/GPU/port')
        import hashlib
        provenance=json.loads((reference/'generated_provenance.json').read_text())
        for name,digest in provenance['files'].items():
            if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise RuntimeError('frozen controller changed: '+name)
        snapshot=json.loads((reference/'experience_snapshot.json').read_text())
        available={hashlib.sha256(p.read_bytes()).hexdigest() for folder in ['global','jev_discrete'] for p in (ROOT/'code/experience'/folder).glob('*.md')}
        if any(r['sha256'] not in available for r in snapshot['records']):raise RuntimeError('frozen experience changed')
        commit=json.loads((reference/'provenance.json').read_text())['commit']
        for name in ['run_position_pilot.py','robodojo_position.py','structured_task_runner.py','local_rgbd_perception.py','local_digit_ocr.py','rgbd_bridge.py']:
            relative='code/scripts/'+name
            if subprocess.check_output(['git','show',commit+':'+relative],cwd=ROOT)!=(ROOT/relative).read_bytes():raise RuntimeError('frozen pipeline changed: '+relative)
        cfg['frozen_reference']=str(reference)
    usage=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.used,utilization.gpu','--format=csv,noheader,nounits'],text=True)
    memory={int(r.split(',')[0]):int(r.split(',')[1]) for r in usage.splitlines()}
    utilization={int(r.split(',')[0]):int(r.split(',')[2]) for r in usage.splitlines()}
    lease=None
    if auto_gpu:
        import fcntl
        leases=folder/'jev-discrete-gpu-leases';leases.mkdir(exist_ok=True)
        for index in sorted(memory,key=memory.get):
            if memory[index]>1024 or utilization[index]>5:continue
            handle=(leases/f'{index}.lock').open('a+')
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:handle.close();continue
            lease=handle;cfg['gpu']=index;break
        if lease is None:
            print(json.dumps(dict(event='deferred_before_trial',task=task,reason='no idle GPU; no trial reserved')),flush=True)
            return 2
    if memory[cfg['gpu']]>1024:
        print(json.dumps(dict(event='deferred_before_trial',task=task,gpu=cfg['gpu'],reason='occupied; no trial reserved')),flush=True)
        return 2
    config=ROOT/f'code/configs/jev-discrete/launched-{task}-{number:02d}.json'
    config.write_text(json.dumps(cfg,indent=2)+'\n')
    command=[cfg['robodojo_python'],'-B','-u',str(ROOT/'code/scripts/run_position_pilot.py'),'--config',str(config),'--output',str(output),'--backend','robodojo','--with-jev']
    log=folder/f'jev-discrete-{task}-{number:02d}.stdout.log'
    env=dict(os.environ,TMPDIR=str(folder/'cache/tmp'),PYTHONDONTWRITEBYTECODE='1')
    print(json.dumps(dict(event='launch',task=task,attempt=number,variant=variant,processing=processing,layout=layout,command=command)),flush=True)
    with log.open('w') as f:
        result=subprocess.run(command,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT)
    rpath=output/'structured_result.json';result_data=json.loads(rpath.read_text()) if rpath.exists() else {}
    print(json.dumps(dict(event='complete',task=task,attempt=number,returncode=result.returncode,result=result_data)),flush=True)
    if lease is not None:lease.close()
    return result.returncode

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--tasks',nargs='+',choices=TASKS,default=TASKS)
    p.add_argument('--variant',choices=['numeric','relations','evidence','hierarchical','english','compact','geometry'],default='numeric')
    p.add_argument('--processing',choices=['anchored','live','precision'],default='anchored');p.add_argument('--layout',type=int,default=0)
    p.add_argument('--gpu',type=int);p.add_argument('--auto-gpu',action='store_true');p.add_argument('--frozen-from');p.add_argument('--layouts',nargs='+',type=int)
    args=p.parse_args()
    if args.gpu is not None and len(args.tasks)!=1:p.error('--gpu requires exactly one task')
    for layout in args.layouts or [args.layout]:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            jobs=[pool.submit(run,t,args.variant,args.processing,layout,args.gpu,args.frozen_from,args.auto_gpu) for t in args.tasks]
            codes=[j.result() for j in jobs]
        if any(codes):sys.exit(1)

"""Tracked foreground batch. Trial directories reserve budget before launch."""
import argparse,concurrent.futures,json,os,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
TASKS=['general_pickup','stack_bowls','fold_clothes','press_by_number','match_and_pick_from_conveyor']

def next_attempt(folder,task):
    # Frozen historical worktrees also consumed physical task budget. A copied
    # result with the same numbered trial is counted once, not twice.
    patterns=[f'jev-discrete-{task}-[0-9][0-9]',f'pro-discrete-{task}-[0-9][0-9]',
        f'robodojo-*/code/runs/jev-discrete-{task}-[0-9][0-9]']
    numbers={int(p.name[-2:]) for pattern in patterns for p in folder.glob(pattern)}
    return max(numbers,default=0)+1

def run(task,variant,processing,layout,gpu=None,frozen_from=None,auto_gpu=False,gpu_memory_limit_mib=1024,startup_only=False,model_backend='legacy_jev',batch_views=False):
    if model_backend not in ('legacy_jev','codex_pro'):
        raise ValueError('Unknown model backend')
    folder=ROOT/'code/runs';number=next_attempt(folder,task)
    if number>50:raise RuntimeError('50 trial budget reached '+task)
    if shutil.disk_usage(folder).free<8*1024**3:raise RuntimeError('less than 8 GiB available; do not launch')
    prefix='pro-discrete' if model_backend=='codex_pro' else 'jev-discrete'
    output=folder/f'{prefix}-{task}-{number:02d}'
    cfg=json.loads((ROOT/f'code/configs/jev-discrete/{task}-{variant}.json').read_text())
    cfg['controller_settings']['processing_variant']=processing;cfg['robodojo_layout_id']=layout
    if model_backend=='codex_pro':
        from codex_pro_bridge import health, model_preflight
        health()
        model_preflight()
        cfg.update(protocol='pro-discrete-phase-gripper-development',model_backend='codex_pro',
                   jev_transport_backend='codex_pro',runtime_perception='codex_pro',
                   forbid_runtime_gpt6=False,wall_limit_seconds=6600,
                   pro_batch_views=bool(batch_views))
        cfg['controller_settings']['wall_budget_seconds']=6300
        # GPT-6 Sol/xhigh vision is slower than the historical local detector.
        # Preserve the contact/Z gate while allowing signed XY approach after
        # two observed rotation actions. Legacy Jev defaults remain unchanged.
        cfg['controller_settings']['orientation_step_cap_rad']=.35
        cfg['controller_settings']['rotation_only_observations']=2
        for key in ('api_config','jev_proxy_url','jev_transport_attempts','deepseek_key_file',
                    'deepseek_max_calls','gpt6_key_file','gpt6_base_url'):
            cfg.pop(key,None)
    if startup_only:cfg['startup_only']=True
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
        import re
        directory=Path(cfg['generated_controller']).parent
        task_source=(directory/'task_controller.py').read_text()
        memory_source=(directory/'experience.py').read_text()
        task_match=re.search(r'experience/([a-zA-Z0-9_]+)',task_source)
        global_match=re.search(r"parent/'([a-zA-Z0-9_]+)'",memory_source)
        folders=[task_match[1] if task_match else 'jev_discrete',global_match[1] if global_match else 'global']
        available={hashlib.sha256(p.read_bytes()).hexdigest() for folder in folders for p in (ROOT/'code/experience'/folder).glob('*.md')}
        if any(r['sha256'] not in available for r in snapshot['records']):raise RuntimeError('frozen experience changed')
        commit=json.loads((reference/'provenance.json').read_text())['commit']
        pipeline=['run_position_pilot.py','robodojo_position.py','structured_task_runner.py','local_rgbd_perception.py','local_digit_ocr.py','rgbd_bridge.py']
        if model_backend=='codex_pro':pipeline+=['codex_pro_bridge.py','codex_pro_bridge_server.py']
        if cfg.get('jev_transport_backend')=='curl':pipeline.append('jev_curl_transport.py')
        if cfg.get('nvidia_material_cache'):pipeline.append('nvidia_material_cache.py')
        for name in pipeline:
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
            if memory[index]>gpu_memory_limit_mib or utilization[index]>5:continue
            handle=(leases/f'{index}.lock').open('a+')
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:handle.close();continue
            lease=handle;cfg['gpu']=index;break
        if lease is None:
            print(json.dumps(dict(event='deferred_before_trial',task=task,reason='no idle GPU; no trial reserved')),flush=True)
            return 2
    if memory[cfg['gpu']]>gpu_memory_limit_mib or utilization[cfg['gpu']]>5:
        print(json.dumps(dict(event='deferred_before_trial',task=task,gpu=cfg['gpu'],reason='occupied; no trial reserved')),flush=True)
        return 2
    if cfg.get('cuda_startup_preflight',False):
        import time
        preflights=folder/'cuda-startup-preflights';preflights.mkdir(exist_ok=True)
        report=preflights/f'{task}-{number:02d}-{time.time_ns()}.json'
        probe=[cfg['robodojo_python'],'-B','-c',
               'import torch; print(torch.cuda.get_device_name(0),flush=True); '
               'x=torch.zeros(1,device="cuda:0"); torch.cuda.synchronize(); '
               'print("isolated CUDA allocation passed",flush=True)']
        try:
            checked=subprocess.run(probe,env=dict(os.environ,CUDA_VISIBLE_DEVICES=str(cfg['gpu'])),
                                   text=True,capture_output=True,timeout=30)
            check=dict(gpu=cfg['gpu'],returncode=checked.returncode,stdout=checked.stdout,stderr=checked.stderr)
        except subprocess.TimeoutExpired:
            check=dict(gpu=cfg['gpu'],returncode=None,error='isolated CUDA startup exceeded 30 seconds')
        report.write_text(json.dumps(check,indent=2)+'\n')
        if check['returncode']!=0:
            if lease is not None:lease.close()
            raise RuntimeError('CUDA startup preflight failed; no simulator started; see '+str(report))
    config=ROOT/f'code/configs/jev-discrete/launched-{prefix}-{task}-{number:02d}.json' if model_backend=='codex_pro' else ROOT/f'code/configs/jev-discrete/launched-{task}-{number:02d}.json'
    config.write_text(json.dumps(cfg,indent=2)+'\n')
    command=[cfg['robodojo_python'],'-B','-u',str(ROOT/'code/scripts/run_position_pilot.py'),'--config',str(config),'--output',str(output),'--backend','robodojo',
             '--with-model' if model_backend=='codex_pro' else '--with-jev']
    log=folder/f'{prefix}-{task}-{number:02d}.stdout.log'
    env=dict(os.environ,TMPDIR=str(folder/'cache/tmp'),PYTHONDONTWRITEBYTECODE='1')
    if model_backend=='codex_pro':env['JEV_RSI_MODEL_BACKEND']='codex_pro'
    print(json.dumps(dict(event='launch',task=task,attempt=number,variant=variant,processing=processing,layout=layout,model_backend=model_backend,command=command)),flush=True)
    with log.open('w') as f:
        result=subprocess.run(command,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT)
    rpath=output/'structured_result.json';result_data=json.loads(rpath.read_text()) if rpath.exists() else {}
    print(json.dumps(dict(event='complete',task=task,attempt=number,model_backend=model_backend,returncode=result.returncode,result=result_data)),flush=True)
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

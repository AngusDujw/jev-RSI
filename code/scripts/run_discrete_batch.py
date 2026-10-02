"""Tracked foreground batch. Trial directories reserve budget before launch."""
import argparse,concurrent.futures,json,os,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
TASKS=['general_pickup','stack_bowls','fold_clothes','press_by_number','match_and_pick_from_conveyor']

def run(task,variant,processing,layout):
    folder=ROOT/'code/runs';old=sorted(folder.glob('jev-discrete-'+task+'-[0-9][0-9]'))
    numbers=[int(p.name[-2:]) for p in old];number=max(numbers,default=0)+1
    if number>50:raise RuntimeError('50 trial budget reached '+task)
    if shutil.disk_usage(folder).free<8*1024**3:raise RuntimeError('less than 8 GiB available; do not launch')
    output=folder/f'jev-discrete-{task}-{number:02d}'
    cfg=json.loads((ROOT/f'code/configs/jev-discrete/{task}-{variant}.json').read_text())
    cfg['controller_settings']['processing_variant']=processing;cfg['robodojo_layout_id']=layout
    usage=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.used','--format=csv,noheader,nounits'],text=True)
    memory={int(r.split(',')[0]):int(r.split(',')[1]) for r in usage.splitlines()}
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
    return result.returncode

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--tasks',nargs='+',choices=TASKS,default=TASKS)
    p.add_argument('--variant',choices=['numeric','relations','evidence'],default='numeric')
    p.add_argument('--processing',choices=['anchored','live','precision'],default='anchored');p.add_argument('--layout',type=int,default=0)
    args=p.parse_args()
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        jobs=[pool.submit(run,t,args.variant,args.processing,args.layout) for t in args.tasks]
        codes=[j.result() for j in jobs]
    sys.exit(int(any(codes)))

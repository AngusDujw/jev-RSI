"""Launch four owned native workers and inspect them without touching other jobs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
from gpu_admission import admit

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]/'code/runs/company2-20261018'


def launch(name,adopt=None,resume=False,layout_offset=0,share=False,gpus=None,layout_manifest=None,processing=False,prepared_from=None,backend='luna',omit_images=False):
    folder=ROOT/name
    folder.mkdir(parents=True,exist_ok=resume)
    existing=folder/'batch.json'
    runs=json.loads(existing.read_text())['runs'] if resume and existing.exists() else []
    for gpu,task,layout in [(2,'stack_blocks',0),(5,'classify_objects',0),(6,'stack_blocks',1),(7,'classify_objects',1)]:
        if gpus and gpu not in gpus:
            continue
        layout+=layout_offset
        if any(r['gpu']==gpu for r in runs):
            continue
        if gpu==2 and adopt:
            run=(ROOT/adopt).resolve()
            if not run.is_relative_to(ROOT.resolve()):
                raise ValueError('Adopted run outside campaign')
            pid=int((run/'worker.pid').read_text())
            os.kill(pid,0)
            runs.append(dict(task=task,layout=layout,gpu=gpu,pid=pid,directory=str(run.relative_to(ROOT.resolve()))))
            (folder/'batch.json').write_text(json.dumps(dict(batch=name,framework='raw-three-rgb-v1',keep_image_task='stack_blocks',runs=runs,started=time.time()),indent=2)+'\n')
            continue
        admit(gpu,share)
        run=folder/f'{task}-l{layout}-gpu{gpu}'
        run.mkdir()
        with (run/'worker.log').open('w') as stream:
            proc=subprocess.Popen(['bash',str(HERE/'launch_worker.sh'),str(gpu),task,str(layout),str(run)],
                stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,
                env=dict(os.environ,ALLOW_CAMPAIGN_GPU_SHARE='1' if share else '0',
                         ROBO_ENABLE_PROCESSING='1' if processing else '0',
                         ROBO_PREPARED_FROM=str(Path(prepared_from).resolve()) if prepared_from else '',
                         ROBO_DECISION_BACKEND=backend,ROBO_OMIT_IMAGES='1' if omit_images else '0',
                         ROBO_LAYOUT_MANIFEST=str(Path(layout_manifest).resolve()) if layout_manifest else ''))
        (run/'worker.pid').write_text(str(proc.pid)+'\n')
        runs.append(dict(task=task,layout=layout,gpu=gpu,pid=proc.pid,directory=str(run.relative_to(ROOT)),backend=backend,
                         input_modality='text_only' if backend=='jev' or omit_images else 'rgb_and_text'))
        manifest=dict(batch=name,framework='planner-authored-processing-v2' if processing else 'raw-three-rgb-v1',
                      keep_image_task='stack_blocks' if any(r['task']=='stack_blocks' for r in runs) else runs[0]['task'],
                      runs=runs,started=time.time())
        (folder/'batch.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return runs


def status():
    rows=[]
    for manifest in ROOT.glob('*/batch.json'):
        for run in json.loads(manifest.read_text())['runs']:
            p=ROOT/run['directory']
            alive=False
            try:
                os.kill(run['pid'],0)
                alive=True
                stat=Path(f'/proc/{run["pid"]}/stat')
                if stat.exists() and stat.read_text().split()[2]=='Z':
                    alive=False
            except ProcessLookupError:
                pass
            result=dict(run,alive=alive)
            if (p/'oversight_stop.json').exists():
                result['oversight_stop']=json.loads((p/'oversight_stop.json').read_text())
            for key,path in [('outcome',p/'episode/native/evaluation_outcome.json'),('summary',p/'episode/native/summary.json')]:
                if path.exists():
                    result[key]=json.loads(path.read_text())
            error=p/'episode/error.txt'
            if error.exists():
                result['error']=error.read_text()[-1500:]
            result['decision_calls']=len(list((p/'episode/decisions').glob('*/request.json')))
            result['plan_ready']=(p/'episode/plan.json').exists()
            rows.append(result)
    return rows


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['launch','status'])
    parser.add_argument('--name')
    parser.add_argument('--adopt-stack0')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--layout-offset',type=int,default=0)
    parser.add_argument('--share-own-gpu',action='store_true')
    parser.add_argument('--gpus',type=int,nargs='+',choices=[2,5,6,7])
    parser.add_argument('--layout-manifest')
    parser.add_argument('--processing',action='store_true')
    parser.add_argument('--prepared-from')
    parser.add_argument('--backend',choices=['luna','jev'],default='luna')
    parser.add_argument('--omit-images',action='store_true')
    args=parser.parse_args()
    print(json.dumps(launch(args.name,args.adopt_stack0,args.resume,args.layout_offset,args.share_own_gpu,args.gpus,args.layout_manifest,args.processing,args.prepared_from,args.backend,args.omit_images) if args.action=='launch' else status(),indent=2))

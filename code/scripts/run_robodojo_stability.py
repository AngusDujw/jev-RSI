"""Serial additional <=30 trials, with auditable non-started deferrals.

No built-in tuning or hidden retry. Invoke one explicit candidate/layout at a
time; development and frozen validation are journaled separately.
"""
import argparse
import fcntl
import json
import shutil
from pathlib import Path
from run_discrete_batch import ROOT, TASKS, run

CAMPAIGN = '2026-10-04-robodojo-stability30'


def execute(task, variant, layout, purpose, frozen_from=None):
    folder = ROOT/'code/runs'
    journal = folder/(CAMPAIGN+'.jsonl')
    with (folder/(CAMPAIGN+'.lock')).open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = [json.loads(line) for line in journal.read_text().splitlines()] if journal.exists() else []
        released = {r['reservation'] for r in rows if r['event']=='not_started'}
        used = sum(r['event']=='reserved' and r['reservation'] not in released for r in rows)
        if used >= 30:
            return dict(event='campaign_budget_exhausted',used=used)
        if shutil.disk_usage(folder).free < 8*1024**3:
            return dict(event='deferred_disk_space',used=used,free_bytes=shutil.disk_usage(folder).free)
        old = list(folder.glob('jev-discrete-'+task+'-[0-9][0-9]'))
        attempt = max((int(p.name[-2:]) for p in old),default=0)+1
        if attempt>50:
            return dict(event='task_budget_exhausted',task=task)
        if purpose=='validation' and not frozen_from:
            raise ValueError('Validation requires a frozen successful pilot reference')
        if frozen_from:
            reference = Path(frozen_from)
            result = json.loads((reference/'structured_result.json').read_text())
            if not result.get('native',{}).get('success'):
                raise ValueError('Cannot validate a failed development reference')
        reservation = max((r.get('reservation',0) for r in rows),default=0)+1
        entry = dict(event='reserved',reservation=reservation,physical_trial=used+1,task=task,
                     attempt=attempt,variant=variant,layout=layout,purpose=purpose,frozen_from=frozen_from)
        def append(row):
            with journal.open('a') as handle:
                handle.write(json.dumps(row)+'\n')
        append(entry)
        try:
            # This 24GB host has persistent simulation contexts on every GPU.
            # A <=10GB, <=5% device leaves >=14GB for our single ~6.5GB pilot,
            # including headroom; do not kill or modify existing jobs.
            # Keep the original batch default (1GB) unchanged for other callers.
            code = run(task,variant,'precision',layout,auto_gpu=True,frozen_from=frozen_from,gpu_memory_limit_mib=10240)
            failure = None
        except Exception as exc:
            code = 1
            failure = type(exc).__name__+': '+str(exc)
        output = folder/f'jev-discrete-{task}-{attempt:02d}'
        started = output.exists() or (folder/f'jev-discrete-{task}-{attempt:02d}.stdout.log').exists()
        finished = dict(entry,event='finished' if started else 'not_started',returncode=code,error=failure)
        result_path = output/'structured_result.json'
        finished['result'] = json.loads(result_path.read_text()) if result_path.exists() else None
        append(finished)
        return finished


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task',choices=TASKS,required=True)
    parser.add_argument('--variant',required=True)
    parser.add_argument('--layout',type=int,required=True)
    parser.add_argument('--purpose',choices=['development','validation'],required=True)
    parser.add_argument('--frozen-from')
    args = parser.parse_args()
    print(json.dumps(execute(args.task,args.variant,args.layout,args.purpose,args.frozen_from)),flush=True)

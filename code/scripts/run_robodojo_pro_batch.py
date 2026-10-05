"""Bounded, separate ChatGPT Pro GPT-6 Sol/xhigh RoboDojo trial ledger."""
import argparse
import fcntl
import json
import shutil
from pathlib import Path

from run_discrete_batch import ROOT, TASKS, next_attempt, run
from codex_pro_bridge import health, model_preflight


CAMPAIGN = '2026-10-05-robodojo-pro30'


def execute(task, variant, layout, purpose, frozen_from=None):
    folder = ROOT/'code/runs'
    journal = folder/(CAMPAIGN+'.jsonl')
    with (folder/(CAMPAIGN+'.lock')).open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = [json.loads(line) for line in journal.read_text().splitlines()] if journal.exists() else []
        released = {r['reservation'] for r in rows if r['event']=='not_started'}
        used = sum(r['event']=='reserved' and r['reservation'] not in released for r in rows)
        if used >= 30:
            return dict(event='campaign_budget_exhausted', used=used)
        if shutil.disk_usage(folder).free < 8*1024**3:
            return dict(event='deferred_disk_space', used=used)
        attempt = next_attempt(folder, task)
        if attempt > 50:
            return dict(event='task_budget_exhausted', task=task)
        if purpose == 'validation':
            if not frozen_from:
                raise ValueError('Validation requires a successful Pro frozen reference')
            reference = Path(frozen_from)
            result = json.loads((reference/'structured_result.json').read_text())
            if (not result.get('native',{}).get('success') or
                    result.get('model_backend') != 'codex_pro' or
                    result.get('model') != 'gpt-6-sol' or
                    result.get('reasoning_effort') != 'xhigh'):
                raise ValueError('Frozen reference is not a successful Pro/xhigh trial')
        try:
            health()
            model_preflight()
        except Exception as exc:
            return dict(event='model_preflight_failed', physical_trials=0,
                error_type=type(exc).__name__, error=str(exc)[:300])
        reservation = max((r.get('reservation',0) for r in rows),default=0)+1
        entry = dict(event='reserved', reservation=reservation, physical_trial=used+1,
            task=task, attempt=attempt, variant=variant, layout=layout, purpose=purpose,
            frozen_from=frozen_from, model='gpt-6-sol', reasoning_effort='xhigh',
            authentication='ChatGPT')
        def append(row):
            with journal.open('a') as handle:
                handle.write(json.dumps(row)+'\n')
        append(entry)
        try:
            code = run(task, variant, 'precision', layout, auto_gpu=True,
                frozen_from=frozen_from, gpu_memory_limit_mib=10240,
                model_backend='codex_pro')
            failure = None
        except Exception as exc:
            code = 1
            failure = type(exc).__name__+': '+str(exc)
        output = folder/f'pro-discrete-{task}-{attempt:02d}'
        started = output.exists() or (folder/f'pro-discrete-{task}-{attempt:02d}.stdout.log').exists()
        finished = dict(entry, event='finished' if started else 'not_started',
            returncode=code, error=failure)
        result_path = output/'structured_result.json'
        finished['result'] = json.loads(result_path.read_text()) if result_path.exists() else None
        append(finished)
        return finished


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', choices=TASKS, required=True)
    parser.add_argument('--variant', required=True)
    parser.add_argument('--layout', type=int, required=True)
    parser.add_argument('--purpose', choices=['development','validation'], required=True)
    parser.add_argument('--frozen-from')
    args = parser.parse_args()
    print(json.dumps(execute(args.task,args.variant,args.layout,args.purpose,args.frozen_from)), flush=True)

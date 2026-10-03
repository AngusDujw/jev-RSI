"""Bounded campaign; every reserved physical trial counts, including crashes."""
import argparse
import concurrent.futures
import fcntl
import json
import subprocess
from pathlib import Path
from run_discrete_batch import ROOT, TASKS, run


def trial(task, variant, layout, campaign, limit, frozen_from=None):
    folder = ROOT / 'code/runs'
    with (folder / (campaign + '.lock')).open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        journal = folder / (campaign + '.jsonl')
        entries = [json.loads(line) for line in journal.read_text().splitlines()] if journal.exists() else []
        reservations = [row for row in entries if row['event'] == 'reserved']
        if len(reservations) >= limit:
            return {'task': task, 'event': 'budget_exhausted', 'used': len(reservations)}
        usage = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used,utilization.gpu',
                                          '--format=csv,noheader,nounits'], text=True)
        if not any(int(r.split(',')[0]) <= 1024 and int(r.split(',')[1]) <= 5 for r in usage.splitlines()):
            return {'task': task, 'event': 'deferred_no_idle_gpu'}
        old = list(folder.glob('jev-discrete-' + task + '-[0-9][0-9]'))
        attempt = max((int(p.name[-2:]) for p in old), default=0) + 1
        if attempt > 50:
            return {'task': task, 'event': 'task_budget_exhausted'}
        row = dict(event='reserved', campaign=campaign, trial=len(reservations) + 1,
                   task=task, attempt=attempt, variant=variant, layout=layout)
        with journal.open('a') as handle:
            handle.write(json.dumps(row) + '\n')
    code = run(task, variant, 'precision', layout, auto_gpu=True, frozen_from=frozen_from)
    if code == 2:
        # A raced GPU lease did not start a physical trial. Keep explicit release history.
        row['event'] = 'deferred_after_reservation'
    else:
        row['event'] = 'finished'
    result_path = folder / f'jev-discrete-{task}-{attempt:02d}/structured_result.json'
    row.update(returncode=code, result=json.loads(result_path.read_text()) if result_path.exists() else None)
    with (folder / (campaign + '.lock')).open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with journal.open('a') as handle:
            handle.write(json.dumps(row) + '\n')
    return row


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tasks', nargs='+', choices=TASKS, default=TASKS)
    parser.add_argument('--variant', choices=['english', 'compact', 'geometry', 'anchors', 'local'], required=True)
    parser.add_argument('--layout', type=int, default=0)
    parser.add_argument('--campaign', default='2026-10-04-robodojo-opt30')
    parser.add_argument('--limit', type=int, default=30)
    parser.add_argument('--frozen-from')
    args = parser.parse_args()
    if not 1 <= args.limit <= 30:
        parser.error('campaign limit must be 1..30')
    if len(set(args.tasks)) != len(args.tasks):
        parser.error('tasks must be unique within one batch')
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        jobs = [pool.submit(trial, task, args.variant, args.layout, args.campaign, args.limit, args.frozen_from)
                for task in args.tasks]
        for job in concurrent.futures.as_completed(jobs):
            print(json.dumps(job.result()), flush=True)

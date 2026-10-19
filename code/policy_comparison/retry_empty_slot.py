"""One fresh stack slot after a verified empty Pro capacity failure.

No API probe, response resampling, episode resume or automatic retry loop.
Other active task slots are left running in the original batch.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import run_batch as batch
from storage_policy import alive, sweep


def verify_empty_failure(previous):
    log=(previous/'controller.log').read_text(errors='replace')
    if 'serverOverloaded' not in log or '"tool_start"' in log or '"item_type": "agentMessage"' in log:
        raise RuntimeError('Not an empty service capacity failure; never resample a response')
    if (previous/'controller/run.json').exists():
        raise RuntimeError('Episode already started; manual audit required')
    history=previous/'controller/history.json'
    if history.exists() and json.loads(history.read_text()):
        raise RuntimeError('Previous episode has actions; refuse this helper')


def main():
    batch.validate_store()
    previous=batch.ARTIFACT_ROOT/'luna-stack_blocks-trial3-layout0-completion-20261019d'
    verify_empty_failure(previous)
    audit=batch.ROOT/'empty-capacity-retry-20261019e.json'
    if audit.exists():raise RuntimeError('One-shot retry already allocated; inspect instead of replay')
    audit.write_text(json.dumps(dict(previous=previous.name,pid=os.getpid(),
        next_run='luna-stack_blocks-trial3-layout0-completion-20261019e',
        reason='serverOverloaded before any response or native action',maximum_new_attempts=1),indent=2)+'\n')
    signal.signal(signal.SIGTERM,lambda *_:batch.STOP.set())
    signal.signal(signal.SIGINT,lambda *_:batch.STOP.set())
    while True:
        state=json.loads((previous/'status.json').read_text())
        if not alive(state.get('controller_pid')) and not alive(state.get('ssh_pid')):break
        if batch.STOP.wait(5):return 130
    # Allow the parent's finally block to finish its port cancellation and audit.
    while not json.loads((previous/'status.json').read_text()).get('infrastructure_interrupted'):
        if batch.STOP.wait(2):return 130
    sys.path.insert(0,str(batch.ROOT/'official_runtime'))
    guard=subprocess.Popen([sys.executable,'-u',str(Path(__file__).with_name('storage_policy.py')),
        '--batch-pid',str(os.getpid())])
    try:
        row=batch.run_one('stack_blocks',0,4,'luna',3,recovery='completion-20261019e')
        print(json.dumps(row),flush=True)
        return 1 if row.get('infrastructure_interrupted') else 0
    finally:
        guard.terminate()
        guard.wait(timeout=20)
        sweep()


if __name__=='__main__':sys.exit(main())

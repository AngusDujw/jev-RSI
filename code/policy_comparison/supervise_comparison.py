"""Observable service owner for a finite comparison, retention and telemetry.

No automatic episode replay or model-request retry. Agent-level recovery is
handled by the user's separately authorized AgentsDock monitoring job.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import run_batch as batch


def main():
    if not batch.ARTIFACT_ROOT.is_mount():
        raise RuntimeError('Artifact mount must be active before launch')
    entry=Path(__file__).resolve().parent
    output=batch.ROOT/'supervision-20261019b'
    output.mkdir(exist_ok=False)
    child=None
    guard=None
    def stop(*_):
        if child and child.poll() is None:child.send_signal(signal.SIGTERM)
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    with (output/'batch.log').open('w') as log, (output/'retention.log').open('w') as retention:
        child=subprocess.Popen([sys.executable,'-u',str(entry/'recover_comparison.py'),
            '--parallel','3','--recovery','completion-20261019b'],stdout=log,stderr=subprocess.STDOUT)
        guard=subprocess.Popen([sys.executable,'-u',str(entry/'storage_policy.py'),
            '--batch-pid',str(child.pid)],stdout=retention,stderr=subprocess.STDOUT)
        (output/'owner.json').write_text(json.dumps(dict(supervisor_pid=os.getpid(),
            batch_pid=child.pid,retention_pid=guard.pid,parallel=3,automatic_replay=False),indent=2)+'\n')
        while child.poll() is None:
            command='nvidia-smi --query-gpu=index,memory.used,memory.free,utilization.gpu --format=csv,noheader; free -b; docker ps --format "{{.Names}} {{.Status}}"'
            sample=dict(time=time.time(),batch_pid=child.pid)
            try:
                result=subprocess.run(batch.SSH+['--','server02',command],capture_output=True,text=True,timeout=30)
                sample.update(returncode=result.returncode,resource_snapshot=result.stdout,error=result.stderr[-1000:])
            except subprocess.SubprocessError as error:sample['error']=str(error)
            (output/'health.json').write_text(json.dumps(sample,indent=2)+'\n')
            print(json.dumps(sample),flush=True)
            for _ in range(60):
                if child.poll() is not None:break
                time.sleep(1)
        try:guard.wait(timeout=150)
        except subprocess.TimeoutExpired:
            guard.terminate()
            guard.wait(timeout=20)
        result=dict(batch_exit=child.returncode,retention_exit=guard.returncode,finished_at=time.time())
        (output/'exit.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result),flush=True)
    return child.returncode


if __name__=='__main__':sys.exit(main())

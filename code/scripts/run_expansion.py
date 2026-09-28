"""Sequential, resumable developmental sampling; stops after three failed runs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from batch_guard import record, stopped


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--start-seed', type=int, default=10)
    p.add_argument('--count', type=int, default=30)
    p.add_argument('--coordinator')
    a = p.parse_args()
    root = Path(a.output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(Path(a.config).read_text())
    failures = 0
    for seed in range(a.start_seed, a.start_seed+a.count):
        folder = root/f'seed-{seed}'
        if (root/'STOP').exists() or stopped(a.coordinator):
            break
        if folder.exists():
            raise RuntimeError(f'Refusing overwrite: {folder}')
        command = [cfg['embodied_python'], '-B', 'code/scripts/run_position_pilot.py',
                   '--config', a.config, '--output', str(folder), '--with-jev', '--seed', str(seed)]
        started = time.time()
        with (root/f'seed-{seed}.log').open('x') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        summary = json.loads((folder/'summary.json').read_text()) if (folder/'summary.json').exists() else {}
        row = dict(seed=seed, returncode=result.returncode, started=started, finished=time.time(), summary=summary)
        with (root/'batch.jsonl').open('a') as stream:
            stream.write(json.dumps(row)+'\n')
        print(json.dumps(row), flush=True)
        record(a.coordinator,row,result.returncode==0)
        failures = failures+1 if result.returncode else 0
        if failures >= 3:
            (root/'STOP').write_text('Three consecutive failures; user escalation required.\n')
            break
    (root/'finished.json').write_text(json.dumps(dict(finished=time.time(), consecutive_failures=failures)))


if __name__ == '__main__':
    main()

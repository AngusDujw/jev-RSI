"""Admit one project command only when a GPU has no compute clients."""
import argparse
import json
from pathlib import Path
import subprocess
import time


def idle_devices(gpu_text, client_text, memory_limit=128):
    clients = {line.split(',')[0].strip() for line in client_text.splitlines() if line.strip()}
    result = []
    for line in gpu_text.splitlines():
        index, uuid, memory, utilization = [v.strip() for v in line.split(',')]
        if uuid not in clients and int(memory) <= memory_limit and int(utilization) == 0:
            result.append(int(index))
    return result


def snapshot():
    def query(fields):
        return subprocess.check_output(['nvidia-smi', fields, '--format=csv,noheader,nounits'], text=True, timeout=15)
    gpus = query('--query-gpu=index,uuid,memory.used,utilization.gpu')
    clients = query('--query-compute-apps=gpu_uuid,pid')
    return idle_devices(gpus, clients)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--status', type=Path, required=True)
    parser.add_argument('--wait-seconds', type=int, default=3600)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or command.count('{gpu}') != 1:
        parser.error('Command must contain one separate {gpu} argument')
    args.status.parent.mkdir(parents=True, exist_ok=True)
    def status(phase, **detail):
        record = dict(phase=phase, timestamp=time.time(), **detail)
        args.status.write_text(json.dumps(record, indent=2)+'\n')
        print(json.dumps(record), flush=True)
    deadline = time.monotonic()+args.wait_seconds
    while time.monotonic() < deadline:
        available = snapshot()
        if available:
            device = available[0]
            time.sleep(3)
            if device in snapshot():
                status('admitted', gpu=device, condition='No compute clients; memory<=128MiB; utilization=0; checked twice')
                actual = [str(device) if v == '{gpu}' else v for v in command]
                completed = subprocess.run(actual, check=False)
                status('finished', gpu=device, returncode=completed.returncode)
                return completed.returncode
        status('waiting_for_empty_gpu', scope='No simulation or model request started by this queue')
        time.sleep(min(30, max(0, deadline-time.monotonic())))
    status('not_admitted', reason='No empty GPU within admission window; no physical episode attempted')
    return 3


if __name__ == '__main__':
    raise SystemExit(main())

"""Admit only idle GPUs or sharing with this campaign's registered workers."""
import json
import os
from pathlib import Path
import subprocess
import sys


def admit(gpu,share=False):
    raw=subprocess.check_output(['nvidia-smi','--id='+str(gpu),'--query-gpu=memory.used,memory.free',
                                 '--format=csv,noheader,nounits'],text=True)
    used,free=map(int,raw.strip().split(','))
    if used<=256:
        return
    if not share or free<8192:
        raise RuntimeError(f'GPU {gpu}: occupied or insufficient headroom ({used} used, {free} free MiB)')
    root=Path(__file__).resolve().parents[1]/'runs/company2-20261018'
    known=set()
    for manifest in root.glob('*/batch.json'):
        for run in json.loads(manifest.read_text())['runs']:
            pid=run['pid']
            cmd=Path(f'/proc/{pid}/cmdline')
            if cmd.exists() and b'planner_advancer/runtime.py' in cmd.read_bytes():
                known.add(pid)
    raw=subprocess.check_output(['nvidia-smi','--id='+str(gpu),'--query-compute-apps=pid',
                                 '--format=csv,noheader,nounits'],text=True)
    occupants={int(line.strip()) for line in raw.splitlines() if line.strip().isdigit()}
    if not occupants or not occupants.issubset(known) or len(occupants)>=3:
        raise RuntimeError(f'GPU {gpu}: unowned processes or three-worker limit; refusing to share')


if __name__=='__main__':
    admit(int(sys.argv[1]),os.environ.get('ALLOW_CAMPAIGN_GPU_SHARE')=='1')

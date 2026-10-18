"""Foreground retention companion: discard binary outputs after each trial.

Images needed by the original agent remain available throughout its episode.
Only this comparison's artifacts are touched; model inputs are never changed.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import time

ROOT = Path('/home/ykj/project/gpt6/benchmark/gpt_as_policy_robodojo/runs/server02-policy-comparison-20261018')
LOCAL = Path(__file__).resolve().parents[1] / 'runs/server02-policy-comparison-20261018/local_state'
BINARY = {'.png', '.jpg', '.jpeg', '.webp', '.mp4', '.mov', '.npz', '.npy'}


def alive(pid):
    if not pid:
        return False
    try:
        state = Path(f'/proc/{int(pid)}/stat').read_text().split(') ', 1)[1][0]
        return state != 'Z'
    except (OSError, ValueError):
        return False


def prune(run, state):
    if alive(state.get('controller_pid')) or alive(state.get('ssh_pid')):
        return None
    if state.get('status') not in ('failed', 'controller_finished'):
        return None
    receipt = run / 'compact_retention.json'
    if receipt.exists():
        return None
    counts = dict(deleted_files=0, deleted_bytes=0, local_state_bytes=0)
    campaign = '/home/user/ykj/project/gpt6/jev-RSI/code/runs/server02-policy-comparison-20261018'
    # Native simulator outputs belong to its container UID. Use that same UID
    # with only this campaign mounted, without chmod or host Python changes.
    command = shlex.join(['docker','run','--rm','--user','0:0','--network','none',
        '--runtime','runc','--entrypoint','/isaac-sim/python.sh',
        '-v',campaign+':'+campaign+':rw','nvcr.io/nvidia/isaac-sim:5.1.0',
        campaign+'/prune_trial_media.py',run.name])
    result = subprocess.run(['ssh','-F','/dev/null','-S',
        '/home/ykj/.ssh/s2-policy-20261018.ctl','--','server02', command],
        check=True,capture_output=True,text=True,timeout=120)
    counts.update(json.loads(result.stdout))
    local = LOCAL/run.name
    if local.is_dir() and not local.is_symlink():
        counts['local_state_bytes'] = sum(p.stat().st_size for p in local.rglob('*') if p.is_file() and not p.is_symlink())
        shutil.rmtree(local)
    receipt.write_text(json.dumps(dict(policy='Text results retained; binary media and large raw logs discarded after controller and simulator exit.', **counts), indent=2)+'\n')
    return dict(run=run.name, **counts)


def sweep():
    for path in ROOT.glob('*/status.json'):
        try:
            result = prune(path.parent, json.loads(path.read_text()))
            if result:
                print(json.dumps(result), flush=True)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            print(json.dumps(dict(run=path.parent.name, retention_error=str(error))), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch-pid', type=int, required=True)
    args = parser.parse_args()
    if not ROOT.is_mount():
        raise RuntimeError('Expected this comparison remote artifact mount')
    while alive(args.batch_pid):
        sweep()
        time.sleep(20)
    sweep()


if __name__ == '__main__':
    main()

"""Remove generated binary outputs from one completed comparison trial only."""
import json
import os
from pathlib import Path
import re
import sys

CAMPAIGN = Path('/home/user/ykj/project/gpt6/jev-RSI/code/runs/server02-policy-comparison-20261018')


def prune(run):
    counts = dict(deleted_files=0, deleted_bytes=0)
    for directory, dirs, files in os.walk(run, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(directory)/d).is_symlink()]
        for name in files:
            path = Path(directory)/name
            if path.is_symlink():
                continue
            size = path.stat().st_size
            if path.suffix.lower() in {'.png','.jpg','.jpeg','.webp','.mp4','.mov','.npz','.npy'} or (
                    size >= 4*1024**2 and path.suffix in ('.jsonl','.log')):
                path.unlink()
                counts['deleted_files'] += 1
                counts['deleted_bytes'] += size
    return counts


if __name__ == '__main__':
    name = sys.argv[1]
    if not re.fullmatch(r'(luna|decisions)-(stack_blocks|classify_objects)-(trial\d+-)?layout\d+', name):
        raise ValueError('Not a comparison trial name')
    run = CAMPAIGN/name
    if run.is_symlink() or run.resolve().parent != CAMPAIGN:
        raise ValueError('Not an owned comparison directory')
    state = json.loads((run/'status.json').read_text())
    if state.get('status') not in ('failed','controller_finished'):
        raise ValueError('Trial is not finished')
    print(json.dumps(prune(run)))

"""User-authorized image retention for this campaign's registered runs only."""
import argparse
import json
import os
from pathlib import Path
import shutil
import time


def prune(root):
    root=Path(root).resolve()
    free=shutil.disk_usage(root).free
    if free>=20*1024**3:
        return dict(free_bytes=free,deleted=0)
    removed=[]
    for manifest in root.glob('*/batch.json'):
        batch=json.loads(manifest.read_text())
        keep=batch['keep_image_task']
        for record in batch['runs']:
            if record['task']==keep:
                continue
            run=(root/record['directory']).resolve()
            if not run.is_relative_to(root) or run.is_symlink():
                raise ValueError('Run outside campaign root')
            pid=run/'worker.pid'
            if pid.exists():
                try:
                    value=int(pid.read_text())
                    os.kill(value,0)
                    stat=Path(f'/proc/{value}/stat')
                    if not stat.exists() or stat.read_text().split()[2]!='Z':
                        continue
                except ProcessLookupError:
                    pass
            for path in run.rglob('*'):
                if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(run):
                    continue
                if path.suffix.lower() not in ('.png','.jpg','.jpeg','.mp4','.npz'):
                    continue
                if path.suffix=='.npz':
                    import numpy as np
                    with np.load(path,allow_pickle=False) as data:
                        state={k:data[k].tolist() for k in data.files if not k.startswith('cam_')}
                    path.with_suffix('.state.json').write_text(json.dumps(state)+'\n')
                removed.append(dict(path=str(path.relative_to(root)),bytes=path.stat().st_size,task=record['task']))
                path.unlink()
    if removed:
        with (root/'retention.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(time=time.time(),free_bytes_before=free,removed=removed))+'\n')
    return dict(free_bytes=shutil.disk_usage(root).free,deleted=len(removed))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('root')
    parser.add_argument('--watch',action='store_true')
    args=parser.parse_args()
    while True:
        print(json.dumps(prune(args.root)),flush=True)
        if not args.watch:
            break
        time.sleep(45)

#!/usr/bin/env python3
"""Plan and unlink old generated media/large logs within explicit output roots."""
import argparse
from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
import re
import stat
from zoneinfo import ZoneInfo

EXCLUDED = {'.git','.venv','venv','.conda','envs','site-packages','node_modules',
    'assets','weights','models','checkpoints','official_runtime','framework_source',
    'runtime-robodojo','source','src','__pycache__','.deps','hybrid_rollout','gpt-as-policy','robodojo'}
MEDIA = {'.png','.jpg','.jpeg','.webp','.bmp','.tif','.tiff','.gif','.svg',
         '.mp4','.mov','.avi','.mkv','.m4v','.webm','.exr'}
TRACE_DIRS = {'observations','execution','executions','proposals','predictions',
    'frames','trajectory','trajectories','recordings','captures','sim','simulator','native','traces'}
DATE = re.compile(r'(?<!\d)(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)(?!\d)')


def protected_date(parts, cutoff):
    for part in parts:
        for found in DATE.finditer(part):
            try:
                date = datetime(*map(int,found.groups())).date()
            except ValueError:
                continue
            if date >= cutoff:
                return True
    return False


def kind(path, relative, size):
    suffix = path.suffix.lower()
    stem = path.stem.lower()
    if suffix in MEDIA:
        return 'media'
    if suffix in {'.npy','.npz','.pkl','.msgpack'} and any(p.lower() in TRACE_DIRS for p in relative.parts[:-1]):
        return 'array_trace'
    if size >= 8*1024**2 and suffix in {'.log','.jsonl','.ndjson','.out','.err'}:
        return 'large_log'
    if size >= 8*1024**2 and suffix == '.json' and any(x in stem for x in ('request','response','payload','raw_observation')):
        return 'large_raw_request'
    if size >= 8*1024**2 and suffix == '.csv' and any(x in stem for x in ('trace','tracking','trajectory','joint','action','eef')):
        return 'large_csv_trace'
    if size >= 1024**2 and 'tfevents' in path.name:
        return 'tensorboard_event'
    return None


def plan(args):
    cutoff_date = datetime.fromisoformat(args.before).date()
    boundary = datetime.combine(cutoff_date,datetime.min.time(),tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
    roots = [Path(p).absolute() for p in args.root]
    seen = set()
    summary = Counter()
    args.manifest.parent.mkdir(parents=True,exist_ok=True)
    with args.manifest.open('x') as output:
        output.write(json.dumps(dict(type='header',roots=list(map(str,roots)),
            before_exclusive=args.before,timezone='Asia/Shanghai',policy='generated_media_and_large_raw_logs_only; preserve summaries/source/env/weights; no symlinks or mount traversal'))+'\n')
        for root in roots:
            if not root.exists() or root.is_symlink():
                continue
            device = root.stat().st_dev
            for directory, dirs, files in os.walk(root,followlinks=False):
                here = Path(directory)
                kept = []
                for name in dirs:
                    child = here/name
                    if name.lower() in EXCLUDED or child.is_symlink() or (child/".git").exists():
                        continue
                    try:
                        if child.stat().st_dev != device:
                            continue
                    except OSError:
                        continue
                    if protected_date(child.relative_to(root).parts,cutoff_date):
                        continue
                    kept.append(name)
                dirs[:] = kept
                for name in files:
                    path = here/name
                    try:
                        info = path.lstat()
                    except OSError:
                        continue
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_dev != device:
                        continue
                    if info.st_mtime >= boundary:
                        continue
                    relative = path.relative_to(root)
                    if protected_date(relative.parts,cutoff_date):
                        continue
                    category = kind(path,relative,info.st_size)
                    if not category or str(path) in seen:
                        continue
                    seen.add(str(path))
                    record=dict(type='file',root=str(root),path=str(path),size=info.st_size,
                        inode=info.st_ino,device=info.st_dev,mtime_ns=info.st_mtime_ns,kind=category)
                    output.write(json.dumps(record)+'\n')
                    summary['files']+=1; summary['bytes']+=info.st_size
                    summary[category+'_files']+=1
    print(json.dumps(dict(manifest=str(args.manifest),**summary)))


def apply(args):
    totals=Counter()
    with args.manifest.open() as manifest, args.journal.open('x') as journal:
        header=json.loads(next(manifest))
        roots=[Path(p).resolve() for p in header['roots']]
        for line in manifest:
            item=json.loads(line); path=Path(item['path'])
            try:
                info=path.lstat()
                if path.is_symlink() or not any(path.resolve().is_relative_to(root) for root in roots):
                    raise ValueError('Path escaped an authorized output root')
                if (info.st_ino,info.st_dev,info.st_mtime_ns,info.st_size,info.st_nlink) != (
                    item['inode'],item['device'],item['mtime_ns'],item['size'],1):
                    raise ValueError('Changed since plan; preserve it')
                path.unlink()
                totals['deleted_files']+=1;totals['deleted_bytes']+=item['size']
                journal.write(json.dumps(dict(path=str(path),bytes=item['size'],status='deleted'))+'\n')
            except (OSError,ValueError) as exc:
                totals['skipped_files']+=1
                journal.write(json.dumps(dict(path=str(path),status='preserved',reason=str(exc)))+'\n')
    args.summary.write_text(json.dumps(dict(**totals,manifest=str(args.manifest),journal=str(args.journal)),indent=2)+'\n')
    print(json.dumps(dict(**totals)))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',choices=['plan','apply'])
    parser.add_argument('--root',action='append',default=[])
    parser.add_argument('--before',default='2026-10-16')
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--journal',type=Path)
    parser.add_argument('--summary',type=Path)
    args=parser.parse_args()
    if args.operation=='plan':plan(args)
    else:
        if args.journal is None or args.summary is None:parser.error('apply requires journal and summary')
        apply(args)

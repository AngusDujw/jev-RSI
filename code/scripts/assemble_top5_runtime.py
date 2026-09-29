"""Build an isolated RoboDojo runtime; shared assets are file symlinks only."""
import argparse
import json
from pathlib import Path
import shutil
from prepare_top5_assets import valid


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--existing',type=Path,required=True)
    p.add_argument('--runtime',type=Path,required=True)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--verify',action='store_true')
    a=p.parse_args()
    if a.runtime.resolve()==a.existing.resolve():
        raise ValueError('Runtime must be isolated from existing source')
    if a.verify:
        entries=json.loads(a.manifest.read_text())['files']
        bad=[e['rfilename'] for e in entries if not valid(a.runtime/e['rfilename'],e)]
        if bad: raise RuntimeError('Missing or invalid assets: '+repr(bad[:20]))
        print('Verified official assets:',len(entries)); return
    a.runtime.mkdir(parents=True,exist_ok=False)
    if shutil.disk_usage(a.runtime).free<20_000_000_000:
        raise RuntimeError('Less than 20GB free')
    for source in a.existing.iterdir():
        if source.name.startswith('.') or source.name=='Assets': continue
        target=a.runtime/source.name
        if source.name in ('third_party','XPolicyLab'):
            target.symlink_to(source.resolve(),target_is_directory=True)
        elif source.is_dir():
            shutil.copytree(source,target,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        else: shutil.copy2(source,target)
    count=0
    for source in (a.existing/'Assets').rglob('*'):
        if not source.is_file(): continue
        target=a.runtime/source.relative_to(a.existing)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.symlink_to(source.resolve()); count+=1
    print('Runtime created; reused individual asset files:',count)


if __name__=='__main__': main()

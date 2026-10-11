"""Lossless archive of simulator duplicates created by this campaign only.

Keep per-stage frames, requests, responses and commands directly readable.
Never touch earlier experiments or any incomplete campaign trial.
"""
import hashlib
import json
import shutil
import tarfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    sha=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):sha.update(chunk)
    return sha.hexdigest()


def main():
    journal=ROOT/'code/runs/2026-10-04-robodojo-opt30.jsonl'
    for line in journal.read_text().splitlines():
        row=json.loads(line)
        if row['event']!='finished':continue
        folder=ROOT/'code/runs'/f"jev-discrete-{row['task']}-{row['attempt']:02d}"
        source=folder/'simulator';target=folder/'simulator-raw.tar.gz'
        if not source.exists() or not (folder/'summary.json').exists():continue
        if target.exists():continue
        files=sorted(p for p in source.rglob('*') if p.is_file())
        if any(p.is_symlink() for p in files):raise RuntimeError('Refuse archive with symlinks')
        hashes={str(p.relative_to(folder)):digest(p) for p in files}
        before=sum(p.stat().st_size for p in files)
        partial=folder/'simulator-raw.tar.gz.partial'
        with tarfile.open(partial,'w:gz',compresslevel=1) as tar:tar.add(source,arcname='simulator')
        with tarfile.open(partial,'r:gz') as tar:
            verified={}
            for member in tar:
                if not member.isfile():continue
                sha=hashlib.sha256()
                with tar.extractfile(member) as f:
                    for chunk in iter(lambda:f.read(1024*1024),b''):sha.update(chunk)
                verified[member.name]=sha.hexdigest()
        if verified!=hashes:raise RuntimeError('Archive verification failed; originals retained')
        partial.rename(target)
        manifest=dict(campaign=row['campaign'],trial=row['trial'],files=hashes,
                      archive_sha256=digest(target),original_bytes=before,archive_bytes=target.stat().st_size)
        (folder/'simulator-archive-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        shutil.rmtree(source)  # Only files this authorized campaign created, after full SHA verification.
        print(json.dumps(dict(run=folder.name,original_bytes=before,archive_bytes=target.stat().st_size,
                              verified_files=len(hashes))),flush=True)


if __name__=='__main__':main()

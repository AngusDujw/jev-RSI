"""Losslessly compress finished campaign depth; verify original manifest first.

Only this campaign's generated NPY files are replaced. Local original backups
must have been independently verified before invoking this on the server.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sha_stream(handle):
    digest = hashlib.sha256()
    for block in iter(lambda: handle.read(1024 * 1024), b''):
        digest.update(block)
    return digest.hexdigest()


def archive_file(path, expected):
    target = path.with_suffix(path.suffix + '.gz')
    if path.exists():
        if path.is_symlink() or path.stat().st_size != expected['bytes']:
            raise RuntimeError('Unexpected source: ' + str(path))
        with path.open('rb') as source:
            if sha_stream(source) != expected['sha256']:
                raise RuntimeError('Source differs from verified backup: ' + str(path))
    if not target.exists():
        partial = target.with_suffix(target.suffix + '.partial')
        if partial.exists():
            raise RuntimeError('Inspect unfinished archive before resuming: ' + str(partial))
        with path.open('rb') as source, partial.open('xb') as output:
            with gzip.GzipFile(filename='', mode='wb', fileobj=output, compresslevel=1, mtime=0) as compressed:
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    compressed.write(block)
            output.flush()
            os.fsync(output.fileno())
        with gzip.open(partial, 'rb') as restored:
            if sha_stream(restored) != expected['sha256']:
                raise RuntimeError('Restore mismatch; original retained')
        partial.rename(target)
    with gzip.open(target, 'rb') as restored:
        if sha_stream(restored) != expected['sha256']:
            raise RuntimeError('Existing archive restore mismatch; original retained')
    with target.open('rb') as archive:
        record = dict(expected, archive_sha256=sha_stream(archive), archive_bytes=target.stat().st_size)
    if path.exists():
        path.unlink()  # Only our manifest-verified generated file, after exact restore check.
    return record


def load_depth(path):
    """Load a directly saved or losslessly compressed depth snapshot."""
    import numpy as np
    path = Path(path)
    if path.exists():
        return np.load(path, allow_pickle=False)
    with gzip.open(path.with_suffix(path.suffix + '.gz'), 'rb') as handle:
        return np.load(handle, allow_pickle=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', required=True)
    parser.add_argument('--verified-original-manifest', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.verified_original_manifest.read_text())
    if manifest['campaign'] != args.campaign:
        raise RuntimeError('Campaign and manifest differ')
    rows = [json.loads(line) for line in (ROOT / 'code/runs' / (args.campaign + '.jsonl')).read_text().splitlines()]
    for row in rows:
        if row['event'] != 'finished':
            continue
        folder = ROOT / 'code/runs' / f"jev-discrete-{row['task']}-{row['attempt']:02d}"
        if not (folder / 'summary.json').exists() or not (folder / 'structured_result.json').exists():
            raise RuntimeError('Not a completed owned trial: ' + str(folder))
        prefix = str(folder.relative_to(ROOT)) + '/'
        record_path = folder / 'depth-archive-manifest.json'
        records = json.loads(record_path.read_text()) if record_path.exists() else {}
        for name, expected in manifest['files'].items():
            if not name.startswith(prefix) or not name.endswith('-depth.npy') or '/frame-' not in name:
                continue
            path = ROOT / name
            records[name] = archive_file(path, expected)
            pending = record_path.with_suffix('.json.partial')
            pending.write_text(json.dumps(records, indent=2) + '\n')
            pending.replace(record_path)
        print(json.dumps(dict(run=folder.name, files=len(records),
                              saved_bytes=sum(r['bytes']-r['archive_bytes'] for r in records.values()))), flush=True)


if __name__ == '__main__':
    main()

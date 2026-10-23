"""Hash explicit frozen assets and report USD dependency resolution without Kit."""
import argparse
import hashlib
import json
from pathlib import Path

from pxr import UsdUtils


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data-root', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    root = args.data_root.resolve()
    manifest = json.loads((root/'.roboicl-assets.json').read_text())
    layers, errors, unresolved = [], [], set()
    for row in manifest['files']:
        path = root/row['path']
        if not path.is_file() or path.stat().st_size != row['size']:
            raise ValueError('Missing or truncated frozen file: ' + str(path))
        digest = hashlib.sha256()
        with path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(2**20), b''):
                digest.update(chunk)
        if digest.hexdigest() != row['sha256']:
            raise ValueError('Frozen file hash mismatch: ' + str(path))
        if path.suffix.lower() in ('.usd', '.usda', '.usdc', '.usdz'):
            try:
                found_layers, assets, missing = UsdUtils.ComputeAllDependencies(str(path))
                layers.append({'root': row['path'], 'layer_count': len(found_layers),
                               'asset_count': len(assets), 'unresolved': list(missing)})
                unresolved.update(missing)
            except Exception as exc:
                errors.append({'root': row['path'], 'error': str(exc)})
    result = {'hashed_files': len(manifest['files']),
              'hashed_bytes': sum(row['size'] for row in manifest['files']),
              'usd_roots': layers, 'errors': errors, 'unresolved': sorted(unresolved),
              'note': 'Core MDL module references must be checked against the Isaac runtime; camera preflight remains mandatory.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'usd_roots'}))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

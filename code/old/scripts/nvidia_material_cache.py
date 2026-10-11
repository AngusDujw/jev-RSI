"""Verified project-local mirror of the scene's public NVIDIA MDL resources.

Preserves source bytes and relative texture paths. No USD, physics or material
parameters are edited. Install aliases only after Kit has loaded omni.client.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urljoin, urlparse

PREFIX = 'https://omniverse-content-production.s3.us-west-2.amazonaws.com/Materials/2023_1/Base/'
MATERIALS = ('Metals/Aluminum_Cast.mdl', 'Metals/Aluminum_Anodized.mdl', 'Plastics/Plastic_ABS.mdl')


def verify(root):
    root = Path(root).resolve()
    manifest = json.loads((root / 'manifest.json').read_text())
    if manifest['prefix'] != PREFIX or not manifest['files']:
        raise ValueError('Unexpected NVIDIA material manifest')
    available = set()
    for row in manifest['files']:
        relative = Path(row['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Material path escapes project cache')
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Material cache symlink is not permitted')
        data = path.read_bytes()
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('Material cache checksum mismatch: ' + str(relative))
        if row['url'] != PREFIX + relative.as_posix():
            raise ValueError('Material source URL mismatch')
        available.add(relative.as_posix())
    for relative in MATERIALS:
        if relative not in available:
            raise ValueError('Missing required MDL: ' + relative)
        for texture in re.findall(r'texture_2d\("([^"\n]+)"', (root / relative).read_text()):
            resolved = urljoin(PREFIX + relative, texture)
            if not resolved.startswith(PREFIX) or resolved[len(PREFIX):] not in available:
                raise ValueError('Missing MDL texture dependency: ' + resolved)
    return manifest


def install(root):
    manifest = verify(root)
    import omni.client
    omni.client.set_alias(PREFIX, Path(root).resolve().as_uri() + '/')
    # Exercise the actual client used by the renderer, not just curl.
    for row in manifest['files']:
        result, _, content = omni.client.read_file(row['url'])
        if result != omni.client.Result.OK or hashlib.sha256(bytes(content)).hexdigest() != row['sha256']:
            raise RuntimeError('Native material alias failed: ' + row['path'])
    print(json.dumps(dict(event='material_cache_verified', files=len(manifest['files']),
                          bytes=sum(r['bytes'] for r in manifest['files']), prefix=PREFIX)), flush=True)


def prepare(root, proxy):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'manifest.json').exists():
        return verify(root)
    pending, rows = list(MATERIALS), {}
    while pending:
        relative = pending.pop(0)
        if relative in rows:
            continue
        url = PREFIX + relative
        if urlparse(url).hostname != urlparse(PREFIX).hostname or '..' in Path(relative).parts:
            raise ValueError('Unexpected material URL')
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError('Unverified existing resource; preserve it: ' + str(target))
        partial = target.with_suffix(target.suffix + '.download')
        if partial.exists():
            raise FileExistsError(partial)
        command = ['curl', '--fail', '--silent', '--show-error', '--location',
                   '--proto', '=https', '--proxy', proxy, '--noproxy', '',
                   '--connect-timeout', '10', '--max-time', '60', '--max-filesize', '16777216',
                   '--output', str(partial), url]
        subprocess.run(command, check=True, timeout=65)
        data = partial.read_bytes()
        if sum(row['bytes'] for row in rows.values()) + len(data) > 128 * 1024**2:
            raise RuntimeError('Material cache exceeds 128 MiB guard')
        if relative.endswith('.mdl'):
            text = data.decode()
            if not text.lstrip().startswith('mdl '):
                raise ValueError('Not an MDL resource')
            for texture in re.findall(r'texture_2d\("([^"\n]+)"', text):
                resolved = urljoin(url, texture)
                if not resolved.startswith(PREFIX):
                    raise ValueError('Texture outside material mirror')
                pending.append(resolved[len(PREFIX):])
        elif relative.endswith('.png') and not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Not a PNG texture')
        partial.rename(target)
        rows[relative] = dict(path=relative, url=url, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    manifest = dict(prefix=PREFIX, files=list(rows.values()), source='NVIDIA public original bytes')
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return verify(root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--proxy', required=True)
    args = parser.parse_args()
    manifest = prepare(args.root, args.proxy)
    print(json.dumps(dict(files=len(manifest['files']), bytes=sum(r['bytes'] for r in manifest['files']))))

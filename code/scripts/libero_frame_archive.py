"""Lossless, byte-restorable archival of our completed LIBERO control frames.

Policy inputs and recorded decisions are untouched. Source removal is allowed
only after every decoded frame reproduces the original PNG SHA256 exactly.
"""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

import cv2
import numpy as np


def sha(data):
    return hashlib.sha256(data).hexdigest()


def exact_read(stream, size):
    chunks = bytearray()
    while len(chunks) < size:
        block = stream.read(size - len(chunks))
        if not block:
            raise RuntimeError('Truncated lossless frame stream')
        chunks.extend(block)
    return bytes(chunks)


def decode(video, rows, shape, restore=False):
    height, width, channels = shape
    assert channels == 3
    proc = subprocess.Popen(['ffmpeg', '-hide_banner', '-loglevel', 'error',
        '-i', str(video), '-f', 'rawvideo', '-pix_fmt', 'bgr24', 'pipe:1'],
        stdout=subprocess.PIPE)
    try:
        for row in rows:
            data = exact_read(proc.stdout, height * width * channels)
            assert sha(data) == row['pixel_sha256'], row['name']
            frame = np.frombuffer(data, np.uint8).reshape(shape)
            ok, png = cv2.imencode('.png', frame)
            assert ok and sha(png.tobytes()) == row['png_sha256'], row['name']
            if restore:
                target = video.parent / row['name']
                if target.exists():
                    assert sha(target.read_bytes()) == row['png_sha256']
                else:
                    target.write_bytes(png.tobytes())
        assert not proc.stdout.read(1), 'Unexpected additional frame'
        assert proc.wait() == 0
    finally:
        proc.stdout.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def archive(run, remove_source=False, expected_inventory=None):
    run = Path(run).resolve()
    assert (run / 'result.json').is_file(), 'Never archive an active episode'
    assert any(part.startswith(('2026-10-03-libero-recovery30-',
        '2026-10-04-libero-verify20-', '2026-10-04-libero-top5-',
        '2026-10-05-pro-sol-'))
        for part in run.parts), 'Only this conversation owned campaigns'
    manifest_path = run / 'control-frame-archive.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        for group in manifest['groups']:
            assert sha((run / group['video']).read_bytes()) == group['video_sha256']
            decode(run / group['video'], group['frames'], group['shape'])
    else:
        groups = []
        for camera in ['agentview', 'robot0_eye_in_hand']:
            files = sorted(f for f in run.glob('*-' + camera + '.png')
                if re.fullmatch(r'\d{4,}-.+-' + camera + r'\.png', f.name))
            if not files:
                continue
            video = run / ('control-frames-' + camera + '.mkv')
            assert not video.exists(), 'Do not overwrite an archive'
            first = cv2.imread(str(files[0])); height, width, channels = first.shape
            rows = []
            enc = subprocess.Popen(['ffmpeg', '-hide_banner', '-loglevel', 'error',
                '-f', 'rawvideo', '-pixel_format', 'bgr24', '-video_size',
                f'{width}x{height}', '-framerate', '10', '-i', 'pipe:0',
                '-c:v', 'libx264rgb', '-crf', '0', '-preset', 'medium', '-pix_fmt', 'bgr24',
                '-threads', '2', str(video)], stdin=subprocess.PIPE)
            try:
                for path in files:
                    png = path.read_bytes()
                    if expected_inventory is not None:
                        key = str(path.relative_to(Path(__file__).resolve().parents[2]))
                        assert sha(png) == expected_inventory[key]['sha256'], key
                    frame = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
                    assert frame.shape == first.shape
                    raw = frame.tobytes()
                    rows.append(dict(name=path.name, png_sha256=sha(png),
                        pixel_sha256=sha(raw), original_bytes=len(png)))
                    enc.stdin.write(raw)
                enc.stdin.close()
                assert enc.wait() == 0
            finally:
                if enc.poll() is None:
                    enc.kill(); enc.wait()
            decode(video, rows, list(first.shape))
            groups.append(dict(video=video.name, video_sha256=sha(video.read_bytes()),
                shape=list(first.shape), frames=rows))
        manifest = dict(codec='libx264rgb CRF0 RGB lossless, decoded bgr24',
            restoration='Default OpenCV PNG encoder must reproduce every original PNG SHA256',
            opencv_version=cv2.__version__, groups=groups)
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    removed = 0
    if remove_source:
        for group in manifest['groups']:
            for row in group['frames']:
                path = run / row['name']
                if path.exists():
                    assert sha(path.read_bytes()) == row['png_sha256']
                    removed += path.stat().st_size
                    path.unlink()
    return dict(run=str(run), frames=sum(len(g['frames']) for g in manifest['groups']),
        original_bytes=sum(r['original_bytes'] for g in manifest['groups'] for r in g['frames']),
        archive_bytes=sum((run/g['video']).stat().st_size for g in manifest['groups']),
        removed_bytes=removed, byte_restoration_verified=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('run', type=Path)
    p.add_argument('--remove-source', action='store_true')
    p.add_argument('--expected-inventory', type=Path)
    p.add_argument('--restore', action='store_true')
    a = p.parse_args()
    if a.restore:
        assert not a.remove_source
        manifest = json.loads((a.run/'control-frame-archive.json').read_text())
        for group in manifest['groups']:
            assert sha((a.run/group['video']).read_bytes()) == group['video_sha256']
            decode(a.run/group['video'], group['frames'], group['shape'], restore=True)
        print('Restored exact original PNG bytes')
    else:
        inv = json.loads(a.expected_inventory.read_text()) if a.expected_inventory else None
        print(json.dumps(archive(a.run, a.remove_source, inv)), flush=True)

"""Render recorded RGB boundaries; never infer intermediate simulator frames."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--from-step', type=int, default=0)
    parser.add_argument('--to-step', type=int, default=550)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--title', default='Recorded policy observations')
    args = parser.parse_args()
    run = args.run.resolve()
    frames = []
    for path in sorted((run/'controller/observations').glob('*/observation.json')):
        observation = json.loads(path.read_text())
        if args.from_step <= observation['step_id'] <= args.to_step:
            frames.append((path.parent, observation['step_id']))
    if not frames:
        raise ValueError('No recorded observations in this step interval')
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 20)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    process = subprocess.Popen([ffmpeg, '-v', 'error', '-y', '-f', 'rawvideo',
        '-pix_fmt', 'rgb24', '-s', '1280x544', '-r', '1', '-i', '-', '-an',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
        str(output)], stdin=subprocess.PIPE)
    sources = []
    try:
        for directory, step in frames:
            canvas = Image.new('RGB', (1280, 544), '#111827')
            draw = ImageDraw.Draw(canvas)
            draw.text((12, 5), f'{args.title} | native step {step} | observation-boundary replay',
                      font=font, fill='white')
            paths = []
            for column, camera in enumerate(('cam_high', 'cam_right_wrist')):
                path = directory/(camera+'.png')
                with Image.open(path) as image:
                    if image.size != (640, 480):
                        raise ValueError('Expected original RoboDojo 640x480 RGB')
                    canvas.paste(image.convert('RGB'), (640*column, 64))
                draw.text((640*column+12, 34), camera, font=font, fill='white')
                paths.append(dict(path=str(path.relative_to(run)),
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            process.stdin.write(canvas.tobytes())
            sources.append(dict(step=step, images=paths))
    finally:
        process.stdin.close()
        returncode = process.wait()
    if returncode:
        raise RuntimeError('Video encoder failed')
    subprocess.run([ffmpeg, '-v', 'error', '-i', str(output), '-f', 'null', '-'], check=True)
    manifest = dict(sources=sources, fps=1, frames=len(sources),
        scope='Exact original RGB at observation boundaries, not continuous video or task success.')
    output.with_suffix('.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps(dict(output=str(output), frames=len(sources))))


if __name__ == '__main__':
    main()

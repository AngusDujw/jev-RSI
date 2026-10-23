"""Audit an existing completed episode without inference or simulator execution."""
import argparse
import collections
import json
import math
from pathlib import Path
import subprocess

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    root = args.run.resolve()
    out = root / 'audit'
    out.mkdir(exist_ok=True)
    history = json.loads((root / 'controller/history.json').read_text())
    observations = [json.loads(p.read_text()) for p in sorted(
        (root / 'controller/observations').glob('*/observation.json'))]
    phases = [(0, 60, 'White: approach and lower'),
              (60, 180, 'White: repeated grasp checks'),
              (180, 220, 'Purple: approach and lower'),
              (220, 305, 'Purple: repeated grasp checks'),
              (305, 355, 'Open-hand yaw adjustment'),
              (355, 440, 'White: finger-offset grasp retries'),
              (440, 490, 'White: further grasp retries'),
              (490, 550, 'Purple: final grasp retries')]
    initial = observations[0]['current_eef']['right']
    metrics = []
    for obs in observations:
        arm = obs['current_eef']['right']
        distance = math.dist(arm['position'], initial['position'])
        q, q0 = arm['quaternion_wxyz'], initial['quaternion_wxyz']
        dot = abs(sum(a*b for a, b in zip(q, q0)))
        dot /= math.sqrt(sum(a*a for a in q)*sum(a*a for a in q0))
        metrics.append(dict(step=obs['step_id'], displacement_m=distance,
                            rotation_deg=math.degrees(2*math.acos(min(1, dot)))))
    close_onsets = []
    closed = False
    for event in history:
        now = event['response']['target']['right']['gripper_closed']
        if now and not closed:
            close_onsets.append(event['start_tick'])
        closed = now
    errors = collections.Counter()
    for path in (root / 'controller/codex_workspace').glob('call_*_result.json'):
        value = json.loads(path.read_text())
        if 'error' in value:
            errors[value['error']] += 1
    image_metrics = {}
    for camera, roi in [('cam_high', (470, 240, 630, 350)),
                        ('cam_right_wrist', (220, 250, 440, 480))]:
        images = [root / 'controller/observations' / folder / (camera+'.png')
                  for folder in ('000', '110')]
        a, b = [np.asarray(Image.open(p).convert('L').crop(roi), dtype=float)
                for p in images]
        image_metrics[camera] = dict(roi=roi,
            initial_final_correlation=float(np.corrcoef(a.ravel(), b.ravel())[0, 1]),
            mean_absolute_intensity_change=float(np.abs(a-b).mean()))
    result = dict(native=json.loads((root/'native-results/summary.json').read_text()),
        accepted_decisions=len(history), physical_steps=sum(h['executed_steps'] for h in history),
        close_onsets=close_onsets, closed_command_steps=sum(h['executed_steps'] for h in history
            if h['response']['target']['right']['gripper_closed']),
        rejected_calls=dict(errors), rejected_calls_consume_native_steps=False,
        phases=[dict(start=a, end=b, steps=b-a, description=c) for a,b,c in phases],
        max_displacement=max(metrics, key=lambda v:v['displacement_m']),
        max_rotation=max(metrics, key=lambda v:v['rotation_deg']),
        final_displacement=metrics[-1], image_roi_metrics=image_metrics,
        finding='Measured robot motion conflicts with nearly stationary rendered hand and wrist views. '
                'Native failure is real, but model-capability attribution is confounded by rendering. '
                'ROI correlation alone is not a general synchronization test.',
        video_provenance='Native sensors.mp4: 551 recorded control frames at 25 fps. '
            'Audit video: the 111 exact model-boundary RGB triplets, one second per observation; '
            'no intermediate images fabricated. Overlay is outer analysis, not original policy input.')
    (out/'audit.json').write_text(json.dumps(result, indent=2)+'\n')
    rows = ['start_step\tend_step\tright_closed\treason']
    rows += [f"{h['start_tick']}\t{h['end_tick']}\t{h['response']['target']['right']['gripper_closed']}\t"
             + h['response']['reason'].replace('\n', ' ') for h in history]
    (out/'actions.tsv').write_text('\n'.join(rows)+'\n')
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 19)
    video = out/'luna-high-stack-model-observations.mp4'
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [ffmpeg, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
               '-s', '1440x440', '-r', '1', '-i', '-', '-an', '-c:v', 'libx264',
               '-pix_fmt', 'yuv420p', '-crf', '20', '-movflags', '+faststart', str(video)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        for obs in observations:
            step = obs['step_id']
            canvas = Image.new('RGB', (1440, 440), '#111827')
            draw = ImageDraw.Draw(canvas)
            draw.text((12, 8), f'Luna high | stack_blocks | step {step}/550 | model-boundary replay (1 s/view)', font=font)
            for i, camera in enumerate(['cam_high', 'cam_left_wrist', 'cam_right_wrist']):
                path = root/'controller/observations'/f'{step//5:03d}'/(camera+'.png')
                with Image.open(path) as image:
                    canvas.paste(image.convert('RGB').resize((480,360)), (480*i, 62))
                draw.text((480*i+10, 36), camera, font=font)
            arm = obs['current_eef']['right']
            p = ', '.join(f'{x:.3f}' for x in arm['position'])
            phase = next((c for a,b,c in phases if a <= step < b), 'Terminal: step limit')
            draw.text((12, 420), f'Right LINK6 XYZ: [{p}] m | {phase}', font=font)
            process.stdin.write(canvas.tobytes())
    finally:
        process.stdin.close()
    if process.wait() != 0:
        raise RuntimeError('Video encoding failed')
    subprocess.run([ffmpeg, '-v', 'error', '-i', str(video), '-f', 'null', '-'], check=True)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

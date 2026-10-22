"""Unranked current receiver observations from a second registered RGB-D view."""
import base64
import io
import math

import numpy as np


def projected_window(shape, K, camera_to_world, width, height, margin=16):
    """Attention only: project ALL observed partial wood rectangles, not a target."""
    from libero_visible_shape import project_observed_segment
    pixels = []
    for plane in (shape or {}).get('observed_wood_planes', []):
        try:
            centre = np.asarray(plane['visible_centroid_world_mm'], float)
            axes = np.asarray(plane['in_plane_axes_world_unit'], float)
            spans = np.asarray(plane['visible_in_plane_spans_mm'], float)
            if centre.shape != (3,) or axes.shape != (2, 3) or spans.shape != (2,):
                continue
            corners = [centre + a*axes[0]*spans[0]/2 + b*axes[1]*spans[1]/2
                       for a in (-1, 1) for b in (-1, 1)]
            if not np.isfinite(corners).all() or np.any(spans <= 0):
                continue
            projection = project_observed_segment(corners, K, camera_to_world)
            if projection is not None:
                pixels.extend(projection)
        except (ValueError, KeyError, TypeError):
            continue
    if not pixels or not np.isfinite(pixels).all():
        return None
    box = [max(0, math.floor(min(p[0] for p in pixels))-margin),
           max(0, math.floor(min(p[1] for p in pixels))-margin),
           min(width, math.ceil(max(p[0] for p in pixels))+margin+1),
           min(height, math.ceil(max(p[1] for p in pixels))+margin+1)]
    return box if box[2]-box[0] >= 8 and box[3]-box[1] >= 8 else None


def sample_visible_wood(rgb, depth, K, camera_to_world, box, existing, reject_own=None):
    """Stratify ALL matching visible pixels; actor decides wood identity/support."""
    height, width = rgb.shape[:2]
    if box is None:
        return []
    r, g, b = np.asarray(rgb, float).transpose(2, 0, 1)
    mask = (r > g*1.12) & (r < g*1.8) & (g > b*1.1) & (r > 45) & (r < 210)
    region = np.zeros((height, width), bool)
    region[box[1]:box[3], box[0]:box[2]] = True
    ys, xs = np.nonzero(mask & region & np.isfinite(depth) & (depth > 0))
    if not len(xs):
        return []
    points = (camera_to_world[:3, :3] @
              (np.linalg.solve(K, np.stack((xs, ys, np.ones(len(xs))))) * depth[ys, xs])
              + camera_to_world[:3, 3, None]).T
    keep = np.isfinite(points).all(axis=1)
    if reject_own is not None:
        keep &= ~reject_own(points)
    ys, xs, points = ys[keep], xs[keep], points[keep]
    if len(xs) < 18:
        return []
    used = [int(s['label'][1:]) for s in existing
            if s['label'].startswith('B') and s['label'][1:].isdigit()]
    first = max(used, default=-1)+1
    selected = []
    for fy in (.15, .5, .85):
        band = np.flatnonzero(abs(ys-np.quantile(ys, fy)) <= max(2, (box[3]-box[1])*.08))
        for fx in (.25, .5, .75):
            if not len(band):
                continue
            index = int(band[np.argmin(abs(xs[band]-np.quantile(xs[band], fx)))])
            if index not in selected:
                selected.append(index)
    return [dict(label='B'+str(first+i), pixel_uv=[int(xs[j]), int(ys[j])],
                 observation_camera='sideview', visible_surface_world_mm=np.round(points[j]*1000, 1).tolist(),
                 meaning='CURRENT colour/depth surface candidate; actor must identify upper receiving wood in RGB.')
            for i, j in enumerate(selected)]


def receiver_zoom(state, raw_cameras):
    from PIL import Image, ImageDraw, ImageFont
    window = state.get('receiver_aux_window')
    if not window or window['observation_camera'] not in raw_cameras:
        return []
    camera = window['observation_camera']
    samples = [s for s in state.get('visible_surface_samples', [])
               if s['label'].startswith('B') and s.get('observation_camera') == camera]
    if not samples:
        return []
    image = Image.open(io.BytesIO(raw_cameras[camera])).convert('RGB')
    left, top, right, bottom = window['bbox_xyxy']
    crop = image.crop((left, top, right, bottom))
    scale = 640/max(crop.size)
    crop = crop.resize(tuple(max(1, round(v*scale)) for v in crop.size), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(crop)
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 18)
    for sample in samples:
        u, v = sample['pixel_uv']
        x, y = (u-left)*scale, (v-top)*scale
        draw.ellipse((x-4, y-4, x+4, y+4), outline='#ffff00', width=2)
        draw.text((max(0, min(crop.width-52, x+5)), max(0, min(crop.height-24, y-20))),
                  sample['label'], font=font, fill='#ffff00', stroke_width=1, stroke_fill='black')
    stream = io.BytesIO()
    crop.save(stream, format='PNG')
    return [dict(type='input_text', text=(
        f'CURRENT {camera} receiving-region zoom, observation {window["native_tick"]}. '
        'Yellow rings mark the actual pixels of ALL B candidates from THIS camera. '
        'Other B labels belong to their own catalog camera. Identify visible upper-board wood; '
        'reject robot, background, legs and the lower board. A candidate is not a target or support certificate.')),
        dict(type='input_image', image_url='data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode())]

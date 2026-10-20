"""Project measured robot TCPs, never scene object locations, into fresh RGB."""
import numpy as np
from PIL import Image, ImageDraw


def project(camera, point):
    transform = np.asarray(camera['camera_to_world'], dtype=float)
    local = transform[:3, :3].T @ (np.asarray(point, dtype=float)-transform[:3, 3])
    if not np.isfinite(local).all() or local[2] <= 1e-5:
        return None
    pixel = np.asarray(camera['K']) @ local
    return (pixel[:2]/pixel[2]).tolist()


def annotate(rgb, camera, robot):
    image = Image.fromarray(rgb).convert('RGB')
    draw = ImageDraw.Draw(image)
    width, height = image.size
    for arm, color in [('left', '#00ffff'), ('right', '#ffae00')]:
        point = np.asarray(robot[arm]['tcp_position_world_m'])
        uv = project(camera, point)
        if uv is None or not (0 <= uv[0] < width and 0 <= uv[1] < height):
            continue
        u, v = uv
        draw.line((u-6, v, u+6, v), fill=color, width=2)
        draw.line((u, v-6, u, v+6), fill=color, width=2)
        draw.text((u+7, v+7), arm+' TCP projection', fill=color)
        for axis, axis_color in enumerate(['#ff5050', '#40ff60', '#6080ff']):
            target = project(camera, point+np.eye(3)[axis]*.02)
            if target is not None and all(abs(x) < 10000 for x in target):
                draw.line((u, v, *target), fill=axis_color, width=2)
                draw.text(tuple(target), '+'+'XYZ'[axis], fill=axis_color)
    return image

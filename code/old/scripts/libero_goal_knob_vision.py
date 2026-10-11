"""Public RGB-D estimate of a stove knob and its raised grasp tab.

Only rendered pixels, camera calibration, and the public stove-control task
define this observation. A missing or ambiguous control is an error.
"""
import cv2
import numpy as np

from libero_goal_plate_vision import visible_stove, world_cloud


def visible_stove_control(view):
    rgb = np.asarray(view['rgb'])
    depth = np.asarray(view['depth'])
    stove = visible_stove(view)
    sx, sy, _, _ = stove['bbox']
    x0, y0 = max(0, sx+20), max(0, sy-80)
    x1, y1 = min(rgb.shape[1], sx+120), min(rgb.shape[0], sy+10)
    dark = (cv2.cvtColor(rgb[y0:y1, x0:x1], cv2.COLOR_RGB2GRAY) < 65).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(dark, 8)
    world = world_cloud(view)
    candidates = []
    for index in range(1, count):
        x, y, width, height, area = map(int, stats[index])
        if not (35 <= width <= 90 and 35 <= height <= 90 and 1000 <= area <= 5000):
            continue
        vv, uu = np.where(labels == index)
        uu, vv = uu+x0, vv+y0
        valid = np.isfinite(depth[vv, uu]) & (depth[vv, uu] > .02) & (depth[vv, uu] < 3.)
        points = world[vv[valid], uu[valid]]
        if len(points) < 800:
            continue
        low, high = np.quantile(points, [.05, .95], axis=0)
        if not (.02 < high[2]-low[2] < .10):
            continue
        top = points[points[:, 2] >= np.quantile(points[:, 2], .8)]
        center = np.median(top[:, :2], axis=0)
        _, _, vh = np.linalg.svd(top[:, :2]-center, full_matrices=False)
        axis = vh[0]
        if axis[0] < 0:
            axis = -axis
        top_span = np.quantile((top[:, :2]-center)@axis, [.05, .95])
        if not .025 < top_span[1]-top_span[0] < .085:
            continue
        candidates.append(dict(
            bbox=[x+x0,y+y0,x+x0+width,y+y0+height], pixels=area,
            center_world_xy_m=center.tolist(),
            top_world_z_m=float(np.quantile(top[:, 2], .5)),
            low_world_z_m=float(low[2]),
            tab_axis_world_xy=axis.tolist(),
            tab_axis_angle_rad=float(np.arctan2(axis[1], axis[0])),
            tab_visible_span_m=float(top_span[1]-top_span[0]),
            top_depth_points=len(top),
            stove_bbox=stove['bbox'],
            source='Public agentview RGB dark component above visible stove housing; calibrated RGB-D top-tab points'))
    if len(candidates) != 1:
        raise RuntimeError(f'Expected one visible stove control, found {len(candidates)}')
    return candidates[0]

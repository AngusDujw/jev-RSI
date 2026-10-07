"""Visible cabinet-handle candidates for Goal drawer tasks.

The ROI and appearance thresholds are declared from public RGB captures of the
768-pixel Goal camera view. They are not simulator object IDs/poses. Reject any
view in which the three handles cannot be separately observed.
"""
from __future__ import annotations

import cv2
import numpy as np


_ROI = (190, 360, 275, 565)  # visible cabinet-handle region in agentview


def visible_drawer_handles(rgb, depth, intrinsic, extrinsic):
    """Return three measured handle centres, highest world Z first.

    Inputs are rendered RGB-D and camera calibration only. The output is a
    hypothesis from visible pixels, never the simulator's drawer body pose.
    """
    image = np.asarray(rgb)
    distance = np.asarray(depth, dtype=float)
    k = np.asarray(intrinsic, dtype=float)
    t = np.asarray(extrinsic, dtype=float)
    if (image.shape != (768, 768, 3) or distance.shape != (768, 768) or
            k.shape != (3, 3) or t.shape != (4, 4)):
        raise ValueError("Drawer detector requires calibrated 768x768 agentview RGB-D")
    x0, y0, x1, y1 = _ROI
    patch = image[y0:y1, x0:x1].astype(np.int16)
    light = patch.max(axis=2)
    dark = patch.min(axis=2)
    neutral_metal = ((light >= 45) & (light <= 135) &
                     (light-dark <= 16)).astype(np.uint8)
    separated = cv2.erode(neutral_metal, np.ones((5, 5), np.uint8))
    count, labels, statistics, _ = cv2.connectedComponentsWithStats(separated, 8)
    candidates = []
    for label in range(1, count):
        x, y, width, height, area = map(int, statistics[label])
        if not (15 <= width <= 40 and 50 <= height <= 95 and area >= 400
                and x+x0 >= 205):
            continue
        v, u = np.where(labels == label)
        u = u+x0
        v = v+y0
        d = distance[v, u]
        valid = np.isfinite(d) & (d > .02) & (d < 3.)
        if int(valid.sum()) < 300:
            continue
        u, v, d = u[valid], v[valid], d[valid]
        camera = np.stack(((u-k[0, 2])*d/k[0, 0],
                           (v-k[1, 2])*d/k[1, 1], d), axis=1)
        world = camera @ t[:3, :3].T + t[:3, 3]
        if not np.isfinite(world).all():
            continue
        centre = np.median(world, axis=0)
        axis = np.linalg.svd(world-centre, full_matrices=False)[2][0]
        if axis[2] < 0:
            axis = -axis
        length = float(np.quantile((world-centre)@axis, .95)-
                       np.quantile((world-centre)@axis, .05))
        candidates.append(dict(
            center_uv=[round(float(np.median(u)), 2),
                       round(float(np.median(v)), 2)],
            center_world_m=centre.tolist(),
            rod_axis_world=axis.tolist(),
            visible_rod_length_m=length,
            bbox_xywh=[x+x0, y+y0, width, height],
            valid_depth_pixels=int(valid.sum()),
            source="agentview visible neutral-metal component + calibrated depth"))
    if len(candidates) != 3:
        raise RuntimeError(f"Expected three separately visible drawer handles; found {len(candidates)}")
    candidates.sort(key=lambda item: item["center_world_m"][2], reverse=True)
    heights = np.array([item["center_world_m"][2] for item in candidates])
    if not np.all(heights[:-1]-heights[1:] > .025):
        raise RuntimeError("Visible handle heights are not separable by 25mm")
    return candidates


def visible_cabinet_front(rgb, depth, intrinsic, extrinsic, handle_world_m):
    """Fit the dark visible front plane near the handles, oriented outward.

    The dominant world-Y surface is selected from RGB-D pixels, then fitted in
    3-D. World Y is the declared fixture orientation for this public Goal view;
    the actual plane offset and normal are freshly measured on every call.
    """
    image = np.asarray(rgb)
    distance = np.asarray(depth, dtype=float)
    k = np.asarray(intrinsic, dtype=float)
    t = np.asarray(extrinsic, dtype=float)
    handle = np.asarray(handle_world_m, dtype=float)
    if (image.shape != (768, 768, 3) or distance.shape != (768, 768)
            or k.shape != (3, 3) or t.shape != (4, 4)
            or handle.shape != (3,) or not np.isfinite(handle).all()):
        raise ValueError("Invalid calibrated cabinet-front observation")
    v, u = np.mgrid[360:560:2, 165:225:2]
    d = distance[v, u]
    colour = image[v, u]
    good = (colour.max(axis=2) < 60) & np.isfinite(d) & (d > .02) & (d < 3.)
    u, v, d = u[good], v[good], d[good]
    if len(d) < 500:
        raise RuntimeError("Insufficient dark visible cabinet-front pixels")
    points = np.stack(((u-k[0, 2])*d/k[0, 0],
                       (v-k[1, 2])*d/k[1, 1], d), axis=1)
    points = points @ t[:3, :3].T + t[:3, 3]
    counts, edges = np.histogram(points[:, 1], bins=100,
                                range=(handle[1]-.17, handle[1]+.08))
    mode = float((edges[np.argmax(counts)]+edges[np.argmax(counts)+1])/2)
    surface = points[np.abs(points[:, 1]-mode) < .004]
    if len(surface) < 500:
        raise RuntimeError("Cabinet front is not a sufficiently visible plane")
    centre = surface.mean(axis=0)
    normal = np.linalg.svd(surface-centre, full_matrices=False)[2][-1]
    if np.dot(handle-centre, normal) < 0:
        normal = -normal
    residual = np.abs((surface-centre)@normal)
    gap = float(np.dot(handle-centre, normal))
    if (float(np.quantile(residual, .9)) > .003 or
            not .008 < gap < .07 or abs(normal[1]) < .9):
        raise RuntimeError("Visible cabinet front/handle geometry inconsistent")
    return dict(point_world_m=centre.tolist(),
                outward_normal_world=normal.tolist(),
                handle_front_gap_m=gap,
                plane_residual_p90_m=float(np.quantile(residual, .9)),
                visible_pixels=int(len(surface)),
                source="dark visible RGB-D front plane near measured handle")


def select_public_handle(handles, requested_level):
    """Map the public words top/middle/bottom to measured visible candidates."""
    if len(handles) != 3:
        raise ValueError("Exactly three measured handles are required")
    order = {"top": 0, "middle": 1, "bottom": 2}
    if requested_level not in order:
        raise ValueError("Unknown public drawer level")
    return handles[order[requested_level]]

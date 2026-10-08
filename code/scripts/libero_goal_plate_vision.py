"""Visible red-rimmed plate and stove-front geometry for Goal task 1296.

The public task names the plate and stove. Every position comes from rendered
agentview RGB-D and calibration; this module does not read scene object state,
asset geometry, the evaluator, or a model service.
"""
from __future__ import annotations

import cv2
import numpy as np

from run_position_pilot import dump


def world_cloud(view):
    depth = np.asarray(view['depth'], float)
    k = np.asarray(view['K'], float)
    t = np.asarray(view['T'], float)
    if depth.shape != (768, 768) or k.shape != (3, 3) or t.shape != (4, 4):
        raise ValueError('Expected calibrated 768x768 agentview RGB-D')
    vv, uu = np.indices(depth.shape)
    xyz = np.stack(((uu-k[0, 2])*depth/k[0, 0],
                    (vv-k[1, 2])*depth/k[1, 1], depth), axis=-1)
    return xyz @ t[:3, :3].T + t[:3, 3]


def visible_plate(view, previous_uv=None):
    """Select the flat red-ring plate, rejecting similar round bowls/burners."""
    rgb = np.asarray(view['rgb'])
    if rgb.shape != (768, 768, 3):
        raise ValueError('Expected 768x768 RGB')
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    red = (((hsv[:, :, 0] < 12) | (hsv[:, :, 0] > 175)) &
           (hsv[:, :, 1] > 55) & (hsv[:, :, 2] > 70)).astype(np.uint8)
    red[:340] = 0
    red[:, :250] = 0
    n, labels, stats, centres = cv2.connectedComponentsWithStats(red, 8)
    candidates = []
    cloud = world_cloud(view)
    for idx in range(1, n):
        x, y, w, h, count = map(int, stats[idx])
        if not (65 <= w <= 190 and 45 <= h <= 140 and count >= 350 and
                .8 <= w/h <= 2.1):
            continue
        if previous_uv is not None and np.linalg.norm(centres[idx]-previous_uv) > 190:
            continue
        pixels = np.column_stack(np.where(labels == idx))[:, ::-1].astype(np.int32)
        hull = cv2.convexHull(pixels)
        mask = np.zeros(red.shape, np.uint8)
        cv2.fillConvexPoly(mask, hull, 1)
        good = (mask > 0) & np.isfinite(view['depth']) & (view['depth'] > .02)
        points = cloud[good]
        if len(points) < 1500:
            continue
        low, high = np.quantile(points, [.05, .95], axis=0)
        if not (.07 < max(high[:2]-low[:2]) < .24 and
                high[2]-low[2] < .045):
            continue
        centre = (low+high)/2
        candidates.append(dict(mask=good, bbox=[x, y, x+w, y+h],
                               uv=centres[idx].tolist(),
                               center=centre.tolist(), low=low.tolist(),
                               high=high.tolist(), red_pixels=count,
                               valid_depth_pixels=len(points)))
    if not candidates:
        raise RuntimeError('No unambiguous visible flat red-rim plate')
    candidates.sort(key=lambda row: row['red_pixels'], reverse=True)
    if (len(candidates) > 1 and
            candidates[1]['red_pixels'] > .75*candidates[0]['red_pixels'] and
            np.linalg.norm(np.asarray(candidates[1]['uv'])-
                           np.asarray(candidates[0]['uv'])) > 80):
        raise RuntimeError('Ambiguous visible red-rim plate candidates')
    return candidates[0]


def visible_stove(view):
    """Measure the light stove housing in the public fixed agentview layout."""
    hsv = cv2.cvtColor(np.asarray(view['rgb']), cv2.COLOR_RGB2HSV)
    light = ((hsv[:, :, 1] < 40) & (hsv[:, :, 2] > 130)).astype(np.uint8)
    light[:260] = 0
    light[450:] = 0
    light[:, :430] = 0
    n, _, stats, _ = cv2.connectedComponentsWithStats(light, 8)
    boxes = []
    for idx in range(1, n):
        x, y, w, h, count = map(int, stats[idx])
        if 140 <= w <= 240 and 70 <= h <= 150 and count >= 5000:
            boxes.append((x, y, w, h, count))
    if len(boxes) != 1:
        raise RuntimeError(f'Expected one visible stove housing, found {len(boxes)}')
    x, y, w, h, count = boxes[0]
    return dict(bbox=[x, y, x+w, y+h], light_pixels=count,
                source='visible light stove housing in public agentview')


def visible_front_goal(view, plate, stove):
    """Choose free tabletop in front of the stove with a clear swept plate path.

    Candidate pixels share the measured stove's horizontal span. The vertical
    row is selected from visible table in front of it, with plate radius and
    elevated RGB-D points guarding the entire straight swept corridor.
    """
    cloud = world_cloud(view)
    source = np.asarray(plate['center'], float)
    stove_x0, _, stove_x1, stove_y1 = stove['bbox']
    centre_u = (stove_x0+stove_x1)//2
    source_v = int(round(plate['uv'][1]))
    goals = []
    # More frontal rows are tried first only if the swept visible corridor is
    # free. The ranges refer to image layout, while geometry comes from depth.
    for v in (max(stove_y1+75, source_v-55),
              max(stove_y1+100, source_v-25),
              max(stove_y1+125, source_v)):
        for u in (centre_u, centre_u-18, centre_u+18):
            if not (20 <= u < 748 and 20 <= v < 748):
                continue
            patch = cloud[v-4:v+5, u-4:u+5].reshape(-1, 3)
            if not np.isfinite(patch).all():
                continue
            goal = np.median(patch, axis=0)
            if abs(goal[2]-plate['low'][2]) > .025:
                continue
            vector = goal[:2]-source[:2]
            distance = np.linalg.norm(vector)
            if not .07 < distance < .45:
                continue
            direction = vector/distance
            # Only visible tabletop pixels are considered. Ignore the source
            # plate itself; elevated bowl/carton/bottle points remain obstacles.
            valid = np.isfinite(cloud).all(axis=2)
            elevated = valid & (cloud[:, :, 2] > goal[2]+.025) & (
                cloud[:, :, 2] < goal[2]+.30)
            elevated[:320] = 0
            elevated[:, :250] = 0
            elevated &= ~plate['mask']
            points = cloud[elevated][:, :2]
            if len(points):
                along = (points-source[:2]) @ direction
                lateral = np.abs((points-source[:2])[:, 0]*direction[1] -
                                 (points-source[:2])[:, 1]*direction[0])
                radius = .5*max(np.asarray(plate['high'])[:2]-
                                np.asarray(plate['low'])[:2]) + .008
                blocked = (along > .015) & (along < distance+.02) & (lateral < radius)
                blockers = int(blocked.sum())
            else:
                blockers = 0
            goals.append(dict(goal_uv=[u, v], goal_world_m=goal.tolist(),
                              travel_m=float(distance), elevated_corridor_pixels=blockers))
    clear = [candidate for candidate in goals if candidate['elevated_corridor_pixels'] < 80]
    if not clear:
        raise RuntimeError('No visible collision-clear plate corridor in front of stove')
    return min(clear, key=lambda row: (row['travel_m'], row['elevated_corridor_pixels']))


def visible_side_contact(view, plate_mask, plate, direction, central_contact_xy):
    """Select a supported off-centre rim point with a visible clear rear lane.

    This uses only calibrated RGB-D, the plate's segmented pixels, and the
    already-computed contact line. The camera-facing side wins equal-clearance
    ties, avoiding a fixed simulator/world-coordinate side choice.
    """
    cloud = world_cloud(view)
    if plate_mask.shape != cloud.shape[:2]:
        raise ValueError('Plate mask/depth shape mismatch')
    good = plate_mask & np.isfinite(cloud).all(axis=2)
    if int(good.sum()) < 500:
        raise RuntimeError('Insufficient visible plate support for side contact')
    direction = np.asarray(direction, float)
    lateral = np.array([direction[1], -direction[0]])
    source_xy = np.asarray(plate['center'][:2], float)
    support = (cloud[good, :2]-source_xy) @ lateral
    q05, q95 = np.quantile(support, [.05, .95])
    available = min(q95, -q05)
    if available < .020:
        raise RuntimeError('Plate rim too narrow for supported side contact')
    offset = float(min(.035, .80*available))
    elevated = (np.isfinite(cloud).all(axis=2) & ~plate_mask &
                (cloud[:, :, 2] > plate['high'][2]+.012) &
                (cloud[:, :, 2] < plate['high'][2]+.45))
    points = cloud[elevated][:, :2]
    camera_xy = np.asarray(view['T'], float)[:2, 3]
    rows = []
    for sign in (-1, 1):
        contact = np.asarray(central_contact_xy, float)+sign*offset*lateral
        relative = points-contact
        along = relative @ direction
        across = relative @ lateral
        # The descending wrist occupies a wider area than the fingertip.
        # Count only *visible* elevated pixels in its rear approach corridor.
        nearby = (along > -.075) & (along < .015) & (np.abs(across) < .055)
        rows.append(dict(offset_m=sign*offset,
                         contact_xy_m=contact.tolist(),
                         elevated_rear_corridor_pixels=int(nearby.sum()),
                         camera_side_score_m=float(np.dot(contact-camera_xy,
                             contact-camera_xy))))
    fewest = min(row['elevated_rear_corridor_pixels'] for row in rows)
    # Pixel counts fluctuate with occlusion and sloped surfaces. Treat lanes
    # within 15% as equivalent, then favour the camera-facing exposed rim.
    nearly_clear = [row for row in rows if
                    row['elevated_rear_corridor_pixels'] <= fewest*1.15+50]
    selected = min(nearly_clear, key=lambda row: row['camera_side_score_m'])
    return dict(**selected, alternatives=rows,
                plate_lateral_support_5_95_m=[float(q05), float(q95)],
                source='segmented plate RGB-D and visible elevated rear corridor')


class GoalPlateVision:
    """Drop-in visible-only source/goal adapter for the Jev push primitive."""

    def __init__(self, rec):
        self.rec = rec
        self.calls = 0
        self.refreshes = 0
        self.goal = None
        self.last_uv = None

    def locate(self, views, public_task, reason, previous=None):
        if reason not in ('initial', 'reobserve', 'after_push') or self.calls >= 3:
            raise RuntimeError('Goal plate observation trigger/budget')
        self.calls += 1
        view = views['agentview']
        plate = visible_plate(view, self.last_uv)
        self.last_uv = plate['uv']
        if reason == 'initial':
            stove = visible_stove(view)
            self.goal = visible_front_goal(view, plate, stove)
            dump(self.rec.folder/'goal-plate-visible-plan.json', dict(
                plate={key: value for key, value in plate.items() if key != 'mask'},
                stove=stove, goal=self.goal, public_task=public_task,
                source='agentview RGB-D/calibration only'))
        if self.goal is None:
            raise RuntimeError('Goal plate target has not been measured')
        uv = self.goal['goal_uv']
        result = dict(source=dict(label='visible flat red-rim plate',
                                  camera='agentview', bbox=plate['bbox'],
                                  visible=True),
                      destination=dict(label='visible free tabletop in front of stove',
                                       camera='agentview',
                                       bbox=[uv[0]-8, uv[1]-8, uv[0]+8, uv[1]+8],
                                       visible=True),
                      goal_uv=uv, reason=reason,
                      evidence='RGB-D flat red-rim plate and visible stove/table geometry')
        dump(self.rec.folder/f'goal-plate-observation-{self.calls}.json', result)
        return result

    def measure(self, view, bbox, label, reason):
        self.refreshes += 1
        plate = visible_plate(view, self.last_uv)
        self.last_uv = plate['uv']
        folder = self.rec.folder/f'plate-mask-{self.refreshes}'
        folder.mkdir()
        path = folder/'mask.npy'
        np.save(path, plate['mask'])
        result = dict(center=plate['center'], low=plate['low'],
                      high=plate['high'], points=plate['valid_depth_pixels'],
                      label=label, visible_mask_path=str(path),
                      source='visible red-rim connected component + RGB-D quantiles')
        dump(folder/'geometry.json', result)
        return result

    def close(self):
        pass

"""RGB-D block geometry and visual memory, without simulator object access.

Initial masks are GroundingDINO/SAM outputs. Online associations use measured
color and metric proximity across cameras. Occluded poses are explicitly stale.
Assumes upright cuboids on the measured dominant horizontal table plane.
"""
import cv2
import numpy as np


def cloud(view, origin):
    depth = np.asarray(view['depth_m'])
    y, x = np.indices(depth.shape)
    rays = np.stack([x, y, np.ones_like(x)], -1) @ np.linalg.inv(view['intrinsic']).T
    local = rays*depth[..., None]*[1, -1, -1]
    transform = np.asarray(view['camera_to_world_opengl'])
    points = local @ transform[:3, :3].T+transform[:3, 3]-origin
    points[(~np.isfinite(depth)) | (depth < .05) | (depth > 3)] = np.nan
    return points


def top_geometry(points):
    z = float(np.quantile(points[:, 2], .9))
    top = points[np.abs(points[:, 2]-z) < .0025]
    if len(top) < 12:
        raise ValueError('Insufficient visible top surface')
    rect = cv2.minAreaRect(top[:, :2].astype(np.float32))
    xy, size, degrees = rect
    return np.r_[xy, z], np.asarray(size), float(np.deg2rad(degrees))


class BlockMemory:
    def __init__(self, captured, evidence):
        head = captured['cameras']['cam_high']
        pts = cloud(head, np.asarray(captured['env_origin']))
        valid = np.isfinite(pts).all(-1) & (np.abs(pts[..., 0]) < .65) & (np.abs(pts[..., 1]) < .5)
        z = pts[..., 2][valid]
        z = z[(z > .4) & (z < 1.)]
        bins, counts = np.unique(np.round(z/.001).astype(int), return_counts=True)
        self.table_z = float(bins[counts.argmax()]*.001)
        self.objects = {}
        h, w = pts.shape[:2]
        for d in evidence['views']['cam_high']['objects']:
            mask = np.zeros((h, w), np.uint8)
            polygon = np.rint(np.asarray(d['contour_uv01'])*[w, h]).astype(np.int32)
            cv2.fillPoly(mask, [polygon], 1)
            mask = cv2.erode(mask, np.ones((3, 3), np.uint8)).astype(bool)
            mask &= valid & (pts[..., 2] > self.table_z+.008) & (pts[..., 2] < self.table_z+.12)
            points = pts[mask]
            if len(points) < 30:
                continue
            top, size, yaw = top_geometry(points)
            height = top[2]-self.table_z
            if not (.015 < min(size) < .08 and .015 < max(size) < .08 and .015 < height < .08):
                continue
            color = np.median(np.asarray(head['rgb'])[mask], axis=0)
            self.objects[d['id']] = dict(id=d['id'], center=top-[0, 0, height/2],
                height=float(height), top=top, size=size, yaw=yaw, rgb=color,
                initial_center=top-[0, 0, height/2], observed=True,
                last_seen_tick=captured['native_step'], source='initial_RGB_mask_depth_top_and_table',
                last_measurement=top-[0, 0, height/2], views=['cam_high'], spread_m=.003)
        if len(self.objects) != 3:
            raise ValueError(f'Need 3 valid visual cuboids, found {len(self.objects)}')

    def update(self, captured, predictions=None):
        predictions = predictions or {}
        points = {n: cloud(v, np.asarray(captured['env_origin'])) for n, v in captured['cameras'].items()}
        for oid, obj in self.objects.items():
            predicted = np.asarray(predictions.get(oid, obj['center']))
            candidates, names = [], []
            proto = obj['rgb']/max(float(np.sum(obj['rgb'])), 1.)
            for name, view in captured['cameras'].items():
                p = points[name]
                rgb = np.asarray(view['rgb'], dtype=float)
                chroma = rgb/np.maximum(rgb.sum(-1, keepdims=True), 1.)
                good = np.isfinite(p).all(-1)
                good &= np.linalg.norm(p[..., :2]-predicted[:2], axis=-1) < .045
                good &= (p[..., 2] > predicted[2]-.6*obj['height']) & (p[..., 2] < predicted[2]+.7*obj['height'])
                good &= np.linalg.norm(chroma-proto, axis=-1) < .07
                good &= (rgb.mean(-1) > .45*np.mean(obj['rgb'])) & (rgb.mean(-1) < 1.6*np.mean(obj['rgb']))
                good &= p[..., 2] > self.table_z+.008
                selected = p[good]
                if len(selected) < 24:
                    continue
                try:
                    top, size, _ = top_geometry(selected)
                except ValueError:
                    continue
                # Reject gripper/large false surfaces and partial slivers.
                if min(size) < .008 or max(size) > .065:
                    continue
                center = top-[0, 0, obj['height']/2]
                if np.linalg.norm(center-predicted) > .035:
                    continue
                candidates.append(center)
                names.append(name)
            obj['observed'] = bool(candidates)
            obj['views'] = names
            if candidates:
                measured = np.median(candidates, axis=0)
                obj['last_measurement'] = measured
                obj['spread_m'] = float(max(.003, np.max(np.linalg.norm(np.asarray(candidates)-measured, axis=1))))
                obj['last_seen_tick'] = captured['native_step']
                # Static uncontacted blocks retain their less-occluded initial map.
                # A carried/released object uses measured pose, not attachment truth.
                if oid in predictions:
                    obj['center'] = measured
                    obj['top'] = measured+[0, 0, obj['height']/2]
                obj['source'] = 'RGB_color_depth_multiview; static_map_if_uncontacted'
            else:
                obj['source'] = 'occluded_visual_memory_NOT_fresh_measurement'
        return self.objects

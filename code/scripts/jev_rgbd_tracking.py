"""Public RGB-D patch registration; no simulator or object-state access."""
from __future__ import annotations

import cv2
import numpy as np


def rigid_fit(source, target):
    a, b = source.mean(0), target.mean(0)
    u, _, vt = np.linalg.svd((source-a).T @ (target-b))
    r = vt.T @ u.T
    if np.linalg.det(r) < 0:
        vt[-1] *= -1
        r = vt.T @ u.T
    return r, b-r@a


def robust_registration(source, target, threshold=.004):
    """RANSAC and measured residuals; unknown is distinct from no motion."""
    if len(source) < 6:
        return None
    rng = np.random.default_rng(0)
    best = np.zeros(len(source), bool)
    for _ in range(128):
        ids = rng.choice(len(source), 3, replace=False)
        if np.linalg.norm(np.cross(source[ids[1]]-source[ids[0]], source[ids[2]]-source[ids[0]])) < 1e-6:
            continue
        r, t = rigid_fit(source[ids], target[ids])
        inliers = np.linalg.norm(source@r.T+t-target, axis=1) < threshold
        if inliers.sum() > best.sum():
            best = inliers
    if best.sum() < 6 or best.mean() < .4:
        return None
    for _ in range(2):
        r, t = rigid_fit(source[best], target[best])
        best = np.linalg.norm(source@r.T+t-target, axis=1) < threshold
        if best.sum() < 6:
            return None
    spread = np.linalg.svd(source[best]-source[best].mean(0), compute_uv=False)/np.sqrt(best.sum())
    if spread[1] < .003:
        return None
    errors = np.linalg.norm(source[best]@r.T+t-target[best], axis=1)
    return r, t, best, float(np.sqrt(np.mean(errors**2))), spread


def lift_pixels(view, pixels):
    """Backproject local median depth; retain indices for descriptor pairing."""
    xyz, kept = [], []
    height, width = view["depth"].shape
    for i, (u, v) in enumerate(pixels):
        x, y = int(round(u)), int(round(v))
        if not (1 <= x < width-1 and 1 <= y < height-1):
            continue
        patch = view["depth"][y-1:y+2, x-1:x+2]
        if not np.isfinite(patch).all() or patch.min() < .02 or patch.max() > 3 or np.ptp(patch) > .015:
            continue
        z = float(np.median(patch))
        p = view["T"][:3, :3] @ (np.linalg.solve(view["K"], [u, v, 1.])*z)+view["T"][:3, 3]
        xyz.append(p)
        kept.append(i)
    return np.asarray(xyz).reshape(-1, 3), np.asarray(kept, int)


class RGBDPatch:
    """Register a caller-selected textured rigid surface across public views."""

    def __init__(self, view, polygon, frame_id):
        poly = np.asarray(polygon, float)
        h, w = view["rgb"].shape[:2]
        if poly.ndim != 2 or poly.shape[1] != 2 or not 3 <= len(poly) <= 16 or not np.isfinite(poly).all():
            raise ValueError("Expected 3..16 visible polygon vertices")
        if (poly < 0).any() or (poly[:, 0] >= w).any() or (poly[:, 1] >= h).any():
            raise ValueError("Tracking polygon crosses image boundary")
        self.sift = cv2.SIFT_create(nfeatures=800, contrastThreshold=.02)
        mask = np.zeros((h, w), np.uint8)
        cv2.fillPoly(mask, [poly.astype(np.int32)], 255)
        mask = cv2.erode(mask, np.ones((3, 3), np.uint8), iterations=2)
        keypoints, descriptors = self.sift.detectAndCompute(cv2.cvtColor(view["rgb"], cv2.COLOR_RGB2GRAY), mask)
        if descriptors is None:
            raise ValueError("Selected surface has no usable visual texture")
        pixels = np.array([k.pt for k in keypoints])
        self.reference, kept = lift_pixels(view, pixels)
        self.descriptors = descriptors[kept]
        self.pixels = pixels[kept]
        if len(kept) < 12:
            raise ValueError("Need at least 12 textured depth-valid surface features")
        self.frame_id = frame_id

    def update(self, views, frame_id):
        best = None
        candidates = []
        for camera, view in views.items():
            kp, desc = self.sift.detectAndCompute(cv2.cvtColor(view["rgb"], cv2.COLOR_RGB2GRAY), None)
            if desc is None or len(desc) < 2:
                candidates.append(dict(camera=camera, matches=0))
                continue
            matches = cv2.BFMatcher(cv2.NORM_L2).knnMatch(self.descriptors, desc, k=2)
            pairs = [m[0] for m in matches if len(m) == 2 and m[0].distance < .72*m[1].distance]
            pairs.sort(key=lambda x: x.distance)
            used, unique = set(), []
            for pair in pairs:
                if pair.trainIdx not in used:
                    unique.append(pair)
                    used.add(pair.trainIdx)
                if len(unique) >= 120:
                    break
            pixels = np.array([kp[m.trainIdx].pt for m in unique]).reshape(-1, 2)
            target, kept = lift_pixels(view, pixels)
            source = np.asarray([self.reference[unique[i].queryIdx] for i in kept]).reshape(-1, 3)
            fit = robust_registration(source, target)
            candidates.append(dict(camera=camera, matches=len(kept), rigid_consensus=fit is not None))
            if fit is None:
                continue
            r, t, inliers, rms, spread = fit
            if best is None or (int(inliers.sum()), -rms) > best[0]:
                transform = np.eye(4)
                transform[:3, :3], transform[:3, 3] = r, t
                result = dict(status="tracked", camera=camera, frame_id=frame_id, reference_frame_id=self.frame_id,
                    transform_initial_world_to_current_world=transform.tolist(),
                    reference_patch_centroid_world_m=self.reference.mean(0).tolist(),
                    current_patch_centroid_world_m=(r@self.reference.mean(0)+t).tolist(),
                    matches=len(source), inliers=int(inliers.sum()), rms_m=rms,
                    inlier_spread_m=spread.tolist(), uncertainty_floor_m=max(.0015, rms),
                    reference_inlier_world_m=source[inliers].tolist(), current_inlier_world_m=target[inliers].tolist(),
                    source="RGB-D feature correspondence and rigid registration; not object truth")
                best = ((int(inliers.sum()), -rms), result)
        if best is None:
            return dict(status="unknown", frame_id=frame_id, reference_frame_id=self.frame_id,
                reason="No sufficient nondegenerate rigid feature consensus", candidates=candidates,
                source="public RGB-D patch matching; no extrapolated tracking result")
        best[1]["candidates"] = candidates
        return best[1]

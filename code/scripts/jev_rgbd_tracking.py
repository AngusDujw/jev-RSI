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


def balanced_features(sift, gray, mask=None):
    """Prevent distant high-contrast texture from consuming all feature slots."""
    kp, desc = sift.detectAndCompute(gray, mask)
    if desc is None:
        return [], None, dict(raw_features=0, selected_features=0)
    h, w = gray.shape
    cells = {}
    for i, keypoint in enumerate(kp):
        cell = (min(3, int(keypoint.pt[0]*4/w)), min(3, int(keypoint.pt[1]*4/h)))
        cells.setdefault(cell, []).append(i)
    selected = []
    for cell in sorted(cells):
        selected.extend(sorted(cells[cell], key=lambda i: kp[i].response, reverse=True)[:128])
    return [kp[i] for i in selected], desc[selected], dict(raw_features=len(kp),
        selected_features=len(selected), grid=[4, 4], per_cell_limit=128)


class RGBDPatch:
    """Register a caller-selected textured rigid surface across public views."""

    def __init__(self, view, polygon, frame_id):
        poly = np.asarray(polygon, float)
        h, w = view["rgb"].shape[:2]
        if poly.ndim != 2 or poly.shape[1] != 2 or not 3 <= len(poly) <= 16 or not np.isfinite(poly).all():
            raise ValueError("Expected 3..16 visible polygon vertices")
        if (poly < 0).any() or (poly[:, 0] >= w).any() or (poly[:, 1] >= h).any():
            raise ValueError("Tracking polygon crosses image boundary")
        # OpenCV applies retainBest before its mask. Budget spatially afterwards.
        self.sift = cv2.SIFT_create(nfeatures=0, contrastThreshold=.02)
        mask = np.zeros((h, w), np.uint8)
        cv2.fillPoly(mask, [poly.astype(np.int32)], 255)
        mask = cv2.erode(mask, np.ones((3, 3), np.uint8), iterations=2)
        keypoints, descriptors, _ = balanced_features(self.sift, cv2.cvtColor(view["rgb"], cv2.COLOR_RGB2GRAY), mask)
        if descriptors is None:
            raise ValueError("Selected surface has no usable visual texture")
        pixels = np.array([k.pt for k in keypoints])
        self.reference, kept = lift_pixels(view, pixels)
        self.descriptors = descriptors[kept]
        self.pixels = pixels[kept]
        if len(kept) < 12:
            raise ValueError("Selected patch has "+str(len(kept))+" textured depth-valid features; at least 12 are required. Use a clearer textured interior patch or initialize before occluding camera motion.")
        self.frame_id = frame_id
        self.initial_centroid = self.reference.mean(0)
        self.initial_depth = view["depth"].copy()
        self.initial_K = view["K"].copy()
        self.initial_world_to_camera = np.linalg.inv(view["T"])
        self.initial_mask = mask
        self.banks = [(self.reference, self.descriptors, np.full(len(self.reference), .0015))]
        self.reference_uncertainty = self.banks[0][2]
        self.last_keyframe = frame_id

    def grow_reference(self, view, kp, desc, r, t, uncertainty, frame_id):
        """Add current appearance only on the original measured surface support."""
        if frame_id-self.last_keyframe < 6:
            return 0
        pixels = np.asarray([k.pt for k in kp]).reshape(-1, 2)
        current, kept = lift_pixels(view, pixels)
        canonical = (current-t) @ r
        camera = canonical @ self.initial_world_to_camera[:3, :3].T+self.initial_world_to_camera[:3, 3]
        positive = camera[:, 2] > .02
        projected = camera @ self.initial_K.T
        uv = np.rint(projected[:, :2]/np.maximum(projected[:, 2:3], .0001)).astype(int)
        h, w = self.initial_depth.shape
        inside = positive & (uv[:, 0] >= 1) & (uv[:, 0] < w-1) & (uv[:, 1] >= 1) & (uv[:, 1] < h-1)
        candidates = np.flatnonzero(inside)
        accepted = []
        for i in candidates:
            x, y = uv[i]
            depth = self.initial_depth[y-1:y+2, x-1:x+2]
            if self.initial_mask[y, x] and np.isfinite(depth).all() and np.ptp(depth) < .015 and abs(float(np.median(depth))-camera[i, 2]) < .0025:
                accepted.append(i)
        if len(accepted) < 12:
            return 0
        # Preserve multiple appearance keyframes, but keep the original bank.
        accepted = sorted(accepted, key=lambda i: kp[kept[i]].response, reverse=True)[:200]
        point_uncertainty = np.sqrt(uncertainty**2+.0005**2)
        self.banks.append((canonical[accepted], desc[kept[accepted]], np.full(len(accepted), point_uncertainty)))
        self.banks = self.banks[:1]+self.banks[-7:] if len(self.banks) > 8 else self.banks
        self.reference = np.vstack([bank[0] for bank in self.banks])
        self.descriptors = np.vstack([bank[1] for bank in self.banks])
        self.reference_uncertainty = np.concatenate([bank[2] for bank in self.banks])
        self.last_keyframe = frame_id
        return len(accepted)

    def update(self, views, frame_id):
        best = None
        candidates = []
        for camera, view in views.items():
            kp, desc, search = balanced_features(self.sift, cv2.cvtColor(view["rgb"], cv2.COLOR_RGB2GRAY))
            if desc is None or len(desc) < 2:
                candidates.append(dict(camera=camera, matches=0, feature_search=search))
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
            uncertainty = np.asarray([self.reference_uncertainty[unique[i].queryIdx] for i in kept])
            fit = robust_registration(source, target)
            candidates.append(dict(camera=camera, matches=len(kept), rigid_consensus=fit is not None, feature_search=search))
            if fit is None:
                continue
            r, t, inliers, rms, spread = fit
            if best is None or (int(inliers.sum()), -rms) > best[0]:
                transform = np.eye(4)
                transform[:3, :3], transform[:3, 3] = r, t
                result = dict(status="tracked", camera=camera, frame_id=frame_id, reference_frame_id=self.frame_id,
                    transform_initial_world_to_current_world=transform.tolist(),
                    reference_patch_centroid_world_m=self.initial_centroid.tolist(),
                    current_patch_centroid_world_m=(r@self.initial_centroid+t).tolist(),
                    matches=len(source), inliers=int(inliers.sum()), rms_m=rms,
                    inlier_spread_m=spread.tolist(), uncertainty_floor_m=max(.0015, rms, float(uncertainty[inliers].max())),
                    reference_inlier_world_m=source[inliers].tolist(), current_inlier_world_m=target[inliers].tolist(),
                    source="RGB-D feature correspondence and rigid registration; not object truth", feature_search=search)
                best = ((int(inliers.sum()), -rms), result, (view, kp, desc, r, t))
        if best is None:
            return dict(status="unknown", frame_id=frame_id, reference_frame_id=self.frame_id,
                reason="No sufficient nondegenerate rigid feature consensus", candidates=candidates,
                source="public RGB-D patch matching; no extrapolated tracking result")
        best[1]["candidates"] = candidates
        result = best[1]
        added = 0
        if result["inliers"] >= 12 and result["inliers"]/result["matches"] >= .65 and result["rms_m"] <= .0015:
            added = self.grow_reference(*best[2], result["uncertainty_floor_m"], frame_id)
        result["appearance_reference"] = dict(keyframes=len(self.banks), features=len(self.reference),
            added_features=added, last_keyframe_frame_id=self.last_keyframe,
            support="original RGB-D polygon and depth consistency; historical appearance, not object truth")
        return best[1]

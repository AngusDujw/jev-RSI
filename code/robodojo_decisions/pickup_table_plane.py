"""Estimate a visible horizontal support plane from RGB texture matches.

Only historical/current RGB and public camera calibration enter. The plane
is a local image-derived hypothesis, not simulator table pose or clearance.
"""
from pathlib import Path

import cv2
import numpy as np

from camera_geometry import project
from pickup_temporal_stereo import _triangulate


def _features(observation):
    path = Path(next(x["path"] for x in observation["images"]
                     if x["camera"] == "cam_right_wrist"))
    image = cv2.imread(str(path))
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([5, 25, 50]),
                       np.array([35, 240, 245]))
    mask[:110] = 0
    keys, descriptors = cv2.SIFT_create(
        nfeatures=3000, contrastThreshold=.008).detectAndCompute(
            cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), mask)
    if descriptors is None or len(keys) < 20:
        raise ValueError("Insufficient visible brown support texture")
    return keys, descriptors


def build(reference, reference_calibration, current, current_calibration):
    if (reference["step_id"] >= current["step_id"] or
            reference["task"] != current["task"] or
            reference_calibration["step_id"] != reference["step_id"] or
            current_calibration["step_id"] != current["step_id"]):
        raise ValueError("Support-plane image/calibration freshness mismatch")
    old_keys, old_desc = _features(reference)
    new_keys, new_desc = _features(current)
    ca = reference_calibration["cameras"]["cam_right_wrist"]
    cb = current_calibration["cameras"]["cam_right_wrist"]
    high = cv2.imread(next(x["path"] for x in current["images"]
                          if x["camera"] == "cam_high"))
    high_hsv = cv2.cvtColor(high, cv2.COLOR_BGR2HSV)
    high_wood = cv2.inRange(high_hsv, np.array([5, 25, 50]),
                            np.array([35, 240, 245])) != 0
    candidates = []
    seen_a, seen_b = set(), set()
    for pair in cv2.BFMatcher().knnMatch(old_desc, new_desc, k=2):
        if len(pair) != 2 or pair[0].distance >= .72*pair[1].distance:
            continue
        match = pair[0]
        ua = old_keys[match.queryIdx].pt
        ub = new_keys[match.trainIdx].pt
        ia, ib = tuple(np.rint(ua)), tuple(np.rint(ub))
        if ia in seen_a or ib in seen_b:
            continue
        try:
            tri = _triangulate(ca, list(ua), cb, list(ub))
        except ValueError:
            continue
        if (tri["ray_angle_deg"] < 4 or tri["ray_gap_mm"] > 3 or
                max(tri["reprojection_error_px"]) > 2 or
                not .5 < tri["point"][2] < 1.):
            continue
        uv = project(current_calibration["cameras"]["cam_high"],
                     tri["point"])
        if uv is None:
            continue
        u, v = np.rint(uv).astype(int)
        if not (0 <= u < high.shape[1] and 0 <= v < high.shape[0] and
                high_wood[v, u]):
            continue
        seen_a.add(ia)
        seen_b.add(ib)
        patch = high[max(0, v-3):v+4, max(0, u-3):u+4]
        candidates.append({"point": tri["point"], "reference_uv": ua,
                           "current_uv": ub, "fixed_high_uv": [int(u), int(v)],
                           "fixed_high_rgb_median":
                               np.median(patch.reshape(-1, 3), axis=0).tolist()})
    if len(candidates) < 10:
        raise ValueError(f"Only {len(candidates)} verified support texture matches")
    xyz = np.asarray([r["point"] for r in candidates])
    mask = max((np.abs(xyz[:, 2]-z) < .006 for z in xyz[:, 2]),
               key=lambda m: int(m.sum()))
    xyz = xyz[mask]
    rows = [r for r, ok in zip(candidates, mask) if ok]
    if len(rows) < 10 or np.min(np.ptp(xyz[:, :2], axis=0)) < .10:
        raise ValueError("Horizontal texture plane lacks ten spatially spread matches")
    design = np.column_stack((xyz[:, :2], np.ones(len(xyz))))
    coeff = np.linalg.lstsq(design, xyz[:, 2], rcond=None)[0]
    residual = xyz[:, 2]-design @ coeff
    tilt = float(np.degrees(np.arctan(np.linalg.norm(coeff[:2]))))
    if tilt > 5 or np.quantile(np.abs(residual), .95) > .006:
        raise ValueError("Support texture does not fit a near-horizontal plane")
    rng = np.random.default_rng(198)
    shifts = []
    for _ in range(30):
        heights = []
        for row in rows:
            try:
                moved = _triangulate(
                    ca, (np.asarray(row["reference_uv"])+rng.uniform(-1, 1, 2)).tolist(),
                    cb, (np.asarray(row["current_uv"])+rng.uniform(-1, 1, 2)).tolist())
                heights.append(float(moved["point"][2]))
            except ValueError:
                continue
        if len(heights) >= 10:
            shifts.append(float(np.median(heights)))
    if len(shifts) < 20:
        raise ValueError("Support-plane pixel-jitter sample support insufficient")
    median = float(np.median(xyz[:, 2]))
    jitter = float(np.quantile(np.abs(np.asarray(shifts)-median), .95))
    upper = float(np.quantile(xyz[:, 2], .95)+jitter+.005)
    return {
        "source": "Same-feature historical/current right-wrist brown RGB texture with current fixed-high brown-pixel reprojection; public K/T only",
        "reference_step_id": reference["step_id"],
        "current_step_id": current["step_id"],
        "accepted_texture_match_count": len(rows),
        "world_xy_coverage_m": np.ptp(xyz[:, :2], axis=0).round(4).tolist(),
        "near_horizontal_plane_z_ax_by_c": coeff.round(6).tolist(),
        "plane_tilt_deg": round(tilt, 3),
        "plane_fit_abs_residual_p95_mm": round(float(np.quantile(np.abs(residual), .95))*1000, 3),
        "matched_height_q05_q50_q95_m": np.quantile(xyz[:, 2], [.05, .5, .95]).round(6).tolist(),
        "plusminus_1px_median_height_shift_p95_mm": round(jitter*1000, 3),
        "assumed_systematic_allowance_mm": 5,
        "upper_height_for_robot_check_m": round(upper, 6),
        "fixed_high_camera_to_environment":
            current_calibration["cameras"]["cam_high"]["camera_to_environment"],
        "fixed_high_texture_checks": [{
            "pixel_uv": row["fixed_high_uv"],
            "rgb_median": row["fixed_high_rgb_median"]} for row in rows],
        "limitations": "RGB brown-texture identity and a local horizontal plane are hypotheses. Pixel perturbation excludes unknown calibration bias; the declared additional 5mm is not a certified bound. Coverage does not map all scene obstacles or hidden table edges. This plane may help compare the public hand mesh with visible support, but cannot establish contact or scene clearance. Luna must inspect the full current RGB hand sweep."
    }


def revalidate(plane, current, calibration):
    """Reuse an observed plane only with fresh fixed-camera texture checks."""
    expected = np.asarray(plane["fixed_high_camera_to_environment"], float)
    actual = np.asarray(calibration["cameras"]["cam_high"]["camera_to_environment"], float)
    if not np.allclose(expected, actual, atol=1e-6):
        raise ValueError("Fixed-high camera moved; old support plane is invalid")
    image = cv2.imread(next(x["path"] for x in current["images"]
                          if x["camera"] == "cam_high"))
    changes = []
    for row in plane["fixed_high_texture_checks"]:
        u, v = row["pixel_uv"]
        patch = image[max(0, v-3):v+4, max(0, u-3):u+4]
        median = np.median(patch.reshape(-1, 3), axis=0)
        change = float(np.mean(np.abs(
            median-np.asarray(row["rgb_median"], float))))
        if change <= 20:
            changes.append(change)
    if len(changes) < 8 or len(changes) < .6*len(plane["fixed_high_texture_checks"]):
        raise ValueError("Current fixed-high texture cannot revalidate old plane")
    updated = dict(plane)
    updated["plane_first_observed_step_id"] = plane.get(
        "plane_first_observed_step_id", plane["current_step_id"])
    updated["current_step_id"] = current["step_id"]
    updated["fresh_fixed_high_texture_retained_count"] = len(changes)
    updated["fresh_fixed_high_texture_rgb_change_p95"] = round(
        float(np.quantile(changes, .95)), 3)
    updated["current_evidence_mode"] = (
        "Earlier RGB plane, revalidated by current same-coordinate fixed-high texture; current wrist depth need not be available. This is not current object contact evidence.")
    return updated

"""Track a visible scissors hinge patch between two real wrist RGB frames.

Only public calibrated cameras, measured robot state, and image features enter.
The result locates an observed metal patch, never a grasp/contact point or a
simulator object pose. It is invalid if the source moved between frames.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import binary_closing, binary_fill_holes, label

from camera_geometry import project, ray
from gripper_pad_projection import inspect as inspect_public_pads
from pickup_visual_hull import _green_mask, _project_many


def _image(obs: dict, camera: str) -> Path:
    return next(Path(row["path"]) for row in obs["images"]
                if row["camera"] == camera)


def _high_static_check(before: dict, after: dict) -> dict:
    rows = []
    masks = []
    for obs in (before, after):
        mask = _green_mask(_image(obs, "cam_high"), "cam_high")
        masks.append(mask)
        y, x = np.nonzero(mask)
        rows.append({"count": len(x),
                     "bbox_xyxy": [int(x.min()), int(y.min()),
                                   int(x.max()), int(y.max())],
                     "centroid_uv": [float(x.mean()), float(y.mean())]})
    bbox_change = max(abs(a-b) for a, b in zip(
        rows[0]["bbox_xyxy"], rows[1]["bbox_xyxy"]))
    centroid_change = float(np.linalg.norm(
        np.asarray(rows[0]["centroid_uv"]) -
        np.asarray(rows[1]["centroid_uv"])))
    area_ratio = min(row["count"] for row in rows) / max(row["count"] for row in rows)
    overlap = masks[0] & masks[1]
    overlap_current_ratio = float(overlap.sum()/masks[1].sum())
    before_rgb = cv2.imread(str(_image(before, "cam_high")))
    after_rgb = cv2.imread(str(_image(after, "cam_high")))
    pixel_change = np.abs(before_rgb.astype(float)-after_rgb.astype(float)).mean(axis=2)
    shared_colour_change_p95 = (float(np.quantile(pixel_change[overlap], 0.95))
                                if np.any(overlap) else 1000.0)
    strict = bool(bbox_change <= 2 and centroid_change <= 4.0 and area_ratio >= 0.65)
    occlusion_compatible = bool(
        area_ratio >= 0.5 and overlap_current_ratio >= 0.95 and
        shared_colour_change_p95 <= 15.0)
    return {"reference": rows[0], "current": rows[1],
            "max_bbox_edge_change_px": bbox_change,
            "centroid_change_px": round(centroid_change, 2),
            "area_ratio": round(area_ratio, 3),
            "current_green_pixels_present_in_reference_fraction":
                round(overlap_current_ratio, 3),
            "shared_green_rgb_abs_change_p95":
                round(shared_colour_change_p95, 2),
            "stability_mode": ("full_bbox" if strict else
                               "current_visible_green_subset_of_reference"
                               if occlusion_compatible else "unverified"),
            "stable_enough_for_temporal_ray_check":
                bool(strict or occlusion_compatible),
            "limitation": "Fixed high-view green RGB supports static identity, including cases where the current hand occludes old material and remaining green pixels retain the same fixed-image location/colour. This is not proof of absolute object stationarity or complete visibility; reject large/new green displacements."}


def _wrist_features(obs: dict) -> tuple[list, np.ndarray, np.ndarray,
                                       list[int], np.ndarray]:
    path = _image(obs, "cam_right_wrist")
    gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError(f"Wrist RGB not readable: {path}")
    green = _green_mask(path, "cam_right_wrist")
    y, x = np.nonzero(green)
    bbox = [int(x.min()), int(y.min()), int(x.max()), int(y.max())]
    roi = np.zeros(gray.shape, np.uint8)
    roi[max(0, bbox[3]+5):min(gray.shape[0], bbox[3]+90),
        max(0, bbox[0]-25):min(gray.shape[1], bbox[2]+25)] = 255
    keypoints, descriptors = cv2.SIFT_create(
        nfeatures=1000, contrastThreshold=0.01).detectAndCompute(gray, roi)
    if descriptors is None or len(keypoints) < 5:
        raise ValueError("Insufficient current silver-connector SIFT features")
    return keypoints, descriptors, gray, bbox, green


def _pivot_circle(gray: np.ndarray, bbox: list[int]) -> dict:
    x0 = max(0, bbox[0] - 25)
    x1 = min(gray.shape[1], bbox[2] + 26)
    y0 = max(0, bbox[3] - 25)
    y1 = min(gray.shape[0], bbox[3] + 86)
    candidates = cv2.HoughCircles(
        gray[y0:y1, x0:x1], cv2.HOUGH_GRADIENT,
        dp=1.1, minDist=20, param1=100, param2=15,
        minRadius=6, maxRadius=25)
    if candidates is None:
        raise ValueError("Current metal pivot circle not detected")
    rows = []
    for u, v, radius in candidates[0]:
        uv = [float(u+x0), float(v+y0)]
        if not bbox[0]-10 <= uv[0] <= bbox[2]+10 or not bbox[3]+8 <= uv[1] <= bbox[3]+80:
            continue
        score = abs(uv[1] - (bbox[3]+32)) + 0.2*abs(uv[0] - (bbox[0]+bbox[2])/2)
        rows.append((score, uv, float(radius)))
    if not rows:
        raise ValueError("No named current metal pivot circle beneath green handle")
    _, uv, radius = min(rows, key=lambda row: row[0])
    return {"centre_uv": [round(x, 2) for x in uv],
            "radius_px": round(radius, 2),
            "detector": "Hough circle in current RGB silver connector ROI; diagnostic region, not grasp point"}


def _apertures(obs: dict) -> list[dict]:
    mask = _green_mask(_image(obs, "cam_right_wrist"), "cam_right_wrist")
    contour = binary_closing(mask, iterations=2)
    labels, count = label(binary_fill_holes(contour) & ~contour)
    rows = []
    for index in range(1, count+1):
        yy, xx = np.nonzero(labels == index)
        if len(xx) >= 200:
            rows.append({"uv": [float(xx.mean()), float(yy.mean())],
                         "area_px": int(len(xx))})
    rows.sort(key=lambda row: row["uv"][0])
    if len(rows) != 2:
        raise ValueError(f"Expected two current visible green apertures, found {len(rows)}")
    return rows


def _ring_centres(reference: dict, reference_calibration: dict,
                  current: dict, current_calibration: dict,
                  pad_midpoint: np.ndarray) -> dict:
    """Temporal 3D location of two projected aperture centroids, not material."""
    old = _apertures(reference)
    now = _apertures(current)
    camera_a = reference_calibration["cameras"]["cam_right_wrist"]
    camera_b = current_calibration["cameras"]["cam_right_wrist"]
    rng = np.random.default_rng(268)
    rows = []
    for index in (0, 1):
        uv_a, uv_b = old[index]["uv"], now[index]["uv"]
        tri = _triangulate(camera_a, uv_a, camera_b, uv_b)
        if (min(tri["forward_depth_m"]) <= 0 or tri["ray_angle_deg"] < 6 or
                tri["ray_gap_mm"] > 2 or max(tri["reprojection_error_px"]) > 2):
            raise ValueError(f"Green aperture centre {index} ray gate failed")
        jitter = []
        for _ in range(120):
            try:
                moved = _triangulate(
                    camera_a, (np.asarray(uv_a)+rng.uniform(-2, 2, 2)).tolist(),
                    camera_b, (np.asarray(uv_b)+rng.uniform(-2, 2, 2)).tolist())
            except ValueError:
                continue
            jitter.append(moved["point"])
        if len(jitter) < 10:
            raise ValueError("Green aperture pixel-jitter depth support is insufficient")
        values = np.asarray(jitter)
        rows.append({
            "ring_left_to_right": index,
            "reference_aperture_centroid_uv": np.round(uv_a, 2).tolist(),
            "current_aperture_centroid_uv": np.round(uv_b, 2).tolist(),
            "estimated_aperture_centre_world_xyz_m": tri["point"].round(5).tolist(),
            "aperture_centre_minus_public_pad_midpoint_xyz_mm":
                ((tri["point"]-pad_midpoint)*1000).round(1).tolist(),
            "pixel_only_plusminus_2px_xyz_q05_q95_m": {
                "q05": np.quantile(values, 0.05, axis=0).round(5).tolist(),
                "q95": np.quantile(values, 0.95, axis=0).round(5).tolist()},
            "ray_gap_mm": round(tri["ray_gap_mm"], 3),
            "ray_angle_deg": round(tri["ray_angle_deg"], 2),
            "reprojection_error_px_max": round(max(tri["reprojection_error_px"]), 2),
        })
    return {
        "source": "Two RGB green handle holes detected by contour closure at earlier and current same-episode wrist views; left/right hole identity; public K/T and fixed-high source static check",
        "rows": rows,
        "limits": "Aperture centroid is AIR inside each handle ring, not a physical material point or grasp target. Its projected centroid may shift with perspective, partial occlusion, morphology and lighting; ±2px jitter excludes calibration/systematic shape error. Require independent visible solid handle and actual inner-pad evidence before contact.",
    }


def build_aperture_geometry(reference: dict, reference_calibration: dict,
                            current: dict, current_calibration: dict) -> dict:
    """Independent green aperture diagnostic when metal texture is occluded."""
    if (reference["task"] != "general_pickup" or
            current["task"] != "general_pickup" or
            reference["step_id"] >= current["step_id"] or
            reference_calibration["step_id"] != reference["step_id"] or
            current_calibration["step_id"] != current["step_id"]):
        raise ValueError("Temporal aperture task/step/calibration mismatch")
    static = _high_static_check(reference, current)
    if not static["stable_enough_for_temporal_ray_check"]:
        raise ValueError("Fixed high RGB does not support static temporal aperture geometry")
    pads = inspect_public_pads(current, current_calibration)
    midpoint = np.mean([
        np.asarray(pads["rows"][name]["inner_facet_world_xyz_m"]).mean(axis=0)
        for name in ("link7", "link8")], axis=0)
    return {"reference_step_id": reference["step_id"],
            "current_step_id": current["step_id"],
            "fixed_high_rgb_static_check": static,
            "green_aperture_centre_temporal_geometry": _ring_centres(
                reference, reference_calibration, current,
                current_calibration, midpoint)}


def _triangulate(camera_a: dict, uv_a: list[float], camera_b: dict,
                 uv_b: list[float]) -> dict:
    eye_a, ray_a = ray(camera_a, uv_a)
    eye_b, ray_b = ray(camera_b, uv_b)
    system = np.column_stack((ray_a, -ray_b))
    distances = np.linalg.lstsq(system, eye_b-eye_a, rcond=None)[0]
    p_a = eye_a + distances[0]*ray_a
    p_b = eye_b + distances[1]*ray_b
    point = (p_a+p_b)/2
    if (not np.all(np.isfinite(distances)) or
            not np.all(np.isfinite(point)) or min(distances) <= 0):
        raise ValueError("Temporal rays do not meet in front of both cameras")
    angle = float(np.degrees(np.arccos(np.clip(abs(ray_a @ ray_b), -1, 1))))
    reproj_a = project(camera_a, point)
    reproj_b = project(camera_b, point)
    if reproj_a is None or reproj_b is None:
        raise ValueError("Temporal point cannot be projected into both public cameras")
    reproj_a, reproj_b = np.asarray(reproj_a, float), np.asarray(reproj_b, float)
    if (reproj_a.shape != (2,) or reproj_b.shape != (2,) or
            not np.all(np.isfinite(reproj_a)) or
            not np.all(np.isfinite(reproj_b))):
        raise ValueError("Temporal reprojection is non-finite or malformed")
    return {"point": point, "ray_gap_mm": float(np.linalg.norm(p_a-p_b)*1000),
            "ray_angle_deg": angle, "forward_depth_m": distances.tolist(),
            "reprojection_error_px": [float(np.linalg.norm(np.asarray(uv_a)-reproj_a)),
                                      float(np.linalg.norm(np.asarray(uv_b)-reproj_b))]}


def _temporal_green_support(reference: dict, reference_calibration: dict,
                            current: dict, current_calibration: dict,
                            pad_midpoint: np.ndarray) -> dict:
    """Intersect current green rays with fixed high and historical wrist masks.

    Historical mask is valid only after the independent static-scene gate. The
    returned points are an image-consistent hypothesis set, not a surface.
    """
    cur_wrist = _green_mask(_image(current, "cam_right_wrist"),
                            "cam_right_wrist")
    cur_high = _green_mask(_image(current, "cam_high"), "cam_high")
    ref_wrist = _green_mask(_image(reference, "cam_right_wrist"),
                            "cam_right_wrist")
    yy, xx = np.nonzero(cur_wrist)
    samples = np.arange(0, len(xx), 3)
    uv = np.column_stack((xx[samples], yy[samples]))
    cam = current_calibration["cameras"]["cam_right_wrist"]
    transform = np.asarray(cam["camera_to_environment"], float)
    k = np.asarray(cam["intrinsic"], float)
    rays = np.column_stack(((uv[:, 0]-k[0, 2])/k[0, 0],
                            -(uv[:, 1]-k[1, 2])/k[1, 1],
                            -np.ones(len(uv)))) @ transform[:3, :3].T
    rays /= np.linalg.norm(rays, axis=1, keepdims=True)
    depths = np.arange(0.15, 1.201, 0.005)
    points = (transform[:3, 3] + rays[:, None, :] *
              depths[None, :, None]).reshape(-1, 3)
    workspace = ((points[:, 0] >= 0.15) & (points[:, 0] <= 0.55) &
                 (points[:, 1] >= -0.30) & (points[:, 1] <= 0.20) &
                 (points[:, 2] >= 0.65) & (points[:, 2] <= 1.00))
    points = points[workspace]
    counts = {"workspace_candidate_count": len(points)}
    for name, camera, mask in (
        ("current_fixed_high", current_calibration["cameras"]["cam_high"],
         cur_high),
        ("historical_right_wrist", reference_calibration["cameras"]["cam_right_wrist"],
         ref_wrist),
    ):
        projected, positive_depth = _project_many(camera, points)
        pixel = np.rint(projected).astype(int)
        in_frame = ((positive_depth > 0) & (pixel[:, 0] >= 0) &
                    (pixel[:, 0] < mask.shape[1]) & (pixel[:, 1] >= 0) &
                    (pixel[:, 1] < mask.shape[0]))
        accepted = np.zeros(len(points), bool)
        accepted[in_frame] = mask[pixel[in_frame, 1], pixel[in_frame, 0]]
        points = points[accepted]
        counts[f"after_{name}_count"] = len(points)
        if len(points) < 50:
            raise ValueError("Temporal green silhouette intersection lacks support")
    residual_mm = (points-pad_midpoint)*1000
    distance_mm = np.linalg.norm(residual_mm, axis=1)
    return {
        "sampled_support_counts": counts,
        "visual_green_support_world_xyz_q05_q50_q95_m": {
            name: np.quantile(points, q, axis=0).round(5).tolist()
            for name, q in (("q05", 0.05), ("q50", 0.5), ("q95", 0.95))},
        "visual_green_support_minus_public_pad_xyz_q05_q50_q95_mm": {
            name: np.quantile(residual_mm, q, axis=0).round(1).tolist()
            for name, q in (("q05", 0.05), ("q50", 0.5), ("q95", 0.95))},
        "visual_green_support_distance_to_pad_q05_q50_q95_mm":
            np.quantile(distance_mm, (0.05, 0.5, 0.95)).round(1).tolist(),
        "limits": "Three RGB silhouette intersection is a sampled possible green volume under the fixed-high static-source assumption and declared 0.15–1.20m ray-depth / workspace grid. Morphology, occlusion, calibration and sampling can exclude physical points. Quantiles are not calibrated confidence or physical clearance; support points are not solid-handle contact locations.",
    }


def build(reference: dict, reference_calibration: dict,
          current: dict, current_calibration: dict) -> dict:
    if (reference["task"] != "general_pickup" or current["task"] != "general_pickup" or
            reference["step_id"] >= current["step_id"] or
            reference_calibration["step_id"] != reference["step_id"] or
            current_calibration["step_id"] != current["step_id"]):
        raise ValueError("Task/step/current camera contracts do not match")
    static = _high_static_check(reference, current)
    if not static["stable_enough_for_temporal_ray_check"]:
        raise ValueError("Fixed high RGB does not support static temporal geometry")
    ref_keys, ref_desc, _, ref_bbox, _ = _wrist_features(reference)
    cur_keys, cur_desc, cur_gray, cur_bbox, _ = _wrist_features(current)
    pivot = _pivot_circle(cur_gray, cur_bbox)
    camera_a = reference_calibration["cameras"]["cam_right_wrist"]
    camera_b = current_calibration["cameras"]["cam_right_wrist"]
    candidates = []
    used_current = set()
    used_reference = set()
    matches = sorted(cv2.BFMatcher().knnMatch(ref_desc, cur_desc, k=2),
                     key=lambda pair: pair[0].distance)
    for pair in matches:
        if len(pair) != 2:
            continue
        match, alternative = pair
        if match.distance >= 0.8*alternative.distance:
            continue
        uv_a = np.asarray(ref_keys[match.queryIdx].pt)
        uv_b = np.asarray(cur_keys[match.trainIdx].pt)
        if (np.linalg.norm(uv_b-pivot["centre_uv"]) > 29 or
                uv_b[1] < cur_bbox[3]+5):
            continue
        unique_a = tuple(np.rint(uv_a).astype(int))
        unique_b = tuple(np.rint(uv_b).astype(int))
        if unique_a in used_reference or unique_b in used_current:
            continue
        try:
            tri = _triangulate(camera_a, uv_a.tolist(), camera_b, uv_b.tolist())
        except ValueError:
            continue
        point = tri["point"]
        if (min(tri["forward_depth_m"]) <= 0 or
                tri["ray_gap_mm"] > 1.5 or tri["ray_angle_deg"] < 5.0 or
                max(tri["reprojection_error_px"]) > 2.0 or
                not 0.65 <= point[2] <= 0.85):
            continue
        used_reference.add(unique_a)
        used_current.add(unique_b)
        candidates.append({"reference_uv": uv_a.tolist(),
                           "current_uv": uv_b.tolist(),
                           "descriptor_distance": float(match.distance),
                           **tri})
    if len(candidates) < 3:
        raise ValueError(f"Only {len(candidates)} geometrically consistent temporal matches")
    points = np.asarray([row["point"] for row in candidates])
    # Max-consensus cluster in world coordinates keeps repeated features on
    # the same small visible metal patch without a benchmark object pose.
    neighborhoods = [np.linalg.norm(points - point, axis=1) <= 0.012
                     for point in points]
    support = max(neighborhoods, key=lambda mask: int(mask.sum()))
    centre = np.median(points[support], axis=0)
    support &= np.linalg.norm(points-centre, axis=1) <= 0.012
    inliers = [row for row, ok in zip(candidates, support) if ok]
    if len(inliers) < 3:
        raise ValueError("Temporal image matches do not form a three-feature metal patch")
    xyz = np.asarray([row["point"] for row in inliers])
    rng = np.random.default_rng(165)
    perturbed = []
    for row in inliers:
        for _ in range(80):
            offset_a = rng.uniform(-2, 2, 2)
            offset_b = rng.uniform(-2, 2, 2)
            try:
                moved = _triangulate(camera_a,
                                     (np.asarray(row["reference_uv"])+offset_a).tolist(),
                                     camera_b,
                                     (np.asarray(row["current_uv"])+offset_b).tolist())
            except ValueError:
                continue
            perturbed.append(moved["point"])
    if len(perturbed) < 20:
        raise ValueError("Metal-patch pixel-jitter depth support is insufficient")
    sensitivity = np.asarray(perturbed)
    obs_with_calibration = dict(current)
    obs_with_calibration["camera_calibration"] = current_calibration
    pads = inspect_public_pads(obs_with_calibration, current_calibration)
    pad_facets = [np.asarray(pads["rows"][name]["inner_facet_world_xyz_m"])
                  for name in ("link7", "link8")]
    pad_centres = [facet.mean(axis=0) for facet in pad_facets]
    midpoint = np.mean(pad_centres, axis=0)
    median = np.median(xyz, axis=0)
    try:
        apertures = _ring_centres(reference, reference_calibration,
                                  current, current_calibration, midpoint)
        aperture_error = None
    except ValueError as error:
        apertures = None
        aperture_error = str(error)
    return {
        "source": "SIFT-matched right-wrist RGB silver hinge patch at two observed steps; public K/T from measured LINK6; current fixed-high RGB static check; public X5 URDF/STL pad facets",
        "task": current["task"], "reference_step_id": reference["step_id"],
        "current_step_id": current["step_id"],
        "fixed_high_rgb_static_check": static,
        "reference_green_bbox_xyxy": ref_bbox,
        "current_green_bbox_xyxy": cur_bbox,
        "current_pivot_circle": pivot,
        "accepted_sift_feature_count": len(inliers),
        "visual_metal_patch_world_xyz_median_m": median.round(5).tolist(),
        "visual_metal_patch_world_xyz_q05_q95_m": {
            "q05": np.quantile(xyz, 0.05, axis=0).round(5).tolist(),
            "q95": np.quantile(xyz, 0.95, axis=0).round(5).tolist()},
        "pixel_only_plusminus_2px_sensitivity_xyz_q05_q95_m": {
            "q05": np.quantile(sensitivity, 0.05, axis=0).round(5).tolist(),
            "q95": np.quantile(sensitivity, 0.95, axis=0).round(5).tolist()},
        "metal_patch_minus_public_pad_midpoint_xyz_mm":
            ((median-midpoint)*1000).round(1).tolist(),
        "green_aperture_centre_temporal_geometry": apertures,
        "green_aperture_centre_error": aperture_error,
        "temporal_green_visual_support": _temporal_green_support(
            reference, reference_calibration, current, current_calibration,
            midpoint),
        "public_inner_pad_centres_world_m": {
            name: centre.round(5).tolist()
            for name, centre in zip(("link7", "link8"), pad_centres)},
        "inlier_ray_gap_mm_max": round(max(row["ray_gap_mm"] for row in inliers), 3),
        "inlier_ray_angle_deg_min": round(min(row["ray_angle_deg"] for row in inliers), 2),
        "inlier_reprojection_error_px_max": round(max(
            max(row["reprojection_error_px"]) for row in inliers), 2),
        "inlier_features": [{
            "reference_uv": np.round(row["reference_uv"], 2).tolist(),
            "current_uv": np.round(row["current_uv"], 2).tolist(),
            "estimated_point_world_m": row["point"].round(5).tolist(),
            "ray_gap_mm": round(row["ray_gap_mm"], 3),
            "angle_deg": round(row["ray_angle_deg"], 2),
            "descriptor_distance": round(row["descriptor_distance"], 1),
        } for row in inliers[:12]],
        "limits": "Feature cluster is an observed metal connector/hinge PATCH, not a whole scissors pose, green grasp point, physical contact, free-space certificate, or calibrated confidence region. Pixel jitter omits calibration/model error. Reject if fixed high RGB no longer supports static source, if current features are occluded, or if ray match/reprojection gates fail. Do not pass evaluator/true object state to models.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-observation", type=Path, required=True)
    parser.add_argument("--reference-calibration", type=Path, required=True)
    parser.add_argument("--current-observation", type=Path, required=True)
    parser.add_argument("--current-calibration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = build(json.loads(args.reference_observation.read_text()),
                   json.loads(args.reference_calibration.read_text()),
                   json.loads(args.current_observation.read_text()),
                   json.loads(args.current_calibration.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output),
                      "accepted_sift_feature_count": result["accepted_sift_feature_count"],
                      "metal_patch_world_m": result["visual_metal_patch_world_xyz_median_m"],
                      "ray_gap_mm_max": result["inlier_ray_gap_mm_max"]}))


if __name__ == "__main__":
    main()

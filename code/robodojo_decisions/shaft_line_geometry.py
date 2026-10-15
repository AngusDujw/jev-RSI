"""Recover a visible mallet shaft line from RGB, without matched interior points.

Two image lines back-project to two planes whose intersection is a candidate
3D shaft axis. Pro labels visible bare wood in each current RGB view; it need
not pretend that arbitrary points along an untextured shaft correspond.
No simulator object state, contact or reward enters the model or calculation.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

from camera_geometry import project, ray


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _pixel_line_distance(pixel, near, far) -> float:
    p, a, b = [np.asarray(x, float) for x in (pixel, near, far)]
    return float(abs(np.cross(b - a, p - a)) / np.linalg.norm(b - a))


def _segment_fraction(pixel, near, far) -> float:
    p, a, b = [np.asarray(x, float) for x in (pixel, near, far)]
    return float(np.dot(p - a, b - a) / np.dot(b - a, b - a))


def estimate_line(calibration: dict, annotation: dict, anchor: dict) -> dict:
    """Intersect two public-camera shaft planes near a validated free-end anchor."""
    cameras = calibration["cameras"]
    views = annotation["views"]
    names = ("cam_high", "cam_left_wrist")
    if set(views) != set(names):
        raise ValueError("Shaft requires high and left-wrist centerlines")
    normals, offsets, segment_uv = [], [], {}
    for name in names:
        entry = views[name]
        near, far = entry["near_free_end_uv"], entry["farther_along_shaft_uv"]
        radius = entry["uncertainty_radius_px"]
        width, height = cameras[name]["size"]
        if (not isinstance(radius, (int, float)) or not 1 <= radius <= 10 or
                any(not isinstance(p, list) or len(p) != 2 or
                    any(not isinstance(v, (int, float)) for v in p) or
                    not 0 <= p[0] < width or not 0 <= p[1] < height
                    for p in (near, far)) or
                np.linalg.norm(np.asarray(far) - np.asarray(near)) < 20):
            raise ValueError(f"Invalid or short shaft line in {name}")
        eye, d1 = ray(cameras[name], near)
        _, d2 = ray(cameras[name], far)
        n = np.cross(d1, d2)
        if np.linalg.norm(n) < 0.01:
            raise ValueError("Shaft back-projection plane degenerate")
        n /= np.linalg.norm(n)
        normals.append(n)
        offsets.append(float(np.dot(n, eye)))
        segment_uv[name] = {"near": near, "far": far, "uncertainty_radius_px": radius}
    direction = np.cross(normals[0], normals[1])
    plane_sine = float(np.linalg.norm(direction))
    if plane_sine < 0.12:
        raise ValueError("Two shaft planes are nearly parallel")
    direction /= plane_sine
    anchor_xyz = np.asarray(anchor["estimated_position_environment_m"], float)
    matrix = np.vstack((normals[0], normals[1], direction))
    point = np.linalg.solve(matrix, np.asarray(offsets + [float(np.dot(direction, anchor_xyz))]))
    if np.linalg.norm(point - anchor_xyz) > 0.008:
        raise ValueError("Shaft axis misses validated free-end center by >8 mm")
    high = cameras["cam_high"]
    plus = project(high, point + 0.025 * direction)
    minus = project(high, point - 0.025 * direction)
    high_far = np.asarray(segment_uv["cam_high"]["far"], float)
    high_near = np.asarray(segment_uv["cam_high"]["near"], float)
    if np.dot(np.asarray(plus) - np.asarray(minus), high_far - high_near) < 0:
        direction *= -1
    candidate = point + 0.025 * direction
    checks = {}
    accepted = True
    for name in names:
        camera = cameras[name]
        entry = segment_uv[name]
        uv_anchor = project(camera, point)
        uv_grip = project(camera, candidate)
        if uv_anchor is None or uv_grip is None:
            raise ValueError("Shaft projects behind camera")
        near, far = entry["near"], entry["far"]
        anchor_line_error = _pixel_line_distance(uv_anchor, near, far)
        grip_line_error = _pixel_line_distance(uv_grip, near, far)
        fraction = _segment_fraction(uv_grip, near, far)
        inside = (-0.1 <= fraction <= 1.1 and
                  grip_line_error <= entry["uncertainty_radius_px"] + 2 and
                  anchor_line_error <= entry["uncertainty_radius_px"] + 3)
        accepted &= inside
        checks[name] = {"anchor_uv": uv_anchor, "interior_25mm_uv": uv_grip,
                        "anchor_line_error_px": anchor_line_error,
                        "interior_line_error_px": grip_line_error,
                        "interior_segment_fraction": fraction,
                        "within_current_visible_segment": inside}
    result = {
        "source": "two current RGB shaft centerlines + public K/T + camera-derived same-point free end",
        "accepted": bool(accepted),
        "camera_step_id": calibration["step_id"],
        "shaft_axis_near_free_end_environment_m": point.tolist(),
        "shaft_axis_direction_toward_ball": direction.tolist(),
        "interior_25mm_candidate_environment_m": candidate.tolist(),
        "free_end_axis_offset_m": float(np.linalg.norm(point - anchor_xyz)),
        "interplane_sine": plane_sine,
        "checks": checks,
        "caution": "A shaft-axis/grip-region hypothesis, not cylinder radius, gripper orientation, collision-free approach, grasp, or native success. Interior points need no pixel-to-pixel physical correspondence."
    }
    return result


def annotation_sensitivity(calibration: dict, annotation: dict, anchor: dict,
                           nominal: dict, samples: int = 250) -> dict:
    """Propagate Pro's pixel radii through the line reconstruction for review."""
    rng = np.random.default_rng(13)
    positions, axis_angles = [], []
    nominal_position = np.asarray(nominal["interior_25mm_candidate_environment_m"])
    nominal_axis = np.asarray(nominal["shaft_axis_direction_toward_ball"])
    for _ in range(samples):
        perturbed = copy.deepcopy(annotation)
        for view in perturbed["views"].values():
            sigma = float(view["uncertainty_radius_px"]) / 2.0
            for key in ("near_free_end_uv", "farther_along_shaft_uv"):
                view[key] = (np.asarray(view[key], float) +
                             rng.normal(0, sigma, 2)).tolist()
        try:
            candidate = estimate_line(calibration, perturbed, anchor)
            if not candidate["accepted"]:
                continue
        except ValueError:
            continue
        positions.append(candidate["interior_25mm_candidate_environment_m"])
        alignment = np.clip(np.dot(nominal_axis,
                                   candidate["shaft_axis_direction_toward_ball"]), -1, 1)
        axis_angles.append(float(np.degrees(np.arccos(alignment))))
    if not positions:
        return {"samples": samples, "accepted_perturbations": 0,
                "grasp_region_precision_ready": False,
                "method": "independent Gaussian pixel perturbations with sigma=Pro radius/2; no privileged state"}
    distance_mm = np.linalg.norm(np.asarray(positions) - nominal_position, axis=1) * 1000
    position_p95 = float(np.percentile(distance_mm, 95))
    angle_p95 = float(np.percentile(axis_angles, 95))
    return {
        "samples": samples, "accepted_perturbations": len(positions),
        "candidate_position_error_mm_p50": float(np.percentile(distance_mm, 50)),
        "candidate_position_error_mm_p95": position_p95,
        "axis_direction_error_deg_p50": float(np.percentile(axis_angles, 50)),
        "axis_direction_error_deg_p95": angle_p95,
        "grasp_region_precision_ready": bool(position_p95 < 5 and angle_p95 < 10 and
                                               len(positions) >= 0.8 * samples),
        "method": "independent Gaussian pixel perturbations with sigma=Pro radius/2; no privileged state"
    }


def color_refine(calibration: dict, annotation: dict, anchor: dict,
                 observation: dict, roi_config: dict, manual: dict) -> dict:
    """Fit a shaft centerline to pale-wood pixels inside reviewed RGB regions."""
    images = {item["camera"]: Path(item["path"]) for item in observation["images"]}
    refined = {"status": "visible", "views": {}}
    masks = {}
    for name in ("cam_high", "cam_left_wrist"):
        config = roi_config[name]
        x1, x2, y1, y2 = config["bounds_xyxy"]
        array = np.asarray(Image.open(images[name]).convert("RGB"), dtype=np.int16)
        height, width = array.shape[:2]
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise ValueError("RGB shaft region outside current image")
        crop = array[y1:y2, x1:x2]
        selected = ((crop[:, :, 0] > config["minimum_rgb"][0]) &
                    (crop[:, :, 1] > config["minimum_rgb"][1]) &
                    (crop[:, :, 2] > config["minimum_rgb"][2]) &
                    ((crop[:, :, 0] - crop[:, :, 1]) < config["maximum_r_minus_g"]))
        ys, xs = np.nonzero(selected)
        points = np.column_stack((xs + x1, ys + y1))
        if len(points) < (40 if name == "cam_high" else 200):
            raise ValueError(f"Insufficient pale-wood shaft pixels in {name}")
        center = points.mean(axis=0)
        values, vectors = np.linalg.eigh(np.cov(points.T))
        if values[1] / max(values[0], 0.01) < 25:
            raise ValueError(f"Color mask is not a sufficiently straight shaft in {name}")
        direction = vectors[:, -1]
        pro_direction = (np.asarray(annotation["views"][name]["farther_along_shaft_uv"], float) -
                         np.asarray(annotation["views"][name]["near_free_end_uv"], float))
        if float(np.dot(direction, pro_direction)) < 0:
            direction = -direction
        if float(np.dot(direction, pro_direction) /
                 (np.linalg.norm(direction) * np.linalg.norm(pro_direction))) < 0.985:
            raise ValueError(f"Color line deviates from Pro-identified shaft in {name}")
        scalar = (points - center) @ direction
        near = center + np.percentile(scalar, 5) * direction
        far = center + np.percentile(scalar, 95) * direction
        refined["views"][name] = {
            "near_free_end_uv": near.tolist(),
            "farther_along_shaft_uv": far.tolist(),
            "uncertainty_radius_px": config["line_fit_uncertainty_radius_px"],
        }
        masks[name] = {"pixel_count": int(len(points)),
                       "covariance_eigenvalues_px2": values.tolist(),
                       "region_xyxy": config["bounds_xyxy"]}
    geometry = estimate_line(calibration, refined, anchor)
    geometry["annotation_sensitivity"] = annotation_sensitivity(
        calibration, refined, anchor, geometry)
    discrepancy = float(np.linalg.norm(
        np.asarray(geometry["interior_25mm_candidate_environment_m"]) -
        np.asarray(manual["interior_25mm_candidate_environment_m"])))
    if discrepancy > 0.005:
        geometry["accepted"] = False
    geometry["pro_centerline_agreement_m"] = discrepancy
    geometry["color_masks"] = masks
    geometry["refined_annotation"] = refined
    geometry["source"] += " + pale-wood RGB mask within reviewed regions"
    geometry["caution"] += " Color thresholds and regions are scene-specific; do not treat fit sensitivity as a contact certificate."
    return geometry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--free-end-geometry", type=Path, required=True)
    parser.add_argument("--global-experience", type=Path, required=True)
    parser.add_argument("--task-experience", type=Path, required=True)
    parser.add_argument("--color-roi", type=Path,
                        help="Optional reviewed current-RGB pale-wood regions and thresholds")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    obs = json.loads(args.observation.read_text())
    calibration = json.loads(args.calibration.read_text())
    anchor = json.loads(args.free_end_geometry.read_text())
    if (obs["task"] != "play_Xylophone" or
            calibration["step_id"] != obs["step_id"] or
            anchor["camera_step_id"] != obs["step_id"] or
            not anchor["accepted"]):
        raise ValueError("Current xylophone same-step camera and free-end anchor required")
    experience = {"global": args.global_experience.read_text(),
                  "task": args.task_experience.read_text()}
    public = {"task": obs["task"], "instruction": obs["instruction"],
              "step_id": obs["step_id"], "current_eef": obs["current_eef"],
              "current_joint_state": obs["current_state"],
              "camera_calibration": calibration,
              "validated_mallet_wood_free_end": anchor,
              "experience": experience}
    system = (
        "Identify the specified wooden shaft using the supplied observations. "
        "Using ONLY current three RGB, public camera calibration, measured robot "
        "state and validated camera-derived mallet wooden free-end, identify the "
        "SAME bare wooden shaft in cam_high and cam_left_wrist. In each current "
        "image mark TWO centerline pixels on a plainly visible, straight bare "
        "wood segment: near_free_end_uv and farther_along_shaft_uv toward the pink "
        "ball. The two point pairs describe an image LINE, so the high and wrist "
        "farther points need NOT correspond to the same physical point. Exclude "
        "the blue-white object, xylophone, robot fingers and any occluded shaft. "
        "If a visible segment in either view is shorter than 20 pixels, or shaft "
        "identity/axis is ambiguous, return status=uncertain, views={} and explain. "
        "Otherwise return JSON with status=visible, views mapping exactly "
        "cam_high and cam_left_wrist to near_free_end_uv [u,v], "
        "farther_along_shaft_uv [u,v], uncertainty_radius_px from 1 to 10, "
        "and explanation. Do not assert world object pose, contact, collision "
        "clearance or task success."
    )
    parts = [{"type": "text", "text": json.dumps(public, ensure_ascii=False)}]
    images = []
    for item in obs["images"]:
        if item["camera"] not in {"cam_high", "cam_left_wrist", "cam_right_wrist"}:
            raise ValueError("Unexpected camera")
        path = Path(item["path"])
        raw = path.read_bytes()
        images.append({"camera": item["camera"], "path": str(path),
                       "sha256": hashlib.sha256(raw).hexdigest()})
        parts.extend(({"type": "text", "text": "CURRENT RGB " + item["camera"]},
                      {"type": "image_url", "image_url": {
                          "url": "data:image/png;base64," + base64.b64encode(raw).decode("ascii")}}))
    _write(args.output / "input-manifest.json", {
        "model": "gpt-6.1-sol", "reasoning_effort": "high", "public": public,
        "images": images,
        "experience_sha256": {k: hashlib.sha256(v.encode()).hexdigest()
                              for k, v in experience.items()}})
    payload = {"model": "gpt-6.1-sol", "reasoning_effort": "high",
               "response_format": {"type": "json_object"}, "stream": False,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": parts}]}
    from model_input_language import require_english_model_input
    require_english_model_input(payload, "legacy shaft planner request")
    request = urllib.request.Request("http://127.0.0.1:18883/v1/chat/completions",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(request, timeout=1300) as handle:
        response = json.load(handle)
    _write(args.output / "planner-response.json", response)
    annotation = json.loads(response["choices"][0]["message"]["content"])
    _write(args.output / "annotation.json", annotation)
    if annotation.get("status") != "visible":
        raise ValueError("Pro could not identify one bare shaft segment in both current RGB views")
    result = estimate_line(calibration, annotation, anchor)
    result["annotation_sensitivity"] = annotation_sensitivity(
        calibration, annotation, anchor, result)
    _write(args.output / "line-geometry.json", result)
    if args.color_roi:
        refined = color_refine(calibration, annotation, anchor, obs,
                               json.loads(args.color_roi.read_text()), result)
        _write(args.output / "color-refined-geometry.json", refined)
    print(json.dumps({"accepted": result["accepted"],
                      "interplane_sine": result["interplane_sine"],
                      "checks": result["checks"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

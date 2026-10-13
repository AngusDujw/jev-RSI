"""Numeric sensor-derived error and world-axis image effects for a right-hand decision.

Only current RGB landmark annotations, public K/T and measured robot/URDF/STL enter.
No simulator object pose, contact, reward or evaluator state is consulted.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np

from camera_geometry import estimate, project
from gripper_pad_projection import inspect as inspect_public_pads


def _image_paths(obs: dict) -> dict[str, Path]:
    return {item["camera"]: Path(item["path"]) for item in obs["images"]}


def _within(camera: dict, uv: list[float] | None) -> bool:
    return bool(uv is not None and 0 <= uv[0] < camera["size"][0]
                and 0 <= uv[1] < camera["size"][1])


def _uncertainty_points(calibration: dict, geometry: dict) -> np.ndarray:
    views = {name: {"pixel_uv": row["observed_uv"],
                    "uncertainty_radius_px": row["annotation_uncertainty_radius_px"]}
             for name, row in geometry["checks"].items()}
    point = (geometry["estimated_position_environment_m"] if geometry["accepted"] else
             geometry["candidate_position_environment_m"])
    rows = [np.asarray(point, float)]
    for name, item in views.items():
        for du, dv in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            variant = copy.deepcopy(views)
            variant[name]["pixel_uv"] = [item["pixel_uv"][0] +
                                         du * item["uncertainty_radius_px"],
                                         item["pixel_uv"][1] +
                                         dv * item["uncertainty_radius_px"]]
            trial = estimate(calibration, {"views": variant})
            if all(depth > 0 for depth in trial["positive_ray_distances_m"]):
                rows.append(np.asarray(trial["candidate_position_environment_m"], float))
    return np.stack(rows)


def build(obs: dict, geometry: dict, *, step_m: float = 0.005) -> dict:
    if obs["task"] != "general_pickup":
        raise ValueError("This pilot is scoped to general_pickup")
    if (not (geometry["accepted"] or geometry.get("diagnostic_only_near_consistent")) or
            geometry["camera_step_id"] != obs["step_id"] or
            set(geometry["views"]) != {"cam_high", "cam_right_wrist"}):
        raise ValueError("Current accepted high/right same-point geometry required")
    if not 0 < step_m <= 0.01:
        raise ValueError("Diagnostic axis scale must be <=10 mm")
    calibration = obs["camera_calibration"]
    if calibration["step_id"] != obs["step_id"]:
        raise ValueError("Current RGB/K/T step mismatch")
    pad_data = inspect_public_pads(obs, calibration)
    facets = [np.asarray(pad_data["rows"][name]["inner_facet_world_xyz_m"], float)
              for name in ("link7", "link8")]
    centers = [points.mean(axis=0) for points in facets]
    midpoint = np.mean(centers, axis=0)
    point = (geometry["estimated_position_environment_m"] if geometry["accepted"] else
             geometry["candidate_position_environment_m"])
    landmark = np.asarray(point, float)
    uncertain = _uncertainty_points(calibration, geometry)
    errors = uncertain - midpoint
    if not geometry["accepted"]:
        # The two rays miss by `gap`; enlarge each reported component rather
        # than silently upgrading a near miss to a metric correspondence.
        gap = float(geometry["ray_gap_m"])
        errors = np.concatenate((errors - gap, errors + gap))
    cameras = calibration["cameras"]
    baseline = {}
    for name, camera in cameras.items():
        source_uv = project(camera, landmark)
        pad_uv = project(camera, midpoint)
        baseline[name] = {"landmark_uv": source_uv if _within(camera, source_uv) else None,
                          "pad_midpoint_uv": pad_uv if _within(camera, pad_uv) else None,
                          "both_projected_in_frame":
                          _within(camera, source_uv) and _within(camera, pad_uv)}
    rows = {}
    for axis_index, axis in enumerate("xyz"):
        for sign, label in ((-1, "negative"), (1, "positive")):
            delta = np.zeros(3)
            delta[axis_index] = sign * step_m
            projections = {}
            for name, camera in cameras.items():
                moved = copy.deepcopy(camera)
                if name == "cam_right_wrist":
                    moved["camera_to_environment"] = np.asarray(
                        camera["camera_to_environment"], float).copy().tolist()
                    for index in range(3):
                        moved["camera_to_environment"][index][3] += float(delta[index])
                # Fixed high/left camera sees moving pads; moving right wrist
                # sees the fixed visual landmark shift in the opposite direction.
                source_uv = project(moved, landmark)
                pad_uv = project(moved, midpoint + delta)
                before = baseline[name]
                visible = (_within(camera, source_uv) and _within(camera, pad_uv) and
                           _within(camera, before["landmark_uv"]) and
                           _within(camera, before["pad_midpoint_uv"]))
                projections[name] = {
                    "source_uv_after": source_uv if visible else None,
                    "pad_midpoint_uv_after": pad_uv if visible else None,
                    "source_delta_uv_px": (np.subtract(source_uv, before["landmark_uv"]).round(2).tolist()
                                            if visible else None),
                    "pad_delta_uv_px": (np.subtract(pad_uv, before["pad_midpoint_uv"]).round(2).tolist()
                                         if visible else None),
                    "both_projected_in_frame": visible,
                }
            rows[f"{axis}_{label}"] = {
                "world_link6_translation_m": delta.tolist(),
                "predicted_landmark_to_pad_error_norm_mm_after":
                    round(float(np.linalg.norm(landmark - midpoint - delta) * 1000), 2),
                "camera_effect": projections,
            }
    return {
        "task": obs["task"], "step_id": obs["step_id"],
        "landmark_identity": geometry["landmark"],
        "landmark_is_grasp_target": False,
        "strict_stereo_accepted": geometry["accepted"],
        "diagnostic_only_near_consistent": geometry.get("diagnostic_only_near_consistent", False),
        "same_point_stereo": {"ray_gap_mm": round(1000 * geometry["ray_gap_m"], 2),
                              "ray_condition": geometry["ray_condition"],
                              "reprojection": geometry["checks"]},
        "landmark_world_hypothesis_m": landmark.tolist(),
        "public_opposing_inner_pad_centers_world_m": [p.tolist() for p in centers],
        "pad_midpoint_world_m": midpoint.tolist(),
        "landmark_minus_pad_midpoint_mm": (1000 * (landmark - midpoint)).round(2).tolist(),
        "pixel_uncertainty_sampled_error_interval_mm": {
            "min": (1000 * errors.min(axis=0)).round(2).tolist(),
            "max": (1000 * errors.max(axis=0)).round(2).tolist(),
            "samples": len(errors),
        },
        "current_projections": baseline,
        "world_axis_effect_at_5mm": rows,
        "limits": "Scissors hinge is a camera-derived diagnostic point, not a handle grasp target. "
                  "Pad facets are public robot-mesh geometry and may be occluded. "
                  "Axis table is first-order rigid scene/robot projection, not a collision or tracking guarantee. "
                  "No simulator object pose, contact or evaluator state is used.",
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    obs = json.loads(args.observation.read_text())
    obs["camera_calibration"] = json.loads(args.calibration.read_text())
    geometry = json.loads(args.geometry.read_text())
    if isinstance(geometry, list) and len(geometry) == 1:
        geometry = geometry[0]
    result = build(obs, geometry)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output),
                      "error_mm": result["landmark_minus_pad_midpoint_mm"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

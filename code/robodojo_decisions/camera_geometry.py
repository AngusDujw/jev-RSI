"""Triangulate a Pro-annotated RGB landmark from public camera calibration."""

import argparse
import copy
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation


def eef_transform(pose):
    """Measured LINK6 world pose, wxyz quaternion, as a rigid transform."""
    quaternion = np.asarray(pose["quaternion_wxyz"], float)
    transform = np.eye(4)
    transform[:3, :3] = Rotation.from_quat(quaternion[[1, 2, 3, 0]]).as_matrix()
    transform[:3, 3] = np.asarray(pose["position"], float)
    return transform


def propagate_wrist_calibration(initial, initial_eef, current_eef, step_id):
    """Propagate rigid wrist camera mounts using only public initial K/T and measured LINK6."""
    result = copy.deepcopy(initial)
    result["source"] = "initial public RGB calibration + measured LINK6 rigid wrist mount"
    result["step_id"] = int(step_id)
    for arm in ("left", "right"):
        name = f"cam_{arm}_wrist"
        initial_camera = np.asarray(initial["cameras"][name]["camera_to_environment"], float)
        start_link = eef_transform(initial_eef[arm])
        current_link = eef_transform(current_eef[arm])
        result["cameras"][name]["camera_to_environment"] = (
            current_link @ np.linalg.inv(start_link) @ initial_camera).tolist()
    return result


def ray(camera, uv):
    k = np.asarray(camera["intrinsic"], float)
    transform = np.asarray(camera["camera_to_environment"], float)
    u, v = map(float, uv)
    direction = transform[:3, :3] @ np.array(
        [(u - k[0, 2]) / k[0, 0], -(v - k[1, 2]) / k[1, 1], -1.0])
    return transform[:3, 3], direction / np.linalg.norm(direction)


def project(camera, point):
    k = np.asarray(camera["intrinsic"], float)
    transform = np.asarray(camera["camera_to_environment"], float)
    local = transform[:3, :3].T @ (point - transform[:3, 3])
    depth = -local[2]
    if depth <= 0:
        return None
    return [float(k[0, 0] * local[0] / depth + k[0, 2]),
            float(k[1, 2] - k[1, 1] * local[1] / depth)]


def estimate(calibration, annotation):
    views = annotation["views"]
    if len(views) != 2:
        raise ValueError("Exactly two current RGB views are required")
    names = list(views)
    a, b = names
    cameras = calibration["cameras"]
    if a not in cameras or b not in cameras:
        raise ValueError("Missing camera calibration")
    eye_a, ray_a = ray(cameras[a], views[a]["pixel_uv"])
    eye_b, ray_b = ray(cameras[b], views[b]["pixel_uv"])
    system = np.column_stack((ray_a, -ray_b))
    condition = float(np.linalg.cond(system))
    distances = np.linalg.lstsq(system, eye_b - eye_a, rcond=None)[0]
    point_a = eye_a + distances[0] * ray_a
    point_b = eye_b + distances[1] * ray_b
    point = (point_a + point_b) / 2
    gap = float(np.linalg.norm(point_a - point_b))
    checks = {}
    for name in names:
        predicted = project(cameras[name], point)
        observed = np.asarray(views[name]["pixel_uv"], float)
        error = (float(np.linalg.norm(np.asarray(predicted) - observed))
                 if predicted is not None else None)
        radius = float(views[name]["uncertainty_radius_px"])
        checks[name] = {"observed_uv": observed.tolist(),
                        "projected_uv": predicted,
                        "reprojection_error_px": error,
                        "annotation_uncertainty_radius_px": radius}
    accepted = bool(condition <= 30 and np.all(distances > 0) and gap <= 0.010 and
                    all(item["reprojection_error_px"] is not None and
                        item["reprojection_error_px"] <= min(4.0, item["annotation_uncertainty_radius_px"])
                        for item in checks.values()))
    return {"source": "public RGB calibration + Pro-annotated same visible landmark",
            "landmark": annotation.get("physical_landmark") or annotation.get("landmark"),
            "camera_step_id": calibration["step_id"],
            "views": names, "accepted": accepted,
            "estimated_position_environment_m": point.round(5).tolist() if accepted else None,
            "candidate_position_environment_m": point.round(5).tolist(),
            "ray_gap_m": gap, "ray_condition": condition,
            "positive_ray_distances_m": distances.tolist(), "checks": checks,
            "caution": "Camera-derived landmark hypothesis, not object pose, contact, grasp or native success."}


def main():
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--plan", type=Path)
    source.add_argument("--annotation", type=Path)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    calibration = json.loads(args.calibration.read_text())
    annotations = ([json.loads(args.annotation.read_text())] if args.annotation else
                   json.loads(args.plan.read_text())["visual_method"]["initial_correspondences"])
    result = [estimate(calibration, item) for item in annotations]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps([{"accepted": row["accepted"], "ray_gap_m": row["ray_gap_m"],
                       "checks": {name: item["reprojection_error_px"]
                                  for name, item in row["checks"].items()}}
                      for row in result]))


if __name__ == "__main__":
    main()

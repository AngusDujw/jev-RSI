"""Triangulate a Pro-annotated RGB landmark from public camera calibration."""

import argparse
import copy
import json
import os
import pwd
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation


@lru_cache(maxsize=2)
def gripper_mesh_vertices(mesh_dir: str):
    """Public X5 robot STL geometry in each link's own frame, never scene object state."""
    import trimesh

    root = Path(mesh_dir)
    return tuple(np.asarray(trimesh.load_mesh(root / f"{name}.STL", process=False).vertices,
                            dtype=float)
                 for name in ("link6", "link7", "link8"))


def gripper_height_above_landmark(eef, landmark, descent_m=0.005, mesh_dir=None):
    """Lower bound on hand-mesh height relative to a camera-derived landmark plane.

    The unknown table and other visible obstacles still require RGB inspection.
    """
    if mesh_dir is None:
        # The simulator deliberately rewrites HOME to an isolated runtime directory.
        user_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        mesh_dir = (user_home / "DataStorage/jev-router/sources/RoboDojo/Assets/Robots/x5/meshes")
    vertices = gripper_mesh_vertices(str(mesh_dir))
    transform = eef_transform(eef)
    origins = (np.zeros(3), np.array([0.08657, 0.024896, -0.0002436]),
               np.array([0.08657, -0.0249, -0.00024366]))
    axes = (0, 1, -1)
    bottom = float("inf")
    for verts, origin, axis in zip(vertices, origins, axes):
        for opening in (0.0, 0.044):
            offset = origin + np.array([0.0, axis * opening, 0.0])
            world = (verts + offset) @ transform[:3, :3].T + transform[:3, 3]
            bottom = min(bottom, float(np.min(world[:, 2])))
    clearance = bottom - float(descent_m) - float(landmark[2])
    return {
        "robot_source": "X5 public URDF link6/7/8 collision STL and measured LINK6 pose",
        "min_hand_mesh_z_after_m": bottom - float(descent_m),
        "camera_landmark_plane_z_m": float(landmark[2]),
        "hand_above_landmark_plane_after_m": clearance,
        "descent_m": float(descent_m),
        "limitation": "A camera-derived landmark plane is not a scene collision map or table pose. Check the complete swept path and other obstacles in fresh RGB.",
    }


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
    local = transform[:3, :3].T @ (np.asarray(point, float) - transform[:3, 3])
    depth = -local[2]
    if depth <= 0:
        return None
    return [float(k[0, 0] * local[0] / depth + k[0, 2]),
            float(k[1, 2] - k[1, 1] * local[1] / depth)]


def view_motion_candidates(camera, landmark, measured_eef, min_height_clearance=0.08):
    """Project short wrist-only translations from camera and measured robot state."""
    point = np.asarray(landmark, float)
    current = project(camera, point)
    if current is None:
        return []
    width, height = camera["size"]

    def margin(uv):
        return min(uv[0], width - 1 - uv[0], uv[1], height - 1 - uv[1])

    candidates = []
    initial_distance = float(np.linalg.norm(point - np.asarray(measured_eef["position"], float)))
    for axis in range(3):
        for sign in (-1, 1):
            amount = 0.005 if axis == 2 else 0.010
            delta = sign * amount
            if axis == 2 and float(measured_eef["position"][2]) + delta < point[2] + min_height_clearance:
                continue
            moved = copy.deepcopy(camera)
            moved["camera_to_environment"][axis][3] += delta
            uv = project(moved, point)
            if uv is None:
                continue
            gain = margin(uv) - margin(current)
            new_eef = np.asarray(measured_eef["position"], float).copy()
            new_eef[axis] += delta
            candidates.append({"axis": "xyz"[axis], "sign": "positive" if sign > 0 else "negative",
                               "distance_m": amount, "landmark_uv_before": current,
                               "landmark_uv_after_prediction": uv,
                               "image_margin_px_before": margin(current),
                               "image_margin_px_after_prediction": margin(uv),
                               "margin_gain_px": gain,
                               "landmark_distance_reduction_m": initial_distance - float(np.linalg.norm(point - new_eef))})
    return candidates


def view_margin_candidate(camera, landmark, measured_eef, min_height_clearance=0.08,
                          require_progress=False):
    """Find a short wrist-only translation that increases landmark image margin."""
    candidates = view_motion_candidates(camera, landmark, measured_eef, min_height_clearance)
    if require_progress:
        candidates = [item for item in candidates
                      if item["landmark_distance_reduction_m"] >= 0.001]
    best = max(candidates, key=lambda item: item["margin_gain_px"], default=None)
    return best if best and best["margin_gain_px"] >= 3.0 else None


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

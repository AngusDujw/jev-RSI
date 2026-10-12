"""Forecast one right-wrist sensing turn from public cameras and robot meshes.

The source point must come from current RGB correspondence. Mesh heights and
hand-hand gaps are partial geometry evidence, never a scene collision proof.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from camera_geometry import eef_transform, project
from source_view_probe import _hand_vertices


def forecast(observation: dict, calibration: dict, source_geometry: dict,
             bar_height_m: float, angle_rad: float = 0.12) -> dict:
    if calibration["step_id"] != observation["step_id"]:
        raise ValueError("Current RGB and propagated calibration must share step_id")
    measured = observation["current_eef"]["right"]
    source = np.asarray(source_geometry["estimated_position_environment_m"], float)
    left_tree = cKDTree(_hand_vertices(observation["current_eef"]["left"]))
    current_camera = calibration["cameras"]["cam_right_wrist"]
    current_link = eef_transform(measured)
    current_camera_matrix = np.asarray(current_camera["camera_to_environment"], float)
    q = np.asarray(measured["quaternion_wxyz"], float)
    start_rotation = Rotation.from_quat(q[[1, 2, 3, 0]])
    samples = []
    for theta in np.linspace(0.0, angle_rad, 7):
        turned = Rotation.from_rotvec([0.0, 0.0, float(theta)]) * start_rotation
        xyzw = turned.as_quat()
        pose = {"position": list(measured["position"]),
                "quaternion_wxyz": xyzw[[3, 0, 1, 2]].tolist()}
        hand = _hand_vertices(pose)
        samples.append({
            "world_z_rotation_from_current_rad": float(theta),
            "min_right_hand_world_z_m": float(hand[:, 2].min()),
            "min_right_to_left_hand_mesh_m": float(left_tree.query(hand, k=1)[0].min()),
        })
    target = pose
    moved_camera = copy.deepcopy(current_camera)
    moved_camera["camera_to_environment"] = (
        eef_transform(target) @ np.linalg.inv(current_link) @
        current_camera_matrix).tolist()
    before, after = project(current_camera, source), project(moved_camera, source)
    if before is None or after is None:
        raise ValueError("Public calibration cannot project confirmed source")
    return {
        "step_id": observation["step_id"],
        "source": "same-current-step camera-derived free-end plus public K/T, measured LINK6 and X5 hand meshes",
        "target_right_link6": target,
        "source_uv_right_current_prediction": before,
        "source_uv_right_after_prediction": after,
        "source_is_actually_visible_in_right_rgb": False,
        "mesh_samples": samples,
        "min_hand_height_above_camera_derived_bar_plane_m":
            min(row["min_right_hand_world_z_m"] for row in samples) - bar_height_m,
        "min_hand_height_above_camera_derived_source_plane_m":
            min(row["min_right_hand_world_z_m"] for row in samples) - float(source[2]),
        "min_hand_to_other_hand_mesh_m":
            min(row["min_right_to_left_hand_mesh_m"] for row in samples),
        "limitations": "Source UVs are projections of a high/left RGB hypothesis, not a right-RGB observation. Public hand meshes sample link6/7/8 openings, not full arm or scene objects. A landmark height plane is not a scene surface or clearance certificate.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--bar-height-m", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = forecast(json.loads(args.observation.read_text()),
                      json.loads(args.calibration.read_text()),
                      json.loads(args.geometry.read_text()), args.bar_height_m)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output),
                      "source_uv_after_prediction": result["source_uv_right_after_prediction"]}))


if __name__ == "__main__":
    main()

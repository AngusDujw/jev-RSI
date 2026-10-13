"""Preview a short X5 EEF target using measured joints and public robot URDF.

This predicts robot kinematics and public link-mesh separation only. It never
reads simulator object poses, contact flags, reward or future physics state.
Native execution and scene clearance remain separate checks.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

import numpy as np
import trimesh
from scipy.spatial.transform import Rotation

from camera_geometry import eef_transform
from hybrid_rollout.robodojo.robodojo_server.kinematics import ArmFK


def _urdf() -> Path:
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    return home / "DataStorage/jev-router/sources/RoboDojo/Assets/Robots/x5/X5A.urdf"


@lru_cache(maxsize=1)
def _model():
    path = _urdf()
    names = [f"joint{i}" for i in range(1, 7)]
    fk = ArmFK(path, names)
    joints = {entry.get("name"): entry
              for entry in ET.parse(path).getroot().findall("joint")}
    limits = np.asarray([[float(joints[name].find("limit").get(field))
                          for field in ("lower", "upper")] for name in names])
    meshes = {i: np.asarray(trimesh.load_mesh(
        path.parent / f"meshes/link{i}.STL", process=False).vertices, float)
        for i in range(2, 6)}
    return fk, limits, meshes


def _root(fk: ArmFK, pose: dict, joints: np.ndarray) -> np.ndarray:
    return eef_transform(pose) @ np.linalg.inv(fk.matrix(joints))


def _arm_mesh(fk: ArmFK, root: np.ndarray, joints: np.ndarray,
              meshes: dict[int, np.ndarray], distal_only: bool = False) -> np.ndarray:
    values = dict(zip(fk.names, joints))
    transform = root.copy()
    points = []
    for name, kind, origin, axis in fk.chain:
        motion = np.eye(4)
        if kind in ("revolute", "continuous"):
            motion[:3, :3] = Rotation.from_rotvec(axis * values[name]).as_matrix()
        transform = transform @ origin @ motion
        if name.startswith("joint") and name[5:].isdigit():
            index = int(name[5:])
            if index in meshes and (not distal_only or index >= 4):
                vertices = meshes[index]
                points.append(vertices @ transform[:3, :3].T + transform[:3, 3])
    return np.concatenate(points)


def preview(observation: dict, target: dict, native_first_joint_action: list[float] | None,
            steps: int = 5) -> dict:
    if steps not in (5, 10, 15, 20):
        raise ValueError("Preview supports 5, 10, 15, or 20 bounded native steps")
    fk, limits, meshes = _model()
    q_right = np.asarray(observation["current_state"][7:13], float)
    q_left = np.asarray(observation["current_state"][0:6], float)
    if q_right.shape != (6,) or q_left.shape != (6,):
        raise ValueError("Expected public dual X5 six-joint states")
    right_root = _root(fk, observation["current_eef"]["right"], q_right)
    left_root = _root(fk, observation["current_eef"]["left"], q_left)
    left_vertices = _arm_mesh(fk, left_root, q_left, meshes)
    left_min, left_max = left_vertices.min(axis=0), left_vertices.max(axis=0)
    desired = eef_transform(target)
    measured_right = eef_transform(observation["current_eef"]["right"])
    requested_translation_m = float(np.linalg.norm(
        desired[:3, 3] - measured_right[:3, 3]))
    requested_rotation_rad = float(Rotation.from_matrix(
        desired[:3, :3] @ measured_right[:3, :3].T).magnitude())
    native_eef_single_action_legal = bool(
        steps <= 5 and requested_translation_m <= 0.05 + 1e-9 and
        requested_rotation_rad <= 0.35 + 1e-9)
    rows = []
    first_native = (None if native_first_joint_action is None else
                    np.asarray(native_first_joint_action, float))
    if first_native is not None and (first_native.shape != (6,) or
                                     not np.isfinite(first_native).all()):
        raise ValueError("Native read-only IK must provide six right-arm joints")
    first_agreement = None
    for index in range(steps):
        next_q, diagnostic = fk.bounded_target(
            q_right, limits, right_root, target)
        if index == 0 and first_native is not None:
            first_agreement = float(np.max(np.abs(next_q - first_native)))
        eef = right_root @ fk.matrix(next_q)
        eef_xyzw = Rotation.from_matrix(eef[:3, :3]).as_quat()
        translation_error = float(np.linalg.norm(
            desired[:3, 3] - eef[:3, 3]))
        rotation_error = float(Rotation.from_matrix(
            desired[:3, :3] @ eef[:3, :3].T).magnitude())
        right_vertices = _arm_mesh(fk, right_root, next_q, meshes)
        right_distal = _arm_mesh(fk, right_root, next_q, meshes, distal_only=True)
        right_min, right_max = right_vertices.min(axis=0), right_vertices.max(axis=0)
        # Distance between enclosing AABBs is a lower bound on mesh distance.
        aabb_gap = np.maximum(0, np.maximum(left_min - right_max,
                                             right_min - left_max))
        interarm_lower_bound = float(np.linalg.norm(aabb_gap))
        joint_margin = float(np.min(np.minimum(
            next_q - limits[:, 0], limits[:, 1] - next_q)))
        rows.append({"step": index + 1,
                     "predicted_link6_position_m": eef[:3, 3].tolist(),
                     "predicted_link6_quaternion_wxyz": eef_xyzw[[3, 0, 1, 2]].tolist(),
                     "max_joint_delta_rad": float(np.max(np.abs(next_q - q_right))),
                     "predicted_link6_translation_residual_m": translation_error,
                     "predicted_link6_rotation_residual_rad": rotation_error,
                     "min_public_urdf_hard_joint_margin_rad": joint_margin,
                     "min_link2_to_5_world_z_m": float(right_vertices[:, 2].min()),
                     "min_distal_link4_to_5_world_z_m": float(right_distal[:, 2].min()),
                     "other_arm_link2_to_5_aabb_separation_lower_bound_m": interarm_lower_bound,
                     "robot_only_ik_method": diagnostic["method"]})
        q_right = next_q
    public_path_gate = bool(
        max(item["max_joint_delta_rad"] for item in rows) <= 0.051 and
        min(item["min_public_urdf_hard_joint_margin_rad"] for item in rows) > 0.2 and
        rows[-1]["predicted_link6_translation_residual_m"] <= 0.002 and
        rows[-1]["predicted_link6_rotation_residual_rad"] <= 0.01 and
        min(item["other_arm_link2_to_5_aabb_separation_lower_bound_m"]
            for item in rows) >= 0.10)
    output = {
        "source": "public X5 URDF, current measured dual arm joints/LINK6, same bounded DLS update as native robot-only IK",
        "predicted_native_steps": steps,
        "requested_link6_translation_m": requested_translation_m,
        "requested_link6_rotation_rad": requested_rotation_rad,
        "native_eef_single_action_legal": native_eef_single_action_legal,
        "native_eef_contract": "One Decision permits 1..5 steps, LINK6 delta position <=0.05 m and orientation <=0.35 rad; longer public paths are offline diagnostics only.",
        "native_first_step_max_joint_disagreement_rad": first_agreement,
        "predicted_joint_path": rows,
        "public_path_gate": public_path_gate,
        "model_path_gate": bool(first_agreement is not None and
                                first_agreement < 0.002 and public_path_gate and
                                native_eef_single_action_legal),
        "limitations": "Root inferred from current measured LINK6/joints. Native first bounded IK cross-check is required for model_path_gate; a null disagreement means it has not been requested. Later steps are model predictions. Link2-5 AABB separation is a conservative lower bound for those arm meshes; it omits bases, fingers and scene objects. Not a full collision certificate or physical tracking proof."
    }
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline public-robot-only bounded path preview")
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, choices=(5, 10, 15, 20), default=5)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = preview(json.loads(args.observation.read_text()),
                     json.loads(args.target.read_text()), None, args.steps)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output),
                      "public_path_gate": result["public_path_gate"],
                      "native_crosscheck_pending": True}))


if __name__ == "__main__":
    main()

"""Project candidate X5 inner finger surfaces using public URDF/STL and measured LINK6.

The projected facets identify robot geometry only. RGB must confirm their
visibility, and object contact clearance remains unknown.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw
from scipy.spatial import ConvexHull

from camera_geometry import eef_transform


def _project(camera: dict, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    transform = np.asarray(camera["camera_to_environment"], float)
    k = np.asarray(camera["intrinsic"], float)
    local = (points - transform[:3, 3]) @ transform[:3, :3]
    depth = -local[:, 2]
    uv = np.column_stack((k[0, 2] + k[0, 0] * local[:, 0] / depth,
                          k[1, 2] - k[1, 1] * local[:, 1] / depth))
    return uv, depth


def inspect(observation: dict, calibration: dict) -> dict:
    if observation["step_id"] != calibration["step_id"]:
        raise ValueError("RGB/robot observation and camera calibration must be simultaneous")
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    root = home / "DataStorage/jev-router/sources/RoboDojo/Assets/Robots/x5"
    joints = {entry.get("name"): entry
              for entry in ET.parse(root / "X5A.urdf").getroot().findall("joint")}
    eef = observation["current_eef"]["right"]
    link = eef_transform(eef)
    command = float(eef["gripper_opening_command"])
    encoders=observation.get('measured_gripper_joint_state')
    measured={}
    if encoders is not None:
        if encoders['step_id'] != observation['step_id'] or encoders.get('physical_steps')!=0:
            raise ValueError('Gripper encoders must be current zero-step robot reads')
        values=encoders['arms']['right']
        measured=dict(zip(values['joint_names'],values['joint_positions_m']))
        if not {'joint7','joint8'} <= measured.keys():
            raise ValueError('Actual X5 finger joint encoders incomplete')
    camera = calibration["cameras"]["cam_right_wrist"]
    rows = {}
    for name, joint_name, sign in (("link7", "joint7", -1), ("link8", "joint8", 1)):
        joint = joints[joint_name]
        origin = np.fromstring(joint.find("origin").get("xyz"), sep=" ")
        axis = np.fromstring(joint.find("axis").get("xyz"), sep=" ")
        upper = float(joint.find("limit").get("upper"))
        translation=float(measured[joint_name]) if measured else float(np.clip(command,0,1)*upper)
        if not np.isfinite(translation) or not -.001 <= translation <= upper+.001:
            raise ValueError('Public finger encoder outside declared prismatic range')
        offset = origin + axis * translation
        mesh = trimesh.load_mesh(root / f"meshes/{name}.STL", process=False)
        vertices = np.asarray(mesh.vertices, float)
        centers = np.asarray(mesh.triangles_center, float)
        normals = np.asarray(mesh.face_normals, float)
        inner_y = float(vertices[:, 1].min() if sign == -1 else vertices[:, 1].max())
        faces = ((centers[:, 0] > 0.04) &
                 (np.abs(centers[:, 1] - inner_y) < 0.001) &
                 (normals[:, 1] * sign > 0.99))
        if not np.any(faces):
            raise ValueError(f"Public {name} inner-facet candidate empty")
        local_points = np.asarray(mesh.triangles[faces]).reshape(-1, 3) + offset
        world_points = local_points @ link[:3, :3].T + link[:3, 3]
        uv, depth = _project(camera, world_points)
        if np.any(depth <= 0):
            raise ValueError(f"Public {name} candidate lies behind camera")
        rows[name] = {
            "public_source": f"X5A.urdf {joint_name} + meshes/{name}.STL",
            "gripper_command": command,
            "joint_translation_m": translation,
            "joint_translation_source": 'Current robot joint_pos encoder' if measured else 'Command-derived URDF prediction; not a measured finger position',
            "inner_facet_selection": "mesh triangles with inward y-normal >0.99, within 1mm of inner y-extremum, distal local x>40mm",
            "facet_count": int(np.sum(faces)),
            "inner_facet_world_xyz_m": np.round(world_points, 6).tolist(),
            "inner_facet_right_wrist_uv": np.round(uv, 2).tolist(),
            "projected_bbox_xyxy": [float(uv[:, 0].min()), float(uv[:, 1].min()),
                                     float(uv[:, 0].max()), float(uv[:, 1].max())],
            "positive_depth_range_m": [float(depth.min()), float(depth.max())],
        }
    return {
        "task": observation["task"], "step_id": observation["step_id"],
        "camera": "cam_right_wrist", "rows": rows,
        "limitations": "These are public robot-mesh inward-facing distal facet candidates, not RGB-verified visible pads, physical contact, object pose or scene clearance. The simulator may render other hand geometry and occlude these facets; inspect fresh RGB before using them as decision evidence.",
    }


def inspect_high_sweep(observation: dict, calibration: dict, path: dict) -> dict:
    """Project complete public link6/7/8 mesh at current and predicted robot steps."""
    if observation["step_id"] != calibration["step_id"]:
        raise ValueError("Current RGB and robot calibration must be simultaneous")
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    root = home / "DataStorage/jev-router/sources/RoboDojo/Assets/Robots/x5"
    urdf = ET.parse(root / "X5A.urdf").getroot()
    joints = {entry.get("name"): entry for entry in urdf.findall("joint")}
    right = observation["current_eef"]["right"]
    command = float(right["gripper_opening_command"])
    camera = calibration["cameras"]["cam_high"]
    image_path = next(Path(item["path"]) for item in observation["images"]
                      if item["camera"] == "cam_high")
    rgb = np.asarray(Image.open(image_path).convert("RGB"))
    white = np.all(rgb[:, :, :] >= 185, axis=2)
    roi = np.zeros(white.shape, dtype=bool)
    roi[255:285, 500:531] = True
    white &= roi
    meshes = {name: np.asarray(trimesh.load_mesh(
        root / f"meshes/{name}.STL", process=False).vertices, float)
        for name in ("link6", "link7", "link8")}
    local = [meshes["link6"]]
    for name, joint_name in (("link7", "joint7"), ("link8", "joint8")):
        joint = joints[joint_name]
        origin = np.fromstring(joint.find("origin").get("xyz"), sep=" ")
        axis = np.fromstring(joint.find("axis").get("xyz"), sep=" ")
        upper = float(joint.find("limit").get("upper"))
        local.append(meshes[name] + origin + axis * np.clip(command, 0, 1) * upper)
    poses = [(0, right)] + [(row["step"], {
        "position": row["predicted_link6_position_m"],
        "quaternion_wxyz": row["predicted_link6_quaternion_wxyz"]})
        for row in path["predicted_joint_path"]]
    rows = []
    for step, pose in poses:
        transform = eef_transform(pose)
        projected = []
        boxes = {}
        for name, vertices in zip(("link6", "link7", "link8"), local):
            world = vertices @ transform[:3, :3].T + transform[:3, 3]
            uv, depth = _project(camera, world)
            points = uv[depth > 0]
            if len(points) < 3:
                raise ValueError(f"No positive-depth high-camera {name} mesh")
            projected.append(points)
            boxes[name] = [float(points[:, 0].min()), float(points[:, 1].min()),
                           float(points[:, 0].max()), float(points[:, 1].max())]
        points = np.concatenate(projected)
        hull = points[ConvexHull(points).vertices]
        mask = Image.new("1", (rgb.shape[1], rgb.shape[0]), 0)
        ImageDraw.Draw(mask).polygon([tuple(point) for point in hull], fill=1)
        overlap = int(np.count_nonzero(np.asarray(mask, dtype=bool) & white))
        rows.append({"step": step, "public_link_mesh_high_bbox_xyxy": boxes,
                     "public_hand_high_hull_xy": np.round(hull, 2).tolist(),
                     "white_bright_roi_overlap_px": overlap})
    return {
        "source": "public X5 link6/7/8 visual STL and URDF finger joints, measured LINK6 and robot-only predicted five-step path, current high RGB/K/T",
        "white_bright_roi_xyxy": [500, 255, 530, 284],
        "white_bright_roi_pixel_count": int(np.count_nonzero(white)),
        "samples": rows,
        "limitations": "White threshold and ROI include only a partly visible RGB proxy; full scene depth, hidden white-block extent and contact clearance are unknown. The hand hull is a 2D convex envelope of public robot mesh, not a physical collision volume. Predicted intermediate states are public robot-only IK, not future observations."
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overlay", type=Path)
    parser.add_argument("--sweep-target", type=Path)
    parser.add_argument("--sweep-output", type=Path)
    args = parser.parse_args()
    if (args.sweep_target is None) != (args.sweep_output is None):
        parser.error("--sweep-target and --sweep-output must be supplied together")
    if args.output.exists():
        raise FileExistsError(args.output)
    observation = json.loads(args.observation.read_text())
    calibration = json.loads(args.calibration.read_text())
    result = inspect(observation, calibration)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    if args.overlay is not None:
        if args.overlay.exists():
            raise FileExistsError(args.overlay)
        source = next(Path(item["path"]) for item in observation["images"]
                      if item["camera"] == "cam_right_wrist")
        picture = Image.open(source).convert("RGB")
        drawer = ImageDraw.Draw(picture)
        for name, color in (("link7", "#00ffff"), ("link8", "#ff00ff")):
            vertices = result["rows"][name]["inner_facet_right_wrist_uv"]
            for index in range(0, len(vertices), 3):
                triangle = [tuple(v) for v in vertices[index:index + 3]]
                drawer.line(triangle + [triangle[0]], fill=color, width=3)
        args.overlay.parent.mkdir(parents=True, exist_ok=True)
        picture.save(args.overlay)
    if args.sweep_target is not None:
        from robot_path_preview import preview

        if args.sweep_output.exists():
            raise FileExistsError(args.sweep_output)
        target = json.loads(args.sweep_target.read_text())
        path = preview(observation, target, None, steps=5)
        sweep = inspect_high_sweep(observation, calibration, path)
        args.sweep_output.parent.mkdir(parents=True, exist_ok=True)
        args.sweep_output.write_text(json.dumps(sweep, ensure_ascii=False, indent=2))
    print(json.dumps({"output": str(args.output), "step_id": result["step_id"],
                      "facets": {k: v["facet_count"] for k, v in result["rows"].items()}}))


if __name__ == "__main__":
    main()

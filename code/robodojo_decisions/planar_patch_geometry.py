"""Fit a top-face height hypothesis from two current calibrated RGB material masks.

This computes a camera-derived plane with an uncertainty interval. It does not
read simulator object state, contact, reward or a privileged depth image.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, distance_transform_edt

from camera_geometry import eef_transform


def _rgb_mask(path: Path, roi: tuple[int, int, int, int],
              minimum: tuple[int, int, int]) -> np.ndarray:
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)
    keep = np.all(rgb >= np.asarray(minimum, dtype=np.int16), axis=2)
    x0, y0, x1, y1 = roi
    roi_mask = np.zeros(keep.shape, dtype=bool)
    roi_mask[y0:y1 + 1, x0:x1 + 1] = True
    return keep & roi_mask


def fit(obs: dict, calibration: dict, high_roi: tuple[int, ...],
        wrist_roi: tuple[int, ...], rgb_min: tuple[int, ...],
        z_min: float, z_max: float, z_step: float) -> dict:
    if int(obs["step_id"]) != int(calibration["step_id"]):
        raise ValueError("RGB and public calibration must have the same step id")
    if not 0 < z_min < z_max or not 0 < z_step <= 0.01:
        raise ValueError("Invalid explicit plane search interval")
    files = {item["camera"]: Path(item["path"]) for item in obs["images"]}
    high = _rgb_mask(files["cam_high"], high_roi, rgb_min)
    wrist = _rgb_mask(files["cam_right_wrist"], wrist_roi, rgb_min)
    if int(high.sum()) < 20 or int(wrist.sum()) < 50:
        raise ValueError("Material masks too small for planar fitting")
    cameras = calibration["cameras"]
    kh = np.asarray(cameras["cam_high"]["intrinsic"], float)
    kw = np.asarray(cameras["cam_right_wrist"]["intrinsic"], float)
    th = np.asarray(cameras["cam_high"]["camera_to_environment"], float)
    tw = np.asarray(cameras["cam_right_wrist"]["camera_to_environment"], float)
    ys, xs = np.nonzero(high)
    rays = th[:3, :3] @ np.stack(
        ((xs - kh[0, 2]) / kh[0, 0],
         -(ys - kh[1, 2]) / kh[1, 1],
         -np.ones(len(xs))), axis=0)
    eye = th[:3, 3, None]
    scores = []
    for z in np.arange(z_min, z_max + z_step * 0.25, z_step):
        points = eye + rays * ((z - eye[2]) / rays[2])
        local = tw[:3, :3].T @ (points - tw[:3, 3, None])
        depth = -local[2]
        u = kw[0, 2] + kw[0, 0] * local[0] / depth
        v = kw[1, 2] - kw[1, 1] * local[1] / depth
        valid = ((depth > 0) & (u >= 0) & (u < wrist.shape[1])
                 & (v >= 0) & (v < wrist.shape[0]))
        rendered = np.zeros(wrist.shape, dtype=bool)
        rendered[np.rint(v[valid]).astype(int),
                 np.rint(u[valid]).astype(int)] = True
        expanded = binary_dilation(rendered, iterations=3)
        intersection = int((expanded & wrist).sum())
        union = int((expanded | wrist).sum())
        scores.append({
            "plane_z_m": round(float(z), 6),
            "dilated_projected_mask_iou": round(intersection / union if union else 0, 6),
            "right_material_covered_fraction": round(intersection / int(wrist.sum()), 6),
        })
    best = max(scores, key=lambda row: row["dilated_projected_mask_iou"])
    near = [row["plane_z_m"] for row in scores
            if row["dilated_projected_mask_iou"] >=
            best["dilated_projected_mask_iou"] - 0.05]
    interior = distance_transform_edt(high)
    py, px = np.unravel_index(np.argmax(interior), interior.shape)
    direction = th[:3, :3] @ np.array(
        [(px - kh[0, 2]) / kh[0, 0],
         -(py - kh[1, 2]) / kh[1, 1], -1.0])
    origin = th[:3, 3]
    point = origin + direction * (
        (best["plane_z_m"] - origin[2]) / direction[2])
    wrist_local = tw[:3, :3].T @ (point - tw[:3, 3])
    depth = -wrist_local[2]
    uv = [kw[0, 2] + kw[0, 0] * wrist_local[0] / depth,
          kw[1, 2] - kw[1, 1] * wrist_local[1] / depth]
    tool_local = np.linalg.inv(
        eef_transform(obs["current_eef"]["right"])) @ np.append(point, 1)
    return {
        "source": "same-step high/right RGB thresholded material masks, public K/T and measured LINK6",
        "task": obs["task"],
        "step_id": int(obs["step_id"]),
        "mask_threshold_rgb_min": list(rgb_min),
        "high_roi_xyxy": list(high_roi),
        "right_roi_xyxy": list(wrist_roi),
        "high_material_pixels": int(high.sum()),
        "right_material_pixels": int(wrist.sum()),
        "dilation_iterations_px": 3,
        "score_grid": scores,
        "best_plane_z_m": best["plane_z_m"],
        "best_mask_iou": best["dilated_projected_mask_iou"],
        "near_best_z_m_at_iou_within_0p05": [min(near), max(near)],
        "top_interior_material_candidate": {
            "high_pixel_uv": [int(px), int(py)],
            "high_distance_to_mask_edge_px": round(float(interior[py, px]), 3),
            "right_projected_pixel_uv": [round(float(x), 3) for x in uv],
            "camera_derived_world_hypothesis_m": [round(float(x), 6) for x in point],
            "current_right_LINK6_local_hypothesis_m": [round(float(x), 6)
                                                       for x in tool_local[:3]],
        },
        "limits": "Flat material plane is a camera-derived hypothesis with image/height uncertainty. A matching top face is not object pose, bottom/side height, collision clearance, contact, grasp, native reward or success. Require semantic object/face review and actual finger-pad relation."
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--high-roi", type=int, nargs=4, required=True)
    parser.add_argument("--right-roi", type=int, nargs=4, required=True)
    parser.add_argument("--rgb-min", type=int, nargs=3, required=True)
    parser.add_argument("--z-min", type=float, required=True)
    parser.add_argument("--z-max", type=float, required=True)
    parser.add_argument("--z-step", type=float, default=0.001)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = fit(json.loads(args.observation.read_text()),
                 json.loads(args.calibration.read_text()),
                 tuple(args.high_roi), tuple(args.right_roi), tuple(args.rgb_min),
                 args.z_min, args.z_max, args.z_step)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "best_plane_z_m": result["best_plane_z_m"],
        "best_mask_iou": result["best_mask_iou"],
        "candidate": result["top_interior_material_candidate"]},
        ensure_ascii=False))


if __name__ == "__main__":
    main()

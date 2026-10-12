"""Fit a visible flat digit's image plane from two current RGB silhouettes.

Uses only three current RGB images, public K/T and a Pro-annotated same-point
camera estimate. The fitted plane is a hypothesis with a score interval, not
simulator object pose or proof of safe robot contact.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, distance_transform_edt

from camera_geometry import eef_transform


def _mask(path: Path, roi: tuple[int, int, int, int]) -> np.ndarray:
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)
    blue = ((rgb[:, :, 2] > 75) & (rgb[:, :, 2] > rgb[:, :, 0] + 28)
            & (rgb[:, :, 2] > rgb[:, :, 1] + 16))
    x0, y0, x1, y1 = roi
    keep = np.zeros(blue.shape, dtype=bool)
    keep[y0:y1 + 1, x0:x1 + 1] = True
    return blue & keep


def fit(obs: dict, calibration: dict, anchor: dict, high_roi: tuple[int, ...],
        wrist_roi: tuple[int, ...], band: tuple[int, int]) -> dict:
    if int(obs["step_id"]) != int(calibration["step_id"]) or int(obs["step_id"]) != int(anchor["camera_step_id"]):
        raise ValueError("RGB, calibration and anchor must have the same step id")
    if not anchor["accepted"]:
        raise ValueError("Only an accepted current RGB stereo anchor may center the scan")
    files = {item["camera"]: Path(item["path"]) for item in obs["images"]}
    high = _mask(files["cam_high"], high_roi)
    right = _mask(files["cam_right_wrist"], wrist_roi)
    if high.sum() < 20 or right.sum() < 200:
        raise ValueError("Current blue component is too small")
    high_camera = calibration["cameras"]["cam_high"]
    wrist_camera = calibration["cameras"]["cam_right_wrist"]
    kh = np.asarray(high_camera["intrinsic"], float)
    kw = np.asarray(wrist_camera["intrinsic"], float)
    th = np.asarray(high_camera["camera_to_environment"], float)
    tw = np.asarray(wrist_camera["camera_to_environment"], float)
    yy, xx = np.nonzero(high)
    rays = th[:3, :3] @ np.stack(
        ((xx - kh[0, 2]) / kh[0, 0], -(yy - kh[1, 2]) / kh[1, 1],
         -np.ones(len(xx))), axis=0)
    eye = th[:3, 3, None]
    anchor_z = float(anchor["estimated_position_environment_m"][2])
    scores = []
    for z in np.arange(anchor_z - 0.014, anchor_z + 0.0141, 0.001):
        xyz = eye + rays * ((z - eye[2]) / rays[2])
        local = tw[:3, :3].T @ (xyz - tw[:3, 3, None])
        depth = -local[2]
        u = kw[0, 2] + kw[0, 0] * local[0] / depth
        v = kw[1, 2] - kw[1, 1] * local[1] / depth
        valid = ((depth > 0) & (u >= 0) & (u < right.shape[1])
                 & (v >= 0) & (v < right.shape[0]))
        projected = np.zeros(right.shape, dtype=bool)
        projected[np.rint(v[valid]).astype(int), np.rint(u[valid]).astype(int)] = True
        expanded = binary_dilation(projected, iterations=3)
        intersection = int((expanded & right).sum())
        union = int((expanded | right).sum())
        score = intersection / union if union else 0.0
        wrist_dist = distance_transform_edt(~right)
        sampled = wrist_dist[np.rint(v[valid]).astype(int),
                             np.rint(u[valid]).astype(int)]
        scores.append({"plane_z_m": round(float(z), 6),
                       "dilated_projected_mask_iou": round(score, 6),
                       "right_blue_covered_fraction": round(
                           intersection / int(right.sum()), 6),
                       "high_material_projected_within_2px_fraction": round(
                           float(np.mean(sampled <= 2)), 6),
                       "mean_projected_high_to_right_blue_distance_px": round(
                           float(np.mean(sampled)), 6)})
    best_index = int(np.argmax([row["dilated_projected_mask_iou"] for row in scores]))
    best = scores[best_index]
    plausible = [row["plane_z_m"] for row in scores
                 if row["dilated_projected_mask_iou"] >=
                 best["dilated_projected_mask_iou"] - 0.05]
    inside = high & (np.indices(high.shape)[0] >= band[0]) & (
        np.indices(high.shape)[0] <= band[1])
    edge = distance_transform_edt(high)
    if not inside.any():
        raise ValueError("Requested solid-stroke band absent")
    by, bx = np.unravel_index(np.argmax(np.where(inside, edge, -1)), edge.shape)
    eye_point = th[:3, 3]
    direction = th[:3, :3] @ np.array(
        [(bx - kh[0, 2]) / kh[0, 0], -(by - kh[1, 2]) / kh[1, 1], -1.0])
    chosen = eye_point + direction * ((best["plane_z_m"] - eye_point[2]) / direction[2])
    local = tw[:3, :3].T @ (chosen - tw[:3, 3])
    wrist_uv = [float(kw[0, 2] + kw[0, 0] * local[0] / -local[2]),
                float(kw[1, 2] - kw[1, 1] * local[1] / -local[2])]
    tool_local = np.linalg.inv(eef_transform(obs["current_eef"]["right"])) @ np.append(chosen, 1)
    return {
        "source": "current cam_high/cam_right_wrist RGB blue masks, public K/T, current measured LINK6, accepted same-material camera anchor",
        "step_id": int(obs["step_id"]),
        "task": obs["task"],
        "high_roi_xyxy": list(high_roi),
        "right_wrist_roi_xyxy": list(wrist_roi),
        "high_blue_pixels": int(high.sum()),
        "right_blue_pixels": int(right.sum()),
        "dilation_radius_px": 3,
        "score_grid": scores,
        "best_plane_z_m": best["plane_z_m"],
        "best_mask_iou": best["dilated_projected_mask_iou"],
        "plausible_z_m_at_iou_within_0p05": [min(plausible), max(plausible)],
        "current_anchor_z_m": anchor_z,
        "solid_lower_stroke_candidate": {
            "high_pixel_uv": [int(bx), int(by)],
            "high_interior_distance_to_blue_mask_edge_px": round(float(edge[by, bx]), 3),
            "right_projected_pixel_uv": [round(x, 3) for x in wrist_uv],
            "camera_derived_world_hypothesis_m": [round(float(x), 6) for x in chosen],
            "current_right_LINK6_local_hypothesis_m": [round(float(x), 6) for x in tool_local[:3]],
            "status": "planar silhouette hypothesis, not independently annotated same 3D surface point or contact proof"
        },
        "limits": "Flat constant-z surface is a camera-derived hypothesis. Mask IoU can tolerate shape and occlusion errors. Neither simulator object pose nor table/contact state was read. Require fresh Pro/Luna review, measured tool-pad geometry and conservative clearance before physical contact."
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--anchor-geometry", type=Path, required=True)
    parser.add_argument("--high-roi", type=int, nargs=4, required=True)
    parser.add_argument("--right-roi", type=int, nargs=4, required=True)
    parser.add_argument("--solid-band-y", type=int, nargs=2, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    value = fit(json.loads(args.observation.read_text()),
                json.loads(args.calibration.read_text()),
                json.loads(args.anchor_geometry.read_text()),
                tuple(args.high_roi), tuple(args.right_roi),
                tuple(args.solid_band_y))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"best_plane_z_m": value["best_plane_z_m"],
                      "best_mask_iou": value["best_mask_iou"],
                      "solid_candidate": value["solid_lower_stroke_candidate"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()

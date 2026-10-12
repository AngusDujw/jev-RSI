"""Conservative RGB silhouette depth interval for a named static object.

Uses only two current RGB masks and public camera calibration. The returned
interval is a view-planning cue, not a grasp point or collision certificate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def white_mask(path: Path, roi: list[int], dilation_px: int = 4) -> np.ndarray:
    raw = cv2.imread(str(path))
    if raw is None:
        raise ValueError(f"Cannot read RGB: {path}")
    image = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)
    x0, y0, x1, y1 = roi
    if not (0 <= x0 < x1 <= image.shape[1] and 0 <= y0 < y1 <= image.shape[0]):
        raise ValueError("Invalid object ROI")
    lo = np.min(image, axis=2)
    spread = np.max(image, axis=2).astype(int) - lo.astype(int)
    mask = (lo >= 177) & (spread <= 72)
    outside = np.ones(mask.shape, dtype=bool)
    outside[y0:y1, x0:x1] = False
    mask[outside] = False
    if dilation_px:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                           (2 * dilation_px + 1, 2 * dilation_px + 1))
        mask = cv2.dilate(mask.astype(np.uint8), kernel).astype(bool)
    return mask


def depth_interval(high: dict, wrist: dict, high_mask: np.ndarray,
                   wrist_mask: np.ndarray, depth_values: np.ndarray) -> dict:
    y, x = np.nonzero(wrist_mask)
    if len(x) == 0 or not np.any(high_mask):
        raise ValueError("Source object mask empty")
    k = np.asarray(wrist["intrinsic"], float)
    pose = np.asarray(wrist["camera_to_environment"], float)
    dirs_local = np.stack(((x - k[0, 2]) / k[0, 0],
                           -(y - k[1, 2]) / k[1, 1],
                           -np.ones_like(x)), axis=1)
    dirs_world = dirs_local @ pose[:3, :3].T
    high_pose = np.asarray(high["camera_to_environment"], float)
    high_k = np.asarray(high["intrinsic"], float)
    local_origin = (pose[:3, 3] - high_pose[:3, 3]) @ high_pose[:3, :3]
    local_dirs = dirs_world @ high_pose[:3, :3]
    matched = []
    for depth in depth_values:
        points = local_origin + float(depth) * local_dirs
        forward = -points[:, 2]
        valid = forward > 0
        u = high_k[0, 0] * points[:, 0] / np.maximum(forward, 1e-9) + high_k[0, 2]
        v = high_k[1, 2] - high_k[1, 1] * points[:, 1] / np.maximum(forward, 1e-9)
        col = np.rint(u).astype(int)
        row = np.rint(v).astype(int)
        inside = valid & (col >= 0) & (col < high_mask.shape[1]) & (
            row >= 0) & (row < high_mask.shape[0])
        ids = np.flatnonzero(inside)
        if ids.size and np.any(high_mask[row[ids], col[ids]]):
            matched.append(float(depth))
    return {
        "depth_interval_camera_optical_m": [min(matched), max(matched)] if matched else None,
        "high_mask_pixels": int(np.count_nonzero(high_mask)),
        "wrist_mask_pixels": int(len(x)),
        "depth_grid_count": int(len(depth_values)),
        "source": "current RGB white masks + public K/T + world-ray projection",
        "limitations": "ROI, color threshold, dilation and depth grid are conservative but not a complete visual hull. The interval is for image-border prediction only; it is not a contact point, scene clearance, or proof of matching surface pixels.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    obs = json.loads(args.observation.read_text())
    if args.output.exists():
        raise FileExistsError(args.output)
    paths = {item["camera"]: Path(item["path"]) for item in obs["images"]}
    cameras = json.loads(args.calibration.read_text())["cameras"]
    high = white_mask(paths["cam_high"], [399, 172, 479, 246])
    wrist = white_mask(paths["cam_right_wrist"], [142, 210, 350, 376])
    result = depth_interval(cameras["cam_high"], cameras["cam_right_wrist"],
                            high, wrist, np.linspace(0.03, 0.90, 871))
    result["task"] = obs["task"]
    result["step_id"] = obs["step_id"]
    result["object_identity"] = "right source bowl, matching high and right wrist whole silhouettes"
    result["mask_method"] = {"rgb_min": 177, "rgb_max_minus_min": 72,
                             "dilation_px": 4,
                             "high_roi_xyxy": [399, 172, 479, 246],
                             "right_wrist_roi_xyxy": [142, 210, 350, 376]}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

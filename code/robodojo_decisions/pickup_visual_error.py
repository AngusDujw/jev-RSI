"""RGB handle-region error to public X5 pad projections, with depth uncertainty.

This deliberately uses no same-point stereo, simulator object pose, contact,
reward, or evaluator state. The source mask centre is a 2D region summary,
not a grasp point or a physical correspondence between cameras.
"""

from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
from PIL import Image

from camera_geometry import project, ray
from gripper_pad_projection import inspect as inspect_public_pads


def _green_region(path: Path, camera: str) -> dict:
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)
    height, width = rgb.shape[:2]
    yy, xx = np.indices((height, width))
    color = ((rgb[:, :, 0] > 90) &
             (rgb[:, :, 1] > rgb[:, :, 0] + 8) &
             (rgb[:, :, 1] > rgb[:, :, 2] + 8) &
             (rgb[:, :, 2] > 70))
    # This layout-0 pilot names the right-hand mint-green scissors; the ROIs
    # exclude the cyan/yellow tool on the other side of the table.
    roi = ((xx > 370) & (yy > 150) & (yy < 350) if camera == "cam_high"
           else (xx > 300) & (yy > 180) & (yy < 340))
    y, x = np.nonzero(color & roi)
    if len(x) < (150 if camera == "cam_high" else 500):
        raise ValueError(f"Current {camera} green scissors region unavailable")
    bbox = [int(x.min()), int(y.min()), int(x.max()), int(y.max())]
    if camera == "cam_high" and not (460 <= bbox[0] and bbox[2] <= 525):
        raise ValueError("High green region fails scissors identity ROI")
    if camera == "cam_right_wrist" and not (370 <= bbox[0] and bbox[2] <= 505):
        raise ValueError("Wrist green region fails scissors identity ROI")
    return {"pixels": int(len(x)), "bbox_xyxy": bbox,
            "center_uv": [round(float(x.mean()), 2), round(float(y.mean()), 2)],
            "center_spread_px": [round(float(x.std()), 2), round(float(y.std()), 2)],
            "scope": "Current RGB pale-green scissors handle region, not a corresponding physical point or contact target"}


def build(obs: dict) -> dict:
    if obs["task"] != "general_pickup" or "camera_calibration" not in obs:
        raise ValueError("Current calibrated general_pickup observation required")
    calibration = obs["camera_calibration"]
    if calibration["step_id"] != obs["step_id"]:
        raise ValueError("Current RGB and K/T step mismatch")
    files = {item["camera"]: Path(item["path"]) for item in obs["images"]}
    regions = {name: _green_region(files[name], name)
               for name in ("cam_high", "cam_right_wrist")}
    pads = inspect_public_pads(obs, calibration)
    facets = [np.asarray(pads["rows"][name]["inner_facet_world_xyz_m"], float)
              for name in ("link7", "link8")]
    pad_center = np.mean([points.mean(axis=0) for points in facets], axis=0)
    cameras = calibration["cameras"]
    pixel_error = {}
    for name, region in regions.items():
        uv = project(cameras[name], pad_center)
        if uv is None:
            raise ValueError(f"Public pad midpoint behind {name}")
        pixel_error[name] = {
            "source_green_region_center_uv": region["center_uv"],
            "projected_public_pad_midpoint_uv": [round(float(x), 2) for x in uv],
            "source_region_center_minus_pad_uv_px":
                np.subtract(region["center_uv"], uv).round(2).tolist(),
            "source_region_bbox_xyxy": region["bbox_xyxy"],
            "uncertainty": "Bounding region centre is not a grasp point; RGB segmentation, depth and scene clearance remain unknown",
        }
    wrist = cameras["cam_right_wrist"]
    ray_eye, ray_direction = ray(wrist, regions["cam_right_wrist"]["center_uv"])
    effects = {}
    for axis_index, axis in enumerate("xyz"):
        for sign, label in ((-1, "negative"), (1, "positive")):
            delta = np.zeros(3)
            delta[axis_index] = sign * 0.005
            moved_wrist = copy.deepcopy(wrist)
            for k in range(3):
                moved_wrist["camera_to_environment"][k][3] += float(delta[k])
            wrist_changes = []
            for ray_distance in (0.20, 0.30, 0.40, 0.60):
                point = ray_eye + ray_direction * ray_distance
                uv_after = project(moved_wrist, point)
                if uv_after is not None:
                    wrist_changes.append(np.subtract(
                        uv_after, regions["cam_right_wrist"]["center_uv"]))
            if not wrist_changes:
                raise ValueError("Wrist ray scenarios project behind camera")
            high_before = project(cameras["cam_high"], pad_center)
            high_after = project(cameras["cam_high"], pad_center + delta)
            effect = np.asarray(wrist_changes)
            effects[f"{axis}_{label}"] = {
                "world_LINK6_delta_m": delta.tolist(),
                "fixed_high_projected_pad_delta_uv_px":
                    np.subtract(high_after, high_before).round(2).tolist(),
                "moving_right_wrist_stationary_green_region_delta_uv_px_range": {
                    "min": effect.min(axis=0).round(2).tolist(),
                    "max": effect.max(axis=0).round(2).tolist()},
                "wrist_ray_distance_scenarios_m": [0.20, 0.30, 0.40, 0.60],
            }
    return {"task": obs["task"], "step_id": obs["step_id"],
            "source_regions": regions, "two_view_pixel_error": pixel_error,
            "world_axis_image_effect_at_5mm": effects,
            "method": "Current RGB color/shape-gated mint-green handle region; public X5 inward STL facets and current K/T; fixed-camera pad projection and moving-camera ray-distance scenarios",
            "limits": "The two mask centres are NOT the same physical point and are NOT triangulated. No metric object XYZ, depth, grasp point, contact, collision certificate or evaluator information is provided. The wrist pixel-motion ranges use hypothetical distances, not measured object depth."}

"""Optional RGB-only block labels for the stack_blocks Decisions pilot.

The color thresholds inspect rendered camera pixels. They never read object poses,
instance labels, segmentation buffers, contacts, or evaluator state.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

COLOR_BOUNDS = {
    "purple": ((145, 90, 60), (175, 255, 220)),
    "yellow": ((16, 25, 190), (32, 160, 255)),
    "white": ((0, 0, 210), (179, 20, 255)),
}
RANKS = ("initial_left", "initial_middle", "initial_right")
DRAW_COLORS = {"purple": (230, 140, 255), "yellow": (30, 250, 255), "white": (255, 255, 255)}

# RGB pixels only. These bounds locate the right open gripper in the fixed
# layout-0 high camera; they are not object/robot ground-truth coordinates.
RIGHT_TEMPLATE_XYWH = (500, 270, 80, 55)
RIGHT_SEARCH_XYWH = (360, 215, 260, 160)
RIGHT_FINGER_INNER_X = (489, 548)
RIGHT_FINGER_TIP_Y = 295


def detect_blocks(image_path: Path) -> list[dict]:
    """Locate only three compact color regions in a high-camera RGB frame."""
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(image_path)
    height, width = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    candidates = []
    for color, (low, high) in COLOR_BOUNDS.items():
        mask = cv2.inRange(hsv, np.asarray(low, dtype=np.uint8),
                           np.asarray(high, dtype=np.uint8))
        _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        valid = []
        for x, y, box_w, box_h, area in stats[1:]:
            center_x, center_y = x + box_w / 2, y + box_h / 2
            if not (0.20 * width < center_x < 0.86 * width and
                    0.15 * height < center_y < 0.77 * height):
                continue
            if not (70 <= area <= 1100 and 10 <= box_w <= 45 and 10 <= box_h <= 45):
                continue
            if not (0.55 <= box_w / box_h <= 1.8):
                continue
            valid.append((int(area), int(x), int(y), int(box_w), int(box_h)))
        if valid:
            area, x, y, box_w, box_h = max(valid)
            candidates.append({"color": color, "bbox_xywh": [x, y, box_w, box_h],
                               "center_px": [round(x + box_w / 2, 1), round(y + box_h / 2, 1)],
                               "mask_area_px": area})
    candidates.sort(key=lambda item: item["center_px"][0])
    if len(candidates) == 3:
        for rank, block in zip(RANKS, candidates):
            block["id"] = rank
    return candidates


def draw_reference(source: Path, destination: Path, blocks: list[dict],
                   target: str | None = None, base: str | None = None) -> Path:
    image = cv2.imread(str(source))
    if image is None:
        raise FileNotFoundError(source)
    for block in blocks:
        x, y, width, height = block["bbox_xywh"]
        block_id = block.get("id", block["color"])
        role = " TARGET" if block_id == target else " BASE" if block_id == base else ""
        label = f"{block_id}: {block['color']}{role}"
        color = (50, 255, 60) if block_id == target else (0, 220, 255) if block_id == base else DRAW_COLORS[block["color"]]
        cv2.rectangle(image, (x - 4, y - 4), (x + width + 4, y + height + 4), color, 2)
        cv2.putText(image, label, (max(8, x - 100), max(18, y - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(image, label, (max(8, x - 100), max(18, y - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(destination), image):
        raise OSError(f"Cannot write RGB reference: {destination}")
    return destination


def track_right_gripper(reference: Path, current: Path, extended: bool = False) -> dict:
    """Match a visible right-gripper RGB crop and report image displacement."""
    initial = cv2.imread(str(reference))
    image = cv2.imread(str(current))
    if initial is None or image is None:
        raise FileNotFoundError((reference, current))
    tx, ty, tw, th = RIGHT_TEMPLATE_XYWH
    sx, sy, sw, sh = (310, 150, 310, 225) if extended else RIGHT_SEARCH_XYWH
    template = initial[ty:ty + th, tx:tx + tw]
    search = image[sy:sy + sh, sx:sx + sw]
    response = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, location = cv2.minMaxLoc(response)
    dx = int(sx + location[0] - tx)
    dy = int(sy + location[1] - ty)
    left, right = (x + dx for x in RIGHT_FINGER_INNER_X)
    return {
        "template_shift_px": [dx, dy],
        "normalized_match_score": round(float(score), 4),
        "estimated_inner_finger_x_px": [left, right],
        "estimated_finger_tip_y_px": RIGHT_FINGER_TIP_Y + dy,
        "usable": bool(score >= 0.75),
        "limits": "Fixed layout-0 RGB template; approximate fingertip geometry, invalid after strong wrist rotation, lighting changes, or occlusion.",
    }

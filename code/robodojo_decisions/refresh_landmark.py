"""Ask the Pro planner for a specified same-point RGB landmark, then verify stereo."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from camera_geometry import estimate


def refresh_landmark(obs: dict, plan: dict, output: Path) -> dict:
    """Use only public images, camera calibration, robot state, and experience notes."""
    output = Path(output) / f"step_{int(obs['step_id']):03d}"
    output.mkdir(parents=True, exist_ok=False)
    data = Path(os.environ.get("ROBODOJO_GPT6_DATA_ROOT", str(Path.home() / "DataStorage/gpt6-dec")))
    experience = {}
    experience_root = data / "experience" / ("model" if plan.get("method_only") else "")
    for label, name in (("global", "global.md"), ("task", f"{obs['task']}.md")):
        path = experience_root / name
        if plan.get("method_only") and not path.is_file():
            raise FileNotFoundError(f"Model-facing experience missing: {path}")
        experience[label] = path.read_text() if path.is_file() else ""
    previous = plan.get("initial_landmark_estimate")
    spec = plan.get("landmark_spec") or {
        "landmark_id": "scissors_hinge_rivet_center",
        "target_identity": "the mint green scissors",
        "physical_landmark": "same circular rivet at the hinge between green handles and silver blades",
        "required_views": ["cam_high", "cam_right_wrist"],
    }
    required_views = spec.get("required_views")
    if (not isinstance(required_views, list) or len(required_views) != 2 or
            len(set(required_views)) != 2 or
            not set(required_views) <= {"cam_high", "cam_left_wrist", "cam_right_wrist"} or
            not all(isinstance(spec.get(key), str) and spec[key]
                    for key in ("landmark_id", "target_identity", "physical_landmark"))):
        raise ValueError("Invalid planner landmark_spec")
    public = {
        "task": obs["task"], "instruction": obs["instruction"],
        "step_id": obs["step_id"], "current_eef": obs["current_eef"],
        "current_joint_state": obs["current_state"],
        "camera_calibration": obs["camera_calibration"],
        "previous_camera_estimate": previous,
        "planner_visual_method": plan.get("visual_method"),
        "planner_experience": plan.get("experience"),
        "latest_experience_files": experience,
        "landmark_spec": spec,
    }
    system = (
        "You are GPT-6.1 Sol high, a sensor-only RoboDojo visual planner. "
        "Identify only landmark_spec.target_identity and the SAME physical point "
        "described by landmark_spec.physical_landmark in both named CURRENT RGB "
        "views. Do not switch to a nearby but different object or point. Camera "
        "intrinsics/extrinsics and robot state are public sensors. Never use true "
        "simulator object pose, reward, contact, or saved scene layout. The prior "
        "estimate and old wrist image are stale; use them only to preserve object "
        "identity, never copy old pixels. Return one JSON object with exactly "
        "landmark_id equal to the supplied landmark_spec.landmark_id, status='visible' "
        "or 'uncertain', landmark (short description), views mapping exactly the "
        "two landmark_spec.required_views to pixel_uv [u,v] and "
        "uncertainty_radius_px, and explanation. If the identical physical point "
        "cannot be located in both current images, set status "
        "uncertain and views empty. Do not invent 3D position."
    )
    parts = [{"type": "text", "text": json.dumps(public, ensure_ascii=False)}]
    images = []
    for item in obs["images"]:
        if item["camera"] not in {"cam_high", "cam_left_wrist", "cam_right_wrist"}:
            raise ValueError("Unexpected camera")
        path = Path(item["path"])
        raw = path.read_bytes()
        images.append({"camera": item["camera"], "path": str(path),
                       "sha256": hashlib.sha256(raw).hexdigest()})
        parts.append({"type": "text", "text": "CURRENT RGB " + item["camera"]})
        parts.append({"type": "image_url", "image_url": {
            "url": "data:image/png;base64," + base64.b64encode(raw).decode("ascii")}})
    (output / "input-manifest.json").write_text(json.dumps({
        "model": "gpt-6.1-sol", "reasoning_effort": "high", "public": public,
        "images": images,
        "experience_sha256": {k: hashlib.sha256(v.encode()).hexdigest()
                              for k, v in experience.items()},
    }, ensure_ascii=False, indent=2))
    payload = {"model": "gpt-6.1-sol", "reasoning_effort": "high",
               "response_format": {"type": "json_object"}, "stream": False,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": parts}]}
    from model_input_language import require_english_model_input
    require_english_model_input(payload, "legacy landmark planner request")
    request = urllib.request.Request("http://127.0.0.1:18883/v1/chat/completions",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"},
        method="POST")
    last_error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=900) as handle:
                response = json.load(handle)
            break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = str(error)
            time.sleep(min(10 * (attempt + 1), 30))
    else:
        raise RuntimeError("Pro landmark refresh failed: " + str(last_error))
    (output / "planner-response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2))
    annotation = json.loads(response["choices"][0]["message"]["content"])
    if annotation.get("landmark_id") != spec["landmark_id"]:
        raise ValueError("Planner changed physical landmark identity")
    if annotation.get("status") != "visible":
        raise ValueError("Specified same physical landmark not visible in both current RGB views")
    views = annotation.get("views")
    if not isinstance(views, dict) or set(views) != set(required_views):
        raise ValueError("Planner must annotate both required current RGB views")
    for name, item in views.items():
        uv = item.get("pixel_uv")
        radius = item.get("uncertainty_radius_px")
        width, height = obs["camera_calibration"]["cameras"][name]["size"]
        if (not isinstance(uv, list) or len(uv) != 2 or
                not all(isinstance(x, (int, float)) for x in uv) or
                not 0 <= uv[0] < width or not 0 <= uv[1] < height or
                not isinstance(radius, (int, float)) or not 1 <= radius <= 12):
            raise ValueError("Invalid planner pixel annotation")
    geometry = estimate(obs["camera_calibration"], annotation)
    (output / "annotation.json").write_text(json.dumps(annotation, ensure_ascii=False, indent=2))
    (output / "geometry.json").write_text(json.dumps(geometry, ensure_ascii=False, indent=2))
    if not geometry["accepted"]:
        errors = [item["reprojection_error_px"] for item in geometry["checks"].values()]
        radii = [item["annotation_uncertainty_radius_px"] for item in geometry["checks"].values()]
        diagnostic_only = bool(
            plan.get("method_only") and
            all(depth > 0 for depth in geometry["positive_ray_distances_m"]) and
            geometry["ray_condition"] <= 30 and geometry["ray_gap_m"] <= 0.010 and
            all(error is not None and error <= 4.0 and error <= radius + 0.5
                for error, radius in zip(errors, radii)))
        if not diagnostic_only:
            raise ValueError("Current two-view ray/reprojection check rejected landmark")
        geometry["diagnostic_only_near_consistent"] = True
        geometry["diagnostic_limits"] = (
            "Strict same-point stereo acceptance failed. This near-consistent ray result "
            "may inform only a <=5mm open-gripper precontact direction with full RGB veto; "
            "it may not justify object contact, grasp, closure, or a precise world target.")
        (output / "geometry.json").write_text(json.dumps(geometry, ensure_ascii=False, indent=2))
    return geometry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    obs = json.loads(args.observation.read_text())
    obs["camera_calibration"] = json.loads(args.calibration.read_text())
    geometry = refresh_landmark(obs, json.loads(args.plan.read_text()), args.output)
    print(json.dumps({"accepted": geometry["accepted"],
                      "step_id": geometry["camera_step_id"],
                      "ray_gap_m": geometry["ray_gap_m"],
                      "checks": geometry["checks"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

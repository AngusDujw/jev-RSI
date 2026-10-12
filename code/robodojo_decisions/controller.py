"""RGB + measured robot state -> OpenAI Decisions -> bounded native EEF action."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

MODEL = "gpt-6-luna"
ENDPOINT = "https://api.openai.com/v1/decisions"
MAX_QUERY_ATTEMPTS = 10
AXES = ("x", "y", "z")
ARMS = ("left", "right")
SIGNS = ("negative", "hold", "positive")
SIZES = {"fine": 0.005, "short": 0.015, "medium": 0.030, "long": 0.045}
ROTATIONS = {
    "hold": (0, 0.0), "yaw_positive": (2, 0.18), "yaw_negative": (2, -0.18),
    "pitch_positive": (1, 0.18), "pitch_negative": (1, -0.18),
    "roll_positive": (0, 0.18), "roll_negative": (0, -0.18),
}


def choice(name: str, instructions: str, options: dict[str, str]) -> dict:
    if len(options) < 2:
        raise ValueError(f"Decision choice {name} needs at least two options")
    return {"type": "choice", "name": name, "instructions": instructions,
            "choices": [{"value": value, "description": description}
                        for value, description in options.items()]}


def questions(plan: dict) -> list[dict]:
    stages = plan["stages"]
    result = [choice("stage", "Which observable stage should be worked on now? Choose from the provided task sequence using the CURRENT camera views and measured feedback. A native success must never be presumed.", stages)]
    for arm in ARMS:
        for axis in AXES:
            result.append(choice(f"{arm}_{axis}",
                f"For the {arm} hand LINK6 end-effector, should its next bounded target move toward negative {axis}, hold {axis}, or positive {axis} in the stated WORLD frame? Use the three fresh camera images, robot pose and current stage. Do not infer motion from image left/right alone.",
                {"negative": f"Decrease world {axis}", "hold": f"Keep world {axis}",
                 "positive": f"Increase world {axis}"}))
        result.append(choice(f"{arm}_size", f"Choose the {arm} hand translation magnitude for this one feedback move. Use fine near contact and release; larger moves only in clear free space.",
            {k: f"{v * 1000:g} mm normalized XYZ move" for k, v in SIZES.items()}))
        result.append(choice(f"{arm}_rotation", f"Choose one small world-frame orientation correction for the {arm} hand, or hold orientation. Rotation is around the LINK6 target, not an object pose.",
            {k: ("No orientation change" if k == "hold" else k.replace("_", " ") + " by 0.18 rad") for k in ROTATIONS}))
        result.append(choice(f"{arm}_gripper", f"Choose the {arm} gripper command from visual evidence; closing a gripper does not prove an object is held.",
            {"keep": "Retain measured open/closed command", "open": "Open", "close": "Close"}))
    result.extend([
        {"type": "predicate", "name": "left_object_held", "instructions": "Do current cameras provide clear visual evidence that the LEFT gripper is carrying the intended target object off its support?"},
        {"type": "predicate", "name": "right_object_held", "instructions": "Do current cameras provide clear visual evidence that the RIGHT gripper is carrying the intended target object off its support?"},
        {"type": "predicate", "name": "visible_goal_done", "instructions": "Do the CURRENT cameras clearly show the full task goal complete, including release/return if the instruction requires it? Do not use hidden evaluator state."},
    ])
    return result


def geometry_sign_questions(obs: dict, plan: dict) -> list[dict]:
    """Offer Luna only directions supported by a fresh, public RGB landmark."""
    landmark = plan.get("initial_landmark_estimate", {})
    age = int(obs["step_id"]) - int(landmark.get("camera_step_id", -1000))
    if not landmark.get("accepted") or not 0 <= age < 40:
        raise ValueError("RGB landmark estimate is missing or stale")
    point = landmark["estimated_position_environment_m"]
    current = obs["current_eef"]["right"]["position"]
    stages = {name: plan["stages"][name] for name in ("pregrasp", "sense_view")}
    result = [choice("stage", "Use current RGB to decide whether the visible scissors and right hand support a cautious pregrasp move, or a view check. Neither option declares a grasp.", stages)]
    for index, axis in enumerate(("x", "y")):
        residual = float(point[index]) - float(current[index])
        direction = "positive" if residual >= 0 else "negative"
        if abs(residual) <= 0.015:
            options = {"hold": "Remain at the measured axis position", direction: "Only if current RGB clearly requires it, correct within the 15 mm uncertainty band"}
        else:
            options = {"hold": "Pause this axis because the current RGB makes the path uncertain", direction: f"Move toward the RGB-derived landmark along world {axis}; estimated residual {residual:+.3f} m"}
        result.append(choice(f"right_{axis}", f"Pick one world-frame direction for the right LINK6. The landmark is a scissors hinge, not a contact target. Current signed residual {residual:+.3f} m; use the images to reject unsafe motion.", options))
    result.append(choice("right_size", "Choose at most a 10 mm 3D translation for one observed precontact step.",
                         {"fine": "5 mm 3D translation", "short": "10 mm maximum after clipping"}))
    result.extend([
        {"type": "predicate", "name": "right_object_held", "instructions": "Do fresh RGB views clearly show the scissors held off the table?"},
        {"type": "predicate", "name": "visible_goal_done", "instructions": "Do fresh RGB views clearly show scissors lifted by 10 cm and held?"},
    ])
    return result


def geometry_candidate_questions(obs: dict, plan: dict) -> list[dict]:
    """Luna judges complete, bounded actions synthesized from public sensors."""
    landmark = plan.get("initial_landmark_estimate", {})
    age = int(obs["step_id"]) - int(landmark.get("camera_step_id", -1000))
    if not landmark.get("accepted") or not 0 <= age < 40:
        raise ValueError("RGB landmark estimate is missing or stale")
    point = landmark["estimated_position_environment_m"]
    current = obs["current_eef"]["right"]["position"]
    residual = [float(point[i]) - float(current[i]) for i in range(3)]
    axes = ["+" if d > 0 else "-" for d in residual[:2]]
    instructions = (
        "Inspect all three CURRENT RGB views and choose one complete, open-gripper "
        "precontact action. The candidate toward the RGB-derived scissors hinge "
        f"moves world X{axes[0]}/Y{axes[1]} by 10 mm TOTAL, remains at current Z, "
        "and must be followed by a fresh image. It is a diagnostic move toward a "
        "landmark, not a grasp/contact point. The view candidate raises world Z by "
        "5 mm for a new image. Choose stop only if target identity or the next 10 mm "
        "corridor cannot be judged safe from current RGB."
    )
    return [
        choice("motion", instructions, {
            "probe_toward": "Small planar pregrasp probe toward camera-derived hinge, 10 mm total, gripper open",
            "probe_view": "Raise view by 5 mm, gripper open, to reduce occlusion; maximum two uses",
            "stop": "Do not move; return a specific visual blocker for replanning",
        }),
        choice("blocker", "Which current visual fact most limits this precontact action? Choose none when a safe 10 mm corridor is visible.", {
            "none": "No specific blocker visible in the first 10 mm corridor",
            "target_identity": "The mint green scissors cannot be identified consistently",
            "occluded_path": "The gripper-to-target corridor is occluded",
            "visible_collision": "A specific object or table intersection blocks the proposed 10 mm move",
        }),
        {"type": "predicate", "name": "right_object_held", "instructions": "Do fresh RGB views clearly show the scissors carried off the table by the right gripper?"},
        {"type": "predicate", "name": "visible_goal_done", "instructions": "Do fresh RGB views clearly show scissors lifted by 10 cm and held?"},
    ]


def public_evidence(obs: dict, plan: dict, stage: str, history: list[dict]) -> str:
    # Deliberately omit native_success, evaluator score, scene layout, object pose and contacts.
    previous = history[-6:]
    state = obs["current_state"]
    clean = {
        "task": obs["task"], "instruction": obs["instruction"],
        "world_frame": "RoboDojo environment origin; +X/+Y/+Z are fixed world axes; Z increases upward",
        "end_effector": "LINK6 poses, position in meters, quaternion wxyz",
        "gripper_state": "joint command 0 closed, 1 open; this is not grasp evidence",
        "current_eef": obs["current_eef"], "current_joint_state": state,
        "current_camera_calibration": obs.get("camera_calibration"),
        "step_id": obs["step_id"], "remaining_native_steps": obs["remaining_steps"],
        "stage_before_this_decision": stage, "stage_recipe": plan["stages"],
        "task_notes": plan.get("notes", ""),
        "planner_task_detail": plan.get("task_detail"),
        "planner_visual_method": plan.get("visual_method"),
        "planner_experience": plan.get("experience", []),
        "decision_constraint": (
            "For this diagnostic pregrasp pilot, choose only offered world X/Y signs supported by the "
            "fresh RGB-derived hinge estimate. Z, rotation, both grippers and the left arm stay fixed. "
            "Stop after 40 native steps until the landmark can be re-observed. The hinge is not a grasp point."
            if plan.get("geometry_sign_gate") else
            "Choose among complete 10 mm planar approach, 5 mm view, or stop candidates. "
            "Inspect the current RGB for target identity and a specific immediate path blocker. "
            "No gripper contact, rotation or left-arm motion is permitted in this short pilot. "
            "The initial hinge estimate expires after 40 native steps."
            if plan.get("geometry_candidate_gate") else None),
        "recent_executed_actions": previous,
        "instruction_to_decision_model": (
            "Inspect ALL three attached fresh RGB views directly. Decide the current task stage, bounded LINK6 motion, "
            "small orientation change and gripper command for BOTH arms. Choose hold for an unused arm. "
            "Check actual measured EEF movement and fresh visual object movement against the previous command. "
            "A listed candidate answer is a decision, not a declaration of simulator success. "
            "Use visual evidence to correct the phase after failed grasp, slip, or blocked motion. "
            "Do not claim target grasp from a closed gripper alone."
        ),
    }
    landmark = plan.get("initial_landmark_estimate")
    if landmark and landmark.get("accepted"):
        age = int(obs["step_id"]) - int(landmark["camera_step_id"])
        point = landmark["estimated_position_environment_m"]
        task_detail = plan.get("task_detail")
        arm = task_detail.get("active_arm", "right") if isinstance(task_detail, dict) else "right"
        eef = obs["current_eef"][arm]["position"]
        clean["camera_landmark_hypothesis"] = {
            "source": landmark["source"], "visible_part": landmark["landmark"],
            "initial_estimate_environment_m": point,
            "initial_ray_gap_m": landmark["ray_gap_m"],
            "initial_reprojection_checks": landmark["checks"],
            "age_native_steps": age,
            "accepted_for_bounded_precontact_approach": age <= 40,
            "landmark_minus_current_link6_m":
                [round(float(target) - float(current), 5)
                 for target, current in zip(point, eef)] if age <= 40 else None,
            "limitation": (
                "This is an RGB landmark estimate from an initial observation, not a "
                "known object pose or gripper contact point. After 40 native steps, "
                "reobserve and recompute before using the metric residual again. "
                "Inspect all current RGB for target motion or occlusion after each move."
            ),
        }
    return json.dumps(clean, ensure_ascii=False, separators=(",", ":"))


def decode_response(response: dict, asked: list[dict]) -> dict:
    if response.get("model") != MODEL:
        raise ValueError(f"Unexpected decision model: {response.get('model')}")
    expected = {q["name"]: q for q in asked}
    answers = response.get("answers")
    if not isinstance(answers, list):
        raise ValueError("Missing decision answers")
    found = {}
    for item in answers:
        name = item.get("name")
        if name not in expected or name in found or item.get("type") == "refusal":
            raise ValueError(f"Missing, duplicate or refused decision question: {name}")
        kind = expected[name]["type"]
        if item.get("type") != kind:
            raise ValueError(f"Question {name} returned wrong type")
        if kind == "choice":
            options = {entry["value"] for entry in expected[name]["choices"]}
            if item.get("choice") not in options:
                raise ValueError(f"Question {name} returned invalid choice")
            found[name] = item["choice"]
        else:
            probability = item.get("probability")
            if not isinstance(probability, (int, float)) or not 0 <= probability <= 1:
                raise ValueError(f"Question {name} returned invalid probability")
            found[name] = float(probability)
    if set(found) != set(expected):
        raise ValueError(f"Missing decision answers: {sorted(set(expected) - set(found))}")
    return found


def decode_answers(response: dict, plan: dict) -> dict:
    return decode_response(response, questions(plan))


def curl_socks_decision(payload: dict, key: str, timeout: int) -> dict:
    """Send one Decisions read over local SOCKS without putting the key in argv or on disk."""
    config_fd, config_writer = os.pipe()
    try:
        os.write(config_writer, f'header = "Authorization: Bearer {key}"\n'.encode())
    finally:
        os.close(config_writer)
    try:
        environment = os.environ.copy()
        for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
                     "ALL_PROXY", "all_proxy"):
            environment.pop(name, None)
        command = ["curl", "--silent", "--show-error", "--http1.1",
                   "--socks5-hostname", "127.0.0.1:7897", "--connect-timeout", "15",
                   "--max-time", str(timeout), "--header", "Content-Type: application/json",
                   "--config", f"/proc/self/fd/{config_fd}", "--data-binary", "@-",
                   "--write-out", "\n%{http_code}", ENDPOINT]
        try:
            result = subprocess.run(command, input=json.dumps(payload).encode(),
                                    capture_output=True, env=environment, pass_fds=(config_fd,),
                                    timeout=timeout + 5, check=False)
        except subprocess.TimeoutExpired as error:
            raise urllib.error.URLError("curl SOCKS Decisions request timed out") from error
        body, separator, raw_status = result.stdout.rpartition(b"\n")
        status = int(raw_status) if separator and raw_status.isdigit() else 0
        if status >= 400:
            raise urllib.error.HTTPError(ENDPOINT, status, "Decisions HTTP error", None,
                                         io.BytesIO(body))
        if result.returncode or not 200 <= status < 300:
            detail = result.stderr.decode(errors="replace")[:500]
            raise urllib.error.URLError(f"curl SOCKS transport code={result.returncode}, status={status}: {detail}")
        return json.loads(body)
    finally:
        os.close(config_fd)


def to_action(obs: dict, answers: dict, max_translation_m: float = 0.05) -> dict:
    target = {}
    for index, arm in enumerate(ARMS):
        old = obs["current_eef"][arm]
        signs = np.asarray([{"negative": -1.0, "hold": 0.0, "positive": 1.0}[answers[f"{arm}_{axis}"]]
                            for axis in AXES])
        norm = float(np.linalg.norm(signs))
        delta = signs / norm * SIZES[answers[f"{arm}_size"]] if norm else signs
        if np.linalg.norm(delta) > max_translation_m:
            delta = delta / np.linalg.norm(delta) * max_translation_m
        position = np.asarray(old["position"], dtype=float) + delta
        old_q = np.asarray(old["quaternion_wxyz"], dtype=float)
        rotation_axis, radians = ROTATIONS[answers[f"{arm}_rotation"]]
        vector = np.zeros(3)
        vector[rotation_axis] = radians
        current = Rotation.from_quat(old_q[[1, 2, 3, 0]])
        changed = Rotation.from_rotvec(vector) * current
        xyzw = changed.as_quat()
        wxyz = xyzw[[3, 0, 1, 2]]
        gripper = answers[f"{arm}_gripper"]
        closed = bool(obs["current_state"][index * 7 + 6] < 0.5) if gripper == "keep" else gripper == "close"
        if not math.isfinite(float(np.linalg.norm(position))) or np.linalg.norm(delta) > 0.05 + 1e-9:
            raise ValueError("Generated action outside 5 cm bound")
        target[arm] = {"position": position.tolist(), "quaternion_wxyz": wxyz.tolist(),
                       "gripper_closed": closed}
    return {"request_id": obs["request_id"], "mode": "eef", "steps": 5,
            "reason": "RGB Decisions stage=" + answers["stage"] + "; bounded EEF response to current cameras and measured robot state",
            "target": target}


class DecisionClient:
    def __init__(self, key_file: Path, output: Path, timeout: int = 90):
        self.key_file = Path(key_file)
        self.output = Path(output)
        self.timeout = timeout

    def query(self, obs: dict, asked: list[dict], evidence: str, record_name: str,
              reference_image: Path | None = None,
              extra_images: list[dict] | None = None) -> dict:
        content = [{"type": "input_text", "text": evidence}]
        image_info = []
        images = list(obs["images"])
        if reference_image is not None:
            images.append({"camera": "initial_high_camera_reference", "path": str(reference_image)})
        images.extend(extra_images or [])
        for image in images:
            path = Path(image["path"])
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            content.append({"type": "input_text", "text": image["camera"]})
            content.append({"type": "input_image", "detail": "high",
                            "image_url": "data:image/png;base64," + base64.b64encode(raw).decode("ascii")})
            image_info.append({"camera": image["camera"], "path": str(path), "sha256": digest,
                               "bytes": len(raw)})
        payload = {"model": MODEL, "input": [{"role": "user", "content": content}],
                   "questions": asked}
        key = self.key_file.read_text().strip()
        if not key.startswith("sk-"):
            raise ValueError("Key file does not contain an OpenAI API key")
        meta = {"record_name": record_name, "step_id": obs["step_id"], "model": MODEL,
                "input_text": content[0]["text"], "images": image_info,
                "question_names": [q["name"] for q in payload["questions"]]}
        self.output.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        request = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            method="POST")
        transient_errors = []
        for attempt in range(MAX_QUERY_ATTEMPTS):
            try:
                if os.environ.get("ROBODOJO_DECISION_TRANSPORT") == "curl_socks":
                    response = curl_socks_decision(payload, key, self.timeout)
                else:
                    with urllib.request.urlopen(request, timeout=self.timeout) as handle:
                        response = json.load(handle)
                break
            except urllib.error.HTTPError as error:
                body = error.read().decode("utf-8", errors="replace")[:2000]
                try:
                    error_code = json.loads(body).get("error", {}).get("code")
                except (ValueError, AttributeError):
                    error_code = None
                transport_scheme_error = (error.code == 403 and error_code == "http_unsupported"
                                          and ENDPOINT.startswith("https://"))
                if (error.code in (429, 500, 502, 503, 504) or transport_scheme_error) and attempt + 1 < MAX_QUERY_ATTEMPTS:
                    transient_errors.append({"attempt": attempt + 1,
                                             "http_status": error.code, "error_code": error_code})
                    time.sleep(min(2 ** attempt, 30))
                    continue
                (self.output / f"{record_name}.json").write_text(json.dumps(
                    {**meta, "latency_s": time.monotonic() - started, "attempts": attempt + 1,
                     "transient_errors": transient_errors, "http_status": error.code,
                     "error_body": body}, ensure_ascii=False, indent=2))
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError,
                    json.JSONDecodeError) as error:
                transient_errors.append({"attempt": attempt + 1,
                                         "error_type": type(error).__name__, "error": str(error)})
                if attempt + 1 < MAX_QUERY_ATTEMPTS:
                    time.sleep(min(2 ** attempt, 30))
                    continue
                (self.output / f"{record_name}.json").write_text(json.dumps(
                    {**meta, "latency_s": time.monotonic() - started, "attempts": attempt + 1,
                     "transient_errors": transient_errors}, ensure_ascii=False, indent=2))
                raise
        answers = decode_response(response, asked)
        record = {**meta, "latency_s": time.monotonic() - started,
                  "attempts": len(transient_errors) + 1, "transient_errors": transient_errors,
                  "response_id": response.get("id"), "response_model": response.get("model"),
                  "usage": response.get("usage"), "raw_answers": response.get("answers"),
                  "decoded_answers": answers}
        (self.output / f"{record_name}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
        return answers

    def decide(self, obs: dict, plan: dict, stage: str, history: list[dict]) -> tuple[dict, dict]:
        record_name = f"decision_{len(history):04d}"
        sign_gated = bool(plan.get("geometry_sign_gate"))
        candidate_gated = bool(plan.get("geometry_candidate_gate"))
        if sign_gated and candidate_gated:
            raise ValueError("Only one geometry decision gate may be active")
        asked = (geometry_candidate_questions(obs, plan) if candidate_gated else
                 geometry_sign_questions(obs, plan) if sign_gated else questions(plan))
        answers = self.query(obs, asked, public_evidence(obs, plan, stage, history), record_name)
        if candidate_gated:
            landmark = plan["initial_landmark_estimate"]["estimated_position_environment_m"]
            current = obs["current_eef"]["right"]["position"]
            residual = [float(landmark[i]) - float(current[i]) for i in range(2)]
            motion = answers["motion"]
            if motion == "probe_toward" and answers["blocker"] == "occluded_path":
                answers["motion_routed_from"] = motion
                motion = "probe_view"
            elif motion == "probe_toward" and answers["blocker"] != "none":
                answers["motion_routed_from"] = motion
                motion = "stop"
            signs = ["positive" if x > 0.015 else "negative" if x < -0.015 else "hold"
                     for x in residual]
            approach_stage = "planar_align" if "planar_align" in plan["stages"] else "pregrasp"
            sense_stage = "sense_scissors" if "sense_scissors" in plan["stages"] else "sense_view"
            answers = {**{
                "left_x": "hold", "left_y": "hold", "left_z": "hold", "left_size": "fine",
                "left_rotation": "hold", "left_gripper": "keep", "right_rotation": "hold",
                "right_gripper": "keep", "left_object_held": 0.0,
            }, **answers, "motion": motion,
                "stage": approach_stage if motion == "probe_toward" else sense_stage,
                "right_x": signs[0] if motion == "probe_toward" else "hold",
                "right_y": signs[1] if motion == "probe_toward" else "hold",
                "right_z": "positive" if motion == "probe_view" else "hold",
                "right_size": "fine" if motion == "probe_view" else "short"}
        if sign_gated:
            answers = {**{
                "left_x": "hold", "left_y": "hold", "left_z": "hold", "left_size": "fine",
                "left_rotation": "hold", "left_gripper": "keep", "right_z": "hold",
                "right_rotation": "hold", "right_gripper": "keep", "left_object_held": 0.0,
            }, **answers}
        action = to_action(obs, answers, max_translation_m=0.01 if (sign_gated or candidate_gated) else 0.05)
        path = self.output / f"{record_name}.json"
        record = json.loads(path.read_text())
        record["action"] = action
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
        return action, answers

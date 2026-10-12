"""RGB + measured robot state -> OpenAI Decisions -> bounded native EEF action."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

MODEL = "gpt-6-luna"
ENDPOINT = "https://api.openai.com/v1/decisions"
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
        "step_id": obs["step_id"], "remaining_native_steps": obs["remaining_steps"],
        "stage_before_this_decision": stage, "stage_recipe": plan["stages"],
        "task_notes": plan.get("notes", ""), "recent_executed_actions": previous,
        "instruction_to_decision_model": (
            "Inspect ALL three attached fresh RGB views directly. Decide the current task stage, bounded LINK6 motion, "
            "small orientation change and gripper command for BOTH arms. Choose hold for an unused arm. "
            "Check actual measured EEF movement and fresh visual object movement against the previous command. "
            "A listed candidate answer is a decision, not a declaration of simulator success. "
            "Use visual evidence to correct the phase after failed grasp, slip, or blocked motion. "
            "Do not claim target grasp from a closed gripper alone."
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


def to_action(obs: dict, answers: dict) -> dict:
    target = {}
    for index, arm in enumerate(ARMS):
        old = obs["current_eef"][arm]
        signs = np.asarray([{"negative": -1.0, "hold": 0.0, "positive": 1.0}[answers[f"{arm}_{axis}"]]
                            for axis in AXES])
        norm = float(np.linalg.norm(signs))
        delta = signs / norm * SIZES[answers[f"{arm}_size"]] if norm else signs
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
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as handle:
                response = json.load(handle)
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")[:2000]
            (self.output / f"{record_name}.json").write_text(json.dumps(
                {**meta, "latency_s": time.monotonic() - started, "http_status": error.code,
                 "error_body": body}, ensure_ascii=False, indent=2))
            raise
        answers = decode_response(response, asked)
        record = {**meta, "latency_s": time.monotonic() - started,
                  "response_id": response.get("id"), "response_model": response.get("model"),
                  "usage": response.get("usage"), "raw_answers": response.get("answers"),
                  "decoded_answers": answers}
        (self.output / f"{record_name}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
        return answers

    def decide(self, obs: dict, plan: dict, stage: str, history: list[dict]) -> tuple[dict, dict]:
        record_name = f"decision_{len(history):04d}"
        answers = self.query(obs, questions(plan), public_evidence(obs, plan, stage, history), record_name)
        action = to_action(obs, answers)
        path = self.output / f"{record_name}.json"
        record = json.loads(path.read_text())
        record["action"] = action
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
        return action, answers

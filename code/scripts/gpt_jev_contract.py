"""Task-independent, data-only GPT plan grammar and bounded Jev interpreter."""
from __future__ import annotations

import json
import math
import re

CAMERAS = ("agentview", "robot0_eye_in_hand")
VERSION = "gpt-jev-contract-v1"
CAPABILITIES = {
    "schema": VERSION,
    "observations": "Current RGB-D, camera calibration, TCP pose, gripper proprioception, own finger geometry and acknowledged action history only",
    "frame": "world; meters; quaternion convention is xyzw; rotation deltas are world rotation vectors",
    "anchor_processing": "Median depth of a 1..4 pixel radius patch, followed by calibrated pinhole backprojection; reject invalid or discontinuous patches",
    "target_expression": "anchor_world + offset_m; anchor tcp is evaluated at stage entry; pad_center subtracts own pad offset at desired orientation",
    "motion_limits": {"translation_l2_m": 0.02, "rotation_l2_rad": 0.10, "native_steps_per_decision": 3},
    "pose_tolerance": {"position_l2_m": 0.008, "orientation_l2_rad": 0.06},
    "gripper": "open or close or keep; command delivery and joint positions do not prove object retention",
    "stage_limit_decisions": 40,
    "forced_visual_review": "After at most 4 stages or 40 decisions, on stalled motion or missing evidence",
    "unsupported": ["arbitrary code", "hidden object state", "collision certification", "force sensing", "learned visual predicates", "automatic task recipes"],
}


def schema():
    def obj(properties):
        return dict(type="object", properties=properties, required=list(properties), additionalProperties=False)

    text = dict(type="string", minLength=1, maxLength=500)
    vec = dict(type="array", items=dict(type="number"), minItems=3, maxItems=3)
    anchor = obj(dict(id=dict(type="string", pattern="^[a-z][a-z0-9_]{0,23}$"),
        camera=dict(type="string", enum=list(CAMERAS)),
        pixel=dict(type="array", items=dict(type="integer", minimum=0, maximum=767), minItems=2, maxItems=2),
        radius_px=dict(type="integer", minimum=1, maximum=4), meaning=text))
    target = obj(dict(anchor=dict(type="string"), offset_m=vec,
        tool_point=dict(type="string", enum=["tcp", "pad_center"])))
    stage = obj(dict(id=dict(type="string", pattern="^[a-z][a-z0-9_]{0,23}$"), intent=text,
        target=target, rotation_delta_world_rad=vec,
        gripper=dict(type="string", enum=["open", "close", "keep"]),
        min_steps=dict(type="integer", minimum=1, maximum=20),
        review_after=dict(type="boolean"), visual_check=text))
    return obj(dict(status=dict(type="string", enum=["plan", "stop", "complete"]),
        explanation=text,
        anchors=dict(type="array", items=anchor, maxItems=12),
        stages=dict(type="array", items=stage, maxItems=8)))


def english(value):
    """Check actual nested text, including escaped JSON, before either model call."""
    if isinstance(value, dict):
        for key, item in value.items():
            english(key)
            english(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            english(item)
    elif isinstance(value, str) and not value.startswith("data:image/"):
        if not value.isascii() or re.search(r"\\u(?:[2-9a-fA-F][0-9a-fA-F]{3})", value):
            raise ValueError("Model-visible text must be English ASCII")


def validate(plan):
    """Validate without eval, generated Python, implicit defaults or task lookup."""
    def walk(value, rule):
        kind = rule["type"]
        if kind == "object":
            if not isinstance(value, dict) or set(value) != set(rule["properties"]):
                raise ValueError("Unexpected or missing contract field")
            for k, v in value.items():
                walk(v, rule["properties"][k])
        elif kind == "array":
            if not isinstance(value, list) or not rule.get("minItems", 0) <= len(value) <= rule.get("maxItems", 100):
                raise ValueError("Invalid array length")
            for v in value:
                walk(v, rule["items"])
        elif kind == "string":
            if not isinstance(value, str) or not rule.get("minLength", 0) <= len(value) <= rule.get("maxLength", 500):
                raise ValueError("Invalid contract text")
            if "pattern" in rule and not re.fullmatch(rule["pattern"], value):
                raise ValueError("Invalid identifier")
        elif kind == "boolean":
            if type(value) is not bool:
                raise ValueError("Expected boolean")
        else:
            if type(value) not in ((int,) if kind == "integer" else (int, float)) or not math.isfinite(value):
                raise ValueError("Expected finite number")
            if not rule.get("minimum", -math.inf) <= value <= rule.get("maximum", math.inf):
                raise ValueError("Number outside contract limits")
        if "enum" in rule and value not in rule["enum"]:
            raise ValueError("Unsupported contract option")

    english(plan)
    walk(plan, schema())
    names = [a["id"] for a in plan["anchors"]]
    if len(set(names)) != len(names) or "tcp" in names:
        raise ValueError("Duplicate or reserved anchor")
    ids = [s["id"] for s in plan["stages"]]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate stage")
    if (plan["status"] == "plan") != bool(ids):
        raise ValueError("Only plan status may have stages, and it needs a stage")
    for stage in plan["stages"]:
        if stage["target"]["anchor"] not in names + ["tcp"]:
            raise ValueError("Unknown target anchor")
        if math.sqrt(sum(x*x for x in stage["target"]["offset_m"])) > .5:
            raise ValueError("Target offset exceeds local contract")
        if math.sqrt(sum(x*x for x in stage["rotation_delta_world_rad"])) > math.pi:
            raise ValueError("Rotation exceeds principal local range")
    return plan


def jev_request(stage, position_error, rotation_error, gripper_command, executed_steps, ready, model):
    """Expose only current contract/evidence. Jev owns every dispatched choice."""
    def choice(instructions, criteria):
        return dict(type="choice", instructions=instructions, criteria=criteria)
    axes = dict(negative="Decrease world coordinate", hold="No movement on this axis", positive="Increase world coordinate")
    questions = {}
    for j, axis in enumerate(("x", "y", "z", "rx", "ry", "rz")):
        questions[axis] = choice(
            f"Read axes.{axis}.goal_relation. Choose positive for increase, negative for decrease, and hold for within_tolerance. This is a direction choice, not a numeric calculation.", axes)
    questions["gripper"] = choice("Follow the stage gripper requirement; keep preserves the last command. Closure is not grasp evidence.",
        dict(open="Command open", close="Command close", keep="Preserve last command"))
    edges = dict(continue_phase="Execute one bounded control update in this stage", review="Request fresh GPT visual planning", stop="Stop incomplete")
    if ready:
        edges["advance"] = "Local pose and command-delivery gates passed; advance, without claiming object or task success"
    questions["transition"] = choice(
        "The supplied axes and local_gates_passed are current valid execution evidence. When local_gates_passed is false, choose continue_phase to approach the local goal. When true, choose advance. Visual object-effect checks belong to the next GPT review, not this local gate. Choose review only if current local motion evidence is missing or contradictory; do not demand future arrival evidence before moving.", edges)
    local_stage = dict(id=stage["id"], intent=stage["intent"], gripper=stage["gripper"])
    state = dict(stage=local_stage, translation_error_world_m=position_error,
        rotation_error_world_rad=rotation_error, previous_gripper_command=gripper_command,
        acknowledged_stage_native_steps=executed_steps, local_gates_passed=ready,
        translation_axis_tolerance_m=.008/math.sqrt(3), rotation_axis_tolerance_rad=.06/math.sqrt(3),
        evidence_scope="Robot pose and delivered commands only; object effects require a fresh visual review")
    state["axes"] = {}
    for axis, residual in zip(("x", "y", "z", "rx", "ry", "rz"), position_error + rotation_error):
        tolerance = (.008 if len(axis) == 1 else .06)/math.sqrt(3)
        state["axes"][axis] = dict(error=residual, goal_relation="within_tolerance" if abs(residual) <= tolerance else "increase" if residual > 0 else "decrease")
    request = dict(model=model, state=state, questions=questions)
    english(request)
    return request


def parse_jev(request, response):
    if response.get("model") != request["model"] or set(response.get("answers", {})) != set(request["questions"]):
        raise ValueError("Unexpected Jev model or answer set")
    choices = {}
    for name, q in request["questions"].items():
        answer = response["answers"][name]
        if answer.get("type") != "choice" or answer.get("choice") not in q["criteria"]:
            raise ValueError("Jev choice outside declared options")
        p = answer.get("probabilities", {})
        if set(p) != set(q["criteria"]) or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in p.values()) or abs(sum(p.values())-1) > .02:
            raise ValueError("Invalid Jev probabilities")
        choices[name] = answer["choice"]
    return choices

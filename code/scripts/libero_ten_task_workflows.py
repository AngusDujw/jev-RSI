"""Public-language LIBERO-Plus task plans and Jev-style decision contracts.

This module builds decision inputs; it does not infer hidden scene state, move
the robot, call a model, or claim that a task has been completed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class TaskPlan:
    task_id: int
    language: str
    primitives: tuple[str, ...]
    source: str
    destination: str
    relation: str


TASKS = {
    1098: TaskPlan(1098, "please make sure the middle drawer of the cabinet is open",
        ("open_drawer",), "middle drawer handle", "drawer opening", "open"),
    1144: TaskPlan(1144, "place the round deep dish used for serving food onto the appliance used for cooking",
        ("pick_place",), "bowl", "stove top", "on"),
    1163: TaskPlan(1163, "could you place the wine bottle on top of the cabinet for me please",
        ("pick_place",), "wine bottle", "cabinet top", "on"),
    1202: TaskPlan(1202, "when you get a chance would you mind opening the top drawer to store the bowl inside",
        ("open_drawer", "pick_place"), "top drawer handle; bowl", "open drawer interior", "inside"),
    1252: TaskPlan(1252, "could you place the bowl up on the cabinet for me please",
        ("pick_place",), "bowl", "cabinet top", "on"),
    1296: TaskPlan(1296, "could you please push the plate to the front of the stove i need it for cooking",
        ("push",), "plate", "visible free patch in front of stove", "in_front_of"),
    1335: TaskPlan(1335, "could you put the cream cheese into the bowl",
        ("pick_place",), "cream cheese", "bowl interior", "inside"),
    1383: TaskPlan(1383, "ignite the cooking appliance",
        ("turn_control",), "visible stove control", "stove control", "turn_on"),
    1423: TaskPlan(1423, "could you kindly put the bowl onto the plate for me",
        ("pick_place",), "bowl", "plate", "on"),
    1458: TaskPlan(1458, "could we place the wine bottle in the rack",
        ("pick_place",), "wine bottle", "rack opening", "inside"),
}

# Each gate describes evidence to measure from RGB-D, calibration, the robot's
# own mesh/proprioception, and executed action history. None is a simulator
# success predicate. A false/unknown gate leaves the model in the phase.
PHASES = {
    "pick_place": (
        ("observe", "source and receiving region visible; identity unambiguous", "visible_identity"),
        ("select_grasp", "choose a visible pad-overlap/clearance candidate", "candidate_selected"),
        ("approach", "move above candidate with open gripper", "hover_reached"),
        ("align", "orient own finger envelope around visible object", "orientation_reached"),
        ("descend", "reach observed contact pose without crossing support", "contact_pose_reached"),
        ("grasp", "close gripper while holding contact pose", "closure_executed"),
        ("test_lift", "lift briefly and compare visible source motion with TCP", "visible_co_motion"),
        ("lift", "raise held source above visible obstacles", "clearance_reached"),
        ("carry", "move above visible receiving region", "receiver_hover_reached"),
        ("lower", "lower toward observed receiving surface or opening", "release_pose_reached"),
        ("release", "open gripper at release pose", "opening_executed"),
        ("retreat", "withdraw without dragging source", "retreat_reached"),
        ("verify", "observe source resting in intended visible relation", "visible_relation"),
    ),
    "push": (
        ("observe", "identify source, free goal patch and visible straight corridor", "visible_corridor"),
        ("approach_rear", "move behind visible source along goal direction", "rear_hover_reached"),
        ("lower", "lower own finger to visible side-contact height", "side_contact_pose_reached"),
        ("push", "move along corridor; compare plate motion with TCP motion", "visible_goal_reached"),
        ("retreat", "withdraw from plate", "retreat_reached"),
        ("verify", "reobserve plate and visible goal relation", "visible_relation"),
    ),
    "open_drawer": (
        ("observe", "identify specified handle and visible cabinet front", "handle_visible"),
        ("approach", "move open gripper to handle approach pose", "handle_hover_reached"),
        ("align", "align own fingers to visible handle and cabinet-front normal", "orientation_reached"),
        ("contact", "reach handle without crossing cabinet front", "handle_contact_pose_reached"),
        ("grasp", "close on handle and measure actual aperture", "closure_executed"),
        ("pull", "pull outward along estimated cabinet-front normal; measure handle displacement", "visible_handle_displacement"),
        ("release", "open gripper", "opening_executed"),
        ("verify", "observe drawer aperture increase from initial image", "visible_opening"),
    ),
    "turn_control": (
        ("observe", "identify a visible stove control and local surface normal", "control_visible"),
        ("approach", "move open gripper to visible control", "control_hover_reached"),
        ("align", "align own fingers to the visible control", "orientation_reached"),
        ("contact", "reach control contact pose", "control_contact_pose_reached"),
        ("grasp", "close on the visible control", "closure_executed"),
        ("turn", "apply bounded tangent motion around observed centre", "visible_rotation"),
        ("release", "open gripper and clear control", "opening_executed"),
        ("verify", "compare visible control/indicator before and after", "visible_change"),
    ),
}

ALLOWED_SOURCES = ("public_task", "agentview_rgbd", "wrist_rgbd",
                   "camera_calibration", "robot_proprioception", "own_robot_mesh",
                   "executed_action_history")
FORBIDDEN = ("reward", "success", "object_pose", "object_id", "bddl",
             "goal_predicate", "scene_state", "simulator_truth",
             "evaluator", "native_finish")


def stages(task_id: int) -> tuple[dict, ...]:
    plan = TASKS[task_id]
    sequence = []
    for part_index, primitive in enumerate(plan.primitives):
        phases = list(PHASES[primitive])
        if primitive == "open_drawer":
            phases.insert(1, ("select_handle",
                "separate visible handles and select requested world-height rank",
                "handle_unambiguous"))
        if primitive == "pick_place" and task_id in (1163, 1252):
            phases.insert(1, ("inspect_receiver",
                "measure a visible cabinet-top support polygon; do not extrapolate hidden top",
                "support_surface_visible"))
        if primitive == "pick_place" and task_id == 1202:
            phases.insert(1, ("reobserve_interior",
                "after opening, freshly measure the drawer mouth and interior bottom",
                "interior_visible"))
        if primitive == "push":
            phases.insert(1, ("choose_corridor",
                "measure a free table corridor from the plate to a patch in front of the stove",
                "collision_free_corridor"))
        if primitive == "pick_place" and task_id == 1458:
            phases = [
                ("align_opening",
                 "align the held bottle axis with a visibly measured rack entrance",
                 "opening_aligned") if name == "lower" else
                (name, contract, gate)
                for name, contract, gate in phases]
            insertion = next(i for i, row in enumerate(phases)
                             if row[0] == "align_opening") + 1
            phases.insert(insertion, ("insert",
                "advance incrementally through the visible opening with clearance checks",
                "visible_insertion"))
        sequence.extend(dict(id=f"{part_index}:{primitive}:{name}",
                             primitive=primitive, name=name, contract=contract,
                             gate=gate) for name, contract, gate in phases)
    return tuple(sequence)


def _finite_vec(value, size, label):
    if len(value) != size or any(not math.isfinite(float(v)) for v in value):
        raise ValueError(f"{label} must contain {size} finite numbers")
    return [float(v) for v in value]


def _public_only(value):
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in FORBIDDEN):
                raise ValueError(f"Privileged input field: {key}")
            _public_only(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _public_only(item)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite input measurement")


def decision_request(task_id: int, stage_id: str, *, tcp_xyz_m,
                     target_xyz_m, rotation_error_world_rad,
                     gripper_aperture_mm: float, last_gripper_command: str,
                     observed_evidence: dict, recent_actions: list,
                     native_tick: int) -> dict:
    """Build a model request from measurements provided by a vision adapter.

    The adapter must only supply rendered RGB-D/calibration, own robot feedback
    and history. A gate is an observation claim, never the native task checker.
    The model retains direction, gripper and phase-choice ownership.
    """
    plan = TASKS[task_id]
    sequence = stages(task_id)
    index = next((i for i, phase in enumerate(sequence)
                  if phase["id"] == stage_id), None)
    if index is None:
        raise ValueError(f"Unknown stage {stage_id} for task {task_id}")
    phase = sequence[index]
    operation_index = int(stage_id.split(":", 1)[0])
    source, destination, relation = (
        ("top drawer handle", "drawer opening", "open")
        if task_id == 1202 and operation_index == 0 else
        ("bowl", "open drawer interior", "inside")
        if task_id == 1202 and operation_index == 1 else
        (plan.source, plan.destination, plan.relation))
    current = _finite_vec(tcp_xyz_m, 3, "tcp_xyz_m")
    target = _finite_vec(target_xyz_m, 3, "target_xyz_m")
    rotation = _finite_vec(rotation_error_world_rad, 3,
                           "rotation_error_world_rad")
    if not math.isfinite(gripper_aperture_mm) or native_tick < 0:
        raise ValueError("Invalid gripper aperture or native tick")
    if last_gripper_command not in ("open", "close"):
        raise ValueError("last_gripper_command must be open or close")
    if not isinstance(observed_evidence, dict):
        raise ValueError("observed_evidence must be a dict")
    _public_only(observed_evidence)
    _public_only(recent_actions)
    sources = observed_evidence.get("sources")
    if not isinstance(sources, list) or not sources or any(
            source not in ALLOWED_SOURCES for source in sources):
        raise ValueError("Evidence must cite permitted observation sources")
    if observed_evidence.get("observed_native_tick") != native_tick:
        raise ValueError("Evidence must be current for this decision")
    gate = observed_evidence.get(phase["gate"])
    if gate not in (True, False, None):
        raise ValueError("Phase gate must be true, false or unknown")
    axes = {axis: dict(current_coordinate_m=current[j],
                       goal_coordinate_m=target[j],
                       goal_minus_current_mm=round((target[j]-current[j])*1000, 2),
                       relation=("within_tolerance" if abs(target[j]-current[j]) < .002
                                 else "goal_coordinate_larger" if target[j] > current[j]
                                 else "goal_coordinate_smaller"))
            for j, axis in enumerate("xyz")}
    next_stage = sequence[index+1]["id"] if index+1 < len(sequence) else "finish_attempt"
    state = dict(task=plan.language,
                 public_entity_slots=dict(source=source,
                                          destination=destination,
                                          relation=relation),
                 stage=stage_id,
                 next_stage=next_stage, stage_contract=phase["contract"],
                 translation_axes=axes,
                 required_rotation_world_rad=dict(zip(("rx", "ry", "rz"), rotation)),
                 gripper=dict(aperture_mm=gripper_aperture_mm,
                              last_command=last_gripper_command),
                 completion_evidence=observed_evidence,
                 recent_actions=recent_actions[-3:],
                 allowed_transitions=dict(continue_phase=True,
                                          advance=gate is True,
                                          reobserve=True,
                                          stop=True),
                 information_sources=list(ALLOWED_SOURCES))
    questions = {axis: dict(type="choice",
                            instructions=f"Select world {axis} direction toward the stage target; hold within 2 mm. Step size is external.",
                            criteria=dict(negative="Decrease coordinate",
                                          hold="No movement",
                                          positive="Increase coordinate"))
                 for axis in "xyz"}
    for axis, err in zip(("rx", "ry", "rz"), rotation):
        if abs(err) >= .03:
            questions[axis] = dict(type="choice",
                                   instructions=f"Select world {axis} rotation sign toward the stage orientation.",
                                   criteria=dict(negative="Negative rotation",
                                                 hold="No rotation",
                                                 positive="Positive rotation"))
    questions["gripper"] = dict(type="choice",
                                instructions="Select open, close, or keep for the current stage.",
                                criteria=dict(open="Open", close="Close",
                                              keep="Keep previous command"))
    choices = dict(continue_phase="Stay in current stage",
                   reobserve="Request a fresh permitted camera observation",
                   stop="End incomplete")
    if gate is True:
        choices["advance"] = "Advance after executing this decision"
    questions["transition"] = dict(type="choice",
                                   instructions="Advance only with current visible/proprioceptive gate evidence; choose independently of motion signs.",
                                   criteria=choices)
    return dict(model_role="jev_discrete", state=state, questions=questions)


def validate_choice_set(request: dict, answers: dict) -> None:
    """Prevent a parser from silently inventing an unasked model choice."""
    questions = request["questions"]
    if set(answers) != set(questions):
        raise ValueError("Model answer keys differ from requested questions")
    for key, question in questions.items():
        choice = answers[key]["choice"]
        if choice not in question["criteria"]:
            raise ValueError(f"Invalid {key} choice: {choice}")

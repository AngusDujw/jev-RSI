"""Small RGB-observed world-Y projection probe before another stack-block attempt.

This intentionally ends incomplete. It uses only current camera pixels and
measured EEF state; neither simulator object poses nor evaluator success are
sent to the Decisions model.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from controller import ARMS, DecisionClient, choice
from visual_context import detect_blocks, draw_reference

OFFSETS_M = (0.005, -0.005, 0.0)


def high_path(obs: dict) -> Path:
    return next(Path(item["path"]) for item in obs["images"]
                if item["camera"] == "cam_high")


def color_center(blocks: list[dict], color: str) -> list[float] | None:
    return next((block["center_px"] for block in blocks if block["color"] == color), None)


def questions(after_motion: bool) -> list[dict]:
    asked = [
        choice("target_visible", "Inspect the three CURRENT RGB views directly. Is the initial loose PURPLE target separately visible from the YELLOW support and the right fingers?",
               {"visible": "Purple target separately visible", "occluded": "Purple target hidden behind right arm or fingers", "uncertain": "Cannot identify the target reliably"}),
        choice("target_vs_right_fingers", "In CURRENT RGB, where is the purple target relative to the open RIGHT fingers? This is image-space evidence, not a world-axis action.",
               {"left": "Purple left of both fingers", "between": "Purple between both fingers", "right": "Purple right of both fingers", "hidden": "Cannot locate purple relative to fingers"}),
        choice("right_wrist_object", "Which colored block is directly recognizable in the CURRENT right-wrist RGB?",
               {"purple": "Purple target", "yellow": "Yellow support", "white": "White block", "none": "No colored block reliably visible"}),
    ]
    if after_motion:
        asked.append(choice("right_gripper_high_shift", "Compare CURRENT high RGB with the attached PREVIOUS high RGB. Which way did the RIGHT gripper move in high-camera pixels? Ignore apparent block motion and do not infer the world-Y sign from a single image.",
                           {"left": "Image left", "right": "Image right", "up": "Image up", "down": "Image down", "none": "No visible shift", "uncertain": "Cannot identify corresponding gripper parts"}))
    return asked


def evidence(obs: dict, origin: list[float], previous_eef: list[float] | None,
             offset_m: float | None, blocks: list[dict]) -> str:
    return json.dumps({
        "purpose": "small world-Y camera projection calibration, NOT a grasp or success verdict",
        "task": obs["task"], "instruction": obs["instruction"],
        "locked_visual_target": "initial high RGB purple loose block",
        "locked_visual_support": "initial high RGB yellow support block",
        "active_arm": "right", "world_frame": "fixed world XYZ, Z upward",
        "current_measured_eef": obs["current_eef"],
        "origin_right_eef_position_m": origin,
        "previous_right_eef_position_m": previous_eef,
        "previous_world_y_offset_command_m": offset_m,
        "current_high_rgb_color_regions_px": blocks,
        "step_id": obs["step_id"],
        "instruction_to_model": "Use CURRENT raw high, left-wrist, right-wrist RGB plus the labeled initial high. If a previous high is attached, compare visible right-gripper parts between the previous and current images. HSV color boxes are fallible pixel hints. No object pose, reward, contact, or success label is supplied.",
    }, ensure_ascii=False, separators=(",", ":"))


def action(obs: dict, origin: np.ndarray, offset_m: float) -> dict:
    target = {}
    for index, arm in enumerate(ARMS):
        measured = obs["current_eef"][arm]
        position = list(measured["position"])
        if arm == "right":
            position = origin.copy().tolist()
            position[1] += offset_m
        target[arm] = {
            "position": position,
            "quaternion_wxyz": measured["quaternion_wxyz"],
            "gripper_closed": False,
        }
    return {
        "request_id": obs["request_id"], "mode": "eef", "steps": 5,
        "reason": f"RGB Decisions v5 small Y projection probe; right arm offset={offset_m:+.3f}m; open fingers, no grasp",
        "target": target,
    }


def run_probe(tools, obs: dict, model: DecisionClient, output: Path) -> dict:
    import hybrid_rollout.robodojo.robodojo_server.gpt_only_client as native

    initial_high = high_path(obs)
    initial_blocks = detect_blocks(initial_high)
    if {item["color"] for item in initial_blocks} != {"purple", "yellow", "white"}:
        native_result = tools.finish("probe_initial_rgb_incomplete")
        return {"status": "probe_initial_rgb_incomplete", "native_result": native_result,
                "decisions": 0, "visual_queries": 0}
    reference = draw_reference(initial_high, output / "visual_context/probe_initial_labeled.png",
                               initial_blocks, "initial_left", "initial_middle")
    origin = np.asarray(obs["current_eef"]["right"]["position"], dtype=float)
    purple_initial = color_center(initial_blocks, "purple")
    previous_high: Path | None = None
    previous_eef: list[float] | None = None
    last_offset: float | None = None
    trace = []
    stop_reason = "y_projection_probe_incomplete"
    for index in range(len(OFFSETS_M) + 1):
        current_high = high_path(obs)
        blocks = detect_blocks(current_high)
        extra = ([{"camera": "previous_high_before_y_motion", "path": str(previous_high)}]
                 if previous_high is not None else [])
        answers = model.query(obs, questions(previous_high is not None),
                              evidence(obs, origin.tolist(), previous_eef, last_offset, blocks),
                              f"probe_view_{index:02d}", reference, extra)
        purple = color_center(blocks, "purple")
        entry = {"step_id": obs["step_id"], "right_eef": obs["current_eef"]["right"]["position"],
                 "purple_center_px": purple, "yellow_center_px": color_center(blocks, "yellow"),
                 "model_answers": answers}
        trace.append(entry)
        (output / "probe_y_trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2))
        if answers["target_visible"] != "visible" or purple is None:
            stop_reason = "probe_target_visibility_incomplete"
            break
        if purple_initial is not None and max(abs(purple[0] - purple_initial[0]),
                                               abs(purple[1] - purple_initial[1])) > 3:
            stop_reason = "probe_possible_block_motion_incomplete"
            break
        if index == len(OFFSETS_M):
            break
        offset = OFFSETS_M[index]
        response = action(obs, origin, offset)
        native.validate_action(response, tools.request)
        call = tools.next_call()
        call.pop("tool")
        call["response"] = response
        previous_high = current_high
        previous_eef = obs["current_eef"]["right"]["position"]
        last_offset = offset
        obs = tools.act(**call)
        entry["executed_action"] = response
        (output / "probe_y_trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2))
        if obs["rollout_finished"]:
            stop_reason = "probe_native_ended"
            break
    native_result = obs.get("result") if obs["rollout_finished"] else tools.finish(stop_reason)
    return {"status": "probe_complete_incomplete" if stop_reason == "y_projection_probe_incomplete"
            else stop_reason, "decisions": sum("executed_action" in item for item in trace),
            "visual_queries": len(trace), "native_result": native_result,
            "probe_trace": str(output / "probe_y_trace.json")}

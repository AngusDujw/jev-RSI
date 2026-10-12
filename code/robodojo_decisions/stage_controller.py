"""Visual evidence gate followed by one arm's bounded Decisions action."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from controller import AXES, ARMS, ROTATIONS, SIZES, DecisionClient, choice

GATES = {
    "observe_blocks": "At least one loose block and a distinct block that can support it are clearly visible in current RGB; all three blocks need not be unoccluded.",
    "select_arm": "One arm has a visible collision-free approach to a named loose block; identify that arm, target and supporting block in the choices below.",
    "approach": "The chosen OPEN gripper is visibly near its loose target block, within roughly one gripper width, and ready for fine alignment.",
    "align": "Fresh high RGB shows the LOCKED target visibly inside the OPEN active finger gap near the finger tips; its height is plausible from the wrist and measured hand pose. A yellow support in the right wrist view is not evidence that the purple target is held.",
    "reobserve": "The LOCKED target and distinct support are separately identifiable in fresh RGB, and the target can be located relative to both open fingers after withdrawal.",
    "grasp": "After gripper closure AND a small test lift, the SAME target block visibly moves upward with the gripper and stays between the fingers. Closure alone fails this test.",
    "lift": "The gripped target block is visibly lifted clear of its prior table or stack support and remains held.",
    "move_to_stack": "The visibly held target block is centered above the selected supporting block or existing stack in at least two views.",
    "place": "The held target has been lowered onto the supporting block or stack and visually remains supported there.",
    "release": "After the fingers open, the target remains visibly on the supporting block or stack instead of falling or following the gripper.",
    "retreat": "The open gripper is visibly clear of the stack and no block is visibly moving or falling.",
    "verify": "All THREE differently textured blocks are visibly stacked and stable in current RGB, regardless of their ordering.",
    "return_home": "Both measured LINK6 positions are within 0.15 m of their starting positions, their rotations are within 20 degrees, and both grippers are open; the three-block stack remains visible and stable.",
}
NEXT = {
    "observe_blocks": "select_arm", "select_arm": "approach", "approach": "align",
    "align": "grasp", "reobserve": "align", "grasp": "lift", "lift": "move_to_stack",
    "move_to_stack": "place", "place": "release", "release": "retreat",
    "retreat": "verify", "verify": "return_home", "return_home": "return_home",
}
NO_MOTION = {"observe_blocks", "select_arm", "verify"}
DIRECTIONS = {
    "hold": (0, 0, 0), "x_negative": (-1, 0, 0), "x_positive": (1, 0, 0),
    "y_negative": (0, -1, 0), "y_positive": (0, 1, 0),
    "z_negative": (0, 0, -1), "z_positive": (0, 0, 1),
    "x_negative_y_negative": (-1, -1, 0),
    "x_negative_y_positive": (-1, 1, 0),
    "x_positive_y_negative": (1, -1, 0),
    "x_positive_y_positive": (1, 1, 0),
}
BLOCK_IDS = ("initial_left", "initial_middle", "initial_right")
BLOCK_DESCRIPTIONS = {
    "initial_left": "initial high-view leftmost block",
    "initial_middle": "initial high-view middle block",
    "initial_right": "initial high-view rightmost block",
}
PICK_BASE_PAIRS = {
    f"{pick}__{base}": f"Pick {BLOCK_DESCRIPTIONS[pick]}; support on distinct {BLOCK_DESCRIPTIONS[base]} or its existing stack"
    for pick in BLOCK_IDS for base in BLOCK_IDS if pick != base
}


def gate_questions(stage: str) -> list[dict]:
    questions = [choice("gate", "Assess ONLY the current stage from fresh RGB and measured robot state. PASS only with the specified visible evidence. CONTINUE if reachable but unfinished. RECOVER if an attempted grasp/placement failed or the target was lost. UNCERTAIN for insufficient visibility. Do not treat a prior command as evidence it succeeded.",
        {"pass": GATES[stage], "continue": "Stage not complete; target and active arm remain identifiable",
         "recover": "Task geometry or grasp failed; a previous stage must be retried",
         "uncertain": "Current views do not support a reliable stage verdict"}),
        choice("evidence_view", "Which fresh RGB view(s) show the strongest DIRECT evidence for the gate choice?",
            {"high": "High camera", "left_wrist": "Left wrist camera", "right_wrist": "Right wrist camera",
             "multiple": "At least two cameras", "none": "No clear visual evidence"})]
    if stage == "select_arm":
        questions.extend([
            choice("active_arm", "Choose the arm with the clearest visible approach to ONE loose block. The other arm stays still.",
                   {"left": "Left", "right": "Right"}),
            choice("pick_base_pair", "Choose a visually feasible LOOSE target and DISTINCT supporting block from the INITIAL high-camera reference. Track texture identity in the current views. If two blocks are already stacked, choose its visible top as support.",
                   PICK_BASE_PAIRS),
        ])
    if stage == "reobserve":
        questions.extend([
            choice("target_visibility", "Using fresh RGB and the labeled INITIAL high reference, is the LOCKED loose target distinct from the supporting block? Do not substitute the support for the target.",
                   {"visible": "Target block is directly visible", "occluded": "Target location is hidden by the robot", "uncertain": "Identity cannot be resolved"}),
            choice("target_vs_fingers", "In the current high or active wrist RGB, where is the LOCKED target relative to the OPEN active fingers? This is image geometry, not a world-axis command.",
                   {"left": "Visible left of both fingers", "between": "Visible between both fingers", "right": "Visible right of both fingers", "hidden": "Cannot locate target relative to both fingers"}),
        ])
    return questions


def motion_questions(stage: str, augmented: bool = False,
                     geometry_cue: bool = False,
                     horizontal_error_px: float | None = None,
                     allowed_directions: tuple[str, ...] | None = None) -> list[dict]:
    allowed = DIRECTIONS
    if stage == "grasp":
        allowed = {key: value for key, value in DIRECTIONS.items() if key in ("hold", "z_positive")}
    elif augmented and stage in ("approach", "align"):
        allowed = {key: value for key, value in DIRECTIONS.items() if key != "hold"}
    if horizontal_error_px is not None and abs(horizontal_error_px) > 5:
        allowed = {key: value for key, value in allowed.items()
                   if value[0] == 0 or value[0] * horizontal_error_px > 0}
    if allowed_directions is not None:
        allowed = {key: value for key, value in allowed.items()
                   if key in allowed_directions}
    asked = [
        choice("direction", f"For the LOCKED active arm at stage {stage}, choose one bounded WORLD XYZ direction toward the visible target. Choose hold if only gripper change is needed. Do not move the inactive arm. " +
               ("Use the RGB-derived target-to-finger pixel error and measured world-axis image probes in the text; image vertical error mixes world Y and Z, so inspect wrist RGB and height too. " if geometry_cue else ""),
               {key: f"World XYZ sign {vector}" for key, vector in allowed.items()}),
        choice("size", "Choose translation length for this one feedback motion. Use fine around contact and never assume the commanded pose was reached. If the image-derived target is still more than 15 pixels outside the fingers and free space is visible, choose medium or long rather than repeating fine X motions.",
               {key: f"{value * 1000:g} mm" for key, value in SIZES.items()}),
    ]
    if not (geometry_cue and stage in ("approach", "align")):
        asked.append(choice("rotation", "Choose one small world orientation correction, or hold, based on visible gripper geometry.",
                            {key: key for key in ROTATIONS}))
    return asked


def rot_distance(a: list[float], b: list[float]) -> float:
    qa = Rotation.from_quat(np.asarray(a)[[1, 2, 3, 0]])
    qb = Rotation.from_quat(np.asarray(b)[[1, 2, 3, 0]])
    return float((qa * qb.inv()).magnitude())


class StageController:
    def __init__(self, client: DecisionClient, initial_obs: dict, plan: dict,
                 augmented: bool = False, reobserve: bool = False,
                 geometry_cue: bool = False, sign_gate: bool = False,
                 staged_micro: bool = False, recovery_sweep: bool = False,
                 y_probe: bool = False):
        self.client = client
        self.plan = plan
        self.augmented = augmented
        self.reobserve = reobserve
        self.geometry_cue = geometry_cue
        self.sign_gate = sign_gate
        self.staged_micro = staged_micro
        self.recovery_sweep = recovery_sweep
        self.y_probe = y_probe
        self.stage = "observe_blocks"
        self.active_arm: str | None = None
        self.target_id: str | None = None
        self.base_id: str | None = None
        self.initial_eef = initial_obs["current_eef"]
        self.raw_reference = next(Path(item["path"]) for item in initial_obs["images"] if item["camera"] == "cam_high")
        self.reference = self.raw_reference
        self.block_reference: list[dict] = []
        if augmented:
            from visual_context import detect_blocks, draw_reference
            detected = detect_blocks(self.raw_reference)
            if len(detected) == 3:
                self.block_reference = detected
                self.reference = draw_reference(self.raw_reference,
                    client.output.parent / "visual_context/initial_labeled.png", detected)
        self.phase_calls = 0
        self.motion_calls = 0
        self.events: list[dict] = []
        self.target_missing = 0
        self.reobserve_cycles = 0
        self.reobserve_actions = 0
        self.align_actions = 0
        self.stalled_reason: str | None = None
        self.pending_x_error_abs: float | None = None
        self.x_no_progress_count = 0
        self.horizontal_confirmations = 0
        self.pending_micro: dict | None = None
        self.micro_no_progress_count = 0
        self.last_x_sign = 0
        self.y_probe_actions = 0

    def _current_colors(self, obs: dict) -> set[str]:
        if not self.augmented:
            return set()
        from visual_context import detect_blocks
        high = next(Path(item["path"]) for item in obs["images"] if item["camera"] == "cam_high")
        return {item["color"] for item in detect_blocks(high)}

    def _locked_colors(self) -> tuple[str | None, str | None]:
        by_id = {item["id"]: item["color"] for item in self.block_reference}
        return by_id.get(self.target_id), by_id.get(self.base_id)

    def _high_geometry(self, obs: dict) -> dict | None:
        if not self.geometry_cue or self.active_arm != "right" or not self.target_id:
            return None
        from visual_context import detect_blocks, track_right_gripper
        current_high = next(Path(item["path"]) for item in obs["images"]
                            if item["camera"] == "cam_high")
        tracked = track_right_gripper(self.raw_reference, current_high)
        target_color, _ = self._locked_colors()
        target = next((item for item in detect_blocks(current_high)
                       if item["color"] == target_color), None)
        if target is not None:
            x, y = target["center_px"]
            left, right = tracked["estimated_inner_finger_x_px"]
            tip_y = tracked["estimated_finger_tip_y_px"]
            tracked.update({
                "locked_target_center_px": [x, y],
                "locked_target_mask_area_px": int(target["mask_area_px"]),
                "target_minus_finger_gap_center_px": [round(x - (left + right) / 2, 1),
                                                       round(y - tip_y, 1)],
                "target_inside_inner_finger_gap_x": bool(left + 8 <= x <= right - 8),
                "target_near_finger_tip_y": bool(abs(y - tip_y) <= 12),
            })
        else:
            tracked["locked_target_center_px"] = None
        initial_z = float(self.initial_eef["right"]["position"][2])
        current_z = float(obs["current_eef"]["right"]["position"][2])
        tracked["right_eef_z_change_from_initial_mm"] = round((current_z - initial_z) * 1000, 1)
        tracked["empirical_axes_from_RGB_probes"] = {
            "+world_X": "gripper moves high-image right, roughly 0.5 px/mm in this local view",
            "+world_Y": "gripper moves high-image up, roughly 0.7 px/mm in this local view",
            "warning": "Image vertical motion also responds to world Z; this local projection is not an object pose or depth estimate.",
        }
        return tracked

    def _evidence(self, obs: dict, recent: list[dict], purpose: str) -> str:
        state = {
            "task": obs["task"], "instruction": obs["instruction"], "purpose": purpose,
            "current_stage": self.stage, "stage_pass_criterion": GATES[self.stage],
            "active_arm": self.active_arm, "target_initial_high_rank": self.target_id,
            "support_initial_high_rank": self.base_id,
            "world_frame": "fixed RoboDojo world axes, Z upward; do not mistake image left/right for world X/Y",
            "end_effector": "LINK6 target; measured pose in meters, quaternion wxyz; gripper joint 0 closed, 1 open",
            "measured_eef": obs["current_eef"], "measured_joint_state": obs["current_state"],
            "initial_eef": self.initial_eef, "step_id": obs["step_id"],
            "remaining_native_steps": obs["remaining_steps"],
            "recent_executed_actions": recent[-4:], "recent_stage_events": self.events[-4:],
            "task_notes": self.plan.get("notes", []),
            "camera_instruction": "Inspect the current three RGB views directly. The fourth high view, if attached, is the initial block identity reference. Do not use hidden object state, reward, or a prior gripper command as grasp proof.",
        }
        if self.augmented:
            from visual_context import detect_blocks
            current_high = next(Path(item["path"]) for item in obs["images"]
                                if item["camera"] == "cam_high")
            detected = detect_blocks(current_high)
            color_by_id = {block["id"]: block["color"] for block in self.block_reference}
            state["rgb_only_extra_information"] = {
                "initial_ranked_color_boxes": self.block_reference,
                "target_color_from_initial_rgb": color_by_id.get(self.target_id),
                "support_color_from_initial_rgb": color_by_id.get(self.base_id),
                "current_color_regions_px": [
                    {key: block[key] for key in ("color", "bbox_xywh", "center_px", "mask_area_px")}
                    for block in detected],
                "limitations": "HSV color boxes are image-derived hints only; occlusion and robot materials can cause misses or false positives. Current left-to-right rank is NOT persistent identity.",
                "empirical_high_camera_axis": "In the preceding layout-0 pilot, +world X moved the right gripper toward IMAGE RIGHT in the high view. Recheck on fresh frames; do not infer Y/depth from this.",
                "align_guidance": ("Track the LOCKED target color rather than the support color. A hold may obtain a fresh confirmation frame."
                                   if self.staged_micro else
                                   "Track the LOCKED target color rather than the support color. In align, each micro-motion should reduce a visible gripper-target error; no zero-motion hold is offered."),
            }
            if self.reobserve:
                target_color, base_color = self._locked_colors()
                found = {item["color"] for item in detected}
                state["rgb_only_extra_information"].update({
                    "locked_target_detected_in_current_high": target_color in found if target_color else None,
                    "locked_support_detected_in_current_high": base_color in found if base_color else None,
                    "visibility_recovery_rule": ("If the target disappears, first raise open gripper in three Z+10 mm steps. If still hidden, retreat along the last X path in at most three 10 mm steps. Re-identify target in fresh RGB before approach."
                                                 if self.recovery_sweep else
                                                 "If the target disappears, preserve X and use only a 5 mm Z+ visibility probe, at most twice; stop if still hidden."
                                                 if self.staged_micro else
                                                 "If the target disappears behind the open gripper, briefly lift and withdraw toward the previously clear starting hand pose; visually re-identify target and support before further alignment. High-view color detection is fallible; inspect raw RGB yourself."),
                })
            if self.geometry_cue:
                state["rgb_only_extra_information"]["right_gripper_rgb_geometry"] = self._high_geometry(obs)
            if self.sign_gate:
                state["rgb_only_extra_information"]["horizontal_action_rule"] = (
                    "If the RGB target is more than 5 px left of the estimated right-finger gap, +world X options are excluded; if more than 5 px right, -world X options are excluded. " +
                    ("Y/Z is deferred until horizontal confirmation. " if self.staged_micro else "Y/Z choices remain available. ") +
                    "This is a visual sign check, not an object pose.")
            if self.staged_micro:
                state["rgb_only_extra_information"]["staged_motion_rule"] = (
                    "First reduce the target-to-finger horizontal RGB error with X only. " +
                    ("If occluded, raise up to 30 mm, then retreat X up to 30 mm, each in 10 mm steps to regain visibility. "
                     if self.recovery_sweep else
                     "If the target is occluded, preserve measured X progress and use at most two 5 mm Z+ visibility probes. ") +
                    ("At horizontal error <=8 px in two fresh observations, stop X and run one Y-3 mm RGB/EEF probe, "
                     "possibly followed by Y-2 mm only if the first improves the vertical error without moving the block."
                     if self.y_probe else
                     "Only after two reliable RGB observations at horizontal error <=5 px may Y/Z be considered; "
                     "each such action is capped at 5 mm and checked against measured EEF and fresh RGB."))
        return json.dumps(state, ensure_ascii=False, separators=(",", ":"))

    def inspect(self, obs: dict, recent: list[dict]) -> dict:
        if self.staged_micro and self.active_arm == "right" and self.stage in ("approach", "align", "reobserve"):
            geometry = self._high_geometry(obs)
            score = float(geometry["normalized_match_score"]) if geometry else 0.0
            target_seen = bool(geometry and geometry.get("locked_target_center_px"))
            if score < 0.80 and not (self.recovery_sweep and self.stage == "reobserve"):
                self.stalled_reason = "rgb_gripper_tracker_below_0_80"
            if self.recovery_sweep and self.stage == "reobserve" and geometry and (
                    float(geometry["right_eef_z_change_from_initial_mm"]) > 65):
                self.stalled_reason = "visibility_recovery_above_65mm_from_start"
            if self.pending_micro is not None:
                previous = self.pending_micro
                self.pending_micro = None
                before = np.asarray(previous["eef_position"], dtype=float)
                after = np.asarray(obs["current_eef"]["right"]["position"], dtype=float)
                measured_mm = float(np.linalg.norm(after - before) * 1000)
                if measured_mm < 1.0 or measured_mm > 9.0:
                    self.stalled_reason = f"micro_probe_measured_eef_outside_1_to_9_mm:{measured_mm:.1f}"
                if previous.get("purpose") == "y_probe" and not target_seen:
                    self.stalled_reason = "target_disappeared_after_y_probe"
                if target_seen and score >= 0.80:
                    errors = geometry["target_minus_finger_gap_center_px"]
                    improvement = abs(previous["vertical_error_px"]) - abs(float(errors[1]))
                    self.micro_no_progress_count = (0 if improvement >= 1.0
                                                    else self.micro_no_progress_count + 1)
                    if self.micro_no_progress_count >= 2:
                        self.stalled_reason = "vertical_rgb_error_not_improving_after_two_micro_moves"
                    if previous.get("purpose") == "y_probe":
                        before_center = np.asarray(previous["target_center_px"], dtype=float)
                        after_center = np.asarray(geometry["locked_target_center_px"], dtype=float)
                        block_shift = float(np.linalg.norm(after_center - before_center))
                        area_ratio = (float(geometry["locked_target_mask_area_px"]) /
                                      max(1.0, float(previous["target_mask_area_px"])))
                        if improvement < 1.0 or block_shift > 2.0 or area_ratio < 0.70:
                            self.stalled_reason = ("y_probe_rgb_rejected:"
                                                   f"improvement={improvement:.1f},"
                                                   f"block_shift={block_shift:.1f},area_ratio={area_ratio:.2f}")
                        elif self.y_probe_actions >= 2:
                            self.stalled_reason = "bounded_y_probe_complete_incomplete"
            if self.stage in ("approach", "align"):
                if target_seen and score >= 0.80:
                    horizontal = abs(float(geometry["target_minus_finger_gap_center_px"][0]))
                    self.horizontal_confirmations = (self.horizontal_confirmations + 1
                                                     if horizontal <= (8 if self.y_probe else 5) else 0)
                else:
                    self.horizontal_confirmations = 0
                    self.stage = "reobserve"
                    self.reobserve_cycles += 1
                    self.reobserve_actions = 0
            elif self.stage == "reobserve" and not target_seen and self.reobserve_actions >= (6 if self.recovery_sweep else 2):
                self.stalled_reason = ("target_hidden_after_bounded_lift_and_x_retreat" if self.recovery_sweep
                                       else "target_hidden_after_two_5mm_visibility_probes")
        if self.sign_gate and self.pending_x_error_abs is not None:
            geometry = self._high_geometry(obs)
            if geometry and geometry["usable"] and geometry.get("target_minus_finger_gap_center_px"):
                current = abs(float(geometry["target_minus_finger_gap_center_px"][0]))
                if current >= self.pending_x_error_abs - 0.5:
                    self.x_no_progress_count += 1
                else:
                    self.x_no_progress_count = 0
                if self.x_no_progress_count >= 2:
                    self.stalled_reason = "rgb_x_projection_not_improving"
            self.pending_x_error_abs = None
        if self.stalled_reason:
            event = {"step_id": obs["step_id"], "stage_before": self.stage,
                     "stage_after": self.stage, "verdict": "uncertain",
                     "raw_gate": None, "record": None, "stall_reason": self.stalled_reason}
            self.events.append(event)
            return event
        name = f"gate_{self.phase_calls:04d}"
        self.phase_calls += 1
        asked = gate_questions(self.stage)
        answer = self.client.query(obs, asked, self._evidence(obs, recent, "visual stage acceptance"),
                                   name, self.reference)
        old = self.stage
        verdict = answer["gate"]
        # A pass requires some direct camera evidence even for stages with measured-pose criteria.
        if verdict == "pass" and answer["evidence_view"] == "none":
            verdict = "uncertain"
        if self.stage == "select_arm" and verdict == "pass":
            self.active_arm = answer["active_arm"]
            self.target_id, self.base_id = answer["pick_base_pair"].split("__")
            if self.augmented and self.block_reference:
                from visual_context import draw_reference
                self.reference = draw_reference(self.raw_reference,
                    self.client.output.parent / "visual_context/target_and_base.png",
                    self.block_reference, self.target_id, self.base_id)
        if self.reobserve and self.stage in ("align", "reobserve"):
            target_color, base_color = self._locked_colors()
            colors = self._current_colors(obs)
            target_visible = target_color in colors if target_color else False
            support_visible = base_color in colors if base_color else False
            if self.stage == "align":
                if self.geometry_cue and verdict == "pass":
                    geometry = self._high_geometry(obs)
                    z_change = geometry.get("right_eef_z_change_from_initial_mm", 1000) if geometry else 1000
                    if not (geometry and geometry["usable"] and
                            geometry.get("target_inside_inner_finger_gap_x") and
                            geometry.get("target_near_finger_tip_y") and
                            -45 <= z_change <= 15):
                        verdict = "uncertain"
                    if self.staged_micro and (not geometry or
                            float(geometry["normalized_match_score"]) < 0.80 or
                            self.horizontal_confirmations < 2 or
                            not geometry.get("target_minus_finger_gap_center_px") or
                            abs(float(geometry["target_minus_finger_gap_center_px"][0])) >
                            (8 if self.y_probe else 5)):
                        verdict = "uncertain"
                self.target_missing = 0 if target_visible else self.target_missing + 1
                if verdict == "pass" and not target_visible:
                    verdict = "uncertain"
                if self.target_missing >= (1 if self.staged_micro else 2):
                    verdict = "continue"
                    self.stage = "reobserve"
                    self.reobserve_cycles += 1
                    self.reobserve_actions = 0
                    if self.reobserve_cycles > (4 if self.geometry_cue else 2):
                        self.stalled_reason = "repeated_target_occlusion"
            else:
                recovered = (target_visible and support_visible and
                             answer["target_visibility"] == "visible" and
                             answer["target_vs_fingers"] != "hidden")
                if verdict == "pass" and not recovered:
                    verdict = "uncertain"
                if recovered:
                    verdict = "pass"
                if self.reobserve_actions >= (6 if self.recovery_sweep else 2 if self.staged_micro else 3) and verdict != "pass":
                    self.stalled_reason = "target_unrecoverable_after_visibility_actions"
        if self.stage == "return_home" and verdict == "pass":
            for arm in ARMS:
                current = obs["current_eef"][arm]
                start = self.initial_eef[arm]
                distance = float(np.linalg.norm(np.asarray(current["position"]) - start["position"]))
                if distance > 0.15 or rot_distance(current["quaternion_wxyz"], start["quaternion_wxyz"]) > math.radians(20):
                    verdict = "continue"
            if any(float(obs["current_state"][index * 7 + 6]) < 0.8 for index in range(2)):
                verdict = "continue"
        if verdict == "pass" and self.stage != "return_home":
            self.stage = NEXT[self.stage]
        elif verdict == "recover":
            self.stage = {"grasp": "align", "lift": "observe_blocks",
                          "move_to_stack": "observe_blocks", "place": "move_to_stack",
                          "release": "observe_blocks", "retreat": "observe_blocks",
                          "verify": "observe_blocks"}.get(self.stage, self.stage)
        elif self.stage == "verify" and verdict == "continue":
            self.stage = "observe_blocks"
        if self.stage == "observe_blocks" and old != "observe_blocks":
            self.active_arm = self.target_id = self.base_id = None
        if old == "align" and self.stage == "grasp":
            self.align_actions = 0
        event = {"step_id": obs["step_id"], "stage_before": old, "stage_after": self.stage,
                 "verdict": verdict, "raw_gate": answer, "record": name}
        self.events.append(event)
        return event

    def action(self, obs: dict, recent: list[dict]) -> tuple[dict, dict]:
        if self.stage in NO_MOTION or self.active_arm not in ARMS:
            raise ValueError(f"No motion allowed at stage={self.stage}, arm={self.active_arm}")
        if self.stage == "return_home":
            self.active_arm = max(ARMS, key=lambda arm: float(np.linalg.norm(
                np.asarray(obs["current_eef"][arm]["position"]) - self.initial_eef[arm]["position"]))
                + 0.15 * rot_distance(obs["current_eef"][arm]["quaternion_wxyz"],
                                      self.initial_eef[arm]["quaternion_wxyz"]))
        name = f"move_{self.motion_calls:04d}"
        self.motion_calls += 1
        if self.stage == "reobserve":
            if self.recovery_sweep:
                if self.reobserve_actions < 3:
                    delta = np.asarray((0.0, 0.0, 0.010))
                    direction = "reobserve_z_positive_10mm"
                else:
                    if not self.last_x_sign:
                        raise ValueError("No measured X approach direction for bounded retreat")
                    delta = np.asarray((-self.last_x_sign * 0.010, 0.0, 0.0))
                    direction = "reobserve_reverse_x_10mm"
                answer = {"direction": direction, "size": "recovery_10mm", "rotation": "hold"}
            elif self.staged_micro:
                delta = np.asarray((0.0, 0.0, 0.005))
                answer = {"direction": "reobserve_z_positive_5mm", "size": "fine", "rotation": "hold"}
            elif self.reobserve_actions == 0:
                delta = np.asarray((0.0, 0.0, 0.015))
                answer = {"direction": "reobserve_lift", "size": "short", "rotation": "hold"}
            else:
                current = np.asarray(obs["current_eef"][self.active_arm]["position"])
                initial = np.asarray(self.initial_eef[self.active_arm]["position"])
                toward_start = initial - current
                toward_start[2] = 0
                length = float(np.linalg.norm(toward_start))
                delta = toward_start / length * min(length, 0.030) if length else toward_start
                answer = {"direction": "reobserve_to_initial_xy", "size": "medium", "rotation": "hold"}
            self.reobserve_actions += 1
            source = "bounded RGB visibility recovery"
        elif self.y_probe and self.stage in ("approach", "align") and self.active_arm == "right":
            geometry = self._high_geometry(obs)
            if not geometry or float(geometry["normalized_match_score"]) < 0.80 or not geometry.get("target_minus_finger_gap_center_px"):
                raise ValueError("Y probe requires a visible target and reliable RGB tracker")
            horizontal_error = abs(float(geometry["target_minus_finger_gap_center_px"][0]))
            if horizontal_error <= 8 and self.horizontal_confirmations == 1:
                delta = np.zeros(3)
                answer = {"direction": "hold_for_second_horizontal_rgb_frame", "size": "hold", "rotation": "hold"}
                source = "fresh RGB confirmation before Pro-guided Y probe"
            elif horizontal_error <= 8 and self.horizontal_confirmations >= 2:
                if self.y_probe_actions >= 2:
                    raise ValueError("Bounded Y probe already completed")
                distance = 0.003 if self.y_probe_actions == 0 else 0.002
                delta = np.asarray((0.0, -distance, 0.0))
                answer = {"direction": "y_negative_pro_probe", "size": f"{distance * 1000:g}mm", "rotation": "hold"}
                self.pending_micro = {
                    "purpose": "y_probe",
                    "eef_position": obs["current_eef"][self.active_arm]["position"],
                    "vertical_error_px": float(geometry["target_minus_finger_gap_center_px"][1]),
                    "target_center_px": geometry["locked_target_center_px"],
                    "target_mask_area_px": geometry["locked_target_mask_area_px"],
                }
                self.y_probe_actions += 1
                source = "Pro-guided single-axis RGB/EEF probe, at most 5mm total"
            else:
                answer = None
            if answer is None:
                answer, delta, source = self._model_motion(obs, recent, name)
        else:
            answer, delta, source = self._model_motion(obs, recent, name)
        arm = self.active_arm
        target = {}
        for index, hand in enumerate(ARMS):
            current = obs["current_eef"][hand]
            position = np.asarray(current["position"], dtype=float)
            old_q = np.asarray(current["quaternion_wxyz"], dtype=float)
            if hand == arm:
                position = position + delta
                axis, radians = ROTATIONS[answer["rotation"]]
                rotation = np.zeros(3)
                rotation[axis] = radians
                q = (Rotation.from_rotvec(rotation) * Rotation.from_quat(old_q[[1, 2, 3, 0]])).as_quat()
                old_q = q[[3, 0, 1, 2]]
            gripper_closed = bool(obs["current_state"][index * 7 + 6] < 0.5)
            if hand == arm:
                if self.stage in ("approach", "align", "release", "retreat", "return_home"):
                    gripper_closed = False
                elif self.stage in ("grasp", "lift", "move_to_stack", "place"):
                    gripper_closed = True
            if self.stage == "return_home":
                gripper_closed = False
            target[hand] = {"position": position.tolist(), "quaternion_wxyz": old_q.tolist(),
                            "gripper_closed": gripper_closed}
        result = {"request_id": obs["request_id"], "mode": "eef", "steps": 5,
                  "reason": f"RGB Decisions stage={self.stage}, arm={arm}, target={self.target_id}, base={self.base_id}; {source}",
                  "target": target}
        path = self.client.output / f"{name}.json"
        record = json.loads(path.read_text()) if path.exists() else {}
        record["action"] = result
        record["stage"] = self.stage
        record["active_arm"] = arm
        record["target_id"] = self.target_id
        record["base_id"] = self.base_id
        record["source"] = source
        record["decoded_answers"] = answer
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
        return result, answer

    def _model_motion(self, obs: dict, recent: list[dict], name: str) -> tuple[dict, np.ndarray, str]:
        geometry = self._high_geometry(obs) if self.sign_gate else None
        horizontal_error = (float(geometry["target_minus_finger_gap_center_px"][0])
                            if geometry and geometry["usable"] and
                            geometry.get("target_minus_finger_gap_center_px") else None)
        allowed_directions = None
        if self.staged_micro and self.stage in ("approach", "align"):
            if horizontal_error is None or float(geometry["normalized_match_score"]) < 0.80:
                raise ValueError("Staged RGB action requires a visible target and reliable gripper tracker")
            if abs(horizontal_error) > (8 if self.y_probe else 5) or self.horizontal_confirmations < 2:
                allowed_directions = ("hold", "x_negative" if horizontal_error < 0 else "x_positive")
            else:
                allowed_directions = ("hold", "y_negative", "y_positive", "z_negative", "z_positive")
        answer = self.client.query(obs, motion_questions(self.stage,
                                                          self.augmented and not self.staged_micro,
                                                          self.geometry_cue,
                                                          horizontal_error if self.stage in ("approach", "align") else None,
                                                          allowed_directions),
                                   self._evidence(obs, recent, "one bounded action for locked arm"),
                                   name, self.reference)
        answer.setdefault("rotation", "hold")
        vector = np.asarray(DIRECTIONS[answer["direction"]], dtype=float)
        norm = float(np.linalg.norm(vector))
        delta = vector / norm * SIZES[answer["size"]] if norm else vector
        source = "OpenAI Decisions RGB action"
        if self.staged_micro and self.stage in ("approach", "align"):
            if vector[1] or vector[2]:
                delta = vector * min(SIZES[answer["size"]], 0.005)
                self.pending_micro = {
                    "eef_position": obs["current_eef"][self.active_arm]["position"],
                    "vertical_error_px": float(geometry["target_minus_finger_gap_center_px"][1]),
                }
                source += "; Y/Z capped at 5mm with measured EEF/RGB acceptance"
            elif not norm:
                self.x_no_progress_count += 1
                if self.x_no_progress_count >= 2:
                    self.stalled_reason = "two_holds_before_rgb_alignment"
        if (self.sign_gate and self.stage in ("approach", "align") and
                vector[0] and horizontal_error is not None):
            self.pending_x_error_abs = abs(horizontal_error)
        if self.recovery_sweep and vector[0]:
            self.last_x_sign = int(np.sign(vector[0]))
        if self.reobserve and self.stage == "align":
            self.align_actions += 1
            if self.align_actions > (50 if self.geometry_cue else 16):
                self.stalled_reason = "align_action_budget_without_grasp"
        return answer, delta, source

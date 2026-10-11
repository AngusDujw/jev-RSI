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
    "align": "Two current camera views show the OPEN gripper straddling the target block at grasp height, without a visible collision.",
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
    "align": "grasp", "grasp": "lift", "lift": "move_to_stack",
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
    return questions


def motion_questions(stage: str, augmented: bool = False) -> list[dict]:
    allowed = DIRECTIONS
    if stage == "grasp":
        allowed = {key: value for key, value in DIRECTIONS.items() if key in ("hold", "z_positive")}
    elif augmented and stage in ("approach", "align"):
        allowed = {key: value for key, value in DIRECTIONS.items() if key != "hold"}
    return [
        choice("direction", f"For the LOCKED active arm at stage {stage}, choose one bounded WORLD XYZ direction toward the visible target. Choose hold if only gripper change is needed. Do not move the inactive arm.",
               {key: f"World XYZ sign {vector}" for key, vector in allowed.items()}),
        choice("size", "Choose translation length for this one feedback motion. Use fine around contact and never assume the commanded pose was reached.",
               {key: f"{value * 1000:g} mm" for key, value in SIZES.items()}),
        choice("rotation", "Choose one small world orientation correction, or hold, based on visible gripper geometry.",
               {key: key for key in ROTATIONS}),
    ]


def rot_distance(a: list[float], b: list[float]) -> float:
    qa = Rotation.from_quat(np.asarray(a)[[1, 2, 3, 0]])
    qb = Rotation.from_quat(np.asarray(b)[[1, 2, 3, 0]])
    return float((qa * qb.inv()).magnitude())


class StageController:
    def __init__(self, client: DecisionClient, initial_obs: dict, plan: dict,
                 augmented: bool = False):
        self.client = client
        self.plan = plan
        self.augmented = augmented
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
                "align_guidance": "Track the LOCKED target color rather than the support color. In align, each micro-motion should reduce a visible gripper-target error; no zero-motion hold is offered.",
            }
        return json.dumps(state, ensure_ascii=False, separators=(",", ":"))

    def inspect(self, obs: dict, recent: list[dict]) -> dict:
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
        answer = self.client.query(obs, motion_questions(self.stage, self.augmented),
                                   self._evidence(obs, recent, "one bounded action for locked arm"),
                                   name, self.reference)
        arm = self.active_arm
        vector = np.asarray(DIRECTIONS[answer["direction"]], dtype=float)
        norm = float(np.linalg.norm(vector))
        delta = vector / norm * SIZES[answer["size"]] if norm else vector
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
                  "reason": f"RGB Decisions v2 stage={self.stage}, arm={arm}, target={self.target_id}, base={self.base_id}",
                  "target": target}
        path = self.client.output / f"{name}.json"
        record = json.loads(path.read_text())
        record["action"] = result
        record["stage"] = self.stage
        record["active_arm"] = arm
        record["target_id"] = self.target_id
        record["base_id"] = self.base_id
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
        return result, answer

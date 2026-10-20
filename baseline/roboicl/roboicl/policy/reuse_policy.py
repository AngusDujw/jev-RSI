"""Paper-inspired, single-extra-segment Jev gate; no new robot actions.

The original gate prompt was not released. This reconstruction preserves the
published observation classes and 20-predict / 5+5-execute schedule, with no
confidence threshold invented from the paper. All robot guards remain active.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import time
import urllib.request

from .astra_policy import STATE_KEYS, plain
from .action_feedback import TrackingGuard, tracking_receipt
from .dialogue_policy import Model as DialogueModel


def image_free(value):
    from reproduction.pro_oauth_bridge import audit
    return audit(plain(value))


def jev_vote(state):
    path = Path(os.environ["ROBOICL_JEV_CONFIG"])
    config = json.loads(path.read_text())
    config = config.get("jev", config)
    key = os.environ.get(config.get("key_env", "TYPESAFE_API_KEY"))
    if not key:
        key_path = Path(config["key_file"])
        if not key_path.is_absolute():
            key_path = path.parent / key_path
        key = key_path.read_text().strip()
    request = {"model": config.get("model", "jev-1.13"), "state": state, "questions": {
        "reuse": {"type": "choice", "instructions":
            "Decide whether to reuse the next five actions of the existing GPT proposal. "
            "Use only the plan note, robot proprioception, issued commands and tracking receipts. "
            "Arm joints are radians; EE poses use environment-origin positions in meters "
            "and world-aligned quaternions [w,x,y,z]. Gripper values are previous normalized "
            "commands (0 closed, 1 open), not measured aperture or grasp success. "
            "Tracking does not establish grasp success or task progress. "
            "Choose replan when feedback contradicts the plan, execution was interrupted, "
            "or a fresh observation and plan are needed. Do not generate or modify actions.",
            "criteria": {"reuse": "Continue one additional five-action segment from the same proposal.",
                         "replan": "Discard the unexecuted suffix and request a fresh GPT proposal."}}}}
    from reproduction.pro_oauth_bridge import check_english
    check_english(request)
    wire = json.dumps(request).encode()
    url = config["base_url"].rstrip("/") + "/systemone"
    call = urllib.request.Request(url, data=wire, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    start = time.monotonic()
    with urllib.request.urlopen(call, timeout=config.get("timeout_s", 60)) as reply:
        response = json.load(reply)
    choice = response.get("answers", {}).get("reuse", {}).get("choice")
    if choice not in ("reuse", "replan") or not response.get("model", "").startswith("jev-"):
        raise ValueError("Invalid Jev reuse response or model")
    return choice, {"request": request, "response": response, "elapsed_s": time.monotonic()-start}


class Model(DialogueModel):
    def __init__(self, cfg):
        super().__init__(cfg)
        if os.environ.get("ROBOICL_REUSE_MODE", "pure") == "jev":
            if self.dialogue_config.execute_horizon != 5 or self.dialogue_config.predict_horizon != 20:
                raise ValueError("The reconstructed paper gate requires 20-predict / 5+5-execute")
            contract = "execute at most 5."
            if self.prompt.count(contract) != 1:
                raise ValueError("Released execution contract changed; review the reuse prompt")
            self.prompt = self.prompt.replace(contract, "execute at most 10.", 1)
            self._log("reuse_contract.jsonl", {"initial_dispatch": 5, "maximum_execution": 10,
                "prompt_change": "Execution upper bound changed from five to ten; all other released text retained."})

    def reset(self):
        super().reset()
        self.reuse_suffix = []
        self.reuse_checked = False

    def execution_context(self):
        pending = self.pending or {}
        return {"call_id": pending.get("call_id"), "kind": pending.get("kind", "act"),
                "start": pending.get("start", self.step)}

    def _prefix_allows_reuse(self, records):
        if len(records) != 5 or any(row.get("controller_event") for row in records):
            return False
        if os.environ.get("ASTRA_TRACKING_GUARD", "1") == "1":
            guard = TrackingGuard()
            for row in records:
                receipt = tracking_receipt(row["executed_action"], self.archive[row["resulting_step"]]["state"])
                if guard.observe(receipt):
                    return False
        return True

    def _log(self, name, value):
        # The in-memory action dialogue retains its images; only disk logs are scrubbed.
        super()._log(name, image_free(value))

    def _get_action_once(self, allow_correction=False):
        result = super()._get_action_once(allow_correction=allow_correction)
        self.reuse_suffix = []
        self.reuse_checked = False
        if (result is not None and self.pending and "call_id" in self.pending
                and self.pending["start"] == self.step and self.decisions
                and self.decisions[-1]["step"] == self.step):
            all_actions = self._convert_tensor(self.decisions[-1]["requested_tensor"], self.archive[self.step]["state"])
            self.reuse_suffix = all_actions[len(result):]
        return result

    def get_action(self):
        pending = self.pending
        if (os.environ.get("ROBOICL_REUSE_MODE", "pure") == "jev"
                and pending and "call_id" in pending and not self.reuse_checked
                and len(self.reuse_suffix) >= 5):
            self.reuse_checked = True
            executed = self.step - pending["start"]
            if (executed == pending["returned"] == 5
                    and "controller_rejection" not in pending):
                records = [row for row in self.ledger if pending["start"] < row["resulting_step"] <= self.step]
                if not self._prefix_allows_reuse(records):
                    self._log("reuse_guard_rejections.jsonl", {"proposal_start": pending["start"],
                        "step": self.step, "reason": "Incomplete prefix or released tracking guard requires replanning."})
                    return super().get_action()
                state = {
                    "plan_note": pending["execution_note"],
                    "proposal_start_step": pending["start"], "current_step": self.step,
                    "robot_proprioception": {key: plain(self.archive[self.step]["state"][key]) for key in STATE_KEYS},
                    "execution_tracking": [tracking_receipt(row["executed_action"], self.archive[row["resulting_step"]]["state"]) for row in records],
                    "executed_commands": [plain(row["executed_action"]) for row in records],
                    "proposed_suffix_commands": plain(self.reuse_suffix[:5]),
                }
                self._log("reuse_attempts.jsonl", {"proposal_start": pending["start"], "step": self.step})
                try:
                    choice, audit = jev_vote(state)
                except Exception as error:
                    self._log("reuse_errors.jsonl", {"proposal_start": pending["start"], "step": self.step,
                        "error_type": type(error).__name__, "error": str(error)[:600]})
                    raise
                self._log("reuse_votes.jsonl", {"proposal_start": pending["start"], "step": self.step, "choice": choice, **audit})
                if choice == "reuse":
                    result = deepcopy(self.reuse_suffix[:5])
                    self.reuse_suffix = []
                    # One original tool result now covers the entire executed prefix.
                    pending["returned"] += len(result)
                    self._log("reuse_dispatch.jsonl", {"call_id": pending["call_id"], "step": self.step, "actions": result})
                    return result
        return super().get_action()

    def notify_action_rejection(self, obs):
        # The simulator indexes each dispatched segment from zero. The original
        # pending tool call spans both segments, so normalize its suffix index.
        obs = deepcopy(obs)
        if (self.reuse_checked and self.pending
                and self.pending.get("returned") == 10
                and self.step - self.pending["start"] >= 5):
            obs["event"]["action_index"] += 5
        return super().notify_action_rejection(obs)

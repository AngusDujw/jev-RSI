"""Observable, timestamped evidence for program-internal classification.

No simulator handle is accepted. Measurements are public robot API results;
program context is labeled separately and cannot replace those observations.
"""
from __future__ import annotations

from collections import deque
from dataclasses import fields, is_dataclass
import hashlib
import json
import math
import re
import unicodedata


class JudgmentServiceError(RuntimeError):
    """No valid model judgment exists; no physical branch may be inferred."""


def plain(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return round(value, 6) if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items() if k not in ("masks", "pixels", "image", "depth")}
    if isinstance(value, (tuple, list, deque)):
        return [plain(v) for v in value[:24]] if not isinstance(value, deque) else plain(list(value))
    if is_dataclass(value):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)
                if f.name not in ("masks", "pixels", "image", "depth", "candidates", "notes")}
    if hasattr(value, "shape") and hasattr(value, "tolist"):
        return plain(value.tolist()) if value.size <= 32 else {"omitted_array_shape": list(value.shape)}
    if hasattr(value, "item"):
        return plain(value.item())
    raise ValueError("Unsupported evidence value: " + type(value).__name__)


def ascii_wire(value):
    """Normalize display glyphs only; refuse CJK rather than silently translating."""
    if isinstance(value, dict):
        return {ascii_wire(k): ascii_wire(v) for k, v in value.items()}
    if isinstance(value, list):
        return [ascii_wire(v) for v in value]
    if not isinstance(value, str) or value.startswith("data:image/"):
        return value
    if re.search(r"[\u3400-\u9fff]", value):
        raise ValueError("Model inputs must be English")
    for a, b in (("±", "+/-"), ("°", " deg"), ("→", "->"), ("×", "x"),
                 ("−", "-"), ("—", " - "), ("–", "-"), ("’", "'"), ("‘", "'"),
                 ("“", '"'), ("”", '"'), ("…", "...")):
        value = value.replace(a, b)
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()


class Evidence:
    def __init__(self):
        self.events = deque(maxlen=18)
        self.measurements = deque(maxlen=24)

    def add(self, name, result, *, step, proprio, error=None):
        if name not in ("measure", "to_world", "goto", "arc", "gripper", "home", "wait"):
            return
        row = dict(call=name, step=step, robot=plain(proprio))
        if error is not None:
            row["error"] = str(error)[:800]
        elif result is not None:
            row["result"] = plain(result)
        self.events.append(row)
        if name == "measure" and result is not None:
            self.measurements.append(row)

    def snapshot(self, *, step, instruction, proprio):
        rows = [dict(row, age_steps=max(0, step - row["step"])) for row in self.events]
        temporal = []
        by_label = {}
        for row in self.measurements:
            obj = row.get("result", {})
            label, center = obj.get("label"), obj.get("center_xyz")
            if not label or not obj.get("found") or center is None:
                continue
            old = by_label.get(label)
            if old and row["step"] > old["step"]:
                a, b = old["result"]["center_xyz"], center
                p, q = old["robot"]["tcp"], row["robot"]["tcp"]
                delta = [b[i] - a[i] for i in range(3)]
                hand = [q[i][3] - p[i][3] for i in range(3)]
                temporal.append(dict(label=label, from_step=old["step"], to_step=row["step"],
                    age_steps=max(0, step-row["step"]), object_delta_m=delta, tcp_delta_m=hand,
                    relative_delta_m=[delta[i]-hand[i] for i in range(3)],
                    source="Difference of two SAM3/RGB-D surface measurements; correspondence is not guaranteed"))
            by_label[label] = row
        return plain(dict(schema="hexashell-jev-evidence-v1", step=step,
            instruction=instruction, frame="fixed arm base; metres; TCP rotation matrix",
            robot=proprio, observation_history=rows, temporal_measurements=temporal[-8:],
            limitations=["No raw images, object ground truth, contact forces or native success signal",
                "Gripper holding is a width heuristic, not proof of intended-object retention",
                "Measured centers describe visible surfaces; occlusion and correspondence can shift them",
                "Age is native motion steps, not a guarantee that a prior object observation is current"]))


def validate_question(question, options, context):
    if not isinstance(question, str) or not 1 <= len(question) <= 1800:
        raise ValueError("question must be 1..1800 English characters")
    if not isinstance(options, dict) or not 2 <= len(options) <= 12 or "unknown" not in options:
        raise ValueError("options must have 2..12 branches including unknown")
    for key, desc in options.items():
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", key):
            raise ValueError("branch names use lowercase ASCII identifiers")
        if not isinstance(desc, str) or not 1 <= len(desc) <= 800:
            raise ValueError("each branch needs an English description of at most 800 characters")
    packet = dict(question=question, options=options, context=plain(context))
    ascii_wire(packet)
    if len(json.dumps(packet)) > 16000:
        raise ValueError("question and context exceed 16000 characters")
    return packet


class Decisions:
    def __init__(self, backend, bridge, output, *, pro_submit, post, max_calls=40):
        self.backend, self.bridge, self.output = backend, bridge.rstrip("/"), output
        self.pro_submit, self.post = pro_submit, post
        self.max_calls, self.count = max_calls, 0

    def choose(self, evidence, question, options, context=None):
        spec = validate_question(question, options, context)
        from run_gpt_jev_program import model_wire_numbers
        # Normalize once before either backend. GPT embeds this as JSON text,
        # whereas JEV receives structured JSON; both must see identical values.
        evidence = model_wire_numbers(ascii_wire(evidence))
        if self.count >= self.max_calls:
            raise RuntimeError("Local judgment budget exhausted")
        ident = self.count
        self.count += 1
        instructions = ("Select one local robot-policy branch using the supplied observations. "
            "Program context describes intent, never independent evidence. Distinguish measured "
            "feedback from requested commands and heuristics. Use unknown when evidence is missing, "
            "stale or contradictory for this question. Do not invent visual or contact observations. "
            "Confidence is distribution concentration, not correctness. Question: " + question)
        state = dict(observations=evidence, program_context=spec["context"],
                     context_source="GPT-authored policy; not an independent sensor")
        folder = self.output / f"decision-{ident:03d}"
        if self.backend == "jev":
            request = ascii_wire(dict(model="jev-1.13.0", state=state, questions=dict(
                branch=dict(type="choice", instructions=instructions, criteria=options))))
            try:
                raw = self.post(self.bridge + "/systemone", request, folder, timeout=300)
            except Exception as exc:
                raise JudgmentServiceError(type(exc).__name__ + ": " + str(exc)[:600]) from exc
            answer = raw.get("answers", {}).get("branch", {})
            choice = answer.get("choice")
            if raw.get("model") != "jev-1.13.0":
                raise JudgmentServiceError("JEV returned an unexpected model")
        else:
            schema = dict(type="object", properties=dict(choice=dict(type="string", enum=list(options))),
                          required=["choice"], additionalProperties=False)
            try:
                answer, raw = self.pro_submit("submit_judgment", schema, instructions,
                    [dict(type="input_text", text=json.dumps(ascii_wire(dict(state=state, options=options))))], folder)
            except Exception as exc:
                raise JudgmentServiceError(type(exc).__name__ + ": " + str(exc)[:600]) from exc
            choice = answer.get("choice")
        if choice not in options:
            raise JudgmentServiceError("Judgment returned an undeclared branch")
        receipt = dict(decision_id=ident, backend=self.backend, choice=choice,
            evidence_step=evidence["step"], evidence_sha256=hashlib.sha256(
                json.dumps(evidence, sort_keys=True).encode()).hexdigest(),
            model=raw.get("model"), confidence=answer.get("confidence"),
            probabilities=answer.get("probabilities"), usage=raw.get("usage"))
        (self.output / f"decision-{ident:03d}.receipt.json").write_text(json.dumps(receipt, indent=2)+"\n")
        return receipt

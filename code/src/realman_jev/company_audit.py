"""Post-hoc conservative action audit. Never imported by the policy process."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import re

import numpy as np


def resolve_target(row, projection_validated):
    name = row["declaration"]["target"]
    objects = row["before"]["objects"]
    exact = [obj for obj in objects if obj["id"] == name]
    if exact:
        return exact[0], "oracle_exact_id"
    evidence = row["declaration"]["evidence"]
    if not projection_validated or "views" not in evidence:
        return None, "no_validated_cross_modal_correspondence"
    for camera, view in evidence["views"].items():
        detections = [obj for obj in view["objects"] if obj["id"] == name]
        if not detections or camera not in row["before"].get("cameras", {}):
            continue
        detection = detections[0]
        calibration = row["before"]["cameras"][camera]
        world_to_camera = np.linalg.inv(np.asarray(calibration["camera_to_world"]))
        k = np.asarray(calibration["intrinsic"])
        origin = np.asarray(row["before"]["env_origin"])
        w, h = view["size"]
        x0, y0, x1, y1 = detection["bbox_uv01"]
        candidates = []
        for obj in objects:
            point = world_to_camera @ np.r_[np.asarray(obj["position_m"]).reshape(3) + origin, 1.]
            point = point[:3] * [1, -1, -1]  # USD/OpenGL camera -> optical axes.
            if point[2] <= 0:
                continue
            uv = (k @ point)[:2] / point[2] / [w, h]
            # A projected center inside a 2D box does not establish visibility.
            # Require unique physical candidate and matching visible category.
            category = str(obj.get("category", "")).lower().replace("_", " ")
            label = detection["label"].lower()
            category_words = {word.rstrip("s") for word in re.findall(r"[a-z]+", category)}
            label_words = {word.rstrip("s") for word in re.findall(r"[a-z]+", label)}
            if x0 <= uv[0] <= x1 and y0 <= uv[1] <= y1 and category_words & label_words:
                candidates.append(obj)
        if len(candidates) == 1:
            return candidates[0], "unique_projected_center_and_category_not_contact_proof"
        return None, f"ambiguous_projected_candidates:{len(candidates)}"
    return None, "target_missing"


def task_relevance(task, target, intent):
    label = str(target.get("audit_label", ""))
    category = str(target.get("category", ""))
    if intent not in {"approach", "align", "grasp", "lift"}:
        return "uncertain", "Destination/ordering/contact evidence requires task-specific review"
    if task == "general_pickup":
        return ("correct", "The uniquely instructed pickup target") if label == "target" else ("incorrect", "Different object from instructed pickup target")
    if task == "put_bottles_into_dustbin":
        if label.startswith("bottle") or category == "bottle":
            return "correct", "Any remaining bottle is an eligible pickup; progress checked separately"
        return "incorrect", "Pickup target is not a bottle"
    if task == "stack_blocks":
        if label.startswith("block_"):
            return "uncertain", "Block is eligible, but selecting an existing support may undo the stack"
        return "incorrect", "Target is not an instructed block"
    return "uncertain", "Task-specific order, target eligibility or support role not independently established"


def audit(row, task, projection_validated=False):
    out = dict(decision=row["decision"], start_tick=row["before"]["tick"], end_tick=row["after"]["tick"],
               requested=row["execution"]["requested"], executed=row["execution"].get("executed"),
               intent=row["declaration"]["intent"], target=row["declaration"]["target"],
               local="uncertain", task_relevance="uncertain", verdict="uncertain", rule="U0", evidence={})
    if not row["execution"]["ticks"] or out["executed"] == "hold":
        return dict(out, reason="No manipulation executed; abstention/transition is not proof of correctness")
    target, mapping = resolve_target(row, projection_validated)
    out["mapping"] = mapping
    if target is None:
        return dict(out, reason="Target cannot be mapped unambiguously to physical instance")
    after = next((o for o in row["after"]["objects"] if o["id"] == target["id"]), None)
    if after is None:
        return dict(out, reason="Target physical state unavailable after action")
    arm = 0 if out["executed"].startswith("left_") else 1
    p0 = np.asarray(target["position_m"]).reshape(3)
    p1 = np.asarray(after["position_m"]).reshape(3)
    r0 = np.asarray(row["before"]["robot"]["nominal_grasp_points_m"])[arm]
    r1 = np.asarray(row["after"]["robot"]["nominal_grasp_points_m"])[arm]
    d0, d1 = float(np.linalg.norm(p0-r0)), float(np.linalg.norm(p1-r1))
    out["physical_target"] = target["id"]
    out["evidence"] = dict(distance_before_m=d0, distance_after_m=d1,
        distance_change_m=d1-d0, object_delta_m=(p1-p0).tolist(), grasp_reference_delta_m=(r1-r0).tolist(),
        following_error_m=float(np.linalg.norm((p1-p0)-(r1-r0))),
        reference="Nominal robot-config grasp point; object origin; NOT confirmed finger contact")
    intent = out["intent"]
    if intent == "approach" and "_move_" in out["executed"]:
        # Measures literal local approach only. Increasing distance can be a
        # legitimate clearance maneuver; without path evidence do not mark wrong.
        if d1 < d0 - .002:
            out.update(local="correct", rule="A1", reason="Declared target approached by >2 mm at nominal grasp reference")
        else:
            out.update(rule="A2", reason="No >2 mm approach; avoidance or tracking error cannot be excluded")
    elif intent == "grasp" and out["executed"].endswith("_close"):
        out.update(rule="G1", reason="Finger contact/holding not established by closing alone")
    elif intent == "lift":
        if (p1-p0)[2] > .002 and (r1-r0)[2] > .002 and out["evidence"]["following_error_m"] < .006:
            out.update(local="correct", rule="L1", reason="Object and grasp reference rose together within 6 mm displacement residual")
        elif (r1-r0)[2] > .004 and abs((p1-p0)[2]) < .001:
            out.update(local="incorrect", rule="L2", reason="Hand rose >4 mm while declared object rose <1 mm; requested object lift did not occur")
        else:
            out.update(rule="L3", reason="Lift/following evidence inconclusive")
    else:
        out.update(rule="U1", reason="Requires validated contact, placement region, rotation or task-order evidence")
    relevance, reason = task_relevance(task, target, intent)
    out.update(task_relevance=relevance, task_reason=reason)
    if relevance == "incorrect" or out["local"] == "incorrect":
        out["verdict"] = "incorrect"
    elif relevance == "correct" and out["local"] == "correct":
        out["verdict"] = "correct"
    return out


def write_report(sim_dir, policy_dir, projection_validated=False):
    sim_dir, policy_dir = Path(sim_dir), Path(policy_dir)
    config = json.loads((policy_dir / "config.json").read_text())
    task = config["case"]["task"]
    path = sim_dir / "audit_only/decisions.jsonl"
    rows = [audit(json.loads(line), task, projection_validated) for line in path.read_text().splitlines()] if path.exists() else []
    covered = {row["decision"] for row in rows}
    events_path = policy_dir / "events.jsonl"
    if events_path.exists():
        for line in events_path.read_text().splitlines():
            event = json.loads(line)
            if event.get("kind") != "decision" or event["decision"] in covered:
                continue
            rows.append(dict(decision=event["decision"], start_tick=event["tick"], end_tick=None,
                requested=event["action"], executed=None, intent=event["intent"], target=event["target"],
                local="uncertain", task_relevance="uncertain", verdict="uncertain", rule="INFRA",
                evidence={}, reason="No verified post-action audit; execution outcome unavailable. Not a Jev action failure."))
    rows.sort(key=lambda row: row["decision"])
    (policy_dir / "decision-audit.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    columns = ["decision", "start_tick", "end_tick", "requested", "executed", "intent", "target", "local", "task_relevance", "verdict", "rule", "reason"]
    with (policy_dir / "decision-audit.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    counts = Counter(row["verdict"] for row in rows)
    decided = counts["correct"] + counts["incorrect"]
    result = dict(decisions=len(rows), counts=dict(counts), coverage=decided/len(rows) if rows else 0,
                  accuracy=counts["correct"]/decided if decided else None,
                  projection_validated=projection_validated,
                  local_counts=dict(Counter(row["local"] for row in rows)),
                  limitation="Conservative rule audit, not omniscient ground-truth action labels; report uncertainty and coverage")
    (policy_dir / "audit-summary.json").write_text(json.dumps(result, indent=2))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sim-dir", required=True)
    p.add_argument("--policy-dir", required=True)
    p.add_argument("--projection-validated", action="store_true")
    args = p.parse_args()
    print(json.dumps(write_report(args.sim_dir, args.policy_dir, args.projection_validated), indent=2))


if __name__ == "__main__":
    main()

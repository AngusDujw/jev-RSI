#!/usr/bin/env python3
"""Audit saved policy/decision cooperation without simulator access."""
from pathlib import Path
import argparse
import hashlib
import json


def audit(root):
    root = Path(root)
    result = json.loads((root / "result.json").read_text())
    impl = json.loads((root / "implementation.json").read_text())
    cells = [json.loads(s) for s in (root / "cells.jsonl").read_text().splitlines() if s]
    decisions, errors = [], []
    for path in sorted(root.glob("decision-*.receipt.json")):
        value = json.loads(path.read_text())
        request = json.loads(path.with_name(path.name.replace(".receipt", ".request")).read_text())
        backend = value["backend"]
        if backend == "jev":
            response = json.loads(path.with_name(path.name.replace(".receipt", ".response")).read_text())
            expected = response["answers"]["branch"]["choice"]
            evidence = request["state"]["observations"]
            expected_model = "jev-1.13.0"
            options = request["questions"]["branch"]["criteria"]
        else:
            response = json.loads(path.with_name(path.name.replace(".receipt", ".response")).read_text())
            packet = json.loads(request["input"][0]["content"][0]["text"])
            evidence = packet["state"]["observations"]
            expected = json.loads(response["output"][0]["arguments"])["choice"]
            expected_model = "gpt-6-astra"
            options = packet["options"]
        if (value["choice"] != expected or value["choice"] not in options or
                value["model"] != expected_model or value["evidence_step"] != evidence["step"]):
            errors.append("Decision receipt differs from model response: " + path.name)
        # post() rounds float wire inputs. Compare the actual wire evidence
        # timestamp/content separately from the pre-wire snapshot receipt hash.
        decisions.append(dict(**value, wire_evidence_sha256=hashlib.sha256(
            json.dumps(evidence, sort_keys=True).encode()).hexdigest()))
    called = sum(call["name"] == "decide" for cell in cells for call in cell["calls"])
    if len(decisions) > called:
        errors.append("More completed decisions than actual sandbox decide calls")
    return dict(record=str(root), success=result["success"], end=result["end"],
        steps=result.get("step"), planner_turns=result["turns"], backend=impl["judgment_backend"],
        phase=impl["phase"], decide_calls=called, completed_decisions=len(decisions),
        choices=[dict(decision_id=d["decision_id"], choice=d["choice"], evidence_step=d["evidence_step"])
                 for d in decisions], errors=errors,
        limitations="Checks saved request/answer/call consistency; does not independently prove physical predicates or causality")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("record", type=Path)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    report = audit(args.record)
    text = json.dumps(report, indent=2)+"\n"
    if args.output:
        args.output.write_text(text)
    print(text)
    return bool(report["errors"])


if __name__ == "__main__":
    raise SystemExit(main())

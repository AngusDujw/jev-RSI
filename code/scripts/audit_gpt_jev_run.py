"""Audit saved program-host v2 runs without models, physics or hidden state.

Check Jev-to-action consistency, GPT source origin, declared tool schemas,
unique full-request relay matches and known/unknown upstream token usage.
Observation truth and the terminal evaluator are not rerun by this tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from gpt_jev_contract import english, parse_jev
from gpt_jev_program_worker import validate_source
from gpt_jev_review_contract import validate_value
from run_gpt_jev_generic import scrub
from run_gpt_jev_program import apply_method_patch


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def ledger_index(path):
    result = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        try:
            item = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Incomplete ledger line {number} in {path.name}") from error
        require("request" in item, f"Ledger line {number} has no request")
        result.setdefault(digest(item["request"]), []).append(item)
    return result


def known_tokens(usage):
    """A missing component is unknown; reported numerical zero remains known."""
    if not isinstance(usage, dict):
        return None
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    if not all(type(x) is int and x >= 0 for x in (input_tokens, output_tokens)):
        return None
    return input_tokens, output_tokens


def check_native_origin(response, entry, answer, tool):
    native = entry.get("native_session", {})
    submitted = native.get("submission", {})
    calls = [x for x in response.get("output", []) if x.get("type") == "function_call"]
    require(len(calls) == 1 and native.get("completed") is True and
        native.get("thread_id") == response["transport"]["thread_id"] and
        submitted.get("arguments") == answer and submitted.get("tool") == tool and
        submitted.get("callId") == calls[0]["call_id"],
        "Native session envelope differs from validated dynamic-tool receipt")
    require(not native.get("instruction_sources"), "Native planner loaded instruction files")


def check_dispatch(request, response, receipt, previous_grip):
    choices = parse_jev(request, response)
    require(choices == receipt["choices"], "Dispatched choices differ from raw Jev response")
    features = request["state"]["processed_features"]
    actions = receipt["action"]
    require(len(actions) == 7 and all(type(x) in (int, float) and math.isfinite(x)
        for x in actions), "Invalid action vector")
    for i, axis in enumerate(("x", "y", "z", "rx", "ry", "rz")):
        expected = {"increase": "positive", "decrease": "negative",
            "within_tolerance": "hold"}[features["axes"][axis]["goal_relation"]]
        require(choices[axis] == expected, f"Jev semantic direction mismatch on {axis}")
        value = actions[i]
        require(value == 0 if choices[axis] == "hold" else value >= 0
            if choices[axis] == "positive" else value <= 0, f"Action sign mismatch on {axis}")
    require(choices["gripper"] == features["objective"]["gripper"], "Jev gripper objective mismatch")
    grip = previous_grip if choices["gripper"] == "keep" else {"open": -1, "close": 1}[choices["gripper"]]
    require(actions[6] == grip, "Carried gripper command mismatch")
    require(math.hypot(*actions[:3]) <= .400001, "Translation bound exceeded")
    require(math.hypot(*actions[3:6]) <= .200001, "Rotation bound exceeded")
    require(type(receipt["acknowledged_steps"]) is int and
        0 <= receipt["acknowledged_steps"] <= 3, "Invalid acknowledged-step count")
    return grip, receipt["acknowledged_steps"]


def audit_run(run, ledgers):
    summary, protocol = read(run / "summary.json"), read(run / "protocol.json")
    require(type(summary["native_success"]) is bool, "Missing terminal native outcome")
    steps, grip, dispatches = 0, -1, 0
    for path in sorted(run.glob("dispatch-*.json")):
        receipt = read(path)
        prefix = f"jev-{receipt['decision']:03d}"
        grip, count = check_dispatch(read(run / (prefix+".request.json")),
            read(run / (prefix+".response.json")), receipt, grip)
        steps += count
        dispatches += 1
    require(steps == summary["native_steps"], "Acknowledged steps disagree with native summary")
    strict, designs, legacy, usage, purpose, origins = 0, 0, 0, {}, {}, set()
    for kind in ("gpt", "jev"):
        totals = dict(attempts=0, unknown_usage=0, completed_input=0,
            completed_output=0, relay_seconds=0., matched_requests=0,
            undelivered_or_missing_responses=0, native_accounting_records=0)
        request_models, transport_hashes = set(), set()
        for path in sorted(run.glob(kind+"-*.request.json")):
            request = read(path)
            english(request)
            matches = ledgers[kind].get(digest(request), [])
            require(len(matches) == 1,
                f"{run.name}/{path.name}: expected one exact ledger match, found {len(matches)}")
            entry = matches[0]
            request_models.add(request["model"])
            if entry.get("transport_implementation_sha256"):
                transport_hashes.add(entry["transport_implementation_sha256"])
            totals["matched_requests"] += 1
            totals["relay_seconds"] += entry.get("elapsed_s", 0)
            group = None
            if kind == "gpt":
                tool = request["tool_choice"]["name"]
                group = purpose.setdefault(tool, dict(calls=0, upstream_attempts=0,
                    completed_returns=0, input=0, output=0, unknown_usage=0,
                    native_accounting_records=0))
                group["calls"] += 1
            for attempt in entry.get("upstream_attempts", [])+entry.get("native_accounting", []):
                native_record = attempt.get("kind", "").startswith("native_")
                totals["native_accounting_records" if native_record else "attempts"] += 1
                tokens = known_tokens(attempt.get("usage"))
                if tokens is None:
                    totals["unknown_usage"] += 1
                else:
                    totals["completed_input"] += tokens[0]
                    totals["completed_output"] += tokens[1]
                if group is not None:
                    group["native_accounting_records" if native_record else "upstream_attempts"] += 1
                    if tokens is None:
                        group["unknown_usage"] += 1
                    else:
                        group["input"] += tokens[0]
                        group["output"] += tokens[1]
            response_path = path.with_name(path.name.replace(".request.json", ".response.json"))
            if not response_path.exists():
                if "response" in entry:
                    totals["undelivered_or_missing_responses"] += 1
                continue
            response = read(response_path)
            require("response" in entry and digest(scrub(response)) == digest(entry["response"]),
                "Saved response differs from relay response")
            if kind == "jev":
                parse_jev(request, response)
                continue
            group["completed_returns"] += 1
            calls = [x for x in response["output"] if x.get("type") == "function_call"]
            require(len(calls) == 1 and calls[0].get("name") == tool, "Unexpected model tool return")
            answer = json.loads(calls[0]["arguments"])
            if response.get("transport", {}).get("kind") == "codex_app_server":
                check_native_origin(response, entry, answer, tool)
            english(answer)
            definition = request["tools"][0]
            require(definition["name"] == tool, "Tool declaration mismatch")
            validate_value(answer, definition["parameters"], tool)
            if tool == "submit_design":
                require(definition.get("strict") is True, "Design schema is not strict")
                designs += 1
            elif tool == "submit_review":
                if definition.get("strict") is True:
                    strict += 1
                else:
                    require(protocol["reused_method_sha256"] and not
                        protocol["arguments"]["revise_archived"], "Unexpected untyped generated-method review")
                    require(isinstance(json.loads(answer["parameters_json"]), dict), "Invalid legacy parameters")
                    legacy += 1
            elif tool in ("submit_method", "submit_method_patch"):
                if tool == "submit_method_patch":
                    state = json.loads(request["input"][0]["content"][-1]["text"])
                    answer = apply_method_patch(state["previous_method"], answer)
                validate_source(answer["source"])
                origins.add(hashlib.sha256(answer["source"].encode("ascii")).hexdigest())
            else:
                raise ValueError("Unsupported program-host tool")
        require(totals["matched_requests"] == summary[kind+"_calls"], "Request count mismatch")
        totals.update(request_models=sorted(request_models),
            transport_source_hashes=sorted(transport_hashes))
        usage[kind] = totals
    source_origins = []
    for item in summary["methods"]:
        method = read(run / f"method-{item['number']:02d}.json")
        validate_source(method["source"])
        source_hash = hashlib.sha256(method["source"].encode("ascii")).hexdigest()
        require(source_hash == item["source_sha256"], "Executed source hash mismatch")
        reused = item["number"] == 0 and source_hash == protocol["reused_method_sha256"]
        require(source_hash in origins or reused, "Source is not an actual model output or declared archive")
        source_origins.append(dict(number=item["number"], source_sha256=source_hash,
            origin="declared exact-source reuse" if reused else "actual model output or assembled model patch"))
    result = {k: summary[k] for k in ("native_success", "termination", "gpt_calls",
        "jev_calls", "native_steps", "elapsed_s", "methods")}
    program_result = summary.get("result")
    valid_result = isinstance(program_result, dict) and type(program_result.get("completion_proposed")) is bool
    result.update(completion_proposed=program_result["completion_proposed"] if valid_result else None,
        program_result_contract_valid=valid_result if summary["methods"] else None,
        audit="Saved responses, raw choices, semantic labels, action bounds, source origins and costs checked"
            if summary["methods"] else "No source or dispatch; request/cost and zero-step consistency only",
        native_result_source="Saved terminal summary; no evaluator or observation-truth recheck",
        dispatches=dispatches, models=usage, strict_reviews_validated=strict,
        strict_designs_validated=designs, legacy_reviews_json_decoded=legacy,
        source_origins=source_origins, gpt_cost_by_purpose=purpose,
        usage_scope="Known totals include reported native thread aggregates; native accounting records are not provider HTTP attempts. Internal native attempt counts and missing retry usage remain unknown.")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, nargs="+")
    parser.add_argument("--bridge-dir", type=Path, required=True)
    parser.add_argument("--no-write", action="store_true", help="Read-only audit; do not save audit.json")
    args = parser.parse_args()
    try:
        ledgers = {kind: ledger_index(args.bridge_dir / filename)
            for kind, filename in (("gpt", "requests.jsonl"), ("jev", "jev-requests.jsonl"))}
        for run in args.runs:
            result = audit_run(run, ledgers)
            if not args.no_write:
                (run / "audit.json").write_text(json.dumps(result, indent=2)+"\n")
            print(json.dumps(dict(run=str(run), **result)))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(1, f"Audit failed: {error}\n")


if __name__ == "__main__":
    main()

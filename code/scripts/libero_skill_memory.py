"""Evidence-linked Playground knowledge, frozen transfer, and planner context.

Only skills/ and lessons/ transfer. They are reference material, never an
automatically executed policy or current observation. No filesystem chmod.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from gpt_jev_contract import english

VERSION = "libero-playground-memory-v1"
LIMIT = 60000


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_files(root):
    root = Path(root)
    if root.is_symlink():
        raise ValueError("Knowledge root must not be a symlink")
    result = {}
    for component in ("skills", "lessons"):
        directory = root / component
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("Expected ordinary skills and lessons directories")
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise ValueError("Knowledge cannot contain symlinks")
            if path.is_dir():
                continue
            if not path.is_file() or path.suffix not in (".md", ".py"):
                raise ValueError("Only Markdown and Python reference files transfer")
            name = path.relative_to(root).as_posix()
            if not re.fullmatch(r"[A-Za-z0-9_./-]+", name):
                raise ValueError("Use portable ASCII knowledge paths")
            raw = path.read_bytes()
            if len(raw) > LIMIT:
                raise ValueError("Knowledge file exceeds context budget")
            content = raw.decode("utf-8")
            english(content)
            result[name] = content
    if sum(len(v) for v in result.values()) > LIMIT:
        raise ValueError("Knowledge exceeds total context budget")
    return result


def file_hashes(files):
    return {name: digest(content.encode()) for name, content in files.items()}


def freeze(source, destination, evidence):
    """Copy explicit knowledge and preserve separate, non-model evidence links."""
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ValueError("Freeze destination must be new")
    files = read_files(source)
    if not files or not evidence:
        raise ValueError("Freeze requires knowledge and at least one Playground episode")
    records = []
    for episode in evidence:
        episode = Path(episode)
        protocol_bytes = (episode / "protocol.json").read_bytes()
        summary_bytes = (episode / "summary.json").read_bytes()
        protocol = json.loads(protocol_bytes)
        if protocol.get("arguments", {}).get("knowledge_phase") != "playground":
            raise ValueError("Only explicitly declared Playground episodes may train memory")
        summary = json.loads(summary_bytes)
        if not isinstance(summary, dict) or not {"termination", "native_success", "gpt_calls", "jev_calls", "native_steps"} <= summary.keys():
            raise ValueError("Missing terminal episode evidence")
        args = protocol["arguments"]
        records.append(dict(episode=str(episode.resolve()),
            suite=args["suite"], task_id=args["task_id"], init_index=args["init_index"],
            seed=args["seed"], protocol_sha256=digest(protocol_bytes),
            summary_sha256=digest(summary_bytes)))
    lineage = source / "lineage.json"
    if lineage.exists():
        required = json.loads(lineage.read_text())["episodes"]
        supplied = {entry["episode"]: entry for entry in records}
        for entry in required:
            if supplied.get(entry["episode"]) != entry:
                raise ValueError("Freeze omits or changes contributing Playground evidence")
    manifest = dict(version=VERSION, files=file_hashes(files), playground=records,
        transfer="Only skills and lessons; no episode source, state, images, or evaluator inputs")
    destination.mkdir(parents=True)
    for component in ("skills", "lessons"):
        (destination / component).mkdir()
    for name, content in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    (destination / "freeze.json").write_text(json.dumps(manifest, indent=2)+"\n")
    return manifest


def load(root, phase, *, suite=None, task_id=None, init_index=None):
    """Hash-check frozen inputs once; return an in-memory immutable text snapshot."""
    files = read_files(root)
    hashes = file_hashes(files)
    metadata = dict(version=VERSION, phase=phase, files=hashes,
        snapshot_sha256=digest(json.dumps(hashes, sort_keys=True).encode()))
    if phase == "test":
        manifest = json.loads((Path(root) / "freeze.json").read_text())
        if manifest.get("version") != VERSION or manifest.get("files") != hashes:
            raise ValueError("Frozen knowledge integrity mismatch")
        if not manifest.get("playground"):
            raise ValueError("Frozen knowledge has no Playground provenance")
        for entry in manifest["playground"]:
            if (entry["suite"], entry["task_id"], entry["init_index"]) == (suite, task_id, init_index):
                raise ValueError("Test initial state overlaps Playground")
        metadata["freeze_sha256"] = digest((Path(root) / "freeze.json").read_bytes())
    elif phase != "playground":
        raise ValueError("Unknown knowledge phase")
    if not files:
        return "", metadata
    context = (
        "\n\nTRANSFERRED PLAYGROUND KNOWLEDGE\n"
        "Use relevant skills and lessons to design the plan, observation processing, "
        "Jev questions and candidate actions, executable method, feedback checks and recovery. "
        "Check applicability and evidence status. This is prior experience, not current "
        "sensor evidence or proof of task success. Remeasure scene-dependent values. "
        "Code is reference material: adapt it to the current API and source validator; "
        "it is not preloaded or automatically executed.\n"
    )
    for name, content in files.items():
        context += "\n--- " + name + " ---\n" + content + "\n"
    english(context)
    return context, metadata


def pack_episode_evidence(directory, summary, *, source_budget=90000):
    """Avoid duplicating full stage histories and per-action robot geometry."""
    directory = Path(directory)
    record = dict(episode_id=directory.name,
        summary={k: v for k, v in summary.items() if k != "result"}, methods=[], events=[])
    if isinstance(summary.get("result"), dict):
        record["terminal_program_result"] = {k: summary["result"][k] for k in
            ("completion_proposed", "hierarchical_termination", "stage_status", "reason")
            if k in summary["result"]}
    journal_path = directory / "stage-journal.json"
    successful_hashes = set()
    if journal_path.exists():
        journal = json.loads(journal_path.read_text())
        events = []
        for event in journal.get("events", []):
            event = dict(event)
            outcome = dict(event.get("outcome") or {})
            if outcome.get("stage_status") == "stage_complete":
                successful_hashes.add(event.get("source_sha256"))
            handoff = outcome.pop("handoff", None)
            if handoff is not None:
                outcome["handoff_scope"] = "Omitted duplicate handoff; consult checkpoint/source references."
            effect = outcome.get("evidence")
            if isinstance(effect, dict) and isinstance(effect.get("execution"), list):
                effect = dict(effect)
                # Keep every authored phase and receipt, but not repeated copies
                # of the complete robot geometry and budget at each action.
                effect["execution"] = [{k: v for k, v in item.items() if k not in
                    ("before_state", "after_state")} if isinstance(item, dict) else item
                    for item in effect["execution"]]
                effect["execution_scope"] = "Repeated before_state/after_state omitted; effect measurements retained."
                outcome["evidence"] = effect
            event["outcome"] = outcome
            events.append(event)
        compact = dict(events=events, plans=journal.get("plans", []),
            completed=[{k: item.get(k) for k in ("stage", "frame_id", "source_sha256")}
                       for item in journal.get("completed", [])], termination=journal.get("termination"))
        record["events"].append(dict(id=journal_path.name, sha256=digest(journal_path.read_bytes()), data=compact))
    methods = []
    for path in sorted(directory.glob("method-*.json")):
        data = json.loads(path.read_text())
        methods.append(dict(id=path.name, sha256=digest(path.read_bytes()), data=data))
    # Prefer complete demonstrated stage methods, then the latest revision.
    priority = sorted(range(len(methods)), key=lambda i: (
        digest(methods[i]["data"].get("source", "").encode()) in successful_hashes
        if isinstance(methods[i]["data"], dict) else False, i), reverse=True)
    for index in priority:
        data = methods[index]["data"]
        if not isinstance(data, dict) or "source" not in data:
            continue
        source = data["source"]
        if len(source) <= source_budget:
            source_budget -= len(source)
        else:
            data.pop("source")
            data["source_omitted"] = dict(sha256=digest(source.encode()), characters=len(source),
                reason="Complete source exceeds remaining source budget; no truncated code is supplied.")
    record["methods"] = methods
    checkpoints = directory / "program-checkpoints.json"
    if checkpoints.exists():
        values = json.loads(checkpoints.read_text())
        compact = {}
        for key, value in values.items():
            wire = json.dumps(value, separators=(",", ":"))
            compact[key] = value if len(wire) <= 8000 else dict(
                omitted=True, sha256=digest(wire.encode()), characters=len(wire),
                reason="Large checkpoint; its outcomes and effect evidence remain in the stage journal.")
        record["events"].append(dict(id=checkpoints.name, sha256=digest(checkpoints.read_bytes()), data=compact))
    dispatches = sorted(directory.glob("dispatch-*.json"))
    selected = sorted(set(dispatches[:4] + dispatches[-8:]))
    record["dispatch_sample"] = [dict(id=p.name, data=json.loads(p.read_text())) for p in selected]
    record["dispatch_sample_scope"] = dict(total=len(dispatches), included=len(selected),
        selection="first four and last eight actual dispatch receipts; not a complete trajectory")
    reviews = []
    for path in sorted(directory.glob("gpt-*.parsed.json")):
        data = json.loads(path.read_text())
        if "source" not in data and path.stat().st_size <= 12000:
            reviews.append(dict(id=path.name, data=data))
    record["recent_plans_and_reviews"] = reviews[-12:]
    record["scope"] = "Selected source and public evidence, with explicit omissions. Full immutable receipts remain archived."
    return record


def pack_refinement_evidence(previous, episodes, *, limit=300000):
    """Fit whole source files around retained observations and failure evidence."""
    source_budget = 90000
    while True:
        evidence = [pack_episode_evidence(directory, summary, source_budget=source_budget)
                    for directory, summary in episodes]
        text = json.dumps(dict(previous=previous, playground_evidence=evidence), separators=(",", ":"))
        if len(text) <= limit:
            return text
        if source_budget == 0:
            raise ValueError("Non-source evidence exceeds refinement budget; select a smaller episode batch")
        # Repack from immutable receipts: never truncate code or discard outcomes.
        # The episode packer retains demonstrated methods before other revisions.
        source_budget = max(0, source_budget - max(1000, (len(text)-limit)//max(1, len(episodes))+1000))


def refine(source, destination, episodes, receipts, bridge="http://127.0.0.1:7921"):
    """Ask local Pro to distill actual Playground receipts into a new revision."""
    # Deferred import avoids a cycle with the episode host's knowledge loader.
    from run_gpt_jev_program import post
    from gpt_jev_review_contract import validate_value
    import urllib.request

    source, destination, receipts = Path(source), Path(destination), Path(receipts)
    if not re.fullmatch(r"http://127\.0\.0\.1:(7921|7941)", bridge):
        raise ValueError("Use the declared local Pro bridge")
    if destination.exists():
        raise ValueError("Use a new revision directory")
    previous = read_files(source)
    lineage = json.loads((source / "lineage.json").read_text())["episodes"] if (source / "lineage.json").exists() else []
    episode_summaries = []
    for directory in episodes:
        directory = Path(directory)
        protocol = json.loads((directory / "protocol.json").read_text())
        if protocol.get("arguments", {}).get("knowledge_phase") != "playground":
            raise ValueError("Test episodes cannot update transferable knowledge")
        summary = json.loads((directory / "summary.json").read_text())
        if not {"termination", "native_success", "gpt_calls", "jev_calls", "native_steps"} <= summary.keys():
            raise ValueError("Episode is not terminal")
        args = protocol["arguments"]
        entry = dict(episode=str(directory.resolve()), suite=args["suite"], task_id=args["task_id"],
            init_index=args["init_index"], seed=args["seed"],
            protocol_sha256=digest((directory / "protocol.json").read_bytes()),
            summary_sha256=digest((directory / "summary.json").read_bytes()))
        if entry not in lineage:
            lineage.append(entry)
        episode_summaries.append((directory, summary))
    if not episode_summaries:
        raise ValueError("At least one terminal Playground episode is required")
    text = pack_refinement_evidence(previous, episode_summaries)
    english(text)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(bridge+"/", timeout=10) as response:
        health = json.load(response)
    if (health.get("transport"), health.get("auth"), health.get("model"), health.get("effort")) != (
            "native-session", "ChatGPT", "gpt-6-astra", "xhigh"):
        raise ValueError("Refinement requires the local signed-in Pro native-session bridge")
    schema = dict(type="object", additionalProperties=False, required=["files"], properties=dict(
        files=dict(type="array", minItems=1, maxItems=12, items=dict(type="object",
            additionalProperties=False, required=["path", "content"], properties=dict(
                path=dict(type="string", pattern=r"^(skills|lessons)/[a-z0-9-]+\.md$"),
                content=dict(type="string", minLength=1, maxLength=12000))))))
    instructions = (
        "Distill reusable LIBERO skills and lessons from the supplied Playground experience. "
        "Return the complete next knowledge revision, retaining relevant previous findings. "
        "Skills may teach planning, observable subgoal decomposition, measurement processing, "
        "Jev state/question/candidate design, numerical execution, feedback verification and recovery. "
        "Include code examples only when useful. Do not copy an entire episode solution. "
        "For each finding state applicability, inputs and frames/units, Jev versus program responsibilities, "
        "failure/stopping conditions, evidence IDs, and status: hypothesis, scene-specific, or verified. "
        "Verified requires repeated supporting observations; native success alone does not isolate a cause. "
        "Failures must remain visible. Do not present guesses as learned successes. "
        "Evidence packets explicitly mark omitted or sampled material. Do not infer missing details or treat a sample as a complete trajectory. "
        "Parameterize scene-specific measurements; exclude fixed task IDs, stored coordinates and "
        "hidden evaluation state. A skill guides future fresh synthesis and is not a current observation. "
        "For each skills/<name>.md use YAML frontmatter with name and description. "
        "Use concise English ASCII throughout. Return submit_skill_revision only."
    )
    receipts.mkdir(parents=True, exist_ok=True)
    payload = dict(model="gpt-6-astra", reasoning=dict(effort="xhigh"), instructions=instructions,
        input=[dict(role="user", content=[dict(type="input_text", text=text)])],
        tools=[dict(type="function", name="submit_skill_revision", description="Submit reusable knowledge",
                    parameters=schema, strict=True)],
        tool_choice=dict(type="function", name="submit_skill_revision"), parallel_tool_calls=False, store=False)
    attempts = []
    for attempt in range(3):
        prefix = receipts / ("refinement" if attempt == 0 else f"correction-{attempt}")
        request_path, response_path = prefix.with_suffix(".request.json"), prefix.with_suffix(".response.json")
        if request_path.exists() or response_path.exists():
            if not request_path.exists() or not response_path.exists():
                raise ValueError("Incomplete refinement request; inspect its bridge job before resuming")
            if json.loads(request_path.read_text()) != payload:
                raise ValueError("Refinement inputs changed before resume")
            result = json.loads(response_path.read_text())
        else:
            result = post(bridge+"/responses", payload, prefix, timeout=None)
        attempts.append(dict(receipt=prefix.name, usage=result.get("usage")))
        try:
            calls = [item for item in result.get("output", []) if item.get("type") == "function_call"]
            if result.get("status") != "completed" or len(calls) != 1 or calls[0].get("name") != "submit_skill_revision":
                raise ValueError("Refinement did not complete exactly one valid submission")
            answer = json.loads(calls[0]["arguments"])
            validate_value(answer, schema, "skill revision")
            english(answer)
            files = {item["path"]: item["content"] for item in answer["files"]}
            if len(files) != len(answer["files"]) or sum(map(len, files.values())) > LIMIT:
                raise ValueError("Duplicate paths or oversized knowledge revision")
            invalid = [name for name in files if not re.fullmatch(r"(skills|lessons)/[a-z0-9-]+\.md", name)]
            if invalid:
                raise ValueError("Invalid knowledge output paths: " + ", ".join(invalid))
            break
        except (ValueError, KeyError, TypeError) as error:
            attempts[-1]["validation_error"] = str(error)
            (receipts / "validation.json").write_text(json.dumps(attempts, indent=2)+"\n")
            if attempt == 2:
                raise ValueError("Refinement exhausted two format corrections") from error
            payload = json.loads(json.dumps(payload))
            feedback = dict(validation_error=str(error), previous_output=result.get("output"),
                correction="Return the complete corrected revision. Every path must match skills/<lowercase-hyphen-name>.md or lessons/<lowercase-hyphen-name>.md. No README.md, references directory, nested directories or other paths. Preserve evidence limits; do not invent new observations.")
            payload["input"].append(dict(role="user", content=[dict(type="input_text", text=json.dumps(feedback))]))
    destination.mkdir(parents=True)
    for component in ("skills", "lessons"):
        (destination / component).mkdir()
    for name, content in files.items():
        (destination / name).write_text(content)
    (destination / "lineage.json").write_text(json.dumps(dict(episodes=lineage), indent=2)+"\n")
    (receipts / "revision.json").write_text(json.dumps(dict(files=file_hashes(files),
        episodes=[str(Path(p).resolve()) for p in episodes], usage=result.get("usage"),
        refinement_attempts=attempts), indent=2)+"\n")
    return dict(files=len(files), usage=result.get("usage"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("freeze")
    command.add_argument("--source", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--evidence", type=Path, nargs="+", required=True)
    command = sub.add_parser("refine")
    command.add_argument("--source", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--evidence", type=Path, nargs="+", required=True)
    command.add_argument("--receipts", type=Path, required=True)
    command.add_argument("--bridge", default="http://127.0.0.1:7921")
    args = parser.parse_args()
    if args.command == "refine":
        print(json.dumps(refine(args.source, args.output, args.evidence, args.receipts, args.bridge)))
        return
    manifest = freeze(args.source, args.output, args.evidence)
    print(json.dumps(dict(files=len(manifest["files"]), episodes=len(manifest["playground"]))))


if __name__ == "__main__":
    main()

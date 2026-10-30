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


def refine(source, destination, episodes, receipts):
    """Ask local Pro to distill actual Playground receipts into a new revision."""
    # Deferred import avoids a cycle with the episode host's knowledge loader.
    from run_gpt_jev_program import post
    from gpt_jev_review_contract import validate_value
    import urllib.request

    source, destination, receipts = Path(source), Path(destination), Path(receipts)
    if destination.exists() or receipts.exists():
        raise ValueError("Use new revision and receipt directories")
    previous = read_files(source)
    evidence = []
    for directory in episodes:
        directory = Path(directory)
        protocol = json.loads((directory / "protocol.json").read_text())
        if protocol.get("arguments", {}).get("knowledge_phase") != "playground":
            raise ValueError("Test episodes cannot update transferable knowledge")
        summary = json.loads((directory / "summary.json").read_text())
        if not {"termination", "native_success", "gpt_calls", "jev_calls", "native_steps"} <= summary.keys():
            raise ValueError("Episode is not terminal")
        # Preserve program declarations and their actual outcomes, including failures.
        # Raw credentials, infrastructure paths and evaluator internals are excluded.
        record = dict(episode_id=directory.name, summary=summary, methods=[], events=[])
        for path in sorted(directory.glob("method-*.json")):
            record["methods"].append(dict(id=path.name, data=json.loads(path.read_text())))
        for name in ("stage-journal.json", "program-checkpoints.json"):
            path = directory / name
            if path.exists():
                record["events"].append(dict(id=name, data=json.loads(path.read_text())))
        evidence.append(record)
    if not evidence:
        raise ValueError("At least one terminal Playground episode is required")
    text = json.dumps(dict(previous=previous, playground_evidence=evidence))
    english(text)
    if len(text) > 200000:
        raise ValueError("Evidence exceeds refinement budget; select a smaller episode batch")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:7921/", timeout=10) as response:
        health = json.load(response)
    if health.get("transport") != "native-session":
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
        "Parameterize scene-specific measurements; exclude fixed task IDs, stored coordinates and "
        "hidden evaluation state. A skill guides future fresh synthesis and is not a current observation. "
        "For each skills/<name>.md use YAML frontmatter with name and description. "
        "Use concise English ASCII throughout. Return submit_skill_revision only."
    )
    receipts.mkdir(parents=True)
    payload = dict(model="gpt-6-astra", reasoning=dict(effort="xhigh"), instructions=instructions,
        input=[dict(role="user", content=[dict(type="input_text", text=text)])],
        tools=[dict(type="function", name="submit_skill_revision", description="Submit reusable knowledge",
                    parameters=schema, strict=True)],
        tool_choice=dict(type="function", name="submit_skill_revision"), parallel_tool_calls=False, store=False)
    result = post("http://127.0.0.1:7921/responses", payload, receipts / "refinement", timeout=None)
    calls = [item for item in result.get("output", []) if item.get("type") == "function_call"]
    if result.get("status") != "completed" or len(calls) != 1 or calls[0].get("name") != "submit_skill_revision":
        raise ValueError("Refinement did not complete exactly one valid submission")
    answer = json.loads(calls[0]["arguments"])
    validate_value(answer, schema, "skill revision")
    english(answer)
    files = {item["path"]: item["content"] for item in answer["files"]}
    if len(files) != len(answer["files"]) or sum(map(len, files.values())) > LIMIT:
        raise ValueError("Duplicate paths or oversized knowledge revision")
    for name in files:
        if not re.fullmatch(r"(skills|lessons)/[a-z0-9-]+\.md", name):
            raise ValueError("Invalid knowledge output path")
    destination.mkdir(parents=True)
    for component in ("skills", "lessons"):
        (destination / component).mkdir()
    for name, content in files.items():
        (destination / name).write_text(content)
    (receipts / "revision.json").write_text(json.dumps(dict(files=file_hashes(files),
        episodes=[str(Path(p).resolve()) for p in episodes], usage=result.get("usage")), indent=2)+"\n")
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
    args = parser.parse_args()
    if args.command == "refine":
        print(json.dumps(refine(args.source, args.output, args.evidence, args.receipts)))
        return
    manifest = freeze(args.source, args.output, args.evidence)
    print(json.dumps(dict(files=len(manifest["files"]), episodes=len(manifest["playground"]))))


if __name__ == "__main__":
    main()

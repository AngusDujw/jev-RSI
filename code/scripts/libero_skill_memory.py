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
        if not isinstance(summary, dict) or not summary:
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("freeze")
    command.add_argument("--source", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--evidence", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    manifest = freeze(args.source, args.output, args.evidence)
    print(json.dumps(dict(files=len(manifest["files"]), episodes=len(manifest["playground"]))))


if __name__ == "__main__":
    main()

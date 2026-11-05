"""Playground-only refinement and hash-checked frozen transfer."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil

from judgments import ascii_wire


def files_at(root):
    root = Path(root).resolve()
    files = {}
    for folder in ("skills", "lessons"):
        base = root / folder
        if base.is_symlink():
            raise ValueError("Knowledge folders cannot be symlinks")
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_symlink():
                raise ValueError("Knowledge cannot contain symlinks")
            if not path.is_file():
                continue
            if path.suffix != ".md" or not path.resolve().is_relative_to(root):
                raise ValueError("Transfer accepts only independent Markdown knowledge files")
            text = path.read_text()
            if not text.isascii():
                raise ValueError("Knowledge must be English ASCII")
            files[str(path.relative_to(root))] = text
    if sum(len(v) for v in files.values()) > 65000:
        raise ValueError("Knowledge exceeds the fixed 65000-character transfer budget")
    return files


def signature(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load(root, *, require_frozen=False):
    root = Path(root)
    files = files_at(root)
    marker = root / "freeze.json"
    if require_frozen and not marker.is_file():
        raise ValueError("Test requires a frozen knowledge snapshot")
    if marker.exists() and json.loads(marker.read_text())["knowledge_sha256"] != signature(files):
        raise ValueError("Frozen knowledge changed after freezing")
    return "\n\n".join("FILE " + name + "\n" + text for name, text in sorted(files.items()))


def freeze(source, target, training_records):
    target = Path(target)
    if target.exists():
        raise ValueError("Freeze destination must not already exist")
    files = files_at(source)
    if not files:
        raise ValueError("Cannot freeze empty learned knowledge")
    provenance = []
    for record in training_records:
        record = Path(record)
        impl = json.loads((record / "implementation.json").read_text())
        if impl["phase"] != "playground":
            raise ValueError("Only Playground episodes may supply training provenance")
        provenance.append(dict(record=str(record), result_sha256=hashlib.sha256(
            (record / "result.json").read_bytes()).hexdigest()))
    target.mkdir(parents=True)
    for name, text in files.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    value = dict(schema="hexashell-jev-freeze-v1", knowledge_sha256=signature(files),
                 files={k: hashlib.sha256(v.encode()).hexdigest() for k, v in files.items()},
                 playground=provenance, transfer="skills and lessons only; no simulator state or episode code")
    (target / "freeze.json").write_text(json.dumps(value, indent=2)+"\n")
    return value


def refine(pro, records, target, previous=None):
    records = [Path(p) for p in records]
    packets, pictures = [], []
    for record in records:
        impl = json.loads((record / "implementation.json").read_text())
        if impl["phase"] != "playground":
            raise ValueError("Refinement may read Playground records only")
        cells = (record / "cells.jsonl").read_text()
        receipts = []
        for path in sorted(record.glob("decision-*.request.json")):
            receipts.append(dict(request=json.loads(path.read_text()),
                receipt=json.loads(path.with_name(path.name.replace(".request", ".receipt")).read_text())
                if path.with_name(path.name.replace(".request", ".receipt")).exists() else None))
        packets.append(dict(result=json.loads((record / "result.json").read_text()),
                            cells=cells[-70000:], judgments=receipts[-20:]))
        pictures.extend(sorted((record / "pictures").glob("*.jpg"))[-2:])
    instruction = (
        "Refine reusable robot code-policy skills and diagnostic lessons from Playground only. "
        "Return the COMPLETE next knowledge snapshot, preserving useful prior knowledge. Files are "
        "English ASCII Markdown under skills/ or lessons/. Describe observable preconditions, frames, "
        "units, bounded actions, verification, local retries, and when the policy should query the "
        "local decision model or return to GPT. Improve the evidence representation, questions, "
        "answer options and answer-to-code branches together. Markdown may contain reusable Python "
        "helper definitions, but never auto-executed motion or scene pixel coordinates. Distinguish "
        "verified observations, scene-specific findings and hypotheses; failures are evidence. "
        "Do not claim task success unless the native result says success. Do not turn the host's "
        "holding heuristic into proof. Do not claim JEV sees images. Do not use test knowledge, "
        "private simulator state or benchmark-checker code. Keep the entire snapshot below 65000 "
        "characters. No model weights are trained. Prefer concise practical procedures.")
    text = dict(prior_knowledge=load(previous) if previous else "", playground=packets)
    content = [dict(type="input_text", text=json.dumps(ascii_wire(text)))]
    import base64
    for path in pictures[-4:]:
        content.append(dict(type="input_image", image_url="data:image/jpeg;base64,"+
                            base64.b64encode(path.read_bytes()).decode()))
    item = dict(type="object", properties=dict(path=dict(type="string", maxLength=120),
        content=dict(type="string", maxLength=16000)), required=["path", "content"], additionalProperties=False)
    schema = dict(type="object", properties=dict(files=dict(type="array", items=item, minItems=1, maxItems=16),
        rationale=dict(type="string", maxLength=3000)), required=["files", "rationale"], additionalProperties=False)
    value, raw = pro.submit("submit_knowledge", schema, instruction, content)
    target = Path(target)
    if target.exists():
        raise ValueError("Refinement destination must be fresh")
    files = {}
    for item in value["files"]:
        path = PurePosixPath(item["path"])
        if (len(path.parts) != 2 or path.parts[0] not in ("skills", "lessons") or
                path.suffix != ".md" or ".." in path.parts or path.is_absolute() or str(path) in files):
            raise ValueError("Invalid knowledge path")
        if not item["content"].isascii():
            raise ValueError("Knowledge must be English ASCII")
        files[str(path)] = item["content"]
    if sum(map(len, files.values())) > 65000:
        raise ValueError("Knowledge exceeds transfer budget")
    target.mkdir(parents=True)
    for name, text in files.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (target / "lineage.json").write_text(json.dumps(dict(records=list(map(str, records)),
        knowledge_sha256=signature(files), rationale=value["rationale"], usage=raw.get("usage")), indent=2)+"\n")
    return target

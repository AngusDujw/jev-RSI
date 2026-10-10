"""Build a portable, read-only casebook from two recorded LIBERO Goal episodes.

The generated page embeds every Jev request/response and executed action for
the selected episodes. Source episodes are never modified.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil


CODE = Path(__file__).resolve().parents[1]
OUTPUT = CODE / "reports" / "libero-goal-casebook"
CASES = (
    {
        "id": "1383",
        "folder": "2026-10-09-goal-1383-local-init6-frozen-0b9f2dc",
        "frames": (
            ("agentview.png", "初始观测", "外部相机"),
            ("0126-contact-agentview.png", "接触旋钮", "外部相机"),
            ("0216-turn-agentview.png", "旋转中", "外部相机"),
            ("0312-terminal-agentview.png", "终局画面", "外部相机"),
        ),
        "evidence": (
            "visible-control-initial.json",
            "contact-plan.json",
            "visible-control-after.json",
        ),
    },
    {
        "id": "1458",
        "folder": "2026-10-09-goal-1458-local-init2-low-release",
        "frames": (
            ("agentview.png", "初始观测", "外部相机"),
            ("0186-grasp-agentview.png", "夹取瓶身", "外部相机"),
            ("0381-orient_receiver-agentview.png", "高处对齐斜架", "外部相机"),
            ("0429-lower-agentview.png", "下降接近承托面", "外部相机"),
            ("0513-select-agentview.png", "撤手并复看", "外部相机"),
            ("0429-lower-robot0_eye_in_hand.png", "下降时腕部视角", "腕部相机"),
        ),
        "evidence": (
            "visible-rack-fit.json",
            "rack-contact-0429.json",
            "visible-goal-0510.json",
        ),
    },
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_case(spec: dict) -> dict:
    folder = CODE / "runs" / spec["folder"]
    episode = folder / "episode"
    manifest = read_json(folder / "manifest.json")
    result = read_json(episode / "result.json")
    if not (result["success"] and result["program_finished"]):
        raise ValueError(f"Case must have both terminal flags: {folder}")

    branches = {
        item["decision_id"]: item
        for item in map(json.loads, (episode / "branches.jsonl").read_text().splitlines())
    }
    decisions = []
    for request_path in sorted(episode.glob("decision-*/request.json")):
        response_path = request_path.with_name("response.json")
        decision_id = request_path.parent.name
        request = read_json(request_path)
        response = read_json(response_path)
        if decision_id not in branches or set(request) != {"model", "state", "questions"}:
            raise ValueError(f"Incomplete recorded decision: {request_path}")
        if set(response) != {"model", "answers", "usage"}:
            raise ValueError(f"Unexpected Jev response shape: {response_path}")
        if set(request["questions"]) != set(response["answers"]):
            raise ValueError(f"Question/answer mismatch: {decision_id}")
        decisions.append({
            "id": decision_id,
            "stage": request["state"].get("stage", request["state"].get("operation")),
            "request": request,
            "response": response,
            "execution": branches[decision_id],
            "request_sha256": digest(request_path),
            "response_sha256": digest(response_path),
            "source": f"../../runs/{spec['folder']}/episode/{decision_id}/",
        })
    if len(decisions) != result["jev_calls"]:
        raise ValueError(f"Missing decision data: {folder}")

    events = [json.loads(line) for line in (episode / "events.jsonl").read_text().splitlines()]
    transitions = [
        {key: row.get(key) for key in ("from_stage", "to_stage", "decision_id", "selected_transition")}
        for row in events if row.get("kind") == "phase_transition"
    ]
    assets = OUTPUT / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    frames = []
    for filename, label, camera in spec["frames"]:
        source = episode / filename
        target = assets / f"{spec['id']}-{filename}"
        shutil.copyfile(source, target)
        frames.append({"src": f"assets/{target.name}", "label": label,
                       "camera": camera, "source": f"../../runs/{spec['folder']}/episode/{filename}"})

    evidence = {name: read_json(episode / name) for name in spec["evidence"]}
    return {
        "id": spec["id"],
        "folder": spec["folder"],
        "task": decisions[0]["request"]["state"]["task"],
        "init": manifest["reservation"]["init"],
        "commit": manifest["reservation"]["policy_commit"],
        "model": manifest["reservation"]["model"],
        "result": result,
        "frames": frames,
        "evidence": evidence,
        "transitions": transitions,
        "decisions": decisions,
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    cases = {spec["id"]: build_case(spec) for spec in CASES}
    data = "window.LIBERO_CASEBOOK_DATA = " + json.dumps(
        cases, ensure_ascii=False, separators=(",", ":")) + ";\n"
    (OUTPUT / "data.js").write_text(data, encoding="utf-8")
    print(f"Built {OUTPUT / 'data.js'}: " + ", ".join(
        f"Goal {key} {len(item['decisions'])} decisions" for key, item in cases.items()))


if __name__ == "__main__":
    main()

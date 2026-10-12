"""Build a sensor-only RoboDojo stage plan through the local Pro bridge."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import time
import urllib.error
import urllib.request


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--template", type=Path)
    parser.add_argument("--global-experience", type=Path, required=True)
    parser.add_argument("--task-experience", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    obs = json.loads(args.observation.read_text())
    template = json.loads(args.template.read_text()) if args.template else None
    if template and template["task"] != obs["task"]:
        raise ValueError("Task mismatch")
    public = {
        "task": obs["task"], "instruction": obs["instruction"],
        "current_eef": obs["current_eef"],
        "current_joint_state": obs["current_state"],
    }
    experience = {
        "global": args.global_experience.read_text(),
        "task": args.task_experience.read_text() if args.task_experience else "",
    }
    system = (
        "You are GPT-6.1 Sol high, the stage and visual-method planner for a RoboDojo robot. "
        "Use ONLY the task instruction, three supplied RGB frames, measured robot state, "
        "and the supplied experience notes. No hidden simulator object pose, contacts, reward, "
        "evaluation state, or task layout data are available. Produce one JSON object with "
        "task, initial_stage, stages, notes, visual_method, experience. "
        + ("Keep EXACTLY the provided stage keys and initial_stage from the template. "
           if template else
           "Choose 4 to 12 task-specific stages and an initial_stage that is one of them. ") +
        "stages maps each key to "
        "a concise actionable recipe with visual pass criterion and bounded recovery. "
        "visual_method must describe how to use RGB and measured robot state to construct "
        "the decision model input, including image identity, color/shape measurements, "
        "camera/frame ambiguities, freshness and occlusion handling. experience is a "
        "short list of applicable, evidence-grounded lessons, never an assertion of success. "
        "The GPT-6 Luna decision model receives all three current RGB frames and may only "
        "choose among offered discrete motion, gripper and stage options. Do not emit "
        "precise object world coordinates from monocular RGB. Require visible capture and "
        "post-release verification. Return JSON only."
    )
    details = {
        "public_observation": public,
        "experience": experience,
    }
    if template:
        details["existing_stage_template"] = template
    parts = [{"type": "text", "text": json.dumps(details, ensure_ascii=False)}]
    image_meta = []
    for item in obs["images"]:
        if item["camera"] not in {"cam_high", "cam_left_wrist", "cam_right_wrist"}:
            raise ValueError("Unexpected camera")
        image = Path(item["path"])
        raw = image.read_bytes()
        image_meta.append({"camera": item["camera"], "path": str(image),
                           "sha256": hashlib.sha256(raw).hexdigest()})
        parts.append({"type": "text", "text": "Current RGB: " + item["camera"]})
        parts.append({"type": "image_url", "image_url": {
            "url": "data:image/png;base64," + base64.b64encode(raw).decode("ascii")}})
    payload = {
        "model": "gpt-6.1-sol", "reasoning_effort": "high",
        "response_format": {"type": "json_object"}, "stream": False,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": parts}],
    }
    write_json(args.output / "planner-input-manifest.json", {
        "model": payload["model"], "reasoning_effort": payload["reasoning_effort"],
        "public_observation": public, "images": image_meta,
        "template_sha256": (hashlib.sha256(args.template.read_bytes()).hexdigest()
                            if args.template else None),
        "experience_sha256": {k: hashlib.sha256(v.encode()).hexdigest()
                              for k, v in experience.items()},
    })
    request = urllib.request.Request("http://127.0.0.1:18883/v1/chat/completions",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"},
        method="POST")
    last_error = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=1300) as handle:
                response = json.load(handle)
            break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = str(error)
            time.sleep(min(20 * (attempt + 1), 60))
    else:
        raise RuntimeError("Planner bridge failed: " + str(last_error))
    write_json(args.output / "planner-response.json", response)
    plan = json.loads(response["choices"][0]["message"]["content"])
    if isinstance(plan.get("task"), dict) and plan["task"].get("id") == obs["task"]:
        plan["task_detail"] = plan["task"]
        plan["task"] = obs["task"]
    if isinstance(plan.get("stages"), dict):
        plan["stages"] = {
            key: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            if isinstance(value, dict) else value
            for key, value in plan["stages"].items()
        }
    stages = plan.get("stages")
    if (plan.get("task") != obs["task"] or
            not isinstance(stages, dict) or
            not 4 <= len(stages) <= 12 or
            (template and set(stages) != set(template["stages"])) or
            (template and plan.get("initial_stage") != template["initial_stage"]) or
            plan.get("initial_stage") not in stages or
            not all(isinstance(k, str) and k and isinstance(v, str) and v.strip()
                    for k, v in stages.items()) or
            not isinstance(plan.get("visual_method"), (dict, str)) or
            not isinstance(plan.get("experience"), list)):
        raise ValueError("Planner output failed contract validation")
    plan["planner_provenance"] = {
        "model": "gpt-6.1-sol", "reasoning_effort": "high",
        "auth": "local ChatGPT Pro subscription bridge",
        "input_manifest": str(args.output / "planner-input-manifest.json"),
    }
    write_json(args.output / "plan.json", plan)
    print(json.dumps({"plan": str(args.output / "plan.json"),
                      "stage_count": len(plan["stages"]),
                      "image_count": len(image_meta)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

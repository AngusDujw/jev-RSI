"""Foreground, resumable RoboICL paired experiment; lightweight artifacts only."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import os
from pathlib import Path
import queue
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
TASKS = ("general_pickup", "fold_clothes", "press_by_number", "match_and_pick_from_conveyor", "stack_bowls")


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_suffix(path.suffix + ".writing")
    staging.write_text(json.dumps(value, indent=2) + "\n")
    staging.replace(path)


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def summarize_case(folder):
    results = sorted(folder.glob("*/result.json"))
    status_files = sorted(folder.glob("*/status.json"))
    row = {"folder": str(folder), "scored": bool(results), "success": False}
    if status_files:
        row["status"] = json.loads(status_files[-1].read_text())
    if results:
        result = json.loads(results[-1].read_text())
        details = list(result.get("details", {}).values())
        row.update(score=result.get("score"), native_success=bool(details and details[0].get("success")),
                   policy_error=result.get("policy_error"))
        row["success"] = row["native_success"] and not row["policy_error"]
    traces = list(folder.rglob("observations.jsonl"))
    if len(traces) > 1:
        raise ValueError(f"Ambiguous policy trace: {folder}")
    if traces:
        trace = traces[0].parent
        observations = lines(traces[0])
        receipts = lines(trace/"tool_results.jsonl")
        exchanges = lines(trace/"exchanges.jsonl")
        robot_steps = max((item.get("step", 0) for item in observations), default=0)
        call_starts = [item["step"] for item in exchanges]
        intervals = [end-start for start, end in zip(call_starts, call_starts[1:]+[robot_steps])]
        if any(step < 0 for step in intervals):
            raise ValueError("Nonmonotone GPT-call/robot-step ledger")
        row.update(robot_steps=robot_steps,
                   gpt_completed=len(exchanges), gpt_attempts=len(lines(trace/"requests.jsonl")),
                   jev_calls=len(lines(trace/"reuse_votes.jsonl")),
                   jev_attempts=len(lines(trace/"reuse_attempts.jsonl")),
                   jev_errors=len(lines(trace/"reuse_errors.jsonl")),
                   jev_approvals=sum(item.get("choice") == "reuse" for item in lines(trace/"reuse_votes.jsonl")),
                   executed_intervals=intervals,
                   accepted_tool_intervals=[item["executed_steps"] for item in receipts],
                   nonterminal_full_intervals=[item["executed_steps"] for item in receipts
                       if item["executed_steps"] == item["dispatched_steps"] and not item.get("controller_events")
                       and item["executed_step_interval"][-1] < max((o.get("step", 0) for o in observations), default=0)],
                   gpt_usage=[item.get("response", {}).get("usage", {}) for item in exchanges])
    media = [str(p) for p in folder.rglob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".mp4", ".hdf5", ".npy", ".npz")]
    if media:
        raise RuntimeError(f"Unexpected persisted media: {media[:5]}")
    return row


def summarize(root):
    rows = []
    for path in sorted(root.glob("*/*/layout-*/case.json")):
        case = json.loads(path.read_text())
        if (path.parent/"finished.json").exists():
            rows.append({**case, **summarize_case(path.parent), **json.loads((path.parent/"finished.json").read_text())})
    save(root/"summary.json", {"episodes": rows})
    for condition in sorted({row["condition"] for row in rows}):
        for task in TASKS:
            selected = [row for row in rows if row["condition"] == condition and row["task"] == task]
            if selected:
                print(json.dumps({"condition": condition, "task": task, "finished": len(selected),
                    "success": sum(row["success"] for row in selected), "scored": sum(row["scored"] for row in selected),
                    "mean_robot_steps_all_attempts": statistics.mean(row.get("robot_steps", 0) for row in selected),
                    "mean_robot_steps_scored": statistics.mean(row.get("robot_steps", 0) for row in selected if row["scored"] and not row.get("policy_error"))
                        if any(row["scored"] and not row.get("policy_error") for row in selected) else None,
                    "gpt_completed": sum(row.get("gpt_completed", 0) for row in selected)}), flush=True)
    return rows


def frozen_intervals(root):
    path = root/"frozen_intervals.json"
    if path.exists():
        return json.loads(path.read_text())
    rows = summarize(root)
    report = {}
    for task in TASKS:
        cases = [row for row in rows if row["condition"] == "jev" and row["task"] == task]
        if len(cases) != 4 or not all(row["scored"] and not row.get("policy_error") for row in cases):
            raise ValueError(f"Need four completed Jev episodes before freezing intervals: {task}")
        intervals = [step for row in cases for step in row["executed_intervals"]]
        if not intervals:
            raise ValueError(f"No execution intervals for {task}")
        mean = statistics.mean(intervals)
        report[task] = {"mean": max(1, min(20, int(Decimal(str(mean)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))),
                        "maximum": max(1, min(20, max(intervals))), "raw_maximum": max(intervals),
                        "raw_mean": mean, "samples": intervals,
                        "source_cases": [row["folder"] for row in cases]}
    save(path, report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sim-python", required=True)
    parser.add_argument("--policy-python", required=True)
    parser.add_argument("--gpus", type=int, nargs="+", default=[0, 1, 2, 3])
    parser.add_argument("--slots-per-gpu", type=int, default=1, choices=(1, 2, 3, 4))
    parser.add_argument("--conditions", nargs="+", choices=("pure", "jev", "mean", "maximum"), default=["pure", "jev"])
    parser.add_argument("--task", choices=TASKS)
    parser.add_argument("--layout", type=int, choices=range(4))
    parser.add_argument("--minimum-free-mib", type=int, default=9000)
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    if len(set(args.gpus)) != len(args.gpus) or len(args.gpus) > 4:
        parser.error("Use at most four unique GPUs")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if args.summary_only:
        summarize(root)
        return
    if "jev" in args.conditions and not Path(os.environ.get("ROBOICL_JEV_CONFIG", "missing")).is_file():
        parser.error("A readable authorized Jev config is required")
    intervals = frozen_intervals(root) if any(c in args.conditions for c in ("mean", "maximum")) else None
    profile = json.loads((ROOT/"configs/protocols/zero_shot_b25.json").read_text())
    profile.update(id="roboicl-pro-reuse-20261021", model="gpt-6-astra", endpoint="http://127.0.0.1:7911/responses")
    profile_path = root/"profile.json"
    if profile_path.exists() and json.loads(profile_path.read_text()) != profile:
        raise ValueError("Existing profile differs; use a new output root")
    save(profile_path, profile)
    jobs = queue.Queue()
    for layout in ([args.layout] if args.layout is not None else range(4)):
        for task in ([args.task] if args.task else TASKS):
            for condition in args.conditions:
                jobs.put((task, layout, condition))

    def worker(gpu, slot):
        while True:
            try:
                task, layout, condition = jobs.get_nowait()
            except queue.Empty:
                return
            folder = root/condition/task/f"layout-{layout}"
            if (folder/"finished.json").exists():
                continue
            if folder.exists():
                raise RuntimeError(f"Unfinished case preserved; inspect before a new attempt: {folder}")
            memory = subprocess.check_output(["nvidia-smi", "--id="+str(gpu), "--query-gpu=memory.free", "--format=csv,noheader,nounits"], text=True)
            if int(memory.strip()) < args.minimum_free_mib:
                raise RuntimeError(f"Insufficient current free GPU memory on {gpu}; no experiment started")
            horizon = intervals[task][condition] if intervals and condition in ("mean", "maximum") else 5
            folder.mkdir(parents=True)
            case = {"condition": condition, "task": task, "layout": layout,
                    "layout_directory_seed": 0, "sim_initial_seed": 0, "reset_seed": layout, "gpu": gpu, "slot": slot,
                    "execute_horizon": horizon, "predict_horizon": 20, "pro_auth": "ChatGPT", "model": "gpt-6-astra", "effort": "xhigh",
                    "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()}
            save(folder/"case.json", case)
            env = dict(os.environ, ROBOICL_REUSE_MODE="jev" if condition == "jev" else "pure", ROBOICL_NO_MEDIA="1",
                       ROBOICL_PREDICT_HORIZON="20", ROBOICL_EXECUTE_HORIZON=str(horizon),
                       ROBOICL_GPU_SLOTS=str(args.slots_per_gpu), ASTRA_API_KEY="local-chatgpt-placeholder",
                       TMPDIR=str(ROOT/".runtime/tmp"), XDG_CACHE_HOME=str(ROOT/".runtime/cache"),
                       TORCH_EXTENSIONS_DIR=str(ROOT/".runtime/torch-extensions"))
            command = [args.policy_python, "-B", "-m", "roboicl.run", task, "--shots", "0", "--seed", "0", "--layout", str(layout),
                       "--gpu", str(gpu), "--gpu-slot", str(slot), "--sim-python", args.sim_python, "--policy-python", args.policy_python,
                       "--profile", str(profile_path), "--results-root", str(folder)]
            started = time.monotonic()
            print(json.dumps({"event": "start", **case}), flush=True)
            with (folder/"launcher.log").open("w") as log:
                result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            save(folder/"finished.json", {"returncode": result.returncode, "wall_seconds": time.monotonic()-started})
            print(json.dumps({"event": "end", "condition": condition, "task": task, "layout": layout, **summarize_case(folder)}), flush=True)

    with ThreadPoolExecutor(max_workers=len(args.gpus)*args.slots_per_gpu) as executor:
        futures = [executor.submit(worker, gpu, slot) for gpu in args.gpus for slot in range(args.slots_per_gpu)]
        for future in futures:
            future.result()
    summarize(root)


if __name__ == "__main__":
    main()

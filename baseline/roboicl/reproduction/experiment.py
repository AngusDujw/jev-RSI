"""Foreground, resumable RoboICL paired experiment; lightweight artifacts only."""
import argparse
import fcntl
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
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
TASKS = ("general_pickup", "fold_clothes", "press_by_number", "match_and_pick_from_conveyor", "stack_bowls")


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.writing")
    staging.write_text(json.dumps(value, indent=2) + "\n")
    staging.replace(path)


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def claim_case_folder(folder, skip_existing=False):
    try:
        folder.mkdir(parents=True)
    except FileExistsError:
        if skip_existing:
            return False
        raise RuntimeError(f"Unfinished case preserved; inspect before a new attempt: {folder}") from None
    return True


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
        reused_steps = []
        for dispatch in lines(trace/"reuse_dispatch.jsonl"):
            start = dispatch["step"]
            following_call = next((step for step in call_starts if step >= start), robot_steps)
            reused_steps.append(max(0, min(len(dispatch["actions"]), following_call-start, robot_steps-start)))
        if any(step < 0 for step in intervals):
            raise ValueError("Nonmonotone GPT-call/robot-step ledger")
        tail_censored = not row["scored"] or bool(row.get("policy_error"))
        row.update(robot_steps=robot_steps,
                   gpt_completed=len(exchanges), gpt_attempts=len(lines(trace/"requests.jsonl")),
                   jev_calls=len(lines(trace/"reuse_votes.jsonl")),
                   jev_attempts=len(lines(trace/"reuse_attempts.jsonl")),
                   jev_errors=len(lines(trace/"reuse_errors.jsonl")),
                   jev_reused_steps=sum(reused_steps), jev_executed_extra_intervals=reused_steps,
                   jev_approvals=sum(item.get("choice") == "reuse" for item in lines(trace/"reuse_votes.jsonl")),
                   executed_intervals=intervals,
                   interval_tail_censored=tail_censored,
                   calibration_intervals=intervals[:-1] if tail_censored else intervals,
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


def frozen_intervals(root, tasks=TASKS):
    """Freeze each requested task once, after its four Jev attempts terminate."""
    with (root/"frozen_intervals.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _freeze_intervals(root, tasks)


def _freeze_intervals(root, tasks):
    path = root/"frozen_intervals.json"
    report = json.loads(path.read_text()) if path.exists() else {}
    missing = [task for task in tasks if task not in report]
    if not missing:
        return report
    rows = summarize(root)
    for task in missing:
        cases = [row for row in rows if row["condition"] == "jev" and row["task"] == task]
        if len(cases) != 4 or {row["layout"] for row in cases} != set(range(4)):
            raise ValueError(f"Need four terminated Jev attempts before freezing intervals: {task}")
        intervals = [step for row in cases for step in row.get("calibration_intervals", [])]
        if not intervals:
            raise ValueError(f"No execution intervals for {task}")
        mean = statistics.mean(intervals)
        report[task] = {"mean": max(1, min(20, int(Decimal(str(mean)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))),
                        "maximum": max(1, min(20, max(intervals))), "raw_maximum": max(intervals),
                        "raw_mean": mean, "samples": intervals,
                        "scored_attempts": sum(row["scored"] and not row.get("policy_error") for row in cases),
                        "usable_attempts": sum(bool(row.get("calibration_intervals")) for row in cases),
                        "censored_tails": sum(row.get("interval_tail_censored", True) for row in cases),
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
    task_filter = parser.add_mutually_exclusive_group()
    task_filter.add_argument("--task", choices=TASKS)
    task_filter.add_argument("--tasks", choices=TASKS, nargs="+")
    parser.add_argument("--layout", type=int, choices=range(4))
    parser.add_argument("--minimum-free-mib", type=int, default=9000)
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Parallel fixed-control pools only: leave already claimed cases untouched")
    args = parser.parse_args()
    if len(set(args.gpus)) != len(args.gpus) or len(args.gpus) > 4:
        parser.error("Use at most four unique GPUs")
    selected_tasks = args.tasks or ([args.task] if args.task else list(TASKS))
    if len(set(selected_tasks)) != len(selected_tasks):
        parser.error("Task filters must be unique")
    if args.skip_existing and any(c in ("pure", "jev") for c in args.conditions):
        parser.error("--skip-existing is only allowed for parallel fixed-control pools")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if args.summary_only:
        summarize(root)
        return
    if "jev" in args.conditions and not Path(os.environ.get("ROBOICL_JEV_CONFIG", "missing")).is_file():
        parser.error("A readable authorized Jev config is required")
    intervals = frozen_intervals(root, selected_tasks) if any(c in args.conditions for c in ("mean", "maximum")) else None
    profile = json.loads((ROOT/"configs/protocols/zero_shot_b25.json").read_text())
    profile.update(id="roboicl-pro-reuse-20261021", model="gpt-6-astra", endpoint="http://127.0.0.1:7911/responses")
    profile_path = root/"profile.json"
    if profile_path.exists() and json.loads(profile_path.read_text()) != profile:
        raise ValueError("Existing profile differs; use a new output root")
    save(profile_path, profile)
    jobs = queue.Queue()
    for layout in ([args.layout] if args.layout is not None else range(4)):
        for task in selected_tasks:
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
                if args.skip_existing:
                    continue
                raise RuntimeError(f"Unfinished case preserved; inspect before a new attempt: {folder}")
            memory = subprocess.check_output(["nvidia-smi", "--id="+str(gpu), "--query-gpu=memory.free", "--format=csv,noheader,nounits"], text=True)
            if int(memory.strip()) < args.minimum_free_mib:
                raise RuntimeError(f"Insufficient current free GPU memory on {gpu}; no experiment started")
            horizon = intervals[task][condition] if intervals and condition in ("mean", "maximum") else 5
            if not claim_case_folder(folder, args.skip_existing):
                continue
            case = {"condition": condition, "task": task, "layout": layout,
                    "layout_directory_seed": 0, "sim_initial_seed": 0, "reset_seed": layout, "gpu": gpu, "slot": slot,
                    "execute_horizon": horizon, "predict_horizon": 20, "pro_auth": "ChatGPT", "model": "gpt-6-astra", "effort": "xhigh",
                    "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()}
            save(folder/"case.json", case)
            kit_root = ROOT/".runtime"/f"kit-gpu{gpu}-slot{slot}"
            kit_root.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ, ROBOICL_REUSE_MODE="jev" if condition == "jev" else "pure", ROBOICL_NO_MEDIA="1",
                       ROBOICL_PREDICT_HORIZON="20", ROBOICL_EXECUTE_HORIZON=str(horizon),
                       ROBOICL_GPU_SLOTS=str(args.slots_per_gpu), ASTRA_API_KEY="local-chatgpt-placeholder",
                       TMPDIR=str(ROOT/".runtime/tmp"), XDG_CACHE_HOME=str(ROOT/".runtime/cache"),
                       TORCH_EXTENSIONS_DIR=str(ROOT/".runtime/torch-extensions"),
                       CUDA_CACHE_PATH=str(ROOT/".runtime/cuda-cache"), ROBOICL_KIT_PORTABLE_ROOT=str(kit_root))
            command = [args.policy_python, "-B", "-m", "roboicl.run", task, "--shots", "0", "--seed", "0", "--layout", str(layout),
                       "--model", "gpt-6-astra", "--reasoning-effort", "xhigh",
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

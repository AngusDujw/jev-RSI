"""Ledgered RGB-D capture for ten public LIBERO-Plus Goal tasks.

Capture does not call Jev or GPT-6. Every reserved scene counts against the
task's existing 50-attempt cap, including setup failures.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from libero_ten_task_workflows import TASKS


SIM_PYTHON = "/root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python"
TASK_CAP = 50


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--egl-device-id", type=int, choices=range(8), default=2)
    parser.add_argument("--render-backend", choices=("nvidia", "mesa"),
                        default="nvidia")
    parser.add_argument("--init-index", type=int, default=0)
    parser.add_argument("--task-ids", default=",".join(map(str, TASKS)),
                        help="Comma-separated subset of the ten public Goal task IDs")
    args = parser.parse_args()
    try:
        task_ids = [int(item) for item in args.task_ids.split(",")]
    except ValueError:
        parser.error("--task-ids must be comma-separated integers")
    if not task_ids or len(task_ids) != len(set(task_ids)) or any(
            task_id not in TASKS for task_id in task_ids):
        parser.error("--task-ids must be a nonempty unique subset of the ten tasks")
    repo = Path(__file__).resolve().parents[2]
    root = args.output.resolve()
    if not root.is_relative_to(repo / "code/runs"):
        parser.error("Output must be under project code/runs")
    if root.exists():
        parser.error("Output already exists")
    if not 0 <= args.init_index < 50:
        parser.error("Official init index must be 0..49")
    root.mkdir(parents=True)
    ledger = repo / "code/runs/libero-supervisor-ledger.jsonl"
    source = Path(__file__).with_name("libero_jev_rollout.py")
    manifest = dict(task_ids=task_ids, suite="libero_goal",
                    init_index=args.init_index, model_calls=0,
                    render_backend=args.render_backend,
                    purpose="public-scene RGB-D observation only",
                    camera_size=768, per_task_cap=TASK_CAP,
                    source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    code_commit=subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], text=True).strip())
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    rows = []
    consecutive_crashes = 0
    for task_id in task_ids:
        if shutil.disk_usage(root).free < 6 * 1024**3:
            (root / "stopped.json").write_text(json.dumps(dict(
                reason="Less than 6GiB free", task_id=task_id), indent=2) + "\n")
            break
        out = root / f"libero_goal-{task_id}-init-{args.init_index}"
        with ledger.open("a+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.seek(0)
            prior = [json.loads(line) for line in stream if line.strip()]
            count = sum(r.get("suite") == "libero_goal" and
                        r.get("task") == task_id for r in prior)
            if count >= TASK_CAP:
                raise RuntimeError(f"Task {task_id} already at {TASK_CAP} attempts")
            if any(r.get("suite") == "libero_goal" and
                   r.get("task") == task_id and r.get("init") == args.init_index and
                   r.get("campaign") == root.name for r in prior):
                raise RuntimeError(f"Duplicate reservation for task {task_id}")
            reservation = dict(suite="libero_goal", task=task_id,
                init=args.init_index, attempt=count + 1, campaign=root.name,
                output=str(out), purpose="workflow_capture", model="none")
            stream.write(json.dumps(reservation) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        command = [SIM_PYTHON, "-B", str(source), "--capture-only",
                   "--suite", "libero_goal", "--task-id", str(task_id),
                   "--init-index", str(args.init_index), "--camera-size", "768",
                   "--output", str(out), "--wall-limit-seconds", "500"]
        env = dict(os.environ, JEV_RSI_MODEL_BACKEND="capture_only")
        if args.render_backend == "mesa":
            env.pop("MUJOCO_EGL_DEVICE_ID", None)
            env.update(MUJOCO_GL="egl", EGL_PLATFORM="surfaceless",
                __EGL_VENDOR_LIBRARY_FILENAMES=(
                    "/usr/share/glvnd/egl_vendor.d/50_mesa.json"),
                CUDA_VISIBLE_DEVICES="")
        else:
            env.update(MUJOCO_EGL_DEVICE_ID=str(args.egl_device_id),
                       CUDA_VISIBLE_DEVICES=str(args.egl_device_id))
        started = time.monotonic()
        with (root / f"libero_goal-{task_id}.log").open("w") as log:
            try:
                completed = subprocess.run(command, stdout=log,
                    stderr=subprocess.STDOUT, env=env, timeout=600)
                returncode = completed.returncode
                termination = None
            except subprocess.TimeoutExpired:
                returncode = 124
                termination = "600s capture timeout"
        result_path = out / "summary.json"
        result = json.loads(result_path.read_text()) if result_path.exists() else {}
        scene_ready = (returncode == 0 and result.get("status") == "capture_only" and
            all((out / name).exists() for name in (
                "agentview.png", "robot0_eye_in_hand.png",
                "agentview-depth.npy", "robot0_eye_in_hand-depth.npy",
                "agentview-calibration.json",
                "robot0_eye_in_hand-calibration.json", "robot.json", "task.json")))
        row = dict(**reservation, scene_ready=scene_ready,
                   returncode=returncode, termination=termination,
                   seconds=round(time.monotonic() - started, 3),
                   result=result)
        rows.append(row)
        (root / "batch.json").write_text(json.dumps(rows, indent=2) + "\n")
        print(json.dumps(row), flush=True)
        consecutive_crashes = 0 if scene_ready else consecutive_crashes + 1
        if consecutive_crashes >= 3:
            (root / "stopped.json").write_text(json.dumps(dict(
                reason="Three consecutive capture crashes",
                task_id=task_id), indent=2) + "\n")
            break
        if sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) > 1 * 1024**3:
            (root / "stopped.json").write_text(json.dumps(dict(
                reason="1GiB campaign disk guard", task_id=task_id), indent=2) + "\n")
            break
    (root / "summary.json").write_text(json.dumps(dict(
        captured=sum(r["scene_ready"] for r in rows),
        reserved=len(rows), planned=len(task_ids)), indent=2) + "\n")


if __name__ == "__main__":
    main()

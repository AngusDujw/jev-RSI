"""One foreground RoboDojo episode, with all runtime output on DataStorage."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path

SOURCE_ROOT = Path.home() / "DataStorage/jev-router/sources"
DATA_ROOT = Path(os.environ.get("ROBODOJO_GPT6_DATA_ROOT", str(Path.home() / "DataStorage/gpt6-dec")))
ENVIRONMENT = Path.home() / "DataStorage/jev-router/project/jev-router/ENVIRONMENT.json"
TASKS = ("stack_blocks", "general_pickup", "fold_clothes", "press_by_number", "stack_bowls")


def executable() -> Path:
    value = json.loads(ENVIRONMENT.read_text())
    path = Path(value["executable"])
    if not path.is_file():
        raise FileNotFoundError(f"Existing RoboDojo environment unavailable: {path}")
    return path


def native_env(run: Path, python: Path) -> dict:
    env = os.environ.copy()
    folders = {
        "TMPDIR": DATA_ROOT / "tmp", "XDG_CACHE_HOME": DATA_ROOT / "cache",
        "XDG_CONFIG_HOME": run / "runtime-config", "XDG_DATA_HOME": run / "runtime-data",
        "XDG_RUNTIME_DIR": run / "runtime-dir", "HOME": run / "runtime-home",
        "ROBODOJO_DECISION_CACHE": DATA_ROOT / "cache",
        "__GL_SHADER_DISK_CACHE_PATH": DATA_ROOT / "cache/nvidia",
    }
    for name, folder in folders.items():
        folder.mkdir(parents=True, exist_ok=True)
        env[name] = str(folder)
    robo = SOURCE_ROOT / "RoboDojo"
    paths = [Path(__file__).resolve().parent, SOURCE_ROOT / "GPT-as-Policy", robo,
             robo / "XPolicyLab", robo / "third_party/curobo"]
    env["PYTHONPATH"] = ":".join(map(str, paths))
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1", OMNI_KIT_ACCEPT_EULA="YES",
               OMP_NUM_THREADS="2", MKL_NUM_THREADS="2", OPENBLAS_NUM_THREADS="1",
               ROBODOJO_HEADLESS="1", ROBODOJO_LIVE_PREVIEW="1", CUDA_VISIBLE_DEVICES="0")
    site = Path(subprocess.check_output([str(python), "-c", "import pathlib,site; "
        "print(next(str(pathlib.Path(p)/'isaacsim') for p in site.getsitepackages() "
        "if (pathlib.Path(p)/'isaacsim').is_dir()))"], text=True).strip())
    libs = [str(path) for ext in ("exts", "extsDeprecated") for path in (site/ext).rglob("*")
            if path.is_dir() and (path.name == "bin" or str(path).endswith("plugins/lib"))]
    env["LD_LIBRARY_PATH"] = ":".join(libs + [env.get("LD_LIBRARY_PATH", "")])
    env["VK_ICD_FILENAMES"] = "/usr/share/vulkan/icd.d/nvidia_icd.json"
    env["__EGL_VENDOR_LIBRARY_FILENAMES"] = "/usr/share/glvnd/egl_vendor.d/10_nvidia.json"
    return env


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_ready(proc: subprocess.Popen, logfile: Path, seconds: int = 1200) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"Simulator exited before RPC readiness: {proc.returncode}")
        if logfile.exists() and '"event": "ready"' in logfile.read_text(errors="replace")[-10000:]:
            return
        time.sleep(2)
    raise TimeoutError("Simulator RPC readiness deadline")


def run_control(task: str, layout: int, output: Path, key_file: Path | None,
                plan: dict, max_decisions: int, deadline: float, preflight: bool,
                controller_version: str) -> dict:
    from controller import DecisionClient
    import hybrid_rollout.robodojo.robodojo_server.gpt_only_client as native
    from hybrid_rollout.robodojo.robodojo_server.client import RPCClient

    native.MODEL = "gpt-6-luna"
    native.PROVIDER = "openai-decisions"
    native.EFFORT = "decisions"
    tools = native.GPTOnlyTools(output / "controller", task, sim_port=int(os.environ["ROBODOJO_RPC_PORT"]),
                                seed=layout, max_decisions=max_decisions,
                                prompt_sha256=hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest())
    tools.rpc_factory = lambda *a, **kw: RPCClient(*a, **dict(kw, timeout=None))
    history, stage = [], plan["initial_stage"]
    result = {"task": task, "layout": layout, "status": "started", "decisions": 0}
    try:
        call = tools.next_call()
        call.pop("tool")
        obs = tools.start(**call)
        if preflight:
            tools.finish("preflight_no_control")
            result["status"] = "preflight_complete"
            return result
        if key_file is None:
            raise ValueError("--key-file is required for control")
        model = DecisionClient(key_file, output / "decisions")
        if controller_version == "v5_probe_y":
            from probe_y import run_probe
            result.update(run_probe(tools, obs, model, output))
            return result
        if controller_version in ("v2", "v3", "v4", "v6", "v7", "v8", "v9", "v10_y_probe", "v11_edge_probe", "v12_confirm_probe", "v13_yellow_first"):
            from stage_controller import NO_MOTION, StageController
            stage_control = StageController(model, obs, plan,
                augmented=(controller_version in ("v3", "v4", "v6", "v7", "v8", "v9", "v10_y_probe", "v11_edge_probe", "v12_confirm_probe", "v13_yellow_first")),
                reobserve=(controller_version in ("v4", "v6", "v7", "v8", "v9", "v10_y_probe", "v11_edge_probe", "v12_confirm_probe", "v13_yellow_first")),
                geometry_cue=(controller_version in ("v6", "v7", "v8", "v9", "v10_y_probe", "v11_edge_probe", "v12_confirm_probe", "v13_yellow_first")),
                sign_gate=(controller_version in ("v7", "v8", "v9", "v10_y_probe", "v11_edge_probe", "v12_confirm_probe", "v13_yellow_first")),
                staged_micro=(controller_version in ("v8", "v9", "v10_y_probe", "v11_edge_probe", "v12_confirm_probe")),
                recovery_sweep=(controller_version in ("v9", "v10_y_probe", "v11_edge_probe", "v12_confirm_probe")),
                y_probe=(controller_version in ("v10_y_probe", "v11_edge_probe", "v12_confirm_probe")),
                edge_margin_probe=(controller_version in ("v11_edge_probe", "v12_confirm_probe")),
                visibility_confirmation=(controller_version == "v12_confirm_probe"),
                yellow_first=(controller_version == "v13_yellow_first"))
        else:
            stage_control = None
        while not obs["rollout_finished"]:
            if time.monotonic() > deadline:
                tools.finish("wall_budget_incomplete")
                result["status"] = "wall_budget_incomplete"
                break
            if stage_control is None:
                action, answers = model.decide(obs, plan, stage, history)
            else:
                # Zero-motion gates may advance several semantic stages using the same fresh view.
                for _ in range(4):
                    event = stage_control.inspect(obs, history)
                    if stage_control.stage not in NO_MOTION:
                        break
                    if event["stage_after"] == event["stage_before"]:
                        tools.finish("visual_gate_stalled_incomplete")
                        result["status"] = "visual_gate_stalled_incomplete"
                        result["gate_event"] = event
                        return result
                if stage_control.stage in NO_MOTION:
                    tools.finish("visual_gate_loop_incomplete")
                    result["status"] = "visual_gate_loop_incomplete"
                    return result
                if stage_control.stalled_reason:
                    tools.finish("visual_stall_incomplete")
                    result.update(status="visual_stall_incomplete",
                                  stall_reason=stage_control.stalled_reason,
                                  final_stage=stage_control.stage,
                                  stage_events=len(stage_control.events))
                    return result
                action, answers = stage_control.action(obs, history)
            native.validate_action(action, tools.request)
            call = tools.next_call()
            call.pop("tool")
            call["response"] = action
            next_obs = tools.act(**call)
            chosen_stage = answers["stage"] if stage_control is None else stage_control.stage
            history.append({"stage": chosen_stage, "step_before": obs["step_id"],
                            "step_after": next_obs["step_id"],
                            "model_choices": {k: v for k, v in answers.items() if not k.endswith("_held")},
                            "visible_predicates": {k: v for k, v in answers.items()
                                                   if k.endswith("_held") or k == "visible_goal_done"},
                            "target": action["target"],
                            "measured_eef_after": next_obs["current_eef"]})
            stage, obs = chosen_stage, next_obs
            result["decisions"] = len(history)
        if obs["rollout_finished"]:
            result["native_result"] = obs.get("result")
            native_result = result["native_result"] or {}
            if native_result.get("success") and native_result.get("complete"):
                result["status"] = "native_success"
            elif native_result.get("reason") == "decision_budget":
                result["status"] = "decision_budget_incomplete"
            elif native_result.get("complete"):
                result["status"] = "native_complete_failure"
            else:
                result["status"] = "native_incomplete"
        if stage_control is not None:
            result["stage_events"] = len(stage_control.events)
            result["final_stage"] = stage_control.stage
    except BaseException as error:
        result.update(status="controller_error", error_type=type(error).__name__, error=str(error))
        (output / "controller_error.txt").write_text(traceback.format_exc())
        if tools.sim is not None and tools.episode:
            try:
                tools.finish("controller_error")
            except Exception:
                pass
        raise
    finally:
        tools.close()
        (output / "episode_status.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=TASKS, required=True)
    parser.add_argument("--layout", type=int, default=0)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--max-decisions", type=int, default=30)
    parser.add_argument("--controller", choices=("v1", "v2", "v3", "v4", "v5_probe_y", "v6", "v7", "v8", "v9", "v10_y_probe", "v11_edge_probe", "v12_confirm_probe", "v13_yellow_first"), default="v1")
    parser.add_argument("--max-wall-seconds", type=int, default=6800)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.layout < 0 or args.max_decisions < 0 or not 1 <= args.max_wall_seconds <= 6900:
        parser.error("layout/max-decisions must be nonnegative; max-wall-seconds must be 1..6900")
    if args.controller == "v5_probe_y" and (args.task != "stack_blocks" or args.layout != 0):
        parser.error("v5_probe_y is a stack_blocks layout-0 calibration pilot")
    if args.controller in ("v6", "v7", "v8", "v9", "v10_y_probe", "v11_edge_probe", "v12_confirm_probe", "v13_yellow_first") and (args.task != "stack_blocks" or args.layout != 0):
        parser.error("RGB geometry cue is calibrated only for stack_blocks layout 0")
    python = executable()
    robo = SOURCE_ROOT / "RoboDojo"
    if not (robo / "Assets").is_dir() or not (robo / "XPolicyLab").is_dir():
        raise FileNotFoundError("Existing RoboDojo assets/source links unavailable")
    plan_file = args.plan or Path(__file__).resolve().parent / "plans" / f"{args.task}.json"
    plan = json.loads(plan_file.read_text())
    if plan.get("task") != args.task or plan["initial_stage"] not in plan["stages"]:
        raise ValueError("Task plan mismatch")
    output = DATA_ROOT / "runs" / args.run_name
    if args.dry_run:
        print(json.dumps({"python": str(python), "sources": str(SOURCE_ROOT),
                          "data_root": str(DATA_ROOT), "output": str(output),
                          "task": args.task, "layout": args.layout, "plan": str(plan_file)}, indent=2))
        return
    if output.exists():
        raise FileExistsError(f"Run already exists; never overwrite: {output}")
    output.mkdir(parents=True)
    (output / "sim").mkdir()
    (output / "controller").mkdir()
    (output / "native_runtime").mkdir()
    (output / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    environment = native_env(output, python)
    sys.path[:0] = environment["PYTHONPATH"].split(":")
    port = free_port()
    command = [str(python), str(Path(__file__).resolve().parent / "sim_server.py"),
               "--task", args.task, "--output", str(output / "sim"),
               "--port", str(port), "--eval-seed", "0"]
    (output / "launch.json").write_text(json.dumps({"command": command, "layout": args.layout,
        "started": dt.datetime.now().astimezone().isoformat(),
        "source": "existing read-only RoboDojo + GPT-as-Policy installation",
        "planner_model": "gpt-6.1-sol high via local Pro bridge",
        "decision_model": "gpt-6-luna via du cad/direct key",
        "input_contract": "current three RGB views and measured robot state only"}, indent=2))
    os.environ.update(environment)
    os.environ["ROBODOJO_RPC_PORT"] = str(port)
    simlog = output / "sim.log"
    with simlog.open("w") as logfile:
        deadline = time.monotonic() + args.max_wall_seconds
        process = subprocess.Popen(command, cwd=output / "native_runtime", env=environment,
                                   stdout=logfile, stderr=subprocess.STDOUT)
        try:
            wait_ready(process, simlog, min(1200, args.max_wall_seconds))
            result = run_control(args.task, args.layout, output, args.key_file, plan,
                                 args.max_decisions, deadline, args.preflight_only,
                                 args.controller)
            print(json.dumps(result, ensure_ascii=False), flush=True)
        finally:
            if process.poll() is None:
                try:
                    process.wait(timeout=25)
                except subprocess.TimeoutExpired:
                    process.send_signal(signal.SIGTERM)
                    try:
                        process.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == "__main__":
    main()

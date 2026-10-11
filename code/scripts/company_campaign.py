"""Run the frozen paired panel, retaining every attempt and hourly health records."""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time


def write(path, value):
    replacement = path.with_suffix(path.suffix + ".new")
    replacement.write_text(json.dumps(value, indent=2) + "\n")
    replacement.replace(path)


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def hourly_monitor(output, root, interval, done):
    while not done.wait(interval):
        progress = json.loads((output / "progress.json").read_text()) if (output / "progress.json").exists() else {}
        results = list(output.glob("*/result.json"))
        append(output / "hourly-checks.jsonl", dict(event="hourly_campaign_check", progress=progress,
            result_count=len(results), retained_failures=len(list(output.glob("*/attempt-*/failure.json"))),
            free_gb=shutil.disk_usage(root).free/1e9))


def append(path, value):
    with path.open("a") as stream:
        stream.write(json.dumps(dict(time=stamp(), **value)) + "\n")


def stop_child(process):
    if process is not None and process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=20)


def run_case(cfg, output, case, policy, observation, max_decisions=None):
    root = Path(cfg["root"])
    output.mkdir(parents=True, exist_ok=False)
    (output / "sim").mkdir()
    casefile = output / "case.json"
    write(casefile, case)
    actual = root / "robodojo" / case["layout"]
    if hashlib.sha256(actual.read_bytes()).hexdigest() != case["layout_sha256"]:
        raise ValueError("Layout differs from pinned manifest")
    effective = output / "config.json"
    write(effective, cfg)
    env = dict(os.environ)
    env.update(PYTHONPATH=os.pathsep.join([str(root / "controller/src"), str(root / "GPT-as-Policy"), str(root / "robodojo"), str(root / "robodojo/XPolicyLab")]),
        TMPDIR=str(root / ".cache/tmp"), XDG_CACHE_HOME=str(root / ".cache/xdg"),
        TORCH_EXTENSIONS_DIR=str(root / ".cache/torch-extensions"),
        OMNI_KIT_ACCEPT_EULA="YES", ACCEPT_EULA="Y", PYTHONNOUSERSITE="1",
        CUDA_VISIBLE_DEVICES=str(cfg["gpu_ids"][0]), COMPANY_OBSERVATION=observation,
        COMPANY_LAYOUT_SHA256=case["layout_sha256"], COMPANY_LAYOUT_PATH=str(actual.resolve()),
        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    env['COMPANY_ORACLE_GEOMETRY'] = '1' if cfg.get('oracle_geometry', False) and observation == 'oracle' else '0'
    port = cfg["base_port"]
    sim_command = [cfg["sim_python"], "-u", "-m", "realman_jev.company_bridge", "--task", case["runtime_task"],
        "--eval-seed", str(case["eval_seed"]), "--output", str(output / "sim"), "--port", str(port),
        "--headless", "--enable_cameras", "--device", "cuda:0",
        f"--kit_args=--/exts/omni.kit.registry.nucleus/cachePath={root}/.cache/kit-extensions "
        f"--/renderer/activeGpu={cfg['gpu_ids'][0]} --/renderer/multiGpu/enabled=false "
        "--/app/updateOrder/checkForHydraRenderComplete=1000 "
        "--/app/renderer/waitIdle=true --/app/hydraEngine/waitIdle=true"]
    policy_command = [cfg["sim_python"], "-u", "-m", "realman_jev.company_policy", "--config", str(effective),
        "--case", str(casefile), "--api-config", str(cfg.get("api_config", root / "controller/config/api.company.local.json")),
        "--policy", policy, "--observation", observation, "--port", str(port), "--output", str(output / "policy")]
    if max_decisions:
        policy_command += ["--max-decisions", str(max_decisions)]
    write(output / "launch.json", dict(sim=sim_command, policy=policy_command, started=stamp(),
        controller_commit=subprocess.check_output(["git", "-C", str(root / "controller"), "rev-parse", "HEAD"], text=True).strip()))
    server = controller = None
    started = time.monotonic()
    last_hour = started
    status = "starting"
    try:
        with (output / "server.log").open("w") as simlog, (output / "policy.log").open("w") as policylog:
            server = subprocess.Popen(sim_command, cwd=root / "robodojo", env=env, stdout=simlog, stderr=subprocess.STDOUT, start_new_session=True)
            write(output / "processes.json", dict(simulator_pid=server.pid))
            while True:
                if server.poll() is not None:
                    raise RuntimeError(f"Simulator exited before ready: {server.returncode}")
                # The RPC server is single-owner: readiness MUST NOT open a socket.
                if '"event": "ready"' in (output / "server.log").read_text(errors="replace"):
                    break
                if time.monotonic()-started > cfg["startup_timeout_s"]:
                    raise TimeoutError("Simulator startup timeout")
                if Path(cfg["stop_file"]).exists():
                    raise InterruptedError("Operator stop")
                time.sleep(2)
            controller = subprocess.Popen(policy_command, cwd=root / "controller", env=env, stdout=policylog, stderr=subprocess.STDOUT, start_new_session=True)
            write(output / "processes.json", dict(simulator_pid=server.pid, policy_pid=controller.pid))
            append(output / "health.jsonl", dict(event="started", simulator_pid=server.pid, policy_pid=controller.pid))
            while controller.poll() is None:
                now = time.monotonic()
                events = output / "policy/events.jsonl"
                heartbeat = events.stat().st_mtime if events.exists() else (output / "policy.log").stat().st_mtime
                if now-last_hour >= cfg["hourly_check_s"]:
                    append(output / "health.jsonl", dict(event="hourly_check", elapsed_s=now-started,
                        simulator_alive=server.poll() is None, policy_alive=True,
                        seconds_since_event=time.time()-heartbeat, free_gb=shutil.disk_usage(root).free/1e9))
                    last_hour = now
                if Path(cfg["stop_file"]).exists():
                    raise InterruptedError("Operator stop")
                if shutil.disk_usage(root).free < cfg["minimum_free_gb"]*1e9:
                    raise RuntimeError("Project filesystem reserve reached")
                if server.poll() is not None:
                    raise RuntimeError("Simulator exited while policy was running")
                if time.time()-heartbeat > cfg["stalled_seconds"]:
                    raise TimeoutError("Policy heartbeat stalled")
                if now-started > cfg["timeout_s"]+cfg["startup_timeout_s"]+300:
                    raise TimeoutError("Worker hard wall-clock limit")
                time.sleep(5)
            summary_path = output / "policy/summary.json"
            if not summary_path.exists():
                raise RuntimeError(f"Policy exited without summary: {controller.returncode}")
            summary = json.loads(summary_path.read_text())
            native_path = output / "sim/evaluation_outcome.json"
            native = json.loads(native_path.read_text()) if native_path.exists() else {}
            native_invalid = native.get("status") == "invalid_native_layout"
            if native_invalid:
                summary.update(status="invalid_native_layout", native_evaluation=native,
                               complete=False, physical_success=False)
            status = summary["status"]
            if controller.returncode and not native_invalid:
                raise RuntimeError(f"Policy failed: {summary.get('error_type')}: {summary.get('error')}")
            # Let the bridge finalize mp4 headers and native results before kill fallback.
            try:
                server.wait(timeout=60)
            except subprocess.TimeoutExpired:
                append(output / "health.jsonl", dict(event="repair", action="terminate_owned_server_after_policy_finished"))
            native_path = output / "sim/evaluation_outcome.json"
            if native_path.exists():
                summary["native_evaluation"] = json.loads(native_path.read_text())
            command = [cfg["sim_python"], "-m", "realman_jev.company_audit", "--sim-dir", str(output / "sim"), "--policy-dir", str(output / "policy")]
            if cfg["vision_projection_validated"]:
                command += ["--projection-validated"]
            subprocess.run(command, env=env, cwd=root / "controller", check=True, stdout=policylog, stderr=subprocess.STDOUT)
            report_env = dict(env, PYTHONPATH=env["PYTHONPATH"]+os.pathsep+str(root/"controller/scripts"))
            subprocess.run([cfg["sim_python"], "-c", "import sys; from company_report import render; from pathlib import Path; print(render(Path(sys.argv[1])))", str(output/"policy")],
                           env=report_env, cwd=root/"controller", check=True, stdout=policylog, stderr=subprocess.STDOUT)
            return summary
    except Exception as exc:
        status = "infrastructure_error"
        write(output / "failure.json", dict(status=status, error_type=type(exc).__name__, message=str(exc)[:800], time=stamp()))
        raise
    finally:
        stop_child(controller)
        stop_child(server)
        if (output / "policy/config.json").exists() and not (output / "policy/decision-audit.jsonl").exists():
            try:
                command = [cfg["sim_python"], "-m", "realman_jev.company_audit", "--sim-dir", str(output/"sim"), "--policy-dir", str(output/"policy")]
                subprocess.run(command, env=env, cwd=root/"controller", check=True, capture_output=True, timeout=120)
            except Exception as exc:
                append(output / "health.jsonl", dict(event="audit_finalize_error", error_type=type(exc).__name__))
        append(output / "health.jsonl", dict(event="finished", status=status, elapsed_s=time.monotonic()-started))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--smoke-observation", choices=["oracle", "vision"], default="oracle")
    p.add_argument("--smoke-task", default="general_pickup")
    p.add_argument("--smoke-policy", choices=['jev', 'gpt6_jev'], default='jev')
    p.add_argument("--smoke-decisions", type=int, default=3)
    args = p.parse_args()
    cfg = json.loads(args.config.read_text())
    manifest = json.loads(args.manifest.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "campaign.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        identity = dict(config=cfg, manifest_sha256=hashlib.sha256(args.manifest.read_bytes()).hexdigest(), smoke=args.smoke)
        frozen = args.output / "frozen.json"
        if frozen.exists() and json.loads(frozen.read_text()) != identity:
            raise ValueError("Configuration differs from frozen campaign")
        write(frozen, identity)
        monitor_done = threading.Event()
        threading.Thread(target=hourly_monitor, args=(args.output, cfg["root"], cfg["hourly_check_s"], monitor_done), daemon=True).start()
        cases = manifest["cases"]
        queue = [(policy, observation, case) for policy in ("jev", "gpt6_jev") for observation in ("oracle", "vision") for case in cases]
        if args.smoke:
            queue = [(args.smoke_policy, args.smoke_observation, next(c for c in cases if c["task"] == args.smoke_task))]
        for number, (policy, observation, case) in enumerate(queue):
            name = f'{number:03d}-{policy}-{observation}-{case["runtime_task"]}-{case["layout_id"]}'
            case_root = args.output / name
            if (case_root / "result.json").exists():
                continue
            case_root.mkdir(exist_ok=True)
            attempt = len(list(case_root.glob("attempt-*")))
            # Failed attempts remain visible. A restart resumes at the first unfinished
            # case; it never counts a retry as an extra independent trial.
            write(args.output / "progress.json", dict(status="running", active=name, completed=number, planned=len(queue), updated=stamp()))
            try:
                result = run_case(cfg, case_root / f"attempt-{attempt:02d}", case, policy, observation,
                                  args.smoke_decisions if args.smoke else None)
                write(case_root / "result.json", result)
                from company_report import report
                report(args.output)
            except Exception as exc:
                write(args.output / "progress.json", dict(status="needs_repair", active=name, completed=number,
                    planned=len(queue), error=str(exc)[:800], updated=stamp()))
                # Unknown faults require diagnosis; never silently skip an experimental case.
                raise
        write(args.output / "progress.json", dict(status="finished", completed=len(queue), planned=len(queue), updated=stamp()))
        monitor_done.set()


if __name__ == "__main__":
    main()

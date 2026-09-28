"""One native no-rollback episode: actuator checks and local direction probes.

This deliberately does NOT pretend sequential motions are paired amplitude trials.
The existing bridge forbids reset/rollback; exact paired trials use MuJoCo first.
"""
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

import numpy as np
from scipy.spatial.transform import Rotation

from run_position_pilot import Jev, dump, state_for


def run(rec, with_jev):
    cfg = rec.cfg
    root = Path(cfg["existing_root"])
    paths = [root/"controller/src", root/"GPT-as-Policy", root/"robodojo", root/"robodojo/XPolicyLab"]
    for p in reversed(paths):
        sys.path.insert(0, str(p))
    from hybrid_rollout.robodojo.robodojo_server.protocol import RPCClient
    from realman_jev.robodojo import targets_for
    manifest = json.loads((root/"controller/config/company-assets-manifest.json").read_text())
    case = next(c for c in manifest["cases"] if c["runtime_task"] == "stack_blocks"
                and c["layout_id"] == cfg["robodojo_layout_id"])
    layout = root/"robodojo"/case["layout"]
    if hashlib.sha256(layout.read_bytes()).hexdigest() != case["layout_sha256"]:
        raise RuntimeError("Frozen RoboDojo layout hash mismatch")
    dump(rec.folder/"case.json", case)
    port = cfg["port"]
    with socket.socket() as check:
        check.bind(("127.0.0.1", port))
    gpu_info = subprocess.check_output(["nvidia-smi", "--query-gpu=index,memory.used", "--format=csv,noheader,nounits"], text=True)
    memory = dict((int(row.split(",")[0]), int(row.split(",")[1])) for row in gpu_info.strip().splitlines())
    if memory[cfg["gpu"]] > 1024:
        raise RuntimeError("Configured GPU is occupied; no process preemption allowed")
    dump(rec.folder/"gpu-before.json", dict(memory_mib=memory))
    cache = rec.folder.parent/"cache"
    for name in ("tmp", "xdg", "torch-extensions", "kit-extensions"):
        (cache/name).mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(map(str, paths)),
               TMPDIR=str(cache/"tmp"), XDG_CACHE_HOME=str(cache/"xdg"),
               TORCH_EXTENSIONS_DIR=str(cache/"torch-extensions"),
               PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
               OMNI_KIT_ACCEPT_EULA="YES", ACCEPT_EULA="Y",
               CUDA_VISIBLE_DEVICES=str(cfg["gpu"]), COMPANY_OBSERVATION="oracle",
               COMPANY_LAYOUT_PATH=str(layout.resolve()), COMPANY_LAYOUT_SHA256=case["layout_sha256"],
               COMPANY_ORACLE_GEOMETRY=str(int(cfg.get("robodojo_task_mode") == "stage_stack")), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    output = rec.folder/"simulator"
    output.mkdir()
    command = [cfg["robodojo_python"], "-B", "-u", "-m", "realman_jev.company_bridge",
               "--task", "stack_blocks", "--eval-seed", str(case["eval_seed"]),
               "--output", str(output), "--port", str(port), "--headless", "--enable_cameras",
               "--device", "cuda:0",
               f"--kit_args=--/exts/omni.kit.registry.nucleus/cachePath={cache}/kit-extensions "
               f"--/renderer/activeGpu={cfg['gpu']} --/renderer/multiGpu/enabled=false "
               "--/app/updateOrder/checkForHydraRenderComplete=1000 "
               "--/app/renderer/waitIdle=true --/app/hydraEngine/waitIdle=true"]
    dump(rec.folder/"launch.json", dict(command=command, cwd=str(root/"robodojo"),
        observation="oracle", paired_amplitude_supported=False, note="Existing bridge permits exactly one fresh episode"))
    log_path = rec.folder/"simulator.log"
    rpc = model = None
    episode, tick = None, 0
    with log_path.open("w") as logfile:
        process = subprocess.Popen(command, cwd=root/"robodojo", env=env, stdout=logfile,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        dump(rec.folder/"owned_process.json", dict(pid=process.pid, pgid=process.pid))
        try:
            start = time.monotonic()
            while True:
                rec.check_budget()
                if process.poll() is not None:
                    raise RuntimeError(f"Isaac startup exited with {process.returncode}; see simulator.log")
                # Do not probe the socket: native RPC accepts a single owner only.
                if '"event": "ready"' in log_path.read_text(errors="replace"):
                    break
                if time.monotonic()-start > cfg["robodojo_startup_timeout_seconds"]:
                    raise RuntimeError("Isaac startup timeout")
                time.sleep(2)
            rec.event(dict(kind="simulator_ready", startup_seconds=time.monotonic()-start))
            rpc = RPCClient("127.0.0.1", port, timeout=180)
            dump(rec.folder/"native_metadata.json", rpc.request("metadata"))
            reset = rpc.request("reset", seed=case["layout_id"], source="gpt_eef",
                                policy_version="jev_rsi_development_probe_v1")
            episode, tick = reset["episode_id"], reset["step_id"]
            dump(rec.folder/"reset.json", reset)
            if cfg.get("robodojo_task_mode") == "stage_stack":
                from robodojo_stack import run_stack
                run_stack(rec, rpc, reset)
                return

            def call(op, **kwargs):
                return rpc.request(op, episode_id=episode, step_id=tick, **kwargs)

            def observe():
                return call("teacher_observation")

            def compact(obs):
                return {k: obs[k] for k in ("states", "eef_positions", "eef_quaternions_wxyz", "remaining_steps")}

            def move(delta):
                nonlocal tick
                rec.check_budget()
                before = observe()
                primitive = dict(arm="right", delta=np.asarray(delta).tolist(), rotation=[0., 0., 0.], gripper="hold")
                targets = targets_for(before, primitive, .011, .001)
                acks = []
                for _ in range(cfg["robodojo_motion_ticks"]):
                    proposal = call("eef_joint_target", targets=targets)
                    command = np.asarray(proposal["action"], np.float32)
                    command[:7] = before["states"][:7]
                    ack = call("chunk_step", actions=command.reshape(1, 14), controller="jev_rsi_position_probe")
                    tick = ack["step_id"]
                    acks.append(dict(step_id=tick, action=command, ik=proposal, steps=ack["steps"]))
                    if any(r["terminated"] or r["truncated"] for r in ack["steps"]):
                        raise RuntimeError("Native episode ended during local probe")
                after = observe()
                q0 = np.asarray(before["eef_quaternions_wxyz"])[1, [1, 2, 3, 0]]
                q1 = np.asarray(after["eef_quaternions_wxyz"])[1, [1, 2, 3, 0]]
                return dict(before=compact(before), after=compact(after), acks=acks,
                    actual_delta_m=after["eef_positions"][1]-before["eef_positions"][1],
                    target_tracking_error_m=float(np.linalg.norm(after["eef_positions"][1]-targets["right"]["position"])),
                    inactive_arm_displacement_m=float(np.linalg.norm(after["eef_positions"][0]-before["eef_positions"][0])),
                    orientation_drift_rad=float((Rotation.from_quat(q1)*Rotation.from_quat(q0).inv()).magnitude()),
                    stable=None, settling_protocol="fixed_15_native_ticks_NOT_certified_stable",
                    reset_identical=False, state_protocol="sequential_native_no_rollback")

            # Sequential + and - motions are never labeled repeated identical states.
            for axis in range(-1, 3):
                for sign in ([0] if axis == -1 else [-1, 1]):
                    delta = np.zeros(3)
                    if axis >= 0:
                        delta[axis] = sign*.002
                    rec.branch(dict(kind="actuator", axis=axis, sign=sign, requested_delta_m=delta, **move(delta)))
            if with_jev:
                model = Jev(rec)
                offsets = [(0.02, 0, 0), (-.02, 0, 0), (0, .005, 0), (0, -.005, 0), (0, 0, .01), (0, 0, -.01)]
                for i, offset in enumerate(offsets[:cfg["max_jev_decisions"]]):
                    obs = observe()
                    position = np.asarray(obs["eef_positions"])[1]
                    target = position + offset
                    state = state_for(position, target, "airborne_local_position_probe", cfg,
                        gripper_opening=float(obs["states"][13]),
                        orientation_quaternion_wxyz=obs["eef_quaternions_wxyz"][1].tolist())
                    state["coordinate_frame"] = "environment_origin_m_link6"
                    decision = model.choose(state, dict(stage=state["stage"], phase_index=i, environment="robodojo",
                        trajectory_id=episode, native_step=tick, layout_id=case["layout_id"],
                        stage_scope="synthetic local position goal in stack scene; not a manipulation subtask"))
                    dump(rec.folder/decision["decision_id"]/"native_state.json", compact(obs))
                    vector = np.asarray(decision["signs"], float)
                    if np.linalg.norm(vector):
                        vector /= np.linalg.norm(vector)
                    result = move(vector*.002)
                    before_error = float(np.linalg.norm(target-position))
                    after_error = float(np.linalg.norm(target-np.asarray(result["after"]["eef_positions"])[1]))
                    rec.branch(dict(kind="direction_probe", decision_id=decision["decision_id"], stage=state["stage"],
                        amplitude_m=.002, goal_position_m=target, goal_error_before_m=before_error,
                        goal_error_after_m=after_error, loss_decrease_m2=(before_error**2-after_error**2)/2, **result))
            dump(rec.folder/"native_finish.json", call("finish_pilot", reason="local_diagnostic_finished_NOT_full_stack_success"))
        finally:
            if model is not None:
                model.close()
            if rpc is not None:
                rpc.close()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            rec.event(dict(kind="owned_simulator_closed", pid=process.pid, returncode=process.returncode))

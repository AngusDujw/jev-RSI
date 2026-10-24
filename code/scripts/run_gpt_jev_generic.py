"""One bounded LIBERO episode: generic GPT contracts -> real Jev -> OSC_POSE.

No task-specific stage tables, object truth, segmentation IDs, physics previews,
or success predicates enter planning or execution. Native evaluation is terminal.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import io
import json
import logging
import math
import os
from pathlib import Path
import sys
import time
import urllib.request

from gpt_jev_contract import CAPABILITIES, CAMERAS, english, jev_request, parse_jev, schema, validate


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def scrub(value):
    if isinstance(value, str) and value.startswith("data:image/"):
        return dict(image_sha256=hashlib.sha256(value.encode()).hexdigest(), characters=len(value))
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k != "encrypted_content"}
    return value


def post(url, payload, path):
    english(payload)
    save(path.with_suffix(".request.json"), scrub(payload))
    started = time.monotonic()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with opener.open(request, timeout=900) as response:
            raw = json.load(response)
        save(path.with_suffix(".response.json"), raw)
        return raw
    except Exception as error:
        save(path.with_suffix(".failure.json"), dict(error_type=type(error).__name__,
            elapsed_s=time.monotonic()-started, usage_unknown=True, dispatched=False))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--libero-root", type=Path, required=True)
    parser.add_argument("--suite", default="libero_goal")
    parser.add_argument("--task-id", type=int, required=True)
    parser.add_argument("--init-index", type=int, default=0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--bridge", default="http://127.0.0.1:7921")
    parser.add_argument("--jev-model", default="jev-1.13.0")
    parser.add_argument("--max-jev", type=int, default=160)
    parser.add_argument("--max-plans", type=int, default=8)
    parser.add_argument("--max-native-steps", type=int, default=600)
    parser.add_argument("--wall-seconds", type=int, default=2400)
    args = parser.parse_args()
    from urllib.parse import urlsplit
    endpoint = urlsplit(args.bridge)
    if endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1" or endpoint.port != 7921 or endpoint.path or endpoint.query:
        parser.error("Use the explicit loopback bridge on port 7921")
    repo = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if not output.is_relative_to(repo / "code/runs") or output.exists():
        parser.error("Output must be a new directory inside project code/runs")
    if not (1 <= args.max_plans <= 12 and 1 <= args.max_jev <= 200 and 1 <= args.max_native_steps <= 800):
        parser.error("Invalid bounded episode budgets")
    output.mkdir(parents=True)
    cache = output / "runtime"
    cache.mkdir()
    config_dir = cache / "libero-config"
    config_dir.mkdir()
    base = args.libero_root / "libero/libero"
    save(config_dir / "config.yaml", dict(benchmark_root=str(base), bddl_files=str(base / "bddl_files"),
        init_states=str(base / "init_files"), datasets=str(args.libero_root / "libero/datasets"), assets=str(base / "assets")))
    os.environ.update(LIBERO_CONFIG_PATH=str(config_dir),
        MUJOCO_GL="egl", TMPDIR=str(cache), XDG_CACHE_HOME=str(cache),
        NUMBA_CACHE_DIR=str(cache / "numba"), MPLCONFIGDIR=str(cache / "matplotlib"))
    os.environ.setdefault("MUJOCO_EGL_DEVICE_ID", "0")
    sys.path.insert(0, str(args.libero_root))
    import cv2
    import numpy as np
    from scipy.spatial.transform import Rotation
    # This installed robosuite hardcodes a global temporary log. Relocate only
    # that handler during import; never change the installed package or file.
    original_handler = logging.FileHandler
    def project_handler(filename, *handler_args, **handler_kwargs):
        if str(filename) == "/tmp/robosuite.log":
            filename = cache / "robosuite.log"
        return original_handler(filename, *handler_args, **handler_kwargs)
    logging.FileHandler = project_handler
    try:
        from libero.libero import benchmark
        from libero.libero.envs.env_wrapper import ControlEnv
        from robosuite.utils.camera_utils import get_real_depth_map, get_camera_intrinsic_matrix, get_camera_extrinsic_matrix
    finally:
        logging.FileHandler = original_handler
    from libero_robot_geometry import gripper_geometry

    prompt_path = repo / "code/prompts/gpt_jev_planner_v1.txt"
    prompt = prompt_path.read_text()
    english(prompt)
    save(output / "protocol.json", dict(arguments={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(), capabilities=CAPABILITIES,
        planner_model="gpt-6-astra", effort="xhigh", auth="local ChatGPT Pro", decision_endpoint="official Jev via loopback relay",
        task_specific_recipes=False, hidden_state_to_models=False, evaluator_access="terminal only",
        scope="single development episode; not a generalization or speed comparison"))
    started = time.monotonic()
    env = None
    native_steps = jev_calls = plan_calls = 0
    history, plan_records = [], []
    last_grip = "open"
    termination = "not_started"
    error_type = None
    native_success = None
    plan = None
    with contextlib.redirect_stdout(io.StringIO()):
        suite = benchmark.get_benchmark_dict()[args.suite](0)
    task = suite.get_task(args.task_id)
    english(task.language)
    save(output / "task.json", dict(language=task.language, suite=args.suite, task_id=args.task_id, init_index=args.init_index))

    def budget():
        if time.monotonic() - started >= args.wall_seconds:
            raise RuntimeError("wall_budget")
        if native_steps >= args.max_native_steps:
            raise RuntimeError("native_step_budget")

    def views(label):
        result = {}
        for camera in CAMERAS:
            rgb = np.ascontiguousarray(obs[camera + "_image"][::-1])
            depth = get_real_depth_map(env.sim, obs[camera + "_depth"])[::-1].squeeze()
            result[camera] = dict(rgb=rgb, depth=depth,
                K=get_camera_intrinsic_matrix(env.sim, camera, 768, 768),
                T=get_camera_extrinsic_matrix(env.sim, camera))
            cv2.imwrite(str(output / f"{label}-{camera}.jpg"), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        return result

    def planner(reason, previous, check):
        nonlocal plan_calls
        budget()
        if plan_calls >= args.max_plans:
            raise RuntimeError("planner_budget")
        view = views(f"plan-{plan_calls:02d}")
        content = []
        camera_metadata = {}
        for camera, value in view.items():
            ok, image = cv2.imencode(".jpg", cv2.cvtColor(value["rgb"], cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not ok:
                raise ValueError("Camera encoding failed")
            content += [dict(type="input_text", text=f"Current camera {camera}; image 768x768; pixel origin top left"),
                dict(type="input_image", image_url="data:image/jpeg;base64," + base64.b64encode(image).decode(), detail="high")]
            camera_metadata[camera] = dict(K=value["K"].tolist(), camera_to_world_opencv=value["T"].tolist())
        if previous is not None:
            for camera, value in previous.items():
                ok, image = cv2.imencode(".jpg", cv2.cvtColor(value["rgb"], cv2.COLOR_RGB2BGR))
                content += [dict(type="input_text", text=f"Previous planning observation camera {camera}"),
                    dict(type="input_image", image_url="data:image/jpeg;base64," + base64.b64encode(image).decode(), detail="high")]
        own_geometry = gripper_geometry(env, obs)
        pads = own_geometry["pad_vertices_tool"]
        own = dict(pad_center_in_tool_m=((pads.min(axis=0)+pads.max(axis=0))/2).tolist(),
            pad_extent_in_tool_m=(pads.max(axis=0)-pads.min(axis=0)).tolist(),
            tcp_position_world_m=obs["robot0_eef_pos"].tolist(),
            tcp_quaternion_xyzw=obs["robot0_eef_quat"].tolist(),
            gripper_qpos_m=obs["robot0_gripper_qpos"].tolist(), last_gripper_command=last_grip)
        runtime = dict(instruction=task.language, reason=reason, visual_check=check,
            capabilities=CAPABILITIES, robot=own, cameras=camera_metadata,
            native_steps=native_steps, last_plan=plan, recent_acknowledged_execution=history[-6:])
        content.append(dict(type="input_text", text=json.dumps(runtime)))
        payload = dict(model="gpt-6-astra", reasoning=dict(effort="xhigh"), instructions=prompt,
            input=[dict(role="user", content=content)],
            tools=[dict(type="function", name="submit_plan", description="Submit a grounded executable stage contract or a supported stop/completion claim", parameters=schema())],
            tool_choice=dict(type="function", name="submit_plan"), parallel_tool_calls=False, store=False)
        index = plan_calls
        plan_calls += 1
        raw = post(args.bridge + "/responses", payload, output / f"planner-{index:02d}")
        if not raw.get("model", "").startswith("gpt-6-astra") or raw.get("status") != "completed":
            raise ValueError("Unexpected planner completion")
        calls = [item for item in raw.get("output", []) if item.get("type") == "function_call"]
        if len(calls) != 1 or calls[0].get("name") != "submit_plan":
            raise ValueError("Expected one submit_plan call")
        proposed = validate(json.loads(calls[0]["arguments"]))
        if proposed["status"] == "complete" and not native_steps:
            raise ValueError("Cannot claim completion before any execution")
        coordinates = {}
        measurements = []
        for anchor in proposed["anchors"]:
            value = view[anchor["camera"]]
            u, v = anchor["pixel"]
            r = anchor["radius_px"]
            if not (r <= u < 768-r and r <= v < 768-r):
                raise ValueError("Anchor patch crosses image boundary")
            patch = value["depth"][v-r:v+r+1, u-r:u+r+1]
            if not np.isfinite(patch).all() or patch.min() < .02 or patch.max() > 3 or np.ptp(patch) > .025:
                raise ValueError("Anchor depth missing or discontinuous")
            z = float(np.median(patch))
            K, T = value["K"], value["T"]
            point = T[:3, :3] @ np.array([(u-K[0, 2])*z/K[0, 0], (v-K[1, 2])*z/K[1, 1], z]) + T[:3, 3]
            coordinates[anchor["id"]] = point
            measurements.append(dict(**anchor, depth_m=z, world_m=point.tolist()))
        record = dict(plan=proposed, anchor_measurements=measurements, native_steps=native_steps,
            actual_planner_model=raw["model"], usage=raw.get("usage"))
        plan_records.append(record)
        save(output / f"plan-{index:02d}.json", record)
        print(json.dumps(dict(event="plan", index=index, status=proposed["status"], stages=len(proposed["stages"]), steps=native_steps)), flush=True)
        return proposed, coordinates, view

    try:
        env = ControlEnv(bddl_file_name=suite.get_task_bddl_file_path(args.task_id),
            camera_names=list(CAMERAS), camera_heights=768, camera_widths=768,
            camera_depths=True, control_freq=20, horizon=args.max_native_steps,
            controller="OSC_POSE", initialization_noise=None)
        env.seed(args.seed)
        env.reset()
        obs = env.set_init_state(np.asarray(suite.get_task_init_states(args.task_id)[args.init_index], float))
        for _ in range(10):
            obs, _, _, _ = env.step(np.array([0., 0., 0., 0., 0., 0., -1.]))
        # Ten settling steps are recorded separately, not hidden in policy cost.
        termination = "running"
        plan, anchors, earlier_views = planner("initial", None, "Infer a feasible local strategy from current observations")
        while plan["status"] == "plan":
            review_reason = "plan_exhausted"
            review_check = "Check actual object effects and determine the next grounded plan"
            review_now = False
            calls_since_review = 0
            for stage_index, stage in enumerate(plan["stages"]):
                start_position = obs["robot0_eef_pos"].copy()
                start_rotation = Rotation.from_quat(obs["robot0_eef_quat"])
                goal_rotation = Rotation.from_rotvec(stage["rotation_delta_world_rad"]) * start_rotation
                point = start_position if stage["target"]["anchor"] == "tcp" else anchors[stage["target"]["anchor"]]
                target = point + np.asarray(stage["target"]["offset_m"])
                if stage["target"]["tool_point"] == "pad_center":
                    pads = gripper_geometry(env, obs)["pad_vertices_tool"]
                    center = (pads.min(axis=0)+pads.max(axis=0))/2
                    target = target - goal_rotation.apply(center)
                if np.linalg.norm(target-start_position) > .6:
                    raise ValueError("Stage goal exceeds local reach bound")
                executed = stalled = 0
                advance = False
                for local in range(40):
                    budget()
                    if jev_calls >= args.max_jev:
                        raise RuntimeError("jev_budget")
                    err = target - obs["robot0_eef_pos"]
                    rot = (goal_rotation * Rotation.from_quat(obs["robot0_eef_quat"]).inv()).as_rotvec()
                    grip_ok = stage["gripper"] == "keep" or stage["gripper"] == last_grip
                    ready = bool(np.linalg.norm(err) <= .008 and np.linalg.norm(rot) <= .06 and executed >= stage["min_steps"] and grip_ok)
                    request = jev_request(stage, err.tolist(), rot.tolist(), last_grip, executed, ready, args.jev_model)
                    index = jev_calls
                    jev_calls += 1
                    calls_since_review += 1
                    raw = post(args.bridge + "/systemone", request, output / f"jev-{index:03d}")
                    choices = parse_jev(request, raw)
                    edge = choices["transition"]
                    if edge in ("review", "stop"):
                        save(output / f"dispatch-{index:03d}.json", dict(dispatched=False, reason=edge, native_steps=native_steps))
                        if edge == "stop":
                            raise RuntimeError("jev_stop")
                        review_reason, review_now = "jev_requested_review", True
                        break
                    signs = np.array([{"negative": -1, "hold": 0, "positive": 1}[choices[a]] for a in ("x", "y", "z", "rx", "ry", "rz")])
                    delta, rotation = signs[:3]*np.minimum(abs(err)*.65, .02), signs[3:]*np.minimum(abs(rot)*.65, .10)
                    for vector, limit in ((delta, .02), (rotation, .10)):
                        norm = np.linalg.norm(vector)
                        if norm > limit:
                            vector *= limit/norm
                    chosen_grip = last_grip if choices["gripper"] == "keep" else choices["gripper"]
                    action = np.r_[delta/.05, rotation/.5, -1. if chosen_grip == "open" else 1.]
                    before = obs["robot0_eef_pos"].copy()
                    count = min(3, args.max_native_steps-native_steps)
                    acknowledged = 0
                    try:
                        for _ in range(count):
                            budget()
                            obs, _, _, _ = env.step(action)
                            native_steps += 1
                            acknowledged += 1
                    finally:
                        receipt = dict(jev_decision=index, plan=plan_calls-1, stage=stage["id"], choices=choices,
                            action=action.tolist(), before=before.tolist(), after=obs["robot0_eef_pos"].tolist(),
                            target=target.tolist(), acknowledged_steps=acknowledged, native_steps=native_steps,
                            rotation_error_before_rad=rot.tolist(), pose_gate_before=ready)
                        save(output / f"dispatch-{index:03d}.json", receipt)
                        history.append(receipt)
                    last_grip = chosen_grip
                    executed = executed+count if stage["gripper"] == "keep" or last_grip == stage["gripper"] else 0
                    stalled = stalled+1 if np.linalg.norm(obs["robot0_eef_pos"]-before) < .0008 and np.linalg.norm(err) > .015 else 0
                    if edge == "advance":
                        advance = True
                        print(json.dumps(dict(event="stage", stage=stage["id"], steps=native_steps, jev_calls=jev_calls)), flush=True)
                        break
                    if stalled >= 3 or calls_since_review >= 40:
                        review_reason, review_now = "motion_stall" if stalled >= 3 else "review_lease_expired", True
                        break
                if not advance:
                    review_now = True
                    if review_reason == "plan_exhausted":
                        review_reason = "stage_budget"
                review_check = stage["visual_check"]
                if review_now or stage["review_after"] or stage_index >= 3:
                    if not review_now:
                        review_reason = "stage_visual_review"
                    break
            plan, anchors, earlier_views = planner(review_reason, earlier_views, review_check)
        termination = "planner_" + plan["status"]
    except Exception as error:
        error_type = type(error).__name__
        termination = str(error)[:160] if isinstance(error, (RuntimeError, ValueError)) else "infrastructure_error"
        save(output / "failure.json", dict(error_type=error_type, reason=termination,
            native_steps=native_steps, jev_calls=jev_calls, plan_calls=plan_calls))
        print(json.dumps(dict(event="failure", error_type=error_type, reason=termination)), flush=True)
    finally:
        if env is not None:
            try:
                views("final")
                native_success = bool(env.check_success())
            finally:
                env.close()
        summary = dict(termination=termination, error_type=error_type, native_success=native_success,
            policy_native_steps=native_steps, settling_native_steps=10 if env is not None else 0,
            jev_requests=jev_calls, planner_requests=plan_calls,
            elapsed_s=time.monotonic()-started, scope="one development episode; no generalization or acceleration claim")
        save(output / "summary.json", summary)
        print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()

"""Bounded program-building GPT + real Jev LIBERO development episode."""
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time

from gpt_jev_contract import CAMERAS, english, parse_jev
from gpt_jev_program_worker import validate_source
from run_gpt_jev_generic import post, save


def object_schema(properties):
    return dict(type="object", properties=properties, required=list(properties), additionalProperties=False)


TEXT = dict(type="string")
METHOD_SCHEMA = object_schema({k: TEXT for k in ("explanation", "source", "interface", "jev_protocol")})
REVIEW_SCHEMA = object_schema(dict(
    status=dict(type="string", enum=["continue", "complete", "stop"]), explanation=TEXT,
    parameters_json=TEXT,
    points=dict(type="array", maxItems=10, items=object_schema(dict(name=TEXT, camera=dict(type="string", enum=list(CAMERAS)),
        pixel=dict(type="array", items=dict(type="integer"), minItems=2, maxItems=2), radius=dict(type="integer", minimum=1, maximum=6)))),
    regions=dict(type="array", maxItems=6, items=object_schema(dict(name=TEXT, camera=dict(type="string", enum=list(CAMERAS)),
        box=dict(type="array", items=dict(type="integer"), minItems=4, maxItems=4))))))


def validate_questions(questions, control=False):
    if not isinstance(questions, dict) or not 1 <= len(questions) <= 8:
        raise ValueError("Expected 1..8 Jev questions")
    if control and set(questions) != {"x", "y", "z", "rx", "ry", "rz", "gripper"}:
        raise ValueError("Control requires seven documented questions")
    for name, q in questions.items():
        if not name.isidentifier() or not isinstance(q, dict) or set(q) != {"type", "instructions", "criteria"}:
            raise ValueError("Invalid question definition")
        if q["type"] != "choice" or not isinstance(q["instructions"], str) or not 1 <= len(q["instructions"]) <= 2000:
            raise ValueError("Invalid choice instructions")
        criteria = q["criteria"]
        if not isinstance(criteria, dict) or not 2 <= len(criteria) <= 8 or any(not isinstance(v, str) or not v for v in criteria.values()):
            raise ValueError("Invalid choice criteria")
        if control and set(criteria) != ({"open", "close", "keep"} if name == "gripper" else {"negative", "hold", "positive"}):
            raise ValueError("Control options do not match dispatch mapping")
    english(questions)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--libero-root", type=Path, required=True)
    p.add_argument("--suite", default="libero_goal")
    p.add_argument("--task-id", type=int, required=True)
    p.add_argument("--init-index", type=int, default=0)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--gpu", default="4")
    p.add_argument("--bridge", default="http://127.0.0.1:7921")
    p.add_argument("--max-gpt", type=int, default=14)
    p.add_argument("--max-jev", type=int, default=200)
    p.add_argument("--max-native-steps", type=int, default=600)
    p.add_argument("--max-repairs", type=int, default=2)
    p.add_argument("--wall-seconds", type=int, default=3600)
    args = p.parse_args()
    repo = Path(__file__).resolve().parents[2]
    out = args.output.resolve()
    if args.bridge != "http://127.0.0.1:7921" or out.exists() or not out.is_relative_to(repo / "code/runs"):
        p.error("Use a new project code/runs directory and the explicit loopback relay")
    if not (1 <= args.max_gpt <= 24 and 1 <= args.max_jev <= 300 and 1 <= args.max_native_steps <= 800 and 0 <= args.max_repairs <= 3):
        p.error("Invalid episode budget")
    out.mkdir(parents=True)
    cache = out / "runtime"
    config = cache / "libero-config"
    config.mkdir(parents=True)
    base = args.libero_root / "libero/libero"
    save(config / "config.yaml", dict(benchmark_root=str(base), bddl_files=str(base / "bddl_files"),
        init_states=str(base / "init_files"), datasets=str(args.libero_root / "libero/datasets"), assets=str(base / "assets")))
    os.environ.update(LIBERO_CONFIG_PATH=str(config), MUJOCO_GL="egl", MUJOCO_EGL_DEVICE_ID=args.gpu,
        TMPDIR=str(cache), XDG_CACHE_HOME=str(cache), NUMBA_CACHE_DIR=str(cache / "numba"),
        MPLCONFIGDIR=str(cache / "matplotlib"), OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    sys.path.insert(0, str(args.libero_root))
    import cv2
    import numpy as np
    from scipy.spatial.transform import Rotation
    handler = logging.FileHandler
    def local_handler(filename, *a, **kw):
        return handler(cache / "robosuite.log" if str(filename) == "/tmp/robosuite.log" else filename, *a, **kw)
    logging.FileHandler = local_handler
    try:
        from libero.libero import benchmark
        from libero.libero.envs.env_wrapper import ControlEnv
        from robosuite.utils.camera_utils import get_real_depth_map, get_camera_intrinsic_matrix, get_camera_extrinsic_matrix
    finally:
        logging.FileHandler = handler
    from libero_robot_geometry import gripper_geometry
    prompt = (repo / "code/prompts/gpt_jev_method_v2.txt").read_text()
    manual = (repo / "code/prompts/gpt_jev_program_api_v2.md").read_text()
    english([prompt, manual])
    save(out / "protocol.json", dict(arguments={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(), manual_sha256=hashlib.sha256(manual.encode()).hexdigest(),
        planner="gpt-6-astra/xhigh/local ChatGPT Pro", executor="real jev-1.13.0/official systemone",
        native_evaluation="terminal only; never in policy input", task_recipes=False, stage_templates=False))
    with contextlib.redirect_stdout(io.StringIO()):
        suite = benchmark.get_benchmark_dict()[args.suite](0)
    task = suite.get_task(args.task_id)
    english(task.language)
    save(out / "task.json", dict(language=task.language, suite=args.suite, task_id=args.task_id, init_index=args.init_index))
    started = time.monotonic()
    env = worker = None
    videos = {}
    obs = None
    native_steps = jev_calls = gpt_calls = rpc_calls = 0
    last_grip = "open"
    history, methods, previous = [], [], None
    termination, success, result = "not_started", None, None
    own_method_error = None

    def budgets():
        return dict(gpt_remaining=args.max_gpt-gpt_calls, jev_remaining=args.max_jev-jev_calls,
                    native_steps_remaining=args.max_native_steps-native_steps,
                    wall_seconds_remaining=max(0, args.wall_seconds-(time.monotonic()-started)))

    def budget():
        if time.monotonic()-started >= args.wall_seconds:
            raise RuntimeError("wall_budget")
        if native_steps >= args.max_native_steps:
            raise RuntimeError("native_step_budget")

    def state():
        geom = gripper_geometry(env, obs)
        pads, fingers = geom["pad_vertices_tool"], geom["finger_vertices_tool"]
        return dict(frame_id=native_steps, native_steps=native_steps, budgets=budgets(),
            tcp_position_world_m=obs["robot0_eef_pos"].tolist(), tcp_quaternion_xyzw=obs["robot0_eef_quat"].tolist(),
            gripper_qpos_m=obs["robot0_gripper_qpos"].tolist(), last_gripper_command=last_grip,
            own_geometry=dict(pad_center_in_tool_m=((pads.min(0)+pads.max(0))/2).tolist(),
                pad_extent_in_tool_m=(pads.max(0)-pads.min(0)).tolist(),
                finger_low_offset_tool_m=fingers.min(0).tolist(), finger_high_offset_tool_m=fingers.max(0).tolist()))

    def view(camera):
        if camera not in CAMERAS:
            raise ValueError("Unknown camera")
        return dict(rgb=np.ascontiguousarray(obs[camera+"_image"][::-1]),
            depth=get_real_depth_map(env.sim, obs[camera+"_depth"])[::-1].squeeze(),
            K=get_camera_intrinsic_matrix(env.sim, camera, 768, 768), T=get_camera_extrinsic_matrix(env.sim, camera))

    def point(camera, pixel, radius=3):
        if len(pixel) != 2 or any(type(x) is not int for x in pixel) or type(radius) is not int or not 1 <= radius <= 6:
            raise ValueError("Invalid pixel patch")
        u, v = pixel
        if not (radius <= u < 768-radius and radius <= v < 768-radius):
            raise ValueError("Patch crosses image boundary")
        data = view(camera)
        z = data["depth"][v-radius:v+radius+1, u-radius:u+radius+1]
        if not np.isfinite(z).all() or z.min() < .02 or z.max() > 3 or np.ptp(z) > .025:
            raise ValueError("Invalid or discontinuous surface depth")
        depth = float(np.median(z))
        xyz = data["T"][:3, :3] @ (np.linalg.solve(data["K"], [u, v, 1.])*depth) + data["T"][:3, 3]
        return dict(world_m=xyz.tolist(), depth_m=depth, frame_id=native_steps, pixel=pixel)

    def cloud(camera, box, stride=6):
        if len(box) != 4 or any(type(x) is not int for x in box) or type(stride) is not int or not 4 <= stride <= 32:
            raise ValueError("Invalid region")
        x0, y0, x1, y1 = box
        if not (0 <= x0 < x1 <= 768 and 0 <= y0 < y1 <= 768):
            raise ValueError("Region crosses image boundary")
        data = view(camera)
        v, u = np.mgrid[y0:y1:stride, x0:x1:stride]
        uv = np.column_stack((u.ravel(), v.ravel()))
        z = data["depth"][uv[:, 1], uv[:, 0]]
        good = np.isfinite(z) & (z > .02) & (z < 3)
        uv, z = uv[good], z[good]
        rays = np.linalg.solve(data["K"], np.column_stack((uv, np.ones(len(uv)))).T).T
        xyz = (rays*z[:, None]) @ data["T"][:3, :3].T + data["T"][:3, 3]
        return dict(world_m=xyz.tolist(), rgb=data["rgb"][uv[:, 1], uv[:, 0]].tolist(), pixels=uv.tolist(), frame_id=native_steps)

    def planner(kind, question, failed_method=None):
        nonlocal gpt_calls, previous
        budget()
        if gpt_calls >= args.max_gpt:
            raise RuntimeError("gpt_budget")
        index = gpt_calls
        gpt_calls += 1
        current, content, cameras = {}, [], {}
        for camera in CAMERAS:
            data = view(camera)
            ok, encoded = cv2.imencode(".jpg", cv2.cvtColor(data["rgb"], cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])
            if not ok:
                raise RuntimeError("image_encoding")
            (out / f"gpt-{index:02d}-{camera}.jpg").write_bytes(encoded.tobytes())
            np.savez_compressed(out / f"gpt-{index:02d}-{camera}.npz", depth=data["depth"], K=data["K"], T=data["T"])
            current[camera] = encoded.tobytes()
            cameras[camera] = dict(K=data["K"].tolist(), camera_to_world_opencv=data["T"].tolist())
            content.extend([dict(type="input_text", text=f"Current {camera}; frame {native_steps}; 768x768"),
                dict(type="input_image", image_url="data:image/jpeg;base64,"+base64.b64encode(encoded).decode(), detail="high")])
        if previous:
            for camera, encoded in previous.items():
                content.extend([dict(type="input_text", text=f"Earlier review {camera}"),
                    dict(type="input_image", image_url="data:image/jpeg;base64,"+base64.b64encode(encoded).decode(), detail="high")])
        payload_state = dict(instruction=task.language, question=question, robot=state(), cameras=cameras,
            recent_acknowledged_execution=history[-5:])
        if failed_method:
            payload_state["previous_method"] = failed_method
        content.append(dict(type="input_text", text=json.dumps(payload_state)))
        instructions = prompt+"\n\n"+manual if kind == "method" else (
            "Review the actual current and earlier robot images. Answer the requested evidence question and supply named visible surface points or regions when useful. "
            "Return submit_review only, all text English ASCII. parameters_json must encode an object with concise actionable numeric or boolean observations requested by the caller. "
            "Do not invent hidden geometry or treat closed fingers as retention. A completion claim is not native success. "
            "The caller can process point clouds; use regions if a single point cannot represent the required geometry. No task recipes or hidden evaluator access exist.")
        tool = "submit_method" if kind == "method" else "submit_review"
        payload = dict(model="gpt-6-astra", reasoning=dict(effort="xhigh"), instructions=instructions,
            input=[dict(role="user", content=content)], tools=[dict(type="function", name=tool, description="Return the requested executable method or observation review", parameters=METHOD_SCHEMA if kind == "method" else REVIEW_SCHEMA)],
            tool_choice=dict(type="function", name=tool), parallel_tool_calls=False, store=False)
        raw = post(args.bridge+"/responses", payload, out / f"gpt-{index:02d}")
        if not raw.get("model", "").startswith("gpt-6-astra") or raw.get("status") != "completed":
            raise ValueError("Unexpected planner response")
        calls = [x for x in raw.get("output", []) if x.get("type") == "function_call"]
        if len(calls) != 1 or calls[0].get("name") != tool:
            raise ValueError("Expected one matching function call")
        answer = json.loads(calls[0]["arguments"])
        english(answer)
        previous = current
        save(out / f"gpt-{index:02d}.parsed.json", answer)
        print(json.dumps(dict(event="gpt", index=index, kind=kind, frame=native_steps)), flush=True)
        return answer

    def review(question):
        if not isinstance(question, str) or not 1 <= len(question) <= 6000:
            raise ValueError("Invalid review question")
        answer = planner("review", question)
        parameters = json.loads(answer["parameters_json"])
        if not isinstance(parameters, dict):
            raise ValueError("Review parameters must be an object")
        english(parameters)
        points, regions, errors = {}, {}, []
        for item in answer["points"]:
            try:
                points[item["name"]] = point(item["camera"], item["pixel"], item["radius"])
            except ValueError as error:
                errors.append(dict(name=item["name"], error=str(error)))
        for item in answer["regions"]:
            try:
                regions[item["name"]] = cloud(item["camera"], item["box"])
            except ValueError as error:
                errors.append(dict(name=item["name"], error=str(error)))
        return dict(status=answer["status"], explanation=answer["explanation"], parameters=parameters,
                    points=points, regions=regions, measurement_errors=errors, frame_id=native_steps)

    def choose(questions, features):
        nonlocal jev_calls
        budget()
        validate_questions(questions)
        if jev_calls >= args.max_jev:
            raise RuntimeError("jev_budget")
        request = dict(model="jev-1.13.0", state=dict(robot=state(), processed_features=features,
            feature_source="GPT-authored program; not an independent sensor"), questions=questions)
        index = jev_calls
        jev_calls += 1
        raw = post(args.bridge+"/systemone", request, out / f"jev-{index:03d}")
        return dict(choices=parse_jev(request, raw), frame_id=native_steps, decision=index)

    def control(target, quaternion, gripper, questions, features=None, tool_point="tcp",
                translation_limit=.02, rotation_limit=.10, steps=3, position_tolerance=.006, rotation_tolerance=.06):
        nonlocal native_steps, last_grip
        budget()
        validate_questions(questions, control=True)
        target, quaternion = np.asarray(target, float), np.asarray(quaternion, float)
        if target.shape != (3,) or quaternion.shape != (4,) or not np.isfinite(np.r_[target, quaternion]).all() or not .99 <= np.linalg.norm(quaternion) <= 1.01:
            raise ValueError("Invalid target pose")
        if gripper not in ("open", "close", "keep") or tool_point not in ("tcp", "pad_center"):
            raise ValueError("Invalid gripper/tool point")
        if not (.001 <= translation_limit <= .02 and .01 <= rotation_limit <= .10 and type(steps) is int and 1 <= steps <= 3 and .002 <= position_tolerance <= .012 and .02 <= rotation_tolerance <= .10):
            raise ValueError("Invalid controller bounds")
        desired = Rotation.from_quat(quaternion)
        if tool_point == "pad_center":
            target = target-desired.apply(state()["own_geometry"]["pad_center_in_tool_m"])
        before = obs["robot0_eef_pos"].copy()
        err = target-before
        if np.linalg.norm(err) > .6:
            raise ValueError("Goal exceeds local reach bound")
        rot = (desired*Rotation.from_quat(obs["robot0_eef_quat"]).inv()).as_rotvec()
        features = dict(program=features, objective=dict(gripper=gripper, tool_point=tool_point),
            translation_error_world_m=err.tolist(), rotation_error_world_rad=rot.tolist(),
            axes={axis: dict(error=float(e), goal_relation="within_tolerance" if abs(e) <= tol else "increase" if e > 0 else "decrease")
                  for axis, e, tol in zip(("x", "y", "z", "rx", "ry", "rz"), np.r_[err, rot], [position_tolerance/3**.5]*3+[rotation_tolerance/3**.5]*3)})
        decision = choose(questions, features)
        choices = decision["choices"]
        signs = np.array([{"negative": -1, "hold": 0, "positive": 1}[choices[a]] for a in ("x", "y", "z", "rx", "ry", "rz")])
        delta, rotation = signs[:3]*np.minimum(abs(err)*.65, translation_limit), signs[3:]*np.minimum(abs(rot)*.65, rotation_limit)
        for vector, limit in ((delta, translation_limit), (rotation, rotation_limit)):
            norm = np.linalg.norm(vector)
            if norm > limit:
                vector *= limit/norm
        grip = last_grip if choices["gripper"] == "keep" else choices["gripper"]
        action = np.r_[delta/.05, rotation/.5, -1. if grip == "open" else 1.]
        acknowledged = 0
        try:
            for _ in range(min(steps, args.max_native_steps-native_steps)):
                budget()
                step_env(action)
                native_steps += 1
                acknowledged += 1
        finally:
            after = obs["robot0_eef_pos"].copy()
            receipt = dict(decision=decision["decision"], choices=choices, action=action.tolist(), before=before.tolist(),
                after=after.tolist(), target_tcp=target.tolist(), acknowledged_steps=acknowledged,
                native_steps=native_steps, frame_id=native_steps)
            save(out / f"dispatch-{decision['decision']:03d}.json", receipt)
            history.append(receipt)
        last_grip = grip
        pos_error = float(np.linalg.norm(target-after))
        rot_error = float(np.linalg.norm((desired*Rotation.from_quat(obs["robot0_eef_quat"]).inv()).as_rotvec()))
        reached = pos_error <= position_tolerance and rot_error <= rotation_tolerance and (gripper == "keep" or grip == gripper)
        status = "reached" if reached else "stalled" if np.linalg.norm(after-before) < .0008 and pos_error > .015 else "moved"
        return dict(**receipt, status=status, position_error_m=pos_error, rotation_error_rad=rot_error)

    def step_env(action):
        nonlocal obs
        obs, _, _, _ = env.step(action)
        for camera, video in videos.items():
            video.write(cv2.cvtColor(np.ascontiguousarray(obs[camera+"_image"][::-1]), cv2.COLOR_RGB2BGR))

    def execute_method(method, number):
        nonlocal worker, rpc_calls
        validate_source(method["source"])
        path = out / f"method-{number:02d}.py"
        path.write_text(method["source"])
        save(out / f"method-{number:02d}.json", method)
        methods.append(dict(number=number, source_sha256=hashlib.sha256(method["source"].encode()).hexdigest()))
        child_env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "LD_LIBRARY_PATH", "TMPDIR", "XDG_CACHE_HOME")}
        worker = subprocess.Popen([sys.executable, "-B", str(Path(__file__).with_name("gpt_jev_program_worker.py"))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
            cwd=out, env=child_env, close_fds=True)
        worker.stdin.write(json.dumps(dict(source=method["source"]))+"\n")
        worker.stdin.flush()
        selector = selectors.DefaultSelector()
        selector.register(worker.stdout, selectors.EVENT_READ)
        sandbox = False
        allowed = dict(state=state, point=point, cloud=cloud, compose=lambda q, r: (Rotation.from_rotvec(r)*Rotation.from_quat(q)).as_quat().tolist(), review=review, choose=choose, control=control, note=lambda text: None)
        try:
            for _ in range(4000):
                budget()
                if not selector.select(timeout=5):
                    continue
                line = worker.stdout.readline()
                if not line:
                    raise RuntimeError("worker_exited: " + worker.stderr.read()[-1200:])
                message = json.loads(line)
                if message["kind"] == "sandbox":
                    sandbox = True
                    save(out / f"sandbox-{number:02d}.json", message)
                    worker.stdin.write('{"ready":true}\n')
                    worker.stdin.flush()
                    continue
                if not sandbox:
                    raise RuntimeError("Worker did not establish syscall isolation")
                if message["kind"] == "result":
                    return message["result"]
                if message["kind"] == "error":
                    raise RuntimeError(message["error"])
                if message["kind"] != "rpc":
                    raise ValueError("Invalid worker message")
                rpc_calls += 1
                record = dict(index=rpc_calls, method_number=number, request=message, frame_before=native_steps)
                try:
                    if message["method"] not in allowed:
                        raise ValueError("Unknown RPC method")
                    english(message)
                    response = dict(result=allowed[message["method"]](*message["args"], **message["kwargs"]))
                except (ValueError, TypeError, KeyError) as error:
                    response = dict(error=type(error).__name__+": "+str(error)[:1000])
                record.update(response=response, frame_after=native_steps)
                save(out / f"rpc-{rpc_calls:04d}.json", record)
                worker.stdin.write(json.dumps(response, allow_nan=False)+"\n")
                worker.stdin.flush()
            raise RuntimeError("rpc_budget")
        finally:
            selector.close()
            if worker.poll() is None:
                worker.terminate()
            worker.communicate(timeout=10)
            worker = None

    try:
        env = ControlEnv(bddl_file_name=suite.get_task_bddl_file_path(args.task_id), camera_names=list(CAMERAS),
            camera_heights=768, camera_widths=768, camera_depths=True, control_freq=20,
            horizon=args.max_native_steps+10, controller="OSC_POSE", initialization_noise=None)
        env.seed(args.seed)
        env.reset()
        obs = env.set_init_state(np.asarray(suite.get_task_init_states(args.task_id)[args.init_index], float))
        for camera in CAMERAS:
            writer = cv2.VideoWriter(str(out / f"{camera}.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 20., (768, 768))
            if not writer.isOpened():
                raise RuntimeError("Video writer unavailable")
            videos[camera] = writer
        for _ in range(10):
            step_env(np.array([0., 0., 0., 0., 0., 0., -1.]))
        termination = "running"
        previous_method = None
        question = "Build the complete processing method and Jev input/output cooperation from current observations."
        for revision in range(args.max_repairs+1):
            method = planner("method", question, previous_method)
            try:
                result = execute_method(method, revision)
                if not isinstance(result, dict) or type(result.get("completion_proposed")) is not bool:
                    raise ValueError("Return completion_proposed boolean and evidence")
                termination = "completion_proposed" if result["completion_proposed"] else "method_incomplete"
                break
            except (ValueError, RuntimeError) as error:
                own_method_error = str(error)[:1400]
                save(out / f"method-{revision:02d}.failure.json", dict(error=own_method_error, native_steps=native_steps))
                if own_method_error in ("gpt_budget", "jev_budget", "native_step_budget", "wall_budget"):
                    raise
                previous_method = method
                question = "Repair your complete method for the actual current scene. Executed actions persist. Failure: "+own_method_error
        else:
            termination = "repair_budget"
    except KeyboardInterrupt:
        termination = "agent_or_user_interrupted"
    except Exception as error:
        termination = str(error)[:160]
        save(out / "failure.json", dict(type=type(error).__name__, error=str(error), native_steps=native_steps))
    finally:
        if worker and worker.poll() is None:
            worker.terminate()
            worker.communicate(timeout=10)
        if env is not None:
            try:
                if obs is not None:
                    for camera in CAMERAS:
                        data = view(camera)
                        cv2.imwrite(str(out / f"final-{camera}.jpg"), cv2.cvtColor(data["rgb"], cv2.COLOR_RGB2BGR))
                    # Post-policy privileged snapshot for diagnostics only.
                    np.savez_compressed(out / "terminal-simulator-state.npz", qpos=env.sim.data.qpos.copy(),
                        qvel=env.sim.data.qvel.copy(), body_xpos=env.sim.data.body_xpos.copy())
                    success = bool(env.check_success())
            finally:
                env.close()
        for writer in videos.values():
            writer.release()
        summary = dict(termination=termination, native_success=success, result=result, native_steps=native_steps,
            settling_steps=10 if obs is not None else 0, jev_calls=jev_calls, gpt_calls=gpt_calls,
            rpc_calls=rpc_calls, elapsed_s=time.monotonic()-started, methods=methods, last_method_error=own_method_error)
        save(out / "summary.json", summary)
        print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()

"""Bounded program-building GPT + real Jev LIBERO development episode."""
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
import selectors
import subprocess
import sys
import time
import urllib.request
import urllib.error
import uuid

from gpt_jev_contract import CAMERAS, english, parse_jev
from gpt_jev_program_worker import validate_source
from gpt_jev_review_contract import compile_fields, validate_value
from run_gpt_jev_generic import save, scrub


def model_wire_numbers(value, *, preserve_tools=False):
    """Compact model inputs only; simulator, program data and receipts stay exact."""
    if isinstance(value, dict):
        return {key: json.loads(json.dumps(item, allow_nan=False)) if preserve_tools and key == "tools"
                else model_wire_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [model_wire_numbers(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Nonfinite model input")
        return float(format(value, ".6g"))
    return value


def post(url, payload, path, timeout=1800):
    """Bound model/classification transport by remaining episode time, before dispatch."""
    payload = model_wire_numbers(payload, preserve_tools=True)
    english(payload)
    save(path.with_suffix(".request.json"), scrub(payload))
    started = time.monotonic()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    headers = {"Content-Type": "application/json"}
    if url.endswith(("/responses", "/systemone")):
        ceiling = 900. if url.endswith("/systemone") else 3600.
        headers["X-Model-Request-Timeout-Seconds"] = str(max(.1, min(ceiling, timeout-2.)))
    if url.endswith("/responses"):
        headers["X-Request-ID"] = uuid.uuid4().hex
        headers["Prefer"] = "respond-async"
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    try:
        if url.endswith("/responses"):
            # A request ID is stable across transport retries, never across episodes.
            # The bridge owns inference; a broken polling socket cannot cancel it.
            active, reconnects = request, 0
            while True:
                remaining = timeout-(time.monotonic()-started)
                if remaining <= 0:
                    raise TimeoutError("Planner bridge unavailable until logical deadline")
                try:
                    with opener.open(url[:-len("/responses")]+"/", timeout=min(10, remaining)) as health:
                        asynchronous = json.load(health).get("transport") == "native-session"
                    break
                except (OSError, urllib.error.URLError, ValueError):
                    reconnects += 1
                    time.sleep(min(2, max(0, timeout-(time.monotonic()-started))))
            while True:
                remaining = timeout-(time.monotonic()-started)
                if remaining <= 0:
                    raise TimeoutError("Planner logical request deadline exceeded")
                save(path.with_suffix(".transport.json"), dict(request_id=headers["X-Request-ID"],
                    reconnects=reconnects, elapsed_s=time.monotonic()-started))
                try:
                    if active is request:
                        request.add_header("X-Model-Request-Timeout-Seconds",
                            str(max(.1, min(3600 if asynchronous else 1800, remaining-2))))
                    with opener.open(active, timeout=min(30, remaining) if asynchronous else remaining) as response:
                        result = json.load(response)
                        pending = response.status == 202
                except urllib.error.HTTPError as error:
                    if not asynchronous:
                        raise
                    body = error.read()
                    try:
                        detail = json.loads(body)
                    except (ValueError, UnicodeError):
                        detail = {}
                    if detail.get("terminal") or error.code not in (404, 408, 502, 503, 504):
                        raise
                    # Repost after a bridge restart: it resumes the same saved thread.
                    active = request
                    reconnects += 1
                    time.sleep(min(2, max(0, remaining)))
                    continue
                except (OSError, urllib.error.URLError, ValueError) as error:
                    if not asynchronous:
                        raise
                    reconnects += 1
                    active = request
                    time.sleep(min(2, max(0, remaining)))
                    continue
                if not pending:
                    break
                ident = result["job_id"]
                if ident != headers["X-Request-ID"]:
                    raise ValueError("Native bridge job ID mismatch")
                active = urllib.request.Request(url+"/jobs/"+ident)
                time.sleep(min(2, max(0, timeout-(time.monotonic()-started))))
        else:
            with opener.open(request, timeout=timeout) as response:
                result = json.load(response)
        save(path.with_suffix(".response.json"), result)
        return result
    except Exception as error:
        save(path.with_suffix(".failure.json"), dict(error_type=type(error).__name__,
            elapsed_s=time.monotonic()-started, usage_unknown=True,
            model_request_attempted=True, physical_dispatch=False,
            dispatched=False, dispatch_scope="physical_control_only"))
        raise


def object_schema(properties):
    return dict(type="object", properties=properties, required=list(properties), additionalProperties=False)


TEXT = dict(type="string")
METHOD_SCHEMA = object_schema({k: TEXT for k in ("explanation", "source", "interface", "jev_protocol")})
DESIGN_SCHEMA = object_schema({k: dict(type="string", minLength=1, maxLength=2200)
    for k in ("approach", "observations", "geometry", "gate_dependencies", "bounded_recovery", "jev_contract")})
PATCH_SCHEMA = object_schema(dict(explanation=TEXT, interface=TEXT, jev_protocol=TEXT,
    replacements=dict(type="array", minItems=1, maxItems=12, items=object_schema(dict(old=TEXT, new=TEXT)))))
REVIEW_SCHEMA = object_schema(dict(
    status=dict(type="string", enum=["continue", "complete", "stop"]), explanation=TEXT,
    parameters_json=TEXT,
    points=dict(type="array", maxItems=32, items=object_schema(dict(name=TEXT, camera=dict(type="string", enum=list(CAMERAS)),
        pixel=dict(type="array", items=dict(type="integer"), minItems=2, maxItems=2), radius=dict(type="integer", minimum=1, maximum=6)))),
    regions=dict(type="array", maxItems=8, items=object_schema(dict(name=TEXT, camera=dict(type="string", enum=list(CAMERAS)),
        box=dict(type="array", items=dict(type="integer"), minItems=4, maxItems=4), stride=dict(type="integer", minimum=4, maximum=32))))))


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


def bind_control_questions(questions):
    """Make each model-authored question's axis binding explicit on the wire."""
    validate_questions(questions, control=True)
    result = {}
    for name, question in questions.items():
        prefix = ("For the gripper question, read state.processed_features.objective.gripper and deliver that requirement. " if name == "gripper" else
            f"For axis {name}, read state.processed_features.axes.{name}.goal_relation only. Choose positive for increase, negative for decrease, and hold for within_tolerance. Other axes do not determine this answer. ")
        result[name] = dict(question, instructions=prefix+"Program-authored policy: "+question["instructions"])
    return result


def apply_method_patch(previous, patch):
    """Apply model-authored unique replacements; archive a complete method."""
    english(patch)
    replacements = patch.get("replacements")
    if not isinstance(replacements, list) or not 1 <= len(replacements) <= 12:
        raise ValueError("Expected 1..12 unique source replacements")
    source = previous["source"]
    for edit in replacements:
        if set(edit) != {"old", "new"} or not isinstance(edit["old"], str) or not edit["old"] or not isinstance(edit["new"], str):
            raise ValueError("Invalid source replacement")
        if source.count(edit["old"]) != 1:
            raise ValueError("Replacement old text must occur exactly once")
        source = source.replace(edit["old"], edit["new"], 1)
    validate_source(source)
    return dict(source=source, **{k: patch[k] for k in ("explanation", "interface", "jev_protocol")})


def compact_feedback(value):
    """Bound numeric observation feedback without inventing object semantics."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in ("rgb", "pixels"):
                continue
            if key == "world_m" and isinstance(item, list) and item and isinstance(item[0], list):
                import numpy as np
                points = np.asarray(item, float)
                if points.ndim == 2 and points.shape[1] == 3:
                    result["visible_world_summary"] = dict(count=len(points),
                        minimum=points.min(0).tolist(), median=np.median(points, axis=0).tolist(), maximum=points.max(0).tolist())
                    continue
            result[key] = compact_feedback(item)
        return result
    if isinstance(value, list):
        return [compact_feedback(x) for x in value[:40]]
    if isinstance(value, str):
        return value[:6000]
    return value


def repair_result_context(result):
    """Keep caller-defined outcome fields instead of assuming an evidence schema."""
    if not isinstance(result, dict):
        return dict(program_result=compact_feedback(result))
    returned = dict(result)
    context = dict(program_result=returned)
    evidence = returned.get("evidence")
    if isinstance(evidence, list) and len(evidence) > 12:
        returned["evidence"] = evidence[-12:]
        context["evidence_excerpt"] = dict(original_entries=len(evidence),
            omitted_earlier_entries=len(evidence)-12, retained_entries=12)
    return compact_feedback(context)


class ProgramMemory:
    """Caller-owned JSON checkpoints, scoped to one physical episode."""
    def __init__(self):
        self.entries = {}

    def manifest(self):
        return [{k: v for k, v in item.items() if k != "value"} for item in self.entries.values()]

    def put(self, key, value, frame_id, method):
        if not isinstance(key, str) or not 1 <= len(key) <= 64 or not key.isascii() or not all(c.isalnum() or c in "_.-" for c in key):
            raise ValueError("Checkpoint key must be 1..64 ASCII letters, digits, underscores, dots or hyphens")
        english(value)
        encoded = json.dumps(value, allow_nan=False)
        if len(encoded.encode()) > 16384:
            raise ValueError("Checkpoint value exceeds 16384 bytes")
        if key not in self.entries and len(self.entries) >= 16:
            raise ValueError("At most 16 checkpoints per episode")
        record = dict(key=key, frame_id=frame_id, method_number=method["number"],
            source_sha256=method["source_sha256"], bytes=len(encoded.encode()),
            value=json.loads(encoded), source="program-supplied historical data; not a fresh measurement")
        proposed = dict(self.entries, **{key: record})
        if sum(item["bytes"] for item in proposed.values()) > 131072:
            raise ValueError("Total checkpoint values exceed 131072 bytes")
        self.entries = proposed
        return {k: v for k, v in record.items() if k != "value"}

    def get(self, key=None):
        if key is None:
            return self.manifest()
        if key not in self.entries:
            raise ValueError("Unknown episode checkpoint")
        return json.loads(json.dumps(self.entries[key], allow_nan=False))


def intersect_plane(K, T, pixel, plane):
    """Calibrated ray/plane geometry, with no object identity inference."""
    import numpy as np
    K, T, pixel, plane = (np.asarray(x, float) for x in (K, T, pixel, plane))
    if K.shape != (3, 3) or T.shape != (4, 4) or pixel.shape != (2,) or plane.shape != (4,) or not np.isfinite(np.r_[K.ravel(), T.ravel(), pixel, plane]).all():
        raise ValueError("Invalid ray/plane input")
    if not np.all((pixel >= 0) & (pixel < 768)) or np.linalg.norm(plane[:3]) < 1e-8:
        raise ValueError("Invalid pixel or plane normal")
    normal = plane[:3]/np.linalg.norm(plane[:3])
    offset = plane[3]/np.linalg.norm(plane[:3])
    ray = T[:3, :3] @ np.linalg.solve(K, np.r_[pixel, 1.])
    ray /= np.linalg.norm(ray)
    denominator = float(np.dot(normal, ray))
    if abs(denominator) < .05:
        raise ValueError("Ray is parallel or grazing the supplied plane")
    distance = -(float(np.dot(normal, T[:3, 3]))+offset)/denominator
    if not .02 <= distance <= 3:
        raise ValueError("Plane intersection is behind camera or outside metric range")
    return (T[:3, 3]+distance*ray).tolist()


def control_lease(controller, target, quaternion, gripper, questions, features=None, max_calls=30, **limits):
    """Generic local feedback loop; every update still invokes real Jev."""
    if type(max_calls) is not int or not 1 <= max_calls <= 40:
        raise ValueError("Control lease max_calls must be integer 1..40")
    stalled = 0
    for index in range(max_calls):
        result = controller(target, quaternion, gripper, questions, features=features, **limits)
        stalled = stalled+1 if result["status"] == "stalled" else 0
        if result["status"] == "reached" or stalled >= 3:
            return dict(result, lease_calls=index+1)
    return dict(result, status="lease_exhausted", lease_calls=max_calls)


def planner_request_timeout(kind, staged_design=False, method_request_seconds=None):
    """Keep legacy defaults while allowing an explicit complete-method budget."""
    if kind == "method" and method_request_seconds is not None:
        return method_request_seconds
    return 900 if kind == "design" or (staged_design and kind == "method") else 1800


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
    p.add_argument("--method-file", type=Path, help="Reuse an archived GPT-generated method; acquisition cost remains in its original run")
    p.add_argument("--revise-archived", action="store_true", help="Ask GPT to revise the archived method using its adjacent summary.json")
    p.add_argument("--staged-design", action="store_true", help="Fresh generation: save a bounded design before materializing the complete method")
    p.add_argument("--method-request-seconds", type=int, choices=(900, 1800, 3600),
        help="Override the complete-method request deadline; design/review limits stay unchanged")
    p.add_argument("--no-video", action="store_true", help="Keep observation evidence without recording full episode videos")
    p.add_argument("--wall-seconds", type=int, default=3600)
    args = p.parse_args()
    repo = Path(__file__).resolve().parents[2]
    out = args.output.resolve()
    if args.bridge != "http://127.0.0.1:7921" or out.exists() or not out.is_relative_to(repo / "code/runs"):
        p.error("Use a new project code/runs directory and the explicit loopback relay")
    if not (1 <= args.max_gpt <= 40 and 1 <= args.max_jev <= 300 and 1 <= args.max_native_steps <= 800 and 0 <= args.max_repairs <= 5):
        p.error("Invalid episode budget")
    archived_method = None
    if args.method_file:
        method_path = args.method_file.resolve()
        if not method_path.is_relative_to(repo / "code/runs"):
            p.error("Archived method must be a project run artifact")
        archived_method = json.loads(method_path.read_text())
        if set(archived_method) != set(METHOD_SCHEMA["properties"]):
            p.error("Archived method has unexpected fields")
        english(archived_method)
        validate_source(archived_method["source"])
    if args.revise_archived and not archived_method:
        p.error("--revise-archived requires --method-file")
    if args.staged_design and archived_method:
        p.error("--staged-design is a fresh-generation condition, not archived-method reuse")
    require_typed_reviews = archived_method is None or args.revise_archived
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
    cv2.setNumThreads(1)
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
    from jev_rgbd_tracking import RGBDPatch
    prompt = (repo / "code/prompts/gpt_jev_method_v2.txt").read_text()
    lessons = (repo / "code/prompts/gpt_jev_method_lessons_v2.txt").read_text()
    design_prompt = (repo / "code/prompts/gpt_jev_design_v1.txt").read_text() if args.staged_design else None
    prompt += "\n\n"+lessons
    manual = (repo / "code/prompts/gpt_jev_program_api_v2.md").read_text()
    english([prompt, manual])
    if design_prompt is not None:
        english(design_prompt)
    save(out / "protocol.json", dict(arguments={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(), manual_sha256=hashlib.sha256(manual.encode()).hexdigest(),
        implementation_sha256={name: hashlib.sha256((repo / "code/scripts" / name).read_bytes()).hexdigest()
            for name in ("run_gpt_jev_program.py", "gpt_jev_program_worker.py", "gpt_jev_geometry.py", "gpt_jev_review_contract.py", "jev_rgbd_tracking.py")},
        planner="gpt-6-astra/xhigh/local ChatGPT Pro", executor="real jev-1.13.0/official systemone",
        native_evaluation="terminal only; never in policy input", task_recipes=False, stage_templates=False,
        model_wire_numeric_precision="data: 6 significant digits; tool schema constraints, internal calculations and receipts retain full precision",
        pro_request_deadline="loopback header bounds relay queue, SSE stream and retries; 2-second caller margin",
        review_parameters="method-declared fields use strict structured tool data and host validation; legacy JSON remains supported; no coercion",
        typed_reviews_required_for_generated_methods=True,
        method_request_deadline_seconds=planner_request_timeout("method", args.staged_design, args.method_request_seconds),
        staged_design=dict(enabled=args.staged_design,
            prompt_sha256=hashlib.sha256(design_prompt.encode()).hexdigest() if design_prompt else None,
            schema_sha256=hashlib.sha256(json.dumps(DESIGN_SCHEMA, sort_keys=True).encode()).hexdigest(),
            planning_request_deadline_seconds=900 if args.staged_design else 1800,
            executable_output="Complete four-string method; design alone is never executed"),
        reused_method_sha256=hashlib.sha256(archived_method["source"].encode()).hexdigest() if archived_method else None))
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
    rpc_feedback = []
    annotation_initial = annotation_last = None
    trackers = {}
    program_memory = ProgramMemory()
    termination, success, result = "not_started", None, None
    own_method_error = None
    method_design = None

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
        return dict(world_m=xyz.tolist(), depth_m=depth, frame_id=native_steps, pixel=pixel, camera=camera,
                    source="current_depth_patch_backprojection")

    def camera_geometry(camera):
        data = view(camera)
        return dict(K=data["K"].tolist(), camera_to_world_opencv=data["T"].tolist(), frame_id=native_steps)

    def plane_point(camera, pixel, plane):
        data = view(camera)
        return dict(world_m=intersect_plane(data["K"], data["T"], pixel, plane), pixel=pixel, camera=camera,
            plane=plane, frame_id=native_steps, source="calibrated_ray_intersection_with_program_supplied_plane")

    def track_init(camera, polygon):
        if len(trackers) >= 32:
            raise ValueError("At most 32 public patch trackers per episode")
        tracker = RGBDPatch(view(camera), polygon, native_steps)
        handle = "patch_"+str(len(trackers))
        trackers[handle] = tracker
        return dict(handle=handle, frame_id=native_steps, reference_features=len(tracker.reference),
                    camera=camera, method_number=methods[-1]["number"], source_sha256=methods[-1]["source_sha256"],
                    source="caller-selected visible RGB-D patch; not an object identity oracle")

    def checkpoint(key, value):
        record = program_memory.put(key, value, native_steps, methods[-1])
        save(out / "program-checkpoints.json", program_memory.entries)
        return record

    def track_update(handle):
        if handle not in trackers:
            raise ValueError("Unknown patch tracker handle")
        return trackers[handle].update({camera: view(camera) for camera in CAMERAS}, native_steps)

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
        return dict(world_m=xyz.tolist(), rgb=data["rgb"][uv[:, 1], uv[:, 0]].tolist(), pixels=uv.tolist(), frame_id=native_steps,
                    camera=camera, box=box, stride=stride, source="current_visible_depth_region_backprojection")

    def planner(kind, question, failed_method=None, review_context=None, parameter_schema=None):
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
            recent_acknowledged_execution=history[-5:], recent_program_feedback=rpc_feedback[-8:],
            program_checkpoint_manifest=program_memory.manifest())
        if annotation_last:
            payload_state["historical_named_observations"] = dict(initial=annotation_initial, previous=annotation_last,
                scope="Historical model labels and public measurements, not current object states. Preserve physical landmark identity across camera motion.")
            projections = {}
            for name, measured in annotation_last.get("points", {}).items():
                projections[name] = {}
                for camera, metadata in cameras.items():
                    position = np.linalg.solve(np.asarray(metadata["camera_to_world_opencv"]), np.r_[measured["world_m"], 1.])[:3]
                    if position[2] > .02:
                        pixel = np.asarray(metadata["K"]) @ position
                        projections[name][camera] = (pixel[:2]/pixel[2]).tolist()
            payload_state["historical_point_projections_if_stationary"] = projections
        if review_context is not None:
            payload_state["program_supplied_review_context"] = compact_feedback(review_context)
        if failed_method:
            payload_state["previous_method"] = failed_method
        if kind == "method" and method_design is not None:
            payload_state["method_design"] = dict(proposal=method_design,
                scope="Earlier model design, not sensor truth or executed actions; implementation must acquire runtime evidence")
        content.append(dict(type="input_text", text=json.dumps(model_wire_numbers(payload_state), separators=(",", ":"))))
        instructions = prompt+"\n\n"+manual if kind == "method" else (
            "Review the actual current and earlier robot images. Answer the requested evidence question and supply named visible surface points or regions when useful. "
            "Return submit_review only, all text English ASCII. parameters_json must encode an object with concise actionable numeric or boolean observations requested by the caller. "
            "The caller receives only measurements selected in this response; historical points shown in your context are not automatically returned to the program. "
            "Return all requested obtainable named points and regions, even if they were selected earlier. If a requested measurement is unavailable, explain the gap rather than silently assuming the caller has it. "
            "Apply the caller's evidence definitions at the scope of its proposed local action. Distinguish observed external obstruction, unobserved geometry, and robot self-occlusion; an unavailable global clearance certificate is not itself an observed obstruction. "
            "Assess a separately scoped observation-producing action using its current evidence rather than requiring evidence about a later action. When asked to check a local geometric-model hypothesis, report whether visible features support its stated assumptions and limits; do not invent hidden surfaces or a full-scene certificate. "
            "Do not invent hidden geometry or treat closed fingers as retention. A completion claim is not native success. "
            "The caller can process point clouds; use regions if a single point cannot represent the required geometry. No task recipes or hidden evaluator access exist.")
        if kind == "design":
            instructions = design_prompt+"\n\n"+lessons+"\n\n"+manual
        elif kind == "method" and method_design is not None:
            instructions += ("\n\nMATERIALIZATION STAGE: Implement the supplied method_design as the complete four-string method. "
                "Correct design defects when needed. A design is not a measurement receipt. Acquire current runtime evidence; "
                "do not embed this episode's pixels, measurements or frame-counter shortcuts as reusable observations. "
                "Return complete executable source, not stubs, pseudocode or a plan awaiting another coding step.")
        patching = kind == "method" and failed_method is not None
        if patching:
            instructions += ("\n\nREPAIR MODE: Return submit_method_patch with a small set of exact old/new source replacements applied to previous_method.source. "
                "The runtime will assemble and validate the complete executable method. Each old string must occur exactly once. "
                "Repair the diagnosed mechanism and any directly coupled defects; preserve useful existing processing and Jev definitions. "
                "Do not retransmit the whole source. Keep replacement text below 12000 characters when feasible. "
                "Provide updated concise interface and jev_protocol descriptions. A source patch is a method revision, never a motion command.")
        response_schema = DESIGN_SCHEMA if kind == "design" else PATCH_SCHEMA if patching else METHOD_SCHEMA if kind == "method" else REVIEW_SCHEMA
        if parameter_schema is not None:
            response_schema = json.loads(json.dumps(REVIEW_SCHEMA))
            del response_schema["properties"]["parameters_json"]
            response_schema["properties"]["parameters"] = parameter_schema
            response_schema["required"] = list(response_schema["properties"])
            instructions = instructions.replace(
                "parameters_json must encode an object with concise actionable numeric or boolean observations requested by the caller.",
                "parameters must match the method-declared strict schema exactly. Use the declared field names, types and enum literals. Schema adherence does not establish observation truth.")
        tool = "submit_design" if kind == "design" else "submit_method_patch" if patching else "submit_method" if kind == "method" else "submit_review"
        tool_definition = dict(type="function", name=tool,
            description="Return a bounded implementation design proposal without executable source" if kind == "design" else
                "Return the requested executable method, unique method patch, or observation review", parameters=response_schema)
        if parameter_schema is not None or kind == "design":
            tool_definition["strict"] = True
        payload = dict(model="gpt-6-astra", reasoning=dict(effort="xhigh"), instructions=instructions,
            input=[dict(role="user", content=content)], tools=[tool_definition],
            tool_choice=dict(type="function", name=tool), parallel_tool_calls=False, store=False)
        request_ceiling = planner_request_timeout(kind, args.staged_design, args.method_request_seconds)
        raw = post(args.bridge+"/responses", payload, out / f"gpt-{index:02d}", timeout=max(1, min(request_ceiling, budgets()["wall_seconds_remaining"])))
        if not raw.get("model", "").startswith("gpt-6-astra") or raw.get("status") != "completed":
            raise ValueError("Unexpected planner response")
        calls = [x for x in raw.get("output", []) if x.get("type") == "function_call"]
        if len(calls) != 1 or calls[0].get("name") != tool:
            raise ValueError("Expected one matching function call")
        answer = json.loads(calls[0]["arguments"])
        english(answer)
        if parameter_schema is not None or kind == "design":
            validate_value(answer, response_schema, tool)
        previous = current
        save(out / f"gpt-{index:02d}.parsed.json", answer)
        print(json.dumps(dict(event="gpt", index=index, kind=kind, frame=native_steps)), flush=True)
        return apply_method_patch(failed_method, answer) if patching else answer

    def review(question, context=None, fields=None):
        nonlocal annotation_initial, annotation_last
        if not isinstance(question, str) or not 1 <= len(question) <= 6000:
            raise ValueError("Invalid review question")
        if fields is None and (require_typed_reviews or len(methods) > 1):
            raise ValueError("Generated or repaired methods must declare review fields; free JSON is only for untouched archived methods")
        parameter_schema = compile_fields(fields) if fields is not None else None
        answer = planner("review", question, review_context=context, parameter_schema=parameter_schema)
        parameters = answer["parameters"] if parameter_schema is not None else json.loads(answer["parameters_json"])
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
                regions[item["name"]] = cloud(item["camera"], item["box"], item.get("stride", 6))
            except ValueError as error:
                errors.append(dict(name=item["name"], error=str(error)))
        result = dict(status=answer["status"], explanation=answer["explanation"], parameters=parameters,
                      points=points, regions=regions, measurement_errors=errors, frame_id=native_steps)
        annotation_last = compact_feedback(dict(frame_id=native_steps, parameters=parameters, points=points))
        if annotation_initial is None:
            annotation_initial = annotation_last
        return result

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
        raw = post(args.bridge+"/systemone", request, out / f"jev-{index:03d}", timeout=max(1, min(900, budgets()["wall_seconds_remaining"])))
        return dict(choices=parse_jev(request, raw), frame_id=native_steps, decision=index)

    def control(target, quaternion, gripper, questions, features=None, tool_point="tcp",
                translation_limit=.02, rotation_limit=.10, steps=3, position_tolerance=.006, rotation_tolerance=.06):
        nonlocal native_steps, last_grip
        budget()
        validate_questions(questions, control=True)
        questions = bind_control_questions(questions)
        target, quaternion = np.asarray(target, float), np.asarray(quaternion, float)
        if target.shape != (3,) or quaternion.shape != (4,) or not np.isfinite(np.r_[target, quaternion]).all() or not .99 <= np.linalg.norm(quaternion) <= 1.01:
            raise ValueError("Invalid target pose")
        if gripper not in ("open", "close", "keep") or tool_point not in ("tcp", "pad_center"):
            raise ValueError("Invalid gripper/tool point")
        if not (.001 <= translation_limit <= .02 and .01 <= rotation_limit <= .10 and type(steps) is int and 1 <= steps <= 3 and .0005 <= position_tolerance <= .012 and .01 <= rotation_tolerance <= .10):
            raise ValueError("Controller bounds: translation_limit 0.001..0.02 m; rotation_limit 0.01..0.10 rad; steps integer 1..3; position_tolerance 0.0005..0.012 m; rotation_tolerance 0.01..0.10 rad. Received "+str(dict(translation_limit=translation_limit, rotation_limit=rotation_limit, steps=steps, position_tolerance=position_tolerance, rotation_tolerance=rotation_tolerance)))
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
        linear_magnitude = np.where(abs(err) <= position_tolerance/3**.5, 0., np.minimum(abs(err)*.65, translation_limit))
        angular_magnitude = np.where(abs(rot) <= rotation_tolerance/3**.5, 0., np.minimum(abs(rot)*.65, rotation_limit))
        delta, rotation = signs[:3]*linear_magnitude, signs[3:]*angular_magnitude
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
        if jev_calls % 10 == 0:
            print(json.dumps(dict(event="control", jev_calls=jev_calls, native_steps=native_steps, position_error_m=pos_error, status=status)), flush=True)
        return dict(**receipt, status=status, position_error_m=pos_error, rotation_error_rad=rot_error)

    def step_env(action):
        nonlocal obs
        obs, _, _, _ = env.step(action)
        for camera, video in videos.items():
            video.write(cv2.cvtColor(np.ascontiguousarray(obs[camera+"_image"][::-1]), cv2.COLOR_RGB2BGR))

    def execute_method(method, number):
        nonlocal worker, rpc_calls, annotation_initial, annotation_last
        annotation_initial = annotation_last = None
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
        allowed = dict(state=state, point=point, cloud=cloud, camera=camera_geometry, plane_point=plane_point,
            track_init=track_init, track_update=track_update, checkpoint=checkpoint, recall=program_memory.get,
            compose=lambda q, r: (Rotation.from_rotvec(r)*Rotation.from_quat(q)).as_quat().tolist(), review=review, choose=choose, control=control, drive=lambda *a, **kw: control_lease(control, *a, **kw), note=lambda text: None)
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
                rpc_feedback.append(compact_feedback(dict(request=message, response=response, frame_id=native_steps)))
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
            if args.no_video:
                continue
            writer = cv2.VideoWriter(str(out / f"{camera}.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 20., (768, 768))
            if not writer.isOpened():
                raise RuntimeError("Video writer unavailable")
            videos[camera] = writer
        for _ in range(10):
            step_env(np.array([0., 0., 0., 0., 0., 0., -1.]))
        termination = "running"
        previous_method = None
        question = "Build the complete processing method and Jev input/output cooperation from current observations."
        if args.revise_archived:
            archived_summary = json.loads((args.method_file.resolve().parent / "summary.json").read_text())
            failure = repair_result_context(archived_summary.get("result"))
            for feedback_path in sorted(args.method_file.resolve().parent.glob("rpc-*.json"))[-8:]:
                recorded = json.loads(feedback_path.read_text())
                rpc_feedback.append(compact_feedback(dict(request=recorded.get("request"), response=recorded.get("response"),
                    frame_id=recorded.get("frame_after"), evidence_scope="archived previous episode; remeasure current geometry before acting")))
            previous_method = dict(archived_method, incomplete_result=failure)
            question = "Revise the complete archived GPT method using its recorded incomplete outcome and the current observations/API. Produce a concise executable method with feasible phase-local evidence and bounded recovery. Do not assume a previous physical action occurred in this newly initialized episode."
        if args.staged_design:
            method_design = planner("design", "Design a concise complete processing architecture and Jev cooperation before writing executable code.")
            save(out / "method-design.json", method_design)
            previous = None  # No physical action occurred; avoid duplicate same-frame images.
        for revision in range(args.max_repairs+1):
            method = previous_method
            try:
                method = archived_method if revision == 0 and archived_method and not args.revise_archived else planner("method", question, previous_method)
                result = execute_method(method, revision)
                if not isinstance(result, dict) or type(result.get("completion_proposed")) is not bool:
                    raise ValueError("Return completion_proposed boolean and evidence")
                if not result["completion_proposed"] and revision < args.max_repairs:
                    summary_evidence = repair_result_context(result)
                    previous_method = dict(method, incomplete_result=summary_evidence)
                    question = "Your method returned incomplete. Repair the full method using current images, executed effects, and its recorded limitations. The same physical scene persists; do not reset or assume actions were undone."
                    save(out / f"method-{revision:02d}.incomplete.json", result)
                    continue
                termination = "completion_proposed" if result["completion_proposed"] else "method_incomplete"
                break
            except (ValueError, RuntimeError, SyntaxError) as error:
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

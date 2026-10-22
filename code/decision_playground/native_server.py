"""Simulator-thread, loopback-only Playground RPC; never calls a model API.

Run with the RoboICL simulator interpreter and its usual robodojo CLI arguments.
PLAYGROUND_RPC_PORT and PLAYGROUND_OUTPUT are required. Each connection carries
newline-delimited JSON requests; every request requires a unique request_id.
"""
from __future__ import annotations

import base64
import importlib
import io
import inspect
import json
import os
from pathlib import Path
import signal
import socket
import sys
import time
import types
import uuid


def expanded_limit(official, multiplier):
    if type(official) is not int or official <= 0 or type(multiplier) is not int or multiplier not in (1, 5):
        raise ValueError('Playground supports a positive official limit and explicit 1x or 5x budget')
    return official * multiplier


class OfflineClient:
    def __init__(self, *args, **kwargs):
        pass

    def call(self, *, func_name, **kwargs):
        if func_name != "reset":
            raise RuntimeError(f"Model transport disabled: {func_name}")

    def close(self):
        pass


def plain(value):
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    if hasattr(value, "tolist"):
        return plain(value.tolist())
    return value


class Playground:
    def __init__(self, env):
        self.env = env
        self.output = Path(os.environ["PLAYGROUND_OUTPUT"]).expanduser().resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.attempt = 0
        self.seen = set()
        self.stopping = False
        self.finalized = False
        self.layout = int(env.env_seeds[0])
        self.official_step_limit = int(env.step_lim)
        self.step_multiplier = int(os.environ.get('PLAYGROUND_STEP_MULTIPLIER', '1'))
        self.development_step_limit = expanded_limit(self.official_step_limit, self.step_multiplier)
        self.ik_request_id = None
        self.ik_call_index = 0
        self.install_ik_observer()
        self.begin()

    def log(self, name, record):
        with (self.output / name).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(plain(record), allow_nan=False) + "\n")
            stream.flush()

    def diagnostic_log(self, record):
        """Diagnostics never change a solver result or cause another solve."""
        try:
            self.log("ik.jsonl", record)
        except Exception as error:
            print(f"IK diagnostic persistence failed: {type(error).__name__}: {error}",
                  file=sys.stderr, flush=True)

    def robot_measurement(self, robot, env_idx):
        manager = self.env.robot_manager
        result = {"pose_frame": "environment_origin_world_raw_link_wxyz"}
        for name, getter in (("measured_joints", manager.get_joint),
                             ("measured_raw_link_pose", manager.get_real_endpose)):
            try:
                arguments = {"env_idx_list": [env_idx]}
                if name == "measured_raw_link_pose":
                    arguments["is_relative"] = True
                result[name] = plain(getter(robot, **arguments)[env_idx])
            except Exception as error:
                result[name + "_error"] = f"{type(error).__name__}: {error}"
        return result

    def ik_context(self, event):
        return {"event": event, "episode_id": getattr(self, "episode_id", None),
                "attempt": self.attempt, "request_id": self.ik_request_id,
                "native_step": int(self.env.take_action_cnt[0])}

    def install_ik_observer(self):
        """Wrap the existing bound solver transparently, with one call only.

        No IK status is added to model observations. The original return object
        and exception are passed through unchanged; no target/tolerance edits.
        """
        manager = self.env.robot_manager
        original = manager.solve_ik
        signature = inspect.signature(original)

        def observed(*args, **kwargs):
            self.ik_call_index += 1
            record = {**self.ik_context("solve_ik"), "call_index": self.ik_call_index}
            try:
                bound = signature.bind(*args, **kwargs)
                bound.apply_defaults()
                values = bound.arguments
                robot, env_idx = values["robot"], values["env_idx"]
                record.update(arm=robot.arm_name, env_idx=env_idx,
                              target_pose=plain(values["target_pose"]),
                              transform_mode=values.get("trans"),
                              before=self.robot_measurement(robot, env_idx))
            except Exception as error:
                record["capture_error"] = f"{type(error).__name__}: {error}"
            try:
                result = original(*args, **kwargs)
            except BaseException as error:
                record.update(outcome="exception", exception_type=type(error).__name__,
                              exception=str(error))
                self.diagnostic_log(record)
                raise
            try:
                record.update(outcome="returned", status=result.get("status"),
                              target_joints=plain(result.get("joint_value")),
                              joint_names=plain(result.get("joint_names")))
            except Exception as error:
                record["result_capture_error"] = f"{type(error).__name__}: {error}"
            self.diagnostic_log(record)
            return result

        manager.solve_ik = observed

    def begin(self):
        self.attempt += 1
        self.episode_id = str(uuid.uuid4())
        self.started = time.time()
        self.finalized = False
        self.env.step_lim = self.development_step_limit
        self.env.run_reward()
        if hasattr(self.env, "get_score"):
            self.env.get_score()
        manager = self.env.reward_manager
        if not (manager.check_list[0] or manager.final_check_list[0]):
            raise RuntimeError("Native success predicates must be registered")
        if self.official_step_limit != 200:
            raise RuntimeError("This initial Playground expects official general_pickup limit 200")
        self.env.is_episode_end()
        self.log("attempts.jsonl", {"event": "begin", **self.status()})

    def status(self):
        ended = bool(self.env.end_flag[0])
        return {"episode_id": self.episode_id, "attempt": self.attempt,
                "layout": self.layout, "step": int(self.env.take_action_cnt[0]),
                "limit": int(self.env.step_lim), "ended": ended,
                "official_step_limit": self.official_step_limit,
                "step_multiplier": self.step_multiplier,
                "official_budget_comparable": self.step_multiplier == 1,
                "success": bool(self.env.success[0]) if ended else None}

    def finalize(self, classification, reason):
        if self.finalized:
            return
        self.log("attempts.jsonl", {"event": "end", **self.status(),
                 "classification": classification, "reason": reason,
                 "wall_seconds": time.time() - self.started})
        self.finalized = True

    def observe(self):
        import numpy as np
        from PIL import Image

        obs = self.env.get_obs()
        images = {}
        for camera in ("cam_head", "cam_left_wrist", "cam_right_wrist"):
            stream = obs["vision"][camera]
            raw = np.asarray(stream['color'] if 'color' in stream else stream['rgb'])
            if raw.ndim != 3 or raw.shape[2] < 3 or not raw.size:
                raise ValueError(f"Invalid RGB stream: {camera}")
            raw = raw[:, :, :3]
            if raw.dtype != np.uint8:
                raise ValueError(f"RGB stream must be uint8: {camera}")
            buffer = io.BytesIO()
            Image.fromarray(raw).save(buffer, format="PNG")
            images[camera] = base64.b64encode(buffer.getvalue()).decode("ascii")
        state = plain(obs["state"])
        # Native observations expose raw link rotations; command poses use a
        # fixed robot convention. Expose both explicitly, never camera geometry.
        command_pose = {}
        for robot in self.env.robot_manager.robot_list:
            if robot.type == "target":
                side = robot.arm_name.split("_")[0]
                command_pose[f"{side}_ee_pose"] = plain(
                    self.env.robot_manager.get_delta_endpose(robot, env_idx_list=[0])[0])
        return {**self.status(), "instruction": obs["instruction"],
                "state": state, "command_frame_measured_pose": command_pose,
                "images_png_base64": images,
                "gripper_state_semantics": "Normalized previous command, not measured aperture."}

    def check_expected(self, request):
        if request.get("episode_id") != self.episode_id:
            raise ValueError("Stale or missing episode_id")
        if request.get("expected_step") != int(self.env.take_action_cnt[0]):
            raise ValueError("Stale or missing expected_step")

    def handle(self, request):
        request_id = request.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("Unique nonempty request_id required")
        if request_id in self.seen:
            raise ValueError("Duplicate request_id rejected; action is never replayed")
        self.seen.add(request_id)
        op = request.get("op")
        if op in ("observe", "status"):
            return self.observe() if op == "observe" else self.status()
        if op == "close":
            self.finalize("native_terminal" if self.status()["ended"] else "incomplete",
                          str(request.get("reason", "client_close")))
            self.stopping = True
            return self.status()
        self.check_expected(request)
        if op == "reset":
            reason = request.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("Playground reset requires an explicit reason")
            self.finalize("native_terminal" if self.status()["ended"] else "development_reset", reason)
            self.env.reset(seed=[self.layout])
            self.begin()
            return self.observe()
        if op != "step":
            raise ValueError(f"Unsupported op: {op}")
        if self.status()["ended"]:
            raise ValueError("Episode already ended; use explicit Playground reset")
        steps = request.get("steps", 5)
        if type(steps) is not int or not 1 <= steps <= 5:
            raise ValueError("steps must be an integer in [1,5]")
        action = request.get("action")
        if not isinstance(action, dict):
            raise ValueError("Native action dictionary required")
        self.env.validate_action_dict(action)
        import copy

        # take_action calls solve_ik in its default world mode, which consumes
        # raw-link world quaternions directly. delta_matrix belongs only to
        # the native relative-mode branch; applying it here would be incorrect.
        native_action = copy.deepcopy(action)
        executed = 0
        for _ in range(steps):
            if self.env.is_episode_end():
                break
            before = int(self.env.take_action_cnt[0])
            self.ik_request_id = request_id
            try:
                self.env.take_action(native_action)
            finally:
                # Read-only proprioception after dispatch, including failures.
                for robot in self.env.robot_manager.robot_list:
                    if robot.type == "target":
                        self.diagnostic_log({**self.ik_context("after_native_action"),
                                             "arm": robot.arm_name,
                                             "native_step_before": before,
                                             **self.robot_measurement(robot, 0)})
                self.ik_request_id = None
            after = int(self.env.take_action_cnt[0])
            if after != before + 1:
                raise RuntimeError("Native step counter did not advance exactly once")
            executed += 1
            self.env.is_episode_end()
            self.log("steps.jsonl", {"request_id": request_id, **self.status(),
                                    "action": action, "native_action": native_action})
            if self.status()["ended"]:
                self.finalize("native_terminal", "native_evaluator")
                break
        return {**self.observe(), "executed_steps": executed}

    def serve(self):
        port = int(os.environ["PLAYGROUND_RPC_PORT"])
        if not 1024 <= port <= 65535:
            raise ValueError("PLAYGROUND_RPC_PORT outside unprivileged port range")
        def stop(signum, frame):
            self.stopping = True
            raise KeyboardInterrupt
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, stop)
        try:
            with socket.socket() as server:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind(("127.0.0.1", port))
                server.listen(2)
                server.settimeout(1)
                self.log("server.jsonl", {"event": "ready", "port": port, **self.status()})
                while not self.stopping:
                    try:
                        conn, _ = server.accept()
                    except socket.timeout:
                        continue
                    with conn:
                        # Model decisions may take minutes; idle observation
                        # clients must not terminate the simulator episode.
                        conn.settimeout(None)
                        stream = conn.makefile("rwb")
                        with stream:
                            while not self.stopping:
                                line = stream.readline(2_000_001)
                                if not line:
                                    break
                                request = {}
                                try:
                                    if len(line) > 2_000_000:
                                        raise ValueError("Request too large")
                                    request = json.loads(line)
                                    if not isinstance(request, dict):
                                        raise ValueError("Request must be a JSON object")
                                    result = {"ok": True, "result": self.handle(request)}
                                except Exception as exc:
                                    result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                                    self.log("errors.jsonl", {"request_id": request.get("request_id"),
                                             **self.status(), "error": result["error"]})
                                    if request.get("op") in ("step", "reset"):
                                        self.finalize("incomplete", result["error"])
                                        self.stopping = True
                                result["request_id"] = request.get("request_id")
                                stream.write((json.dumps(result, allow_nan=False) + "\n").encode())
                                stream.flush()
        finally:
            self.finalize("native_terminal" if self.status()["ended"] else "incomplete", "server_exit")


def main():
    from roboicl import robodojo

    original_import = importlib.import_module
    def intercept(name, package=None):
        module = original_import(name, package)
        if name == "src.eval_client.eval_env":
            module.WsModelClient = OfflineClient
            original_factory = module.create_eval_env
            def factory(*args, **kwargs):
                env = original_factory(*args, **kwargs)
                # Persistence disabled; raw RGB remains available in memory.
                env._stream_vision = lambda *a, **kw: None
                env.run_eval = types.MethodType(lambda instance: Playground(instance).serve(), env)
                return env
            module.create_eval_env = factory
        return module
    importlib.import_module = intercept
    try:
        return robodojo.main()
    finally:
        importlib.import_module = original_import


if __name__ == "__main__":
    raise SystemExit(main())

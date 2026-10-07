"""Reproducible diagnostics, not a trained policy or a benchmark success claim.

One exact Jev request per frozen state. All amplitude branches share its ID.
Original JSON responses, state snapshots and failures are retained independently.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

import numpy as np


def serial(value):
    if isinstance(value, (np.ndarray, np.generic)):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value).__name__)


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    default=serial, allow_nan=False) + "\n")


def append(path, value):
    with Path(path).open("a") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, default=serial,
                                allow_nan=False) + "\n")
        stream.flush()


def angle(a, b):
    return float(np.arccos(np.clip((np.trace(a.T @ b) - 1) / 2, -1, 1)))


def direction_metrics(position, target, signs, tolerance):
    error = np.asarray(target) - np.asarray(position)
    signs = np.asarray(signs, dtype=float)
    expected = np.where(np.abs(error) <= tolerance, 0, np.sign(error))
    norm = np.linalg.norm(signs)
    cosine = (float(np.dot(error, signs) / (np.linalg.norm(error) * norm))
              if norm and np.linalg.norm(error) > tolerance else None)
    return dict(error_xyz_m=error, error_norm_m=float(np.linalg.norm(error)),
                expected_signs=expected, axis_correct=(expected == signs).tolist(),
                cosine=cosine, all_hold=bool(norm == 0))


class Recorder:
    def __init__(self, output, cfg):
        self.folder = Path(output).resolve()
        self.folder.mkdir(parents=True, exist_ok=False)
        self.cfg, self.started = cfg, time.monotonic()
        dump(self.folder / "protocol.json", cfg)
        self.rows, self.decisions, self.errors = [], [], []

    def check_budget(self):
        if time.monotonic() - self.started > self.cfg["wall_limit_seconds"]:
            raise RuntimeError("Pilot wall budget reached")
        size = sum(p.stat().st_size for p in self.folder.rglob("*") if p.is_file())
        if size > self.cfg["output_limit_mb"] * 1024 ** 2:
            raise RuntimeError("Pilot output budget reached")

    def event(self, row):
        append(self.folder / "events.jsonl", dict(wall_time=time.time(), **row))

    def branch(self, row):
        self.rows.append(row)
        append(self.folder / "branches.jsonl", row)

    def finish(self, status):
        metrics = [d["metrics"] for d in self.decisions if "metrics" in d]
        valid = [m["cosine"] for m in metrics if m["cosine"] is not None]
        result = dict(status=status, wall_seconds=time.monotonic()-self.started,
                      decisions=len(self.decisions), valid_direction_decisions=len(metrics),
                      branches=len(self.rows), errors=self.errors,
                      positive_cosines=sum(c > 0 for c in valid), measurable_cosines=len(valid),
                      axis_correct=sum(sum(m["axis_correct"]) for m in metrics),
                      axes_evaluated=3*len(metrics),
                      all_hold=sum(m["all_hold"] for m in metrics),
                      stages=sorted({d["stage"] for d in self.decisions}),
                      interpretation="development diagnostic; correlated snapshots, not independent success trials")
        dump(self.folder / "summary.json", result)
        if self.rows:
            fields = sorted({k for row in self.rows for k in row})
            with (self.folder / "branches.csv").open("w") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for row in self.rows:
                    writer.writerow({k: json.dumps(v, default=serial) if isinstance(v, (list, dict, np.ndarray)) else v
                                     for k, v in row.items()})
        print(json.dumps(result, default=serial), flush=True)


class Jev:
    def __init__(self, recorder):
        self.rec = recorder
        sys.path.insert(0, recorder.cfg["existing_root"] + "/controller/src")
        if os.environ.get('JEV_RSI_MODEL_BACKEND') == 'codex_pro':
            from codex_pro_bridge import API
        else:
            from realman_jev.api import API
        config = ({'model': 'gpt-6-sol'} if os.environ.get('JEV_RSI_MODEL_BACKEND') == 'codex_pro'
            else json.loads(Path(recorder.cfg["api_config"]).read_text())["jev"])
        if os.environ.get('JEV_RSI_JEV_PROXY'):
            if os.environ.get('JEV_RSI_MODEL_BACKEND') == 'codex_pro':
                raise ValueError('Jev proxy is only for the Jev backend')
            proxy = os.environ['JEV_RSI_JEV_PROXY']
            if proxy != 'http://127.0.0.1:7905':
                raise ValueError('Jev proxy must be the authorized SSH loopback forward')
            config = dict(config, proxy=proxy)
        self.api = API(config, recorder.event, "jev")

    def choose(self, state, metadata):
        self.rec.check_budget()
        index = len(self.rec.decisions)
        if index >= self.rec.cfg["max_jev_decisions"]:
            return None
        did = f"decision-{index:04d}"
        folder = self.rec.folder / did
        folder.mkdir()
        questions = {axis: dict(type="choice", instructions=(
            f"Choose the {axis.upper()} translation direction toward the supplied local target. "
            "Use hold if the absolute error on this axis is within hold_tolerance_m. "
            "Use only the supplied coordinates; the external controller selects distance. "
            "Keep orientation and gripper unchanged."), criteria=dict(
                negative=f"Decrease the {axis.upper()} coordinate", hold="Keep this axis unchanged",
                positive=f"Increase the {axis.upper()} coordinate")) for axis in "xyz"}
        request = dict(model=self.api.cfg["model"], state=state, questions=questions)
        dump(folder / "request.json", request)
        row = dict(decision_id=did, **metadata, observation=state,
                   prompt_version="xyz-signs-v1", request_sha256=hashlib.sha256(
                       json.dumps(request, sort_keys=True).encode()).hexdigest())
        self.rec.decisions.append(row)
        start = time.monotonic()
        try:
            # API.post checks actual model version. Save the complete response before parsing.
            raw = self.api.post("/systemone", request)
            dump(folder / "response.json", raw)
            answers = raw["answers"]
            signs = []
            for axis in "xyz":
                answer = answers[axis]
                probs = answer["probabilities"]
                values = [answer["confidence"], *probs.values()]
                if (answer.get("type") != "choice" or set(probs) != {"negative", "hold", "positive"}
                    or any(not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in values)
                    or abs(sum(probs.values())-1) > .02):
                    raise ValueError("Malformed direction probabilities")
                signs.append({"negative": -1, "hold": 0, "positive": 1}[answer["choice"]])
            row.update(signs=signs, model=raw.get("model"), answers=answers,
                       metrics=direction_metrics(state["position_m"], state["target_position_m"],
                                                 signs, state["hold_tolerance_m"]))
        except Exception as exc:
            row.update(error_type=type(exc).__name__, error=(str(exc).replace(self.api.credential, "[redacted]") if self.api.credential else str(exc)))
            self.rec.errors.append(dict(decision_id=did, error_type=type(exc).__name__))
            raise
        finally:
            row["request_seconds"] = time.monotonic() - start
            dump(folder / "decision.json", row)
            append(self.rec.folder / "decisions.jsonl", row)
        return row

    def close(self):
        self.api.close()


def state_for(position, target, stage, cfg, **extra):
    return dict(task="stack blocks", stage=stage,
                stage_source="operator_defined_diagnostic_NOT_model_planned",
                observation_source="privileged_simulator_state",
                objective="Reach the supplied static local position; this is not whole-task success.",
                coordinate_frame="world_cartesian_m", position_m=np.asarray(position).tolist(),
                target_position_m=np.asarray(target).tolist(), orientation_instruction="keep fixed",
                hold_tolerance_m=cfg["axis_tolerance_m"], history=[], **extra)


def freeze_world(world, folder):
    import mujoco
    spec = mujoco.mjtState.mjSTATE_INTEGRATION
    state = np.empty(mujoco.mj_stateSize(world.model, spec))
    mujoco.mj_getState(world.model, world.data, state, spec)
    np.savez_compressed(folder / "sim_state.npz", integration=state, spec=int(spec))
    dump(folder / "sim_metadata.json", dict(scene_hash=world.scene_hash, task=world.task, seed=world.seed,
        ctrl=world.data.ctrl, closed=world.closed, stable_seconds=world.stable_seconds,
        contact_seconds=world.contact_seconds, max_lift=world.max_lift,
        unsafe_contacts=world.unsafe_contacts, steps=world.steps, source=world.source, target=world.target))
    return state, spec


def motion(world, target, cfg):
    from embodied_jev.physics import DT
    before = world.position.copy()
    rotation = world.data.site_xmat[world.tcp].reshape(3, 3).copy()
    start_time = float(world.data.time)
    for _ in world.motion(target=target, seconds=cfg["motion_seconds"], emit=False):
        pass
    stable_time = 0.
    last_speed = last_angular = None
    for _ in range(int(cfg["settle_max_seconds"]/DT)):
        old = world.position.copy()
        old_rotation = world.data.site_xmat[world.tcp].reshape(3, 3).copy()
        world.tick()
        last_speed = float(np.linalg.norm(world.position-old)/DT)
        last_angular = angle(old_rotation, world.data.site_xmat[world.tcp].reshape(3, 3))/DT
        stable_time = stable_time+DT if (last_speed <= cfg["speed_threshold_m_s"] and
            last_angular <= cfg["angular_speed_threshold_rad_s"]) else 0.
        if stable_time >= cfg["settle_window_seconds"]:
            break
    return dict(before_position_m=before, after_position_m=world.position,
        command_target_m=target, actual_delta_m=world.position-before,
        target_tracking_error_m=float(np.linalg.norm(world.position-target)),
        orientation_drift_rad=angle(rotation, world.data.site_xmat[world.tcp].reshape(3, 3)),
        simulated_seconds=float(world.data.time)-start_time, final_speed_m_s=last_speed,
        final_angular_speed_rad_s=last_angular, stable=stable_time >= cfg["settle_window_seconds"],
        forbidden_contacts=world.contacts()[2], held=world.observe()["held"])


def embodied(rec, with_jev):
    import mujoco
    from embodied_jev.physics import RobotWorld
    from embodied_jev.planning import baseline_phase, candidates
    from embodied_jev.runtime import run_headless
    baseline_results = []
    for task in ("transfer", "stack", "barrier"):
        rec.check_budget()
        session = run_headless(task, seed=rec.cfg["seed"], timeout=120, camera_views=[])
        result = dict(task=task, seed=rec.cfg["seed"], status=session.status,
                      success=session.world.success(), model_calls=session.policy.calls,
                      unsafe_contacts=session.world.unsafe_contacts, history=session.history)
        dump(rec.folder / f"rule-{task}.json", result)
        baseline_results.append({k: v for k, v in result.items() if k != "history"})
    rec.event(dict(kind="environment_positive_controls", results=baseline_results))
    # Three repeated branches per direction from an identical physics state.
    initial = RobotWorld("stack", seed=rec.cfg["seed"])
    for repeat in range(3):
        for axis in range(-1, 3):
            for sign in ([0] if axis == -1 else [-1, 1]):
                rec.check_budget()
                w = initial.clone()
                delta = np.zeros(3)
                if axis >= 0:
                    delta[axis] = sign*.002
                row = dict(kind="actuator", repeat=repeat, axis=axis, sign=sign,
                           requested_delta_m=delta, **motion(w, w.position+delta, rec.cfg))
                rec.branch(row)
    if not with_jev:
        return
    # Obtain authentic phase states from a separately labeled deterministic scaffold.
    # No scaffold completion is attributed to Jev; physics branches never affect it.
    world = RobotWorld("stack", seed=rec.cfg["seed"])
    model = Jev(rec)
    try:
        for phase_index in range(20):
            stage = baseline_phase(world)
            rec.event(dict(kind="scaffold_phase", phase_index=phase_index, stage=stage,
                           observation=world.observe()))
            if stage == "finish":
                break
            option = candidates(world, stage, preview=False)[0]
            moving = stage in {"approach", "descend", "lift", "carry", "lower", "withdraw"}
            samples = [(0., world.clone())] if moving else []
            iterator = world.motion(option.target, option.gripper, option.seconds, emit=False)
            total_ticks = max(1, int(option.seconds / .002))
            start_step, seen = world.steps, set()
            for _ in iterator:
                fraction = (world.steps-start_step)/total_ticks
                for threshold in rec.cfg.get("phase_fractions", [.50, .85]):
                    if moving and fraction >= threshold and threshold not in seen:
                        samples.append((threshold, world.clone()))
                        seen.add(threshold)
            # Stage end/control outcome remains separate from the branch evaluation.
            rec.event(dict(kind="scaffold_phase_end", stage=stage, observation=world.observe()))
            for fraction, sample in samples:
                if len(rec.decisions) >= rec.cfg["max_jev_decisions"]:
                    return
                # Samples along a scaffold motion are not initially quasi-static.
                # Stop at that sampled pose BEFORE asking Jev or cloning branches.
                preparation = motion(sample, sample.position.copy(), rec.cfg)
                rec.event(dict(kind="sample_preparation", stage=stage, phase_index=phase_index,
                               phase_fraction=fraction, result=preparation))
                if not preparation["stable"]:
                    rec.event(dict(kind="unsettled_sample_not_sent", stage=stage,
                                   phase_index=phase_index, phase_fraction=fraction))
                    continue
                target = np.asarray(option.target)
                state = state_for(sample.position, target, stage, rec.cfg,
                                  gripper="closed" if sample.closed else "open",
                                  orientation_matrix=sample.data.site_xmat[sample.tcp].reshape(3, 3).tolist())
                decision = model.choose(state, dict(stage=stage, phase_index=phase_index,
                    seed=rec.cfg["seed"], phase_fraction=fraction, environment="embodied-jev",
                    preparation=preparation,
                    trajectory_id=f"rule-scaffold-seed-{rec.cfg['seed']}"))
                folder = rec.folder / decision["decision_id"]
                saved, spec = freeze_world(sample, folder)
                vector = np.asarray(decision["signs"], float)
                if np.linalg.norm(vector):
                    vector /= np.linalg.norm(vector)
                for amplitude in rec.cfg["amplitudes_m"]:
                    rec.check_budget()
                    branch = sample.clone()
                    # Explicitly verify clone identity for the full integration state.
                    restored = np.empty_like(saved)
                    mujoco.mj_getState(branch.model, branch.data, restored, spec)
                    identical = bool(np.array_equal(saved, restored))
                    if not identical:
                        raise RuntimeError("MuJoCo clone differs from frozen integration state")
                    start = branch.position.copy()
                    row = dict(kind="amplitude", decision_id=decision["decision_id"], stage=stage,
                               phase_index=phase_index, amplitude_m=amplitude, seed=rec.cfg["seed"],
                               reset_identical=identical, goal_position_m=target,
                               goal_error_before_m=float(np.linalg.norm(start-target)))
                    try:
                        result = motion(branch, start+amplitude*vector, rec.cfg)
                        after_error = float(np.linalg.norm(branch.position-target))
                        row.update(result, goal_error_after_m=after_error,
                                   loss_decrease_m2=float((np.sum((start-target)**2)-np.sum((branch.position-target)**2))/2))
                    except Exception as exc:
                        row.update(error_type=type(exc).__name__, error=str(exc))
                    rec.branch(row)
    finally:
        model.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", choices=["embodied", "robodojo"], default="embodied")
    parser.add_argument("--with-jev", action="store_true")
    parser.add_argument("--with-model", action="store_true",
                        help="Use the configured model backend (Pro bridge when selected)")
    parser.add_argument("--max-decisions", type=int)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text())
    if args.max_decisions is not None:
        cfg["max_jev_decisions"] = args.max_decisions
    if args.seed is not None:
        cfg["seed"] = args.seed
    if args.with_jev and args.with_model:
        parser.error('Select one model flag')
    use_model = args.with_jev or args.with_model
    rec = Recorder(args.output, cfg)
    dump(rec.folder / "provenance.json", dict(command=sys.argv, python=sys.executable,
        commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        backend=args.backend, with_jev=args.with_jev,
        with_model=use_model, model_backend=cfg.get('model_backend','legacy_jev')))
    status = "completed"
    try:
        if args.backend == "embodied":
            embodied(rec, use_model)
        else:
            from robodojo_position import run
            run(rec, use_model)
    except Exception as exc:
        status = "failed"
        rec.errors.append(dict(type=type(exc).__name__, error=str(exc)))
        dump(rec.folder / "failure.json", dict(type=type(exc).__name__, error=str(exc), traceback=traceback.format_exc()))
        raise
    finally:
        rec.finish(status)


if __name__ == "__main__":
    main()

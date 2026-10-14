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
TASKS = ("stack_blocks", "general_pickup", "fold_clothes", "press_by_number", "stack_bowls",
         "match_and_pick_from_conveyor", "push_T", "arrange_largest_number",
         "classify_objects", "align_blocks", "cover_blocks", "solve_equation",
         "stack_blocks_by_language", "imitate_sorting_sequence",
         "classify_objects_by_language", "sort_nesting_dolls_by_size", "swap_T",
         "fasten_screws", "put_bottles_into_dustbin", "play_Xylophone",
         "pick_from_conveyor_by_image", "pour_balls_into_vase",
         "pour_liquid_into_cup", "sweep_blocks", "build_tower", "deposit_coin",
         "fill_egg_holder", "fill_pen_holder", "hang_mugs", "insert_key",
         "insert_tubes", "make_kong", "make_toast", "organize_table",
         "pack_objects_into_box", "play_stacking_toy", "play_tic_tac_toe",
         "plug_in_charger", "pour_by_language", "store_laptop_and_headphones",
         "store_tools_in_toolbox", "swap_blocks")


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
    env["ROBODOJO_GPT6_DATA_ROOT"] = str(DATA_ROOT)
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
        if os.environ.get('ROBODOJO_MEASURED_GRIPPER_STATE') == '1':
            measured=tools._rpc('public_robot_gripper_state')
            if measured.get('physical_steps')!=0 or measured.get('step_id')!=obs['step_id']:
                raise ValueError('Robot encoder read must be current and zero-step')
            obs['measured_gripper_joint_state']=measured
            (output / 'robot_gripper_state_step_000.json').write_text(
                json.dumps(measured,ensure_ascii=False,indent=2))
        initial_camera_calibration = None
        initial_eef = obs["current_eef"]
        if os.environ.get("ROBODOJO_PUBLIC_CAMERA_CALIBRATION") == "1":
            initial_camera_calibration = tools._rpc("public_camera_calibration")
            obs["camera_calibration"] = initial_camera_calibration
            (output / "camera_calibration_initial.json").write_text(
                json.dumps(obs["camera_calibration"], ensure_ascii=False, indent=2))
        if preflight:
            tools.finish("preflight_no_control")
            result["status"] = "preflight_complete"
            return result
        if key_file is None:
            raise ValueError("--key-file is required for control")
        model = DecisionClient(key_file, output / "decisions")
        if controller_version in ("v1_button_camera_audit", "v1_button_two_view", "v1_button_three_view"):
            expected = {"v1_button_camera_audit": 1, "v1_button_two_view": 2,
                        "v1_button_three_view": 3}[controller_version]
            if initial_camera_calibration is None or max_decisions != expected:
                raise ValueError("Button camera sequence requires calibration and exact decision budget")
            if ("followup_plan" in plan) != (expected >= 2):
                raise ValueError("Button followup plan and controller mismatch")
            if expected == 3 and "next_review" not in plan["followup_plan"]:
                raise ValueError("Three-view controller needs step-ten Pro review")
            from button_camera_audit import run_audit
            result.update(run_audit(tools, obs, model, plan, output,
                                    initial_camera_calibration, initial_eef))
            return result
        if controller_version == "v1_button_view":
            if initial_camera_calibration is None:
                raise ValueError("Button view requires public RGB calibration")
            from button_probe import run_probe as run_button_probe
            result.update(run_button_probe(tools, obs, model, plan, output,
                                           initial_camera_calibration, initial_eef))
            return result
        if controller_version == "v1_button_sequence":
            if initial_camera_calibration is None:
                raise ValueError("Button view sequence requires public RGB calibration")
            from button_sequence import run_sequence as run_button_sequence
            result.update(run_button_sequence(tools, obs, model, plan, output,
                                              initial_camera_calibration, initial_eef,
                                              max_decisions))
            return result
        if controller_version == "v1_push_preapproach":
            if initial_camera_calibration is None:
                raise ValueError("Push preapproach requires public RGB calibration")
            from push_probe import run_probe as run_push_probe
            result.update(run_push_probe(tools, obs, model, plan, output,
                                         initial_camera_calibration, initial_eef))
            return result
        if controller_version == "v1_push_followup":
            if initial_camera_calibration is None:
                raise ValueError("Push followup requires public RGB calibration")
            from push_followup import run_sequence as run_push_followup
            result.update(run_push_followup(tools, obs, model, plan, output,
                                            initial_camera_calibration, initial_eef))
            return result
        if controller_version == "v1_bowl_view":
            if initial_camera_calibration is None:
                raise ValueError("Bowl view requires public RGB calibration")
            from bowl_view_probe import run_probe as run_bowl_view
            result.update(run_bowl_view(tools, obs, model, plan, output,
                                         initial_camera_calibration, initial_eef))
            return result
        if controller_version == "v1_bowl_view_sequence":
            if initial_camera_calibration is None or max_decisions != 2:
                raise ValueError("Two bowl views require calibration and --max-decisions 2")
            from bowl_view_sequence import run_sequence as run_bowl_view_sequence
            result.update(run_bowl_view_sequence(tools, obs, model, plan, output,
                                                  initial_camera_calibration, initial_eef))
            return result
        if controller_version in ("v1_stack_first_advance", "v1_stack_side_sequence", "v1_stack_three_view", "v1_stack_four_view"):
            expected = {"v1_stack_first_advance": 1,
                        "v1_stack_side_sequence": 2,
                        "v1_stack_three_view": 3,
                        "v1_stack_four_view": 4}[controller_version]
            if initial_camera_calibration is None or max_decisions != expected:
                raise ValueError("Stack sequence requires calibration and exact decision budget")
            if ("followup_plan" in plan) != (expected >= 2):
                raise ValueError("Stack followup plan and controller mismatch")
            if expected == 3 and "next_review" not in plan["followup_plan"]:
                raise ValueError("Third stack view requires a fresh step-ten Pro review")
            if expected == 4 and "next_review" not in plan["followup_plan"].get("next_review", {}):
                raise ValueError("Fourth stack view requires a fresh step-fifteen Pro review")
            from stack_first_advance import run_probe as run_stack_first_advance
            result.update(run_stack_first_advance(
                tools, obs, model, plan, output,
                initial_camera_calibration, initial_eef))
            return result
        if controller_version == "v1_fold_cuff_view":
            if initial_camera_calibration is None or max_decisions != 1:
                raise ValueError("Fold cuff view requires calibration and one decision")
            from fold_cuff_view import run_view as run_fold_cuff_view
            result.update(run_fold_cuff_view(
                tools, obs, model, plan, output,
                initial_camera_calibration, initial_eef))
            return result
        if controller_version == "v1_fold_synced_view":
            if initial_camera_calibration is None or max_decisions != 1:
                raise ValueError("Synchronized fold view requires calibration and one decision")
            if os.environ.get("ROBODOJO_FOLD_CPU_USD_SYNC_AUDIT") != "1":
                raise ValueError("Synchronized fold view requires CPU/USD cloth and robot updates")
            from fold_synced_view import run_view as run_fold_synced_view
            result.update(run_fold_synced_view(
                tools, obs, model, plan, output,
                initial_camera_calibration, initial_eef))
            return result
        if controller_version == "v1_fold_synced_two_view":
            if initial_camera_calibration is None or max_decisions != 2:
                raise ValueError("Two synchronized fold views require calibration and two decisions")
            if os.environ.get("ROBODOJO_FOLD_CPU_USD_SYNC_AUDIT") != "1":
                raise ValueError("Two synchronized fold views require CPU/USD cloth and robot updates")
            from fold_synced_sequence import run_two_view
            result.update(run_two_view(
                tools, obs, model, plan, output,
                initial_camera_calibration, initial_eef))
            return result
        if controller_version == "v2_pickup_axis_effect":
            if initial_camera_calibration is None or not 1 <= max_decisions <= 8:
                raise ValueError("Pickup axis-effect pilot requires public K/T and 1..8 Decisions")
            from pickup_axis_effect import run as run_pickup_axis_effect
            result.update(run_pickup_axis_effect(
                tools, obs, model, plan, output,
                initial_camera_calibration, initial_eef, max_decisions))
            return result
        if controller_version in ("v2_pickup_rgb_axes", "v2_pickup_rgb_axes_numeric", "v2_pickup_rgb_axes_hull"):
            limit = 40 if controller_version.endswith("_hull") else 8
            if not 1 <= max_decisions <= limit:
                raise ValueError(f"RGB-axis pilot requires 1..{limit} Decisions")
            numeric = controller_version.endswith("_numeric")
            hull = controller_version.endswith("_hull")
            if (numeric or hull) and initial_camera_calibration is None:
                raise ValueError("Paired numeric RGB-axis pilot requires public K/T")
            from pickup_rgb_axes import run as run_pickup_rgb_axes
            result.update(run_pickup_rgb_axes(tools, obs, model, plan,
                                              output, max_decisions,
                                              numeric_evidence=numeric,
                                              hull_evidence=hull,
                                              initial_calibration=initial_camera_calibration,
                                              initial_eef=initial_eef))
            return result
        if controller_version == "v2_rgb_stage_pose_episode":
            if initial_camera_calibration is None or not 1 <= max_decisions <= 110:
                raise ValueError("RGB stage pose baseline requires public K/T and1..110 Decisions")
            from rgb_stage_pose_episode import run as run_rgb_stage_pose
            result.update(run_rgb_stage_pose(tools,obs,model,output,max_decisions,deadline))
            return result
        if controller_version == "v2_pickup_active_episode":
            if initial_camera_calibration is None or not 1 <= max_decisions <= 40:
                raise ValueError("Active pickup requires public K/T and 1..40 Decisions")
            from pickup_active_episode import run as run_pickup_active
            result.update(run_pickup_active(
                tools, obs, model, plan, output, max_decisions,
                initial_camera_calibration, initial_eef))
            return result
        if controller_version == "v1_number_first_view":
            if initial_camera_calibration is None or max_decisions != 1:
                raise ValueError("First number view requires calibration and --max-decisions 1")
            from number_first_view import run_probe as run_number_first_view
            result.update(run_number_first_view(tools, obs, model, plan, output,
                                                initial_camera_calibration, initial_eef))
            return result
        if controller_version == "v1_number_view_sequence":
            expected_decisions = (5 if "fifth_plan" in plan else
                                  4 if "fourth_plan" in plan else
                                  3 if "third_plan" in plan else 2)
            if initial_camera_calibration is None or max_decisions != expected_decisions:
                raise ValueError("Number view sequence requires calibration and its plan decision count")
            from number_view_sequence import run_sequence as run_number_view_sequence
            result.update(run_number_view_sequence(tools, obs, model, plan, output,
                                                   initial_camera_calibration, initial_eef))
            return result
        if controller_version == "v5_probe_y":
            from probe_y import run_probe
            result.update(run_probe(tools, obs, model, output))
            return result
        if controller_version == "v1_source_view":
            if initial_camera_calibration is None:
                raise ValueError("Source-view pilot requires public RGB calibration")
            from source_view_probe import run_probe
            result.update(run_probe(tools, obs, model, plan, output,
                                    initial_camera_calibration, initial_eef,
                                    deadline, max_decisions))
            return result
        if controller_version == "v1_source_view_sequence":
            if initial_camera_calibration is None:
                raise ValueError("Source-view sequence requires public RGB calibration")
            from source_view_probe import run_sequence
            result.update(run_sequence(tools, obs, model, plan, output,
                                       initial_camera_calibration, initial_eef,
                                       deadline, max_decisions))
            return result
        if controller_version == "v1_source_single_view":
            if initial_camera_calibration is None:
                raise ValueError("Single source view requires public RGB calibration")
            from source_view_probe import run_single_view
            result.update(run_single_view(tools, obs, model, plan, output,
                                          initial_camera_calibration, initial_eef,
                                          deadline))
            return result
        if controller_version == "v1_source_double_view":
            if initial_camera_calibration is None:
                raise ValueError("Two source views require public RGB calibration")
            if max_decisions != 2:
                raise ValueError("Two source-view turns require --max-decisions 2")
            from source_view_probe import run_double_view
            result.update(run_double_view(tools, obs, model, plan, output,
                                          initial_camera_calibration, initial_eef,
                                          deadline))
            return result
        if controller_version == "v1_source_right_view":
            if initial_camera_calibration is None:
                raise ValueError("Three source views require public RGB calibration")
            if max_decisions != 3:
                raise ValueError("Three source-view turns require --max-decisions 3")
            from source_view_probe import run_double_view
            result.update(run_double_view(tools, obs, model, plan, output,
                                          initial_camera_calibration, initial_eef,
                                          deadline, include_right=True))
            return result
        if controller_version == "v1_source_right_followup":
            if initial_camera_calibration is None:
                raise ValueError("Four source views require public RGB calibration")
            if max_decisions != 4:
                raise ValueError("Four source-view turns require --max-decisions 4")
            from source_view_probe import run_double_view
            result.update(run_double_view(tools, obs, model, plan, output,
                                          initial_camera_calibration, initial_eef,
                                          deadline, include_right=True,
                                          include_right_followup=True))
            return result
        if controller_version in ("v2", "v3", "v4", "v6", "v7", "v8", "v9", "v10_y_probe", "v11_edge_probe", "v12_confirm_probe", "v13_yellow_first", "v14_yellow_x_first", "v15_yellow_margin_gate"):
            from stage_controller import NO_MOTION, StageController
            stage_control = StageController(model, obs, plan,
                augmented=(controller_version in ("v3", "v4", "v6", "v7", "v8", "v9", "v10_y_probe", "v11_edge_probe", "v12_confirm_probe", "v13_yellow_first", "v14_yellow_x_first", "v15_yellow_margin_gate")),
                reobserve=(controller_version in ("v4", "v6", "v7", "v8", "v9", "v10_y_probe", "v11_edge_probe", "v12_confirm_probe", "v13_yellow_first", "v14_yellow_x_first", "v15_yellow_margin_gate")),
                geometry_cue=(controller_version in ("v6", "v7", "v8", "v9", "v10_y_probe", "v11_edge_probe", "v12_confirm_probe", "v13_yellow_first", "v14_yellow_x_first", "v15_yellow_margin_gate")),
                sign_gate=(controller_version in ("v7", "v8", "v9", "v10_y_probe", "v11_edge_probe", "v12_confirm_probe", "v13_yellow_first", "v14_yellow_x_first", "v15_yellow_margin_gate")),
                staged_micro=(controller_version in ("v8", "v9", "v10_y_probe", "v11_edge_probe", "v12_confirm_probe")),
                recovery_sweep=(controller_version in ("v9", "v10_y_probe", "v11_edge_probe", "v12_confirm_probe")),
                y_probe=(controller_version in ("v10_y_probe", "v11_edge_probe", "v12_confirm_probe")),
                edge_margin_probe=(controller_version in ("v11_edge_probe", "v12_confirm_probe")),
                visibility_confirmation=(controller_version == "v12_confirm_probe"),
                yellow_first=(controller_version in ("v13_yellow_first", "v14_yellow_x_first", "v15_yellow_margin_gate")),
                yellow_x_first=(controller_version in ("v14_yellow_x_first", "v15_yellow_margin_gate")),
                yellow_margin_gate=(controller_version == "v15_yellow_margin_gate"))
        else:
            stage_control = None
        while not obs["rollout_finished"]:
            if controller_version in ("v1_geometry_sign", "v1_geometry_candidate") and int(obs["step_id"]) >= 40:
                tools.finish("geometry_hypothesis_stale_incomplete")
                result["status"] = "geometry_hypothesis_stale_incomplete"
                break
            if controller_version in ("v1_geometry_candidate_refresh", "v1_geometry_candidate_margin"):
                landmark = plan["initial_landmark_estimate"]
                age = int(obs["step_id"]) - int(landmark["camera_step_id"])
                if age >= 40:
                    from refresh_landmark import refresh_landmark
                    try:
                        plan["initial_landmark_estimate"] = refresh_landmark(
                            obs, plan, output / "planner_refresh")
                        result["refreshes"] = result.get("refreshes", 0) + 1
                    except (ValueError, RuntimeError) as error:
                        tools.finish("relocalization_incomplete")
                        result.update(status="relocalization_incomplete",
                                      refresh_error=f"{type(error).__name__}: {error}")
                        return result
                point = plan["initial_landmark_estimate"]["estimated_position_environment_m"]
                eef = obs["current_eef"]["right"]["position"]
                if all(abs(float(point[i]) - float(eef[i])) <= 0.015 for i in (0, 1)):
                    tools.finish("landmark_planar_alignment_incomplete")
                    result["status"] = "landmark_planar_alignment_incomplete"
                    return result
                if controller_version == "v1_geometry_candidate_margin":
                    from camera_geometry import (project, view_margin_candidate,
                                                 gripper_height_above_landmark,
                                                 wrist_rotation_view_candidates)
                    camera = obs["camera_calibration"]["cameras"]["cam_right_wrist"]
                    uv = project(camera, point)
                    width, height = camera["size"]
                    margin = (min(uv[0], width - 1 - uv[0], uv[1], height - 1 - uv[1])
                              if uv is not None else -1.0)
                    view = view_margin_candidate(camera, point, obs["current_eef"]["right"],
                                                 min_height_clearance=0.10, require_progress=True)
                    mesh_bound = gripper_height_above_landmark(obs["current_eef"]["right"], point)
                    rotation_view = next((item for item in wrist_rotation_view_candidates(
                        camera, point, obs["current_eef"]["right"])
                        if item["axis"] == "x" and item["sign"] == "negative" and
                        item["margin_gain_px"] >= 12 and
                        item["min_hand_above_landmark_plane_during_rotation_m"] >= 0.05), None)
                    view_ok = (rotation_view is not None if plan.get("rotation_view_gate") else
                               bool(view and (view["axis"], view["sign"]) == ("z", "negative") and
                                    mesh_bound["hand_above_landmark_plane_after_m"] >= 0.05))
                    if margin < 40 and not view_ok:
                        tools.finish("visibility_candidate_incomplete")
                        result.update(status="visibility_candidate_incomplete",
                                      wrist_image_margin_px=margin,
                                      candidate=rotation_view if plan.get("rotation_view_gate") else view,
                                      robot_mesh_height_bound=mesh_bound)
                        return result
            if time.monotonic() > deadline:
                tools.finish("wall_budget_incomplete")
                result["status"] = "wall_budget_incomplete"
                break
            if stage_control is None:
                action, answers = model.decide(obs, plan, stage, history)
                if controller_version in ("v1_geometry_candidate", "v1_geometry_candidate_refresh", "v1_geometry_candidate_margin"):
                    view_moves = sum(item["model_choices"].get("motion") == "probe_view" for item in history)
                    down_moves = sum(item["model_choices"].get("motion") == "probe_down" for item in history)
                    rotate_moves = sum(item["model_choices"].get("motion") == "probe_rotate_x_negative" for item in history)
                    if (answers["motion"] == "stop" or
                            (answers["motion"] == "probe_view" and view_moves >= 2) or
                            (answers["motion"] == "probe_down" and down_moves >= 8) or
                            (answers["motion"] == "probe_rotate_x_negative" and rotate_moves >= 2)):
                        reason = ("candidate_stop_incomplete" if answers["motion"] == "stop"
                                  else "descent_budget_incomplete" if answers["motion"] == "probe_down"
                                  else "rotation_budget_incomplete" if answers["motion"] == "probe_rotate_x_negative"
                                  else "view_budget_incomplete")
                        tools.finish(reason)
                        result.update(status=reason, blocker=answers["blocker"],
                                      view_moves=view_moves, down_moves=down_moves,
                                      rotate_moves=rotate_moves,
                                      final_stage=answers["stage"])
                        return result
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
            if os.environ.get("ROBODOJO_PUBLIC_CAMERA_CALIBRATION") == "1" and not next_obs["rollout_finished"]:
                from camera_geometry import propagate_wrist_calibration
                next_obs["camera_calibration"] = propagate_wrist_calibration(
                    initial_camera_calibration, initial_eef,
                    next_obs["current_eef"], next_obs["step_id"])
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
    parser.add_argument("--controller", choices=("v2_rgb_stage_pose_episode", "v1", "v1_button_camera_audit", "v1_button_two_view", "v1_button_three_view", "v1_button_view", "v1_button_sequence", "v1_push_preapproach", "v1_push_followup", "v1_bowl_view", "v1_bowl_view_sequence", "v1_stack_first_advance", "v1_stack_side_sequence", "v1_stack_three_view", "v1_stack_four_view", "v1_fold_cuff_view", "v1_fold_synced_view", "v1_fold_synced_two_view", "v2_pickup_axis_effect", "v2_pickup_rgb_axes", "v2_pickup_rgb_axes_numeric", "v2_pickup_rgb_axes_hull", "v2_pickup_active_episode", "v1_number_first_view", "v1_number_view_sequence", "v1_source_view", "v1_source_view_sequence", "v1_source_single_view", "v1_source_double_view", "v1_source_right_view", "v1_source_right_followup", "v1_geometry_sign", "v1_geometry_candidate", "v1_geometry_candidate_refresh", "v1_geometry_candidate_margin", "v2", "v3", "v4", "v5_probe_y", "v6", "v7", "v8", "v9", "v10_y_probe", "v11_edge_probe", "v12_confirm_probe", "v13_yellow_first", "v14_yellow_x_first", "v15_yellow_margin_gate"), default="v1")
    parser.add_argument("--max-wall-seconds", type=int, default=6800)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.layout < 0 or args.max_decisions < 0 or not 1 <= args.max_wall_seconds <= 6900:
        parser.error("layout/max-decisions must be nonnegative; max-wall-seconds must be 1..6900")
    if args.controller == "v5_probe_y" and (args.task != "stack_blocks" or args.layout != 0):
        parser.error("v5_probe_y is a stack_blocks layout-0 calibration pilot")
    if args.controller in ("v1_button_camera_audit", "v1_button_two_view", "v1_button_three_view", "v1_button_view", "v1_button_sequence") and (args.task != "press_by_number" or args.layout != 0):
        parser.error("Button view controllers are press_by_number layout-0 pilots")
    if args.controller in ("v1_stack_first_advance", "v1_stack_side_sequence", "v1_stack_three_view", "v1_stack_four_view") and (args.task != "stack_blocks" or args.layout != 0):
        parser.error("First stack advance is a stack_blocks layout-0 pilot")
    if args.controller == "v1_fold_cuff_view" and (args.task != "fold_clothes" or args.layout != 0):
        parser.error("First cuff view is a fold_clothes layout-0 pilot")
    if args.controller == "v1_fold_synced_view" and (args.task != "fold_clothes" or args.layout != 0):
        parser.error("Synchronized cuff view is a fold_clothes layout-0 pilot")
    if args.controller == "v1_fold_synced_two_view" and (args.task != "fold_clothes" or args.layout != 0):
        parser.error("Two synchronized cuff views are a fold_clothes layout-0 pilot")
    if args.controller in ("v1_push_preapproach", "v1_push_followup") and (args.task != "push_T" or args.layout != 0):
        parser.error("Push controllers are push_T layout-0 pilots")
    if args.controller in ("v1_bowl_view", "v1_bowl_view_sequence") and (args.task != "stack_bowls" or args.layout != 0):
        parser.error("Bowl view controller is a stack_bowls layout-0 pilot")
    if args.controller in ("v1_source_view", "v1_source_view_sequence") and (args.task != "cover_blocks" or args.layout != 0):
        parser.error("source-view pilots are for cover_blocks layout 0")
    if args.controller == "v1_source_single_view" and (args.task != "play_Xylophone" or args.layout != 0):
        parser.error("v1_source_single_view is a play_Xylophone layout-0 pilot")
    if args.controller == "v1_source_double_view" and (args.task != "play_Xylophone" or args.layout != 0):
        parser.error("v1_source_double_view is a play_Xylophone layout-0 pilot")
    if args.controller == "v1_source_right_view" and (args.task != "play_Xylophone" or args.layout != 0):
        parser.error("v1_source_right_view is a play_Xylophone layout-0 pilot")
    if args.controller == "v1_source_right_followup" and (args.task != "play_Xylophone" or args.layout != 0):
        parser.error("v1_source_right_followup is a play_Xylophone layout-0 pilot")
    if args.controller in ("v1_geometry_sign", "v1_geometry_candidate", "v1_geometry_candidate_refresh", "v1_geometry_candidate_margin") and (args.task != "general_pickup" or args.layout != 0):
        parser.error("geometry pilots are for general_pickup layout 0 only")
    if args.controller in ("v6", "v7", "v8", "v9", "v10_y_probe", "v11_edge_probe", "v12_confirm_probe", "v13_yellow_first", "v14_yellow_x_first", "v15_yellow_margin_gate") and (args.task != "stack_blocks" or args.layout != 0):
        parser.error("RGB geometry cue is calibrated only for stack_blocks layout 0")
    python = executable()
    robo = SOURCE_ROOT / "RoboDojo"
    if not (robo / "Assets").is_dir() or not (robo / "XPolicyLab").is_dir():
        raise FileNotFoundError("Existing RoboDojo assets/source links unavailable")
    plan_file = args.plan or Path(__file__).resolve().parent / "plans" / f"{args.task}.json"
    if args.preflight_only and not plan_file.exists():
        plan = {"task": args.task, "initial_stage": "observe",
                "stages": {"observe": "Acquire three current RGB views, measured robot state and public camera calibration; zero control actions."},
                "notes": "Sensor-only preflight; no hidden object state or evaluator feedback."}
    else:
        plan = json.loads(plan_file.read_text())
    if plan.get("task") != args.task or plan["initial_stage"] not in plan["stages"]:
        raise ValueError("Task plan mismatch")
    if args.controller == "v1_geometry_sign" and not plan.get("geometry_sign_gate"):
        raise ValueError("v1_geometry_sign requires a geometry_sign_gate plan")
    if args.controller in ("v1_geometry_candidate", "v1_geometry_candidate_refresh", "v1_geometry_candidate_margin") and not plan.get("geometry_candidate_gate"):
        raise ValueError("geometry candidate controller requires a geometry_candidate_gate plan")
    if args.controller == "v1_geometry_candidate_margin" and not plan.get("visibility_margin_gate"):
        raise ValueError("margin controller requires a visibility_margin_gate plan")
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
    environment["ROBODOJO_TASK"] = args.task
    sys.path[:0] = environment["PYTHONPATH"].split(":")
    port = free_port()
    command = [str(python), str(Path(__file__).resolve().parent / "sim_server.py"),
               "--task", args.task, "--output", str(output / "sim"),
               "--port", str(port), "--eval-seed", "0"]
    (output / "launch.json").write_text(json.dumps({"command": command, "layout": args.layout,
        "started": dt.datetime.now().astimezone().isoformat(),
        "source": "existing read-only RoboDojo + GPT-as-Policy installation",
        "planner_model": "gpt-6.1-sol high",
        "planner_refresh_transport": ("fresh current-RGB AI2RobCoWork method-only plan required before any action; no fallback"
                                      if args.controller == "v2_rgb_stage_pose_episode" else
                                      "supplied authored task-general GPT-6.1 Sol high schema; no fresh per-layout call claimed"
                                      if os.environ.get("ROBODOJO_PICKUP_USE_GENERAL_SCHEMA") == "1" else
                                      "requested AI2RobCoWork Responses gateway; explicit supplied-method fallback if unavailable"
                                      if args.controller == "v2_pickup_active_episode" else "supplied plan provenance"),
        "planner_schema_provenance": plan.get("planner_provenance", {}),
        "decision_model": "gpt-6-luna via du cad/direct key",
        "actor_current_numeric_errors": (False if args.controller == "v2_rgb_stage_pose_episode" else
                                         os.environ.get("ROBODOJO_PICKUP_ACTOR_METRIC_ERRORS", "1") != "0"),
        "runtime_feature_flags": {key: value for key, value in os.environ.items()
            if (key.startswith("ROBODOJO_PICKUP_") and value in ("0", "1")) or key in (
                "ROBODOJO_MEASURED_GRIPPER_STATE", "ROBODOJO_PUBLIC_CAMERA_CALIBRATION",
                "ROBODOJO_DECISION_TRANSPORT", "ROBODOJO_PLANNER_LONG_REQUEST",
                "ROBODOJO_PLANNER_REQUEST_TIMEOUT_SECONDS")},
        "input_contract": "fresh three RGB plus labelled current derived crops, public K/T and robot URDF/STL, measured robot state, uncertain camera-derived geometry and model-facing experience; no true object pose, contact or evaluator outcomes"}, indent=2))
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

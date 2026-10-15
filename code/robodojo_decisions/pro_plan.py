"""Build a sensor-only RoboDojo stage plan through the authorized Responses provider."""

import argparse
import base64
import cv2
import hashlib
import json
from pathlib import Path
from planner_responses import build_payload, load_config, output_text, request
from model_input_language import select_planner_experience


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--calibration", type=Path,
                        help="Current public RGB camera intrinsics/extrinsics, if available")
    parser.add_argument("--previous-observation", type=Path,
                        help="Optional earlier three-RGB public observation for visual motion comparison")
    parser.add_argument("--previous-calibration", type=Path,
                        help="Public camera calibration matched to --previous-observation")
    parser.add_argument("--geometry-evidence", type=Path,
                        help="Optional camera-derived landmark/projection checks from current RGB and measured LINK6")
    parser.add_argument("--template", type=Path)
    parser.add_argument("--method-only", action="store_true",
                        help="Planner defines perception and stages; runtime geometry/Luna own actions")
    parser.add_argument("--rgb-pose-baseline", action="store_true",
                        help="Define an explicit raw-RGB actor baseline without object-error processors")
    parser.add_argument("--omit-image-payload", action="store_true",
                        help="Use RGB-derived sensor summaries when gateway cannot carry GPT-6.1 Sol images")
    parser.add_argument("--select-recent-experience", action="store_true",
                        help="Read and snapshot full notes, submit identity and two newest task lessons verbatim")
    parser.add_argument("--global-experience", type=Path, required=True)
    parser.add_argument("--task-experience", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--response-file", type=Path,
                        help="Revalidate a saved response for exactly the same public input")
    args = parser.parse_args()
    if args.rgb_pose_baseline and not args.method_only:
        raise ValueError('RGB pose baseline requires strict method-only planning')
    args.output.mkdir(parents=True, exist_ok=False)
    obs = json.loads(args.observation.read_text())
    if bool(args.previous_observation) != bool(args.previous_calibration):
        raise ValueError("Previous observation and calibration must be supplied together")
    previous = (json.loads(args.previous_observation.read_text())
                if args.previous_observation else None)
    if previous and (previous["task"] != obs["task"] or
                     int(previous["step_id"]) >= int(obs["step_id"])):
        raise ValueError("Historical RGB must be an earlier step of the same task")
    template = json.loads(args.template.read_text()) if args.template else None
    if template and template["task"] != obs["task"]:
        raise ValueError("Task mismatch")
    public = {
        "task": obs["task"], "instruction": obs["instruction"],
        "step_id": obs["step_id"],
        "current_eef": obs["current_eef"],
        "current_joint_state": obs["current_state"],
    }
    if args.calibration:
        public["camera_calibration"] = json.loads(args.calibration.read_text())
        if int(public["camera_calibration"]["step_id"]) != int(obs["step_id"]):
            raise ValueError("Current RGB/calibration step mismatch")
    if args.geometry_evidence:
        public["camera_derived_geometry_evidence"] = json.loads(args.geometry_evidence.read_text())
    if previous:
        previous_calibration = json.loads(args.previous_calibration.read_text())
        if int(previous_calibration["step_id"]) != int(previous["step_id"]):
            raise ValueError("Historical RGB/calibration step mismatch")
        public["historical_observation_for_motion_or_current_feature"] = {
            "step_id": previous["step_id"],
            "current_eef": previous["current_eef"],
            "current_joint_state": previous["current_state"],
            "camera_calibration": previous_calibration,
        }
    full_experience = {
        "global": args.global_experience.read_text(),
        "task": args.task_experience.read_text() if args.task_experience else "",
    }
    experience = dict(full_experience)
    if args.select_recent_experience:
        chosen = select_planner_experience(full_experience["task"])
        experience["task"] = (
            "# Verbatim selected general_pickup experience\n\n" +
            "\n".join(dict.fromkeys(chosen)) + "\n")
    # Preserve both the entire notes read and the exact subset sent.
    for role, contents in full_experience.items():
        (args.output / f"planner-experience-{role}.md").write_text(contents)
        (args.output / f"planner-selected-experience-{role}.md").write_text(
            experience[role])
    system = (
        "You are the planning model in a planning-model/decision-model robot control architecture. "
        "You have two equally important responsibilities: divide the task into simple, "
        "actionable stages with observable transition conditions, and design the "
        "decision-model inputs needed to make progress in each stage. "
        "The decision model accepts only the supplied formal input schema and returns "
        "choices in the supplied formal output schema. It cannot execute free-form "
        "instructions or run perception algorithms. Use the observation and execution "
        "interfaces supplied for this request; do not assume unavailable evidence. "
        "Choose which available observations to show, explain each input field, and "
        "specify any necessary preprocessing and its output contract. Mark a proposed "
        "processor as required_but_unavailable if it is not supplied; never present "
        "its output as a current measurement or make an unimplemented stage executable. "
        "Use ONLY the task instruction, three supplied RGB frames, measured robot state, "
        "and the supplied experience notes. No hidden simulator object pose, contacts, reward, "
        "evaluation state, or task layout data are available. Produce one JSON object with "
        "task, initial_stage, stages, notes, visual_method, experience. "
        "Set task to the EXACT public_observation.task identifier string; put any "
        "natural-language task description in notes. "
        + ("Keep EXACTLY the provided stage keys and initial_stage from the template. "
           if template else
           "Choose 4 to 12 task-specific stages and an initial_stage that is one of them. ") +
        "stages maps each key to an object with goal, decision_inputs, "
        "decision_question, decision_options, advance_when, and if_stuck. "
        "Use a short plain-English goal. decision_inputs lists the minimal needed "
        "fields or images, their meaning, producer, availability, and numeric units "
        "and coordinate frame when applicable. decision_question asks one concrete "
        "judgment; decision_options uses the supplied categorical interface without "
        "inventing motor commands. advance_when references available observable "
        "evidence or an explicit check computed by the harness. if_stuck identifies "
        "what evidence or stage design must change, rather than repeating STOP on "
        "the same observation. Do not create an open-ended observe/verify stage with "
        "no way for the decision model to advance it. Check visibility within a "
        "concrete task stage where possible. "
        "Do not require evidence from a later stage before the current stage can begin. "
        "visual_method must define the selected image/robot-state inputs and any "
        "processing pipeline needed to construct the stage inputs. Keep algorithm "
        "validation separate from the decision model's simple task judgment: the "
        "harness, not the decision model, checks transforms, ray depth, reprojection "
        "errors and robot path limits. Supply compact valid/unknown checks and "
        "interpretable errors instead of asking the model to verify that machinery. "
        "experience contains at most three short reusable lessons, each stating a "
        "repeated problem, a practical adjustment and its scope. Do not copy run "
        "diaries, confidence lists or long geometric audits into these lessons. "
        "The decision model receives all three current RGB frames and may only "
        "choose among offered discrete motion, gripper and stage options. Do not emit "
        "precise object world coordinates from monocular RGB. Require visible capture and "
        "post-release verification. The native EEF action contract permits only 1 to 5 "
        "physical steps per Decision, at most 0.05 m position change and 0.35 rad "
        "orientation change from each arm's current measured LINK6 pose. A longer "
        "10/15/20-step robot path preview is diagnostic only: it cannot be submitted "
        "as one EEF action. Every executed segment needs fresh observation and Luna approval. "
        "If historical RGB is provided, use it for actual visual motion, public "
        "camera projection validation, and same-feature temporal triangulation only "
        "when a current RGB feature is matched and a fixed-view image supports "
        "source stability. Historical pixels cannot establish current contact, "
        "visibility or a current grasp target. "
        "Any numeric projection prediction must be computed by a supplied algorithm "
        "from current K/T, not guessed in prose. Return JSON only."
        + (" Camera-derived geometry evidence is provided from current RGB and "
           "may include same-feature matches from earlier RGB in the same episode, "
           "with public camera calibration and measured LINK6. Use it only to refine "
           "the semantic stage criteria, feature extraction, uncertainty and "
           "reobservation method. Never select or suggest a motion. "
           if args.geometry_evidence and args.method_only else
           " Camera-derived geometry evidence is provided from the CURRENT RGB, "
           "public camera calibration and measured LINK6. Compare predicted "
           "image margin, public robot-path reachability, visible obstacles and "
           "any available conservative clearance estimate for each candidate "
           "before selecting a new viewpoint. For a non-contact sensing move, "
           "RGB alone cannot certify a complete scene collision map: mark "
           "unknown depth as uncertainty, and you may offer one exploratory "
           "native-legal short move when current RGB shows an open local "
           "corridor, the public robot path is feasible, and Luna retains a "
           "specific visual veto plus immediate post-move reobservation. "
           "Object-contact and grasp candidates still require fresh source/tool "
           "geometry and tighter clearance evidence. A retreat that merely reverses "
           "the next approach is not a durable solution. State an explicit "
           "visibility gate and reject stale or out-of-frame landmarks. "
           "If camera_derived_geometry_evidence names excluded_candidates from "
           "previous failed or vetoed trials, do not recommend those motions again. "
           "Find a distinct public-camera viewpoint, including the other wrist if "
           "its bounded robot-state path can be specified, or explicitly report "
           "that current RGB cannot justify a safe observation action."
           if args.geometry_evidence else "")
        + (" Camera calibration IS provided. Describe how to derive a current "
           "sensor-only geometric uncertainty from public K/T: use a named physical "
           "same-point correspondence with pixel radii, ray-gap and reprojection "
           "checks only when genuinely visible in two cameras; otherwise describe "
           "silhouette/ray support or report unknown depth. Never call a visual "
           "support set a true object pose, contact or grasp point." if args.calibration and args.method_only else
           " Camera calibration IS provided. In visual_method.initial_correspondences, "
           "name the same physical grasp-relevant landmark in two current RGB views and "
           "give each visible view's pixel_uv and an uncertainty radius in pixels. Omit "
           "uncertain views. Explain a calibrated ray-gap and reprojection check before "
           "any 3D estimate; if no reliable correspondence exists, request a bounded "
           "camera viewpoint move as a sensing action." if args.calibration else "")
    )
    if args.rgb_pose_baseline:
        system += (
            ' This is an explicitly experimental RAW-RGB actor baseline. Runtime supplies '
            'three current raw RGB, measured robot/finger state, public camera K/T and '
            'independent public robot paths. Object-error processors are not enabled in '
            'this baseline. Define task-specific semantic object roles, visual parts '
            'to inspect, stage entry/EXIT criteria and uncertainty that Luna can review '
            'with these actual inputs. Describe extra image processing only as a future '
            'requirement if the baseline fails; never imply absent object metrics or '
            '3D contact certificates are supplied. Preserve current visual veto. '
            'The first bounded observation/test acquires missing evidence; stage EXIT '
            'evidence need not already be proved before that test. No concrete actions.')
        if args.omit_image_payload:
            system += (
                ' No image payload is supplied to YOU in this request. This is a '
                'TASK-GENERAL method from instruction/public robot state and experience, '
                'not a per-layout visual inspection. Never invent observed colors, '
                'positions or selected physical source identities. Luna later sees '
                'the current raw RGB and resolves visual identity under your criteria.')
    if args.method_only:
        system += (
            " PLANNER RESPONSIBILITIES: Design both understandable task stages and "
            "the minimal interpretable inputs that let the decision model advance "
            "those stages. Specify transitions and required preprocessing separately. "
            "Do not suggest any concrete robot action, "
            "world-axis sign, absolute target, displacement, rotation, action candidate, "
            "or gripper command, anywhere in the response. The decision model judges "
            "actions from current sensor-derived numeric evidence produced by separate "
            "algorithms. Describe only semantic source/receiver identity, task stages, "
            "RGB feature extraction, optional same-point correspondence or silhouette "
            "support, calibrated geometry "
            "and uncertainty gates, freshness, visible post-action checks, and recovery "
            "conditions. Include landmark_spec only when the CURRENT named physical "
            "point is visible in every listed view; otherwise describe the visual "
            "source region and its uncertainty without inventing a correspondence. "
            "visual_method must be an object. Never expose native evaluation."
            " In each stage distinguish its purpose, currently available entry evidence, "
            "and EXIT evidence for advancing to another stage. Missing evidence that a "
            "bounded observation/test is meant to acquire cannot also be required as "
            "already proven before that test. EXIT capture/source-following criteria "
            "are not assertions of holding or automatic action permission. Describe "
            "uncertainty/reobservation conditions without proposing robot actions."
        )
    details = {
        "public_observation": public,
        "experience": experience,
        "camera_input_mode": ("RGB-derived numeric and semantic features; raw RGB bytes not transmitted"
                              if args.omit_image_payload else
                              "three current RGB frames transmitted as JPEG"),
    }
    if template:
        details["existing_stage_template"] = template
    if args.omit_image_payload:
        system = system.replace("three supplied RGB frames",
                                "algorithm-derived summaries of three current RGB frames")
        system += (
            " The API gateway did not accept GPT-6.1 Sol high image payloads "
            "in a preceding isolated diagnostic. You are NOT viewing raw RGB "
            "pixels in this call. Use only named RGB-derived features and "
            "their uncertainty from the supplied sensor evidence; do not "
            "invent a visible landmark, pixel coordinate, appearance, "
            "clearance or contact. Luna receives all three current raw RGB "
            "frames independently and makes the action decision.")
    parts = [{"type": "text", "text": json.dumps(details, ensure_ascii=False)}]
    image_meta = []
    for item in obs["images"]:
        if item["camera"] not in {"cam_high", "cam_left_wrist", "cam_right_wrist"}:
            raise ValueError("Unexpected camera")
        image = Path(item["path"])
        raw = image.read_bytes()
        pixels = cv2.imread(str(image))
        original_hw = list(pixels.shape[:2])
        sent_hw = [240, 320]
        pixels = cv2.resize(pixels, (sent_hw[1], sent_hw[0]),
                            interpolation=cv2.INTER_AREA)
        encoded = cv2.imencode(".jpg", pixels,
                               [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
        image_meta.append({"camera": item["camera"], "path": str(image),
                           "sha256": hashlib.sha256(raw).hexdigest(),
                           "submitted_jpeg_quality": 85,
                           "original_hw": original_hw, "submitted_hw": sent_hw,
                           "submitted_sha256": hashlib.sha256(encoded).hexdigest()})
        parts.append({"type": "text", "text":
                      f"Current RGB {item['camera']}; transmitted {sent_hw[1]}x{sent_hw[0]} JPEG from original {original_hw[1]}x{original_hw[0]} RGB. Map image pixels back to original resolution before numeric K/T use."})
        if not args.omit_image_payload:
            parts.append({"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii")}})
    previous_image_meta = []
    if previous:
        for item in previous["images"]:
            if item["camera"] not in {"cam_high", "cam_left_wrist", "cam_right_wrist"}:
                raise ValueError("Unexpected historical camera")
            old_image = Path(item["path"])
            old_raw = old_image.read_bytes()
            old_pixels = cv2.imread(str(old_image))
            old_original_hw = list(old_pixels.shape[:2])
            old_sent_hw = [240, 320]
            old_pixels = cv2.resize(
                old_pixels, (old_sent_hw[1], old_sent_hw[0]),
                interpolation=cv2.INTER_AREA)
            old_encoded = cv2.imencode(
                ".jpg", old_pixels,
                [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
            previous_image_meta.append({"camera": item["camera"], "path": str(old_image),
                                        "sha256": hashlib.sha256(old_raw).hexdigest(),
                                        "submitted_jpeg_quality": 85,
                                        "original_hw": old_original_hw,
                                        "submitted_hw": old_sent_hw,
                                        "submitted_sha256": hashlib.sha256(old_encoded).hexdigest()})
            parts.append({"type": "text", "text":
                          f"HISTORICAL RGB step_id={previous['step_id']} for motion or current-feature temporal correspondence, never current contact: {item['camera']}. Transmitted {old_sent_hw[1]}x{old_sent_hw[0]} JPEG from original {old_original_hw[1]}x{old_original_hw[0]}; map pixels back to original resolution before K/T use."})
            if not args.omit_image_payload:
                parts.append({"type": "image_url", "image_url": {
                    "url": "data:image/jpeg;base64," + base64.b64encode(old_encoded).decode("ascii")}})
    configuration = load_config()
    payload = build_payload(system, parts, configuration["model"])
    manifest = {
        "model": payload["model"], "reasoning_effort": payload["reasoning"]["effort"],
        "provider": "ai2robcowork", "wire_api": "responses",
        "method_only": args.method_only,
        "raw_rgb_transmitted_to_planner": not args.omit_image_payload,
        "selected_recent_experience": args.select_recent_experience,
        "public_observation": public, "images": image_meta,
        "historical_images_for_motion_or_current_feature": previous_image_meta,
        "template_sha256": (hashlib.sha256(args.template.read_bytes()).hexdigest()
                            if args.template else None),
        "geometry_evidence_sha256": (hashlib.sha256(args.geometry_evidence.read_bytes()).hexdigest()
                                     if args.geometry_evidence else None),
        "experience_sha256": {k: hashlib.sha256(v.encode()).hexdigest()
                              for k, v in full_experience.items()},
        "selected_experience_sha256": {
            k: hashlib.sha256(v.encode()).hexdigest()
            for k, v in experience.items()},
    }
    if args.select_recent_experience and '- [phase:' in full_experience['task']:
        manifest['experience_selection_policy']='Literal first identity lesson plus latest tagged lesson per phase'
    if args.response_file:
        prior_manifest = json.loads((args.response_file.parent / "planner-input-manifest.json").read_text())
        if prior_manifest != manifest:
            raise ValueError("Saved response public-input manifest differs")
    write_json(args.output / "planner-input-manifest.json", manifest)
    if args.response_file:
        response = json.loads(args.response_file.read_text())
    else:
        response = request(payload, configuration)
    write_json(args.output / "planner-response.json", response)
    plan = json.loads(output_text(response))
    if (args.method_only and not plan.get("landmark_spec") and
            isinstance(plan.get("visual_method"), dict)):
        plan["landmark_spec"] = plan["visual_method"].get("landmark_spec")
    if isinstance(plan.get("task"), dict) and plan["task"].get("id") == obs["task"]:
        plan["task_detail"] = plan["task"]
        plan["task"] = obs["task"]
    if isinstance(plan.get("stages"), dict):
        plan["stages"] = {
            key: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            if isinstance(value, dict) else value
            for key, value in plan["stages"].items()
        }
    stages = plan.get("stages")
    if (plan.get("task") != obs["task"] or
            not isinstance(stages, dict) or
            not 4 <= len(stages) <= 12 or
            (template and set(stages) != set(template["stages"])) or
            (template and plan.get("initial_stage") != template["initial_stage"]) or
            plan.get("initial_stage") not in stages or
            not all(isinstance(k, str) and k and isinstance(v, str) and v.strip()
                    for k, v in stages.items()) or
            not isinstance(plan.get("visual_method"), (dict, str)) or
            not isinstance(plan.get("experience"), list)):
        raise ValueError("Planner output failed contract validation")
    if args.method_only:
        forbidden = ("action_candidate", "selected_action", "selected_motion",
                     "target_pose", "target_position", "world_delta", "move_xyz")
        def inspect_keys(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if any(word in key.lower() for word in forbidden):
                        raise ValueError("Method-only planner emitted action field: " + key)
                    inspect_keys(item)
            elif isinstance(value, list):
                for item in value:
                    inspect_keys(item)
        inspect_keys(plan)
        spec = plan.get("landmark_spec")
        if not isinstance(plan["visual_method"], dict):
            raise ValueError("Method-only visual-method contract failed")
        if spec is not None and (not isinstance(spec, dict) or
                not set(spec.get("required_views", [])).issubset(
                    {item["camera"] for item in obs["images"]}) or
                not all(isinstance(spec.get(key), str) and spec[key]
                        for key in ("landmark_id", "target_identity", "physical_landmark"))):
            raise ValueError("Method-only optional landmark contract failed")
    plan["planner_provenance"] = {
        "model": configuration["model"], "reasoning_effort": payload["reasoning"]["effort"],
        "auth": "task-scoped AI2RobCoWork API key over Responses",
        "provider": "ai2robcowork", "wire_api": "responses",
        "raw_rgb_transmitted": not args.omit_image_payload,
        "input_manifest": str(args.output / "planner-input-manifest.json"),
    }
    if args.method_only:
        plan["method_only"] = True
    write_json(args.output / "plan.json", plan)
    print(json.dumps({"plan": str(args.output / "plan.json"),
                      "stage_count": len(plan["stages"]),
                      "image_count": len(image_meta)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

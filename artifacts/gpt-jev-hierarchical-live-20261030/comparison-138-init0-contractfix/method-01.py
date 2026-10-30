def main(api):
    s0 = api.state()
    old = api.recall("observe.result")["value"]
    g = old["evidence"]["geometry"]
    env = g["next_approach_envelope"]
    keys = ["observe.result", "observe.samples1", "observe.clearance0", "lift.alignment"]
    memo = {"stage": "lift", "phase": "entry", "start_state": s0, "calls_used": 0, "descent_executed": False, "closure_executed": False, "retention_established": False}
    def finish(status, reason):
        memo["end_state"] = api.state()
        memo["acknowledged_native_steps"] = memo["end_state"]["native_steps"] - s0["native_steps"]
        api.checkpoint("lift.alignment", memo)
        return {"stage_status": status, "reason": reason, "evidence": memo, "handoff": {"checkpoint_keys": keys, "coordinate_frame": "World meters; tool-to-world xyzw quaternions; pixels retain their camera and acquisition frame.", "current_phase": memo["phase"], "assumptions": ["Historical bowl and obstacle geometry is not a current object pose after movement.", "No descent, closure, grasp, retention, or support separation is established by this slice.", "A measured local aperture is not clearance for fingers entering the bowl."], "remaining_lift_evidence": "Validate the next descent segment, acquire the rim pinch, and measure bowl-hand co-motion and visible counter separation. Revalidate affected geometry and any saved tracker before use; do not reopen a possibly held object."}, "completion_proposed": False}
    if s0["frame_id"] != g["frame_id"] or s0["native_steps"] != old["evidence"]["native_steps_end"]:
        return finish("blocked", "Entry observations are no longer same-frame. Reconcile acknowledged actions and existing checkpoints before reusing the high-alignment envelope.")
    if s0["last_gripper_command"] != "open":
        return finish("blocked", "The expected open, unladen entry is not established. No gripper command was sent.")
    clear = api.recall("observe.clearance0")["value"]
    names = ["high0", "high1", "high2", "high3"]
    errors = [e["name"] for e in clear["measurement_errors"]]
    if clear["frame_id"] != s0["frame_id"] or any(n not in clear["points"] or n in errors for n in names):
        return finish("blocked", "Same-frame valid obstacle-height measurements are missing.")
    if clear["interpretation"]["coverage"] != "complete" or clear["interpretation"]["robot_clear"] != "visible_clear":
        return finish("blocked", "The saved high-only envelope lacks observed coverage.")
    top = max(float(clear["points"][n]["world_m"][2]) for n in names)
    pad0 = np.asarray(geo.pad_position(s0), dtype=float)
    if float(np.linalg.norm(pad0 - np.asarray(env["pad_start_world_m"]))) > 0.002:
        return finish("blocked", "The measured hand no longer matches the authorized envelope start.")
    radial = np.asarray(g["grasp_region"]["outward_radial_xy"], dtype=float)
    R0 = geo.rotation(s0["tcp_quaternion_xyzw"])
    yaw = math.atan2(float(radial[1]), float(radial[0])) - math.atan2(float(R0[1, 1]), float(R0[0, 1]))
    yaw = (yaw + math.pi / 2.0) % math.pi - math.pi / 2.0
    quat = api.compose(s0["tcp_quaternion_xyzw"], [0.0, 0.0, yaw])
    target = np.asarray(env["high_pad_alignment_world_m"], dtype=float)
    target[2] = pad0[2]
    memo.update({"target_pad_world_m": target.tolist(), "target_quaternion_xyzw": quat, "world_yaw_rad": float(yaw), "obstacle_top_z_m": top, "reference_frame": g["frame_id"], "authority": "High open-hand alignment and downward-tool world yaw only."})
    questions = {}
    for axis in ["x", "y", "z", "rx", "ry", "rz"]:
        questions[axis] = {"type": "choice", "instructions": "For " + axis + ", read state.processed_features.axes." + axis + ".goal_relation. Select positive for increase, negative for decrease, hold for within_tolerance. This corrects only the authorized high pose; do not infer clearance or possession.", "criteria": {"negative": "Decrease this world coordinate or world rotation-vector component.", "hold": "Apply no correction within its supplied tolerance.", "positive": "Increase this world coordinate or world rotation-vector component."}}
    questions["gripper"] = {"type": "choice", "instructions": "Read state.processed_features.objective.gripper. This slice requires keep; preserve the existing open command without initiating closure or reopening.", "criteria": {"open": "Only deliver an explicitly supplied open objective.", "close": "Only deliver an explicitly supplied close objective.", "keep": "Preserve the existing gripper command as required."}}
    def envelope_check(state):
        own = state["own_geometry"]
        lo, hi = own["finger_low_offset_tool_m"], own["finger_high_offset_tool_m"]
        corners = np.asarray([[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]])
        world = corners @ geo.rotation(state["tcp_quaternion_xyzw"]).T + np.asarray(state["tcp_position_world_m"])
        margin = float(np.min(world[:, 2])) - top - env["height_measurement_allowance_m"]
        inside = bool(np.all(np.min(world[:, :2], axis=0) >= np.asarray(env["xy_min_m"])) and np.all(np.max(world[:, :2], axis=0) <= np.asarray(env["xy_max_m"])))
        return inside and margin >= env["required_height_margin_m"], margin
    cap = min(23, int(s0["budgets"]["jev_remaining"]), int(s0["budgets"]["native_steps_remaining"]) // 3)
    if cap < 1 or s0["budgets"]["gpt_remaining"] < 1:
        return finish("yield", "Insufficient budget for a bounded action followed by fresh observation.")
    memo["phase"] = "high_alignment"
    api.checkpoint("lift.alignment", memo)
    stop = ""
    for i in range(cap):
        state = api.state()
        safe, margin = envelope_check(state)
        if not safe:
            stop = "Measured finger bounds leave the previously authorized high envelope."
            break
        features = {"source": "Historical same-entry-frame visible obstacle depths plus current own robot geometry.", "phase": "high_alignment_only", "reference_frame": g["frame_id"], "obstacle_top_z_m": top, "current_height_margin_after_allowance_m": margin, "required_height_margin_m": env["required_height_margin_m"], "target_pad_world_m": target.tolist(), "world_yaw_rad": float(yaw), "descent_authorized": False, "closure_authorized": False}
        receipt = api.control(target.tolist(), quat, "keep", questions, features=features, tool_point="pad_center", translation_limit=0.02, rotation_limit=0.10, steps=3, position_tolerance=0.004, rotation_tolerance=0.04)
        memo["calls_used"] = i + 1
        memo["last_receipt"] = receipt
        memo["last_acknowledged_state"] = api.state()
        api.checkpoint("lift.alignment", memo)
        if receipt["choices"]["gripper"] != "keep":
            stop = "Acknowledged gripper choice differs from the keep objective; do not undo it blindly."
            break
        if receipt["status"] == "stalled":
            stop = "High alignment stalled; no repetition or descent is authorized."
            break
        if receipt["status"] == "reached":
            break
    sf = api.state()
    safe, margin = envelope_check(sf)
    memo["final_height_margin_m"] = margin
    if not safe:
        stop = "Post-action own-finger envelope fails the unchanged clearance margin."
    point_names = ["inner", "outer", "band0", "band1", "pad_a", "pad_b"]
    spec = {"type": "object", "properties": {"camera": {"type": "string", "enum": ["agentview", "robot0_eye_in_hand"]}, "pixel": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}, "visible": {"type": "boolean"}}}
    fields = {n: spec for n in point_names}
    fields.update({"bowl": ["same_upright_on_counter", "moved_or_tipped", "unknown"], "hand": ["clear_above_bowl", "contact_or_collision", "unknown"], "band": ["same_accessible_pinch_band", "changed_or_obstructed", "unknown"], "pad_faces": ["both_inner_contact_faces_visible", "unknown"], "patch_identity": ["patterned_bowl_only", "unknown"], "patch_camera": ["agentview", "robot0_eye_in_hand"], "patch_polygon": {"type": "array", "items": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}, "maxItems": 16}})
    question = "Fresh post-high-alignment observation, not a grasp assessment. Check that the same patterned bowl remains upright on the counter and the robot is visibly clear. Request six named depth points: inner and outer are the opposed bowl wall surfaces at the historical world +x rim-pinch sector, about 8 mm below its rim, at matching height; band0 and band1 are the ends of the same continuous approximately 40 mm tangential rim band. Preserve physical sector identity, not screen direction. pad_a and pad_b are the centers of the actual two opposing inner finger contact faces on the CURRENT open hand, not its silhouette or outer faces. Mark unavailable faces invisible instead of guessing. Select a 3-16 vertex polygon wholly within visible textured bowl material away from this pinch sector, excluding robot, rim boundaries and background, for a future motion reference; otherwise patch_identity unknown and polygon empty. Return all declared parameters and named depth measurements. Do not certify unseen descent space, possession, or retention."
    review = api.review(question, context={"historical_frame": g["frame_id"], "historical_grasp_region": g["grasp_region"], "historical_bowl": g["bowl"], "current_hand": sf, "authorized_motion": memo["authority"], "stop_reason": stop}, fields=fields)
    obs = {"frame_id": review["frame_id"], "parameters": review["parameters"], "points": review["points"], "measurement_errors": [{"name": e["name"], "error": e["error"][:300]} for e in review["measurement_errors"]], "interpretation": review["explanation"][:1200], "fallbacks": []}
    keys.append("lift.measurements")
    api.checkpoint("lift.measurements", obs)
    p = review["parameters"]
    memo["post_review"] = {"frame_id": review["frame_id"], "bowl": p["bowl"], "hand": p["hand"], "band": p["band"], "pad_faces": p["pad_faces"]}
    if p["bowl"] == "moved_or_tipped" or p["hand"] == "contact_or_collision" or p["band"] == "changed_or_obstructed":
        return finish("needs_replan", "Fresh observation invalidates the untouched-bowl or clear-high-approach assumptions.")
    if stop or review["status"] == "stop":
        return finish("blocked", stop or "The fresh observer requests stopping; preserve the current physical state.")
    if p["bowl"] != "same_upright_on_counter" or p["hand"] != "clear_above_bowl" or p["band"] != "same_accessible_pinch_band":
        return finish("blocked", "Current bowl identity, supported state, or hand clearance is unresolved; see lift.measurements.")
    failed = [e["name"] for e in review["measurement_errors"]]
    valid = {}
    for n in point_names:
        if p[n]["visible"] and n in review["points"] and n not in failed and review["points"][n]["frame_id"] == sf["frame_id"]:
            valid[n] = review["points"][n]
        elif p[n]["visible"]:
            try:
                sample = api.point(p[n]["camera"], p[n]["pixel"], radius=1)
                if sample["frame_id"] == sf["frame_id"]:
                    valid[n] = sample
                obs["fallbacks"].append({"name": n, "radius": 1, "sample": sample})
            except Exception as error:
                obs["fallbacks"].append({"name": n, "radius": 1, "error": str(error)[:300]})
    obs["valid_points"] = valid
    api.checkpoint("lift.measurements", obs)
    missing = [n for n in point_names if n not in valid]
    if missing or p["pad_faces"] != "both_inner_contact_faces_visible":
        memo["measurement_gap"] = {"missing_valid_depth": missing, "pad_faces": p["pad_faces"]}
        return finish("blocked", "High movement is acknowledged, but local pinch/aperture depths remain unresolved after a bounded smaller-depth-patch attempt. Do not descend from these data.")
    xyz = {n: np.asarray(valid[n]["world_m"], dtype=float) for n in point_names}
    center = (xyz["inner"] + xyz["outer"]) / 2.0
    tangent = np.asarray([-radial[1], radial[0]])
    thickness = abs(float(np.dot((xyz["outer"] - xyz["inner"])[:2], radial)))
    span = abs(float(np.dot((xyz["band1"] - xyz["band0"])[:2], tangent)))
    df = geo.rotation(sf["tcp_quaternion_xyzw"]).T @ (xyz["pad_b"] - xyz["pad_a"])
    aperture = abs(float(df[1]))
    midpoint_error = float(np.linalg.norm((xyz["pad_a"] + xyz["pad_b"]) / 2.0 - np.asarray(geo.pad_position(sf))))
    metric = {"frame_id": sf["frame_id"], "candidate_center_world_m": center.tolist(), "local_wall_thickness_m": thickness, "tangent_band_span_m": span, "sampled_open_aperture_m": aperture, "aperture_minus_wall_after_allowances_m": aperture - thickness - 0.012, "pad_sample_midpoint_error_m": midpoint_error, "scope": "Local samples only, not descent or full finger-sweep clearance."}
    memo["fresh_local_geometry"] = metric
    if thickness > 0.012 or abs(float(xyz["inner"][2] - xyz["outer"][2])) > 0.004 or span < float(sf["own_geometry"]["pad_extent_in_tool_m"][0]) + 0.012 or aperture - thickness - 0.012 < 0.010 or midpoint_error > 0.020 or abs(float(df[0])) > 0.012 or abs(float(df[2])) > 0.012 or float(np.linalg.norm(center - np.asarray(g["grasp_region"]["candidate_center_world_m"]))) > 0.010:
        return finish("blocked", "Fresh contact/aperture measurements fail an explicit unchanged geometry margin; inspect the numerical gap before further motion.")
    if p["patch_identity"] == "patterned_bowl_only" and 3 <= len(p["patch_polygon"]) <= 16:
        try:
            track = api.track_init(p["patch_camera"], p["patch_polygon"])
            patch = {"handle": track["handle"], "reference_frame_id": track["frame_id"], "camera": p["patch_camera"], "polygon": p["patch_polygon"], "physical_identity": "Textured material of the same patterned bowl, away from the world +x pinch sector.", "provenance": "Initialized after high alignment, before any descent or closure. Not retention evidence."}
            api.checkpoint("lift.patch", patch)
            keys.append("lift.patch")
            memo["tracker_handle"] = track["handle"]
        except Exception as error:
            memo["tracker_gap"] = str(error)[:600]
    else:
        memo["tracker_gap"] = "No unambiguous bowl-only polygon was visible."
    position_error = float(np.linalg.norm(np.asarray(geo.pad_position(sf)) - target))
    rotation_error = math.acos(max(-1.0, min(1.0, float((np.trace(geo.rotation(quat) @ geo.rotation(sf["tcp_quaternion_xyzw"]).T) - 1.0) / 2.0))))
    memo["high_pose_errors"] = {"position_m": position_error, "rotation_rad": rotation_error}
    memo["phase"] = "high_aligned_observed" if position_error <= 0.004 and rotation_error <= 0.04 else "partial_high_alignment_observed"
    return finish("yield", "Bounded lift slice made only high open-hand alignment and refreshed local geometry. Further lift processing is required: descent clearance, closure, actual retention, and counter separation are not established.")

def main(api):
    s0 = api.state()
    alignment = api.recall("lift.alignment")["value"]
    previous = api.recall("lift.measurements")["value"]
    keys = ["observe.result", "lift.alignment", "lift.measurements", "lift.view_recovery", "lift.view_samples"]
    memo = {"stage": "lift", "phase": "complementary_high_view", "start_state": s0, "prior_native_steps": s0["native_steps"], "calls": 0, "retention_established": False}
    samples = {}
    def finish(status, reason):
        memo["end_state"] = api.state()
        memo["new_native_steps"] = memo["end_state"]["native_steps"] - s0["native_steps"]
        api.checkpoint("lift.view_recovery", memo)
        return {"stage_status": status, "reason": reason, "evidence": memo, "handoff": {"checkpoint_keys": keys, "frames": "World meters; tool-to-world xyzw; image samples retain camera and acquisition frame.", "provenance": "lift.alignment and lift.measurements preserve the earlier 69 acknowledged steps and bowl samples. lift.view_recovery records this turn's measured envelope, orientation target, receipts, and any tool-frame pad calibration. lift.view_samples preserves valid partial RGB-D samples and errors.", "scope": "Only a high observation-producing turn was requested. No approach descent, closure, or bowl lift was requested; inspect receipts for actual choices. No retention is established.", "reference_rules": "Pad calibration, if present, is expressed in the measured tool frame, not reusable pixels. Revalidate unchanged finger qpos, own geometry and face identity before propagating it to a new orientation. Reobserve the bowl and local finger-entry corridor before descent. Historical clearance is not descent authorization. Never reopen automatically after an unexpected gripper choice.", "remaining_effect": "The lift stage still requires acquisition, observed bowl-hand co-motion, visible counter separation, and updated retained-bowl extent. No transfer or placement is authorized by this result."}, "completion_proposed": False}
    def angle(q1, q2):
        c = float((np.trace(geo.rotation(q1) @ geo.rotation(q2).T) - 1.0) / 2.0)
        return math.acos(max(-1.0, min(1.0, c)))
    def finger_radius(state):
        lo, hi = state["own_geometry"]["finger_low_offset_tool_m"], state["own_geometry"]["finger_high_offset_tool_m"]
        return max(float(np.linalg.norm([x, y, z])) for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]])
    spec = {"type": "object", "properties": {"camera": {"type": "string", "enum": ["agentview", "robot0_eye_in_hand"]}, "pixel": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}, "visible": {"type": "boolean"}}}
    def collect(review, names, label):
        obs = {"frame_id": review["frame_id"], "parameters": review["parameters"], "points": review["points"], "measurement_errors": review["measurement_errors"], "interpretation": review["explanation"][:1000], "fallbacks": [], "valid": {}}
        samples[label] = obs
        api.checkpoint("lift.view_samples", samples)
        errors = [e["name"] for e in review["measurement_errors"]]
        for n in names:
            p = review["parameters"][n]
            if not p["visible"]:
                continue
            if n in review["points"] and n not in errors and review["points"][n]["frame_id"] == review["frame_id"]:
                obs["valid"][n] = review["points"][n]
            else:
                try:
                    pt = api.point(p["camera"], p["pixel"], radius=1)
                    obs["fallbacks"].append({"name": n, "sample": pt})
                    if pt["frame_id"] == review["frame_id"]:
                        obs["valid"][n] = pt
                except Exception as error:
                    obs["fallbacks"].append({"name": n, "error": str(error)[:300]})
        api.checkpoint("lift.view_samples", samples)
        return obs["valid"]
    if s0["frame_id"] != previous["frame_id"] or s0["native_steps"] != alignment["end_state"]["native_steps"]:
        return finish("blocked", "Entry differs from the acknowledged high alignment. Reconcile actions before using its bowl labels or planning this diagnostic turn.")
    if s0["last_gripper_command"] != "open" or alignment["closure_executed"] or alignment["descent_executed"]:
        return finish("blocked", "Expected open, high, pre-contact entry is not established; no reopening is permitted.")
    if s0["budgets"]["gpt_remaining"] < 2:
        return finish("yield", "Reserve two reviews for fresh turn clearance and the changed-view effect.")
    cap = min(23, int(s0["budgets"]["jev_remaining"]), int(s0["budgets"]["native_steps_remaining"]) // 3)
    if cap < 1:
        return finish("yield", "No bounded physical observation budget remains.")
    camera = api.camera("agentview")
    if camera["frame_id"] != s0["frame_id"]:
        return finish("blocked", "Camera calibration and robot pose are not same-frame.")
    tcp = np.asarray(s0["tcp_position_world_m"], dtype=float)
    view = np.asarray(camera["camera_to_world_opencv"], dtype=float)[:3, 3] - tcp
    view = view / np.linalg.norm(view)
    R = geo.rotation(s0["tcp_quaternion_xyzw"])
    a, b, c = float(np.dot(R[:2, 1], view[:2])), float(R[0, 1] * view[1] - R[1, 1] * view[0]), float(R[2, 1] * view[2])
    amplitude = math.sqrt(a * a + b * b)
    if amplitude < 0.1 or abs(c) >= amplitude:
        return finish("blocked", "A bounded side-on pad observation cannot be constructed from this camera direction.")
    phi, alpha = math.atan2(b, a), math.acos(-c / amplitude)
    turns = [(phi + alpha + math.pi) % (2.0 * math.pi) - math.pi, (phi - alpha + math.pi) % (2.0 * math.pi) - math.pi]
    yaw = turns[0] if abs(turns[0]) <= abs(turns[1]) else turns[1]
    qside = api.compose(s0["tcp_quaternion_xyzw"], [0.0, 0.0, yaw])
    Rs = geo.rotation(qside)
    facing = float(np.dot(Rs[:, 2], view))
    tilt = max(0.0, math.asin(0.25) - math.asin(max(-1.0, min(1.0, facing))))
    if tilt > 0.95:
        return finish("blocked", "Exposing the inner faces would require more than the authorized 0.95 rad diagnostic tilt.")
    sign = 1.0 if float(np.dot(np.cross(Rs[:, 1], Rs[:, 2]), view)) >= 0.0 else -1.0
    quat = api.compose(qside, (sign * tilt * Rs[:, 1]).tolist())
    base_radius = finger_radius(s0)
    radius = base_radius + 0.005
    memo["view_plan"] = {"tcp_target_world_m": tcp.tolist(), "quaternion_target_xyzw": quat, "world_yaw_rad": yaw, "tool_y_tilt_rad": sign * tilt, "camera_direction_world": view.tolist(), "finger_sphere_radius_m": radius, "tcp_drift_bound_m": 0.004, "geometry_growth_bound_m": 0.001, "height_allowance_m": 0.005, "required_margin_m": 0.020}
    names = ["h0", "h1", "h2", "h3"]
    fields = {n: spec for n in names}
    fields.update({"bowl": ["same_upright_on_counter", "disturbed", "unknown"], "turn_space": ["visibly_accounted", "obstructed", "unknown"], "height_coverage": ["all_relevant_tops_visible", "incomplete"], "proximal_hand": ["visible_clear_turn", "concern", "unknown"]})
    pre = api.review("This is a NEW high observation-turn clearance question, not another attempt to sample occluded pads. The TCP will stay fixed while the jaw opening is turned side-on to agentview and tilted toward it; the planned tool +z faces that camera with dot product 0.25. Check the supplied conservative all-orientation finger sphere and the actual visible proximal hand/wrist turn. Request named current depth samples h0,h1,h2,h3 on the highest relevant NON-ROBOT scene surfaces in the sphere's vertical XY column; multiple samples of one highest surface are acceptable. Account for every object intersecting that column using both views, including surfaces above or behind the hand if present. Mark height coverage incomplete if an obscured relevant top prevents an upper bound; do not invent hidden clearance. turn_space and proximal_hand concern this high diagnostic turn only, never descent. Check that the same bowl is upright and untouched. Do not require successful future pad visibility as a prerequisite.", context={"plan": memo["view_plan"], "current_robot": s0, "previous_observation": {"frame_id": previous["frame_id"], "parameters": previous["parameters"]}, "finger_sphere_center_world_m": tcp.tolist(), "xy_min_m": (tcp[:2] - radius).tolist(), "xy_max_m": (tcp[:2] + radius).tolist()}, fields=fields)
    valid = collect(pre, names, "before_turn")
    p = pre["parameters"]
    if p["bowl"] == "disturbed":
        return finish("needs_replan", "Fresh observation contradicts the untouched supported-bowl assumption.")
    if pre["status"] == "stop" or p["bowl"] != "same_upright_on_counter" or p["turn_space"] != "visibly_accounted" or p["height_coverage"] != "all_relevant_tops_visible" or p["proximal_hand"] != "visible_clear_turn":
        return finish("blocked", "Fresh visible coverage does not authorize this particular high complementary turn; see the saved coverage and proximal-hand findings.")
    if pre["frame_id"] != s0["frame_id"] or any(n not in valid for n in names):
        return finish("blocked", "The turn's upper-height bound lacks same-frame valid samples after one smaller-patch attempt; partial measurements are saved.")
    top = max(float(valid[n]["world_m"][2]) for n in names)
    margin = float(tcp[2]) - radius - top - 0.005
    memo["clearance"] = {"frame_id": pre["frame_id"], "visible_top_z_m": top, "sphere_height_margin_m": margin, "required_margin_m": 0.020, "scope": "High diagnostic turn only; visible stationary scene assumption."}
    if margin < 0.020:
        return finish("blocked", "The full-orientation finger sphere fails the unchanged 20 mm clearance plus 5 mm height allowance.")
    questions = {}
    for axis in ["x", "y", "z", "rx", "ry", "rz"]:
        questions[axis] = {"type": "choice", "instructions": "For " + axis + ", use state.processed_features.axes." + axis + ".goal_relation: increase means positive, decrease means negative, within_tolerance means hold. Correct only the supplied fixed-TCP diagnostic orientation. Do not infer scene clearance.", "criteria": {"negative": "Decrease this world coordinate or world rotation-vector component.", "hold": "Apply no component correction within tolerance.", "positive": "Increase this world coordinate or world rotation-vector component."}}
    questions["gripper"] = {"type": "choice", "instructions": "Use state.processed_features.objective.gripper. This diagnostic turn requires keep, preserving the existing open command. Neither closure nor a new opening is requested.", "criteria": {"open": "Deliver only an explicitly supplied open objective.", "close": "Deliver only an explicitly supplied close objective.", "keep": "Preserve the existing gripper command, as required here."}}
    stop, stagnant = "", 0
    api.checkpoint("lift.view_recovery", memo)
    for i in range(cap):
        before = api.state()
        if float(np.linalg.norm(np.asarray(before["tcp_position_world_m"]) - tcp)) > 0.004 or finger_radius(before) > base_radius + 0.001 or float(np.max(np.abs(np.asarray(before["gripper_qpos_m"]) - np.asarray(s0["gripper_qpos_m"])))) > 0.001:
            stop = "Measured hand drift, finger extent or opening left the admitted turn bounds."
            break
        if before["budgets"]["jev_remaining"] < 1 or before["budgets"]["native_steps_remaining"] < 3:
            break
        features = {"source": "Fresh pre-turn RGB-D top samples and current proprioception; no hidden-object sensing.", "phase": "high_pad_observation_turn", "clearance": memo["clearance"], "view_plan": memo["view_plan"], "current_tcp_drift_m": float(np.linalg.norm(np.asarray(before["tcp_position_world_m"]) - tcp)), "descent_authorized": False, "closure_authorized": False}
        receipt = api.control(tcp.tolist(), quat, "keep", questions, features=features, translation_limit=0.003, rotation_limit=0.10, steps=3, position_tolerance=0.002, rotation_tolerance=0.025)
        after = api.state()
        memo.update({"calls": i + 1, "last_receipt": receipt, "last_acknowledged_state": after})
        api.checkpoint("lift.view_recovery", memo)
        if receipt["choices"]["gripper"] != "keep" or after["last_gripper_command"] != "open":
            stop = "Unexpected acknowledged gripper delivery; do not reverse it blindly."
            break
        if receipt["status"] == "stalled":
            stop = "Diagnostic turn stalled; the same command will not be repeated."
            break
        progress = angle(before["tcp_quaternion_xyzw"], quat) - angle(after["tcp_quaternion_xyzw"], quat)
        stagnant = stagnant + 1 if progress < 0.001 and float(np.linalg.norm(np.asarray(after["tcp_position_world_m"]) - np.asarray(before["tcp_position_world_m"]))) < 0.0003 else 0
        if stagnant >= 3 or progress < -0.03:
            stop = "Observed orientation failed to progress or moved materially away from the objective."
            break
        if receipt["status"] == "reached":
            break
    sf = api.state()
    drift = float(np.linalg.norm(np.asarray(sf["tcp_position_world_m"]) - tcp))
    if drift > 0.004 or finger_radius(sf) > base_radius + 0.001 or float(np.max(np.abs(np.asarray(sf["gripper_qpos_m"]) - np.asarray(s0["gripper_qpos_m"])))) > 0.001:
        stop = "Post-turn measured hand geometry leaves the admitted bounds."
    memo["pose_errors"] = {"tcp_drift_m": drift, "rotation_rad": angle(sf["tcp_quaternion_xyzw"], quat)}
    fields = {"pad_a": spec, "pad_b": spec, "faces": ["two_actual_inner_face_centers", "not_both_visible", "unknown"], "bowl": ["same_upright_on_counter", "disturbed", "unknown"], "hand": ["visibly_clear", "contact_or_collision", "unknown"]}
    post = api.review("Assess the ACTUALLY EXECUTED changed high view, not the target pose. Request pad_a and pad_b at the centers of the two actual opposing inner finger contact faces, in either order and whichever current view exposes each. Do not use silhouettes, outer faces, fingertips, or placeholder pixels. Set visible false for an unidentifiable center; no extrapolated depth. Check that the same patterned bowl remains upright on its original counter and the hand remains visibly clear. This is a pad-geometry calibration, not a grasp or lift assessment. Report all declared fields even when the turn is partial or stopped.", context={"state": sf, "view_plan": memo["view_plan"], "execution_stop": stop, "historical_bowl_points_frame": previous["frame_id"], "historical_bowl_points": previous["points"]}, fields=fields)
    pads = collect(post, ["pad_a", "pad_b"], "after_turn")
    memo["post_review"] = {"frame_id": post["frame_id"], "parameters": post["parameters"], "stop": stop}
    if post["parameters"]["bowl"] == "disturbed" or post["parameters"]["hand"] == "contact_or_collision":
        return finish("needs_replan", "The changed-view observation reports bowl disturbance or contact; establish actual state before any further manipulation.")
    if stop or post["status"] == "stop":
        return finish("blocked", stop or "The fresh observer requests stopping.")
    if post["frame_id"] != sf["frame_id"] or post["parameters"]["bowl"] != "same_upright_on_counter" or post["parameters"]["hand"] != "visibly_clear":
        return finish("blocked", "Current bowl identity/support or robot separation is unresolved.")
    if post["parameters"]["faces"] != "two_actual_inner_face_centers" or any(n not in pads for n in ["pad_a", "pad_b"]):
        partial = memo["pose_errors"]["rotation_rad"] > 0.025 or drift > 0.002
        return finish("yield" if partial else "blocked", "The complementary turn is partial and pad calibration remains unavailable; preserve its actual pose." if partial else "The completed complementary view still does not expose both true pad-face centers. The exact visibility/depth gap is saved; do not repeat unchanged sampling or descend.")
    Rt = geo.rotation(sf["tcp_quaternion_xyzw"]).T
    local = {n: Rt @ (np.asarray(pads[n]["world_m"]) - np.asarray(sf["tcp_position_world_m"])) for n in ["pad_a", "pad_b"]}
    delta = local["pad_b"] - local["pad_a"]
    pc = np.asarray(sf["own_geometry"]["pad_center_in_tool_m"])
    midpoint_error = float(np.linalg.norm((local["pad_a"] + local["pad_b"]) / 2.0 - pc))
    aperture = abs(float(delta[1]))
    lo, hi = np.asarray(sf["own_geometry"]["finger_low_offset_tool_m"]), np.asarray(sf["own_geometry"]["finger_high_offset_tool_m"])
    calibration = {"frame_id": sf["frame_id"], "state": sf, "face_centers_tool_m": {n: local[n].tolist() for n in local}, "aperture_m": aperture, "midpoint_error_m": midpoint_error, "off_axis_difference_m": [float(delta[0]), float(delta[2])], "per_surface_allowance_m": 0.003, "scope": "Two visible face-center samples at this measured opening, not whole-face shape, finger-entry clearance, or a grasp certificate."}
    memo["pad_calibration"] = calibration
    if aperture < 0.024 or midpoint_error > 0.015 or abs(float(delta[0])) > 0.012 or abs(float(delta[2])) > 0.012 or min(float(local[n][1] - pc[1]) for n in local) >= 0.0 or max(float(local[n][1] - pc[1]) for n in local) <= 0.0 or any(not bool(np.all(local[n] >= lo - 0.006) and np.all(local[n] <= hi + 0.006)) for n in local):
        return finish("blocked", "Changed-view pad samples fail explicit opposing-face, midpoint, alignment, or own-finger bounds. Preserve the measurements instead of treating them as an aperture certificate.")
    memo["phase"] = "high_view_pad_calibrated"
    return finish("yield", "Fresh changed-view RGB-D establishes tool-frame inner pad centers while the bowl remains supported and the hand clear. The lift effect is not yet achieved; continue only after revalidating the approach from this actual turned pose.")

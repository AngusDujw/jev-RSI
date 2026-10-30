def main(api):
    s0 = api.state()
    old = api.recall("lift.view_recovery")["value"]
    samples = {}
    memo = {"stage": "lift", "phase": "single_inner_face_observation", "entry_state": s0, "calls": 0, "retention_established": False, "recent_updates": []}
    keys = ["observe.result", "lift.alignment", "lift.measurements", "lift.view_recovery", "lift.view_samples", "lift.turn_v3", "lift.face_v3"]
    def finish(status, reason):
        memo["end_state"] = api.state()
        memo["new_native_steps"] = memo["end_state"]["native_steps"] - s0["native_steps"]
        api.checkpoint("lift.turn_v3", memo)
        api.checkpoint("lift.face_v3", samples)
        return {"stage_status": status, "reason": reason, "evidence": memo, "handoff": {"checkpoint_keys": keys, "frames": "World meters; tool-to-world xyzw. Each depth sample retains its acquisition frame and camera.", "provenance": "Old checkpoints are preserved. lift.turn_v3 stores the actual frame-72 restart, measured previous drift, newly assessed swept envelope, target, acknowledged progress and optional one-face tool coordinates. lift.face_v3 stores fresh review samples, errors and valid partial measurements.", "scope": "High observation maneuver only. No descent, closure, acquisition, transfer or release was requested. Inspect actual receipts before resuming; never reopen automatically.", "dependencies": "One-face coordinates, if obtained, apply only to this same physical finger at the saved opening and own geometry. They are not pad centers, a full aperture measurement or descent clearance. Revalidate finger identity and opening before propagation. Never reuse image pixels after movement. Historical bowl geometry requires fresh identity and stationarity validation.", "remaining_effect": "Lift remains unachieved: contact geometry and entry clearance, acquisition, observed bowl-hand co-motion, visible counter separation and retained extent are still required.", "resume_information": "The remaining orientation error and actual end state describe any unfinished observation turn. Do not repeat an unchanged visibility review; use a genuinely changed view or a different measurement."}, "completion_proposed": False}
    def angle(a, b):
        c = float((np.trace(geo.rotation(a) @ geo.rotation(b).T) - 1.0) / 2.0)
        return math.acos(max(-1.0, min(1.0, c)))
    def radius(s):
        lo, hi = s["own_geometry"]["finger_low_offset_tool_m"], s["own_geometry"]["finger_high_offset_tool_m"]
        return max(float(np.linalg.norm([x, y, z])) for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]])
    def record(r, label, names):
        bad = [e["name"] for e in r["measurement_errors"]]
        valid = {}
        for n in names:
            if n in r["points"] and n not in bad:
                pt = r["points"][n]
                a = np.asarray(pt["world_m"], dtype=float)
                if pt["frame_id"] == r["frame_id"] and a.shape == (3,) and bool(np.all(np.isfinite(a))):
                    valid[n] = pt
        samples[label] = {"frame_id": r["frame_id"], "parameters": r["parameters"], "points": r["points"], "measurement_errors": r["measurement_errors"], "valid": valid, "explanation": r["explanation"][:1200]}
        api.checkpoint("lift.face_v3", samples)
        return valid
    if s0["frame_id"] != old["end_state"]["frame_id"] or s0["native_steps"] != old["end_state"]["native_steps"]:
        return finish("blocked", "Entry does not match the last acknowledged recovery checkpoint; reconcile intervening actions.")
    if s0["last_gripper_command"] != "open" or old["retention_established"]:
        return finish("blocked", "The expected open, unretained high entry is not established; no reopening is allowed.")
    if s0["budgets"]["gpt_remaining"] < 3:
        return finish("yield", "Reserve clearance, one depth-replacement review if needed, and a changed-view effect review.")
    cap = min(23, int(s0["budgets"]["jev_remaining"]), int(s0["budgets"]["native_steps_remaining"]) // 3)
    if cap < 1:
        return finish("yield", "No observation-motion budget remains.")
    tcp = np.asarray(s0["tcp_position_world_m"], dtype=float)
    camera = api.camera("agentview")
    if camera["frame_id"] != s0["frame_id"]:
        return finish("blocked", "Camera calibration is not current with the entry state.")
    view = np.asarray(camera["camera_to_world_opencv"], dtype=float)[:3, 3] - tcp
    view = view / np.linalg.norm(view)
    R = geo.rotation(s0["tcp_quaternion_xyzw"])
    yaw0 = math.atan2(float(view[1]), float(view[0])) - math.atan2(float(R[1, 1]), float(R[0, 1]))
    turns = [(yaw0 + k + math.pi) % (2.0 * math.pi) - math.pi for k in [0.0, math.pi]]
    yaw = turns[0] if abs(turns[0]) <= abs(turns[1]) else turns[1]
    qside = api.compose(s0["tcp_quaternion_xyzw"], [0.0, 0.0, yaw])
    Rs = geo.rotation(qside)
    vy, vz = float(np.dot(Rs[:, 1], view)), float(np.dot(Rs[:, 2], view))
    sign = 1.0 if vy >= 0.0 else -1.0
    roll = (math.atan2(vz, vy) - math.atan2(0.5, sign * math.sqrt(0.75)) + math.pi) % (2.0 * math.pi) - math.pi
    quat = api.compose(qside, (roll * Rs[:, 0]).tolist())
    if abs(roll) > 1.35 or angle(s0["tcp_quaternion_xyzw"], quat) > 1.45:
        return finish("blocked", "The selected single-face view exceeds this bounded high-turn scope.")
    observed = float(np.linalg.norm(np.asarray(old["last_acknowledged_state"]["tcp_position_world_m"]) - np.asarray(old["start_state"]["tcp_position_world_m"])))
    guard = float(old["view_plan"]["tcp_drift_bound_m"])
    transient = max(0.006, 2.0 * observed)
    base_radius = radius(s0)
    envelope = base_radius + 0.001 + guard + transient
    plan = {"anchor_tcp_world_m": tcp.tolist(), "target_quaternion_xyzw": quat, "yaw_rad": yaw, "roll_rad": roll, "intended_finger_tool_y_sign": -sign, "camera_direction_world": view.tolist(), "previous_three_step_tcp_drift_m": observed, "recenter_trigger_m": guard, "single_update_displacement_allowance_m": transient, "maximum_tcp_excursion_m": guard + transient, "finger_growth_allowance_m": 0.001, "swept_finger_sphere_radius_m": envelope, "height_allowance_m": 0.005, "required_clearance_m": 0.020, "allowance_basis": "Twice the measured prior three-step displacement is an engineering allowance, not a certified dynamics bound. Freshly assess the entire enlarged swept volume; retain the old 4 mm threshold as a rotation-stop/recentering trigger."}
    memo["plan"] = plan
    fields = {"bowl": ["same_upright_supported", "disturbed", "unknown"], "coverage": ["complete_visible_height_bound", "obstructed", "unknown"], "proximal_turn": ["visibly_clear", "concern", "unknown"]}
    names = ["h0", "h1", "h2"]
    context = {"plan": plan, "state": s0, "xy_min_m": (tcp[:2] - envelope).tolist(), "xy_max_m": (tcp[:2] + envelope).tolist(), "prior_stop": "One turn executed; 4.89441 mm drift exceeded the old fixed-TCP assumption. No collision or grasp was observed."}
    question = "Assess NEW swept-volume clearance from the actual current pose, not the historical fixed-TCP certificate. This high turn aims to expose ONE inward pad face from below its tips, not both centers simultaneously. The entire conservative finger sphere includes measured transient drift and recentering. Use both views to account for every relevant non-robot surface in its supplied XY box; do not certify hidden tops. Request named current depth samples h0,h1,h2 on the highest relevant visible surface or surfaces, using separate reliable interior pixels. Confirm the same patterned bowl remains upright supported. Assess the visible proximal hand/wrist sweep to the supplied target separately; the finger sphere does not bound the arm. Coverage concerns only this high turn, never descent. Do not require future face visibility."
    pre = api.review(question, context=context, fields=fields)
    valid = record(pre, "clearance_0", names)
    for retry in range(2):
        p = pre["parameters"]
        if p["bowl"] == "disturbed":
            return finish("needs_replan", "Fresh observations report a disturbed bowl.")
        if pre["status"] == "stop" or p["bowl"] != "same_upright_supported" or p["coverage"] != "complete_visible_height_bound" or p["proximal_turn"] != "visibly_clear" or pre["frame_id"] != s0["frame_id"]:
            return finish("blocked", "The newly proposed swept volume or proximal-hand turn lacks current visible clearance.")
        missing = [n for n in names if n not in valid]
        if not missing:
            break
        if retry == 1:
            return finish("blocked", "The current height bound still lacks valid named depths after one alternative-pixel review; partial evidence is saved.")
        pre = api.review("Replace only these failed named height measurements with DIFFERENT depth-valid interior pixels on the same identified highest relevant surfaces. Do not resample invisible surfaces or reuse placeholder pixels. Reconfirm the declared clearance fields; no motion has occurred.", context={"missing": missing, "saved": samples["clearance_0"], "turn": context}, fields=fields)
        valid.update(record(pre, "clearance_1", missing))
    if any(bool(np.any(np.abs(np.asarray(valid[n]["world_m"])[:2] - tcp[:2]) > envelope + 0.003)) for n in names):
        return finish("blocked", "A height sample is outside the assessed local column; the proposed bound is unresolved.")
    top = max(float(valid[n]["world_m"][2]) for n in names)
    margin = float(tcp[2]) - envelope - top - 0.005
    memo["clearance"] = {"frame_id": pre["frame_id"], "highest_measured_z_m": top, "available_margin_m": margin, "required_margin_m": 0.020, "scope": "New high-turn swept volume only; stationary scene and complete visible coverage required."}
    if margin < 0.020:
        return finish("blocked", "The newly measured swept-volume clearance fails the unchanged 20 mm margin and 5 mm height allowance.")
    questions = {}
    for axis in ["x", "y", "z", "rx", "ry", "rz"]:
        questions[axis] = {"type": "choice", "instructions": "For " + axis + ", read state.processed_features.axes." + axis + ".goal_relation. Select positive for increase, negative for decrease, hold for within_tolerance. Follow only this supplied observation or recentering target; do not infer clearance or object effects.", "criteria": {"negative": "Decrease this world coordinate or world rotation-vector component.", "hold": "No correction on this component within tolerance.", "positive": "Increase this world coordinate or world rotation-vector component."}}
    questions["gripper"] = {"type": "choice", "instructions": "Read state.processed_features.objective.gripper. This high observation maneuver requests keep exclusively; preserve the existing command.", "criteria": {"open": "Deliver an explicit open objective only.", "close": "Deliver an explicit close objective only.", "keep": "Preserve the current command as requested here."}}
    stop, stagnant = "", 0
    api.checkpoint("lift.turn_v3", memo)
    for i in range(cap):
        before = api.state()
        drift = float(np.linalg.norm(np.asarray(before["tcp_position_world_m"]) - tcp))
        if drift > guard + transient or radius(before) > base_radius + 0.001 or float(np.max(np.abs(np.asarray(before["gripper_qpos_m"]) - np.asarray(s0["gripper_qpos_m"])))) > 0.001:
            stop = "Measured pose or finger geometry exceeds the newly assessed swept envelope."
            break
        if before["budgets"]["jev_remaining"] < 1 or before["budgets"]["native_steps_remaining"] < 3:
            break
        recenter = drift > guard
        goalq = before["tcp_quaternion_xyzw"] if recenter else quat
        features = {"source": "Fresh RGB-D coverage and depths, current proprioception, and historical acknowledged displacement; no hidden sensing.", "mode": "translation_recenter_orientation_frozen" if recenter else "single_face_high_turn", "plan": plan, "clearance": memo["clearance"], "current_tcp_excursion_m": drift, "descent_authorized": False, "closure_authorized": False}
        r = api.control(tcp.tolist(), goalq, "keep", questions, features=features, translation_limit=0.003, rotation_limit=0.01 if recenter else 0.10, steps=3, position_tolerance=0.002, rotation_tolerance=0.025)
        after = api.state()
        dnew = float(np.linalg.norm(np.asarray(after["tcp_position_world_m"]) - tcp))
        jump = float(np.linalg.norm(np.asarray(after["tcp_position_world_m"]) - np.asarray(before["tcp_position_world_m"])))
        improvement = drift - dnew if recenter else angle(before["tcp_quaternion_xyzw"], quat) - angle(after["tcp_quaternion_xyzw"], quat)
        stagnant = stagnant + 1 if improvement < (0.0003 if recenter else 0.001) else 0
        memo.update({"calls": i + 1, "last_receipt": r, "last_acknowledged_state": after, "remaining_rotation_rad": angle(after["tcp_quaternion_xyzw"], quat), "tcp_excursion_m": dnew})
        memo["recent_updates"] = (memo["recent_updates"] + [{"frame_id": after["frame_id"], "recenter": recenter, "displacement_m": jump, "tcp_excursion_m": dnew, "rotation_remaining_rad": memo["remaining_rotation_rad"], "status": r["status"]}])[-8:]
        api.checkpoint("lift.turn_v3", memo)
        if r["choices"]["gripper"] != "keep" or after["last_gripper_command"] != "open":
            stop = "Unexpected gripper delivery; no automatic reversal is allowed."
        elif jump > transient or dnew > guard + transient or radius(after) > base_radius + 0.001 or float(np.max(np.abs(np.asarray(after["gripper_qpos_m"]) - np.asarray(s0["gripper_qpos_m"])))) > 0.001:
            stop = "Actual displacement or finger geometry exceeded a freshly assessed execution allowance."
        elif r["status"] == "stalled" or stagnant >= 2 or improvement < (-0.002 if recenter else -0.03):
            stop = "Stall, repeated inadequate progress, or reversed progress; do not repeat the maneuver blindly."
        if stop or (memo["remaining_rotation_rad"] <= 0.025 and dnew <= 0.002):
            break
    sf = api.state()
    memo["execution_stop"] = stop
    memo["remaining_rotation_rad"] = angle(sf["tcp_quaternion_xyzw"], quat)
    memo["observed_orientation_change_rad"] = angle(s0["tcp_quaternion_xyzw"], sf["tcp_quaternion_xyzw"])
    if sf["frame_id"] == s0["frame_id"]:
        return finish("blocked" if stop else "yield", stop or "No physical update occurred; no unchanged visibility review was repeated.")
    postfields = {"face": ["one_actual_inward_contact_face", "not_visible", "ambiguous"], "bowl": ["same_upright_supported", "disturbed", "unknown"], "hand": ["visibly_clear", "contact_or_collision", "unknown"]}
    post = api.review("Assess the ACTUAL changed pose, not the target. Identify ONE genuinely visible inward finger contact face, preferably the intended far finger. If identifiable, request m0,m1,m2,m3 at separated interior surface locations on that same face, spanning its small width and height. These are surface samples, NOT estimated face centers. Never use outer faces, silhouettes, tips, placeholder pixels, or an unseen opposing face. If not visible, return no pad measurements. Check the same bowl remains upright supported and the hand clear. An unavailable face is not a collision; explain whether the partial view is useful.", context={"state": sf, "plan": plan, "rotation_remaining_rad": memo["remaining_rotation_rad"], "execution_stop": stop}, fields=postfields)
    pads = record(post, "changed_view", ["m0", "m1", "m2", "m3"])
    memo["fresh_effect_review"] = {"frame_id": post["frame_id"], "parameters": post["parameters"]}
    p = post["parameters"]
    if p["bowl"] == "disturbed" or p["hand"] == "contact_or_collision":
        return finish("needs_replan", "Fresh changed-view evidence reports disturbance or contact; establish the actual scene before retrying.")
    if post["frame_id"] != sf["frame_id"] or p["bowl"] != "same_upright_supported" or p["hand"] != "visibly_clear":
        return finish("blocked", "Current bowl support/identity or hand separation is unresolved.")
    if p["face"] == "one_actual_inward_contact_face" and len(pads) >= 3:
        Rt = geo.rotation(sf["tcp_quaternion_xyzw"]).T
        local = np.asarray([(Rt @ (np.asarray(pads[n]["world_m"]) - np.asarray(sf["tcp_position_world_m"]))).tolist() for n in sorted(pads)])
        lo, hi = np.asarray(sf["own_geometry"]["finger_low_offset_tool_m"]), np.asarray(sf["own_geometry"]["finger_high_offset_tool_m"])
        spans = np.max(local, axis=0) - np.min(local, axis=0)
        mean_y = float(np.mean(local[:, 1]))
        consistent = bool(np.all(local >= lo - 0.003) and np.all(local <= hi + 0.003) and np.all((-sign) * local[:, 1] > 0.010))
        consistent = consistent and float(spans[0]) >= 0.004 and float(spans[2]) >= 0.004 and float(spans[1]) <= 0.003
        memo["single_face_measurement"] = {"frame_id": sf["frame_id"], "state": sf, "sample_names": sorted(pads), "points_tool_m": local.tolist(), "mean_tool_y_m": mean_y, "spans_tool_m": spans.tolist(), "per_sample_allowance_m": 0.003, "checks_passed": consistent, "scope": "One visually identified inner face patch only; no opposing face, aperture, center calibration, descent clearance or retention is inferred."}
        if not consistent:
            return finish("blocked", "Visible face samples fail side, own-finger bounds, spread or constant-tool-y consistency checks; measurements are preserved.")
    if stop or post["status"] == "stop":
        return finish("blocked", stop or "The changed-view observer requests stopping; see saved evidence.")
    if "single_face_measurement" in memo:
        return finish("yield", "Fresh changed-view depths establish one inward contact-face patch while the bowl remains supported. Preserve this numerical reference; the lift effect is not yet achieved.")
    if memo["remaining_rotation_rad"] > 0.025 and memo["observed_orientation_change_rad"] >= 0.15:
        return finish("yield", "The bounded turn made measured progress but is incomplete; no valid face patch is yet established. Resume only from the acknowledged pose and renewed clearance.")
    return finish("blocked", "The changed view did not establish a usable inward face patch. Saved visibility, depth failures and actual pose specify the remaining sensing gap.")

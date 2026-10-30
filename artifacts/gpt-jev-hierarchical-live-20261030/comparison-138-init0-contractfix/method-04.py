def main(api):
    start = api.state()
    old = api.recall("lift.view_recovery")["value"]
    samples = {}
    memo = {"stage": "lift", "phase": "single_face_observation_repair", "entry_state": start, "calls": 0, "retention_established": False, "updates": []}
    keys = ["observe.result", "lift.alignment", "lift.measurements", "lift.view_recovery", "lift.view_samples", "lift.turn_v4", "lift.face_v4"]
    def finish(status, reason):
        memo["end_state"] = api.state()
        memo["new_native_steps"] = memo["end_state"]["native_steps"] - start["native_steps"]
        api.checkpoint("lift.turn_v4", memo)
        api.checkpoint("lift.face_v4", samples)
        return {"stage_status": status, "reason": reason, "evidence": memo, "handoff": {"checkpoint_keys": keys, "frames": "World meters; xyzw tool-to-world orientations. Each sample retains its camera and acquisition frame.", "provenance": "lift.turn_v4 records the actual entry, historical measured displacement, newly reviewed envelope, target, acknowledged execution and any measured single-face tool coordinates. lift.face_v4 records current review parameters, valid partial depths and errors. Earlier checkpoints remain historical and unchanged.", "scope": "High observation turn only. No descent or gripper change was requested. Retention and lift are NOT established. Continue from the saved actual state, not a commanded pose.", "dependencies": "The observed face belongs to the recorded positive- or negative-tool-y finger at the saved opening. It is not an opposing-face measurement, aperture certificate, pad center or descent clearance. Revalidate opening, identity and geometry before propagation. Reacquire image landmarks after movement. Bowl and cabinet references require identity and stationarity checks.", "remaining_effect": "Acquire the bowl only after resolving approach/contact geometry. Lift-stage completion still requires fresh bowl-hand co-motion, visible counter separation, orientation and retained extent. No later-stage control code is supplied."}, "completion_proposed": False}
    def angle(a, b):
        c = float((np.trace(geo.rotation(a) @ geo.rotation(b).T) - 1.0) / 2.0)
        return math.acos(max(-1.0, min(1.0, c)))
    def radius(s):
        lo, hi = s["own_geometry"]["finger_low_offset_tool_m"], s["own_geometry"]["finger_high_offset_tool_m"]
        return max(float(np.linalg.norm([x, y, z])) for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]])
    def observe(label, question, context, fields, names):
        contract = "HARD MEASUREMENT CONTRACT: submit regions=[]; request ZERO regions/clouds. Request only these named current depth points when genuinely visible: " + str(names) + ". Do not add other measurements. Both images remain available for qualitative coverage, identity and visibility assessment. If this limited evidence cannot establish coverage, return unknown rather than adding regions or claiming hidden clearance. "
        try:
            r = api.review(contract + question, context=context, fields=fields)
        except Exception as exc:
            samples[label] = {"error": str(exc)[:1200], "state": api.state()}
            api.checkpoint("lift.face_v4", samples)
            return None, {}
        bad = [e["name"] for e in r["measurement_errors"]]
        valid = {}
        for n in names:
            if n in r["points"] and n not in bad:
                p = r["points"][n]
                a = np.asarray(p["world_m"], dtype=float)
                if p["frame_id"] == r["frame_id"] and a.shape == (3,) and bool(np.all(np.isfinite(a))):
                    valid[n] = p
        samples[label] = {"frame_id": r["frame_id"], "parameters": r["parameters"], "valid": valid, "measurement_errors": r["measurement_errors"], "explanation": r["explanation"][:1000]}
        api.checkpoint("lift.face_v4", samples)
        return r, valid
    if start["frame_id"] != old["end_state"]["frame_id"] or start["native_steps"] != old["end_state"]["native_steps"]:
        return finish("blocked", "Intervening execution does not match the last acknowledged frame-72 recovery; reconcile it before motion.")
    if start["last_gripper_command"] != "open" or old["retention_established"]:
        return finish("blocked", "Expected open, unretained entry is not established; never reopen automatically.")
    cap = min(23, int(start["budgets"]["jev_remaining"]), int(start["budgets"]["native_steps_remaining"]) // 3)
    if cap < 1 or start["budgets"]["gpt_remaining"] < 3:
        return finish("yield", "Insufficient budget for a bounded observation maneuver, a possible depth replacement and its fresh effect review.")
    tcp = np.asarray(start["tcp_position_world_m"], dtype=float)
    cam = api.camera("agentview")
    if cam["frame_id"] != start["frame_id"]:
        return finish("blocked", "External camera calibration is not current.")
    view = np.asarray(cam["camera_to_world_opencv"], dtype=float)[:3, 3] - tcp
    view = view / np.linalg.norm(view)
    R = geo.rotation(start["tcp_quaternion_xyzw"])
    yaw0 = math.atan2(float(view[1]), float(view[0])) - math.atan2(float(R[1, 1]), float(R[0, 1]))
    alternatives = [(yaw0 + k + math.pi) % (2.0 * math.pi) - math.pi for k in [0.0, math.pi]]
    yaw = min(alternatives, key=abs)
    qside = api.compose(start["tcp_quaternion_xyzw"], [0.0, 0.0, yaw])
    Rs = geo.rotation(qside)
    vy, vz = float(np.dot(Rs[:, 1], view)), float(np.dot(Rs[:, 2], view))
    sign = 1.0 if vy >= 0.0 else -1.0
    roll = (math.atan2(vz, vy) - math.atan2(0.5, sign * math.sqrt(0.75)) + math.pi) % (2.0 * math.pi) - math.pi
    quat = api.compose(qside, (roll * Rs[:, 0]).tolist())
    if abs(roll) > 1.35 or angle(start["tcp_quaternion_xyzw"], quat) > 1.45:
        return finish("blocked", "The computed one-face view exceeds this local high-turn scope.")
    prior_drift = float(np.linalg.norm(np.asarray(old["last_acknowledged_state"]["tcp_position_world_m"]) - np.asarray(old["start_state"]["tcp_position_world_m"])))
    guard = float(old["view_plan"]["tcp_drift_bound_m"])
    transient, base = max(0.006, 2.0 * prior_drift), radius(start)
    envelope = base + 0.001 + guard + transient
    plan = {"anchor_tcp_world_m": tcp.tolist(), "target_quaternion_xyzw": quat, "yaw_rad": yaw, "roll_rad": roll, "preferred_finger_tool_y_sign": -sign, "camera_direction_world": view.tolist(), "previous_three_step_displacement_m": prior_drift, "recenter_trigger_m": guard, "per_update_displacement_allowance_m": transient, "maximum_tcp_excursion_m": guard + transient, "finger_growth_allowance_m": 0.001, "finger_sphere_radius_m": envelope, "height_allowance_m": 0.005, "required_margin_m": 0.020, "basis": "Twice the measured previous displacement is an engineering transient allowance, not a certified dynamics bound. Freshly review this entire envelope. The original 4 mm limit remains the stop-rotation/recenter trigger."}
    memo["plan"] = plan
    api.checkpoint("lift.turn_v4", memo)
    fields = {"bowl": ["same_upright_supported", "disturbed", "unknown"], "coverage": ["complete_visible_height_bound", "obstructed", "unknown"], "proximal_turn": ["visibly_clear", "concern", "unknown"]}
    context = {"plan": plan, "state": start, "xy_min_m": (tcp[:2] - envelope).tolist(), "xy_max_m": (tcp[:2] + envelope).tolist(), "prior_execution": "The partial turn ended at frame 72. The next attempted method failed its review schema before any physical action. Its target was never reached."}
    question = "Assess ONLY this newly expanded high-turn envelope from the actual current pose. Account visually for all non-robot surfaces intersecting its XY box, including bowl, package, bottle, plate and any cabinet/rack/hotplate portion that could intersect it; do not sample clearly lateral objects unnecessarily. complete_visible_height_bound means no relevant top is hidden and h0,h1,h2 sample the highest relevant visible surface elevations, not arbitrary low surfaces. Request h0,h1,h2 at distinct reliable interior depth pixels on those highest surfaces. Assess the visible proximal hand/wrist sweep to the supplied target separately: the finger sphere does not bound the arm. Unknown sweep or top coverage must be reported unknown. Confirm the same patterned bowl remains upright supported. This is not descent clearance and does not require either pad to be visible yet."
    heights = {}
    for attempt in range(2):
        missing = [n for n in ["h0", "h1", "h2"] if n not in heights]
        r, valid = observe("clearance_" + str(attempt), question, context, fields, missing)
        if r is None:
            return finish("blocked", "The restricted point-only clearance review failed; its exact error is saved. No motion was requested.")
        p = r["parameters"]
        if p["bowl"] == "disturbed":
            return finish("needs_replan", "Fresh evidence reports that the bowl is disturbed.")
        if r["status"] == "stop" or r["frame_id"] != start["frame_id"] or p["bowl"] != "same_upright_supported" or p["coverage"] != "complete_visible_height_bound" or p["proximal_turn"] != "visibly_clear":
            return finish("blocked", "Current visible top coverage, bowl state or proximal-hand sweep is unresolved; zero regions were requested.")
        heights.update(valid)
        if len(heights) == 3:
            break
        context["saved_same_frame_heights"] = heights
        context["measurement_errors"] = r["measurement_errors"]
        question = "No motion occurred. Replace ONLY the missing height names with DIFFERENT depth-valid interior pixels on the same identified highest relevant surfaces. Reconfirm the declared coverage fields for the same envelope. Do not repeat failed pixels, substitute a lower surface, or add regions."
    if len(heights) != 3:
        return finish("blocked", "Highest-surface depths remain incomplete after one different-pixel replacement; valid partial measurements are saved.")
    if any(bool(np.any(np.abs(np.asarray(p["world_m"])[:2] - tcp[:2]) > envelope + 0.003)) for p in heights.values()):
        return finish("blocked", "A height point is outside the reviewed local column; no height certificate is inferred.")
    top = max(float(p["world_m"][2]) for p in heights.values())
    margin = float(tcp[2]) - envelope - top - 0.005
    memo["clearance"] = {"frame_id": start["frame_id"], "highest_sample_z_m": top, "available_margin_m": margin, "required_margin_m": 0.020, "scope": "High-turn envelope only; visible complete coverage and stationary scene required."}
    if margin < 0.020:
        return finish("blocked", "The fresh height bound fails the unchanged 20 mm clearance margin plus 5 mm measurement allowance.")
    questions = {}
    for axis in ["x", "y", "z", "rx", "ry", "rz"]:
        questions[axis] = {"type": "choice", "instructions": "For " + axis + ", read state.processed_features.axes." + axis + ".goal_relation: increase selects positive, decrease selects negative, within_tolerance selects hold. Follow only the provided observation or recentering target. Do not infer clearance or object effects.", "criteria": {"negative": "Decrease this world coordinate or world rotation-vector component.", "hold": "Make no correction on this component within tolerance.", "positive": "Increase this world coordinate or world rotation-vector component."}}
    questions["gripper"] = {"type": "choice", "instructions": "Read state.processed_features.objective.gripper. This observation maneuver requests keep only, preserving the existing command.", "criteria": {"open": "Deliver an explicit open objective only.", "close": "Deliver an explicit close objective only.", "keep": "Preserve the existing command as requested here."}}
    stop, stagnant = "", 0
    for i in range(cap):
        before = api.state()
        drift = float(np.linalg.norm(np.asarray(before["tcp_position_world_m"]) - tcp))
        if drift > guard + transient or radius(before) > base + 0.001 or float(np.max(np.abs(np.asarray(before["gripper_qpos_m"]) - np.asarray(start["gripper_qpos_m"])))) > 0.001:
            stop = "Measured hand geometry or excursion exceeds the freshly assessed envelope."
            break
        if before["budgets"]["jev_remaining"] < 1 or before["budgets"]["native_steps_remaining"] < 3:
            break
        recenter = drift > guard
        goalq = before["tcp_quaternion_xyzw"] if recenter else quat
        features = {"source": "Current proprioception, fresh RGB-D top samples and visual coverage; historical acknowledged displacement.", "mode": "recenter_with_frozen_orientation" if recenter else "single_face_high_turn", "plan": plan, "clearance": memo["clearance"], "current_tcp_excursion_m": drift, "descent_authorized": False, "closure_authorized": False}
        receipt = api.control(tcp.tolist(), goalq, "keep", questions, features=features, translation_limit=0.003, rotation_limit=0.01 if recenter else 0.10, steps=3, position_tolerance=0.002, rotation_tolerance=0.025)
        after = api.state()
        excursion = float(np.linalg.norm(np.asarray(after["tcp_position_world_m"]) - tcp))
        jump = float(np.linalg.norm(np.asarray(after["tcp_position_world_m"]) - np.asarray(before["tcp_position_world_m"])))
        remaining = angle(after["tcp_quaternion_xyzw"], quat)
        progress = drift - excursion if recenter else angle(before["tcp_quaternion_xyzw"], quat) - remaining
        stagnant = stagnant + 1 if progress < (0.0003 if recenter else 0.001) else 0
        memo.update({"calls": i + 1, "last_receipt": receipt, "last_acknowledged_state": after, "remaining_rotation_rad": remaining, "tcp_excursion_m": excursion})
        memo["updates"] = (memo["updates"] + [{"frame_id": after["frame_id"], "recenter": recenter, "displacement_m": jump, "excursion_m": excursion, "rotation_remaining_rad": remaining, "status": receipt["status"]}])[-8:]
        api.checkpoint("lift.turn_v4", memo)
        if receipt["choices"]["gripper"] != "keep" or after["last_gripper_command"] != "open":
            stop = "Unexpected gripper delivery; do not reverse it automatically."
        elif jump > transient or excursion > guard + transient or radius(after) > base + 0.001 or float(np.max(np.abs(np.asarray(after["gripper_qpos_m"]) - np.asarray(start["gripper_qpos_m"])))) > 0.001:
            stop = "Actual motion or finger geometry exceeded a freshly assessed execution allowance."
        elif receipt["status"] == "stalled" or stagnant >= 2 or progress < (-0.002 if recenter else -0.03):
            stop = "Stalled, repeatedly inadequate or materially reversed progress; no blind retry."
        if stop or (remaining <= 0.025 and excursion <= 0.002):
            break
    end = api.state()
    memo["execution_stop"] = stop
    memo["remaining_rotation_rad"] = angle(end["tcp_quaternion_xyzw"], quat)
    memo["observed_rotation_rad"] = angle(start["tcp_quaternion_xyzw"], end["tcp_quaternion_xyzw"])
    if end["frame_id"] == start["frame_id"]:
        return finish("blocked" if stop else "yield", stop or "No physical update occurred; no unchanged pad-visibility review was repeated.")
    postfields = {"face": ["one_actual_inward_contact_face", "not_visible", "ambiguous"], "bowl": ["same_upright_supported", "disturbed", "unknown"], "hand": ["visibly_clear", "contact_or_collision", "unknown"]}
    postcontext = {"state": end, "plan": plan, "execution_stop": stop, "remaining_rotation_rad": memo["remaining_rotation_rad"]}
    postquestion = "Assess the ACTUAL changed view, not target attainment. Identify ONE actual inward finger contact face, preferably the intended far finger; either finger is acceptable if unambiguous. Request m0,m1,m2,m3 at separated interior surface locations spanning the width and height of that SAME face. They are surface samples, NOT estimated centers. Never sample outer faces, tips, silhouettes, hidden faces or placeholder pixels. If no face is identifiable, return no face points. Confirm the same bowl remains upright supported and the hand clear of external objects."
    pads = {}
    for attempt in range(2):
        names = [n for n in ["m0", "m1", "m2", "m3"] if n not in pads]
        post, valid = observe("face_" + str(attempt), postquestion, postcontext, postfields, names)
        if post is None:
            return finish("blocked", "The changed-view point-only review failed; acknowledged physical progress and the exact error are saved.")
        p = post["parameters"]
        memo["fresh_effect_review"] = {"frame_id": post["frame_id"], "parameters": p}
        if p["bowl"] == "disturbed" or p["hand"] == "contact_or_collision":
            return finish("needs_replan", "Changed-view evidence reports disturbance or contact; establish the actual scene before another maneuver.")
        if post["status"] == "stop" or post["frame_id"] != end["frame_id"] or p["bowl"] != "same_upright_supported" or p["hand"] != "visibly_clear":
            return finish("blocked", "Current bowl identity/support or hand separation is unresolved.")
        if p["face"] != "one_actual_inward_contact_face":
            break
        pads.update(valid)
        if len(pads) >= 3 or attempt == 1 or api.state()["budgets"]["gpt_remaining"] < 1:
            break
        postcontext["saved_same_face_points"] = pads
        postcontext["measurement_errors"] = post["measurement_errors"]
        postquestion = "The preceding review identified a visible inward contact face but lacked valid depths. No motion occurred. Replace ONLY missing names with DIFFERENT depth-valid interior pixels on that same physical face; do not mix fingers or reuse failed pixels. Reconfirm all declared fields. Request no regions."
    if p["face"] == "one_actual_inward_contact_face" and len(pads) >= 3:
        T = np.eye(4)
        T[:3, :3] = geo.rotation(end["tcp_quaternion_xyzw"]).T
        T[:3, 3] = -T[:3, :3] @ np.asarray(end["tcp_position_world_m"])
        local = geo.transform([pads[n]["world_m"] for n in sorted(pads)], T)
        lo, hi = np.asarray(end["own_geometry"]["finger_low_offset_tool_m"]), np.asarray(end["own_geometry"]["finger_high_offset_tool_m"])
        spans, mean_y = np.max(local, axis=0) - np.min(local, axis=0), float(np.mean(local[:, 1]))
        side = 1.0 if mean_y >= 0.0 else -1.0
        consistent = bool(np.all(local >= lo - 0.003) and np.all(local <= hi + 0.003) and np.all(side * local[:, 1] > 0.010))
        consistent = consistent and float(spans[0]) >= 0.004 and float(spans[2]) >= 0.004 and float(spans[1]) <= 0.003
        memo["single_face"] = {"frame_id": end["frame_id"], "finger_tool_y_sign": side, "sample_names": sorted(pads), "points_tool_m": local.tolist(), "mean_tool_y_m": mean_y, "spans_tool_m": spans.tolist(), "per_sample_allowance_m": 0.003, "gripper_qpos_m": end["gripper_qpos_m"], "checks_passed": consistent, "scope": "One identified inner face patch, not an aperture, center or retention certificate."}
        if not consistent:
            return finish("blocked", "Face samples fail same-side, own-finger bounds, width/height spread or constant-tool-y checks; partial evidence is preserved.")
    if stop:
        return finish("blocked", stop)
    if "single_face" in memo:
        return finish("yield", "A changed view establishes one usable inward contact-face patch; the bowl remains supported and the lift effect is still unachieved.")
    if memo["remaining_rotation_rad"] > 0.025 and memo["observed_rotation_rad"] >= 0.15:
        return finish("yield", "The bounded turn made measured progress but remains incomplete. Resume from actual execution only after renewing clearance, not from its target.")
    return finish("blocked", "No usable inner-face patch was obtained in the changed view; saved visibility, depth errors and actual pose specify the sensing gap.")

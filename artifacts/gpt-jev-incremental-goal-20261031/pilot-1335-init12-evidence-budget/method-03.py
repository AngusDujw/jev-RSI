def main(api):
    keys = ["pick_reference"]; logs = []; leases = []; handle = None
    def save(key, value):
        api.checkpoint(key, value)
        if key not in keys: keys.append(key)
    def finish(status, reason, evidence):
        s = api.state()
        handoff = {"stage": "retain", "checkpoint_keys": keys[:], "frames": "World meters, tool quaternion xyzw; physical landmark IDs persist across views.", "actual_state": s, "assumptions": "No opening or renewed closure was commanded. Bowl fit and transfer clearance are NOT established. Revalidate affected references before another action.", "measurement_provenance": "retain_reference stores fresh admission measurements and historical dimension provenance. retain_measurements stores consumed point receipts and review interpretations. retain_progress stores actual whole-lease motion. retain_result stores the effect or exact gap."}
        result = {"stage_status": status, "reason": reason, "evidence": evidence, "handoff": handoff, "completion_proposed": False}
        save("retain_result", {"stage_status": status, "reason": reason, "evidence": evidence, "frame_id": s["frame_id"]})
        result["handoff"]["checkpoint_keys"] = keys[:]
        return result
    def fail(name, action, operands, status="blocked"):
        d = {"gate": name, "prevented_action": action, "operands": operands, "frame_id": api.state()["frame_id"], "provenance": "Sensor geometry and runtime budgets are measured; pixel/noise allowances, drift limits and effect tolerances are operational heuristics, not external constraints."}
        save("retain_gate", d)
        return finish(status, name, d)
    questions = {}
    for axis in ["x", "y", "z", "rx", "ry", "rz"]:
        questions[axis] = {"type": "choice", "instructions": "For the " + axis + " world axis, read its trusted goal_relation and pose residual. Follow increase/decrease/within_tolerance. This is an admitted upward-only local test, not permission to find objects or change goals.", "criteria": {"negative": "Decrease this world coordinate or world rotation-vector component when its relation is decrease.", "hold": "No component correction when its relation is within_tolerance.", "positive": "Increase this world coordinate or world rotation-vector component when its relation is increase."}}
    questions["gripper"] = {"type": "choice", "instructions": "Read objective.gripper. Preserve the already executed grasp throughout this test; do not infer retention from closure.", "criteria": {"open": "Deliver open only for an explicit open objective.", "close": "Deliver close only for an explicit close objective.", "keep": "Preserve the current gripper command for the keep objective."}}
    fields = {"identity": ["correct", "wrong", "unknown"], "box_model": ["unchanged", "changed", "unknown"], "corridor": ["clear", "obstructed", "unknown"], "slip": ["observed", "none", "unknown"], "table_same": ["yes", "no", "unknown"], "valid_landmarks": {"type": "array", "items": {"type": "boolean"}, "minItems": 4, "maxItems": 4}, "labels": {"type": "array", "items": {"type": "string", "maxLength": 180}, "minItems": 4, "maxItems": 4}, "patch_camera": ["robot0_eye_in_hand", "agentview", "none"], "patch_polygon": {"type": "array", "items": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}, "maxItems": 16}, "hazards": {"type": "string", "maxLength": 700}}
    history = api.recall("pick_reference")["value"]; s0 = api.state()
    old = history.get("post_closure_contact", {})
    if old.get("frame_id") != s0["frame_id"]:
        return fail("Current support-normal reference unavailable", "Admit vertical departure", {"reference_frame": old.get("frame_id"), "current_frame": s0["frame_id"]})
    def read(phase, context):
        request = "Review only this retained-lift test. Identify the cream cheese package, not fingers or background. Request named depth points p0,p1,p2,p3 at four independently identifiable printed landmarks on its exposed planar top face, spread in two directions, away from silhouettes. Initially name their physical identities in labels; subsequently preserve those exact IDs and strings from context, not screen positions. Mark unavailable or ambiguous IDs false; never substitute a different landmark. Request t0 on the actual nearby tabletop beside the package, away from rims and shadows. table_same concerns that same stationary support. box_model asks whether the same undamaged rectangular package supports reuse of historical dimensions, not whether it is held. Assess corridor ONLY for the remaining straight world +z departure up to the supplied total height, with fixed orientation and 3 mm lateral drift, for package and fingers/wrist. Do not infer hidden clearance. Report visible slip, obstruction and uncertainty separately. Initial phase: optionally supply a 3..16-vertex textured polygon strictly inside this same exposed printed face for tracking; otherwise empty polygon and none. Later: polygon is unnecessary. Effect reviews must identify the current package independently; robot movement is not package retention. "
        r = api.review(request + " Phase: " + phase, context=context, fields=fields)
        p = r["parameters"]; bad = [x["name"] for x in r["measurement_errors"]]; pts = {}; receipts = {}; units = {}
        cameras = {}
        for name in ["p0", "p1", "p2", "p3", "t0"]:
            allowed = p["table_same"] == "yes" if name == "t0" else p["valid_landmarks"][int(name[1])] and p["identity"] == "correct"
            if allowed and name in r["points"] and name not in bad and r["points"][name]["frame_id"] == r["frame_id"]:
                v = r["points"][name]; cam = v["camera"]
                if cam not in cameras: cameras[cam] = api.camera(cam)
                k = cameras[cam]["K"]; pixel = 2.0 * v["depth_m"] / min(k[0][0], k[1][1])
                pts[name] = v["world_m"]; units[name] = 0.00075 + pixel; receipts[name] = v
        ob = {"s": api.state(), "p": pts, "u": units, "parameters": p, "frame_id": r["frame_id"], "tr": None}
        logs.append({"phase": phase, "frame_id": r["frame_id"], "parameters": p, "measurements": receipts, "measurement_errors": r["measurement_errors"]})
        save("retain_measurements", {"observations": logs[-3:]})
        ob["stop"] = r["status"] == "stop"
        return ob
    def tracking():
        if handle is None: return None
        t = api.track_update(handle)
        if t["status"] != "tracked": return {"ok": False, "frame_id": t["frame_id"], "reason": t.get("reason", "unknown")}
        u = max(0.0005, t["uncertainty_floor_m"]) + 2.0 * t["rms_m"]
        spread = sorted(np.asarray(t["inlier_spread_m"]).reshape(-1).tolist())
        ok = t["inliers"] >= 12 and t["inliers"] / max(1, t["matches"]) >= 0.65 and t["rms_m"] <= 0.002 and len(spread) >= 2 and spread[-2] > 3.0 * u
        return {"ok": bool(ok), "frame_id": t["frame_id"], "T": t["transform_initial_world_to_current_world"], "a": t["reference_inlier_world_m"], "b": t["current_inlier_world_m"], "u": u, "rms_m": t["rms_m"], "spread_m": spread, "inliers": t["inliers"]}
    def pairs(a, b):
        names = [n for n in ["p0", "p1", "p2", "p3"] if n in a["p"] and n in b["p"] and a["parameters"]["labels"][int(n[1])] == b["parameters"]["labels"][int(n[1])]]
        if len(names) >= 3:
            aa = np.array([a["p"][n] for n in names]); bb = np.array([b["p"][n] for n in names])
            ua = max(a["u"][n] for n in names); ub = max(b["u"][n] for n in names)
            try:
                pa = geo.plane(aa); pb = geo.plane(bb)
                ua += 2 * pa["rms_m"]; ub += 2 * pb["rms_m"]
                if min(pa["in_plane_spread_m"]) > 2 * ua and min(pb["in_plane_spread_m"]) > 2 * ub:
                    return aa, bb, ua, ub, "identified_depth_landmarks"
            except Exception:
                pass
        ta = a["tr"]; tb = b["tr"]
        if ta and tb and ta["ok"] and tb["ok"]:
            return geo.transform(np.array(tb["a"]), np.array(ta["T"])), np.array(tb["b"]), ta["u"], tb["u"], "quality_checked_same_surface_tracker"
        return None
    def effect(a, b):
        pair = pairs(a, b)
        if pair is None: return {"valid": False, "reason": "Neither corresponding landmarks nor adequate same-patch registration is available.", "frames": [a["frame_id"], b["frame_id"]]}
        aa, bb, ua, ub, method = pair
        err = float(geo.attachment_error(aa, bb, a["s"], b["s"]))
        hand = float(np.dot(np.array(b["s"]["tcp_position_world_m"]) - np.array(a["s"]["tcp_position_world_m"]), normal))
        moved = float(np.mean((bb - aa) @ normal)); tol = ua + ub + 0.001
        minimum = max(0.008, 4 * tol)
        margins = {"excitation_m": hand - minimum, "attachment_m": tol - err, "nonresponse_exclusion_m": moved - ua - ub - 0.5 * hand}
        return {"valid": True, "passed": bool(min(margins.values()) >= 0), "method": method, "frames": [a["frame_id"], b["frame_id"]], "hand_up_m": hand, "object_up_m": moved, "attachment_error_m": err, "uncertainty_before_m": ua, "uncertainty_after_m": ub, "slip_allowance_m": 0.001, "attachment_limit_m": tol, "minimum_hand_motion_m": minimum, "margins": margins}
    context = {"initial_frame": s0["frame_id"], "maximum_total_world_z_departure_m": 0.04, "historical_dimensions_m": [history["long_side_m"], history["short_side_m"], history["top_to_table_height_m"]], "executed_state": "Already closed; never reopen or repeat closure.", "old_gate_reassessment": "3 mm overlap was a precontact heuristic, not a retention sensor. 4 mm table gap was a descent heuristic. This action is upward departure, with measured positive finger clearance and independent co-motion tests."}
    base = read("admission", context)
    if base["stop"]: return finish("abort", "Observation review requested stop", {"frame_id": base["frame_id"]})
    if base["parameters"]["identity"] != "correct" or base["parameters"]["corridor"] != "clear" or base["parameters"]["box_model"] == "changed" or "t0" not in base["p"]:
        return fail("Departure identity, support or corridor unresolved", "Begin upward differential test", {"parameters": base["parameters"], "available_points": list(base["p"]), "frame_id": base["frame_id"]})
    table = np.array(old["table_plane"]["coefficients"], dtype=float); normal = table[:3]
    table[3] = -float(np.dot(normal, base["p"]["t0"]))
    utable = max(base["u"]["t0"], old["vertical_allowance_m"])
    q = s0["tcp_quaternion_xyzw"]; rot0 = geo.rotation(q); own = s0["own_geometry"]
    corners = np.array([[x, y, z] for x in [own["finger_low_offset_tool_m"][0], own["finger_high_offset_tool_m"][0]] for y in [own["finger_low_offset_tool_m"][1], own["finger_high_offset_tool_m"][1]] for z in [own["finger_low_offset_tool_m"][2], own["finger_high_offset_tool_m"][2]]])
    pose = np.eye(4); pose[:3, :3] = rot0; pose[:3, 3] = s0["tcp_position_world_m"]
    clearance = float(np.min(geo.transform(corners, pose) @ normal + table[3]))
    radius = float(np.max(np.linalg.norm(corners, axis=1))); sweep = radius * 0.025
    reserve = utable + 0.002 + sweep + 0.003 * float(np.linalg.norm(normal[:2]))
    admission = {"frame_id": base["frame_id"], "finger_clearance_m": clearance, "support_uncertainty_m": utable, "reverse_correction_allowance_m": 0.002, "rotation_sweep_m": sweep, "lateral_slope_allowance_m": reserve - utable - 0.002 - sweep, "threshold_m": reserve, "residual_margin_m": clearance - reserve, "table_normal_z": float(normal[2]), "normal_z_minimum": 0.98, "normal_margin": float(normal[2]) - 0.98, "action": "At most 40 mm upward, fixed orientation, keep gripper", "rationale": "Positive conservative finger clearance plus positive departure direction; no required pre-existing retention or renewed closure overlap."}
    if clearance <= reserve or normal[2] < 0.98: return fail("Direction-sensitive departure clearance", "Begin upward test", admission)
    polygon = base["parameters"]["patch_polygon"]; camera = base["parameters"]["patch_camera"]; tracker_info = {"status": "not_requested"}
    if camera != "none" and len(polygon) >= 3:
        try:
            init = api.track_init(camera, polygon); handle = init["handle"]
            tracker_info = {"handle": handle, "camera": camera, "polygon": polygon, "reference_frame_id": init["frame_id"], "identity": "Printed planar top of this cream cheese package"}
            base["tr"] = tracking()
        except Exception as e:
            tracker_info = {"status": "unavailable", "reason": str(e)[:400]}
    if pairs(base, base) is None:
        return fail("Observable differential reference unavailable", "Begin upward test", {"tracker": tracker_info, "points": base["p"], "uncertainties_m": base["u"], "frames": [base["frame_id"]]}, "needs_replan")
    save("retain_reference", {"state": s0, "point_world_m": base["p"], "point_uncertainties_m": base["u"], "labels": base["parameters"]["labels"], "table_plane": table.tolist(), "admission": admission, "tracker": tracker_info, "dimensions_source": "pick_reference: historical initial box dimensions, not newly measured perimeter", "dimensions_m": context["historical_dimensions_m"]})
    previous = base; effects = []; used = 0
    for phase in range(2):
        start = api.state(); target = np.array(start["tcp_position_world_m"]); target[2] += 0.020
        target[2] = min(target[2], s0["tcp_position_world_m"][2] + 0.040)
        for lease in range(2):
            before = api.state(); budgets = before["budgets"]
            calls = min(12, 48 - used, budgets["jev_remaining"] - 64, (budgets["native_steps_remaining"] - 192) // 3)
            if calls < 1: return fail("Retain control allocation exhausted", "Continue justified upward test", {"budgets": budgets, "used_calls": used, "reserve_jev": 64, "reserve_steps": 192}, "needs_replan")
            receipt = api.drive(target.tolist(), q, "keep", questions, features={"source": "Fresh admission depth and review; current pose supplied by host", "phase": phase + 1, "departure_gate": admission, "objective": "Upward differential retention test; no lateral transport, reopening or repeated closure"}, max_calls=int(calls), tool_point="tcp", translation_limit=0.02, rotation_limit=0.05, steps=3, position_tolerance=0.002, rotation_tolerance=0.02)
            after = api.state(); used += receipt["lease_calls"]
            delta = np.array(after["tcp_position_world_m"]) - np.array(before["tcp_position_world_m"])
            total = np.array(after["tcp_position_world_m"]) - np.array(s0["tcp_position_world_m"])
            angle = float(np.arccos(np.clip((np.trace(geo.rotation(after["tcp_quaternion_xyzw"]) @ rot0.T) - 1) / 2, -1, 1)))
            progress = float(np.linalg.norm(np.array(before["tcp_position_world_m"]) - target) - np.linalg.norm(np.array(after["tcp_position_world_m"]) - target))
            entry = {"frames": [before["frame_id"], after["frame_id"]], "status": receipt["status"], "calls": receipt["lease_calls"], "delta_world_m": delta.tolist(), "target_progress_m": progress, "lateral_drift_m": float(np.linalg.norm(total[:2])), "rotation_drift_rad": angle, "actual_state": after}
            leases.append(entry); save("retain_progress", {"used_calls": used, "leases": leases[-4:], "effects": effects})
            if receipt["choices"]["gripper"] != "keep" or receipt["status"] == "stalled" or delta[2] < -0.002 or np.linalg.norm(total[:2]) > 0.003 or angle > 0.025:
                return fail("Departure command, stall or drift gate", "Continue upward test", {"lease": entry, "choices": receipt["choices"], "limits": {"minimum_delta_z_m": -0.002, "lateral_m": 0.003, "rotation_rad": 0.025}}, "needs_replan")
            live = tracking()
            if live and live["ok"]:
                probe = {"s": after, "frame_id": after["frame_id"], "p": {}, "u": {}, "parameters": previous["parameters"], "tr": live}
                observed = effect(previous, probe)
                if observed["valid"] and observed["hand_up_m"] >= observed["minimum_hand_motion_m"] and not observed["passed"]:
                    return fail("Measured package nonresponse or slip", "Continue upward test", observed, "needs_replan")
            if receipt["status"] == "reached": break
            if receipt["status"] != "lease_exhausted" or progress <= 0.0005:
                return fail("Whole-lease progress inadequate", "Renew feedback lease", {"lease": entry, "progress_threshold_m": 0.0005, "progress_margin_m": progress - 0.0005}, "needs_replan")
            if live is None or not live["ok"]: break
        context.update({"labels": base["parameters"]["labels"], "before_state": previous["s"], "actual_state": api.state(), "remaining_upward_m": max(0.0, s0["tcp_position_world_m"][2] + 0.040 - api.state()["tcp_position_world_m"][2]), "previous_measurements": previous["p"], "tracker_available": bool(handle is not None)})
        now = read("first effect and next upward admission" if phase == 0 else "final retained-lift effect", context); now["tr"] = tracking()
        if now["stop"]: return finish("abort", "Observation review requested stop", {"frame_id": now["frame_id"]})
        if now["parameters"]["identity"] != "correct" or now["parameters"]["slip"] == "observed" or now["parameters"]["box_model"] == "changed":
            return fail("Package identity, deformation or observed slip", "Accept retention or continue lift", {"parameters": now["parameters"], "frame_id": now["frame_id"]}, "needs_replan")
        measured = effect(previous, now); effects.append(measured)
        if not measured.get("passed", False): return fail("Independent differential retention test", "Accept this lift interval", measured, "needs_replan")
        if "t0" in now["p"]:
            table_error = abs(float(np.dot(normal, now["p"]["t0"]) + table[3])); table_limit = utable + now["u"]["t0"]
            if table_error > table_limit:
                return fail("Support reference changed", "Use tabletop separation or continue lift", {"error_m": table_error, "limit_m": table_limit, "margin_m": table_limit - table_error, "frames": [base["frame_id"], now["frame_id"]]}, "needs_replan")
        if phase == 0 and now["parameters"]["corridor"] != "clear":
            return fail("Second upward corridor unresolved", "Second bounded lift interval", {"parameters": now["parameters"], "accepted_first_effect": measured}, "needs_replan")
        previous = now
    names = [n for n in ["p0", "p1", "p2", "p3"] if n in now["p"]]
    if len(names) >= 3:
        top_points = np.array([now["p"][n] for n in names]); utop = max(now["u"][n] for n in names)
    elif now["tr"] and now["tr"]["ok"]:
        top_points = np.array(now["tr"]["b"]); utop = now["tr"]["u"]
    else:
        return fail("Final top-height evidence unavailable", "Accept tabletop separation", {"effects": effects, "frame_id": now["frame_id"]}, "needs_replan")
    try:
        top = geo.plane(top_points)
    except Exception as e:
        return fail("Final surface geometry invalid", "Accept tabletop separation", {"reason": str(e)[:400], "effects": effects}, "needs_replan")
    utop += 2 * top["rms_m"]; spread = min(top["in_plane_spread_m"])
    tilt = float(np.sqrt(max(0.0, 1 - float(np.dot(normal, top["coefficients"][:3])) ** 2)))
    angular_allowance = min(1.0, 2 * utop / max(spread, 0.000001))
    diagonal = float(np.linalg.norm(context["historical_dimensions_m"][:2])) + 0.004
    height = history["top_to_table_height_m"] + 0.003
    observed_height = float(np.min(top_points @ normal + table[3]))
    lower = observed_height - height - diagonal * min(1.0, tilt + angular_allowance) - utop - utable
    separation = {"frame_id": now["frame_id"], "observed_top_height_m": observed_height, "historical_thickness_upper_m": height, "historical_diagonal_upper_m": diagonal, "measured_tilt_sine": tilt, "angular_allowance_rad_small_angle": angular_allowance, "patch_spread_m": spread, "top_uncertainty_m": utop, "table_uncertainty_m": utable, "separation_lower_m": lower, "threshold_m": 0.002, "residual_margin_m": lower - 0.002, "provenance": "Conservative rectangular-box bound from current top depth, historical dimensions, current identity and orientation uncertainty; not an unseen-bottom measurement."}
    if now["parameters"]["box_model"] != "unchanged" or now["parameters"]["table_same"] != "yes" or lower <= 0.002:
        return fail("Final tabletop separation gate", "Declare retained lift established", {"separation": separation, "parameters": now["parameters"], "effects": effects}, "needs_replan")
    tool = np.eye(4); tool[:3, :3] = geo.rotation(now["s"]["tcp_quaternion_xyzw"]).T
    tool[:3, 3] = -tool[:3, :3] @ np.array(now["s"]["tcp_position_world_m"])
    sample = top_points[:min(4, len(top_points))]
    evidence = {"interval_effects": effects, "separation": separation, "current_top_plane": top, "table_plane": table.tolist(), "current_top_samples_world_m": sample.tolist(), "current_top_samples_tool_m": geo.transform(sample, tool).tolist(), "historical_dimensions_m": context["historical_dimensions_m"], "departure_gate": admission, "obstacle_observations": now["parameters"]["hazards"], "gripper_policy": "keep throughout", "control_calls": used, "remaining_budgets": api.state()["budgets"], "retention_scope": "Independent package co-motion in both upward intervals with tabletop separation; no transfer or placement certified."}
    return finish("stage_complete", "Two observed lift intervals establish retained co-motion and tabletop separation.", evidence)

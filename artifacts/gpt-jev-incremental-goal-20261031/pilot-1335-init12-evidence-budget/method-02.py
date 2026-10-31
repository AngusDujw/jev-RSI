def main(api):
    questions = {}
    for axis in ["x", "y", "z", "rx", "ry", "rz"]:
        questions[axis] = {"type": "choice", "instructions": "For world axis " + axis + ", read the trusted state.processed_features.axes." + axis + ".goal_relation. Select positive for increase, negative for decrease, and hold for within_tolerance. Do not infer contact, image geometry, or grasp success.", "criteria": {"negative": "Decrease this world coordinate or world rotation-vector component.", "hold": "This axis is within its supplied deadband.", "positive": "Increase this world coordinate or world rotation-vector component."}}
    questions["gripper"] = {"type": "choice", "instructions": "Read state.processed_features.objective.gripper and deliver that exact requested choice. Closure is an attempted contact, not evidence of retention.", "criteria": {"open": "The requested objective is open.", "close": "The requested objective is close.", "keep": "The requested objective is keep."}}
    logs, failure, ref, reviews = [], {}, {}, [0]
    handoff = {"stage": "pick", "frame_convention": "World meters; tool quaternions xyzw; landmark identities refer to the same cream cheese package.", "checkpoint_keys": ["pick_reference", "pick_progress", "pick_test", "pick_result", "pick_gate", "pick_observation"], "warning": "Only keys actually written exist. Never reopen a possibly held package. Revalidate references after motion."}
    def plain(v):
        if isinstance(v, np.ndarray):
            return v.tolist()
        if isinstance(v, np.generic):
            return v.item()
        if isinstance(v, dict):
            return {k: plain(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [plain(x) for x in v]
        return v
    def brief(s):
        return {k: s[k] for k in ["frame_id", "native_steps", "tcp_position_world_m", "tcp_quaternion_xyzw", "gripper_qpos_m", "last_gripper_command"]}
    def stop(gate, action, operands, status="blocked"):
        failure.update({"gate": gate, "prevented_action": action, "operands": operands, "frame_id": api.state()["frame_id"], "threshold_provenance": "Operational heuristics unless explicitly labeled measured geometry or runtime budget.", "stage_status": status})
        api.checkpoint("pick_gate", failure)
        raise Exception(gate)
    def require(ok, gate, action, operands, status="blocked"):
        if not ok:
            stop(gate, action, operands, status)
    def observe(question, fields, required, context):
        s = api.state()
        require(reviews[0] == 0 and s["budgets"]["gpt_remaining"] > 28, "Effect review allocation exhausted", "Verify the lift", {"used": reviews[0], "allocation_after_builder": 1, "runtime_remaining": s["budgets"]["gpt_remaining"], "reserve": 28, "margin_calls": s["budgets"]["gpt_remaining"] - 29})
        r = api.review(question, context=context, fields=fields)
        reviews[0] += 1
        bad = [e["name"] for e in r["measurement_errors"]]
        points = {n: p for n, p in r["points"].items() if n not in bad and p["frame_id"] == r["frame_id"]}
        record = {"frame_id": r["frame_id"], "parameters": r["parameters"], "consumed_points": points, "measurement_errors": r["measurement_errors"][:8]}
        api.checkpoint("pick_observation", record)
        require(r["status"] != "stop", "Review requested stop", "Interpret lift evidence", {"reason": r["explanation"]}, "needs_replan")
        require(r["parameters"]["identity"] == "same_top_face", "Current package face unknown", "Measure package rise", {"frame_id": r["frame_id"], "parameters": r["parameters"]})
        for i, n in enumerate(required):
            if n not in points:
                pixel = r["parameters"]["patch_pixels"][i]
                try:
                    p = api.point(r["parameters"]["patch_camera"], [pixel[0] + 3, pixel[1]], radius=1)
                    if p["frame_id"] == r["frame_id"]:
                        points[n] = p
                except Exception as exc:
                    record["replacement_error"] = {"name": n, "error": str(exc)}
                api.checkpoint("pick_observation", record)
        require(all(n in points for n in required), "Surface depth unavailable after bounded replacement", "Verify lift effect", {"frame_id": r["frame_id"], "missing": [n for n in required if n not in points], "valid_measurements_key": "pick_observation", "remaining_effect_reviews": 0})
        return r["parameters"], points, r["frame_id"]
    def uncertainty(point):
        k = api.camera(point["camera"])["K"]
        return 0.001 + 2.0 * float(point["depth_m"]) / min(k[0][0], k[1][1])
    def plane_z(coeff, xy):
        return -(coeff[0] * xy[0] + coeff[1] * xy[1] + coeff[3]) / coeff[2]
    def go(target, quat, grip, phase, tol, limit, reserve):
        target = np.array(target, dtype=float)
        origin = np.array(geo.pad_position(api.state()))
        for lease in range(2):
            before = api.state()
            b = before["budgets"]
            calls = min(11, int(b["jev_remaining"]) - reserve, int(b["native_steps_remaining"] // 3) - reserve)
            require(calls > 0, "Insufficient control budget", phase, {"runtime_budgets": b, "reserved_control_calls": reserve, "available_lease_calls": calls, "admission_margin_calls": calls - 1})
            r = api.drive(target.tolist(), quat, grip, questions, features={"phase": phase, "source": "Program geometry in pick_reference; current residuals are host supplied.", "reference_frame": ref.get("validated_frame_id"), "contact_overlap_margin_m": ref.get("contact_overlap_margin_m"), "package_short_side_m": ref.get("short_side_m"), "position_tolerance_m": tol, "translation_limit_m": limit, "retention_unproven_until_effect_test": True}, tool_point="pad_center", max_calls=calls, translation_limit=limit, rotation_limit=0.07, steps=3, position_tolerance=tol, rotation_tolerance=0.01)
            after = api.state()
            p0, p1 = np.array(geo.pad_position(before)), np.array(geo.pad_position(after))
            r0, r1, rq = geo.rotation(before["tcp_quaternion_xyzw"]), geo.rotation(after["tcp_quaternion_xyzw"]), geo.rotation(quat)
            progress = float(np.linalg.norm(p1 - p0) + 0.04 * np.linalg.norm(r1 - r0))
            improvement = float(np.linalg.norm(p0 - target) - np.linalg.norm(p1 - target) + 0.04 * (np.linalg.norm(r0 - rq) - np.linalg.norm(r1 - rq)))
            entry = {"phase": phase, "lease": lease, "status": r["status"], "lease_calls": r["lease_calls"], "before": brief(before), "after": brief(after), "position_error_m": r["position_error_m"], "rotation_error_rad": r["rotation_error_rad"], "whole_lease_pose_progress_m_equivalent": progress, "objective_improvement_m_equivalent": improvement}
            logs.append(entry)
            api.checkpoint("pick_progress", entry)
            require(r["choices"]["gripper"] == grip, "Jev gripper command mismatch", phase, {"requested": grip, "actual": r["choices"]["gripper"]}, "abort")
            if phase == "differential lift test":
                lateral = float(np.linalg.norm(p1[:2] - origin[:2]))
                require(lateral <= 0.002 and r["rotation_error_rad"] <= 0.01, "Local lift assumptions changed", phase, {"frame_id": after["frame_id"], "lateral_m": lateral, "lateral_limit_m": 0.002, "lateral_margin_m": 0.002 - lateral, "rotation_rad": r["rotation_error_rad"], "rotation_limit_rad": 0.01, "rotation_margin_rad": 0.01 - r["rotation_error_rad"], "source": "Proprioception; operational corridor/attitude limits, not collision bounds."})
            if r["status"] == "reached":
                return after
            if phase == "differential lift test" and float(p1[2] - origin[2]) >= 0.8 * float(target[2] - origin[2]):
                entry["stop_reason"] = "Measured hand rise is sufficient for the independent effect test; no further pose chasing."
                api.checkpoint("pick_progress", entry)
                return after
            require(r["status"] == "lease_exhausted" and progress > 0.001 and improvement > 0.0005, "Stalled or ineffective local motion", phase, {"receipt": entry, "progress_threshold_m_equivalent": 0.001, "improvement_threshold_m_equivalent": 0.0005, "residual_progress_margin": progress - 0.001, "improvement_margin": improvement - 0.0005})
        stop("Finite feedback lease limit reached", phase, {"latest": logs[-1], "maximum_leases": 2, "maximum_calls_per_lease": 11})
    try:
        start = api.state()
        saved, prior = api.recall("pick_reference"), api.recall("pick_progress")["value"]
        ref.update(saved["value"])
        frame, quat = ref["frame_id"], start["tcp_quaternion_xyzw"]
        require(start["frame_id"] == 222 and start["last_gripper_command"] == "close" and prior.get("phase") == "closure dwell" and prior.get("dwell") == 1, "Snapshot/phase changed", "Use frame-222 local lift admission without replay", {"state": brief(start), "prior_progress": prior}, "needs_replan")
        # Frame-222 imagery admits only this local upward test, not carrying.
        names, bpts = ["A", "B", "C", "D", "E", "F"], {}
        selections = [("A", [310, 468]), ("B", [445, 468]), ("C", [312, 535]), ("D", [456, 535]), ("E", [312, 605]), ("F", [454, 605]), ("T1", [605, 503]), ("T2", [664, 504]), ("T3", [605, 568])]
        for name, pixel in selections:
            camera = "agentview" if name in ["T1", "T2", "T3"] else "robot0_eye_in_hand"
            try:
                bpts[name] = api.point(camera, pixel, radius=3)
            except Exception as first_error:
                api.checkpoint("pick_observation", {"frame_id": start["frame_id"], "consumed_points": bpts, "failed_name": name, "error": str(first_error)})
                bpts[name] = api.point(camera, [pixel[0] + 3, pixel[1]], radius=1)
            require(bpts[name]["frame_id"] == 222, "Stale labelled depth", "Prepare the local lift test", {"name": name, "point": bpts[name]})
        api.checkpoint("pick_observation", {"frame_id": 222, "consumed_points": bpts, "identity_source": "Supplied frame-222 views: package top and tabletop."})
        def fit_patch(points, label):
            try:
                fit = plain(geo.plane([p["world_m"] for p in points]))
            except Exception as exc:
                stop("Plane fit rejected", "Use the local surface patch", {"label": label, "points": points, "detail": str(exc)})
            u = max(uncertainty(p) for p in points)
            spread = float(min(fit["in_plane_spread_m"]))
            diagnostic = {"label": label, "frames": [p["frame_id"] for p in points], "fit": fit, "depth_plus_pixel_allowance_m": u, "spread_requirement_m": u + 3 * fit["rms_m"], "spread_margin_m": spread - u - 3 * fit["rms_m"], "rms_margin_m": u - fit["rms_m"], "normal_z_margin": fit["coefficients"][2] - 0.95, "provenance": "Heuristic spread/noise observability, not absolute size."}
            require(spread > u + 3 * fit["rms_m"] and fit["rms_m"] <= u and fit["coefficients"][2] >= 0.95, "Surface patch quality insufficient", "Use this patch for local vertical geometry", diagnostic)
            return fit, u
        top, u0 = fit_patch([bpts[n] for n in names], "pre-lift package top")
        table, ut = fit_patch([bpts[n] for n in ["T1", "T2", "T3"]], "stationary tabletop")
        planes = {"top": top["coefficients"], "table": table["coefficients"]}
        pad, rot, own = np.array(geo.pad_position(start)), geo.rotation(quat), start["own_geometry"]
        transform = np.eye(4)
        transform[:3, :3], transform[:3, 3] = rot, np.array(start["tcp_position_world_m"])
        lo, hi = own["finger_low_offset_tool_m"], own["finger_high_offset_tool_m"]
        world = geo.transform([[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]], transform)
        relative, extent = world - pad, np.array(own["pad_extent_in_tool_m"])
        half_height = float((abs(rot[2, 2]) * extent[2] - np.dot(np.abs(rot[2, :2]), extent[:2])) / 2)
        top_low = min(plane_z(planes["top"], v[:2]) for v in world)
        table_high = max(plane_z(planes["table"], v[:2]) for v in world)
        overlap = min(float(pad[2]) + half_height, top_low) - max(float(pad[2]) - half_height, table_high)
        clearance = min(float(v[2]) - plane_z(planes["table"], v[:2]) for v in world)
        normal_difference = 0.0
        for key, fit in [("top", top), ("table", table)]:
            historical = np.array(ref[key + "_plane"]["coefficients"])
            historical[3] = -float(np.dot(historical[:3], fit["center_world_m"]))
            normal_difference = max(normal_difference, max(abs(plane_z(fit["coefficients"], v[:2]) - plane_z(historical, v[:2])) for v in world))
        pixel_slope = max((u - 0.001) * float(np.linalg.norm(np.array(fit["coefficients"])[:2])) / fit["coefficients"][2] for fit, u in [(top, u0), (table, ut)])
        u_now = max(float(ref["vertical_allowance_m"]), 0.001 + top["rms_m"] + table["rms_m"] + pixel_slope + normal_difference)
        sweep = float(max(np.linalg.norm(relative, axis=1))) * 0.01
        contact = {"frame_id": 222, "top_plane": top, "table_plane": table, "pad_world_m": pad.tolist(), "own_geometry": own, "overlap_m": overlap, "finger_table_clearance_m": clearance, "vertical_allowance_m": u_now, "normal_disagreement_allowance_m": normal_difference, "pixel_slope_allowance_m": pixel_slope, "rotation_sweep_m": sweep, "rotation_tolerance_rad": 0.01, "side_overlap_min_m": 0.003, "table_gap_min_m": 0.004, "contact_margin_m": overlap - u_now - sweep - 0.003, "table_margin_m": clearance - u_now - sweep - 0.004, "prior_hold_failure": api.recall("pick_gate")["value"], "provenance": "Current closed geometry; 3/4 mm minima and allowances are heuristics. Upward test only; no new hold, descent or closure."}
        ref["post_closure_contact"], ref["validated_frame_id"] = contact, 222
        ref["pad_side_overlap_m"], ref["finger_table_clearance_m"], ref["contact_overlap_margin_m"] = overlap, clearance, contact["contact_margin_m"]
        ref.update(plain(ref))
        api.checkpoint("pick_reference", ref)
        require(min(contact["contact_margin_m"], contact["table_margin_m"]) > 0, "Post-closure local contact geometry inadequate", "Begin the bounded upward differential test", plain(contact))
        budget = api.state()["budgets"]
        require(budget["jev_remaining"] >= 94 and budget["native_steps_remaining"] >= 282 and budget["gpt_remaining"] > 28, "Lift and effect verification allocation unavailable", "Begin the differential test", {"runtime_budgets": budget, "maximum_test_calls": 22, "control_reserve": 72, "call_margin": budget["jev_remaining"] - 94, "step_margin": budget["native_steps_remaining"] - 282, "effect_reviews_required": 1, "review_margin": budget["gpt_remaining"] - 29, "model_reserve": 28})
        before, bf = api.state(), start["frame_id"]
        points0 = np.array([bpts[n]["world_m"] for n in names])
        lift = max(0.050, 8 * u0 + 0.015)
        require(lift <= 0.060, "Test exceeds locally observed upward corridor", "Execute the test lift", {"frame_id": bf, "patch_allowance_m": u0, "required_lift_m": lift, "local_limit_m": 0.060, "margin_m": 0.060 - lift, "provenance": "Heuristic from frame-222 views, not hidden clearance."})
        baseline = {"state": brief(before), "frame_id": bf, "surface_samples": {n: bpts[n] for n in names}, "top_plane": top, "table_plane": table, "allowance_m": u0, "planned_lift_m": lift, "identity": "Cream-cheese upper printed face, frame-222 images.", "scope": "Planar patch, not corresponding landmarks. No tracker."}
        api.checkpoint("pick_test", baseline)
        lifted_target = np.array(geo.pad_position(before))
        lifted_target[2] += lift
        after = go(lifted_target.tolist(), quat, "close", "differential lift test", 0.002, 0.008, 72)
        enames = ["U1", "U2", "U3", "U4", "U5", "U6"]
        ep, epts, ef = observe("Verify ONLY the pick after a straight upward test. Request U1..U6 at six well-spread smooth visible INTERIOR samples of the SAME cream-cheese printed upper planar face. Use either view; avoid fingers, perimeter depth mixtures, and side faces. These may be NEW locations on that face. Also return patch_camera and patch_pixels: the six U1..U6 pixel coordinates in order, all in that camera and at least six pixels inside this face, permitting a smaller offset depth sample on failure. Report face identity, whether the package remains between the fingers, visible tabletop separation, and observed drop/slip. Request OPTIONAL bowl_rim, stove_top and bottle_top at visible nearby upper surfaces for handoff; these are samples, not full obstacle bounds. Hidden perimeter and a tracker are unnecessary.", {"patch_camera": ["agentview", "robot0_eye_in_hand"], "patch_pixels": {"type": "array", "minItems": 6, "maxItems": 6, "items": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "integer", "minimum": 6, "maximum": 761}}}, "identity": ["same_top_face", "unknown"], "between_fingers": ["yes", "no", "unknown"], "table_gap": ["visible", "absent", "unknown"], "drop_or_slip": ["observed", "none_visible", "unknown"], "nearby_obstacle_notes": {"type": "string", "maxLength": 1000}, "reason": "string"}, enames, {"baseline": baseline, "actual_hand_after": brief(after), "scope": "Normal co-motion only; not full pose."})
        require(ep["identity"] == "same_top_face", "Post-lift surface identity unresolved", "Interpret measured package rise", {"frame_id": ef, "parameters": ep, "baseline_checkpoint": "pick_test"})
        end_top, u1 = fit_patch([epts[n] for n in enames], "post-lift package top")
        motion = np.eye(4)
        motion[:3, :3] = geo.rotation(after["tcp_quaternion_xyzw"]) @ geo.rotation(before["tcp_quaternion_xyzw"]).T
        motion[:3, 3] = np.array(after["tcp_position_world_m"]) - motion[:3, :3] @ np.array(before["tcp_position_world_m"])
        predicted = geo.transform(points0, motion)
        coeff, c0, c1 = np.array(end_top["coefficients"]), np.array(top["center_world_m"]), np.array(end_top["center_world_m"])
        normal_error = float(max(np.abs(predicted @ coeff[:3] + coeff[3])))
        radius0 = float(max(np.linalg.norm(points0 - c0, axis=1)))
        radius1 = max(float(max(np.linalg.norm(predicted - c1, axis=1))), float(np.linalg.norm(c0[:2] - c1[:2])))
        a0 = (u0 + top["rms_m"]) * (1 + radius0 / min(top["in_plane_spread_m"]))
        a1 = (u1 + end_top["rms_m"]) * (1 + radius1 / min(end_top["in_plane_spread_m"]))
        allowance = (a0 + a1) / min(top["coefficients"][2], coeff[2])
        hand_delta = np.array(geo.pad_position(after)) - np.array(geo.pad_position(before))
        hand_motion = float(np.linalg.norm(hand_delta))
        rise = float(plane_z(coeff, c0[:2]) - c0[2])
        margins = {"co_motion_m": 0.30 * hand_motion - normal_error - allowance, "rise_m": rise - allowance - 0.025, "hand_rise_m": float(hand_delta[2]) - 0.7 * lift}
        effect = plain({"frame_before": bf, "frame_after": ef, "hand_delta_world_m": hand_delta, "hand_motion_m": hand_motion, "surface_normal_prediction_error_m": normal_error, "surface_rise_m": rise, "allowance_before_m": a0, "allowance_after_m": a1, "combined_allowance_m": allowance, "support_radii_m": [radius0, radius1], "patch_spreads_m": [top["in_plane_spread_m"], end_top["in_plane_spread_m"]], "co_motion_limit_m": 0.30 * hand_motion, "minimum_surface_rise_m": 0.025, "hand_rise_min_m": 0.7 * lift, "margins": margins, "review": ep, "current_state": brief(after), "current_top_plane": end_top, "surface_samples": {n: epts[n] for n in enames}, "visible_obstacle_samples": {n: epts[n] for n in ["bowl_rim", "stove_top", "bottle_top"] if n in epts}, "scope": "Current face planes test upward co-motion against actual TCP motion, not full pose or tangential slip.", "provenance": "Heuristic uncertainty scales with patch evaluation radius/spread."})
        api.checkpoint("pick_result", effect)
        require(ef == after["frame_id"] and ef > bf and min(margins.values()) >= 0 and ep["between_fingers"] == "yes" and ep["table_gap"] == "visible" and ep["drop_or_slip"] == "none_visible", "Retained lift effect not established", "Handoff a retained package for transfer", effect, "needs_replan" if ep["between_fingers"] == "no" or ep["table_gap"] == "absent" or ep["drop_or_slip"] == "observed" else "blocked")
        handoff.update({"retained_lift_test_passed": True, "current_frame_id": ef, "gripper_command": "close", "package_dimensions_from_frame": frame, "package_long_short_height_m": [ref["long_side_m"], ref["short_side_m"], ref["top_to_table_height_m"]], "references": {"pick_reference": "Historical shape and closure admission; post_closure_contact has frame-222 geometry and prior failed hold operands.", "pick_test": "Frame-222 surface samples, planes and actual hand baseline.", "pick_result": "Fresh normal co-motion, current face samples, separation review and optional obstacle samples.", "pick_progress": "Last acknowledged lease.", "pick_gate": "Historical failure, not necessarily current.", "pick_observation": "Consumed fresh review measurements, partials and errors."}, "next_stage_assumptions": "Rigid box; upward retention only, not full pose or future clearance. Revalidate attachment, bowl fit and carrying corridor. Obstacle samples are not bounds. No transfer or release occurred."})
        return {"stage_status": "stage_complete", "reason": "Fresh package surface rise agrees with actual hand lift; review confirms retention between the fingers and tabletop separation.", "evidence": effect, "handoff": handoff, "completion_proposed": False}
    except Exception as exc:
        if not failure:
            failure.update({"gate": "Runtime or measurement failure", "prevented_action": "Further pick motion", "detail": str(exc), "state": brief(api.state()), "stage_status": "blocked"})
            api.checkpoint("pick_gate", failure)
        handoff["last_acknowledged_state"] = brief(api.state())
        handoff["recovery_requirement"] = "Inspect written checkpoints and fresh views. Preserve the actual gripper state; do not repeat contact or open blindly."
        return {"stage_status": failure["stage_status"], "reason": str(exc), "evidence": {"failure": failure, "recent_progress": logs[-4:]}, "handoff": handoff, "completion_proposed": False}

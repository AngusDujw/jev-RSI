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
        accumulated, prior_frame = {}, None
        for attempt in range(2):
            s = api.state()
            require(reviews[0] < 4 and s["budgets"]["gpt_remaining"] > 28, "Observation allocation exhausted", question, {"reviews_used_this_repair": reviews[0], "remaining_stage_allocation_at_entry": 4, "runtime_gpt_remaining": s["budgets"]["gpt_remaining"], "supervision_and_later_reserve": 28, "review_count_margin": 3 - reviews[0], "runtime_review_margin_calls": s["budgets"]["gpt_remaining"] - 29, "missing": [n for n in required if n not in accumulated]})
            suffix = "" if attempt == 0 else " Replacement measurement only: use the other camera or a smaller smooth depth patch at the SAME physical feature. Do not redefine a landmark or repeat an invalid boundary patch. Previously valid same-frame measurements may be reused. Missing names: " + str([n for n in required if n not in accumulated])
            r = api.review(question + suffix, context=context, fields=fields)
            reviews[0] += 1
            if prior_frame != r["frame_id"]:
                accumulated = {}
            prior_frame = r["frame_id"]
            bad = [e["name"] for e in r["measurement_errors"]]
            for name, point in r["points"].items():
                if name not in bad and point["frame_id"] == r["frame_id"]:
                    accumulated[name] = point
            api.checkpoint("pick_observation", {"frame_id": r["frame_id"], "parameters": r["parameters"], "consumed_points": {n: accumulated[n] for n in required if n in accumulated}, "measurement_errors": r["measurement_errors"][:8]})
            require(r["status"] != "stop", "Observation requested a stop", question, {"explanation": r["explanation"]}, "needs_replan")
            if all(n in accumulated for n in required):
                return r["parameters"], accumulated, r["frame_id"]
            context = {"original_context": context, "valid_same_frame_points": accumulated, "missing_names": [n for n in required if n not in accumulated]}
        stop("Missing valid depth or landmark correspondence", question, {"frame_id": prior_frame, "missing": [n for n in required if n not in accumulated]})
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
            calls = min(16, int(b["jev_remaining"]) - reserve, int(b["native_steps_remaining"] // 3) - reserve)
            require(calls > 0, "Insufficient control budget", phase, {"runtime_budgets": b, "reserved_control_calls": reserve, "available_lease_calls": calls, "admission_margin_calls": calls - 1})
            r = api.drive(target.tolist(), quat, grip, questions, features={"phase": phase, "source": "Program geometry in pick_reference; current residuals are host supplied.", "reference_frame": ref.get("validated_frame_id"), "contact_overlap_margin_m": ref.get("contact_overlap_margin_m"), "package_short_side_m": ref.get("short_side_m"), "position_tolerance_m": tol, "translation_limit_m": limit, "retention_unproven_until_effect_test": True}, tool_point="pad_center", max_calls=calls, translation_limit=limit, rotation_limit=0.07, steps=3, position_tolerance=tol, rotation_tolerance=0.03)
            after = api.state()
            p0, p1 = np.array(geo.pad_position(before)), np.array(geo.pad_position(after))
            r0, r1, rq = geo.rotation(before["tcp_quaternion_xyzw"]), geo.rotation(after["tcp_quaternion_xyzw"]), geo.rotation(quat)
            progress = float(np.linalg.norm(p1 - p0) + 0.04 * np.linalg.norm(r1 - r0))
            improvement = float(np.linalg.norm(p0 - target) - np.linalg.norm(p1 - target) + 0.04 * (np.linalg.norm(r0 - rq) - np.linalg.norm(r1 - rq)))
            entry = {"phase": phase, "lease": lease, "status": r["status"], "lease_calls": r["lease_calls"], "before": brief(before), "after": brief(after), "position_error_m": r["position_error_m"], "rotation_error_rad": r["rotation_error_rad"], "whole_lease_pose_progress_m_equivalent": progress, "objective_improvement_m_equivalent": improvement}
            logs.append(entry)
            api.checkpoint("pick_progress", entry)
            require(r["choices"]["gripper"] == grip, "Jev gripper command mismatch", phase, {"requested": grip, "actual": r["choices"]["gripper"]}, "abort")
            if r["status"] == "reached":
                return after
            if phase == "differential lift test" and float(p1[2] - origin[2]) >= 0.8 * float(target[2] - origin[2]):
                entry["stop_reason"] = "Measured hand rise is sufficient for the independent effect test; no further pose chasing."
                api.checkpoint("pick_progress", entry)
                return after
            require(r["status"] == "lease_exhausted" and progress > 0.001 and improvement > 0.0005, "Stalled or ineffective local motion", phase, {"receipt": entry, "progress_threshold_m_equivalent": 0.001, "improvement_threshold_m_equivalent": 0.0005, "residual_progress_margin": progress - 0.001, "improvement_margin": improvement - 0.0005})
        stop("Finite feedback lease limit reached", phase, {"latest": logs[-1], "maximum_leases": 2, "maximum_calls_per_lease": 16})
    try:
        start = api.state()
        require(start["last_gripper_command"] == "open", "Resume requires the acknowledged open state", "Assess one new closure, never replay descent or reopen", brief(start), "needs_replan")
        saved = api.recall("pick_reference")
        ref.update(saved["value"])
        frame = ref["frame_id"]
        prior = api.recall("pick_progress")["value"]
        pad = np.array(geo.pad_position(start))
        old_target = np.array([ref["center_world_m"][0], ref["center_world_m"][1], ref["contact_pad_z_m"]])
        entry = {"phase": "Resume after acknowledged descent; old target pursuit cancelled", "state": brief(start), "prior_completed_lease_frame": prior.get("after", prior.get("state", {})).get("frame_id"), "old_pad_target_world_m": old_target.tolist(), "actual_pad_world_m": pad.tolist(), "old_target_residual_m": float(np.linalg.norm(pad - old_target)), "acknowledged_frame_201_to_216_tcp_motion_m": float(np.linalg.norm(np.array(start["tcp_position_world_m"]) - np.array([-0.0518291, 0.145343, 0.915897]))), "provenance": "Current proprioception and supplied acknowledged receipts. Small progress does not identify a collision."}
        logs.append(entry)
        api.checkpoint("pick_progress", entry)
        fields = {"unchanged": ["yes", "shifted", "unknown"], "jaw_fit": ["fits", "does_not_fit", "unknown"], "closure_route": ["clear", "obstructed", "unknown"], "reason": "string"}
        hp, hpts, hf = observe("At this ACTUAL pose, request top_now at a smooth VISIBLE INTERIOR patch of the cream cheese upper face, not its occluded center or a perimeter corner, and support_now on adjacent tabletop. Check unchanged identity, position and attitude against the saved geometry using visible features; hidden corners need not be recovered. jaw_fit asks whether these open fingers straddle its short sides. closure_route concerns ONLY closing inward while holding this current pose, with no descent or translation. Identify any non-package obstruction to that closure. Do not infer collision from slow convergence, demand proof of retention, or certify a future lift corridor.", fields, ["top_now", "support_now"], {"saved_reference": ref, "reference_checkpoint_frame": saved["frame_id"], "actual_state": brief(start), "actual_own_geometry": start["own_geometry"], "cancelled_target": entry})
        require(hp["unchanged"] == "yes", "Package reference identity or stationarity unresolved", "Use historical dimensions for current contact", {"parameters": hp, "frame_id": hf}, "needs_replan" if hp["unchanged"] == "shifted" else "blocked")
        require(hp["closure_route"] == "clear", "Current closure corridor not admitted", "Close at the actual pose", {"closure_route": hp["closure_route"], "reason": hp["reason"], "frame_id": hf}, "needs_replan" if hp["closure_route"] == "obstructed" else "blocked")
        require(hp["jaw_fit"] == "fits", "Current finger straddle unresolved", "Close at the actual pose", {"jaw_fit": hp["jaw_fit"], "reason": hp["reason"], "frame_id": hf}, "needs_replan" if hp["jaw_fit"] == "does_not_fit" else "blocked")
        top, table = ref["top_plane"], ref["table_plane"]
        uz = float(ref["vertical_allowance_m"])
        validation = {"source_frame": frame, "fresh_frame": hf, "uncertainty_m": uz, "threshold_m": uz + 0.002, "errors_m": {}, "margins_m": {}}
        planes = {}
        for name, fit, point in [("top", top, hpts["top_now"]), ("table", table, hpts["support_now"])]:
            coeff = np.array(fit["coefficients"])
            error = abs(float(np.dot(coeff[:3], point["world_m"]) + coeff[3]))
            validation["errors_m"][name], validation["margins_m"][name] = error, uz + 0.002 - error
            coeff[3] = -float(np.dot(coeff[:3], point["world_m"]))
            planes[name] = coeff.tolist()
        require(min(validation["margins_m"].values()) >= 0, "Fresh surface heights invalidate historical planes", "Use the saved local contact geometry", validation, "needs_replan")
        quat = start["tcp_quaternion_xyzw"]
        rot, own = geo.rotation(quat), start["own_geometry"]
        transform = np.eye(4)
        transform[:3, :3], transform[:3, 3] = rot, np.array(start["tcp_position_world_m"])
        lo, hi = own["finger_low_offset_tool_m"], own["finger_high_offset_tool_m"]
        vertices = np.array([[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]])
        world = geo.transform(vertices, transform)
        relative = world - pad
        corners = np.array(ref["corners_world_m"])
        top_low = float(min(plane_z(planes["top"], c[:2]) for c in corners))
        table_high = float(max(plane_z(planes["table"], c[:2]) for c in corners))
        extent = np.array(own["pad_extent_in_tool_m"])
        half_height = float((abs(rot[2, 2]) * extent[2] - np.dot(np.abs(rot[2, :2]), extent[:2])) / 2)
        clearance = float(min(float(v[2]) - plane_z(planes["table"], v[:2]) for v in world))
        overlap = min(float(pad[2]) + half_height, top_low) - max(float(pad[2]) - half_height, table_high)
        # Holding a newly anchored pose is not further convergence on the old target.
        hold_tol, hold_rot = 0.0005, 0.01
        radius_xy = float(max(np.linalg.norm(relative[:, :2], axis=1)))
        rotation_sweep = radius_xy * math.sin(hold_rot) + float(max(np.abs(relative[:, 2]))) * (1 - math.cos(hold_rot))
        pixel_slope = max((uncertainty(hpts[n]) - 0.001) * float(np.linalg.norm(np.array(planes[p])[:2])) / planes[p][2] for n, p in [("top_now", "top"), ("support_now", "table")])
        u_now = max(uz, 0.001 + top["rms_m"] + table["rms_m"] + pixel_slope)
        margin_contact = overlap - u_now - hold_tol - rotation_sweep - 0.003
        margin_table = clearance - u_now - hold_tol - rotation_sweep - 0.004
        contact = {"frame_id": hf, "historical_shape_frame": frame, "depth_receipts": hpts, "validated_planes": planes, "actual_pad_world_m": pad.tolist(), "actual_quaternion_xyzw": quat, "overlap_m": overlap, "common_pad_vertical_half_span_m": half_height, "finger_table_clearance_m": clearance, "minimum_side_overlap_m": 0.003, "minimum_table_gap_m": 0.004, "vertical_uncertainty_m": u_now, "pixel_slope_contribution_m": pixel_slope, "position_hold_budget_m": hold_tol, "rotation_hold_budget_rad": hold_rot, "rotation_vertical_sweep_m": rotation_sweep, "contact_residual_margin_m": margin_contact, "table_residual_margin_m": margin_table, "validation": validation, "provenance": "Dimensions and normals are historical, freshly checked for stationarity; plane offsets are current depth. Own bounds and pose are measured. All allowances and the unchanged 3 mm side/4 mm table minima are operational heuristics, not external constraints or calibrated confidence bounds."}
        ref["current_contact"], ref["validated_frame_id"] = contact, hf
        api.checkpoint("pick_reference", ref)
        require(margin_contact > 0, "Actual-pose side overlap insufficient", "Single stationary closure", contact)
        require(margin_table > 0, "Actual-pose finger/table margin insufficient", "Single stationary closure", contact)
        target = pad.tolist()
        ref["pad_side_overlap_m"], ref["finger_table_clearance_m"], ref["contact_overlap_margin_m"] = overlap, clearance, margin_contact
        api.checkpoint("pick_reference", ref)
        require(api.state()["budgets"]["jev_remaining"] >= 106 and api.state()["budgets"]["native_steps_remaining"] >= 318, "Insufficient bounded contact-test allocation", "Close and perform one lift test", {"runtime_budgets": api.state()["budgets"], "stage_max_calls": 34, "later_call_reserve": 72, "required_steps_including_reserve": 318, "call_margin": api.state()["budgets"]["jev_remaining"] - 106, "step_margin": api.state()["budgets"]["native_steps_remaining"] - 318, "provenance": "Runtime balances are constraints; stage allocation and later reserve are operational budgeting."})
        require(reviews[0] <= 2 and api.state()["budgets"]["gpt_remaining"] >= 30, "Insufficient observation budget before contact", "Close, measure a baseline, and verify a lift", {"repair_reviews_used": reviews[0], "allocation_at_entry": 4, "remaining_runtime_gpt": api.state()["budgets"]["gpt_remaining"], "required_runtime_gpt_including_reserve": 30, "margin_calls": api.state()["budgets"]["gpt_remaining"] - 30})
        for dwell in range(2):
            r = api.control(target, quat, "close", questions, features={"phase": "One closure attempt; two three-step settling deliveries, no reopening or retry.", "retention": "not yet tested", "pad_side_overlap_m": ref["pad_side_overlap_m"], "finger_table_clearance_m": ref["finger_table_clearance_m"]}, tool_point="pad_center", translation_limit=0.001, rotation_limit=0.01, steps=3, position_tolerance=hold_tol, rotation_tolerance=hold_rot)
            api.checkpoint("pick_progress", {"phase": "closure dwell", "dwell": dwell, "state": brief(api.state()), "receipt_status": r["status"]})
            require(r["status"] != "stalled" and r["choices"]["gripper"] == "close" and r["position_error_m"] <= hold_tol and r["rotation_error_rad"] <= hold_rot, "Stationary closure hold or command failure", "Continue the single contact attempt", {"status": r["status"], "position_error_m": r["position_error_m"], "position_limit_m": hold_tol, "pose_margin_m": hold_tol - r["position_error_m"], "rotation_error_rad": r["rotation_error_rad"], "rotation_limit_rad": hold_rot, "rotation_margin_rad": hold_rot - r["rotation_error_rad"], "frame_id": r["frame_id"], "contact_geometry_checkpoint": "pick_reference", "choices": r["choices"]}, "abort" if r["choices"]["gripper"] != "close" else "blocked")
        descriptions = {n + "_description": {"type": "string", "maxLength": 240} for n in ["A", "B", "C"]}
        descriptions.update({"identity": ["clear", "unknown"], "between_fingers": ["yes", "missed", "unknown"], "lift_route": ["clear", "obstructed", "unknown"], "reason": "string"})
        bp, bpts, bf = observe("Establish a PRE-LIFT baseline after closure. Request A,B,C at three distinct, widely separated, identifiable printed features or visible surface landmarks on the cream cheese TOP face. Internal printed landmarks are preferable to occluded perimeter corners. Describe each physical feature precisely for reidentification in the next view; use either camera. Check identity and whether the package is positioned between the fingers, NOT whether retention is already proved. lift_route concerns a single straight upward test of at most 0.075 m with the current closed gripper. Do not ask for hidden corners.", descriptions, ["A", "B", "C"], ref)
        require(bp["identity"] == "clear" and bp["between_fingers"] == "yes" and bp["lift_route"] == "clear", "Lift test not admitted", "One upward retention test", {"parameters": bp, "frame_id": bf}, "needs_replan" if bp["between_fingers"] == "missed" or bp["lift_route"] == "obstructed" else "blocked")
        before = api.state()
        points0 = [bpts[n]["world_m"] for n in ["A", "B", "C"]]
        u0 = max(uncertainty(bpts[n]) for n in ["A", "B", "C"])
        lift = max(0.050, 8 * u0 + 0.015)
        require(lift <= 0.075, "Insufficient observable test motion", "Lift within the reviewed corridor", {"landmark_allowance_m": u0, "required_lift_m": lift, "reviewed_lift_limit_m": 0.075, "residual_margin_m": 0.075 - lift, "frame_id": bf})
        baseline = {"state": before, "landmarks": {n: bpts[n] for n in ["A", "B", "C"]}, "descriptions": {n: bp[n + "_description"] for n in ["A", "B", "C"]}, "frame_id": bf, "uncertainty_allowance_m": u0, "planned_lift_m": lift, "provenance": "Fresh identified visible surface points AFTER closure; no inference from joint closure."}
        api.checkpoint("pick_test", baseline)
        require(reviews[0] < 4 and api.state()["budgets"]["gpt_remaining"] >= 29, "Insufficient effect-verification budget", "Execute the test lift", {"repair_reviews_used": reviews[0], "remaining_runtime_gpt": api.state()["budgets"]["gpt_remaining"], "required_runtime_gpt_including_reserve": 29, "margin_calls": api.state()["budgets"]["gpt_remaining"] - 29})
        lifted_target = np.array(geo.pad_position(before))
        lifted_target[2] += lift
        after = go(lifted_target.tolist(), quat, "close", "differential lift test", 0.002, 0.008, 72)
        ep, epts, ef = observe("Verify ONLY this pick. Request A,B,C at the SAME physical top-face features described in pick_test; never substitute new points under old labels. Use either current view and report identity unknown if correspondence is ambiguous. Is there a visible gap between the package and tabletop, and has a drop or slip been observed? Also request OPTIONAL bowl_rim at the visible highest rim, stove_top at its visible nearby upper corner, and bottle_top at the cork top for handoff. These are visible samples, not hidden clearance bounds. Missing optional obstacle samples must not invalidate successful landmark measurements.", {"identity": ["clear", "unknown"], "table_gap": ["visible", "absent", "unknown"], "drop_or_slip": ["observed", "none_visible", "unknown"], "nearby_obstacle_notes": {"type": "string", "maxLength": 1000}, "reason": "string"}, ["A", "B", "C"], {"baseline": baseline, "package_geometry": ref, "actual_hand_after": brief(after)})
        require(ep["identity"] == "clear", "Post-lift landmark identity unresolved", "Interpret differential package motion", {"frame_id": ef, "parameters": ep, "baseline_checkpoint": "pick_test"})
        points1 = [epts[n]["world_m"] for n in ["A", "B", "C"]]
        u1 = max(uncertainty(epts[n]) for n in ["A", "B", "C"])
        attachment = float(geo.attachment_error(points0, points1, before, after))
        hand_delta = np.array(geo.pad_position(after)) - np.array(geo.pad_position(before))
        hand_motion = float(np.linalg.norm(hand_delta))
        object_rises = np.array(points1)[:, 2] - np.array(points0)[:, 2]
        allowance = u0 + u1
        attachment_margin = 0.30 * hand_motion - attachment - allowance
        rise_margin = float(min(object_rises)) - allowance - 0.025
        effect = {"frame_before": bf, "frame_after": ef, "hand_delta_world_m": hand_delta.tolist(), "hand_motion_m": hand_motion, "object_point_rises_m": object_rises.tolist(), "attachment_error_m": attachment, "allowance_before_m": u0, "allowance_after_m": u1, "attachment_limit_m": 0.30 * hand_motion, "attachment_margin_m": attachment_margin, "minimum_object_rise_m": 0.025, "object_rise_margin_m": rise_margin, "planned_lift_m": lift, "hand_rise_min_m": 0.7 * lift, "hand_rise_margin_m": float(hand_delta[2]) - 0.7 * lift, "landmark_pairwise_spread_m": [float(np.linalg.norm(np.array(points0[i]) - np.array(points0[j]))) for i, j in [(0, 1), (0, 2), (1, 2)]], "observability_scope": "Tests upward co-motion; no angular pose estimate or full perimeter recovery is claimed from this patch.", "review": ep, "current_state": brief(after), "landmarks": {n: epts[n] for n in ["A", "B", "C"]}, "visible_obstacle_samples": {n: epts[n] for n in ["bowl_rim", "stove_top", "bottle_top"] if n in epts}, "provenance": "Independent fresh point correspondences versus measured TCP rigid motion; 1 mm depth plus two-pixel localization allowances are model-selected, not calibrated bounds."}
        api.checkpoint("pick_result", effect)
        require(ef > bf and ep["identity"] == "clear" and ep["drop_or_slip"] != "observed" and ep["table_gap"] == "visible" and float(hand_delta[2]) >= 0.7 * lift and attachment_margin >= 0 and rise_margin >= 0, "Retained lift effect not established", "Handoff a retained package for transfer", effect, "needs_replan" if ep["drop_or_slip"] == "observed" or ep["table_gap"] == "absent" else "blocked")
        handoff.update({"retained_lift_test_passed": True, "current_frame_id": ef, "gripper_command": "close", "package_dimensions_from_frame": frame, "package_long_short_height_m": [ref["long_side_m"], ref["short_side_m"], ref["top_to_table_height_m"]], "references": {"pick_reference": "Historical shape at frame 0, hover validation at 105, and current_contact: fresh depth offsets, current own-finger bounds and actual-pose closure margins after the acknowledged descent; no replay.", "pick_test": "Post-closure landmark identities and actual hand baseline.", "pick_result": "Fresh differential lift proof and current visible obstacle samples.", "pick_progress": "Last acknowledged physical phase.", "pick_gate": "Only exists if a gate failed."}, "next_stage_assumptions": "Box is rigid; tested local retention is not a guarantee for arbitrary motion. Revalidate attachment, bowl opening, placement fit, and carrying corridor. Obstacle samples are current visible heights/locations, not complete bounds or hidden clearance. No transfer or release was performed."})
        return {"stage_status": "stage_complete", "reason": "Fresh package motion agrees with actual hand motion and the package is visibly clear of the table.", "evidence": effect, "handoff": handoff, "completion_proposed": False}
    except Exception as exc:
        if not failure:
            failure.update({"gate": "Runtime or measurement failure", "prevented_action": "Further pick motion", "detail": str(exc), "state": brief(api.state()), "stage_status": "blocked"})
            api.checkpoint("pick_gate", failure)
        handoff["last_acknowledged_state"] = brief(api.state())
        handoff["recovery_requirement"] = "Inspect written checkpoints and fresh views. Preserve the actual gripper state; do not repeat contact or open blindly."
        return {"stage_status": failure["stage_status"], "reason": str(exc), "evidence": {"failure": failure, "recent_progress": logs[-4:]}, "handoff": handoff, "completion_proposed": False}

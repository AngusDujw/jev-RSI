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
            require(reviews[0] < 8 and s["budgets"]["gpt_remaining"] > 28, "Observation allocation exhausted", question, {"reviews_used": reviews[0], "stage_cap": 8, "runtime_gpt_remaining": s["budgets"]["gpt_remaining"], "supervision_and_later_reserve": 28, "review_count_margin": 7 - reviews[0], "runtime_review_margin_calls": s["budgets"]["gpt_remaining"] - 29, "missing": [n for n in required if n not in accumulated]})
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
        for lease in range(4):
            before = api.state()
            b = before["budgets"]
            calls = min(24, int(b["jev_remaining"]) - reserve, int(b["native_steps_remaining"] // 3) - reserve)
            require(calls > 0, "Insufficient control budget", phase, {"runtime_budgets": b, "reserved_control_calls": reserve, "available_lease_calls": calls, "admission_margin_calls": calls - 1})
            r = api.drive(target.tolist(), quat, grip, questions, features={"phase": phase, "source": "Program geometry in pick_reference; current residuals are host supplied.", "reference_frame": ref.get("frame_id"), "contact_overlap_margin_m": ref.get("contact_overlap_margin_m"), "package_short_side_m": ref.get("short_side_m"), "position_tolerance_m": tol, "translation_limit_m": limit, "retention_unproven_until_effect_test": True}, tool_point="pad_center", max_calls=calls, translation_limit=limit, rotation_limit=0.07, steps=3, position_tolerance=tol, rotation_tolerance=0.03)
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
            require(r["status"] == "lease_exhausted" and progress > 0.001 and improvement > 0.0005, "Stalled or ineffective local motion", phase, {"receipt": entry, "progress_threshold_m_equivalent": 0.001, "improvement_threshold_m_equivalent": 0.0005, "residual_progress_margin": progress - 0.001, "improvement_margin": improvement - 0.0005})
        stop("Finite feedback lease limit reached", phase, {"latest": logs[-1], "maximum_leases": 4})
    try:
        start = api.state()
        require(start["last_gripper_command"] == "open", "Entry is not known open", "Begin a new pick attempt", brief(start), "needs_replan")
        pixel = {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "integer", "minimum": 0, "maximum": 767}}
        fields = {"identity": ["cream_cheese_box", "unknown"], "resting": ["on_table", "not_on_table", "unknown"], "top_camera": ["agentview", "robot0_eye_in_hand"], "corners": {"type": "array", "minItems": 4, "maxItems": 4, "items": pixel}, "high_route": ["clear", "obstructed", "unknown"], "hover_route": ["clear", "obstructed", "unknown"], "reason": "string"}
        p, pts, frame = observe("Identify the cream cheese rectangular package, not the bowl or stove. Request depth points t0,t1,t2,t3 widely separated INSIDE its flat upper face, and s0,s1,s2 noncollinear on the adjacent tabletop. Return four OUTER upper-face corner pixels cyclically in top_camera; do not request mixed-depth corner patches. Independently assess high_route: rotate a downward open gripper to align its tool x with the package long side and translate at the CURRENT pad height to above its center. Assess hover_route separately: descend vertically there only until pads are 0.055 m above the top, not to contact. Include own fingers in these visible local corridor assessments; unknown is not clear. Report any established obstruction, not a claim about hidden clearance.", fields, ["t0", "t1", "t2", "t3", "s0", "s1", "s2"], {"state": brief(start), "own_geometry": start["own_geometry"], "stage": "pick only"})
        require(p["identity"] == "cream_cheese_box" and p["resting"] == "on_table", "Package identity or support unresolved", "Plan top-down contact", {"identity": p["identity"], "resting": p["resting"]})
        top = plain(geo.plane([pts["t" + str(i)]["world_m"] for i in range(4)]))
        table = plain(geo.plane([pts["s" + str(i)]["world_m"] for i in range(3)]))
        # These are geometry heuristics, not sensor confidence intervals or task constraints.
        for label, fit in [("top", top), ("table", table)]:
            spread = min(fit["in_plane_spread_m"])
            require(fit["coefficients"][2] >= 0.985 and fit["rms_m"] <= 0.0015 and spread > 4 * fit["rms_m"] + 0.0005, "Planar measurement quality: " + label, "Compute a local grasp plane", {"fit": fit, "normal_z_min": 0.985, "rms_max_m": 0.0015, "normal_z_margin": fit["coefficients"][2] - 0.985, "rms_margin_m": 0.0015 - fit["rms_m"], "spread_minus_noise_margin_m": spread - 4 * fit["rms_m"] - 0.0005, "frame_id": frame})
        corners = np.array([api.plane_point(p["top_camera"], uv, top["coefficients"])["world_m"] for uv in p["corners"]])
        center = np.mean(corners, axis=0)
        edges = np.roll(corners, -1, axis=0) - corners
        lengths = np.linalg.norm(edges[:, :2], axis=1)
        ux = max(uncertainty(pts["t" + str(i)]) - 0.001 for i in range(4))
        orth = abs(float(np.dot(edges[0, :2], edges[1, :2]) / (lengths[0] * lengths[1])))
        require(min(lengths) > 4 * ux and orth < 0.20 and abs(float(lengths[0] - lengths[2])) <= 4 * ux and abs(float(lengths[1] - lengths[3])) <= 4 * ux, "Rectangular boundary geometry unresolved", "Choose short-side contact", {"edge_lengths_m": lengths.tolist(), "pixel_allowance_m": ux, "orthogonality_defect": orth, "orthogonality_limit": 0.20, "minimum_edge_margin_m": float(min(lengths) - 4 * ux), "opposite_edge_allowance_m": 4 * ux, "orthogonality_margin": 0.20 - orth, "opposite_edge_margins_m": [4 * ux - abs(float(lengths[0] - lengths[2])), 4 * ux - abs(float(lengths[1] - lengths[3]))], "frame_id": frame})
        axis_index = 0 if lengths[0] >= lengths[1] else 1
        axis = edges[axis_index, :2] - edges[(axis_index + 2) % 4, :2]
        if float(np.dot(axis, geo.rotation(start["tcp_quaternion_xyzw"])[:2, 0])) < 0:
            axis = -axis
        yaw = math.atan2(float(axis[1]), float(axis[0]))
        quat = api.compose([1.0, 0.0, 0.0, 0.0], [0.0, 0.0, yaw])
        own = start["own_geometry"]
        rot = geo.rotation(quat)
        transform = np.eye(4)
        transform[:3, :3], transform[:3, 3] = rot, -rot @ np.array(own["pad_center_in_tool_m"])
        lo, hi = own["finger_low_offset_tool_m"], own["finger_high_offset_tool_m"]
        vertices = [[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]]
        finger_low = float(min(geo.transform(vertices, transform)[:, 2]))
        half_pad_height = float(np.dot(np.abs(rot[2]), np.array(own["pad_extent_in_tool_m"])) / 2)
        table_high = float(max(plane_z(table["coefficients"], c[:2]) for c in corners))
        top_low = float(min(corners[:, 2]))
        uz = 0.001 + top["rms_m"] + table["rms_m"]
        clearance = uz + 0.004
        contact_z = max(top_low - 0.75 * half_pad_height, table_high - finger_low + clearance)
        overlap = min(contact_z + half_pad_height, top_low) - max(contact_z - half_pad_height, table_high)
        vertical_margin = overlap - uz - 0.0015 - 0.003
        ref.update({"frame_id": frame, "identity": "cream cheese rectangular package", "top_plane": top, "table_plane": table, "corners_world_m": corners.tolist(), "corner_pixels": p["corners"], "corner_camera": p["top_camera"], "center_world_m": center.tolist(), "long_side_m": float(max(lengths)), "short_side_m": float(min(lengths)), "top_to_table_height_m": float(center[2] - plane_z(table["coefficients"], center[:2])), "xy_allowance_m": ux, "vertical_allowance_m": uz, "quaternion_xyzw": quat, "contact_pad_z_m": contact_z, "finger_low_relative_to_pad_m": finger_low, "finger_table_clearance_m": clearance, "pad_side_overlap_m": overlap, "contact_overlap_margin_m": vertical_margin, "provenance": "Visible depth planes, identified projected top boundary, measured own geometry. Pixel/depth allowances and contact margins are operational heuristics."})
        api.checkpoint("pick_reference", ref)
        require(vertical_margin > 0, "Insufficient side contact above tabletop", "Descend to contact", {"overlap_m": overlap, "vertical_allowance_m": uz, "position_tolerance_m": 0.0015, "minimum_usable_overlap_m": 0.003, "residual_margin_m": vertical_margin, "finger_low_relative_pad_m": finger_low, "contact_pad_z_m": contact_z, "table_high_m": table_high, "top_low_m": top_low, "frame_id": frame})
        require(p["hover_route"] != "obstructed", "Established hover obstruction", "Approach the package", {"review_reason": p["reason"]}, "needs_replan")
        require(p["high_route"] == "clear", "High approach not admitted", "High translation and orientation", {"high_route": p["high_route"], "review_reason": p["reason"]})
        go([float(center[0]), float(center[1]), float(geo.pad_position(start)[2])], quat, "open", "high approach", 0.005, 0.02, 30)
        if p["hover_route"] != "clear":
            hp, unused, hf = observe("From the changed current views, assess ONLY the vertical approach above the identified package to a pad center 0.055 m above its top. Include the open fingers, not just the TCP. No contact is authorized yet.", {"hover_route": ["clear", "obstructed", "unknown"], "reason": "string"}, [], ref)
            require(hp["hover_route"] == "clear", "Hover corridor unresolved", "Descend to observation hover", {"frame_id": hf, "review": hp})
        hover = [float(center[0]), float(center[1]), float(max(corners[:, 2]) + 0.055)]
        go(hover, quat, "open", "observation hover", 0.003, 0.015, 20)
        hp, hpts, hf = observe("Check the same package after the noncontact approach. Request center on its geometric upper-face center and support on nearby tabletop. Decide unchanged from the saved box geometry; contact_route authorizes ONLY vertical descent to the supplied pad target; jaw_fit asks whether the currently open fingers can visibly straddle the short sides at this orientation. Assess table/finger clearance and nearby objects. Do not require retention before closing.", {"unchanged": ["yes", "shifted", "unknown"], "contact_route": ["clear", "obstructed", "unknown"], "jaw_fit": ["fits", "does_not_fit", "unknown"], "reason": "string"}, ["center", "support"], ref)
        require(hp["unchanged"] == "yes" and hp["contact_route"] == "clear" and hp["jaw_fit"] == "fits", "Contact action not admitted", "Descent and one closure attempt", {"parameters": hp, "frame_id": hf}, "needs_replan" if hp["unchanged"] == "shifted" or hp["contact_route"] == "obstructed" or hp["jaw_fit"] == "does_not_fit" else "blocked")
        fresh_center = np.array(hpts["center"]["world_m"])
        xy_error = float(np.linalg.norm(fresh_center[:2] - center[:2]))
        top_error = abs(float(np.dot(top["coefficients"][:3], fresh_center) + top["coefficients"][3]))
        support_error = abs(float(np.dot(table["coefficients"][:3], hpts["support"]["world_m"]) + table["coefficients"][3]))
        require(xy_error <= max(0.006, 2 * ux) and top_error <= uz + 0.002 and support_error <= uz + 0.002, "Reference validation failed", "Descend using historical box geometry", {"xy_error_m": xy_error, "xy_limit_m": max(0.006, 2 * ux), "top_plane_error_m": top_error, "support_plane_error_m": support_error, "plane_error_limit_m": uz + 0.002, "residual_margins_m": [max(0.006, 2 * ux) - xy_error, uz + 0.002 - top_error, uz + 0.002 - support_error], "frame_id": hf}, "needs_replan")
        ref["validated_frame_id"], ref["fresh_center"], ref["fresh_support"] = hf, hpts["center"], hpts["support"]
        api.checkpoint("pick_reference", ref)
        target = [float(center[0]), float(center[1]), contact_z]
        go(target, quat, "open", "contact descent", 0.0015, 0.007, 12)
        require(api.state()["budgets"]["jev_remaining"] >= 10 and api.state()["budgets"]["native_steps_remaining"] >= 30, "Insufficient contact-test budget", "Close and perform one lift test", {"runtime_budgets": api.state()["budgets"], "required_calls": 10, "required_steps": 30, "call_margin": api.state()["budgets"]["jev_remaining"] - 10, "step_margin": api.state()["budgets"]["native_steps_remaining"] - 30})
        require(reviews[0] <= 6 and api.state()["budgets"]["gpt_remaining"] >= 31, "Insufficient observation budget before contact", "Close, measure a baseline, and verify a lift", {"stage_reviews_used": reviews[0], "remaining_runtime_gpt": api.state()["budgets"]["gpt_remaining"], "required_runtime_gpt_including_reserve": 31, "margin_calls": api.state()["budgets"]["gpt_remaining"] - 31})
        for dwell in range(2):
            r = api.control(target, quat, "close", questions, features={"phase": "One closure attempt; two three-step settling deliveries, no reopening or retry.", "retention": "not yet tested", "pad_side_overlap_m": ref["pad_side_overlap_m"], "finger_table_clearance_m": ref["finger_table_clearance_m"]}, tool_point="pad_center", translation_limit=0.001, rotation_limit=0.02, steps=3, position_tolerance=0.0015, rotation_tolerance=0.03)
            api.checkpoint("pick_progress", {"phase": "closure dwell", "dwell": dwell, "state": brief(api.state()), "receipt_status": r["status"]})
            require(r["status"] != "stalled" and r["choices"]["gripper"] == "close" and r["position_error_m"] <= 0.004, "Closure pose or command failure", "Continue the single contact attempt", {"status": r["status"], "position_error_m": r["position_error_m"], "position_limit_m": 0.004, "pose_margin_m": 0.004 - r["position_error_m"], "choices": r["choices"]})
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
        require(reviews[0] < 8 and api.state()["budgets"]["gpt_remaining"] >= 30, "Insufficient effect-verification budget", "Execute the test lift", {"stage_reviews_used": reviews[0], "remaining_runtime_gpt": api.state()["budgets"]["gpt_remaining"], "required_runtime_gpt_including_reserve": 30, "margin_calls": api.state()["budgets"]["gpt_remaining"] - 30})
        lifted_target = np.array(geo.pad_position(before))
        lifted_target[2] += lift
        after = go(lifted_target.tolist(), quat, "close", "differential lift test", 0.002, 0.008, 0)
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
        handoff.update({"retained_lift_test_passed": True, "current_frame_id": ef, "gripper_command": "close", "package_dimensions_from_frame": frame, "package_long_short_height_m": [ref["long_side_m"], ref["short_side_m"], ref["top_to_table_height_m"]], "references": {"pick_reference": "Initial visible package and support geometry, own-finger bounds, revalidated at hover.", "pick_test": "Post-closure landmark identities and actual hand baseline.", "pick_result": "Fresh differential lift proof and current visible obstacle samples.", "pick_progress": "Last acknowledged physical phase.", "pick_gate": "Only exists if a gate failed."}, "next_stage_assumptions": "Box is rigid; tested local retention is not a guarantee for arbitrary motion. Revalidate attachment, bowl opening, placement fit, and carrying corridor. Obstacle samples are current visible heights/locations, not complete bounds or hidden clearance. No transfer or release was performed."})
        return {"stage_status": "stage_complete", "reason": "Fresh package motion agrees with actual hand motion and the package is visibly clear of the table.", "evidence": effect, "handoff": handoff, "completion_proposed": False}
    except Exception as exc:
        if not failure:
            failure.update({"gate": "Runtime or measurement failure", "prevented_action": "Further pick motion", "detail": str(exc), "state": brief(api.state()), "stage_status": "blocked"})
            api.checkpoint("pick_gate", failure)
        handoff["last_acknowledged_state"] = brief(api.state())
        handoff["recovery_requirement"] = "Inspect written checkpoints and fresh views. Preserve the actual gripper state; do not repeat contact or open blindly."
        return {"stage_status": failure["stage_status"], "reason": str(exc), "evidence": {"failure": failure, "recent_progress": logs[-4:]}, "handoff": handoff, "completion_proposed": False}

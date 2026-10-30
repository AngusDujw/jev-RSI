def main(api):
    key = "grasp_direct_v4"
    m = {"phase": "validate_entry", "calls": 0, "pending": None, "alternative_measurements": 0}
    start = api.state()
    questions = {}
    for a in ["x", "y", "z", "rx", "ry", "rz"]:
        questions[a] = {"type": "choice", "instructions": "For this world " + ("translation" if len(a) == 1 else "rotation-vector") + " component, read state.processed_features.axes." + a + ".goal_relation. Choose negative for decrease, positive for increase, and hold for within_tolerance. Geometry and object effects are not yours to infer.", "criteria": {"negative": "Decrease this world component.", "hold": "This component is within tolerance.", "positive": "Increase this world component."}}
    questions["gripper"] = {"type": "choice", "instructions": "Read state.processed_features.objective.gripper and deliver that command exactly. Keep preserves the previous command, including a previous close; it never means reopen.", "criteria": {"open": "Deliver requested opening.", "close": "Deliver requested closing.", "keep": "Preserve the existing command."}}

    def save():
        m["last_state"] = api.state()
        api.checkpoint(key, m)

    def stop(reason, status="blocked"):
        m["return_status"] = status
        raise Exception(reason)

    def finish(status, reason):
        m["reason"] = reason
        save()
        return {"stage_status": status, "reason": reason, "evidence": {n: m.get(n) for n in ["phase", "inherited_execution", "tracker_diagnosis", "reference", "last_observation", "measurement_gap", "geometry", "candidate", "actual_contact_margins", "close_delivered", "attachment_tests", "last_receipt", "pending", "last_state"]}, "handoff": {"checkpoint_keys": ["grasp_recovery_v3", key], "phase": m["phase"], "pending": m.get("pending"), "target_pad_world_m": m.get("target_pad_world_m"), "target_quaternion_xyzw": m.get("target_quaternion_xyzw"), "objective_gripper": m.get("objective_gripper"), "package_marks_in_tool_m": m.get("package_marks_in_tool_m"), "reference_rules": "World meters, tool-to-world xyzw quaternions, image pixels with top-left origin. grasp_recovery_v3 preserves the frame-54 boundary, side and table evidence and rejected tracker histories. grasp_direct_v4 preserves independently named material landmarks, exact depth records and frames, measured contact bounds, actual intents/receipts, closure delivery and any lift tests. Its reference labels identify physical printed marks, not image quadrants. Boundary dimensions remain frame-54 observations; a rigid rectangular package and locally stationary table are explicit models, not hidden-surface measurements. Trackers patch_1 and patch_2 remain rejected for insufficient second spread; neither is used as accepted pose or retention evidence. Reacquire affected references before continuing from any yield. Preserve the actual gripper command, particularly after close_delivered. Never replay an unreceipted intent or an acknowledged closure. An interrupted lift is not a failed grasp and does not authorize opening. Only two successful fresh lift/attachment tests permit this method's stage_complete; no bowl alignment, deposit or release is performed."}, "completion_proposed": False}

    def finger_geometry(s):
        own, R = s["own_geometry"], geo.rotation(s["tcp_quaternion_xyzw"])
        if float(R[2, 2]) > -0.98:
            stop("Measured tool attitude is outside the downward finite-pad model.")
        lo, hi = own["finger_low_offset_tool_m"], own["finger_high_offset_tool_m"]
        box = np.array([[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]])
        fb = float(np.min(((box - np.array(own["pad_center_in_tool_m"])) @ R.T)[:, 2]))
        h = np.array(own["pad_extent_in_tool_m"]) / 2.0
        bottom = np.array([[x, y, h[2]] for x in [-h[0], h[0]] for y in [-h[1], h[1]]]) @ R.T
        top = np.array([[x, y, -h[2]] for x in [-h[0], h[0]] for y in [-h[1], h[1]]]) @ R.T
        return fb, float(np.max(bottom[:, 2])), float(np.min(top[:, 2]))

    def candidate():
        s, g = api.state(), m["geometry"]
        fb, pb, pt = finger_geometry(s)
        low = g["table_z_m"] + 0.006 + g["allowance_m"] - fb
        high = g["top_z_m"] - g["allowance_m"] - 0.003 - pb
        c = {"frame_id": s["frame_id"], "low_pad_z_m": low, "high_pad_z_m": high, "target_pad_z_m": (low + high) / 2.0, "interval_m": high - low, "finger_bottom_relative_pad_m": fb, "common_pad_bottom_m": pb, "common_pad_top_m": pt, "required_table_clearance_m": 0.006, "required_overlap_m": 0.003, "end_reserve_m": 0.0006, "surface_allowance_m": g["allowance_m"]}
        m["candidate"] = c
        if high - low < 0.0012 or pt <= pb:
            stop("Measured finite-pad interval fails the unchanged clearance, overlap and two end reserves; no threshold was relaxed.")
        return c

    fields = {"identity": ["same_cream_cheese", "wrong", "unknown"], "marks_identified": ["four_distinct", "same_four", "ambiguous", "unavailable"], "labels": {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "string", "maxLength": 240}}, "support": ["flat_on_table", "clear_of_table", "other", "unknown"], "gripper": ["empty_open", "straddling_open", "opposing_contacts", "other", "unknown"], "route": ["visible_clear", "obstructed", "unknown"], "passages": ["both_visible", "obstructed", "unknown"], "slip": ["none_visible", "visible", "unknown"]}

    def observe(mode, action):
        names, cache, gap = ["p0", "p1", "p2", "p3", "s0", "s1", "s2"], {}, ""
        first = "reference" not in m
        for attempt in range(2):
            if attempt:
                if m["alternative_measurements"] >= 2:
                    break
                m["alternative_measurements"] += 1
            if api.state()["budgets"]["gpt_remaining"] < 3:
                stop("Reserve observation budget for supervision; current evidence is checkpointed.", "yield")
            question = "Current grasp stage only. " + action + " Request depth points p0,p1,p2,p3 on four uniquely identifiable printed material landmarks of the SAME cream cheese top, and s0,s1,s2 on separated bare local TABLE patches, including the finger approach area. Use whichever current camera genuinely sees each landmark. Table points must be noncollinear and distributed, not bowl, robot or stove. "
            question += ("Choose and describe an initial quartet spread in TWO world directions, preferably in the half toward the short end with larger world x so it can remain observable near the hand. Aim for spans above 24 mm and 18 mm, not four points along one letter. Use exact printed tips/intersections, not arbitrary unmarked interior pixels or mixed-depth silhouette corners. labels must describe p0 through p3 in order. " if first else "Reidentify precisely the stored four physical print landmarks, with the same p0 through p3 identities. Do not substitute different marks or image quadrants. Historical projections are only hypotheses. Return the stored label descriptions. ")
            question += "Report only current visible evidence. passages concerns the two bare descent passages beside the package, not invented hidden wall surfaces. route excludes intended package contact but must include nearby bowl, bottle and table obstacles. If retrying, use the other camera or a genuinely different depth-valid patch for a table point, not the same failed measurement. On initial selection only, a rejected quartet may be replaced as a whole before a reference is established."
            r = api.review(question, context={"mode": mode, "reference": m.get("reference"), "frame54_geometry": m["frame54_geometry"], "candidate": m.get("candidate"), "state": api.state(), "gap": gap, "retained_same_frame_points": cache}, fields=fields)
            p, errors = r["parameters"], [e["name"] for e in r["measurement_errors"]]
            m["last_review"] = {"frame_id": r["frame_id"], "parameters": p, "measurement_errors": r["measurement_errors"], "explanation": r["explanation"][:600]}
            if r["status"] == "stop":
                stop("Fresh observation requested a stop: " + r["explanation"][:500], "abort")
            if p["identity"] == "wrong":
                stop("Fresh observation contradicts package identity.", "needs_replan")
            if first:
                cache = {}
            for n in names:
                if n in r["points"] and n not in errors and r["points"][n]["frame_id"] == r["frame_id"]:
                    cache[n] = r["points"][n]
            m["partial_measurements"] = {"frame_id": r["frame_id"], "points": cache, "parameters": p}
            save()
            if r["frame_id"] != api.state()["frame_id"] or p["identity"] != "same_cream_cheese" or p["marks_identified"] != ("four_distinct" if first else "same_four") or not all(n in cache for n in names):
                gap = "Missing current depth-valid points or unambiguous physical landmark correspondences."
                continue
            try:
                P = np.array([cache[n]["world_m"] for n in names[:4]])
                S = np.array([cache[n]["world_m"] for n in names[4:]])
                ft, fs = geo.plane(P), geo.plane(S)
                if min(ft["in_plane_spread_m"]) < 0.006 or min(fs["in_plane_spread_m"]) < 0.015 or max(ft["rms_m"], fs["rms_m"]) > 0.0015 or float(np.ptp(S[:, 2])) > 0.003:
                    raise ValueError("Independent landmarks/table samples fail unchanged distributed support or plane margins.")
                if abs(float(np.mean(S[:, 2])) - m["frame54_geometry"]["table_z_m"]) > 0.002:
                    raise ValueError("Fresh table samples disagree with the stationary local support reference.")
                if mode not in ["lift_one", "lift_two"] and (float(np.ptp(P[:, 2])) > 0.003 or ft["coefficients"][2] < 0.98):
                    raise ValueError("Pre-lift top measurements do not support the flat-package model.")
            except Exception as error:
                gap = str(error)
                m["rejected_measurements"] = m["partial_measurements"]
                cache = {}
                continue
            obs = {"frame_id": r["frame_id"], "mode": mode, "parameters": p, "point_records": cache, "points": P.tolist(), "top_fit": ft, "table_fit": fs, "table_z_m": float(np.mean(S[:, 2]))}
            m["last_observation"] = obs
            m.pop("partial_measurements", None)
            m.pop("measurement_gap", None)
            save()
            return obs
        m["measurement_gap"] = gap
        stop(gap or "No different valid measurement remains within this slice.")

    def flat_update(obs):
        if obs["parameters"]["support"] != "flat_on_table":
            stop("Current support does not confirm the pre-lift flat-package premise.", "needs_replan")
        P, ref = np.array(obs["points"]), np.array(m["reference"]["points"])
        delta = P - ref
        drift = float(np.max(np.linalg.norm(delta, axis=1)))
        if drift > 0.004 or float(np.max(np.linalg.norm(delta - np.mean(delta, axis=0), axis=1))) > 0.002:
            stop("Independent physical landmarks show unexpected package motion or inconsistent correspondences; do not repeat contact.", "needs_replan")
        g = m["geometry"]
        g["center_world_m"] = (np.array(m["frame54_geometry"]["top_center_world_m"]) + np.mean(delta, axis=0)).tolist()
        g["top_z_m"], g["table_z_m"] = float(np.mean(P[:, 2])), obs["table_z_m"]
        g["allowance_m"] = max(g["allowance_m"], 0.001, 3.0 * obs["top_fit"]["rms_m"], 3.0 * obs["table_fit"]["rms_m"], float(np.ptp(P[:, 2])) / 2.0)
        g["validated_frame_id"], g["maximum_material_mark_drift_m"] = obs["frame_id"], drift
        return candidate()

    def motion(target, quaternion, phase, limit=0.02, tolerance=0.003, command="keep", single=False):
        m["phase"], m["target_pad_world_m"], m["target_quaternion_xyzw"], m["objective_gripper"] = phase, target, quaternion, command
        for unused in range(22):
            s = api.state()
            if m["calls"] >= 22 or s["native_steps"] - start["native_steps"] + 3 > 66 or s["budgets"]["jev_remaining"] < 1 or s["budgets"]["native_steps_remaining"] < 3:
                stop("Control slice exhausted after acknowledged progress; continue from the saved actual phase, not the old hover.", "yield")
            m["pending"] = {"phase": phase, "before_frame_id": s["frame_id"], "target_pad_world_m": target, "quaternion_xyzw": quaternion, "gripper": command}
            save()
            receipt = api.control(target, quaternion, command, questions, features={"source": "Independent GPT-identified RGB-D material points, visible passage review, frame-54 boundary model and measured own finger geometry; rejected tracker transforms are unused.", "phase": phase, "geometry": m["geometry"], "candidate": m.get("candidate"), "observation_frame_id": m.get("last_observation", {}).get("frame_id"), "retention_not_inferred_from_closure": True}, tool_point="pad_center", translation_limit=limit, rotation_limit=0.03, steps=3, position_tolerance=tolerance, rotation_tolerance=0.01)
            m["calls"] += 1
            m["last_receipt"], m["pending"] = receipt, None
            if receipt["choices"]["gripper"] == "close":
                m["close_delivered"] = True
            save()
            if receipt["choices"]["gripper"] != command:
                stop("Acknowledged gripper delivery mismatched the requested command.")
            delta = np.array(receipt["target_tcp"]) - np.array(receipt["before"])
            for i, a in enumerate(["x", "y", "z"]):
                if abs(float(delta[i])) > tolerance / math.sqrt(3) and ((delta[i] > 0 and receipt["choices"][a] == "negative") or (delta[i] < 0 and receipt["choices"][a] == "positive")):
                    stop("Acknowledged translation direction opposed the target; no retry.")
            if receipt["status"] == "stalled":
                stop("First translation stall; stop rather than repeat a possible contact.")
            s = api.state()
            clearance = float(geo.pad_position(s)[2]) + finger_geometry(s)[0] - m["geometry"]["table_z_m"] - m["geometry"]["allowance_m"]
            m["measured_finger_table_clearance_m"] = clearance
            if clearance < 0.006:
                stop("Measured own-finger/table clearance fell below the unchanged 6 mm margin.")
            if receipt["status"] == "reached" or single:
                return
        stop("Local control bound reached with its acknowledged pose saved.", "yield")

    def check_route(obs, grippers):
        p = obs["parameters"]
        if p["gripper"] not in grippers or p["route"] != "visible_clear" or p["passages"] != "both_visible":
            stop("Current images do not establish the required empty/straddling gripper and visible local passages. No hidden clearance is assumed.")

    try:
        for record in api.recall():
            if record["key"] == key:
                m = api.recall(key)["value"]
                stop("This slice already has an execution record. Continue its saved phase in a revised method; do not replay approach or closure.", "yield")
        old = api.recall("grasp_recovery_v3")["value"]
        if old.get("pending") or old["last_state"]["native_steps"] != start["native_steps"] or old["geometry"]["reference_frame_id"] != start["frame_id"] or start["last_gripper_command"] != "open":
            stop("Actual entry does not match the acknowledged frame-54 open hover; reconcile execution without reopening.")
        g = old["geometry"]
        m["inherited_execution"] = {"frame_id": start["frame_id"], "native_steps": start["native_steps"], "last_receipt": old["receipt"], "closure_acknowledged": False, "source_checkpoint": "grasp_recovery_v3"}
        m["tracker_diagnosis"] = {"handle": old["tracker"]["handle"], "registration": old["registration"], "use": "Rejected, not relaxed or reinitialized. Narrow automatic texture support is replaced by independent named depth correspondences."}
        m["frame54_geometry"] = {n: g[n] for n in ["reference_frame_id", "top_corners_world_m", "top_center_world_m", "top_z_m", "table_z_m", "width_m", "length_m", "long_axis_world", "side", "side_valid"]}
        if not g["side_valid"]:
            stop("The inherited visible long-side measurement is not valid.")
        m["geometry"] = {"center_world_m": g["top_center_world_m"], "top_z_m": g["top_z_m"], "table_z_m": g["table_z_m"], "allowance_m": g["surface_allowance_m"], "validated_frame_id": start["frame_id"], "width_m": g["width_m"], "length_m": g["length_m"]}
        q = start["tcp_quaternion_xyzw"]
        candidate()
        obs = observe("initial", "Assess ONLY a vertical open-gripper approach centered over the measured package to a pad height 25 mm above its top, without touching it. Confirm empty open fingers and visible free external passages with at least 10 mm separation from other objects.")
        check_route(obs, ["empty_open", "straddling_open"])
        P = np.array(obs["points"])
        d = np.array(g["long_axis_world"])
        v = np.array([-d[1], d[0], 0.0])
        relative = P - np.array(g["top_center_world_m"])
        if max(abs(float(x)) for x in relative @ d) > g["length_m"] / 2.0 - 0.001 or max(abs(float(x)) for x in relative @ v) > g["width_m"] / 2.0 - 0.001 or float(np.max(np.abs(P[:, 2] - g["top_z_m"]))) > 0.002:
            stop("Selected material points do not lie safely inside the independently measured package top.")
        m["reference"] = {"frame_id": obs["frame_id"], "labels": obs["parameters"]["labels"], "points": obs["points"], "identity": "Four individually named printed landmarks on the same cream cheese top; not a tracker or arbitrary pixel samples."}
        c = flat_update(obs)
        target = list(m["geometry"]["center_world_m"])
        target[2] = max(m["geometry"]["top_z_m"] + 0.025, c["target_pad_z_m"] + 0.020)
        motion(target, q, "approach_precontact")
        obs = observe("precontact", "Reacquire the same four marks and table AFTER the approach. Assess only the remaining vertical open-finger descent to the recomputed finite-pad contact height. Both finger passages beside the package must be visible and clear of other objects; no closure is requested yet.")
        check_route(obs, ["empty_open", "straddling_open"])
        c = flat_update(obs)
        target = list(m["geometry"]["center_world_m"])
        target[2] = c["target_pad_z_m"]
        motion(target, q, "descend_to_grasp_height", limit=0.008, tolerance=0.0005)
        obs = observe("at_contact_height", "Reacquire the SAME marks and table at the actual low pose. Are the still-open fingers visibly straddling the two long sides at the intended contact site, with clear closing passages except for intentional package contact? Do not call this a grasp.")
        check_route(obs, ["straddling_open"])
        c = flat_update(obs)
        s, g = api.state(), m["geometry"]
        pad = np.array(geo.pad_position(s))
        fb, pb, pt = finger_geometry(s)
        clearance = float(pad[2]) + fb - g["table_z_m"] - g["allowance_m"]
        overlap = min(g["top_z_m"] - g["allowance_m"], float(pad[2]) + pt) - max(g["table_z_m"] + g["allowance_m"], float(pad[2]) + pb)
        m["actual_contact_margins"] = {"frame_id": s["frame_id"], "table_clearance_m": clearance, "common_vertical_overlap_m": overlap, "pad_z_m": float(pad[2]), "low_reserved_m": c["low_pad_z_m"] + 0.0006, "high_reserved_m": c["high_pad_z_m"] - 0.0006, "xy_error_m": float(np.linalg.norm(pad[:2] - np.array(g["center_world_m"])[:2]))}
        if clearance < 0.006 or overlap < 0.003 or not c["low_pad_z_m"] + 0.0006 <= float(pad[2]) <= c["high_pad_z_m"] - 0.0006 or m["actual_contact_margins"]["xy_error_m"] > 0.004:
            stop("Actual low-pose geometry fails a preserved contact margin; no closure was attempted.")
        grip_target, grip_q = pad.tolist(), s["tcp_quaternion_xyzw"]
        motion(grip_target, grip_q, "deliver_single_close", tolerance=0.0005, command="close", single=True)
        motion(grip_target, grip_q, "allow_closure_delivery", tolerance=0.0005, single=True)
        obs = observe("closed", "Observe the result of the single close and brief keep. Reidentify the same material marks; report whether opposing fingers visibly contact the package rather than the table. Assess the visible local vertical route for a 25 mm diagnostic lift. Closure alone is not retention.")
        flat_update(obs)
        if obs["parameters"]["gripper"] != "opposing_contacts" or obs["parameters"]["route"] != "visible_clear":
            stop("Closure is delivered but opposed package contact or the diagnostic lift route is unconfirmed. Preserve the gripper; do not reopen or reclose.")
        m["attachment_tests"] = []
        for index, dz in enumerate([0.025, 0.018]):
            before, points_before = api.state(), obs["points"]
            m["lift_baseline"] = {"state": before, "points": points_before, "frame_id": obs["frame_id"], "lift_index": index}
            target = np.array(geo.pad_position(before))
            target[2] += dz
            motion(target.tolist(), grip_q, "diagnostic_lift_" + str(index + 1), limit=0.015, tolerance=0.0015)
            obs = observe("lift_one" if index == 0 else "lift_two", "Inspect the actual lifted package, not the commanded pose. Reidentify all four material marks. Is the package visibly clear of the table and still between opposing fingers with no visible slipping relative to the preceding view? For the first lift only, also assess the remaining 18 mm vertical confirmation route. Do not infer a hidden bottom or use closure as grasp evidence.")
            after, P = api.state(), np.array(obs["points"])
            error = float(geo.attachment_error(points_before, obs["points"], before, after))
            mark_rise = float(np.min(P[:, 2] - np.array(points_before)[:, 2]))
            hand_rise = float(geo.pad_position(after)[2] - geo.pad_position(before)[2])
            test = {"before_frame_id": before["frame_id"], "after_frame_id": after["frame_id"], "attachment_error_m": error, "minimum_material_mark_rise_m": mark_rise, "measured_pad_rise_m": hand_rise, "visual": obs["parameters"]}
            m["attachment_tests"].append(test)
            save()
            p = obs["parameters"]
            if error > 0.005 or mark_rise < (0.015 if index == 0 else 0.010) or hand_rise < (0.018 if index == 0 else 0.012) or p["support"] != "clear_of_table" or p["gripper"] != "opposing_contacts" or p["slip"] != "none_visible":
                stop("Fresh lift measurements do not establish rigid following and visible table separation. Preserve the observed state; do not repeat the grasp.", "needs_replan")
            if index == 0 and p["route"] != "visible_clear":
                stop("First lift passed, but the remaining confirmation route is not visibly established.")
        T = np.eye(4)
        T[:3, :3], T[:3, 3] = geo.rotation(after["tcp_quaternion_xyzw"]), np.array(after["tcp_position_world_m"])
        m["package_marks_in_tool_m"] = geo.transform(obs["points"], np.linalg.inv(T)).tolist()
        m["phase"] = "grasp_verified"
        return finish("stage_complete", "Two fresh, independently measured lifts show the same distributed package marks following the measured hand, visible table separation and no apparent slip. Only the grasp stage is complete.")
    except Exception as error:
        return finish(m.pop("return_status", "blocked"), str(error))

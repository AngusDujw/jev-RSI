def main(api):
    key, m, calls = "grasp_stage_v2", {}, [0]
    slice_start = api.state()["native_steps"]
    questions = {}
    for a in ["x", "y", "z", "rx", "ry", "rz"]:
        subject = "world translation " + a if len(a) == 1 else "world rotation-vector component " + a
        questions[a] = {"type": "choice", "instructions": "For " + subject + ", use state.processed_features.axes." + a + ".goal_relation. Choose negative for decrease, positive for increase, hold for within_tolerance. Do not infer scene geometry.", "criteria": {"negative": "Decrease this world component.", "hold": "This component is within tolerance.", "positive": "Increase this world component."}}
    questions["gripper"] = {"type": "choice", "instructions": "Deliver state.processed_features.objective.gripper exactly. Keep preserves the previous command; it does not reopen. Closing is not proof of retention.", "criteria": {"open": "Requested opening.", "close": "Requested closing.", "keep": "Preserve the existing command."}}

    def save():
        m["last_state"], m["slice_calls"] = api.state(), calls[0]
        api.checkpoint(key, m)

    def stop(reason, status="blocked"):
        m["return_status"] = status
        raise Exception(reason)

    def finish(status, reason):
        save()
        return {"stage_status": status, "reason": reason, "evidence": {"phase": m.get("phase"), "audit": m.get("audit"), "contact_model": m.get("model"), "actual_contact": m.get("actual_contact"), "last_receipt": m.get("receipt"), "tracking": m.get("track"), "retention": m.get("retention"), "effect": m.get("effect"), "recent_observations": m.get("observations"), "error": m.get("error"), "state": m["last_state"]}, "handoff": {"checkpoint_keys": ["grasp_stage_v1", key], "phase": m.get("phase"), "pending_action": m.get("pending"), "tracker": m.get("tracker"), "package_top_center_in_tool_m": m.get("top_center_in_tool_m"), "reference_rules": "World meters, tool quaternions xyzw, image pixels scoped to recorded camera/frame. grasp_stage_v1 retains the original measured top/table patches and rejected center-only candidate. grasp_stage_v2 stores their validated provenance, finite-pad clearance audit, reference top corners/samples, current contact measurements, tracker identity, acknowledged actions, and prelift_state/prelift_transform baseline. Reacquire tracker and validate affected surfaces after movement. Geometry is a visible top/side model, not a measured hidden solid or bowl model. Preserve current gripper command; no automatic reopening. Only effect and retention jointly establish the current grasp stage."}, "completion_proposed": False}

    def measured(r, names):
        return all(n in r["points"] for n in names) and not any(e["name"] in names for e in r["measurement_errors"])

    def review(question, context, fields):
        if api.state()["budgets"]["gpt_remaining"] < 2:
            stop("Insufficient observation budget; preserve the current physical state.", "yield")
        r = api.review(question, context=context, fields=fields)
        m["observations"] = (m.get("observations", []) + [{"frame_id": r["frame_id"], "parameters": r["parameters"], "points": r["points"], "measurement_errors": r["measurement_errors"], "explanation": r["explanation"]}])[-2:]
        save()
        if r["status"] == "stop":
            stop("Fresh reviewer requested stop: " + r["explanation"], "abort")
        return r

    def contact_model(s, q):
        g, own, R = m["geometry"], s["own_geometry"], geo.rotation(q)
        if float(R[2, 2]) > -0.98:
            stop("This candidate requires a near-downward tool; no tilted-contact extrapolation.")
        lo, hi, pc = own["finger_low_offset_tool_m"], own["finger_high_offset_tool_m"], np.array(own["pad_center_in_tool_m"])
        box = np.array([[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]])
        finger_bottom = float(np.min(((box - pc) @ R.T)[:, 2]))
        h = np.array(own["pad_extent_in_tool_m"]) / 2.0
        lower = np.array([[x, y, h[2]] for x in [-h[0], h[0]] for y in [-h[1], h[1]]]) @ R.T
        upper = np.array([[x, y, -h[2]] for x in [-h[0], h[0]] for y in [-h[1], h[1]]]) @ R.T
        pb, pt = float(np.max(lower[:, 2])), float(np.min(upper[:, 2]))
        zt, zs, u = g["contact_top_z_m"], g["contact_table_z_m"], g["surface_allowance_m"]
        low, high = zs + 0.006 + u - finger_bottom, zt - u - 0.003 - pb
        return {"finger_bottom_relative_to_pad_m": finger_bottom, "common_pad_bottom_relative_m": pb, "common_pad_top_relative_m": pt, "minimum_pad_center_z_m": low, "maximum_pad_center_z_m": high, "feasible_interval_m": high - low, "target_z_m": (low + high) / 2.0, "required_table_clearance_m": 0.006, "required_vertical_overlap_m": 0.003, "surface_allowance_m": u, "pose_reserve_each_end_m": 0.0006}

    def track(mode):
        t = api.track_update(m["tracker"]["handle"])
        if t["status"] != "tracked":
            m["track"] = t
            stop("Same-package patch registration is unknown in both-view search; no extrapolated contact or lift.")
        names = ["frame_id", "reference_frame_id", "camera", "matches", "inliers", "rms_m", "inlier_spread_m", "uncertainty_floor_m", "transform_initial_world_to_current_world"]
        m["track"] = {n: t[n] for n in names}
        spread = sorted(t["inlier_spread_m"])
        if t["reference_frame_id"] != m["tracker"]["reference_frame_id"] or t["inliers"] < 12 or t["inliers"] / max(1, t["matches"]) < 0.60 or t["rms_m"] > 0.002 or t["uncertainty_floor_m"] > 0.003 or len(spread) < 2 or spread[-2] < 0.006:
            stop("Registration identity reference, residual, uncertainty or distributed support is inadequate.")
        pts = geo.transform(m["geometry"]["top_samples_world_m"], t["transform_initial_world_to_current_world"])
        s = api.state()
        if mode == "stationary" and float(np.max(np.linalg.norm(pts - np.array(m["geometry"]["top_samples_world_m"]), axis=1))) > 0.004:
            stop("Package moved before closure; the old approach is invalid.", "needs_replan")
        if mode == "follow":
            before = geo.transform(m["geometry"]["top_samples_world_m"], m["prelift_transform"])
            error = float(geo.attachment_error(before, pts, m["prelift_state"], s))
            m["retention"] = {"frame_id": t["frame_id"], "attachment_error_m": error, "hand_rise_m": float(geo.pad_position(s)[2] - geo.pad_position(m["prelift_state"])[2]), "package_rise_m": float(np.mean(pts[:, 2] - before[:, 2])), "registration_allowance_m": max(float(t["rms_m"]), float(t["uncertainty_floor_m"])), "source": "Measured rigid registrations of the same textured top and measured TCP motion; not closure inference."}
            if error > 0.008:
                stop("Package motion does not follow the measured hand transform within 8 mm.", "needs_replan")
        return t, pts, s

    def capacity():
        s = api.state()
        if calls[0] >= 22 or s["native_steps"] - slice_start + 3 > 66 or s["budgets"]["jev_remaining"] < 1 or s["budgets"]["native_steps_remaining"] < 3:
            stop("Local control slice exhausted; actual progress and pending phase are checkpointed.", "yield")

    def act(target, grip, limit, tolerance):
        capacity()
        m["pending"] = {"phase": m["phase"], "target_pad_world_m": target, "quaternion_xyzw": m["quaternion"], "gripper": grip, "before_state": api.state()}
        save()
        features = {"source": "Program RGB-D top/side measurements, own finger/pad geometry, accepted patch registration and typed visible-corridor reviews.", "phase": m["phase"], "contact_model": m.get("model"), "package_width_m": m["geometry"]["width_m"], "package_length_m": m["geometry"]["length_m"], "registration": m.get("track"), "retention": m.get("retention"), "meaning": "Directions and requested command only; Jev is not a sensor or an effect judge."}
        r = api.control(target, m["quaternion"], grip, questions, features=features, tool_point="pad_center", translation_limit=limit, rotation_limit=0.10, steps=3, position_tolerance=tolerance, rotation_tolerance=0.01)
        calls[0] += 1
        m["receipt"], m["pending"] = r, None
        save()
        if r["choices"].get("gripper") != grip:
            stop("Acknowledged Jev gripper choice disagrees with the requested command.")
        delta = np.array(r["target_tcp"]) - np.array(r["before"])
        for i, a in enumerate(["x", "y", "z"]):
            c = r["choices"].get(a)
            if abs(float(delta[i])) > tolerance / math.sqrt(3) and ((delta[i] > 0 and c == "negative") or (delta[i] < 0 and c == "positive")):
                stop("Acknowledged translation direction opposes the target.")
        if r["status"] == "stalled":
            stop("First stalled translation: stop without repeating contact.")
        if m["phase"] != "hover":
            s = api.state()
            cm = contact_model(s, s["tcp_quaternion_xyzw"])
            clearance = float(geo.pad_position(s)[2]) + cm["finger_bottom_relative_to_pad_m"] - m["geometry"]["contact_table_z_m"] - cm["surface_allowance_m"]
            m["last_finger_table_clearance_after_allowance_m"] = clearance
            if clearance < 0.006:
                stop("Measured post-action finger/table clearance fails the unchanged 6 mm requirement.")
        return r

    def move(target, limit, tolerance, mode):
        track(mode)
        for unused in range(22):
            r = act(target, "keep", limit, tolerance)
            track(mode)
            if r["status"] == "reached":
                return
        stop("Bounded move ended without convergence.", "yield")

    try:
        for record in api.recall():
            if record["key"] == key:
                m = api.recall(key)["value"]
        if m.get("pending"):
            return finish("blocked", "An earlier action intent lacks a saved receipt; reconcile actual acknowledged execution before continuing.")
        if not m:
            m = {"phase": "audit", "origin_frame_id": api.state()["frame_id"]}
        if m["phase"] == "complete":
            m["phase"] = "verify"
        if m["phase"] == "audit":
            old, s = api.recall("grasp_stage_v1")["value"], api.state()
            r = old.get("partial")
            names = ["t0", "t1", "t2", "t3", "s0", "s1", "s2", "s3"]
            if not r or not measured(r, names):
                stop("Original valid top/table measurements are missing; do not reconstruct them from prose.")
            if s["frame_id"] != r["frame_id"] or s["native_steps"] != old["state"]["native_steps"] or s["last_gripper_command"] != "open" or float(np.linalg.norm(np.array(s["tcp_position_world_m"]) - np.array(old["state"]["tcp_position_world_m"]))) > 0.000001:
                stop("The no-motion provenance needed to reuse frame-0 measurements no longer holds.")
            p = r["parameters"]
            if p["identity"] != "cream_cheese" or p["support"] != "flat_on_table" or p["boundary"] != "full_rectangle" or len(p["corners"]) != 4:
                stop("Original package identity or visible boundary does not support this candidate.")
            top, table = np.array([r["points"][n]["world_m"] for n in names[:4]]), np.array([r["points"][n]["world_m"] for n in names[4:]])
            ft, fs = geo.plane(top), geo.plane(table)
            if max(ft["rms_m"], fs["rms_m"]) > 0.0015 or min(ft["in_plane_spread_m"]) < 0.006 or min(fs["in_plane_spread_m"]) < 0.015 or max(float(np.ptp(top[:, 2])), float(np.ptp(table[:, 2]))) > 0.003:
                stop("Original distributed samples do not support the local horizontal models.")
            zt, zs = float(np.mean(top[:, 2])), float(np.mean(table[:, 2]))
            corners = np.array([api.plane_point(p["camera"], pixel, [0.0, 0.0, 1.0, -zt])["world_m"] for pixel in p["corners"]])
            edges = np.roll(corners, -1, axis=0) - corners
            lengths = np.linalg.norm(edges, axis=1)
            if min(lengths) < 0.020 or max(lengths) > 0.180 or not 0.012 <= zt - zs <= 0.070:
                stop("Dimensions fail the visible rectangular package model.")
            units = edges / lengths[:, None]
            if abs(float(np.dot(units[0], units[1]))) > 0.12 or float(np.dot(units[0], units[2])) > -0.98 or float(np.dot(units[1], units[3])) > -0.98 or abs(float(lengths[0] - lengths[2])) > 0.005 or abs(float(lengths[1] - lengths[3])) > 0.005:
                stop("The measured boundary is not adequately rectangular.")
            direction = edges[0] if lengths[0] >= lengths[1] else edges[1]
            if float(np.dot(direction, geo.rotation(s["tcp_quaternion_xyzw"])[:, 0])) < 0:
                direction = -direction
            m["quaternion"] = api.compose([1.0, 0.0, 0.0, 0.0], [0.0, 0.0, math.atan2(float(direction[1]), float(direction[0]))])
            center = np.mean(corners, axis=0)
            m["geometry"] = {"reference_frame_id": r["frame_id"], "source_checkpoint": "grasp_stage_v1.partial", "camera": p["camera"], "top_samples_world_m": top.tolist(), "table_samples_world_m": table.tolist(), "top_corners_world_m": corners.tolist(), "top_center_world_m": center.tolist(), "top_z_m": zt, "table_z_m": zs, "contact_top_z_m": zt, "contact_table_z_m": zs, "width_m": float(min(lengths)), "length_m": float(max(lengths)), "surface_allowance_m": max(0.001, 3.0 * float(ft["rms_m"]), 3.0 * float(fs["rms_m"]), float(np.ptp(top[:, 2])) / 2.0), "assumptions": "Observed flat package and horizontal tabletop; full own pad extents give a common contact-height band. Allowance is an engineering reserve, not calibrated confidence. No unseen package bottom or obstacle clearance is asserted."}
            cm = contact_model(s, m["quaternion"])
            m["model"] = cm
            m["audit"] = {"previous_error": "Requiring the pad CENTER below the package top ignored the finite 16 mm pad height.", "table_to_top_m": zt - zs, "old_center_only_target_z_m": max(zt - 0.006, zs + 0.006 - cm["finger_bottom_relative_to_pad_m"]), "finite_pad_candidate": cm, "motion_before_revision": "None: same frame and native-step count confirmed.", "required_clearance_unchanged_m": 0.006}
            if cm["feasible_interval_m"] < 0.0012 or cm["common_pad_top_relative_m"] <= cm["common_pad_bottom_relative_m"]:
                stop("Finite-pad candidate still lacks a clearance/overlap interval with pose reserve; this does not establish global infeasibility.")
            m["hover_target"] = [float(center[0]), float(center[1]), zt + 0.075]
            poly = np.array(p["corners"])
            poly = np.mean(poly, axis=0) + 0.78 * (poly - np.mean(poly, axis=0))
            tr = api.track_init(p["camera"], poly.tolist())
            m["tracker"] = {"handle": tr["handle"], "camera": p["camera"], "polygon": poly.tolist(), "reference_frame_id": tr["frame_id"], "identity": "Cream cheese textured top interior, not table or gripper."}
            m["phase"] = "hover"
            save()
        g = m["geometry"]
        if m["phase"] == "hover":
            r = review("This is an observation-producing free-air approach, not a grasp. Check the proposed straight pad-center transfer and yaw adjustment to hover_target using the supplied own finger envelope. Is the relevant swept route visibly free of the bowl, bottle, stove and cabinet with at least 10 mm separation? Do not certify occluded clearance. Confirm the registered top patch is still the same cream cheese and no scene displacement is apparent. The contact-height calculation now uses the finite pad face, retaining 6 mm finger/table clearance; side contact will be measured from the closer view before descent.", {"state": api.state(), "hover_target": m["hover_target"], "quaternion": m["quaternion"], "geometry": g, "audit": m["audit"]}, {"identity": ["same_package", "wrong", "unknown"], "sweep": ["visibly_clear", "obstructed", "unknown"], "scene": ["unchanged", "changed", "unknown"]})
            if r["parameters"] != {"identity": "same_package", "sweep": "visibly_clear", "scene": "unchanged"}:
                stop("Free-air approach lacks current visible identity or corridor evidence.")
            move(m["hover_target"], 0.020, 0.003, "stationary")
            m["phase"] = "descend"
            save()
        if m["phase"] == "descend":
            t, pts, s = track("stationary")
            m["quaternion"] = s["tcp_quaternion_xyzw"]
            m["model"] = contact_model(s, m["quaternion"])
            fields = {"identity": ["same_package", "wrong", "unknown"], "corridors": ["both_open_pad_corridors_visible_clear", "obstructed", "unknown"], "wall": ["continuous_long_side_at_contact_band", "not_suitable", "unknown"], "table": ["unchanged", "changed", "unknown"]}
            for attempt in range(2):
                r = review("From the closer views, assess only the remaining open descent. Are the actual open pads outside the package's opposite LONG side walls, with both downward side corridors visibly clear? Do not infer an inner-jaw gap from qpos or certify hidden clearance. Request side on a depth-valid interior patch of a visible long SIDE wall, not top, shadow or table; top on the package top interior; table on adjacent unobstructed tabletop. Check that the same wall is continuous through the proposed contact-height band. On a failed measurement use a different patch or camera, not the same failed edge. No exact bottom-edge sample is required.", {"attempt": attempt, "state": s, "model": m["model"], "geometry": g, "tracking": m["track"], "previous_measurements": m.get("observations", [])[-1:]}, fields)
                if measured(r, ["side", "top", "table"]):
                    break
            if not measured(r, ["side", "top", "table"]):
                stop("Different-patch/view retry did not obtain the targeted side, top and table depths.")
            if r["parameters"] != {"identity": "same_package", "corridors": "both_open_pad_corridors_visible_clear", "wall": "continuous_long_side_at_contact_band", "table": "unchanged"}:
                stop("Current side-wall suitability or visible open-pad descent corridors remain unresolved.")
            side, fresh_top, fresh_table = [np.array(r["points"][n]["world_m"]) for n in ["side", "top", "table"]]
            if abs(float(fresh_table[2]) - g["table_z_m"]) > 0.002 or abs(float(fresh_top[2]) - float(np.mean(pts[:, 2]))) > 0.002 or float(np.ptp(pts[:, 2])) > 0.003:
                stop("Fresh top/table measurements disagree with the stationary model.", "needs_replan")
            boundary = geo.transform(g["top_corners_world_m"], t["transform_initial_world_to_current_world"])
            center, R = np.mean(boundary, axis=0), geo.rotation(m["quaternion"])
            projected = boundary @ R[:, 1]
            side_error = abs(abs(float(np.dot(side, R[:, 1])) - float(np.mean(projected))) - float(np.ptp(projected)) / 2.0)
            if side_error > 0.004 or abs(float(np.dot(side - center, R[:, 0]))) > g["length_m"] / 2.0 - 0.002 or not float(fresh_table[2]) + 0.001 < float(side[2]) < float(fresh_top[2]) - 0.001:
                stop("Targeted depth does not validate the proposed long side wall; no margin relaxation.")
            g["contact_top_z_m"], g["contact_table_z_m"] = float(fresh_top[2]), float(fresh_table[2])
            m["side_evidence"] = {"frame_id": r["frame_id"], "side_world_m": side.tolist(), "top_world_m": fresh_top.tolist(), "table_world_m": fresh_table.tolist(), "side_plane_residual_m": side_error}
            cm = contact_model(s, m["quaternion"])
            m["model"] = cm
            if cm["feasible_interval_m"] < 0.0012:
                stop("Measured orientation and fresh surfaces leave insufficient height reserve for this candidate.")
            m["grasp_target"] = [float(center[0]), float(center[1]), cm["target_z_m"]]
            save()
            move(m["grasp_target"], 0.008, 0.0005, "stationary")
            m["phase"] = "close"
            save()
        if m["phase"] == "close":
            t, pts, s = track("stationary")
            cm, z = contact_model(s, s["tcp_quaternion_xyzw"]), float(geo.pad_position(s)[2])
            clearance = z + cm["finger_bottom_relative_to_pad_m"] - g["contact_table_z_m"] - cm["surface_allowance_m"]
            overlap = min(g["contact_top_z_m"] - cm["surface_allowance_m"], z + cm["common_pad_top_relative_m"]) - max(g["contact_table_z_m"] + cm["surface_allowance_m"], z + cm["common_pad_bottom_relative_m"])
            m["actual_contact"] = {"frame_id": s["frame_id"], "finger_table_clearance_after_allowance_m": clearance, "common_vertical_overlap_after_allowance_m": overlap}
            if clearance < 0.006 or overlap < 0.003:
                stop("Actual pose fails the unchanged 6 mm clearance or 3 mm finite-pad overlap check.")
            r = review("Before the single close command, verify actual opposed pads straddle the cream cheese long sides in the supplied contact-height band, not its top, with no table or neighboring-object contact. The pad centers may be above the top: the finite lower pad band must overlap the side walls. Reject uncertain identity, apparent displacement, or a finger obstructed by the package.", {"state": s, "actual_contact": m["actual_contact"], "side_evidence": m["side_evidence"]}, {"contact_position": ["valid", "invalid", "unknown"], "identity": ["same_package", "wrong", "unknown"]})
            if r["parameters"] != {"contact_position": "valid", "identity": "same_package"}:
                stop("Actual opposed contact position is not verified; no closure.")
            capacity()
            m["phase"] = "closing"
            act(m["grasp_target"], "close", 0.004, 0.0005)
            m["phase"] = "lift_setup"
            save()
        if m["phase"] == "closing":
            stop("Closure may already have been delivered; reconcile the receipt instead of closing again.")
        if m["phase"] == "lift_setup":
            t, pts, s = track("free")
            m["prelift_state"], m["prelift_transform"] = s, t["transform_initial_world_to_current_world"]
            target = np.array(geo.pad_position(s))
            target[2] += 0.050
            m["lift_target"], m["phase"] = target.tolist(), "lift"
            save()
        if m["phase"] == "lift":
            track("follow")
            r = review("Closure alone is not retention. Is the same cream cheese still between the pads without apparent miss, escape or slip, and is the remaining purely vertical diagnostic lift visibly unobstructed? Confirm the tracked patch remains the package itself. Do not require the package to have lifted before allowing this diagnostic action.", {"state": api.state(), "lift_target": m["lift_target"], "tracker": m["tracker"], "retention": m.get("retention")}, {"candidate": ["between_pads_no_apparent_slip", "missed_or_slipping", "unknown"], "lift_corridor": ["visibly_clear", "obstructed", "unknown"], "patch_identity": ["same_package", "wrong", "unknown"]})
            p = r["parameters"]
            if p["candidate"] == "missed_or_slipping" or p["patch_identity"] == "wrong":
                stop("Observed grasp candidate or tracked identity failed; do not reopen automatically.", "needs_replan")
            if p != {"candidate": "between_pads_no_apparent_slip", "lift_corridor": "visibly_clear", "patch_identity": "same_package"}:
                stop("Diagnostic lift candidate or remaining visible route is uncertain.")
            move(m["lift_target"], 0.010, 0.002, "follow")
            m["phase"] = "verify"
            save()
        if m["phase"] == "verify":
            t, pts, s = track("follow")
            if m["retention"]["hand_rise_m"] < 0.035 or m["retention"]["package_rise_m"] < 0.030:
                stop("Measured motion is insufficient to establish an independently lifted package.")
            fields = {"identity": ["same_package", "wrong", "unknown"], "grasp": ["held_without_apparent_slip", "failed", "unknown"], "gap": ["visible_air_gap_to_table", "contact", "unknown"], "other_support": ["none_visible", "present", "unknown"], "neighbors": ["visibly_clear", "contact", "unknown"], "side_sample": ["lower_package_side", "uncertain"]}
            for attempt in range(2):
                r = review("Assess the grasp effect only. Is the same package visibly clear of the table, moving with the fingers without apparent slipping, and supported only by the fingers with visible neighbor clearance? Request low_side on a visible LOWER SIDE interior patch and table on nearby tabletop. Do not select the top or insist on mixed-depth bottom-edge pixels. The side sample establishes its own altitude, not an unseen underside. Use another visible patch/view on measurement failure.", {"attempt": attempt, "retention": m["retention"], "tracker": m["tracker"], "reference_table_z_m": g["table_z_m"]}, fields)
                if measured(r, ["low_side", "table"]):
                    break
            p = r["parameters"]
            if p["identity"] == "wrong" or p["grasp"] == "failed" or p["gap"] == "contact" or p["other_support"] == "present" or p["neighbors"] == "contact":
                stop("Fresh observation contradicts the stable, independently lifted grasp.", "needs_replan")
            if p != {"identity": "same_package", "grasp": "held_without_apparent_slip", "gap": "visible_air_gap_to_table", "other_support": "none_visible", "neighbors": "visibly_clear", "side_sample": "lower_package_side"} or not measured(r, ["low_side", "table"]):
                stop("Fresh grasp-effect visibility or supporting depth remains inadequate.")
            side_z, table_z = r["points"]["low_side"]["world_m"][2], r["points"]["table"]["world_m"][2]
            if abs(table_z - g["table_z_m"]) > 0.002 or side_z - table_z < 0.020 or side_z > float(np.mean(pts[:, 2])) - 0.002:
                stop("Fresh table reference or visible lower-side altitude is inconsistent.")
            center = geo.transform([g["top_center_world_m"]], t["transform_initial_world_to_current_world"])[0]
            m["top_center_in_tool_m"] = (geo.rotation(s["tcp_quaternion_xyzw"]).T @ (center - np.array(s["tcp_position_world_m"]))).tolist()
            m["effect"] = {"frame_id": r["frame_id"], "parameters": p, "points": r["points"], "visible_side_altitude_above_table_m": side_z - table_z, "current_top_samples_world_m": pts.tolist(), "interpretation": "Fresh visible table separation plus measured rigid hand following and no apparent slip or other support. Side altitude is not a hidden-bottom clearance certificate."}
            m["phase"] = "complete"
            return finish("stage_complete", "The cream cheese visibly cleared the table and followed the gripper without apparent slipping.")
        return finish("blocked", "Unrecognized saved phase; reconcile actual physical state.")
    except Exception as error:
        m["error"] = {"message": str(error), "phase": m.get("phase"), "recovery_action": "None"}
        return finish(m.pop("return_status", "blocked"), str(error))

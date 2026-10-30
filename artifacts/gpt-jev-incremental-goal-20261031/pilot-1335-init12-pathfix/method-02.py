def main(api):
    start, prior = api.state(), api.recall("secure.progress")["value"]
    historical = api.recall("secure.geometry")["value"]["precontact"]
    tracker = api.recall("secure.tracker")["value"]
    keys = ["secure.measurements", "secure.progress", "secure.geometry", "secure.observations", "secure.tracker"]
    log = {"entry_state": start, "previous_actions": prior.get("actions", []), "previous_stop": prior.get("last_receipt"), "actions": [], "phase": "validate_actual_open_pose"}
    references = {"secure.local": "Fresh actual-pose depth, boundary selections, uncertainty and closure margins.", "secure.baseline": "Postclosure surface identities, hand state and optional persistent patch transform.", "secure.effect": "Fresh postlift review and valid depth samples.", "secure.retention": "Object motion compared with actual whole-lift hand motion.", "secure.resume": "Acknowledged repair actions and terminal state.", "secure.tracker": "Historical same-carton top patch, creation ROI and reference frame; not a current detection."}
    def save(key, value):
        api.checkpoint(key, value)
        if key not in keys:
            keys.append(key)
    def finish(status, reason, evidence):
        state = api.state()
        log.update({"stage_status": status, "reason": reason, "state": state})
        save("secure.resume", log)
        return {"stage_status": status, "reason": reason, "evidence": evidence, "completion_proposed": False, "handoff": {"checkpoint_keys": keys, "references": references, "current_state": state, "retention_established": status == "stage_complete", "bowl_reference": log.get("bowl", prior.get("bowl")), "bowl_reference_is_current": (log.get("bowl", prior.get("bowl")) or {}).get("frame_id") == state["frame_id"], "bowl_measurement_gap": log.get("bowl_measurement_gap"), "visible_extent": log.get("extent"), "frames": "World metres; tool-to-world xyzw quaternions. All observations retain camera and frame IDs; checkpoint receipts supply source/method provenance.", "assumptions": ["No transfer, opening or release was commanded by this repair. Preserve actual gripper state.", "Original frame-96 geometry and frame-0 bowl reference remain historical. Use the bowl reference frame, not its presence, to determine freshness.", "Local carton top and parallel sides were checked only for this pinch, not hidden clearance or full reconstruction.", "Reobserve bowl opening, package extent and transfer corridor before the next stage; a top patch does not measure hidden faces."]}}
    def compact(r):
        return {"frame_id": r["frame_id"], "parameters": r["parameters"], "points": r["points"], "measurement_errors": r["measurement_errors"]}
    def measured(r, names):
        bad = {v["name"] for v in r["measurement_errors"]}
        if any(n not in r["points"] or n in bad or r["points"][n]["frame_id"] != r["frame_id"] for n in names):
            raise ValueError("Missing, invalid or noncurrent named depth samples: " + str(names))
        p = np.asarray([r["points"][n]["world_m"] for n in names], dtype=float)
        if not np.all(np.isfinite(p)):
            raise ValueError("Nonfinite surface measurement.")
        u = 0.001
        for n in names:
            v = r["points"][n]
            c = api.camera(v["camera"])
            if c["frame_id"] != r["frame_id"]:
                raise ValueError("Calibration/depth frame mismatch.")
            u = max(u, 2.0*v["depth_m"]/min(c["K"][0][0], c["K"][1][1]))
        return p, float(u)
    def marks(r):
        try:
            p, u = measured(r, ("m0", "m1"))
            return {"p": p, "u": u} if r["parameters"]["marks_clear"] and np.linalg.norm(p[1]-p[0]) > 4*u else None
        except Exception:
            return None
    def tracking():
        try:
            t = api.track_update(tracker["handle"])
            log["tracking"] = {"status": t["status"], "frame_id": t["frame_id"], "reason": t.get("reason", "")}
            if t["status"] != "tracked" or t["reference_frame_id"] != tracker["reference_frame_id"] or t["frame_id"] != api.state()["frame_id"]:
                return None
            fit = geo.plane(t["current_inlier_world_m"])
            u = max(0.001, float(t["rms_m"]), float(t["uncertainty_floor_m"]))
            if t["inliers"] < 12 or t["inliers"]/max(1, t["matches"]) < 0.65 or max(t["rms_m"], fit["rms_m"]) > 0.0025 or min(fit["in_plane_spread_m"]) < 3*u:
                log["tracking"]["reason"] = "Insufficient registration rigidity, inliers or spatial support relative to noise."
                return None
            return {"T": t["transform_initial_world_to_current_world"], "ref": t["reference_inlier_world_m"], "cur": t["current_inlier_world_m"], "u": u, "frame_id": t["frame_id"], "inliers": t["inliers"], "rms_m": t["rms_m"]}
        except Exception as error:
            log["tracking"] = {"reason": str(error)}
            return None
    questions = {}
    for axis in ("x", "y", "z", "rx", "ry", "rz"):
        subject = "world translation " + axis if len(axis) == 1 else "world rotation-vector component " + axis[-1]
        questions[axis] = {"type": "choice", "instructions": "For " + subject + ", use state.processed_features.axes." + axis + ".goal_relation: increase selects positive, decrease selects negative, within_tolerance selects hold. Program geometry is context, not a contact sensor.", "criteria": {"negative": "Decrease this world component toward its target.", "hold": "This component is within its declared tolerance.", "positive": "Increase this world component toward its target."}}
    questions["gripper"] = {"type": "choice", "instructions": "Read state.processed_features.objective.gripper literally. A close choice actuates fingers; it does not establish retention.", "criteria": {"open": "The objective requests opening.", "close": "The objective requests closure.", "keep": "The objective requests unchanged actuation."}}
    expected = prior.get("state", {})
    if start["frame_id"] != expected.get("frame_id") or start["native_steps"] != expected.get("native_steps") or start["last_gripper_command"] != "open":
        return finish("blocked", "Entry no longer matches the acknowledged open-gripper stop. Do not replay acquisition or reopen.", {"actual": start, "expected": expected})
    uv = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}
    fields = {"configuration": ["same_carton_open_straddle", "displaced_or_wrong", "unknown"], "boundary": ["parallel_long_sides_cross_section", "unknown"], "lane": ["clear_75mm_upward", "obstructed", "unknown"], "camera": ["robot0_eye_in_hand", "agentview"], "edge_pixels": {"type": ["array", "null"], "items": uv, "minItems": 2, "maxItems": 2}, "notes": {"type": "string", "maxLength": 900}}
    attempts, local = [], None
    for attempt in range(2):
        r = api.review("Validate the ACTUAL stopped open-finger pose, without demanding the old target. Identify the same cream cheese carton, open fingers outside its width and centered along its length, and visible box sides extending to the table. Request a0,a1,a2,a3 on well-spread visible TOP INTERIOR patches and t0,t1,t2 on nearby bare table; prefer wrist depth. Full historical corners are unnecessary. In edge_pixels select TWO visible intersections of one transverse cross-section with the parallel long top boundaries, in camera; these are boundary rays, not mixed-depth samples. Confirm these boundary identities and a local 75 mm upward withdrawal/test lane, not hidden clearance. Do not call the pose usable merely because the fingers look close. " + ("Use current depths, not old projected labels." if attempt == 0 else "Use different interior patches or the other camera to replace the failed measurements; do not repeat occluded selections."), context={"historical_geometry_not_current": historical, "actual_state": start, "previous_attempt": attempts[-1:]}, fields=fields)
        attempts.append(compact(r))
        save("secure.local", {"attempts": attempts})
        if r["status"] == "stop":
            return finish("abort", "Actual-pose review requested stop.", compact(r))
        if r["parameters"]["configuration"] == "displaced_or_wrong":
            return finish("needs_replan", "Current carton identity, pose or open-straddle configuration invalidates this local pinch.", compact(r))
        try:
            if r["parameters"]["configuration"] != "same_carton_open_straddle" or r["parameters"]["boundary"] != "parallel_long_sides_cross_section" or r["parameters"]["lane"] != "clear_75mm_upward" or r["parameters"]["edge_pixels"] is None:
                raise ValueError("Current pinch relation, boundary identities or upward lane is unresolved.")
            p, u = measured(r, ("a0", "a1", "a2", "a3", "t0", "t1", "t2"))
            top, table = geo.plane(p[:4]), geo.plane(p[4:])
            a, b = np.asarray(top["coefficients"]), np.asarray(table["coefficients"])
            u = max(u, 3*float(top["rms_m"]), 3*float(table["rms_m"]))
            if a[2] < 0.98 or b[2] < 0.995 or max(top["rms_m"], table["rms_m"]) > 0.0015 or min(top["in_plane_spread_m"]) < 3*u or min(table["in_plane_spread_m"]) < 3*u:
                raise ValueError("Local plane model or spread relative to noise is inadequate.")
            edge_records = [api.plane_point(r["parameters"]["camera"], v, a.tolist()) for v in r["parameters"]["edge_pixels"]]
            if any(v["frame_id"] != r["frame_id"] for v in edge_records):
                raise ValueError("Boundary rays are not current.")
            e = np.asarray([v["world_m"] for v in edge_records])
            cam = api.camera(r["parameters"]["camera"])
            origin = np.asarray(cam["camera_to_world_opencv"])[:3, 3]
            u = max(u, float(2*max(np.linalg.norm(e-origin, axis=1))/min(cam["K"][0][0], cam["K"][1][1])))
            rot, pad = geo.rotation(start["tcp_quaternion_xyzw"]), np.asarray(geo.pad_position(start))
            across = e[1, :2]-e[0, :2]
            width = float(np.linalg.norm(across))
            if width <= 6*u:
                raise ValueError("Boundary separation is unresolved relative to its uncertainty.")
            across /= width
            along = np.asarray([-across[1], across[0]])
            contact_xy = e[:, :2] + float((pad[:2]-np.mean(e[:, :2], axis=0)) @ along)*along
            contact_z = -(contact_xy @ a[:2]+a[3])/a[2]
            own = start["own_geometry"]
            lo, hi, h = own["finger_low_offset_tool_m"], own["finger_high_offset_tool_m"], np.asarray(own["pad_extent_in_tool_m"])/2
            verts = np.asarray([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
            world_fingers = verts @ rot.T+np.asarray(start["tcp_position_world_m"])
            bottoms = np.asarray([[x, y, h[2]] for x in (-h[0], h[0]) for y in (-h[1], h[1])]) @ rot.T+pad
            gap, overlap = float(min(world_fingers @ b[:3]+b[3])), float(min(contact_z)-max(bottoms[:, 2]))
            aperture, offset = float(sum(abs(v) for v in start["gripper_qpos_m"])), abs(float((pad[:2]-np.mean(e[:, :2], axis=0)) @ across))
            required_gap, required_overlap = 0.002+2*u, 0.003+2*u
            margin = min(gap-required_gap, overlap-required_overlap)
            local = {"frame_id": r["frame_id"], "state": start, "top_plane": a.tolist(), "table_plane": b.tolist(), "top_rms_m": float(top["rms_m"]), "table_rms_m": float(table["rms_m"]), "boundary_records": edge_records, "contact_side_heights_m": contact_z.tolist(), "width_m": width, "open_joint_span_proxy_m": aperture, "centering_error_m": offset, "finger_table_gap_m": gap, "side_overlap_m": overlap, "required_table_gap_m": required_gap, "required_side_overlap_m": required_overlap, "remaining_margin_m": margin, "uncertainty_m": u, "uncertainty_rule": "max(1 mm working floor, two calibrated pixels, three plane RMS); heuristic, not a calibrated confidence bound", "scope": "Current visible planar top, identified parallel side boundaries and own finger envelope. No hidden clearance claim."}
            save("secure.local", {"attempts": attempts, "geometry": local})
            if abs(float(across @ rot[:2, 1])) < 0.97 or width+2*(0.004+u) >= aperture or offset+2*u >= 0.15*width:
                return finish("blocked", "Fresh lateral alignment or open-width margin does not support closure at this pose.", local)
            if margin < 0.0005:
                return finish("blocked", "Actual gap/overlap lacks the unchanged guards plus 0.5 mm holding reserve. No repeated descent or closure.", local)
            break
        except Exception as error:
            attempts[-1]["gap"] = str(error)
            save("secure.local", {"attempts": attempts})
            local = None
    if local is None:
        return finish("blocked", "Bounded different measurements did not resolve the actual-pose closure relation.", attempts)
    if start["budgets"]["jev_remaining"] < 24 or start["budgets"]["native_steps_remaining"] < 72:
        return finish("blocked", "Insufficient actuation budget for one closure and an observable bounded test.", local)
    for hold in range(4):
        s = api.state()
        log["phase"] = "one_closure_zero_requested_pose_change"
        save("secure.resume", log)
        rec = api.control(s["tcp_position_world_m"], s["tcp_quaternion_xyzw"], "close", questions, features={"phase": log["phase"], "hold_index": hold, "preclosure_geometry": local, "not_live_contact_feedback": True}, tool_point="tcp", translation_limit=0.001, rotation_limit=0.01, steps=3, position_tolerance=0.0005, rotation_tolerance=0.01)
        now = api.state()
        frozen_envelope = verts @ geo.rotation(now["tcp_quaternion_xyzw"]).T+np.asarray(now["tcp_position_world_m"])
        delta = frozen_envelope-world_fingers
        drift = float(max(np.linalg.norm(delta, axis=1)))
        gap_left = gap-max(0.0, float(max(-delta @ b[:3])))
        overlap_left = overlap-max(0.0, float(max(delta @ a[:3])/a[2]))
        offset_now = abs(float((np.asarray(geo.pad_position(now))[:2]-np.mean(e[:, :2], axis=0)) @ across))
        log["actions"].append({"phase": "closure_hold", "receipt": rec, "state": now, "hand_pose_envelope_drift_m": drift, "stationary_model_gap_lower_m": gap_left, "stationary_model_overlap_lower_m": overlap_left})
        save("secure.resume", log)
        if rec["status"] == "stalled" or rec["choices"]["gripper"] != "close" or any(rec["choices"][k] != "hold" for k in ("x", "y", "z", "rx", "ry", "rz")) or gap_left < required_gap or overlap_left < required_overlap or offset_now+2*u >= 0.15*width:
            return finish("blocked", "Closure hold mismatched, stalled or consumed the measured pose reserve. Stop closed; no retry or reopening.", log["actions"][-1])
    ids = {"type": "array", "items": {"type": "string", "maxLength": 220}, "minItems": 2, "maxItems": 2}
    baseline_fields = {"identity": ["same_carton", "unknown"], "candidate": ["supported_vertical_test", "slipped_or_displaced", "unknown"], "marks_clear": "boolean", "mark_ids": ids}
    tb, mb, baseline = tracking(), None, None
    for attempt in range(2):
        baseline = api.review("The single closure has occurred. Confirm the SAME carton is a plausible pinch candidate for the checked upward-only test, without visible slip, unintended contact or a newly obstructed lane; this is not retention. Request m0,m1 at TWO independently recognizable, depth-valid printed landmarks on any visible rigid carton face, and describe their exact physical identities in mark_ids. Choose CURRENT exposed features, not occluded old corners. " + ("Prefer the exposed upper logo details." if attempt == 0 else "Use different exposed printed details or the other camera, not the previous invalid selections."), context={"actual_state": api.state(), "tracking_quality": log.get("tracking"), "previous_attempt": None if baseline is None else compact(baseline)}, fields=baseline_fields)
        mb, before = marks(baseline), api.state()
        reference = {"state": before, "observation": compact(baseline), "mark_ids": baseline["parameters"]["mark_ids"], "landmarks_world_m": None if mb is None else mb["p"].tolist(), "landmark_uncertainty_m": None if mb is None else mb["u"], "tracker_identity": tracker, "transform_initial_to_baseline": None if tb is None else tb["T"], "tracking_uncertainty_m": None if tb is None else tb["u"]}
        save("secure.baseline", reference)
        if baseline["status"] == "stop":
            return finish("abort", "Postclosure review requested stop.", reference)
        if baseline["parameters"]["candidate"] == "slipped_or_displaced":
            return finish("needs_replan", "The single closure visibly displaced the carton or lost the supported test configuration.", reference)
        if baseline["parameters"]["identity"] != "same_carton" or baseline["parameters"]["candidate"] != "supported_vertical_test":
            return finish("blocked", "Current postclosure identity or local test safety is unresolved; no unchanged review or reopening.", reference)
        if tb is not None or mb is not None:
            break
    if baseline["parameters"]["identity"] != "same_carton" or baseline["parameters"]["candidate"] != "supported_vertical_test" or (tb is None and mb is None):
        return finish("blocked", "Postclosure test configuration or differential surface baseline remains unavailable. Preserve closure.", reference)
    rise = max(0.055, 30*(tb["u"] if tb is not None else mb["u"]))
    if rise > 0.075:
        return finish("blocked", "Measurement uncertainty needs a larger effect than the observed 75 mm test lane.", reference)
    target = list(before["tcp_position_world_m"])
    target[2] += rise
    cap = min(26, before["budgets"]["jev_remaining"], int(before["budgets"]["native_steps_remaining"]/3))
    if cap < 16:
        return finish("blocked", "Insufficient remaining lease budget for the one vertical test.", reference)
    log.update({"phase": "single_vertical_retention_test", "lift_before": before, "requested_rise_m": rise})
    save("secure.resume", log)
    rec = api.drive(target, before["tcp_quaternion_xyzw"], "close", questions, features={"phase": log["phase"], "baseline_frame": before["frame_id"], "requested_rise_m": rise, "baseline_uncertainty_m": tb["u"] if tb is not None else mb["u"], "retention_not_yet_established": True}, tool_point="tcp", max_calls=cap, translation_limit=0.008, rotation_limit=0.02, steps=3, position_tolerance=0.0015, rotation_tolerance=0.01)
    after, ta = api.state(), tracking()
    log["actions"].append({"phase": "vertical_test", "before": before, "after": after, "receipt": rec})
    save("secure.resume", log)
    post = api.review("Assess the fresh vertical-test EFFECT. Identify the SAME cream cheese carton as between the fingers with a visible table gap, left on the table, slipped, or unknown. Describe its visible extent relative to the fingers. Request m0,m1 at EXACTLY the baseline physical print identities if independently recognizable in either camera; never substitute stationary projections or different marks. A quality-checked same-surface patch is the alternative, so no full perimeter is required. Request bowl at the currently visible interior center of the same patterned upright bowl if depth-valid; this is only a location, not an opening-fit certificate.", context={"baseline": reference, "actual_after_state": after, "tracking_quality": log.get("tracking")}, fields={"identity": ["same_carton", "unknown"], "effect": ["held_with_table_gap", "on_table", "slipped", "unknown"], "marks_clear": "boolean", "visible_extent": {"type": "string", "maxLength": 1000}, "bowl_identity": ["same_upright_bowl", "unknown"]})
    save("secure.effect", compact(post))
    log["extent"] = post["parameters"]["visible_extent"]
    try:
        measured(post, ("bowl",))
        if post["parameters"]["bowl_identity"] == "same_upright_bowl":
            log["bowl"] = post["points"]["bowl"]
    except Exception:
        log["bowl_measurement_gap"] = "No current validated bowl depth; any inherited bowl location is historical."
    if post["status"] == "stop":
        return finish("abort", "Effect review requested stop. No release issued.", compact(post))
    if post["parameters"]["identity"] != "same_carton":
        return finish("blocked", "Fresh carton identity is unresolved; tracking is not an identity oracle.", compact(post))
    if post["parameters"]["effect"] in ("on_table", "slipped"):
        return finish("needs_replan", "Fresh images show failed acquisition or lost retention.", {"review": compact(post), "actual_lift": log["actions"][-1]})
    ma, pa, pb = marks(post), None, None
    if tb is not None and ta is not None:
        pa, pb = geo.transform(ta["ref"], tb["T"]), np.asarray(ta["cur"])
        sigma, method = tb["u"]+ta["u"], "quality_checked_same_top_patch"
    elif mb is not None and ma is not None:
        pa, pb, sigma, method = mb["p"], ma["p"], mb["u"]+ma["u"], "independently_identified_print_landmarks"
    if pa is None:
        return finish("blocked", "Neither current patch registration nor the independent landmark replacement supports a differential effect test. No additional lift or reopening.", {"baseline": reference, "post": compact(post), "tracking": log.get("tracking"), "actual_lift": log["actions"][-1]})
    hd = np.asarray(after["tcp_position_world_m"])-np.asarray(before["tcp_position_world_m"])
    od, error = np.mean(pb-pa, axis=0), float(geo.attachment_error(pa, pb, before, after))
    travel, allowance = float(np.linalg.norm(hd)), max(0.005, 3*sigma)
    report = {"baseline_frame": before["frame_id"], "current_frame": post["frame_id"], "measurement_method": method, "actual_hand_translation_m": hd.tolist(), "observed_surface_translation_m": od.tolist(), "attachment_error_m": error, "combined_uncertainty_m": sigma, "attachment_allowance_m": allowance, "actual_lease_status": rec["status"], "last_receipt": rec, "fresh_effect": post["parameters"], "current_surface_samples_world_m": pb[:6].tolist(), "current_state": after}
    save("secure.retention", report)
    if rec["choices"]["gripper"] != "close" or after["last_gripper_command"] != "close":
        return finish("blocked", "Lift actuation did not preserve the requested closure.", report)
    if hd[2] < 0.04 or travel <= 8*sigma or allowance > 0.25*travel:
        return finish("blocked", "Actual lift is insufficient relative to measurement uncertainty. The stopped lease is not retried.", report)
    if od[2] < 0.035 or error > allowance:
        return finish("needs_replan", "Observed carton motion does not follow actual hand motion within the declared effect margin.", report)
    if post["parameters"]["effect"] != "held_with_table_gap":
        return finish("blocked", "Differential motion is saved, but current visible table separation remains unresolved.", report)
    return finish("stage_complete", "Fresh carton surface motion follows the actual hand lift, and images show table separation. Gripper remains closed.", report)

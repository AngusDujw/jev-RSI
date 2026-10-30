def main(api):
    q = {}
    for a in ("x", "y", "z", "rx", "ry", "rz"):
        q[a] = {"type": "choice", "instructions": "For world axis " + a + ", read state.processed_features.axes." + a + ".goal_relation. Select positive for increase, negative for decrease, and hold for within_tolerance. Use the host residual, not an imagined object measurement.", "criteria": {"negative": "Decrease this world coordinate or world rotation-vector component.", "hold": "This axis is within the declared deadband.", "positive": "Increase this world coordinate or world rotation-vector component."}}
    q["gripper"] = {"type": "choice", "instructions": "Read state.processed_features.objective.gripper. Close maintains the existing grasp. Open is requested only after this program authorizes release. Keep preserves the preceding command. Do not infer a grasp from closure.", "criteria": {"open": "The objective requests the authorized opening.", "close": "The objective requests continued closure.", "keep": "The objective requests keep."}}
    g, log = {}, {"phase": "audit", "actions": [], "release_started": False}
    def sr(s):
        return {k: s[k] for k in ("frame_id", "native_steps", "tcp_position_world_m", "tcp_quaternion_xyzw", "gripper_qpos_m", "last_gripper_command")}
    def pr(s):
        return {k: s[k] for k in ("frame_id", "native_steps", "tcp_position_world_m", "tcp_quaternion_xyzw")}
    def stop(message, replan=False):
        log["failure_status"] = "needs_replan" if replan else "blocked"
        raise Exception(message)
    def save():
        api.checkpoint("place.geometry", g)
        api.checkpoint("place.progress", log)
    def finish(status, reason):
        if status == "stage_complete":
            log.pop("failure_status", None)
        log.update({"state": sr(api.state()), "stage_status": status, "reason": reason})
        save()
        return {"stage_status": status, "reason": reason, "completion_proposed": False, "evidence": log, "handoff": {"checkpoint_keys": ["place.geometry", "place.progress", "place.effect", "place.revision", "secure.retention"], "references": {"place.geometry": "Original frame-234 measured dimensions, opening, uncertainties and candidate tests; latest independently localized carton, release guard and margins.", "place.progress": "Actual before/after hand states, acknowledged actions, pending command, differential retention tests and release state.", "place.effect": "Most recent review with actual depth samples and errors, including unsuccessful observations.", "place.revision": "Preserved previous no-action rejection and provenance of the frame-matched references."}, "frames": "World metres; tool-to-world xyzw. Pixel references belong only to their recorded camera and observation frame. Checkpoint receipt metadata provides method/source provenance.", "state": log["state"], "release_started": log["release_started"], "assumptions": ["Do not repeat pickup, an acknowledged motion, or opening without auditing progress.", "Occluded carton extent is the previously measured rigid rectangle, not a newly observed hidden surface.", "The clearance model is local and operational, not a whole-arm or hidden-collision certificate.", "No withdrawal or settled-verification control is implemented; those belong to the next stage."]}}
    def record(r):
        return {k: r[k] for k in ("frame_id", "status", "parameters", "points", "measurement_errors")}
    def review(question, fields, context):
        r = api.review(question + " Use English ASCII. Unknown is allowed; historical projections are not current detections.", context=context, fields=fields)
        api.checkpoint("place.effect", record(r))
        log["last_review"] = {"frame_id": r["frame_id"], "parameters": r["parameters"], "measurement_errors": r["measurement_errors"]}
        if r["status"] == "stop":
            stop("Observation requested stop: " + r["explanation"])
        return r
    def valid(r):
        bad = [e["name"] for e in r["measurement_errors"]]
        return {k: v for k, v in r["points"].items() if k not in bad and v["frame_id"] == r["frame_id"]}
    def pts(r, names):
        d = valid(r)
        if any(k not in d for k in names):
            stop("Missing current depths: " + str([k for k in names if k not in d]))
        x = np.array([d[k]["world_m"] for k in names], dtype=float)
        if x.shape != (len(names), 3) or not np.all(np.isfinite(x)):
            stop("Malformed or nonfinite measured points.")
        return x
    def rigid(points, before, after):
        t = np.eye(4)
        t[:3, :3] = geo.rotation(after["tcp_quaternion_xyzw"]) @ geo.rotation(before["tcp_quaternion_xyzw"]).T
        t[:3, 3] = np.array(after["tcp_position_world_m"])-t[:3, :3] @ np.array(before["tcp_position_world_m"])
        return geo.transform(points, t)
    def own_box(s, low=None, high=None):
        lo = s["own_geometry"]["finger_low_offset_tool_m"] if low is None else low
        hi = s["own_geometry"]["finger_high_offset_tool_m"] if high is None else high
        t = np.eye(4)
        t[:3, :3], t[:3, 3] = geo.rotation(s["tcp_quaternion_xyzw"]), np.array(s["tcp_position_world_m"])
        return geo.transform(np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]), t)
    def fit(c, centered=False, box=None):
        b = np.array(c["box_world_m"]) if box is None else box
        center = np.mean(b[:, :2], axis=0) if centered else np.array(g["bowl_center_xy_m"])
        return float(g["bowl_radius_m"]-max(np.linalg.norm(b[:, :2]-center, axis=1))-c["u_m"]-g["bowl_u_m"])
    def vertical(c, s, envelope=None):
        f = own_box(s) if envelope is None else envelope
        return float(min(min(np.array(c["box_world_m"])[:, 2]), min(f[:, 2]))-g["rim_high_m"]-c["u_m"]-g["bowl_u_m"])
    pixel = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}
    fields = {"identity": ["same_carton", "lost", "unknown"], "end_ids_match": "boolean", "end_camera": ["agentview", "robot0_eye_in_hand"], "end_pixels": {"type": "array", "items": pixel, "maxItems": 2}, "bowl": ["same_upright_unchanged", "changed", "unknown"], "bowl_mode": ["landmarks", "rim_samples", "unknown"], "notes": {"type": "string", "maxLength": 900}}
    surface_question = "After the acknowledged motion, locate the same retained cream-cheese carton. Request p0,p1,p2,p3 distributed over the interior of its SAME printed broad face, away from fingers and seams. These are plane samples, not alleged texture correspondences. Return end_pixels in order for the two independently identifiable physical corners c0,c1 of the Cream-initial-C short end. Use the wrist view when useful; no opposite hidden corners are needed. Reidentify the upright bowl. Prefer b0 and b1 at the supplied physical pattern identities. At least one clearly identified pattern mark plus the visible unchanged upright bowl can validate stationarity along this above-lip noncontact route. If both are occluded, use bowl_mode=rim_samples and request v0,v1,v2 on well-separated actual INNER top-lip points, not the outer silhouette or lower wall."
    def bowl(r):
        p = r["parameters"]
        if p["bowl"] == "changed":
            stop("The bowl changed position or orientation.", True)
        if p["bowl"] != "same_upright_unchanged":
            raise ValueError("Bowl identity/upright stationarity is unresolved.")
        names = [n for n in ("b0", "b1") if n in valid(r)]
        if p["bowl_mode"] == "landmarks" and names:
            drift = max(float(np.linalg.norm(pts(r, [n])[0]-np.array(g["bowl_marks_world_m"][int(n[1])])) ) for n in names)
        elif p["bowl_mode"] == "rim_samples" and all(n in valid(r) for n in ("v0", "v1", "v2")):
            v = pts(r, ["v0", "v1", "v2"])
            cf = geo.circle_xy(v)
            pe = float(max(abs(v @ np.array(g["rim_plane"]["coefficients"][:3])+g["rim_plane"]["coefficients"][3])))
            drift = max(float(np.linalg.norm(np.array(cf["center_xy_m"])-np.array(g["bowl_center_xy_m"]))), abs(float(cf["radius_m"])-g["bowl_radius_m"]), pe)
            if cf["largest_angular_gap_rad"] > 3.5:
                raise ValueError("Replacement inner-lip points have inadequate angular coverage.")
        else:
            raise ValueError("Neither identified bowl pattern nor replacement inner-lip evidence is available.")
        if drift > 0.002:
            raise ValueError("Bowl reference discrepancy exceeds 2 mm; fresh opening localization is needed: " + str(drift))
        g["bowl_u_m"] = g["bowl_base_u_m"]+drift
        log["bowl_validation"] = {"frame_id": r["frame_id"], "mode": p["bowl_mode"], "mark_names": names, "discrepancy_m": drift}
    def carton(r):
        p = r["parameters"]
        if p["identity"] == "lost":
            stop("Fresh evidence indicates lost retention.", True)
        if p["identity"] != "same_carton" or not p["end_ids_match"] or len(p["end_pixels"]) != 2:
            raise ValueError("Current physical short-end identities are unresolved.")
        pl = geo.plane(pts(r, ["p0", "p1", "p2", "p3"]))
        rms, spread = float(pl["rms_m"]), float(min(pl["in_plane_spread_m"]))
        if rms > 0.0012 or spread < 5*max(0.0005, rms):
            raise ValueError("Face plane residual/spread does not support its orientation: " + str([rms, spread]))
        n = np.array(pl["coefficients"][:3])
        anchors = np.array([api.plane_point(p["end_camera"], uv, np.array(pl["coefficients"]).tolist())["world_m"] for uv in p["end_pixels"]])
        eu = 0.0004
        for uv, anchor in zip(p["end_pixels"], anchors):
            for du, dv in ((2, 0), (-2, 0), (0, 2), (0, -2)):
                v = api.plane_point(p["end_camera"], [max(0, min(767, uv[0]+du)), max(0, min(767, uv[1]+dv))], np.array(pl["coefficients"]).tolist())
                eu = max(eu, float(np.linalg.norm(np.array(v["world_m"])-anchor)))
        width = float(np.linalg.norm(anchors[1]-anchors[0]))
        if width < 8*eu or abs(width-g["width_m"]) > 2*eu+0.002:
            raise ValueError("Identified short-edge length is noise-limited or inconsistent with historical width.")
        e = (anchors[1]-anchors[0])/width
        d = np.cross(n, e)
        d = d/np.linalg.norm(d)
        side = float(np.dot(d, np.array(pl["center_world_m"])-np.mean(anchors, axis=0)))
        if abs(side) < 4*eu:
            raise ValueError("Face samples do not disambiguate the interior side of the identified edge.")
        if side < 0:
            d = -d
        top = np.array([anchors[0], anchors[1], anchors[1]+g["length_m"]*d, anchors[0]+g["length_m"]*d])
        box = np.concatenate((top, top-g["thickness_upper_m"]*n), axis=0)
        radius = float(max(np.linalg.norm(box-np.array(api.state()["tcp_position_world_m"]), axis=1)))
        nu = 2*max(rms, 0.0002)/spread
        u = g["historical_extent_u_m"]+(1+2*g["length_m"]/width)*eu+2*rms+g["length_m"]*nu+radius*0.015
        return {"box_world_m": box.tolist(), "center_world_m": np.mean(box, axis=0).tolist(), "anchors_world_m": anchors.tolist(), "short_axis_world": e.tolist(), "normal_world": n.tolist(), "normal_u_rad": nu, "edge_u_m": eu, "u_m": float(u), "frame_id": r["frame_id"], "plane_rms_m": rms, "plane_spread_m": spread}
    def observe(old, before, after, phase):
        context = {"geometry": g, "before": sr(before), "after": sr(after), "phase": phase}
        issue = ""
        for attempt in range(2):
            r = review(surface_question if attempt == 0 else "Replace only the failed evidence using a DIFFERENT depth-valid part of the same face or the other camera. Preserve physical corner IDs. If pattern marks are occluded, switch to the declared inner-lip alternative. Do not repeat an unchanged occluded request. Failure: " + issue + ". " + surface_question, fields, context)
            try:
                c = carton(r)
                bowl(r)
                break
            except Exception as exc:
                if log.get("failure_status") == "needs_replan":
                    raise
                issue = str(exc)
                context["partial_review"], context["measurement_gap"] = record(r), issue
                if attempt == 1:
                    stop("One alternate measurement did not resolve: " + issue)
        predicted = rigid(old["anchors_world_m"], before, after)
        error = float(geo.attachment_error(old["anchors_world_m"], c["anchors_world_m"], before, after))
        allowance = 0.002+2*(old["edge_u_m"]+c["edge_u_m"])
        old_normal = old["normal_world"] if "normal_world" in old else old["plane"]["coefficients"][:3]
        en = geo.rotation(after["tcp_quaternion_xyzw"]) @ geo.rotation(before["tcp_quaternion_xyzw"]).T @ np.array(old_normal)
        ne = float(np.arccos(np.clip(np.dot(en, c["normal_world"]), -1.0, 1.0)))
        signal = float(max(np.linalg.norm(predicted-np.array(old["anchors_world_m"]), axis=1)))
        test = {"phase": phase, "before_frame": before["frame_id"], "after_frame": after["frame_id"], "actual_hand_translation_m": (np.array(after["tcp_position_world_m"])-np.array(before["tcp_position_world_m"])).tolist(), "observed_end_translation_m": (np.mean(c["anchors_world_m"], axis=0)-np.mean(old["anchors_world_m"], axis=0)).tolist(), "attachment_error_m": error, "allowance_m": allowance, "normal_error_rad": ne, "predicted_anchor_motion_m": signal, "differential_motion_observable": signal > 3*allowance}
        log["retention_tests"] = log.get("retention_tests", [])+[test]
        g["current_carton"] = c
        save()
        if error > allowance or ne > 0.04+old["normal_u_rad"]+c["normal_u_rad"]:
            stop("Observed carton motion disagrees with actual whole-lease hand motion.", True)
        if phase == "raise" and signal <= 3*allowance:
            stop("The preparation lift did not produce a resolvable differential retention test.")
        return c
    def move(phase, target, quat, calls, limit):
        before = api.state()
        n = min(calls, int(before["budgets"]["jev_remaining"])-8, int(before["budgets"]["native_steps_remaining"])//3-8)
        if n < 1 or before["budgets"]["gpt_remaining"] < 2:
            stop("Insufficient reserve for this lease and fresh effect measurement.")
        log["phase"], log["pending"] = phase, {"target_tcp_world_m": target.tolist(), "quaternion_xyzw": quat, "gripper": "close"}
        save()
        receipt = api.drive(target.tolist(), quat, "close", q, features={"phase": phase, "geometry_frame": c["frame_id"], "carton_uncertainty_m": c["u_m"], "bowl_uncertainty_m": g["bowl_u_m"], "required_margin_m": 0.0035, "release_authorized": False}, max_calls=n, tool_point="tcp", translation_limit=limit, rotation_limit=0.10, steps=3, position_tolerance=0.0015, rotation_tolerance=0.015)
        after = api.state()
        log["actions"].append({"phase": phase, "before": pr(before), "after": pr(after), "receipt": {k: receipt[k] for k in ("frame_id", "status", "lease_calls", "acknowledged_steps", "position_error_m", "rotation_error_rad")}, "gripper_choice": receipt["choices"]["gripper"]})
        log["pending"] = None
        save()
        if receipt["status"] != "reached" or after["last_gripper_command"] != "close" or receipt["choices"]["gripper"] != "close":
            stop("Lease did not converge or its gripper command mismatched. No stalled/exhausted lease is retried.")
        return before, after
    try:
        gr = api.recall("place.geometry")
        g = gr["value"]
        previous = api.recall("place.progress")
        old, effect, s = previous["value"], api.recall("place.effect")["value"], api.state()
        log["entry"] = sr(s)
        revision = api.recall("place.revision")["value"]
        revision["latest_no_action_audit"] = {"progress": old, "geometry_provenance": {k: gr[k] for k in ("key", "frame_id", "method_number", "source_sha256")}, "correction": "corridor=clear and tilt_grasp=supported authorize only the assessed CLOSED route; opening_sweep=unknown is deferred, not treated as obstruction or release permission."}
        api.checkpoint("place.revision", revision)
        if old.get("release_started", False) or old.get("actions", []):
            log["release_started"], log["actions"] = old.get("release_started", False), old.get("actions", [])
            stop("Unexpected acknowledged placement actions exist. Audit actual pending phase; do not replay this entry-only repair.")
        if s["frame_id"] != old["state"]["frame_id"] or s["frame_id"] != g["current_carton"]["frame_id"] or s["frame_id"] != effect["frame_id"] or s["last_gripper_command"] != "close":
            stop("Entry is not the unchanged frame-matched closed-gripper rejection; reference revalidation is required.")
        if effect["parameters"]["corridor"] != "clear" or effect["parameters"]["tilt_grasp"] != "supported":
            stop("The existing review does not support the closed-gripper route.")
        baseline_plane = geo.plane(pts(effect, ["p0", "p1", "p2", "p3"]))
        if baseline_plane["rms_m"] > 0.0012 or min(baseline_plane["in_plane_spread_m"]) < 5*max(0.0005, float(baseline_plane["rms_m"])):
            stop("Frame-matched source depths no longer support the saved face geometry.")
        ids = g["corner_ids"][:2]
        if all(k in valid(effect) for k in ids):
            g["end_identity_reference"] = {"frame_id": effect["frame_id"], "observed_end_corners": {k: valid(effect)[k] for k in ids}, "scope": "Physical identity reference only; after movement these pixels are not current measurements."}
        c = g["current_carton"]
        g["bowl_u_m"] = g["bowl_base_u_m"]
        chosen = g["chosen_candidate"]
        angle = float(chosen["angle_rad"])
        if abs(angle) > 1.20 or chosen["predicted_margin_m"] <= 0.0035:
            stop("Stored candidate is outside the assessed scope or has insufficient fit.")
        sweep = np.concatenate((np.array(c["box_world_m"]), own_box(s)), axis=0)
        radius = float(max(np.linalg.norm(sweep-np.array(s["tcp_position_world_m"]), axis=1)))
        low = float(min(sweep[:, 2]))
        for j in range(9):
            pose = dict(s)
            pose["tcp_quaternion_xyzw"] = api.compose(s["tcp_quaternion_xyzw"], (np.array(c["short_axis_world"])*angle*j/8).tolist())
            low = min(low, float(min(rigid(sweep, s, pose)[:, 2])))
        rise = max(0.025, g["rim_high_m"]+c["u_m"]+g["bowl_u_m"]+0.015-low+radius*abs(angle)/16)
        if rise > 0.12:
            stop("Raised rotation envelope exceeds the assessed 0.12 m local preparation.")
        high = np.array(s["tcp_position_world_m"])+np.array([0.0, 0.0, rise])
        g["preparation"] = {"rise_m": rise, "sampled_low_z_m": low, "inter_sample_reserve_m": radius*abs(angle)/16, "closed_route_review_frame": effect["frame_id"], "release_not_authorized": True}
        save()
        before, after = move("raise", high, s["tcp_quaternion_xyzw"], 24, 0.012)
        c = observe(c, before, after, "raise")
        tilt_start, tilt_axis = after, np.array(c["short_axis_world"])
        final_q = api.compose(tilt_start["tcp_quaternion_xyzw"], (tilt_axis*angle).tolist())
        g["executed_tilt_target"] = {"start_frame": tilt_start["frame_id"], "axis_world": tilt_axis.tolist(), "angle_rad": angle, "quaternion_xyzw": final_q}
        for fraction in (0.5, 1.0):
            pose = dict(after)
            pose["tcp_quaternion_xyzw"] = final_q
            predicted_fit = fit(c, True, rigid(c["box_world_m"], after, pose))
            sweep = np.concatenate((np.array(c["box_world_m"]), own_box(after)), axis=0)
            sweep_low = float(min(sweep[:, 2]))
            for j in range(9):
                pose["tcp_quaternion_xyzw"] = api.compose(tilt_start["tcp_quaternion_xyzw"], (tilt_axis*angle*((fraction-0.5)+0.5*j/8)).tolist())
                sweep_low = min(sweep_low, float(min(rigid(sweep, after, pose)[:, 2])))
            reach = float(max(np.linalg.norm(sweep-np.array(after["tcp_position_world_m"]), axis=1)))
            vm = sweep_low-g["rim_high_m"]-c["u_m"]-g["bowl_u_m"]-reach*(abs(angle)/32+0.015)
            g["pretilt_checks"] = {"final_centered_fit_m": predicted_fit, "sweep_vertical_margin_m": vm, "fraction": fraction}
            save()
            if predicted_fit <= 0.0035 or vm <= 0.0035:
                stop("Current measurements invalidate the remaining tilt fit or above-lip sweep.")
            quat = api.compose(tilt_start["tcp_quaternion_xyzw"], (tilt_axis*angle*fraction).tolist())
            before, after = move("tilt_" + str(fraction), np.array(after["tcp_position_world_m"]), quat, 24, 0.003)
            c = observe(c, before, after, "tilt_" + str(fraction))
        g["pretransfer_checks"] = {"centered_fit_m": fit(c, True), "vertical_margin_m": vertical(c, after), "frame_id": after["frame_id"]}
        save()
        if fit(c, True) <= 0.0035 or vertical(c, after) <= 0.0035:
            stop("Actual tilted pose lacks the required fit or transfer height.")
        target = np.array(after["tcp_position_world_m"])
        target[:2] += np.array(g["bowl_center_xy_m"])-np.array(c["center_world_m"][:2])
        if np.linalg.norm(target-np.array(after["tcp_position_world_m"])) > 0.30:
            stop("Transfer exceeds the assessed local route.")
        before, after = move("transfer", target, final_q, 36, 0.016)
        c = observe(c, before, after, "transfer")
        g["overhead_fit"] = {"actual_margin_m": fit(c), "centered_margin_m": fit(c, True), "frame_id": after["frame_id"]}
        save()
        if fit(c) <= 0.0035:
            delta = np.array(g["bowl_center_xy_m"])-np.array(c["center_world_m"][:2])
            if fit(c, True) <= 0.0035 or np.linalg.norm(delta) > 0.018:
                stop("Fresh overhead fit cannot be corrected within the bounded centering scope.")
            target = np.array(after["tcp_position_world_m"])
            target[:2] += delta
            before, after = move("single_centering", target, final_q, 12, 0.004)
            c = observe(c, before, after, "single_centering")
        if fit(c) <= 0.0035:
            stop("Observed opening fit remains inadequate; descent is unauthorized.")
        lo, hi = np.array(after["own_geometry"]["finger_low_offset_tool_m"]), np.array(after["own_geometry"]["finger_high_offset_tool_m"])
        span = float(hi[1]-lo[1])
        lo[1], hi[1] = lo[1]-span, hi[1]+span
        lo, hi = lo-0.002, hi+0.002
        guard = own_box(after, lo, hi)
        low = min(float(min(np.array(c["box_world_m"])[:, 2])), float(min(guard[:, 2])))
        dz = g["rim_high_m"]+c["u_m"]+g["bowl_u_m"]+0.0055-low
        if dz > 0.003 or dz < -0.10:
            stop("Required endpoint lies outside the assessed local descent.")
        target = np.array(after["tcp_position_world_m"])+np.array([0.0, 0.0, dz])
        g["release_guard"] = {"low_tool_m": lo.tolist(), "high_tool_m": hi.tolist(), "construction": "Current measured finger box, expanded on each tool-y side by its entire measured width and by 2 mm on all axes. This is a proposed empty-space guard, NOT an assumed or measured full-stroke limit. Fresh visual confirmation that the visible parallel-jaw mechanism opens wholly within it is mandatory.", "source_frame": after["frame_id"]}
        g["lowering_endpoint"] = {"target_tcp_world_m": target.tolist(), "quaternion_xyzw": final_q, "predicted_guard_world_m": (guard+np.array([0.0, 0.0, dz])).tolist(), "predicted_carton_world_m": (np.array(c["box_world_m"])+np.array([0.0, 0.0, dz])).tolist()}
        save()
        before, after = move("above_lip_descent", target, final_q, 22, 0.006)
        c = observe(c, before, after, "above_lip_descent")
        guard = own_box(after, lo, hi)
        margins = {"lateral_m": fit(c), "vertical_m": vertical(c, after, guard), "drop_to_floor_m": float(min(np.array(c["box_world_m"])[:, 2])-g["floor_world_m"][2]), "frame_id": after["frame_id"]}
        g["release_margins"], g["release_guard"]["actual_world_m"] = margins, guard.tolist()
        save()
        if margins["lateral_m"] <= 0.0035 or margins["vertical_m"] < 0.0035 or not 0 < margins["drop_to_floor_m"] <= 0.065:
            stop("Actual endpoint fails the unchanged lateral, vertical, or bounded-drop release conditions.")
        audit_fields = {"identity": ["same_carton", "lost", "unknown"], "bowl": ["same_upright_unchanged", "changed", "unknown"], "stroke_bound": ["visible_mechanism_within_guard", "exceeds_guard", "unknown"], "opening_space": ["clear", "obstructed", "unknown"], "contact": ["none_visible", "contact", "unknown"], "notes": {"type": "string", "maxLength": 900}}
        r = review("At the CURRENT actual release endpoint, separately assess opening authorization. The supplied guard is deliberately larger than the measured closed fingers, but is NOT a certified stroke bound. From the visible parallel-jaw hardware/rails and finger geometry, can the entire outward opening motion be bounded inside this guard without guessing hidden geometry? Return stroke_bound=unknown if that is unobservable. Check the ACTUAL world guard and available lateral space against the bowl lip, bottle and other visible obstacles. The numerical lower bound keeps the entire guard and modeled carton above the lip. Assess immediate short-drop alignment, absence of rim contact, same carton and upright bowl. Unknown opening space is not an obstruction and not permission to open. No release has yet occurred.", audit_fields, {"geometry": g, "state": sr(after)})
        p = r["parameters"]
        if p["identity"] == "lost" or p["bowl"] == "changed":
            stop("Pre-release observation invalidates the placement plan.", True)
        if p["identity"] != "same_carton" or p["bowl"] != "same_upright_unchanged" or p["stroke_bound"] != "visible_mechanism_within_guard" or p["opening_space"] != "clear" or p["contact"] != "none_visible":
            stop("Closed-gripper progress is preserved; opening remains unauthorized. Exact remaining gap: " + p["notes"])
        remaining = api.state()["budgets"]
        if remaining["gpt_remaining"] < 2 or remaining["jev_remaining"] < 4 or remaining["native_steps_remaining"] < 12:
            stop("Release is withheld because execution and fresh effect-review reserves are insufficient.")
        log["release_started"], log["phase"] = True, "release"
        log["release_reference"] = {"state": sr(after), "carton_frame": c["frame_id"], "margins": margins, "authorization_frame": r["frame_id"]}
        release_target = after["tcp_position_world_m"]
        prior_aperture = sum(abs(v) for v in after["gripper_qpos_m"])
        save()
        for i in range(4):
            b = api.state()
            receipt = api.control(release_target, final_q, "open", q, features={"phase": "authorized_release", "release_authorized": True, "margins": margins, "opening_guard_frame": after["frame_id"]}, tool_point="tcp", translation_limit=0.002, rotation_limit=0.02, steps=3, position_tolerance=0.0015, rotation_tolerance=0.015)
            now = api.state()
            aperture = sum(abs(v) for v in now["gripper_qpos_m"])
            log["actions"].append({"phase": "release_hold", "before_frame": b["frame_id"], "after": sr(now), "receipt": {k: receipt[k] for k in ("frame_id", "status", "acknowledged_steps")}, "gripper_choice": receipt["choices"]["gripper"]})
            save()
            if now["last_gripper_command"] != "open" or receipt["choices"]["gripper"] != "open" or np.linalg.norm(np.array(now["tcp_position_world_m"])-np.array(release_target)) > 0.003:
                stop("Opening command mismatch or hand drift; no blind opening retry.")
            current_fingers = own_box(now)
            if np.any(np.array(now["own_geometry"]["finger_low_offset_tool_m"]) < lo) or np.any(np.array(now["own_geometry"]["finger_high_offset_tool_m"]) > hi):
                stop("Actual opening geometry exceeded the visually accepted guard; stop opening and reassess.")
            if float(min(current_fingers[:, 2])) < g["rim_high_m"]+g["bowl_u_m"]+0.0035:
                stop("Observed fingers no longer satisfy the above-lip opening bound.")
            if i >= 1 and aperture-prior_aperture < 0.0005:
                break
            prior_aperture = aperture
        final_fields = {"effect": ["inside_free", "still_retained", "rim_supported", "outside", "unknown"], "fingers": ["visibly_separated", "contacting", "unknown"], "bowl": ["same_upright_unchanged", "changed", "unknown"], "bowl_mode": ["landmarks", "rim_samples", "unknown"], "support_description": {"type": "string", "maxLength": 900}}
        r = review("Assess actual placement after the acknowledged opening, not merely delivery of open. inside_free means the same carton is visibly inside the upright bowl, no longer supported by either finger, and not balanced on the rim. Request object on an actually visible carton portion inside the cavity, preferably below the lip. Independently check both finger gaps. Reobserve the same b0,b1 pattern identities; if occluded, request v0,v1,v2 at distributed actual inner-top-lip points and select rim_samples. Describe visible support and containment. No withdrawal or settled-verification claim is requested.", final_fields, {"geometry": g, "release": log["release_reference"], "state": sr(api.state())})
        p = r["parameters"]
        if p["effect"] in ("outside", "rim_supported", "still_retained") or p["bowl"] == "changed":
            stop("Fresh post-release evidence requires a new placement correction: " + p["effect"], True)
        if "object" not in valid(r):
            r = review("Replace the missing object DEPTH using another visible carton patch below the inner lip or the other camera, not a hidden bottom or a bowl pixel. Preserve object/bowl identities and assess both actual finger gaps. Return the same declared effect fields. Request object and an available b0 or b1, or three distributed v0,v1,v2 inner-lip samples if patterns are occluded. This is a distinct measurement, not repeated release or withdrawal.", final_fields, {"geometry": g, "partial": record(r)})
            p = r["parameters"]
        bowl(r)
        x = pts(r, ["object"])[0]
        log["postrelease"] = {"frame_id": r["frame_id"], "parameters": p, "object_world_m": x.tolist(), "measurement_errors": r["measurement_errors"], "full_review_checkpoint": "place.effect"}
        if p["effect"] in ("outside", "rim_supported", "still_retained"):
            stop("Replacement post-release evidence requires correction: " + p["effect"], True)
        if p["effect"] != "inside_free" or p["fingers"] != "visibly_separated" or np.linalg.norm(x[:2]-np.array(g["bowl_center_xy_m"])) >= g["bowl_radius_m"]-g["bowl_u_m"] or x[2] > g["rim_high_m"]-g["bowl_u_m"]:
            stop("Opening occurred, but fresh containment depth or independent finger separation remains unresolved.")
        return finish("stage_complete", "Fresh images and depth show the released carton inside the unchanged upright bowl and visibly free of both fingers. Withdrawal and settling verification remain.")
    except Exception as exc:
        return finish(log.get("failure_status", "blocked"), str(exc))

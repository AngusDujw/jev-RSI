def main(api):
    q = {}
    for a in ("x", "y", "z", "rx", "ry", "rz"):
        q[a] = {"type": "choice", "instructions": "For world axis " + a + ", read state.processed_features.axes." + a + ".goal_relation. Choose positive for increase, negative for decrease, hold for within_tolerance. These are measured hand residuals, not object observations.", "criteria": {"negative": "Decrease this world coordinate or world rotation-vector component.", "hold": "This axis is within its declared deadband.", "positive": "Increase this world coordinate or world rotation-vector component."}}
    q["gripper"] = {"type": "choice", "instructions": "Read state.processed_features.objective.gripper. Select the requested command unchanged. Close maintains the existing grasp command; only an authorized release requests open. Closure is not evidence of retention.", "criteria": {"open": "The objective requests authorized opening.", "close": "The objective requests continued closure.", "keep": "The objective requests preservation of the last command."}}
    g, log = {}, {"phase": "audit", "actions": [], "retention_tests": [], "release_started": False}
    margin, pt, rt = 0.0035, 0.0015, 0.015
    def state_record(s):
        return {k: s[k] for k in ("frame_id", "native_steps", "tcp_position_world_m", "tcp_quaternion_xyzw", "gripper_qpos_m", "last_gripper_command") if k in s}
    def save():
        if g:
            api.checkpoint("place.geometry", g)
        api.checkpoint("place.progress", log)
    def fail(message, status="blocked"):
        log["failure_status"] = status
        raise ValueError(message)
    def finish(status, reason):
        log.update({"stage_status": status, "reason": reason, "state": state_record(api.state())})
        save()
        return {"stage_status": status, "reason": reason, "evidence": log, "completion_proposed": False, "handoff": {"checkpoint_keys": ["place.geometry", "place.progress", "place.effect", "place.revision"], "references": {"place.geometry": "Measured historical carton dimensions and bowl opening, original provenance, latest reobserved face/edge and uncertainty, evaluated margins and opening guard.", "place.progress": "Entry audit, acknowledged partial tilt, bounded new leases, actual hand states, differential retention tests, release status and terminal evidence.", "place.effect": "Latest raw review with frame-labelled depth points and measurement_errors; partial measurements are retained on failure.", "place.revision": "Previous progress, including the interrupted pending command, and original reference provenance."}, "state": log["state"], "release_started": log["release_started"], "frames": "World metres; xyzw tool-to-world quaternions. Pixels are valid only at their recorded camera/frame. Checkpoint metadata identifies source and method.", "assumptions": ["Do not replay the raise, first tilt, interrupted fixed-pivot command, or an acknowledged release.", "Historical rigid carton dimensions are not newly observed hidden corners. Current pose comes from the identified visible short edge and face.", "The local clearance model is operational, not a hidden-surface or whole-arm collision certificate.", "After opening, place.geometry.current_carton is the last held model, not a current object pose; use place.progress.postrelease and place.effect.", "Revalidate affected references after motion. Withdrawal and settled verification are not implemented here."]}}
    def record(r):
        return {k: r[k] for k in ("frame_id", "parameters", "points", "measurement_errors", "same_frame_reused_points") if k in r}
    def review(question, fields, context):
        if api.state()["budgets"]["gpt_remaining"] < 1:
            fail("No observation budget remains for the required effect check.")
        r = api.review(question + " Use English ASCII. Historical projections are not current detections.", fields=fields, context=context)
        prior = context.get("partial")
        if prior is not None and prior["frame_id"] == r["frame_id"]:
            a, b = prior["parameters"], r["parameters"]
            names = []
            if a.get("identity") == "same_carton" and b.get("identity") == "same_carton":
                names += ["p0", "p1", "p2", "p3"]
            if a.get("bowl") == "same_upright_unchanged" and b.get("bowl") == "same_upright_unchanged" and a.get("bowl_mode") == b.get("bowl_mode"):
                names += ["b0", "b1", "v0", "v1", "v2"]
            earlier = valid(prior)
            r["same_frame_reused_points"] = {k: earlier[k] for k in names if k in earlier}
        saved = record(r)
        if prior is not None:
            saved["previous_attempt"] = prior
        api.checkpoint("place.effect", saved)
        log["last_review"] = {"frame_id": r["frame_id"], "parameters": r["parameters"], "measurement_errors": r["measurement_errors"]}
        if r["status"] == "stop":
            fail("Review requested stop: " + r["explanation"])
        return r
    def valid(r):
        bad = [e["name"] for e in r["measurement_errors"]]
        d = {k: v for k, v in r["points"].items() if k not in bad and v["frame_id"] == r["frame_id"]}
        for k, v in r.get("same_frame_reused_points", {}).items():
            if k not in d and v["frame_id"] == r["frame_id"]:
                d[k] = v
        return d
    def points(r, names):
        d = valid(r)
        if any(n not in d for n in names):
            raise ValueError("Missing valid current depths: " + str([n for n in names if n not in d]))
        p = np.array([d[n]["world_m"] for n in names], dtype=float)
        if p.shape != (len(names), 3) or not np.all(np.isfinite(p)):
            raise ValueError("Malformed/nonfinite depth samples.")
        return p
    def rigid(p, before, after):
        t = np.eye(4)
        t[:3, :3] = geo.rotation(after["tcp_quaternion_xyzw"]) @ geo.rotation(before["tcp_quaternion_xyzw"]).T
        t[:3, 3] = np.array(after["tcp_position_world_m"])-t[:3, :3] @ np.array(before["tcp_position_world_m"])
        return geo.transform(np.array(p), t)
    def own_box(s, lo=None, hi=None):
        lo = s["own_geometry"]["finger_low_offset_tool_m"] if lo is None else lo
        hi = s["own_geometry"]["finger_high_offset_tool_m"] if hi is None else hi
        t = np.eye(4)
        t[:3, :3], t[:3, 3] = geo.rotation(s["tcp_quaternion_xyzw"]), np.array(s["tcp_position_world_m"])
        return geo.transform(np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]), t)
    def angle(a, b):
        return float(2*np.arccos(np.clip(abs(np.dot(a, b)), 0.0, 1.0)))
    def fit(c, centered=False, box=None):
        box = np.array(c["box_world_m"]) if box is None else box
        center = np.mean(box[:, :2], axis=0) if centered else np.array(g["bowl_center_xy_m"])
        return float(g["bowl_radius_m"]-max(np.linalg.norm(box[:, :2]-center, axis=1))-c["u_m"]-g["bowl_u_m"])
    def vertical(c, s, fingers=None):
        fingers = own_box(s) if fingers is None else fingers
        return float(min(min(np.array(c["box_world_m"])[:, 2]), min(fingers[:, 2]))-g["rim_high_m"]-c["u_m"]-g["bowl_u_m"])
    pixel = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}
    fields = {"identity": ["same_carton", "lost", "unknown"], "end_ids_match": "boolean", "end_camera": ["agentview", "robot0_eye_in_hand"], "end_pixels": {"type": "array", "items": pixel, "maxItems": 2}, "bowl": ["same_upright_unchanged", "changed", "unknown"], "bowl_mode": ["landmarks", "rim_samples", "unknown"], "closed_space": ["clear", "obstructed", "unknown"], "notes": {"type": "string", "maxLength": 800}}
    observation = "Identify the retained cream-cheese carton and its SAME printed broad face. Request p0,p1,p2,p3 as distributed depth-valid interior face samples, away from seams and fingers; these are not texture correspondences. Independently identify the two physical Cream-initial-C short-end corners c0,c1, in the saved physical order, and return their current end_pixels and camera. No opposite hidden corners are required. For bowl stationarity, request b0 and/or b1 at the saved physical medallion identities, not a similar repeated motif. If those are occluded, switch to rim_samples and request v0,v1,v2 at well-separated actual INNER top-lip points. Assess the local CLOSED-finger remaining tilt and elevated route to above the bowl from the actual pose, considering the bottle and visible surroundings. The remaining tilt may use the saved target or extend it by at most 0.18 rad about the same physical short edge, but total remaining rotation is bounded by 0.45 rad and TCP drift by 8 mm. Assess this bounded local extension too; numerical fit and sweep checks will select a candidate before action. Do not require release clearance yet. Unknown is allowed."
    def check_bowl(r):
        p, d = r["parameters"], valid(r)
        if p["bowl"] == "changed":
            fail("Fresh evidence indicates bowl displacement or changed orientation.", "needs_replan")
        if p["bowl"] != "same_upright_unchanged":
            raise ValueError("Current bowl identity/upright stationarity is unknown.")
        names = [n for n in ("b0", "b1") if n in d]
        if p["bowl_mode"] == "landmarks" and names:
            drift = max(float(np.linalg.norm(points(r, [n])[0]-np.array(g["bowl_marks_world_m"][int(n[1])]))) for n in names)
        elif p["bowl_mode"] == "rim_samples":
            v = points(r, ["v0", "v1", "v2"])
            cf = geo.circle_xy(v)
            if cf["largest_angular_gap_rad"] > 3.5:
                raise ValueError("Replacement inner-lip samples have inadequate angular coverage.")
            pl = np.array(g["rim_plane"]["coefficients"])
            drift = max(float(np.linalg.norm(np.array(cf["center_xy_m"])-np.array(g["bowl_center_xy_m"]))), abs(float(cf["radius_m"])-g["bowl_radius_m"]), float(max(abs(v @ pl[:3]+pl[3]))))
        else:
            raise ValueError("Neither an identified bowl mark nor replacement inner-lip evidence is available.")
        if drift > 0.002:
            raise ValueError("Bowl-reference discrepancy exceeds 2 mm; opening relocalization is needed: " + str(drift))
        g["bowl_u_m"] = g["bowl_base_u_m"]+drift
        log["bowl_validation"] = {"frame_id": r["frame_id"], "discrepancy_m": drift, "mode": p["bowl_mode"]}
    def localize(r):
        p = r["parameters"]
        if p["identity"] == "lost":
            fail("Fresh evidence indicates lost carton retention.", "needs_replan")
        if p["identity"] != "same_carton" or not p["end_ids_match"] or len(p["end_pixels"]) != 2:
            raise ValueError("The physical short-end identities are not resolved.")
        pl = geo.plane(points(r, ["p0", "p1", "p2", "p3"]))
        rms, spread = float(pl["rms_m"]), float(min(pl["in_plane_spread_m"]))
        if rms > 0.0012 or spread < 5*max(0.0005, rms):
            raise ValueError("Face residual/spread cannot support its orientation: " + str([rms, spread]))
        coeff, eu = np.array(pl["coefficients"]), 0.0004
        anchors = np.array([api.plane_point(p["end_camera"], uv, coeff.tolist())["world_m"] for uv in p["end_pixels"]])
        for uv, anchor in zip(p["end_pixels"], anchors):
            for du, dv in ((2, 0), (-2, 0), (0, 2), (0, -2)):
                x = api.plane_point(p["end_camera"], [max(0, min(767, uv[0]+du)), max(0, min(767, uv[1]+dv))], coeff.tolist())
                eu = max(eu, float(np.linalg.norm(np.array(x["world_m"])-anchor)))
        width = float(np.linalg.norm(anchors[1]-anchors[0]))
        if width < 8*eu or abs(width-g["width_m"]) > 2*eu+0.002:
            raise ValueError("Identified short edge is noise-limited or inconsistent with measured width.")
        e, n = (anchors[1]-anchors[0])/width, coeff[:3]
        d = np.cross(n, e)
        d = d/np.linalg.norm(d)
        side = float(np.dot(d, np.array(pl["center_world_m"])-np.mean(anchors, axis=0)))
        if abs(side) < 4*eu:
            raise ValueError("Face samples do not resolve which side of the short edge is interior.")
        d = d if side > 0 else -d
        top = np.array([anchors[0], anchors[1], anchors[1]+g["length_m"]*d, anchors[0]+g["length_m"]*d])
        box = np.concatenate((top, top-g["thickness_upper_m"]*n), axis=0)
        reach = float(max(np.linalg.norm(box-np.array(api.state()["tcp_position_world_m"]), axis=1)))
        nu = 2*max(rms, 0.0002)/spread
        u = g["historical_extent_u_m"]+(1+2*g["length_m"]/width)*eu+2*rms+g["length_m"]*nu+reach*rt
        return {"box_world_m": box.tolist(), "anchors_world_m": anchors.tolist(), "center_world_m": np.mean(box, axis=0).tolist(), "normal_world": n.tolist(), "short_axis_world": e.tolist(), "normal_u_rad": nu, "edge_u_m": eu, "u_m": float(u), "frame_id": r["frame_id"], "plane_rms_m": rms, "plane_spread_m": spread}
    def observe(old, before, after, phase):
        context = {"geometry": g, "before": state_record(before), "after": state_record(after), "phase": phase, "measurement_gap": ""}
        for attempt in range(2):
            r = review(observation if attempt == 0 else "Use a DIFFERENT attainable face patch/camera or the declared rim alternative to replace only the failed evidence. Preserve physical IDs; do not repeat the same occluded request. " + observation, fields, context)
            try:
                c = localize(r)
                check_bowl(r)
                break
            except Exception as exc:
                if log.get("failure_status") == "needs_replan":
                    raise
                context["partial"], context["measurement_gap"] = record(r), str(exc)
                log["measurement_gap"] = str(exc)
                if attempt == 1:
                    fail("One distinct replacement did not resolve: " + str(exc))
        predicted = rigid(old["anchors_world_m"], before, after)
        err = float(geo.attachment_error(old["anchors_world_m"], c["anchors_world_m"], before, after))
        allowance = 0.002+2*(old["edge_u_m"]+c["edge_u_m"])
        en = geo.rotation(after["tcp_quaternion_xyzw"]) @ geo.rotation(before["tcp_quaternion_xyzw"]).T @ np.array(old["normal_world"])
        ne = float(np.arccos(np.clip(np.dot(en, c["normal_world"]), -1.0, 1.0)))
        signal = float(max(np.linalg.norm(predicted-np.array(old["anchors_world_m"]), axis=1)))
        log["retention_tests"].append({"phase": phase, "before_frame": before["frame_id"], "after_frame": after["frame_id"], "actual_hand_translation_m": (np.array(after["tcp_position_world_m"])-np.array(before["tcp_position_world_m"])).tolist(), "observed_edge_translation_m": (np.mean(c["anchors_world_m"], axis=0)-np.mean(old["anchors_world_m"], axis=0)).tolist(), "attachment_error_m": err, "allowance_m": allowance, "normal_error_rad": ne, "predicted_feature_motion_m": signal, "resolvable_differential": signal > 3*allowance})
        g["current_carton"], log["closed_space"] = c, r["parameters"]["closed_space"]
        save()
        if err > allowance or ne > 0.04+old["normal_u_rad"]+c["normal_u_rad"]:
            fail("Current carton motion disagrees with the actual hand rigid transform.", "needs_replan")
        if phase == "interrupted_tilt" and signal <= 3*allowance:
            fail("Interrupted motion did not produce a resolvable current retention test.")
        return c
    def move(phase, target, quat, chunks, limit, rot_limit, tilt=False):
        before = api.state()
        if log.get("closed_space") != "clear":
            fail("Fresh local closed-finger motion clearance is unresolved.")
        if before["budgets"]["gpt_remaining"] < 2:
            fail("Insufficient reserve for motion and a replacement effect observation.")
        start = np.array(before["tcp_position_world_m"])
        reach = float(max(np.linalg.norm(np.concatenate((np.array(c["box_world_m"]), own_box(before)), axis=0)-start, axis=1)))
        log["objective_reference"] = {"phase": phase, "state": state_record(before), "carton_frame": c["frame_id"]}
        failure, last = "", None
        for j in range(chunks):
            s = api.state()
            if s["budgets"]["jev_remaining"] < 7 or s["budgets"]["native_steps_remaining"] < 21:
                failure = "Execution reserve reached; no further lease."
                break
            merit = float(np.linalg.norm(target-np.array(s["tcp_position_world_m"])))+reach*angle(s["tcp_quaternion_xyzw"], quat)
            log["phase"], log["pending"] = phase, {"target_tcp_world_m": target.tolist(), "quaternion_xyzw": quat, "gripper": "close", "chunk": j}
            save()
            last = api.drive(target.tolist(), quat, "close", q, features={"phase": phase, "geometry_frame": c["frame_id"], "carton_u_m": c["u_m"], "bowl_u_m": g["bowl_u_m"], "required_margin_m": margin, "release_authorized": False, "tilt_drift_limit_m": 0.008 if tilt else None}, max_calls=3, tool_point="tcp", translation_limit=limit, rotation_limit=rot_limit, steps=3, position_tolerance=pt, rotation_tolerance=rt)
            now = api.state()
            entry = {"phase": phase, "before": state_record(s), "after": state_record(now), "receipt": {k: last[k] for k in ("frame_id", "status", "lease_calls", "acknowledged_steps", "position_error_m", "rotation_error_rad")}, "gripper_choice": last["choices"]["gripper"]}
            log["actions"] = (log["actions"]+[entry])[-6:]
            log["pending"] = None
            save()
            drift = float(np.linalg.norm(np.array(now["tcp_position_world_m"])-start))
            if last["choices"]["gripper"] != "close" or now["last_gripper_command"] != "close":
                failure = "Actual gripper-command mismatch."
                break
            if tilt and drift > 0.008:
                failure = "Reduced-rate tilt exceeded its newly assessed 8 mm pivot-drift envelope."
                break
            if last["status"] == "stalled":
                failure = "Stalled lease; no retry or assumed obstacle."
                break
            if last["status"] == "reached":
                break
            new_merit = float(np.linalg.norm(target-np.array(now["tcp_position_world_m"])))+reach*angle(now["tcp_quaternion_xyzw"], quat)
            angular_progress = angle(s["tcp_quaternion_xyzw"], quat)-angle(now["tcp_quaternion_xyzw"], quat)
            if merit-new_merit < 0.0002 and not (tilt and drift <= 0.008 and angular_progress > 0.005):
                failure = "No meaningful reduction of measured position-plus-angular endpoint residual."
                break
        after = api.state()
        fresh = observe(c, before, after, phase)
        if failure or last is None or last["status"] != "reached":
            fail(failure if failure else "Finite convergence allowance exhausted; fresh partial effect is preserved.")
        return fresh, after
    try:
        gr, previous = api.recall("place.geometry"), api.recall("place.progress")
        g, old, s = gr["value"], previous["value"], api.state()
        revision = api.recall("place.revision")["value"]
        revision["interrupted_run"] = {k: old[k] for k in ("phase", "entry", "state", "pending", "release_started", "last_review", "objective_reference") if k in old}
        revision["interrupted_run"]["actions"] = old.get("actions", [])[-4:]
        revision["interrupted_run"]["retention_tests"] = old.get("retention_tests", [])[-4:]
        revision["repair_entry"] = {"state": state_record(s), "geometry_provenance": {k: gr[k] for k in ("key", "frame_id", "method_number", "source_sha256")}, "policy_change": "Do not replay the interrupted fixed pivot. Revalidate actual retention and clearance; reset only the remaining tilt pivot to the measured entry TCP, reduce rotation limit, increase translation authority, and check each three-call lease."}
        api.checkpoint("place.revision", revision)
        log["entry"], log["release_started"] = state_record(s), old.get("release_started", False)
        log["preserved_history"] = {"checkpoint": "place.revision", "previous_phase": old.get("phase"), "previous_pending": old.get("pending"), "previous_retention_tests": old.get("retention_tests", [])}
        if log["release_started"] or s["last_gripper_command"] != "close":
            fail("Entry is no longer an unreleased closed grasp; audit actual release before any action.")
        references = [a["after"] for a in old.get("actions", []) if "after" in a and a["after"]["frame_id"] == g["current_carton"]["frame_id"]]
        objective_reference = old.get("objective_reference", {})
        if not references and objective_reference.get("carton_frame") == g["current_carton"]["frame_id"]:
            references = [objective_reference["state"]]
        if not references:
            fail("No measured hand state matches the saved carton reference frame.")
        before = dict(references[-1])
        log["interrupted_tilt"] = {"reference_hand": references[-1], "actual_entry": state_record(s), "acknowledged_native_step_delta": s["native_steps"]-references[-1]["native_steps"], "pending_command_retired": old.get("pending"), "note": "Partial action is real; no receipt or reference reset is invented."}
        c = observe(g["current_carton"], before, s, "interrupted_tilt")
        base_q = g["executed_tilt_target"]["quaternion_xyzw"]
        sweep = np.concatenate((np.array(c["box_world_m"]), own_box(s)), axis=0)
        reach = float(max(np.linalg.norm(sweep-np.array(s["tcp_position_world_m"]), axis=1)))
        final_q, tests = None, []
        for extra in (0.0, 0.06, 0.12, 0.18):
            candidate = api.compose(base_q, (-extra*np.array(c["short_axis_world"])).tolist())
            theta = angle(s["tcp_quaternion_xyzw"], candidate)
            if theta > 0.45:
                tests.append({"extra_tilt_rad": extra, "remaining_angle_rad": theta, "rejected": "Outside remaining-rotation scope."})
                continue
            qa, qb = np.array(s["tcp_quaternion_xyzw"]), np.array(candidate)
            qb = qb if np.dot(qa, qb) >= 0 else -qb
            low, gap, preceding = float(min(sweep[:, 2])), 0.0, qa.tolist()
            pose = dict(s)
            for j in range(9):
                blend = (1-j/8)*qa+(j/8)*qb
                pose["tcp_quaternion_xyzw"] = (blend/np.linalg.norm(blend)).tolist()
                gap = max(gap, angle(preceding, pose["tcp_quaternion_xyzw"]))
                preceding = pose["tcp_quaternion_xyzw"]
                low = min(low, float(min(rigid(sweep, s, pose)[:, 2])))
            expected_fit = fit(c, True, rigid(c["box_world_m"], s, pose))
            clearance = low-g["rim_high_m"]-c["u_m"]-g["bowl_u_m"]-reach*(gap/2+rt)-0.008
            tests.append({"extra_tilt_rad": extra, "remaining_angle_rad": theta, "predicted_centered_fit_m": expected_fit, "sweep_margin_m": clearance})
            if expected_fit > margin+2*pt and clearance > margin:
                final_q = candidate
                break
        g["repair_tilt_check"] = {"frame_id": s["frame_id"], "candidates": tests, "selected_quaternion_xyzw": final_q, "predicted_fit_requirement_m": margin+2*pt, "drift_reserve_m": 0.008, "new_pivot_world_m": s["tcp_position_world_m"]}
        save()
        if final_q is None:
            fail("No bounded remaining-tilt candidate has both the unchanged clearance margin and two position-tolerances of fit headroom.")
        c, s = move("remaining_tilt_reduced_rate", np.array(s["tcp_position_world_m"]), final_q, 10, 0.016, 0.035, True)
        if fit(c, True) <= margin+pt or vertical(c, s) <= margin+pt:
            fail("Actual tilt lacks fit or height for an elevated translation.")
        target = np.array(s["tcp_position_world_m"])
        target[:2] += np.array(g["bowl_center_xy_m"])-np.array(c["center_world_m"][:2])
        if np.linalg.norm(target-np.array(s["tcp_position_world_m"])) > 0.30:
            fail("Transfer exceeds the assessed local route.")
        c, s = move("elevated_transfer", target, final_q, 10, 0.016, 0.035)
        if fit(c) <= margin:
            delta = np.array(g["bowl_center_xy_m"])-np.array(c["center_world_m"][:2])
            if fit(c, True) <= margin+pt or np.linalg.norm(delta) > 0.018:
                fail("Fresh overhead fit cannot be corrected within this local centering scope.")
            target = np.array(s["tcp_position_world_m"])
            target[:2] += delta
            c, s = move("single_centering", target, final_q, 4, 0.006, 0.025)
        if fit(c) <= margin:
            fail("Actual centered carton still fails the unchanged fit margin.")
        lo, hi = np.array(s["own_geometry"]["finger_low_offset_tool_m"]), np.array(s["own_geometry"]["finger_high_offset_tool_m"])
        span = float(hi[1]-lo[1])
        lo[1], hi[1] = lo[1]-span, hi[1]+span
        lo, hi = lo-0.002, hi+0.002
        guard = own_box(s, lo, hi)
        low = min(float(min(np.array(c["box_world_m"])[:, 2])), float(min(guard[:, 2])))
        dz = g["rim_high_m"]+c["u_m"]+g["bowl_u_m"]+0.0055-low
        g["release_guard"] = {"low_tool_m": lo.tolist(), "high_tool_m": hi.tolist(), "source_frame": s["frame_id"], "scope": "Conservative candidate opening-space region, not an actuator stroke sensor or a hidden-clearance certificate."}
        if not -0.10 <= dz <= 0.003:
            fail("The above-lip release endpoint is outside the assessed local descent.")
        if abs(dz) > pt:
            target = np.array(s["tcp_position_world_m"])+np.array([0.0, 0.0, dz])
            c, s = move("above_lip_descent", target, final_q, 7, 0.006, 0.025)
        guard = own_box(s, lo, hi)
        margins = {"frame_id": s["frame_id"], "lateral_m": fit(c), "vertical_m": vertical(c, s, guard), "drop_to_floor_m": float(min(np.array(c["box_world_m"])[:, 2])-g["floor_world_m"][2])}
        g["release_margins"], g["release_guard"]["actual_world_m"] = margins, guard.tolist()
        save()
        if margins["lateral_m"] <= margin or margins["vertical_m"] < margin or not 0 < margins["drop_to_floor_m"] <= 0.065:
            fail("Measured endpoint fails the unchanged fit, above-lip clearance or bounded-drop condition.")
        opening_fields = {"identity": ["same_carton", "lost", "unknown"], "bowl": ["same_upright_unchanged", "changed", "unknown"], "opening_space": ["clear", "obstructed", "unknown"], "opening_within_guard": ["supported", "not_supported", "unknown"], "contact": ["none_visible", "contact", "unknown"], "notes": {"type": "string", "maxLength": 800}}
        r = review("At this ACTUAL endpoint, assess local release only. The supplied opening guard expands each tool-y side of the measured finger box by its entire measured width, with 2 mm on all axes; it is an assessment region, not a measured actuator limit. Do the visible parallel-jaw mechanism and outward directions support opening within this generous region, with visible local space clear of the bowl, bottle and other obstacles? No exact hidden hardware reconstruction is required, but do not assert unseen clearance. The measured lower bound keeps the candidate region above the lip. Check same carton, upright unchanged bowl, short-drop alignment and absence of visible rim contact. If local evidence is insufficient, answer unknown; no opening is authorized yet.", opening_fields, {"geometry": g, "state": state_record(s)})
        p = r["parameters"]
        if p["identity"] == "lost" or p["bowl"] == "changed":
            fail("Pre-release evidence invalidates the current plan.", "needs_replan")
        if p["identity"] != "same_carton" or p["bowl"] != "same_upright_unchanged" or p["opening_space"] != "clear" or p["opening_within_guard"] != "supported" or p["contact"] != "none_visible":
            fail("Release withheld; exact local opening gap: " + p["notes"])
        budgets = api.state()["budgets"]
        if budgets["gpt_remaining"] < 2 or budgets["jev_remaining"] < 4 or budgets["native_steps_remaining"] < 12:
            fail("Insufficient reserved budget for opening and its effect observation.")
        log["release_started"], log["phase"] = True, "release"
        log["release_reference"] = {"state": state_record(s), "carton_frame": c["frame_id"], "authorization_frame": r["frame_id"], "margins": margins}
        target, aperture = s["tcp_position_world_m"], sum(abs(v) for v in s["gripper_qpos_m"])
        save()
        for j in range(4):
            receipt = api.control(target, final_q, "open", q, features={"phase": "authorized_release", "release_authorized": True, "authorization_frame": r["frame_id"], "margins": margins}, tool_point="tcp", translation_limit=0.002, rotation_limit=0.02, steps=3, position_tolerance=pt, rotation_tolerance=rt)
            now = api.state()
            log["actions"] = (log["actions"]+[{"phase": "opening", "after": state_record(now), "receipt": {k: receipt[k] for k in ("frame_id", "status", "acknowledged_steps")}, "gripper_choice": receipt["choices"]["gripper"]}])[-6:]
            save()
            if receipt["status"] == "stalled" or receipt["choices"]["gripper"] != "open" or now["last_gripper_command"] != "open" or np.linalg.norm(np.array(now["tcp_position_world_m"])-np.array(target)) > 0.003 or angle(now["tcp_quaternion_xyzw"], final_q) > rt:
                fail("Opening command mismatch or hand drift; no blind retry.")
            if np.any(np.array(now["own_geometry"]["finger_low_offset_tool_m"]) < lo) or np.any(np.array(now["own_geometry"]["finger_high_offset_tool_m"]) > hi) or float(min(own_box(now)[:, 2])) < g["rim_high_m"]+g["bowl_u_m"]+margin:
                fail("Actual opening geometry violated the accepted local guard; stop and reassess.")
            new_aperture = sum(abs(v) for v in now["gripper_qpos_m"])
            if j >= 1 and new_aperture-aperture < 0.0005:
                break
            aperture = new_aperture
        final_fields = {"effect": ["inside_free", "still_retained", "rim_supported", "outside", "unknown"], "fingers": ["visibly_separated", "contacting", "unknown"], "cavity_relation": ["visible_entry", "unknown"], "bowl": ["same_upright_unchanged", "changed", "unknown"], "bowl_mode": ["landmarks", "rim_samples", "unknown"], "notes": {"type": "string", "maxLength": 800}}
        context = {"geometry": g, "release": log["release_reference"], "state": state_record(api.state())}
        for attempt in range(2):
            question = "Assess actual RELEASE, not open-command delivery. inside_free requires the same carton visibly entering the bowl cavity, no support from either finger, and no rim balancing. Independently inspect both finger gaps and the lower-carton/inner-lip occlusion relation; visible_entry must have positive current image evidence, not a hidden-bottom guess. Request object on a depth-valid visible CARTON portion within the opening, preferably below the lip; do not label bowl texture as carton. Revalidate bowl stationarity with an identified b0/b1, or v0,v1,v2 distributed inner-top-lip samples if those marks are occluded. No withdrawal or settled-placement claim is requested."
            r = review(question if attempt == 0 else "Use a DIFFERENT visible carton patch/camera and the alternate bowl measurement if needed; do not repeat an unchanged occluded query. " + question, final_fields, context)
            p = r["parameters"]
            if p["effect"] in ("still_retained", "rim_supported", "outside") or p["bowl"] == "changed":
                fail("Actual post-release placement needs replanning: " + p["effect"], "needs_replan")
            try:
                check_bowl(r)
                x = points(r, ["object"])[0]
                if p["effect"] != "inside_free" or p["fingers"] != "visibly_separated" or p["cavity_relation"] != "visible_entry":
                    raise ValueError("Positive cavity-entry evidence or independent finger separation is unresolved.")
                if np.linalg.norm(x[:2]-np.array(g["bowl_center_xy_m"])) >= g["bowl_radius_m"]-g["bowl_u_m"]:
                    raise ValueError("The visible carton depth does not lie inside the uncertainty-eroded opening.")
                log["postrelease"] = {"frame_id": r["frame_id"], "parameters": p, "object_world_m": x.tolist(), "point_below_uncertain_lip": bool(x[2] < g["rim_high_m"]-g["bowl_u_m"]), "scope": "Fresh image-supported cavity entry and finger separation plus current carton depth inside the opening; no hidden support or settled stability is certified."}
                return finish("stage_complete", "Fresh observations show the released carton entering the unchanged upright bowl cavity, free of both fingers. Withdrawal and settled verification remain.")
            except Exception as exc:
                if log.get("failure_status") == "needs_replan":
                    raise
                context["partial"], context["measurement_gap"] = record(r), str(exc)
                if attempt == 1:
                    fail("Release occurred but its stage effect remains unresolved: " + str(exc))
        return finish("blocked", "No accepted post-release effect.")
    except Exception as exc:
        return finish(log.get("failure_status", "blocked"), str(exc))

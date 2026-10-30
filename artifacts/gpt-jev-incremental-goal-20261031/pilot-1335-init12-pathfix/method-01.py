def main(api):
    start = api.state()
    prior = api.recall("secure.progress")["value"]
    old = api.recall("secure.measurements")["value"]
    keys = ["secure.measurements", "secure.progress"]
    progress = {"phase": "revised_observation_approach", "prior_outcome": prior.get("reason"), "entry_frame": start["frame_id"], "actions": []}
    questions = {}
    for axis in ("x", "y", "z", "rx", "ry", "rz"):
        subject = "world position " + axis if len(axis) == 1 else "world rotation-vector component " + axis[-1]
        questions[axis] = {"type": "choice", "instructions": "For " + subject + ", read state.processed_features.axes." + axis + ".goal_relation. Select positive for increase, negative for decrease, hold for within_tolerance. Geometry is program-supplied context, not a contact sensor.", "criteria": {"negative": "Decrease this world component toward its target.", "hold": "This component is within its specified tolerance.", "positive": "Increase this world component toward its target."}}
    questions["gripper"] = {"type": "choice", "instructions": "Use state.processed_features.objective.gripper literally. Closing actuates fingers and does not establish retention.", "criteria": {"open": "The objective requests open.", "close": "The objective requests close.", "keep": "The objective requests keep, preserving the current actuation."}}
    def save(key, value):
        api.checkpoint(key, value)
        if key not in keys:
            keys.append(key)
    def finish(status, reason, evidence):
        state = api.state()
        progress.update({"terminal_status": status, "reason": reason, "state": state})
        save("secure.progress", progress)
        return {"stage_status": status, "reason": reason, "evidence": evidence, "handoff": {"checkpoint_keys": keys, "state": state, "retention_established": status == "stage_complete", "bowl_reference": progress.get("bowl"), "bowl_reference_is_current": (progress.get("bowl") or {}).get("frame_id") == state["frame_id"], "visible_extent": progress.get("extent"), "frames": "World metres; xyzw tool-to-world quaternions. Pixels and observations carry camera/frame IDs. Checkpoint receipts carry method/source provenance.", "assumptions": ["Only acquisition and a vertical retention test were attempted; no transfer or release.", "Preserve the actual gripper state. Checkpoint geometry is historical, not a current detection.", "The carton top is treated as a rigid surface. Reobserve the bowl opening, object extent and relevant corridor before transfer."], "references": {"secure.measurements": "Original frame-0 partial measurements, preserved unchanged.", "secure.geometry": "Coarse and close-view top/table geometry, uncertainty derivation and revised pinch interval.", "secure.observations": "Bounded close-view measurement attempts, including valid partial results.", "secure.tracker": "Optional top-surface tracker identity, ROI and reference frame.", "secure.preclosure": "Fresh open-pinch review, valid partial landmarks and measured own-geometry margins.", "secure.baseline": "Postclosure differential reference, partial measurements and actual hand state.", "secure.effect_observation": "Fresh post-test named measurements, identity and separation review.", "secure.retention": "Fresh motion comparison and separation evidence.", "secure.progress": "Acknowledged phases, actual states and terminal gap."}}, "completion_proposed": False}
    def points(r, names):
        p = r.get("points", r.get("valid_points", {}))
        bad = {e["name"] for e in r["measurement_errors"]}
        if any(n not in p or n in bad or p[n]["frame_id"] != r["frame_id"] for n in names):
            return None
        return np.asarray([p[n]["world_m"] for n in names], dtype=float)
    def uncertainty(r, names):
        p, values = r.get("points", r.get("valid_points", {})), [0.001]
        for n in names:
            c = api.camera(p[n]["camera"])
            if c["frame_id"] != r["frame_id"]:
                raise ValueError("Camera and depth frames differ.")
            values.append(2.0*p[n]["depth_m"]/min(c["K"][0][0], c["K"][1][1]))
        return float(max(values))
    def compact(r):
        return {"frame_id": r["frame_id"], "parameters": r["parameters"], "points": r["points"], "measurement_errors": r["measurement_errors"]}
    def geometry(r):
        names = ("f0", "f1", "f2", "f3", "t0", "t1", "t2")
        p = points(r, names)
        if p is None:
            raise ValueError("Missing or invalid named top/table depth samples.")
        top, table = geo.plane(p[:4]), geo.plane(p[4:])
        a, b = np.asarray(top["coefficients"]), np.asarray(table["coefficients"])
        u = max(uncertainty(r, names), 3.0*float(top["rms_m"]), 3.0*float(table["rms_m"]))
        if a[2] < 0.99 or b[2] < 0.995 or max(top["rms_m"], table["rms_m"]) > 0.0015 or min(top["in_plane_spread_m"]) < 3*u or min(table["in_plane_spread_m"]) < 3*u:
            raise ValueError("Top/table model or feature-spread-to-noise support is inadequate.")
        c = np.asarray([api.plane_point(r["parameters"]["camera"], uv, a.tolist())["world_m"] for uv in r["parameters"]["corners_uv"]])
        e = np.roll(c, -1, axis=0)-c
        lengths = np.linalg.norm(e, axis=1)
        if min(lengths) < 6*u or max(abs(lengths[0]-lengths[2]), abs(lengths[1]-lengths[3])) > 4*u or abs(float(np.dot(e[0], e[1]))) > 0.2*lengths[0]*lengths[1]:
            raise ValueError("Visible boundary does not support the local rectangular-carton model.")
        center, axis = np.mean(c, axis=0), e[0 if lengths[0] >= lengths[1] else 1].copy()
        axis[2] = 0.0
        axis /= np.linalg.norm(axis)
        side = {}
        for name in ("s0", "s1"):
            v = points(r, (name,))
            if v is not None:
                su = uncertainty(r, (name,))
                if float(v[0] @ b[:3]+b[3]) < -3*su or v[0, 2] > max(c[:, 2])+3*su:
                    raise ValueError("A selected sidewall depth contradicts the top/support relation.")
                side[name] = v[0].tolist()
        return {"frame_id": r["frame_id"], "camera": r["parameters"]["camera"], "corners_uv": r["parameters"]["corners_uv"], "corners_world_m": c.tolist(), "center_world_m": center.tolist(), "long_axis": axis.tolist(), "top_plane": a.tolist(), "table_plane": b.tolist(), "uncertainty_m": float(u), "uncertainty_rule": "max(1 mm working depth floor, two calibrated pixels at measured depth, three plane RMS); heuristic, not calibrated confidence", "top_rms_m": float(top["rms_m"]), "table_rms_m": float(table["rms_m"]), "top_spread_m": np.asarray(top["in_plane_spread_m"]).tolist(), "sidewall_points_world_m": side, "landmarks_world_m": p[:2].tolist(), "mark_ids": r["parameters"].get("mark_ids", [])}
    def finger_vertices(state):
        lo, hi = state["own_geometry"]["finger_low_offset_tool_m"], state["own_geometry"]["finger_high_offset_tool_m"]
        return np.asarray([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    def plan(g, q):
        state, r, c = api.state(), geo.rotation(q), np.asarray(g["corners_world_m"])
        own, b, u = state["own_geometry"], np.asarray(g["table_plane"]), g["uncertainty_m"]
        rel = (finger_vertices(state)-np.asarray(own["pad_center_in_tool_m"])) @ r.T
        h = np.asarray(own["pad_extent_in_tool_m"])/2
        bottoms = np.asarray([[x, y, h[2]] for x in (-h[0], h[0]) for y in (-h[1], h[1])]) @ r.T
        center = np.asarray(g["center_world_m"])
        base = rel + np.asarray([center[0], center[1], 0.0])
        finger_budget, pad_budget = 0.00075+0.01*float(max(np.linalg.norm(rel, axis=1))), 0.00075+0.01*float(max(np.linalg.norm(bottoms, axis=1)))
        floor_required, overlap_required = 0.002+2*u, 0.003+2*u
        lower = float(max(-(base @ b[:3]+b[3])/b[2])+(floor_required+finger_budget)/b[2])
        upper = float(min(c[:, 2])-overlap_required-max(bottoms[:, 2])-pad_budget)
        projected = c @ r[:, 1]
        width, aperture = float(max(projected)-min(projected)), float(sum(abs(v) for v in state["gripper_qpos_m"]))
        center[2] = (lower+upper)/2
        return {"target": center.tolist(), "quaternion": q, "lower_pad_z_m": lower, "upper_pad_z_m": upper, "feasible_height_interval_m": upper-lower, "required_table_gap_m": floor_required, "required_side_overlap_m": overlap_required, "finger_pose_budget_m": finger_budget, "pad_pose_budget_m": pad_budget, "width_along_closure_m": width, "open_joint_span_proxy_m": aperture, "supported": bool(upper-lower > 0.0002 and width+2*(0.004+u) < aperture), "scope": "Local observed carton/top/table model and own finger envelope; aperture proxy is not a contact sensor or hidden-clearance certificate."}
    def move(phase, target, q, grip, calls, limit, tolerance=0.002):
        before = api.state()
        cap = min(calls, before["budgets"]["jev_remaining"], int(before["budgets"]["native_steps_remaining"]/3))
        progress["phase"] = phase
        save("secure.progress", progress)
        if cap < 1:
            progress["motion_gap"] = "Insufficient remaining actuation budget."
            return False
        receipt = api.drive(target, q, grip, questions, features={"phase": phase, "pre_action_pinch_model": progress.get("plan"), "model_is_not_live_contact_feedback": True}, tool_point="pad_center", max_calls=cap, translation_limit=limit, rotation_limit=0.07, steps=3, position_tolerance=tolerance, rotation_tolerance=0.01)
        after = api.state()
        progress["actions"].append({"phase": phase, "before_frame": before["frame_id"], "after_frame": after["frame_id"], "actual_native_steps": after["native_steps"]-before["native_steps"], "before_tcp": before["tcp_position_world_m"], "after_tcp": after["tcp_position_world_m"], "status": receipt["status"], "lease_calls": receipt["lease_calls"]})
        progress["last_receipt"] = receipt
        save("secure.progress", progress)
        return receipt["status"] == "reached" and receipt["choices"]["gripper"] == grip
    if start["native_steps"] != 0 or start["last_gripper_command"] != "open" or old["frame_id"] != start["frame_id"]:
        return finish("blocked", "Actual execution differs from the acknowledged zero-motion entry. Do not replay acquisition or reopen a possible grasp.", {"state": start, "prior": prior})
    try:
        g0 = geometry(old)
    except Exception as error:
        return finish("blocked", "Preserved frame-0 observations cannot support even the noncontact observation approach: "+str(error), old)
    if old["parameters"]["approach"] != "clear" or old["parameters"]["scene"] != "flat_carton_on_table":
        return finish("blocked", "The unchanged initial observation does not support the overhead observation lane.", old)
    progress["bowl"] = old["valid_points"].get("bowl")
    axis = np.asarray(g0["long_axis"])
    if float(axis @ geo.rotation(start["tcp_quaternion_xyzw"])[:, 0]) < 0:
        axis = -axis
    q = api.compose([1.0, 0.0, 0.0, 0.0], [0.0, 0.0, math.atan2(float(axis[1]), float(axis[0]))])
    high, hover = list(g0["center_world_m"]), list(g0["center_world_m"])
    high[2] = max(float(geo.pad_position(start)[2]), max(v[2] for v in g0["corners_world_m"])+0.12)
    hover[2] = max(v[2] for v in g0["corners_world_m"])+0.09
    save("secure.geometry", {"coarse": g0, "revision": "The rejected pinch is not executed. Move only to a clear noncontact observation hover before reassessing contact geometry."})
    if not move("high_observation_alignment", high, q, "keep", 32, 0.02) or not move("noncontact_close_view", hover, q, "keep", 30, 0.015):
        return finish("blocked", "Observation approach stopped; preserve actual acknowledged motion. No contact was retried.", progress["actions"])
    uv = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}
    fields = {"scene": ["flat_carton_on_table", "different", "unknown"], "camera": ["robot0_eye_in_hand", "agentview"], "top_outline": ["clear", "unknown"], "corners_uv": {"type": "array", "items": uv, "minItems": 4, "maxItems": 4}, "approach": ["clear", "obstructed", "unknown"], "sidewall": ["visible_box_profile", "different", "unknown"], "mark_ids": {"type": "array", "items": {"type": "string", "maxLength": 180}, "minItems": 2, "maxItems": 2}, "notes": {"type": "string", "maxLength": 800}}
    attempts, g, pinch = [], None, None
    for attempt in range(2):
        r = api.review("Reassess the BLUE CREAM CHEESE carton from this noncontact observation pose, not the old rejected pinch. Request f0,f1 at two distinguishable printed top marks near an exposed long-axis end, away from the central pinch; describe their physical identities in mark_ids. Request f2,f3 on other well-spread top interior patches and t0,t1,t2 on adjacent bare table. Prefer the closer calibrated wrist view for these depths. Request s0,s1 on an exposed package sidewall if depth-valid; missing sidewall depths are allowed, but visually confirm a box wall extending toward this support. Return four cyclic visible top-boundary pixels in corners_uv, not edge-depth samples. Check the open-finger descent lane and a 75 mm upward test lane against neighboring objects. No hidden clearance claim. "+("This is the first close measurement." if attempt == 0 else "Use different interior patches or the other available camera for failed measurements; do not repeat the same mixed-depth edge samples."), context={"coarse_geometry": g0, "previous_attempts": attempts, "own_geometry": api.state()["own_geometry"]}, fields=fields)
        attempts.append(compact(r))
        save("secure.observations", attempts)
        p = r["parameters"]
        if r["status"] == "stop":
            return finish("abort", "Close-view review requested stop.", compact(r))
        if p["scene"] == "different" or p["sidewall"] == "different":
            return finish("needs_replan", "Fresh observation invalidates the flat rigid-carton acquisition model.", compact(r))
        if p["approach"] == "obstructed":
            return finish("blocked", "The current local grasp/test lane is obstructed.", compact(r))
        try:
            if p["scene"] != "flat_carton_on_table" or p["top_outline"] != "clear" or p["approach"] != "clear" or p["sidewall"] != "visible_box_profile":
                raise ValueError("Top identity, sidewall/support relation or local lane remains unresolved.")
            g = geometry(r)
            if np.linalg.norm(np.asarray(g["center_world_m"])-np.asarray(g0["center_world_m"])) > 3*(g["uncertainty_m"]+g0["uncertainty_m"]):
                return finish("needs_replan", "The carton moved beyond the noncontact localization allowance.", {"coarse": g0, "current": g})
            pinch = plan(g, q)
            save("secure.geometry", {"coarse": g0, "precontact": g, "plan": pinch})
            if pinch["supported"]:
                break
            raise ValueError("The measured robust pad-height interval or necessary aperture screen is still inadequate.")
        except Exception as error:
            attempts[-1]["gap"] = str(error)
            if pinch is not None:
                attempts[-1]["pinch_diagnostic"] = pinch
            save("secure.observations", attempts)
            if attempt == 0 and p["approach"] == "clear" and p["scene"] == "flat_carton_on_table":
                closer = list(geo.pad_position(api.state()))
                closer[2] = max(closer[2]-0.025, max(v[2] for v in g0["corners_world_m"])+0.06)
                if not move("bounded_closer_observation", closer, q, "keep", 16, 0.006):
                    return finish("blocked", "The bounded alternate observation pose was not reached.", attempts)
    if pinch is None or not pinch["supported"] or g is None:
        return finish("blocked", "No supported local pinch after bounded different measurements; this is not a claim of global infeasibility.", attempts)
    progress["plan"] = pinch
    handle, tracker_frame = None, None
    polygon = np.asarray(g["corners_uv"], dtype=float)
    polygon = 0.72*polygon+0.28*np.mean(polygon, axis=0)
    try:
        init = api.track_init(g["camera"], polygon.tolist())
        handle, tracker_frame = init["handle"], init["frame_id"]
        save("secure.tracker", {"handle": handle, "identity": "Cream cheese carton top-label surface only", "camera": g["camera"], "polygon": polygon.tolist(), "reference_frame_id": tracker_frame, "geometry_key": "secure.geometry/precontact"})
    except Exception as error:
        progress["tracker_initialization_gap"] = str(error)
    def tracking():
        if handle is None:
            return None
        try:
            t = api.track_update(handle)
            progress["tracking_diagnostic"] = {"status": t["status"], "frame_id": t["frame_id"], "reason": t.get("reason", "")}
            if t["status"] != "tracked" or t["reference_frame_id"] != tracker_frame or t["frame_id"] != api.state()["frame_id"]:
                return None
            patch = geo.plane(t["current_inlier_world_m"])
            u = max(0.001, float(t["rms_m"]), float(t["uncertainty_floor_m"]))
            if t["inliers"] < 12 or t["inliers"]/max(1, t["matches"]) < 0.65 or t["rms_m"] > 0.0025 or patch["rms_m"] > 0.0025 or min(patch["in_plane_spread_m"]) < 3*u:
                progress["tracking_diagnostic"]["reason"] = "Insufficient rigid registration quality or spread relative to residuals/noise."
                return None
            return {"t": t, "u": u}
        except Exception as error:
            progress["tracking_diagnostic"] = {"reason": str(error)}
            return None
    def marks(r):
        a = points(r, ("m0", "m1"))
        if not r["parameters"]["marks_clear"] or a is None:
            return None
        u = uncertainty(r, ("m0", "m1"))
        return {"p": a, "u": u} if np.linalg.norm(a[1]-a[0]) > 4*u else None
    if not move("single_open_finger_descent", pinch["target"], q, "keep", 32, 0.006, 0.00075):
        return finish("blocked", "Descent stopped without a contact retry or closure.", progress["actions"])
    state, td = api.state(), tracking()
    rot = geo.rotation(state["tcp_quaternion_xyzw"])
    wf = finger_vertices(state) @ rot.T+np.asarray(state["tcp_position_world_m"])
    b, h = np.asarray(g["table_plane"]), np.asarray(state["own_geometry"]["pad_extent_in_tool_m"])/2
    bottom = np.asarray([[x, y, h[2]] for x in (-h[0], h[0]) for y in (-h[1], h[1])]) @ rot.T
    gap = float(min(wf @ b[:3]+b[3]))
    overlap = float(min(v[2] for v in g["corners_world_m"])-geo.pad_position(state)[2]-max(bottom[:, 2]))
    ready = api.review("Fresh PREclosure check: identify the same stationary carton, the two OPEN fingers straddling its short-width sides, and no unintended contact with the table or neighbors. Confirm the 75 mm upward lane. Full perimeter recovery is unnecessary. If obtainable request m0,m1 at the exact two saved print landmarks; marks_clear means BOTH physical identities are independently recognized, not stationary projections.", context={"geometry": g, "plan": pinch, "actual_own_finger_table_gap_m": gap, "predicted_side_overlap_at_actual_pose_m": overlap, "tracking": progress.get("tracking_diagnostic")}, fields={"alignment": ["aligned_stationary", "shifted_or_misaligned", "unknown"], "lane": ["clear", "obstructed", "unknown"], "marks_clear": "boolean"})
    save("secure.preclosure", {"observation": compact(ready), "state": state, "table_gap_m": gap, "side_overlap_m": overlap, "geometry_reference": "secure.geometry/precontact"})
    if ready["status"] == "stop":
        return finish("abort", "Preclosure review requested stop.", compact(ready))
    if ready["parameters"]["alignment"] == "shifted_or_misaligned":
        return finish("needs_replan", "The carton shifted or the actual open pinch is misaligned.", compact(ready))
    mr = marks(ready)
    displacement = None
    if td is not None:
        cc = np.asarray(g["center_world_m"])
        displacement = float(np.linalg.norm(geo.transform([cc.tolist()], td["t"]["transform_initial_world_to_current_world"])[0]-cc))
        shift_limit = 3*(g["uncertainty_m"]+td["u"])
    elif mr is not None:
        displacement = float(max(np.linalg.norm(mr["p"]-np.asarray(g["landmarks_world_m"]), axis=1)))
        shift_limit = 3*(g["uncertainty_m"]+mr["u"])
    if displacement is not None and displacement > shift_limit:
        return finish("needs_replan", "Current surface evidence shows unintended package motion during descent.", {"displacement_m": displacement, "allowance_m": shift_limit, "review": compact(ready)})
    if ready["parameters"]["alignment"] != "aligned_stationary" or ready["parameters"]["lane"] != "clear" or gap < pinch["required_table_gap_m"] or overlap < pinch["required_side_overlap_m"]:
        return finish("blocked", "Actual pose or fresh visual alignment fails the measured closure margin. No closure issued.", {"table_gap_m": gap, "side_overlap_m": overlap, "required": pinch, "review": compact(ready)})
    close_target, close_q = geo.pad_position(state).tolist(), state["tcp_quaternion_xyzw"]
    for hold in range(4):
        receipt = api.control(close_target, close_q, "close", questions, features={"phase": "one_closure_bounded_settling", "hold_index": hold, "actual_table_gap_before_closure_m": gap, "retention_not_established": True}, tool_point="pad_center", translation_limit=0.002, rotation_limit=0.02, steps=3, position_tolerance=0.00075, rotation_tolerance=0.01)
        progress.update({"phase": "closure_acknowledged", "last_receipt": receipt, "closure_state": api.state()})
        save("secure.progress", progress)
        if receipt["status"] == "stalled" or receipt["choices"]["gripper"] != "close":
            return finish("blocked", "Closure hold stalled or mismatched the command. Preserve the actual grasp state.", progress["closure_state"])
    baseline = api.review("After the single closure, does the same carton remain a plausible pinch candidate for the previously checked vertical test, without evident slip or unintended contact? This is NOT a retention judgment. Request m0,m1 at TWO independently identifiable CURRENT printed landmarks on any visible rigid carton face. Prefer the saved marks only if visible; otherwise choose different currently visible features and describe their physical identities in mark_ids. Do not repeat occluded historical marks or corners. marks_clear means both depth samples and identities are supported. A quality-checked top patch is an alternative.", context={"mark_ids": g["mark_ids"], "geometry_key": "secure.geometry", "state": api.state()}, fields={"candidate": ["supported_vertical_test", "slipped_or_misaligned", "unknown"], "identity": ["same_carton", "unknown"], "marks_clear": "boolean", "mark_ids": {"type": "array", "items": {"type": "string", "maxLength": 180}, "minItems": 2, "maxItems": 2}})
    if baseline["status"] == "stop":
        return finish("abort", "Postclosure review requested stop.", compact(baseline))
    if baseline["parameters"]["candidate"] == "slipped_or_misaligned":
        return finish("needs_replan", "Closure displaced the package or did not produce a supported test configuration.", compact(baseline))
    if baseline["parameters"]["candidate"] != "supported_vertical_test" or baseline["parameters"]["identity"] != "same_carton":
        return finish("blocked", "Postclosure identity or the safe local test configuration is unresolved; do not reopen.", compact(baseline))
    tb, mb, before = tracking(), marks(baseline), api.state()
    reference = {"frame_id": before["frame_id"], "state": before, "observation": compact(baseline), "mark_ids": baseline["parameters"]["mark_ids"], "landmarks_world_m": None if mb is None else mb["p"].tolist(), "landmark_uncertainty_m": None if mb is None else mb["u"], "tracker_handle": handle, "tracker_reference_frame": tracker_frame, "transform_initial_to_baseline": None if tb is None else tb["t"]["transform_initial_world_to_current_world"], "tracking_uncertainty_m": None if tb is None else tb["u"]}
    save("secure.baseline", reference)
    if tb is None and mb is None:
        return finish("blocked", "Neither a current quality-checked patch nor independent print landmarks supplies a differential baseline. Gripper remains closed.", {"baseline": reference, "review": compact(baseline), "tracking": progress.get("tracking_diagnostic")})
    test_rise = max(0.055, 30*(tb["u"] if tb is not None else mb["u"]))
    if test_rise > 0.075:
        return finish("blocked", "Available measurement uncertainty requires a larger effect than the bounded 75 mm test lane.", reference)
    lift = np.asarray(geo.pad_position(before))
    lift[2] += test_rise
    lift_ok = move("vertical_retention_test", lift.tolist(), before["tcp_quaternion_xyzw"], "close", 26, 0.008, 0.0015)
    after, ta = api.state(), tracking()
    post = api.review("Fresh lift-effect check: is the SAME cream cheese carton between the fingers and visibly separated from the table, or left behind/slipped? Describe its visible extent relative to the fingers. Request m0,m1 at exactly the saved printed physical identities if obtainable, using the other view when occluded; never substitute stationary projections. This is the independent replacement for unavailable tracking, not a request for every corner. Request bowl at the current visible bowl interior center if obtainable.", context={"baseline": reference, "current_state": after, "tracking": progress.get("tracking_diagnostic")}, fields={"identity": ["same_carton", "unknown"], "effect": ["held_with_table_gap", "on_table", "slipped", "unknown"], "marks_clear": "boolean", "visible_extent": {"type": "string", "maxLength": 1200}})
    save("secure.effect_observation", compact(post))
    progress["extent"] = post["parameters"]["visible_extent"]
    if points(post, ("bowl",)) is not None:
        progress["bowl"] = post["points"]["bowl"]
    if post["status"] == "stop":
        return finish("abort", "Effect review requested stop; no release issued.", compact(post))
    ma, pa, pb = marks(post), None, None
    if tb is not None and ta is not None:
        pa = geo.transform(ta["t"]["reference_inlier_world_m"], tb["t"]["transform_initial_world_to_current_world"])
        pb = np.asarray(ta["t"]["current_inlier_world_m"])
        sigma, method = tb["u"]+ta["u"], "rigid_top_patch_compared_with_actual_hand_motion"
    elif mb is not None and ma is not None:
        pa, pb, sigma, method = mb["p"], ma["p"], mb["u"]+ma["u"], "independent_print_landmarks_compared_with_actual_hand_motion"
    if pa is None and post["parameters"]["identity"] == "same_carton" and post["parameters"]["effect"] in ("on_table", "slipped"):
        return finish("needs_replan", "Fresh images show failed acquisition or lost retention, even though the differential measurement is unavailable.", {"baseline": reference, "after": after, "review": compact(post)})
    if pa is None:
        return finish("blocked", "Postlift patch registration and its independent-landmark replacement are unavailable. Do not infer retention from closure or a reached pose.", {"baseline": reference, "after": after, "review": compact(post), "tracking": progress.get("tracking_diagnostic")})
    hd = np.asarray(after["tcp_position_world_m"])-np.asarray(before["tcp_position_world_m"])
    od, error = np.mean(pb-pa, axis=0), float(geo.attachment_error(pa, pb, before, after))
    travel, allowance = float(np.linalg.norm(hd)), max(0.005, 3*sigma)
    report = {"baseline_frame": before["frame_id"], "current_frame": post["frame_id"], "method": method, "actual_hand_translation_m": hd.tolist(), "observed_object_translation_m": od.tolist(), "attachment_error_m": error, "combined_uncertainty_m": sigma, "attachment_allowance_m": allowance, "lift_lease_reached": lift_ok, "fresh_visual_effect": post["parameters"], "current_patch_samples_world_m": pb[:6].tolist(), "current_gripper_qpos_m": after["gripper_qpos_m"]}
    if ta is not None:
        report["propagated_top_outline_world_m"] = geo.transform(g["corners_world_m"], ta["t"]["transform_initial_world_to_current_world"]).tolist()
        report["outline_scope"] = "Rigid propagation of a measured visible top outline, not fresh hidden-boundary or clearance evidence."
    save("secure.retention", report)
    if post["parameters"]["effect"] in ("on_table", "slipped"):
        return finish("needs_replan", "Fresh observation shows failed acquisition or lost retention.", report)
    if not lift_ok:
        return finish("blocked", "The bounded lift lease stopped early; its actual differential effect is preserved without a retry.", report)
    if travel <= 8*sigma or allowance > 0.25*travel:
        return finish("blocked", "Actual test motion is insufficiently observable relative to current residuals and uncertainty.", report)
    if hd[2] < 0.04 or od[2] < 0.035 or error > allowance:
        return finish("needs_replan", "Measured object motion does not follow the actual hand lift within the declared margin.", report)
    if post["parameters"]["identity"] != "same_carton" or post["parameters"]["effect"] != "held_with_table_gap":
        return finish("blocked", "Motion evidence is saved, but fresh identity or visible table separation remains unresolved.", report)
    return finish("stage_complete", "Fresh surface motion follows the actual hand lift and images show the carton clear of the table. Gripper remains closed.", report)

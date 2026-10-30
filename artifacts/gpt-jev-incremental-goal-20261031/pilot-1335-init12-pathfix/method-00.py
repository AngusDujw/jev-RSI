def main(api):
    start = api.state()
    if start["native_steps"] != 0 or start["last_gripper_command"] != "open":
        return {"stage_status": "blocked", "reason": "This initial acquisition method must not replay over prior physical execution or reopen a possible grasp.", "evidence": start, "handoff": {"checkpoints": api.recall(), "state": start}, "completion_proposed": False}
    keys, progress = [], {"phase": "initial_observation", "acknowledged": []}
    questions = {}
    for axis in ("x", "y", "z", "rx", "ry", "rz"):
        subject = ("world position " if len(axis) == 1 else "world rotation-vector component ") + axis[-1]
        questions[axis] = {"type": "choice", "instructions": "For " + subject + ", use state.processed_features.axes." + axis + ".goal_relation: increase -> positive, decrease -> negative, within_tolerance -> hold. Program geometry is measured context, not a contact sensor.", "criteria": {"negative": "Decrease this world component toward the target.", "hold": "This component is within its declared tolerance.", "positive": "Increase this world component toward the target."}}
    questions["gripper"] = {"type": "choice", "instructions": "Use state.processed_features.objective.gripper exactly. Closure requests finger actuation, not a claim of retention.", "criteria": {"open": "The objective requests open.", "close": "The objective requests close.", "keep": "The objective requests keep."}}
    def save(key, value):
        api.checkpoint(key, value)
        if key not in keys:
            keys.append(key)
    def finish(status, reason, evidence):
        state = api.state()
        progress["terminal_status"], progress["reason"], progress["state"] = status, reason, state
        save("secure.progress", progress)
        return {"stage_status": status, "reason": reason, "evidence": evidence, "handoff": {"checkpoint_keys": keys, "state": state, "retention_established": status == "stage_complete", "bowl_reference": progress.get("bowl"), "visible_package_extent": progress.get("visible_extent"), "frames_and_provenance": "All metric points are world metres; poses use xyzw tool-to-world quaternions. Each checkpoint contains observation frames; checkpoint receipts add method/source provenance.", "assumptions": ["The identified carton is rigid. Historical top dimensions and bowl anchors are not current detections.", "No release or transfer has been performed. Preserve the actual gripper command; do not reopen automatically.", "Reobserve the bowl opening, package fit and transfer corridor in the next stage."]}, "completion_proposed": False}
    def points(review, names):
        errors = {e["name"] for e in review["measurement_errors"]}
        if any(n in errors or n not in review["points"] for n in names):
            return None
        if any(review["points"][n]["frame_id"] != review["frame_id"] for n in names):
            return None
        return np.asarray([review["points"][n]["world_m"] for n in names], dtype=float)
    def uncertainty(review, names):
        values = [0.0015]
        for name in names:
            p = review["points"][name]
            cam = api.camera(p["camera"])
            if cam["frame_id"] != review["frame_id"]:
                raise ValueError("Camera and depth frames differ.")
            values.append(2.0 * p["depth_m"] / min(cam["K"][0][0], cam["K"][1][1]))
        return float(max(values))
    uv = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}
    geometry_fields = {"scene": ["flat_carton_on_table", "different", "unknown"], "camera": ["agentview", "robot0_eye_in_hand"], "top_outline": ["clear", "unknown"], "corners_uv": {"type": "array", "items": uv, "minItems": 4, "maxItems": 4}, "approach": ["clear", "obstructed", "unknown"], "notes": "string"}
    def measure(context):
        last = {}
        for attempt in range(2):
            r = api.review("Identify the blue cream cheese carton, not the bowl or stove. Request named actual depth points f0,f1,f2,f3 spread INSIDE its flat top-label face, t0,t1,t2 spread noncollinearly on the adjacent bare support table, and bowl at the visible bowl interior center. Return four true top-face boundary corners in cyclic order as corners_uv in camera; these are ray/plane landmarks, not depth samples. Confirm a flat carton resting on this table and a visibly supported overhead approach/open-finger descent lane. Inspect nearby bowl, stove, plate and bottle against the supplied own finger envelope; do not certify hidden clearance. " + ("Use the best current view." if attempt == 0 else "Replacement measurement: use the other attainable camera or different interior depth-valid patches; preserve physical identity and do not repeat failed boundary depth samples."), context={"reference": context, "previous_failure": last, "own_geometry": api.state()["own_geometry"]}, fields=geometry_fields)
            valid = {n: p for n, p in r["points"].items() if n in ("f0", "f1", "f2", "f3", "t0", "t1", "t2", "bowl")}
            last = {"frame_id": r["frame_id"], "parameters": r["parameters"], "valid_points": valid, "measurement_errors": r["measurement_errors"]}
            save("secure.measurements", last)
            if r["status"] == "stop":
                return None, "abort", "Observation review requested stop."
            p = r["parameters"]
            if p["scene"] == "different":
                return None, "needs_replan", "The target or its support differs from the planned initial scene."
            if p["approach"] == "obstructed":
                return None, "blocked", "Observed approach is obstructed: " + p["notes"][:700]
            names = ("f0", "f1", "f2", "f3", "t0", "t1", "t2", "bowl")
            xyz = points(r, names)
            if xyz is None or p["scene"] != "flat_carton_on_table" or p["top_outline"] != "clear" or p["approach"] != "clear":
                last["gap"] = "Missing depth, ambiguous top/support identity, or unsupported approach."
                continue
            try:
                top, table = geo.plane(xyz[:4]), geo.plane(xyz[4:7])
                a, b = np.asarray(top["coefficients"]), np.asarray(table["coefficients"])
                u = max(uncertainty(r, names[:7]), 2.0 * float(top["rms_m"]), 2.0 * float(table["rms_m"]))
                if a[2] < 0.99 or b[2] < 0.995 or max(top["rms_m"], table["rms_m"]) > 0.002 or min(top["in_plane_spread_m"]) < 2.5*u or min(table["in_plane_spread_m"]) < 3*u:
                    raise ValueError("Top/table horizontal-plane fit or spread-to-noise margin is inadequate.")
                corners = np.asarray([api.plane_point(p["camera"], pixel, a.tolist())["world_m"] for pixel in p["corners_uv"]])
                edges = np.roll(corners, -1, axis=0) - corners
                lengths = np.linalg.norm(edges, axis=1)
                if min(lengths) < 6*u or max(abs(lengths[0]-lengths[2]), abs(lengths[1]-lengths[3])) > 4*u or abs(float(np.dot(edges[0], edges[1]))) > 0.25*lengths[0]*lengths[1]:
                    raise ValueError("Visible top outline does not adequately support a rectangular pinch model.")
                center = np.mean(corners, axis=0)
                table_z = float(-(b[0]*center[0]+b[1]*center[1]+b[3])/b[2])
                height = float(center[2]-table_z)
                if height <= 2*u:
                    raise ValueError("Package side height is unresolved above the support plane.")
                long_axis = edges[0 if lengths[0] >= lengths[1] else 1].copy()
                long_axis[2] = 0.0
                long_axis /= np.linalg.norm(long_axis)
                g = {"frame_id": r["frame_id"], "camera": p["camera"], "corners_uv": p["corners_uv"], "corners_world_m": corners.tolist(), "center_world_m": center.tolist(), "long_axis": long_axis.tolist(), "length_m": float(max(lengths)), "width_m": float(min(lengths)), "height_m": height, "table_z_m": table_z, "top_plane": a.tolist(), "table_plane": b.tolist(), "uncertainty_m": u, "bowl": r["points"]["bowl"]}
                return g, "", ""
            except Exception as error:
                last["gap"] = str(error)[:900]
        return None, "blocked", "Bounded alternative geometry measurement failed: " + str(last)[:4500]
    def vertices(state):
        own = state["own_geometry"]
        lo, hi = own["finger_low_offset_tool_m"], own["finger_high_offset_tool_m"]
        return np.asarray([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    def grasp_plan(g):
        state = api.state()
        axis = np.asarray(g["long_axis"])
        if np.dot(axis, geo.rotation(state["tcp_quaternion_xyzw"])[:, 0]) < 0:
            axis = -axis
        yaw = math.atan2(float(axis[1]), float(axis[0]))
        q = [math.cos(yaw/2), math.sin(yaw/2), 0.0, 0.0]
        rotation, own = geo.rotation(q), state["own_geometry"]
        relative = (vertices(state)-np.asarray(own["pad_center_in_tool_m"])) @ rotation.T
        radius = float(max(np.linalg.norm(relative, axis=1)))
        margin = 0.002 + 2*g["uncertainty_m"] + 0.0015 + 0.02*radius
        target = list(g["center_world_m"])
        target[2] = max(g["table_z_m"]-float(min(relative[:, 2]))+margin, target[2]-0.005)
        half = float(np.dot(np.abs(rotation[2]), np.asarray(own["pad_extent_in_tool_m"]))/2)
        overlap = min(g["center_world_m"][2], target[2]+half)-max(g["table_z_m"], target[2]-half)
        span_proxy = sum(abs(x) for x in state["gripper_qpos_m"])
        if overlap < 0.003+2*g["uncertainty_m"] or g["width_m"]+2*(0.004+g["uncertainty_m"]) >= span_proxy:
            return None
        return {"target": target, "quaternion": q, "table_margin_m": margin, "side_overlap_m": overlap, "joint_open_span_proxy_m": span_proxy, "span_scope": "Necessary aperture screen only; fresh images must confirm both open fingers clear the carton sides."}
    def move(phase, target, quaternion, gripper, calls, limit):
        progress["phase"] = phase
        save("secure.progress", progress)
        before = api.state()
        cap = min(calls, before["budgets"]["jev_remaining"], int(before["budgets"]["native_steps_remaining"]/3))
        if cap < 1:
            return False
        r = api.drive(target, quaternion, gripper, questions, features={"phase": phase, "reference_geometry": progress.get("grasp"), "geometry_scope": "Pre-action measured local geometry; no contact or retention sensor."}, tool_point="pad_center", max_calls=cap, translation_limit=limit, rotation_limit=0.07, steps=3, position_tolerance=0.0015, rotation_tolerance=0.02)
        progress["last_receipt"] = r
        progress["acknowledged"].append({"phase": phase, "frame_id": r["frame_id"], "status": r["status"], "state_after": api.state()})
        save("secure.progress", progress)
        return r["status"] == "reached" and r["choices"]["gripper"] == gripper
    g0, status, reason = measure({"stage": "initial", "high_lateral_route_first": True})
    if g0 is None:
        return finish(status, reason, progress)
    plan = grasp_plan(g0)
    if plan is None:
        return finish("blocked", "Measured width, finger/table clearance and side-overlap margins do not support this pinch.", g0)
    progress["grasp"], progress["bowl"] = plan, g0["bowl"]
    save("secure.geometry", {"initial": g0, "grasp": plan})
    high = list(plan["target"])
    high[2] = max(float(geo.pad_position(api.state())[2]), g0["center_world_m"][2]+0.12)
    hover = list(plan["target"])
    hover[2] = max(hover[2], g0["center_world_m"][2])+0.08
    if not move("high_lateral_alignment", high, plan["quaternion"], "open", 24, 0.02) or not move("vertical_hover", hover, plan["quaternion"], "open", 26, 0.02):
        return finish("blocked", "Approach lease did not reach its bounded pose objective; no contact retry.", progress)
    g, status, reason = measure({"stage": "fresh_hover_validation", "previous_geometry": g0, "intended_grasp": plan})
    if g is None:
        return finish(status, reason, progress)
    if np.linalg.norm(np.asarray(g["center_world_m"])-np.asarray(g0["center_world_m"])) > 3*(g["uncertainty_m"]+g0["uncertainty_m"]):
        return finish("needs_replan", "Target position changed beyond the measured noncontact uncertainty.", {"initial": g0, "current": g})
    plan = grasp_plan(g)
    if plan is None:
        return finish("blocked", "Fresh close-range geometry fails the pinch margin.", g)
    progress["grasp"], progress["bowl"] = plan, g["bowl"]
    save("secure.geometry", {"initial": g0, "precontact": g, "grasp": plan})
    handle = None
    polygon = np.asarray(g["corners_uv"], dtype=float)
    polygon = 0.72*polygon + 0.28*np.mean(polygon, axis=0)
    try:
        init = api.track_init(g["camera"], polygon.tolist())
        handle = init["handle"]
        save("secure.tracker", {"handle": handle, "identity": "Cream cheese carton top-label surface only", "camera": g["camera"], "polygon": polygon.tolist(), "reference_frame_id": init["frame_id"], "geometry_checkpoint": "secure.geometry", "geometry_member": "precontact"})
    except Exception as error:
        progress["tracker_initialization_gap"] = str(error)[:700]
    def tracked():
        if handle is None:
            return None
        try:
            t = api.track_update(handle)
            progress["tracking_diagnostic"] = {"status": t["status"], "frame_id": t["frame_id"], "reason": t.get("reason", "")}
            if t["status"] != "tracked":
                return None
            fit = geo.plane(t["current_inlier_world_m"])
            u = max(0.001, float(t["rms_m"]), float(t["uncertainty_floor_m"]))
            if t["inliers"] < 12 or t["inliers"]/max(1, t["matches"]) < 0.65 or t["rms_m"] > 0.0025 or fit["rms_m"] > 0.0025 or min(fit["in_plane_spread_m"]) < 3*u:
                progress["tracking_diagnostic"]["reason"] = "Insufficient rigid top-patch registration quality or spatial support relative to noise."
                return None
            return {"data": t, "u": u}
        except Exception as error:
            progress["tracking_diagnostic"] = {"reason": str(error)[:700]}
            return None
    tracked()
    if not move("open_finger_descent", plan["target"], plan["quaternion"], "open", 14, 0.006):
        return finish("blocked", "Descent stalled or exhausted its lease; do not repeat contact.", progress)
    state = api.state()
    world_fingers = vertices(state) @ geo.rotation(state["tcp_quaternion_xyzw"]).T + np.asarray(state["tcp_position_world_m"])
    table = np.asarray(g["table_plane"])
    floor_gap = float(min(world_fingers @ table[:3] + table[3]))
    ready = api.review("Fresh preclosure check only: identify the same carton between the OPEN fingers, with both pinch sides clear and no unintended bowl/table contact. Assess the short upward test lane too. Do not infer retention. No full perimeter reconstruction is needed.", context={"geometry": g, "grasp": plan, "measured_own_finger_table_gap_m": floor_gap}, fields={"pinch": ["aligned", "misaligned", "unknown"], "upward_lane": ["clear", "obstructed", "unknown"], "identity": ["same_carton", "unknown"]})
    if ready["status"] == "stop":
        return finish("abort", "Preclosure review requested stop.", ready)
    if floor_gap < g["uncertainty_m"]+0.001 or ready["parameters"] != {"pinch": "aligned", "upward_lane": "clear", "identity": "same_carton"}:
        return finish("blocked", "Fresh open-finger alignment or table clearance is unsupported; no closure issued.", {"review": ready, "own_finger_gap_m": floor_gap})
    for hold in range(2):
        r = api.control(plan["target"], plan["quaternion"], "close", questions, features={"phase": "bounded_closure", "closure_index": hold, "side_overlap_m": plan["side_overlap_m"], "retention_not_yet_tested": True}, tool_point="pad_center", translation_limit=0.003, rotation_limit=0.03, steps=3, position_tolerance=0.0015, rotation_tolerance=0.02)
        progress["phase"], progress["last_receipt"], progress["state"] = "closure_acknowledged", r, api.state()
        save("secure.progress", progress)
        if r["status"] == "stalled" or r["choices"]["gripper"] != "close":
            return finish("blocked", "Closure produced a stall or command mismatch; preserve the actual grasp state.", progress)
    baseline = api.review("After closure, is the same carton still a supported pinch candidate with an unobstructed 55 mm vertical test lane? This is NOT a retention judgment. If obtainable, request m0 and m1 at two independently recognizable printed landmarks on its visible top-label surface, and describe their exact physical identities in mark0 and mark1. Do not require perimeter corners. Set marks_clear false and omit failed measurements if occluded; a quality-checked patch tracker is an alternative.", context={"geometry": g, "tracker_handle": handle}, fields={"candidate": ["supported_test", "misaligned", "unknown"], "identity": ["same_carton", "unknown"], "marks_clear": "boolean", "mark0": "string", "mark1": "string"})
    if baseline["status"] == "stop":
        return finish("abort", "Postclosure review requested stop.", baseline)
    if baseline["parameters"]["candidate"] != "supported_test" or baseline["parameters"]["identity"] != "same_carton":
        return finish("blocked", "The fresh postclosure configuration does not support the bounded lift test.", baseline)
    def landmarks(r):
        p = points(r, ("m0", "m1"))
        if not r["parameters"]["marks_clear"] or p is None:
            return None
        u = uncertainty(r, ("m0", "m1"))
        return {"points": p, "u": u} if np.linalg.norm(p[1]-p[0]) > 4*u else None
    tb, mb, before = tracked(), landmarks(baseline), api.state()
    ref = {"frame_id": before["frame_id"], "state": before, "landmark_ids": [baseline["parameters"]["mark0"], baseline["parameters"]["mark1"]], "landmarks_world_m": None if mb is None else mb["points"].tolist(), "landmark_uncertainty_m": None if mb is None else mb["u"], "tracker_handle": handle, "tracking_transform": None if tb is None else tb["data"]["transform_initial_world_to_current_world"], "tracking_uncertainty_m": None if tb is None else tb["u"], "reference_geometry": "secure.geometry/precontact"}
    save("secure.baseline", ref)
    if tb is None and mb is None:
        return finish("blocked", "Neither the current top patch nor independent visible print landmarks supplies a differential baseline. The gripper remains closed.", {"baseline": ref, "tracking": progress.get("tracking_diagnostic"), "measurement_errors": baseline["measurement_errors"]})
    lift = np.asarray(geo.pad_position(before), dtype=float)
    lift[2] += 0.055
    if not move("vertical_retention_test", lift.tolist(), before["tcp_quaternion_xyzw"], "close", 16, 0.008):
        return finish("blocked", "Lift did not reach its bounded target; preserve acknowledged motion and do not retry contact.", {"baseline": ref, "progress": progress})
    after, ta = api.state(), tracked()
    post = api.review("Fresh lift-effect check. Is the SAME carton above the table with a visible gap, still between the fingers, rather than left on the table or slipped? Describe its visible extent relative to the fingers. If the baseline print landmarks are visible, request m0 and m1 at exactly those physical features, not stationary projections or convenient new pixels; marks_clear means both identities match. Prefer the other camera when occluded. Also request bowl at the current visible bowl interior center if obtainable. Do not require all historical corners.", context={"baseline": ref, "current_state": after, "tracking_quality": progress.get("tracking_diagnostic")}, fields={"identity": ["same_carton", "unknown"], "effect": ["held_with_visible_table_gap", "on_table", "slipped", "unknown"], "marks_clear": "boolean", "visible_extent": "string"})
    progress["visible_extent"] = post["parameters"]["visible_extent"][:1400]
    if points(post, ("bowl",)) is not None:
        progress["bowl"] = post["points"]["bowl"]
    if post["status"] == "stop":
        return finish("abort", "Lift-effect review requested stop; no release issued.", post)
    ma = landmarks(post)
    pa, pb, sigma, method = None, None, None, None
    if tb is not None and ta is not None:
        pa = geo.transform(ta["data"]["reference_inlier_world_m"], tb["data"]["transform_initial_world_to_current_world"])
        pb = np.asarray(ta["data"]["current_inlier_world_m"])
        sigma, method = tb["u"]+ta["u"], "quality_checked_rigid_top_patch"
    elif mb is not None and ma is not None:
        pa, pb, sigma, method = mb["points"], ma["points"], mb["u"]+ma["u"], "independently_identified_print_landmarks"
    if pa is None:
        return finish("blocked", "Postlift registration and its independent-landmark replacement are both unavailable. No retention inference from closure or commanded pose.", {"baseline": ref, "current_state": after, "post_review": post, "tracking": progress.get("tracking_diagnostic")})
    hand_delta = np.asarray(after["tcp_position_world_m"])-np.asarray(before["tcp_position_world_m"])
    object_delta = np.mean(pb-pa, axis=0)
    error = float(geo.attachment_error(pa, pb, before, after))
    travel = float(np.linalg.norm(hand_delta))
    allowance = max(0.005, 3*sigma)
    report = {"method": method, "baseline_frame": before["frame_id"], "current_frame": post["frame_id"], "actual_hand_translation_m": hand_delta.tolist(), "measured_package_translation_m": object_delta.tolist(), "attachment_error_m": error, "combined_uncertainty_heuristic_m": sigma, "attachment_allowance_m": allowance, "visible_effect": post["parameters"], "current_patch_points_world_m": pb[:8].tolist(), "gripper_state": after["gripper_qpos_m"]}
    if ta is not None:
        report["tracked_top_extent_estimate_world_m"] = geo.transform(g["corners_world_m"], ta["data"]["transform_initial_world_to_current_world"]).tolist()
        report["extent_scope"] = "Rigid propagation of measured precontact top outline; not newly observed hidden boundaries or a clearance certificate."
    save("secure.retention", report)
    if post["parameters"]["effect"] in ("on_table", "slipped"):
        return finish("needs_replan", "Fresh observation shows that acquisition failed or retention was lost.", report)
    if travel <= 8*sigma or allowance > 0.25*travel:
        return finish("blocked", "Differential motion is not sufficiently observable relative to measurement uncertainty.", report)
    if hand_delta[2] < 0.04 or object_delta[2] < 0.035 or error > allowance:
        return finish("needs_replan", "Measured package motion does not adequately follow actual hand motion in the lift test.", report)
    if post["parameters"]["identity"] != "same_carton" or post["parameters"]["effect"] != "held_with_visible_table_gap":
        return finish("blocked", "Differential measurements are preserved, but fresh package identity or visible table separation remains unresolved.", report)
    return finish("stage_complete", "Fresh image/depth evidence shows the carton clear of the table and following the actual measured hand lift. The gripper remains closed.", report)

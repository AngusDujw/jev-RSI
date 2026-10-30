def main(api):
    logs, keys = [], []
    s0 = api.state()
    def save(key, value):
        api.checkpoint(key, value)
        if key not in keys: keys.append(key)
    def result(status, reason, extra=None):
        return {"stage_status": status, "reason": reason, "evidence": {"events": logs[-10:], "detail": extra}, "handoff": {"stage": "secure", "checkpoint_keys": keys, "state": api.state(), "frames": "All metric coordinates are world meters; quaternions are tool-to-world xyzw.", "assumptions": "Do not reopen. Check actual holding state before further motion. Geometry in secure.geometry is historical after contact. Current patch observations are not a complete package pose. Bowl observations do not authorize transport or release."}, "completion_proposed": False}
    def fail(gate, action, operands, reason, status="blocked"):
        d = {"gate": gate, "prevented_action": action, "operands_and_margins": operands, "observation_frame": api.state()["frame_id"], "reason": reason}
        save("secure.failure", d)
        return result(status, reason, d)
    def valid(r, name):
        return name in r["points"] and not any(e["name"] == name for e in r["measurement_errors"])
    def points(r, names):
        return np.array([r["points"][n]["world_m"] for n in names], dtype=float)
    def review(question, context, fields):
        r = api.review(question, context=context, fields=fields)
        logs.append({"review_frame": r["frame_id"], "parameters": r["parameters"], "measurement_errors": r["measurement_errors"]})
        return r
    questions = {}
    for axis in ["x", "y", "z", "rx", "ry", "rz"]:
        subject = "world translation " + axis if len(axis) == 1 else "world rotation-vector " + axis[1]
        questions[axis] = {"type": "choice", "instructions": "Control " + subject + " using its supplied goal_relation only. Select negative for decrease, positive for increase, and hold for within_tolerance. The program, not you, measured geometry and authorized this local action. Do not infer object pose or contact.", "criteria": {"negative": "Decrease this world component when its goal_relation is decrease.", "hold": "Zero this component when its goal_relation is within_tolerance.", "positive": "Increase this world component when its goal_relation is increase."}}
    questions["gripper"] = {"type": "choice", "instructions": "Use state.processed_features.objective.gripper exactly. This is a commanded actuator choice, not a grasp assessment.", "criteria": {"open": "Open only for objective gripper open.", "close": "Close only for objective gripper close.", "keep": "Preserve the previous gripper actuation for objective gripper keep."}}
    def errors(s, target, q):
        p = float(np.linalg.norm(geo.pad_position(s) - np.array(target)))
        a = 2 * math.acos(min(1.0, abs(float(np.dot(s["tcp_quaternion_xyzw"], q)))))
        return p, a
    def drive(target, q, phase, cap, reserve, tol=0.003, speed=0.02):
        used = 0
        for lease in range(5):
            before = api.state(); b = before["budgets"]
            n = min(24, cap-used, int(b["jev_remaining"])-reserve, int((b["native_steps_remaining"]-3*reserve)//3))
            if n < 1: return {"phase": phase, "reason": "No remaining bounded control allowance; no new motion authorized.", "used": used}
            eb = errors(before, target, q)
            receipt = api.drive(target, q, "keep", questions, features={"source": "program_measured_geometry_and_proprioception", "phase": phase, "authorized_local_target_world_m": target, "geometry_checkpoint": "secure.geometry", "guard_m": guard, "no_object_effect_inferred_from_pose": True}, max_calls=n, tool_point="pad_center", translation_limit=speed, rotation_limit=0.08, steps=3, position_tolerance=tol, rotation_tolerance=0.025)
            after = api.state(); ea = errors(after, target, q); used += receipt["lease_calls"]
            progress = {"phase": phase, "receipt_status": receipt["status"], "lease_calls": receipt["lease_calls"], "before_state": before, "after_state": after, "position_gain_m": eb[0]-ea[0], "rotation_gain_rad": eb[1]-ea[1], "remaining_position_error_m": ea[0]}
            save("secure.progress", progress); logs.append(progress)
            if receipt["choices"]["gripper"] != "keep": return {"phase": phase, "reason": "Gripper command mismatch; inspect actual state.", "receipt": receipt}
            if receipt["status"] == "reached": return None
            if receipt["status"] == "stalled": return {"phase": phase, "reason": "Stalled local motion; do not repeat contact.", "progress": progress}
            if receipt["status"] != "lease_exhausted" or (eb[0]-ea[0] < 0.0005 and eb[1]-ea[1] < 0.005):
                return {"phase": phase, "reason": "No independent whole-lease progress toward the authorized pose.", "progress": progress}
        return {"phase": phase, "reason": "Finite feedback allowance ended; actual progress is checkpointed."}
    pixel = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}
    fields = {"identity": ["cream_cheese_on_counter", "different_state", "unknown"], "top_boundary": ["four_visible_corners", "unknown"], "camera": ["agentview", "robot0_eye_in_hand"], "corners": {"type": "array", "items": pixel, "minItems": 4, "maxItems": 4}, "p0_identity": "string", "same_counter_support": "boolean", "empty_open_hand": "boolean", "notes": "string"}
    geometry_ok = False
    for attempt in range(2):
        r = review("Measure only the cream cheese package grasp geometry. Request p0,p1,p2,p3 as named depth points well distributed on the flat upper face, safely inside its edges. Make p0 a distinctive printed physical landmark and describe it in p0_identity. Request t0,t1,t2 as named depth points on the counter supporting this package, distributed around it, not on nearby objects. Identify the four actual upper-face corners in clockwise order as corners pixel pairs in camera; mixed-depth corner pixels will be ray-intersected with the measured face plane. Do not invent hidden corners. Check the hand is empty and open. On this replacement attempt use the other useful view or different valid interior depth patches rather than repeating a failed sample.", {"attempt": attempt, "state": s0}, fields)
        if r["status"] == "stop": return result("abort", "Observation requested stop.")
        save("secure.partial", {"frame": r["frame_id"], "parameters": r["parameters"], "points": r["points"], "measurement_errors": r["measurement_errors"]})
        p = r["parameters"]
        if p["identity"] == "different_state" or not p["empty_open_hand"]: return result("needs_replan", "Entry condition is not an empty open hand with the package on the counter.")
        names = ["p0", "p1", "p2", "p3", "t0", "t1", "t2"]
        if p["identity"] != "cream_cheese_on_counter" or p["top_boundary"] != "four_visible_corners" or not p["same_counter_support"] or not all(valid(r,n) for n in names): continue
        try:
            top, table = geo.plane(points(r,names[:4])), geo.plane(points(r,names[4:]))
            guard = max(0.0015, 2*float(top["rms_m"]), 2*float(table["rms_m"]))
            margins = {"top_horizontal": float(top["coefficients"][2])-0.985, "counter_horizontal": float(table["coefficients"][2])-0.995, "residual_guard_limit_m": 0.003-guard, "top_spread_vs_guard_m": min(top["in_plane_spread_m"])-4*guard, "table_spread_vs_guard_m": min(table["in_plane_spread_m"])-4*guard}
            save("secure.plane_check", {"frame": r["frame_id"], "top": top, "table": table, "guard_m": guard, "guard_provenance": "Design depth/landmark guard 0.0015 m or twice measured fit RMS, whichever is larger; not a calibrated confidence bound.", "residual_margins": margins})
            if not all(v >= 0 for v in margins.values()): continue
            corners = np.array([api.plane_point(p["camera"], px, top["coefficients"])["world_m"] for px in p["corners"]])
            geometry_ok = True
            break
        except Exception as exc:
            save("secure.measurement_error", {"frame": r["frame_id"], "error": str(exc), "action_not_authorized": "grasp approach"})
    if not geometry_ok: return fail("identity_depth_or_plane_quality", "grasp approach", {"last_partial": "secure.partial", "plane_diagnostics": "secure.plane_check", "attempts": 2}, "No quality-checked current upper face and supporting counter geometry.")
    center = np.mean(corners, axis=0); edges = np.roll(corners,-1,axis=0)-corners
    lengths = np.linalg.norm(edges[:,:2],axis=1)
    width, length = float(min(lengths)), float(max(lengths))
    rectangle_error = max(float(np.linalg.norm(corners[0]+corners[2]-corners[1]-corners[3])), abs(float(np.dot(edges[0,:2],edges[1,:2])))/max(length,0.0001), abs(float(lengths[0]-lengths[2])), abs(float(lengths[1]-lengths[3])))
    if rectangle_error > 3*guard+0.002: return fail("rectangular_face_model", "side grasp", {"error_m": rectangle_error, "threshold_m": 3*guard+0.002, "residual_margin_m": 3*guard+0.002-rectangle_error, "corners_world_m": corners.tolist(), "frame": r["frame_id"]}, "Visible boundary does not support the proposed rectangular side grasp.")
    long_axis = edges[int(np.argmax(lengths)),:2]
    if float(np.dot(long_axis,geo.rotation(s0["tcp_quaternion_xyzw"])[:2,0])) < 0: long_axis = -long_axis
    yaw = math.atan2(float(long_axis[1]),float(long_axis[0]))
    q = api.compose([1.0,0.0,0.0,0.0],[0.0,0.0,yaw]); rot = geo.rotation(q)
    tp = table["coefficients"]; table_z = -(tp[0]*center[0]+tp[1]*center[1]+tp[3])/tp[2]
    height = float(center[2]-table_z); own = s0["own_geometry"]
    lo, hi, off = np.array(own["finger_low_offset_tool_m"]), np.array(own["finger_high_offset_tool_m"]), np.array(own["pad_center_in_tool_m"])
    envelope = np.array([[x,y,z] for x in [lo[0],hi[0]] for y in [lo[1],hi[1]] for z in [lo[2],hi[2]]])
    bottom_offset = float(np.min((envelope-off).dot(rot.T)[:,2]))
    half_pad_z = float(np.dot(np.abs(rot[2]),np.array(own["pad_extent_in_tool_m"]))/2)
    grasp_tol = 0.002
    grasp_z = float(max(table_z+height/2,table_z-bottom_offset+guard+grasp_tol+0.003))
    overlap = float(min(center[2],grasp_z+half_pad_z)-max(table_z,grasp_z-half_pad_z))
    aperture = abs(float(s0["gripper_qpos_m"][0]-s0["gripper_qpos_m"][1]))-max(own["pad_extent_in_tool_m"][0],own["pad_extent_in_tool_m"][2])
    needed_aperture = width+2*(guard+grasp_tol)+length*0.025/2+0.001
    geom = {"frame": r["frame_id"], "top_plane": top, "counter_plane": table, "upper_corners_world_m": corners.tolist(), "center_world_m": center.tolist(), "width_m": width, "length_m": length, "height_m": height, "quaternion_xyzw": q, "grasp_pad_z_m": grasp_z, "guard_m": guard, "grasp_tolerance_m": grasp_tol, "finger_bottom_offset_m": bottom_offset, "side_overlap_m": overlap, "nominal_usable_aperture_m": aperture, "required_aperture_m": needed_aperture, "aperture_assumption": "Symmetric prismatic joint separation less one transverse pad-size allowance is a conservative screening model, not measured inner-face clearance; fresh visible straddling is also required.", "p0_identity": p["p0_identity"]}
    save("secure.geometry", geom)
    gm = {"positive_height_m": height-3*guard, "side_overlap_m": overlap-(0.005+grasp_tol), "aperture_screen_m": aperture-needed_aperture}
    if not all(v >= 0 for v in gm.values()): return fail("grasp_geometry", "descent and closure", {"geometry": geom, "residual_margins_m": gm}, "The measured package and own finger geometry do not support this grasp margin.")
    high = geo.pad_position(api.state()).tolist(); high[0], high[1] = float(center[0]), float(center[1])
    pre = [float(center[0]),float(center[1]),float(center[2]+0.065)]
    action_fields = {"clear": ["clear", "blocked", "unknown"], "package_state": ["unchanged", "moved", "unknown"], "notes": "string"}
    for phase, target, cap, reserve in [("high_alignment",high,48,60),("vertical_pregrasp",pre,55,40)]:
        ar = review("Authorize ONLY "+phase+". Assess the actual open hand swept path to this pad-center target and orientation, including fingers and nearby bowl, bottle, stove and cabinet. The high alignment stays at current altitude; vertical_pregrasp stops 65 mm above the package top. Do not require retention or later bowl fit. Confirm the measured package has not moved. Unknown is not clear.", {"geometry": geom, "target_pad_world_m": target, "target_quaternion_xyzw": q, "state": api.state()}, action_fields)
        if ar["status"] == "stop": return result("abort", "Observation requested stop.")
        if ar["parameters"]["package_state"] == "moved": return result("needs_replan", "Package moved before contact.")
        if ar["parameters"]["clear"] != "clear" or ar["parameters"]["package_state"] != "unchanged": return fail("local_approach_review",phase,ar["parameters"],"This local approach is not supported by current visible evidence.")
        error = drive(target,q,phase,cap,reserve)
        if error is not None: return result("blocked",error["reason"],error)
    descent_fields = {"clear": ["clear", "blocked", "unknown"], "straddling": ["yes", "no", "unknown"], "package_state": ["unchanged", "moved", "unknown"], "notes": "string"}
    descent_ok = False
    for attempt in range(2):
        dr = review("Authorize only the straight vertical descent to the supplied grasp pad height, still keeping the gripper open. Confirm open fingers align outside the two short-width opposing sides, with unobstructed side gaps and no bowl/stove/counter interference along the supplied own-finger envelope. Request named top_center as a valid depth point at the geometric center of the flat package top. If its depth is occluded, request the previously identified printed landmark as named p0 instead; do not sample the hand. On a retry use the other view, not the same occluded point.", {"geometry": geom, "target_pad_world_m": [float(center[0]),float(center[1]),grasp_z], "attempt": attempt}, descent_fields)
        if dr["status"] == "stop": return result("abort","Observation requested stop.")
        if dr["parameters"]["package_state"] == "moved": return result("needs_replan","Package has shifted; old grasp alignment is stale.")
        sample = "top_center" if valid(dr,"top_center") else ("p0" if valid(dr,"p0") else None)
        if sample is None: continue
        reference = center if sample == "top_center" else np.array(r["points"]["p0"]["world_m"])
        delta = np.array(dr["points"][sample]["world_m"])-reference
        drift_limit = guard+0.003
        check = {"sample": sample, "delta_world_m": delta.tolist(), "threshold_m": drift_limit, "residual_margin_m": drift_limit-float(np.linalg.norm(delta)), "reference_frame": r["frame_id"], "current_frame": dr["frame_id"], "uncertainty_guard_m": guard}
        save("secure.alignment",check)
        if float(np.linalg.norm(delta)) > drift_limit: return fail("current_package_alignment","descent",check,"Fresh package measurement disagrees with the planned grasp; update its actual geometry.","needs_replan")
        if dr["parameters"]["clear"] == "clear" and dr["parameters"]["straddling"] == "yes" and dr["parameters"]["package_state"] == "unchanged": descent_ok = True; break
        if dr["parameters"]["clear"] == "blocked" or dr["parameters"]["straddling"] == "no": break
    if not descent_ok: return fail("open_finger_descent","descent",dr["parameters"],"Current side clearance or alignment remains unresolved.")
    target = [float(center[0]),float(center[1]),grasp_z]
    error = drive(target,q,"open_descent",28,22,grasp_tol,0.01)
    if error is not None: return result("blocked",error["reason"],error)
    cr = review("Authorize closure only, with no further descent. Are opposing pads alongside the cream cheese package, rather than over its top, under it, or against the counter or another object? Has the package remained at the measured location? Do not call this retention.", {"geometry": geom, "state": api.state()}, {"closure": ["safe", "blocked", "unknown"], "package_state": ["unchanged", "moved", "unknown"], "notes": "string"})
    if cr["status"] == "stop": return result("abort","Observation requested stop.")
    if cr["parameters"]["package_state"] == "moved": return result("needs_replan","Contact changed package location before closure.")
    if cr["parameters"]["closure"] != "safe" or cr["parameters"]["package_state"] != "unchanged": return fail("closure_clearance","close fingers",cr["parameters"],"Closure is not supported; no blind contact retry.")
    if api.state()["budgets"]["jev_remaining"] < 16: return result("blocked","Insufficient control budget reserved for closure and retention test.")
    for dwell in range(3):
        st = api.state(); command = "close" if dwell == 0 else "keep"
        rc = api.control(geo.pad_position(st).tolist(),st["tcp_quaternion_xyzw"],command,questions,features={"source": "program_closure_gate", "phase": "close_then_two_fixed_pose_settling_updates", "closure_review_frame": cr["frame_id"], "dwell_index": dwell},tool_point="pad_center",translation_limit=0.001,rotation_limit=0.01,steps=3,position_tolerance=0.003,rotation_tolerance=0.025)
        save("secure.progress",{"phase":"closure_dwell","dwell":dwell,"receipt":rc,"state":api.state()})
        if rc["status"] == "stalled" or rc["choices"]["gripper"] != command: return result("blocked","Closure feedback or command mismatch requires inspection; do not reopen.",rc)
    patch_fields = {"candidate_contact": ["yes", "no", "unknown"], "lift_path": ["clear", "blocked", "unknown"], "patch_identity": ["package", "unknown"], "camera": ["agentview", "robot0_eye_in_hand"], "polygon": {"type": "array", "items": pixel, "minItems": 0, "maxItems": 16}, "landmark_ids": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3}, "notes": "string"}
    def quality(t):
        if t["status"] != "tracked": return {"ok":False,"reason":t.get("reason","unknown registration")}
        u = max(0.001,float(t["rms_m"]),float(t["uncertainty_floor_m"]))
        spreads = sorted(np.atleast_1d(t["inlier_spread_m"]).tolist(),reverse=True)
        ok = t["inliers"] >= 12 and t["inliers"]/max(1,t["matches"]) >= 0.6 and u <= 0.003 and len(spreads) >= 2 and spreads[0] >= 4*u and spreads[1] >= 2*u
        return {"ok":bool(ok),"guard_m":u,"rms_m":float(t["rms_m"]),"spread_m":spreads,"inliers":t["inliers"],"matches":t["matches"],"frame":t["frame_id"]}
    handle, tb, qb, baseline, mark_names = None, None, None, None, []
    for attempt in range(2):
        br = review("Assess a candidate grasp, NOT proven retention, and authorize only a 55 mm straight upward test with unchanged orientation and closed actuation. Identify a CURRENT visible textured surface patch belonging to this package, even if the perimeter is occluded; give a tight 3-16 vertex polygon excluding fingers/background, or [] if unavailable. Request b0,b1,b2 as depth points at independently recognizable physical printed or shape landmarks on any currently visible package surface; describe identities in matching landmark_ids. They need not be historical corners. Two separated valid landmarks can replace tracking. On retry use a different exposed patch or the other view, not unchanged occluded evidence.", {"geometry":geom,"attempt":attempt,"state":api.state()},patch_fields)
        if br["status"] == "stop": return result("abort","Observation requested stop.")
        if br["parameters"]["candidate_contact"] == "no": return result("needs_replan","Closure did not establish a credible contact candidate; do not blindly retry.")
        if br["parameters"]["lift_path"] == "blocked": return fail("test_lift_clearance","55 mm test lift",br["parameters"],"Established obstruction prevents the lift.")
        mark_names = [n for n in ["b0","b1","b2"] if valid(br,n) and br["parameters"]["landmark_ids"][int(n[1])]]
        baseline = {"frame":br["frame_id"],"landmark_ids":br["parameters"]["landmark_ids"],"points":{n:br["points"][n] for n in mark_names},"parameters":br["parameters"]}
        save("secure.baseline",baseline)
        if br["parameters"]["patch_identity"] == "package" and len(br["parameters"]["polygon"]) >= 3:
            try:
                init = api.track_init(br["parameters"]["camera"],br["parameters"]["polygon"]); handle = init["handle"]
                tb = api.track_update(handle); qb = quality(tb)
                save("secure.tracker",{"handle":handle,"identity":"Current cream cheese surface selected after closure","camera":br["parameters"]["camera"],"polygon":br["parameters"]["polygon"],"creation_receipt":init,"current_quality":qb})
            except Exception as exc:
                qb = {"ok":False,"reason":str(exc)}
        landmark_ok = len(mark_names) >= 2 and float(np.max(np.linalg.norm(points(br,mark_names)-np.mean(points(br,mark_names),axis=0),axis=1))) >= 0.005
        if br["parameters"]["candidate_contact"] == "yes" and br["parameters"]["lift_path"] == "clear" and ((qb is not None and qb["ok"]) or landmark_ok): break
        handle, tb, qb = None, None, None
    else:
        return fail("observable_differential_baseline","test lift",{"baseline_checkpoint":"secure.baseline","tracking_quality":qb},"No adequate current patch or independent landmark baseline, or no safe lift evidence.")
    before = api.state()
    lift_target = geo.pad_position(before)+np.array([0.0,0.0,0.055])
    save("secure.test",{"before_state":before,"baseline_frame":br["frame_id"],"target_pad_world_m":lift_target.tolist(),"test":"55 mm upward translation; keep actual orientation and gripper actuation"})
    error = drive(lift_target.tolist(),before["tcp_quaternion_xyzw"],"retention_test_lift",32,4,0.0025,0.01)
    if error is not None: return result("blocked",error["reason"],error)
    after = api.state(); ta = None; qa = {"ok":False,"reason":"No usable baseline tracker"}
    if handle is not None and qb is not None and qb["ok"]:
        ta = api.track_update(handle); qa = quality(ta)
    final_fields = {"package_identity": ["confirmed", "unknown"], "held_between_fingers": ["yes", "no", "unknown"], "clear_of_counter": ["yes", "no", "unknown"], "slip_or_other_contact": ["yes", "no", "unknown"], "same_landmarks": ["yes", "unknown"], "nearby_clearance": ["clear", "contact", "unknown"], "bowl_observation": "string", "notes": "string"}
    measured = None
    for attempt in range(2):
        fr = review("Fresh effect check after the upward test: is this the cream cheese package retained between fingers and clear of its counter support, with no visible slip or other support/contact? Request the same physical b0,b1,b2 landmarks that are visible using baseline identities, not screen positions; omit occluded ones rather than inventing them. Report same_landmarks=yes only for correctly identified returned samples. Describe the current bowl and request one named bowl_rim point if available; bowl fit/transport clearance is NOT this stage's gate. If a replacement observation is needed, use the other view or another already identified baseline landmark. Do not infer retention from a closed gripper or tracker alone.", {"baseline":baseline,"before_state":before,"after_state":after,"tracking_quality":qa,"attempt":attempt},final_fields)
        if fr["status"] == "stop": return result("abort","Observation requested stop.")
        fp = fr["parameters"]
        if fp["held_between_fingers"] == "no" or fp["clear_of_counter"] == "no" or fp["slip_or_other_contact"] == "yes" or fp["nearby_clearance"] == "contact": return result("needs_replan","Fresh evidence contradicts a stable lifted grasp.",fp)
        if qa["ok"]:
            refs = np.array(tb["reference_inlier_world_m"]); ids = [int(np.argmin(refs[:,0])),int(np.argmax(refs[:,0])),int(np.argmin(refs[:,1])),int(np.argmax(refs[:,1]))]
            anchors = refs[ids]
            pb = geo.transform(anchors,np.array(tb["transform_initial_world_to_current_world"]))
            pa = geo.transform(anchors,np.array(ta["transform_initial_world_to_current_world"]))
            uncertainty = qb["guard_m"]+qa["guard_m"]+0.0015
            measured = {"mode":"quality_checked_patch_registration","before_points":pb.tolist(),"after_points":pa.tolist(),"uncertainty_m":uncertainty,"before_quality":qb,"after_quality":qa}
        else:
            common = [n for n in mark_names if valid(fr,n)]
            if fp["same_landmarks"] == "yes" and len(common) >= 2:
                pb = np.array([baseline["points"][n]["world_m"] for n in common]); pa = points(fr,common)
                spread = float(np.max(np.linalg.norm(pb-np.mean(pb,axis=0),axis=1)))
                if spread >= 0.005:
                    uncertainty = 0.0065
                    measured = {"mode":"independent_current_landmarks","names":common,"before_points":pb.tolist(),"after_points":pa.tolist(),"uncertainty_m":uncertainty,"landmark_guard_each_m":0.0025,"registration_floor_m":0.0015,"spread_m":spread}
        if measured is not None and fp["package_identity"] == "confirmed" and fp["held_between_fingers"] == "yes" and fp["clear_of_counter"] == "yes" and fp["slip_or_other_contact"] == "no": break
        if attempt == 0 and qa["ok"]: break
    if measured is None: return fail("post_lift_correspondence","declare secure grasp",{"baseline_checkpoint":"secure.baseline","tracker_quality":qa,"current_frame":fr["frame_id"]},"No current corresponding surface measurement; actual hand lift alone is not retention.")
    attachment = float(geo.attachment_error(pb,pa,before,after))
    rise = float(np.min(pa[:,2]-pb[:,2])); hand_rise = float(after["tcp_position_world_m"][2]-before["tcp_position_world_m"][2])
    threshold = min(0.004+uncertainty,0.25*max(hand_rise,0))
    effect = {"before_frame":before["frame_id"],"after_frame":after["frame_id"],"measurement":measured,"attachment_error_m":attachment,"attachment_threshold_m":threshold,"object_min_rise_m":rise,"hand_rise_m":hand_rise,"uncertainty_guard_m":uncertainty,"required_guarded_object_rise_m":0.030,"margins_m":{"attachment":threshold-attachment,"object_rise":rise-uncertainty-0.030,"hand_rise":hand_rise-0.035,"signal_to_guard":hand_rise-4*uncertainty},"visual_review":fr["parameters"],"bowl_rim":fr["points"]["bowl_rim"] if valid(fr,"bowl_rim") else None,"actual_state":after}
    save("secure.retention",effect)
    if not all(v >= 0 for v in effect["margins_m"].values()): return fail("differential_retention_effect","declare secure grasp",effect,"Object motion does not establish retention with the measured hand motion and uncertainty.")
    fp = fr["parameters"]
    if fp["package_identity"] != "confirmed" or fp["held_between_fingers"] != "yes" or fp["clear_of_counter"] != "yes" or fp["slip_or_other_contact"] != "no": return fail("fresh_grasp_effect_review","declare secure grasp",effect,"Numerical motion evidence is available but the current grasp/support interpretation remains unresolved.")
    logs.append({"stage_effect":"Package moved with actual hand and is freshly observed retained above the counter.","retention_checkpoint":"secure.retention"})
    return result("stage_complete","Stable lifted grasp supported by differential object/hand motion and fresh visual evidence.",{"retention_checkpoint":"secure.retention","geometry_checkpoint":"secure.geometry","next_stage_gate":"Reobserve bowl opening, current package extent, retention and transport/rim clearance before positioning. No transport or release was attempted."})

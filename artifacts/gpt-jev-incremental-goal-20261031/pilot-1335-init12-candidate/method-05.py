def main(api):
    logs, phases, keys = [], [], ["alt.model", "alt.progress", "alt.effect", "alt.failure"]
    old = api.recall("secure.candidate")["value"]
    guard_floor = max(0.00174137, float(old["guard_m"]))
    questions = {}
    for axis in ["x", "y", "z", "rx", "ry", "rz"]:
        questions[axis] = {"type": "choice", "instructions": "For world axis " + axis + ", read state.processed_features.axes." + axis + ".goal_relation. Choose positive for increase, negative for decrease, and hold for within_tolerance. Follow the bounded local pose objective only; program features are measured gate results, not unseen clearance.", "criteria": {"negative": "Decrease this world translation or world rotation-vector component.", "hold": "Keep this component inside its deadband.", "positive": "Increase this world translation or world rotation-vector component."}}
    questions["gripper"] = {"type": "choice", "instructions": "Read state.processed_features.objective.gripper. Deliver exactly open, close, or keep as requested. Closure is not evidence of retention.", "criteria": {"open": "Deliver the requested opening.", "close": "Deliver the requested closing.", "keep": "Preserve the previous gripper command."}}
    def norm(x): return float(np.linalg.norm(x))
    def pad(s): return np.asarray(geo.pad_position(s), dtype=float)
    def angle(a, b):
        return float(math.acos(float(np.clip((np.trace(geo.rotation(a).T @ geo.rotation(b)) - 1.0) / 2.0, -1.0, 1.0))))
    def small(s):
        return {k: s[k] for k in ["frame_id", "tcp_position_world_m", "tcp_quaternion_xyzw", "gripper_qpos_m", "last_gripper_command"]}
    def finish(status, reason, detail):
        if status != "stage_complete":
            api.checkpoint("alt.failure", {"gate": detail.get("gate", reason), "prevented_action": detail.get("action", "further alternate pickup"), "observation_frame": api.state()["frame_id"], "diagnostics": detail})
        return {"stage_status": status, "reason": reason, "evidence": {"observations": logs[-8:], "detail": detail}, "handoff": {"stage": "alternate_pickup", "checkpoint_keys": keys + ["secure.candidate", "secure.failure"], "state": api.state(), "frames": "World meters; tool-to-world xyzw; image pixels top-left. Each measurement retains its observation frame.", "provenance": "alt.model holds fresh local contact geometry and orientation screens; alt.progress holds acknowledged whole-lease motion; alt.effect holds post-closure reference and differential lift evidence; alt.failure names any failed action gate. secure.* is preserved historical evidence, not authorization.", "assumptions": "Never reopen automatically. Revalidate retention and bowl geometry before transport. Local wall strips and a surface patch do not establish hidden clearance or a complete object model."}, "completion_proposed": False}
    def observation_record(r, include_parameters=True):
        # Persist only measurements consumed by this method, never raw RGB-D regions.
        wanted = ["t0","t1","t2","t3","c0","c1","c2","a0","a1","b0","b1","l0","l1","l2","low","table","rim0","rim1","rim2"]
        points = {}
        for name in wanted:
            if name in r["points"]:
                v = r["points"][name]
                points[name] = {k:v[k] for k in ["world_m","depth_m","frame_id","pixel","camera","source"] if k in v}
        errors = [{"name":str(v["name"])[:64],"error":str(v["error"])[:160]} for v in r["measurement_errors"][:12]]
        return {"frame_id":r["frame_id"],"status":r["status"],"parameters":r["parameters"] if include_parameters else {"stored_in":"effect_test.final_parameters"},"points":points,"measurement_errors":errors,"measurement_error_count":len(r["measurement_errors"]),"omitted_region_names":[str(k)[:64] for k in list(r["regions"])[:8]],"provenance":r.get("provenance","Current review interpretation with named depth receipts; unused region clouds omitted.")}
    def ask(question, context, fields):
        if api.state()["budgets"]["gpt_remaining"] <= 2: return None
        r = api.review(question, context=context, fields=fields)
        logs.append({"frame": r["frame_id"], "parameters": r["parameters"], "measurement_errors": r["measurement_errors"], "status": r["status"]})
        return r
    def valid(r, name):
        return r is not None and name in r["points"] and not any(e["name"] == name for e in r["measurement_errors"]) and r["points"][name]["frame_id"] == r["frame_id"]
    def pts(r, names):
        return np.asarray([r["points"][n]["world_m"] for n in names], dtype=float)
    def spread(p):
        if len(p) < 3: return 0.0
        try: return min(float(v) for v in geo.plane(p)["in_plane_spread_m"])
        except Exception: return 0.0
    def move(target, q, phase, tolerance, features):
        for lease in range(3):
            before = api.state()
            reserve = 67 if phase == "side_entry_high_alignment" else 49 if phase == "tilted_open_descent" else 33
            n = min(16, int(before["budgets"]["jev_remaining"]) - reserve, (int(before["budgets"]["native_steps_remaining"]) - 3*reserve) // 3)
            if n < 1: return False, {"gate": "reserved_resources", "action": phase, "budgets": before["budgets"], "reserved_jev_calls": reserve, "reserved_native_steps": 3*reserve, "available_calls_after_reserve": n, "minimum_available_calls": 1, "residual_margin_calls": n-1}
            e0, a0 = norm(pad(before) - target), angle(before["tcp_quaternion_xyzw"], q)
            r = api.drive(target.tolist(), q, "keep", questions, features=features, tool_point="pad_center", max_calls=n, translation_limit=0.008, rotation_limit=0.08, steps=3, position_tolerance=tolerance, rotation_tolerance=0.01)
            after = api.state()
            e1, a1 = norm(pad(after) - target), angle(after["tcp_quaternion_xyzw"], q)
            d = {"phase": phase, "status": r["status"], "lease_calls": r["lease_calls"], "before": small(before), "after": small(after), "position_gain_m": e0-e1, "rotation_gain_rad": a0-a1, "position_error_m": e1, "rotation_error_rad": a1, "minimum_position_gain_m": 0.0003, "minimum_rotation_gain_rad": 0.003, "position_gain_margin_m": e0-e1-0.0003, "rotation_gain_margin_rad": a0-a1-0.003, "lease_number": lease+1, "maximum_leases": 3}
            phases.append(d)
            api.checkpoint("alt.progress", {"phases": phases[-8:], "target_pad_world_m": target.tolist(), "target_quaternion_xyzw": q})
            if r["status"] == "reached": return True, d
            if r["status"] == "stalled": return False, dict(d, gate="pose_stall", action=phase)
            if phase == "retention_test_lift" and r["status"] == "lease_exhausted" and e0-e1 > 0.0003:
                return True, dict(d, stopping_reason="Assess the measured test effect now; pose attainment is not asserted.")
            if r["status"] != "lease_exhausted" or not (e0-e1 > 0.0003 or a0-a1 > 0.003):
                return False, dict(d, gate="ineffective_lease", action=phase)
        return False, dict(d, gate="finite_lease_bound", action=phase)
    short = {"type": "string", "maxLength": 600}
    label = {"type": "string", "minLength": 1, "maxLength": 240}
    pixel = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}
    tri_ids = {"type": "array", "items": label, "minItems": 3, "maxItems": 3}
    fields = {"identity": ["same_package_on_counter", "changed", "unknown"], "empty_open_hand": "boolean", "local_walls": ["visible_parallel_sidewalls", "other", "unknown"], "top_boundary": ["visible_local_edges", "unknown"], "camera": ["agentview", "robot0_eye_in_hand"], "edge_pixels": {"type": "array", "items": pixel, "minItems": 4, "maxItems": 4}, "top_ids": {"type": "array", "items": label, "minItems": 4, "maxItems": 4}, "notes": short}
    names = ["t0", "t1", "t2", "t3", "c0", "c1", "c2", "a0", "a1", "b0", "b1"]
    initial_question = "Assess a NEW side-entry pinch: substantially rotate the tool about the package's short/closing axis, with the palm behind either end, rather than repeating the failed vertical height search. Select a visible local segment near an exposed package end, long enough for approximately 20 mm of pad contact. Request t0..t3: four noncollinear recognizable printed top landmarks, preferably away from the proposed finger envelope, and describe their persistent physical IDs in top_ids. They need not be corners or all inside the contact strip. Request c0..c2: noncollinear counter samples bracketing this local segment. Request a0,a1 and b0,b1: depth-valid upper and lower samples on each of the two opposing long sidewalls (use complementary cameras and radius 1 for narrow walls). local_walls must describe visible continuous wall strips, not extrapolated hidden faces. Give four current top-edge pixels in one declared camera, ordered A-end1,A-end2,B-end2,B-end1, bounding only this local segment, not necessarily material corners. This is measurement, not approach or closure permission."
    recovered = None
    if api.state()["frame_id"] == 216:
        # The failed checkpoint saved nothing, but the supplied execution record
        # contains this review. No physical step followed it. Refresh its depths
        # without spending a review on the same unchanged semantic question.
        recovered = {"status":"continue","frame_id":216,"points":{},"regions":{},"measurement_errors":[],
            "provenance":"Recovered frame-216 semantic review from the supplied execution record; depths freshly reacquired at that same physical frame. No approach or closure authorization.",
            "parameters":{"identity":"same_package_on_counter","empty_open_hand":True,"local_walls":"visible_parallel_sidewalls","top_boundary":"visible_local_edges","camera":"robot0_eye_in_hand","edge_pixels":[[344,430],[344,510],[464,500],[464,426]],
                "top_ids":["t0: inner curl of the large initial capital C in the printed word Cream, toward the exposed short end.","t1: inner curl of the large initial capital C in the printed word Cheese, below Cream in this view.","t2: initial F of the smaller printed Fresh Taste line, left of the large lettering in this view.","t3: terminal e of the smaller printed Fresh Taste line, toward the inward end of that line."],
                "notes":"A is the wrist-view left long wall; B is the opposing agentview strip. End1 is exposed and end2 inward. Edge endpoints delimit a local segment, not material corners. The review identified an empty open hand and counter-supported package. All action-specific clearance gates remain unresolved."}}
        samples = [("t0","robot0_eye_in_hand",[400,450]),("t1","robot0_eye_in_hand",[412,556]),("t2","robot0_eye_in_hand",[375,519]),("t3","robot0_eye_in_hand",[376,589]),("c0","robot0_eye_in_hand",[300,489]),("c1","robot0_eye_in_hand",[493,491]),("c2","robot0_eye_in_hand",[400,387]),("a0","robot0_eye_in_hand",[341,478]),("a1","robot0_eye_in_hand",[334,496]),("b0","agentview",[501,483]),("b1","agentview",[501,493])]
        for name, camera, xy in samples:
            try: recovered["points"][name] = api.point(camera,xy,radius=1 if name in names[7:] else 3)
            except Exception as exc: recovered["measurement_errors"].append({"name":name,"error":str(exc)})
        logs.append({"frame":216,"source":recovered["provenance"],"fresh_depth_count":len(recovered["points"]),"measurement_errors":recovered["measurement_errors"]})
    r = None
    for attempt in range(2):
        r = recovered if attempt == 0 and recovered is not None else ask(initial_question + (" Use a DIFFERENT camera or different depth-valid surface samples to replace failed measurements; do not repeat the same mixed-depth pixels." if attempt else ""), {"historical_failure": old, "start": api.state(), "attempt": attempt}, fields)
        if r is None: return finish("blocked", "Insufficient review budget for local geometry.", {"gate": "observation_budget", "action": "contact assessment"})
        api.checkpoint("alt.model", {"phase": "partial_fresh_geometry", "observation": observation_record(r), "historical_guard_floor_m": guard_floor})
        if r["status"] == "stop": return finish("abort", "Observation review requested a stop.", {"review": r["parameters"]})
        if all(valid(r, n) for n in names): break
    if not all(valid(r, n) for n in names): return finish("blocked", "Complementary sampling did not supply the required local wall and support measurements.", {"gate": "local_depth_membership", "action": "side-entry assessment", "missing": [n for n in names if not valid(r, n)], "errors": r["measurement_errors"]})
    p = r["parameters"]
    if p["identity"] == "changed" or not p["empty_open_hand"]: return finish("needs_replan", "The entry object or holding state has changed; no reopening was attempted.", {"parameters": p})
    if p["identity"] != "same_package_on_counter" or p["local_walls"] != "visible_parallel_sidewalls" or p["top_boundary"] != "visible_local_edges":
        return finish("blocked", "Local contact identity or visible wall continuity is unresolved.", {"gate": "local_identity", "action": "side entry", "parameters": p})
    top, counter = pts(r, names[:4]), pts(r, names[4:7])
    try:
        tf, cf = geo.plane(top), geo.plane(counter)
        tp, cp = np.asarray(tf["coefficients"], dtype=float), np.asarray(cf["coefficients"], dtype=float)
    except Exception as exc:
        return finish("blocked", "Fresh plane fit failed.", {"gate": "local_plane_fit", "action": "side entry", "error": str(exc), "top": top.tolist(), "counter": counter.tolist()})
    guard = max(guard_floor, 2.0*float(tf["rms_m"]), 2.0*float(cf["rms_m"]))
    plane_diag = {"frame": r["frame_id"], "guard_m": guard, "guard_provenance": "Never below inherited guard; increased by twice either fresh fit RMS. Operational allowance, not a calibrated confidence interval.", "top_rms_m": float(tf["rms_m"]), "counter_rms_m": float(cf["rms_m"]), "top_spread_m": spread(top), "counter_spread_m": spread(counter), "normal_z": [float(tp[2]), float(cp[2])], "rms_limit_m": 0.0015, "spread_noise_ratio_min": 3.0, "horizontal_normal_z_min": 0.98, "rms_margin_m": 0.0015-max(float(tf["rms_m"]),float(cf["rms_m"])), "normal_margin": float(min(tp[2],cp[2]))-0.98}
    if max(float(tf["rms_m"]), float(cf["rms_m"])) > 0.0015 or min(spread(top), spread(counter)) <= 3*guard or min(tp[2], cp[2]) < 0.98:
        return finish("blocked", "The measured local plane model is inadequate at the preserved uncertainty.", dict(plane_diag, gate="plane_quality", action="side entry", residual_margin_m=min(spread(top), spread(counter))-3*guard))
    try:
        edge_receipts = [api.plane_point(p["camera"], pixel_xy, tp.tolist()) for pixel_xy in p["edge_pixels"]]
    except Exception as exc:
        return finish("blocked", "Current visible boundary rays could not be intersected with the validated top plane.", {"gate": "visible_edge_intersection", "action": "side entry", "error": str(exc), "plane": tp.tolist(), "frame": r["frame_id"]})
    edges = np.asarray([v["world_m"] for v in edge_receipts], dtype=float)
    longitudinal = (edges[1]-edges[0]) + (edges[2]-edges[3]); longitudinal[2] = 0.0
    if norm(longitudinal) < 6*guard: return finish("blocked", "Local longitudinal direction is unresolved relative to noise.", {"gate": "edge_direction", "action": "orient side entry", "norm_m": norm(longitudinal), "threshold_m": 6*guard, "residual_margin_m": norm(longitudinal)-6*guard, "edges": edges.tolist(), "frame": r["frame_id"]})
    e = longitudinal / norm(longitudinal)
    c = np.asarray([-e[1], e[0], 0.0])
    center = np.mean(edges, axis=0)
    edge_widths = [abs(float(np.dot(edges[3]-edges[0],c))),abs(float(np.dot(edges[2]-edges[1],c)))]
    width = max(edge_widths)
    length = min(abs(float(np.dot(edges[1]-edges[0], e))), abs(float(np.dot(edges[2]-edges[3], e))))
    def height(plane, xy): return float(-(plane[0]*xy[0]+plane[1]*xy[1]+plane[3])/plane[2])
    top_floor = min(float(x[2]) for x in edges)
    wall_errors = [abs(float(np.dot(pts(r, [n])[0]-edges[k], c))) for n,k in [("a0",0),("a1",0),("b0",3),("b1",3)]]
    wall_span = min(abs(float(pts(r, ["a0"])[0,2]-pts(r, ["a1"])[0,2])), abs(float(pts(r, ["b0"])[0,2]-pts(r, ["b1"])[0,2])))
    wall_interior_margins = [min(float(pts(r,[n])[0,2])-height(cp,pts(r,[n])[0,:2])-guard,height(tp,pts(r,[n])[0,:2])-float(pts(r,[n])[0,2])-guard) for n in names[7:]]
    if max(wall_errors) > 2*guard or wall_span < 0.005 or min(wall_interior_margins) < 0 or max(edge_widths)-min(edge_widths)>2*guard:
        return finish("blocked", "Wall samples do not support the proposed parallel contact strips.", {"gate": "wall_consistency", "action": "side entry", "wall_residuals_m": wall_errors, "top_plane":tp.tolist(), "counter_plane":cp.tolist(), "edge_world_m":edges.tolist(), "wall_world_m":pts(r,names[7:]).tolist(), "residual_limit_m": 2*guard, "residual_margin_m": 2*guard-max(wall_errors), "wall_span_m": wall_span, "sample_interior_margins_m":wall_interior_margins, "interior_threshold_m":0.0, "edge_widths_m":edge_widths, "edge_width_difference_threshold_m":2*guard, "edge_width_difference_margin_m":2*guard-(max(edge_widths)-min(edge_widths)), "span_threshold_m": 0.005, "span_margin_m": wall_span-0.005, "uncertainty_m": guard, "frame": r["frame_id"]})
    def screen(s, q):
        g, R = s["own_geometry"], geo.rotation(q)
        pc, ext = np.asarray(g["pad_center_in_tool_m"]), np.asarray(g["pad_extent_in_tool_m"])
        lo, hi = np.asarray(g["finger_low_offset_tool_m"]), np.asarray(g["finger_high_offset_tool_m"])
        corners = np.asarray([[x,y,z] for x in [lo[0],hi[0]] for y in [lo[1],hi[1]] for z in [lo[2],hi[2]]])
        rel = (corners-pc) @ R.T
        # A 4 mm longitudinal core contained in each rotated pad face, not its optimistic projected bounding height.
        half = []
        for j in [0,2]:
            available = float(ext[j]/2.0 - abs(np.dot(e, R[:,j]))*0.002)
            if abs(R[2,j]) > 0.000001: half.append(available/abs(float(R[2,j])))
        h = (min(half) if half else 0.0) - abs(float(R[2,1]))*float(ext[1]/2.0)
        f_radius = max(norm(v-pc) for v in corners)
        p_radius = norm(ext/2.0)
        uc, uo = guard+0.0005+f_radius*0.01, guard+0.0005+p_radius*0.01
        support = max(height(cp, center[:2]+v[:2]) for v in rel)
        overlap = max(0.007, 0.005+uo)
        lower, upper = support+0.003+uc-float(np.min(rel[:,2])), top_floor+h-overlap
        pad_long = abs(float(np.dot(e,R[:,0])))*float(ext[0]/2) + abs(float(np.dot(e,R[:,2])))*float(ext[2]/2)
        return {"lower_pad_z_m": lower, "upper_pad_z_m": upper, "interval_m": upper-lower, "interval_threshold_m": 0.0002, "residual_margin_m": upper-lower-0.0002, "contact_core_half_height_m": h, "finger_bottom_relative_pad_m": float(np.min(rel[:,2])), "support_ceiling_m": support, "top_floor_m": top_floor, "counter_allowance_m": uc, "overlap_allowance_m": uo, "finger_rotation_lever_m":f_radius, "pad_rotation_lever_m":p_radius, "finger_rotation_allowance_m":f_radius*0.01, "pad_rotation_allowance_m":p_radius*0.01, "required_nominal_overlap_m": overlap, "guard_m": guard, "position_tolerance_m": 0.0005, "rotation_tolerance_rad": 0.01, "longitudinal_margin_m": length/2-pad_long-guard-0.0005, "outer_span_necessary_margin_m": float(ext[1])-width-2*guard, "frame": s["frame_id"]}
    yawq = api.compose([1.0,0.0,0.0,0.0], [0.0,0.0,math.atan2(float(e[1]),float(e[0]))])
    s = api.state(); candidates, screens = [], []
    for degrees in [70,-70,80,-80,88,-88,90,-90]:
        q = api.compose(yawq, (c*(degrees*math.pi/180.0)).tolist())
        d = screen(s, q); screens.append(dict(d, tilt_degrees=degrees))
        if d["residual_margin_m"] >= 0 and d["contact_core_half_height_m"] > 0 and d["longitudinal_margin_m"] > 0 and d["outer_span_necessary_margin_m"] > 0:
            low = center.copy(); low[2] = (d["lower_pad_z_m"]+d["upper_pad_z_m"])/2
            high = low.copy(); high[2] = max(float(pad(s)[2]), top_floor+0.065)
            candidates.append({"q": q, "low": low.tolist(), "high": high.tolist(), "tilt_degrees": degrees, "screen": d})
    model = {"observation_frame": r["frame_id"], "top_landmarks": {n:r["points"][n] for n in names[:4]}, "top_ids": p["top_ids"], "top_plane": tp.tolist(), "counter_plane": cp.tolist(), "edges": edge_receipts, "center_world_m": center.tolist(), "longitudinal_world": e.tolist(), "closing_world": c.tolist(), "width_m": width, "length_m": length, "plane_quality": plane_diag, "screens": screens, "wall_samples": {n:r["points"][n] for n in names[7:]}, "scope": "Only the observed local wall strips; no global collision certificate."}
    api.checkpoint("alt.model", model)
    if not candidates: return finish("blocked", "No screened materially tilted contact configuration preserves the existing margins.", {"gate": "tilted_contact_interval", "action": "side-entry approach", "screens": screens, "frame": s["frame_id"], "preserved_clearance_m": 0.003, "preserved_guarded_overlap_m": 0.005, "preserved_nominal_overlap_m": 0.007})
    gatefields = {"notes": short}
    for i in range(len(candidates)):
        gatefields["align_"+str(i)] = ["clear","blocked","unknown"]
        gatefields["descent_"+str(i)] = ["clear","blocked","unknown"]
    rv = ask("For EACH numbered alternative, assess align_i separately from descent_i. align_i authorizes only moving the empty, still-open hand to its high pad target and markedly side-entry orientation. Check the visible swept hand/palm/fingers against counter, package, bowl and obstacles. descent_i addresses the later side-entry lowering and whether the open fingers can actually straddle these local walls. The outer-span screen is only necessary, NOT proof of an open aperture or palm clearance. Mark an observed palm/counter obstruction blocked; never call hidden space clear. Unknown descent does not invalidate an independently clear high alignment, but an established descent obstruction must not be postponed.", {"candidates": candidates, "model": model, "state": s}, gatefields)
    if rv is None: return finish("blocked", "No review budget for the new orientation.", {"gate":"alignment_review","action":"side-entry alignment"})
    if rv["status"] == "stop": return finish("abort", "Alignment review requested stop.", {"parameters":rv["parameters"]})
    choices = [i for i in range(len(candidates)) if rv["parameters"]["align_"+str(i)] == "clear" and rv["parameters"]["descent_"+str(i)] != "blocked"]
    if not choices: return finish("blocked", "No alternative has a supported high alignment without an established later obstruction.", {"gate":"new_orientation_path","action":"high alignment","parameters":rv["parameters"],"candidates":candidates})
    chosen = candidates[choices[0]]; q = chosen["q"]
    ok, d = move(np.asarray(chosen["high"]), q, "side_entry_high_alignment", 0.002, {"action":"empty high alignment only","candidate":chosen})
    if not ok: return finish("blocked", "High alignment stopped; do not replay it blindly.", d)
    def stationary_review(action, target, extra):
        ff = {"identity":["unchanged_on_counter","moved","unknown"], "action_clear":["clear","blocked","unknown"], "empty_open_hand":"boolean", "notes":short}
        for attempt in range(2):
            rr = ask("Revalidate only the next action: "+action+". Request t0..t3 at the SAME printed physical landmarks described in context (three sufficient), and c0 on visible adjacent supporting counter. Preserve IDs, not screen positions. Check the CURRENT open aperture, palm and finger sweep for this action; do not infer hidden clearance. A complementary camera/new depth patch may replace a failed measurement. This does not authorize closure unless closure is explicitly the action.", {"model":model,"target_pad_world_m":target.tolist(),"quaternion":q,"specific_gate":extra,"attempt":attempt}, ff)
            if rr is None or rr["status"] == "stop": return False, rr, {"gate":"action_observation","action":action}
            ns = [n for n in names[:4] if valid(rr,n)]
            if len(ns) >= 3 and valid(rr,"c0"):
                errors = [norm(pts(rr,[n])[0]-np.asarray(model["top_landmarks"][n]["world_m"])) for n in ns]
                ce = abs(float(np.dot(cp[:3],pts(rr,["c0"])[0])+cp[3]))
                dd = {"gate":"stationary_local_reference","action":action,"frame":rr["frame_id"],"landmark_errors_m":errors,"landmark_threshold_m":2*guard,"counter_residual_m":ce,"counter_threshold_m":guard,"residual_margin_m":min(2*guard-max(errors),guard-ce),"uncertainty_m":guard,"parameters":rr["parameters"]}
                return rr["parameters"]["identity"] == "unchanged_on_counter" and rr["parameters"]["empty_open_hand"] and rr["parameters"]["action_clear"] == "clear" and dd["residual_margin_m"] >= 0, rr, dd
            api.checkpoint("alt.progress", {"phases":phases[-6:],"partial_revalidation":observation_record(rr)})
        return False, rr, {"gate":"stationary_landmark_membership","action":action,"frame":rr["frame_id"],"measurement_errors":rr["measurement_errors"],"valid_names":ns}
    s = api.state(); d = screen(s, q)
    if d["residual_margin_m"] < 0: return finish("blocked", "Updated finger geometry invalidates the tilted interval.", dict(d,gate="updated_tilted_interval",action="descent"))
    target = center.copy(); target[2] = (d["lower_pad_z_m"]+d["upper_pad_z_m"])/2
    ok, rv, check = stationary_review("lower the still-open tilted hand to this local contact height", target, d)
    if not ok: return finish("abort" if rv is not None and rv["status"]=="stop" else "needs_replan" if rv is not None and rv["parameters"]["identity"]=="moved" else "blocked", "Descent is not authorized by the current local evidence.", check)
    ok, receipt = move(target, q, "tilted_open_descent", 0.0005, {"action":"open side-entry descent","geometry_gate":d,"review_frame":rv["frame_id"]})
    if not ok: return finish("blocked", "The new descent stopped; no closure or stalled retry was attempted.", receipt)
    s = api.state(); actual = screen(s, s["tcp_quaternion_xyzw"]); pp = pad(s)
    nominal = top_floor-(float(pp[2])-actual["contact_core_half_height_m"])
    clearance = float(pp[2])+actual["finger_bottom_relative_pad_m"]-actual["support_ceiling_m"]-guard
    measured_gate = {"gate":"actual_contact_envelope","action":"closure","frame":s["frame_id"],"counter_clearance_after_guard_m":clearance,"counter_threshold_m":0.003,"guarded_overlap_m":nominal-guard,"overlap_threshold_m":0.005,"nominal_overlap_m":nominal,"nominal_threshold_m":0.007,"pad_position_error_m":norm(pp-target),"position_threshold_m":0.0005,"rotation_error_rad":angle(s["tcp_quaternion_xyzw"],q),"rotation_threshold_rad":0.01,"uncertainty_m":guard,"actual_screen":actual,"pose_margin_m":0.0005-norm(pp-target),"rotation_margin_rad":0.01-angle(s["tcp_quaternion_xyzw"],q),"residual_margin_m":min(clearance-0.003,nominal-guard-0.005,nominal-0.007,0.0005-norm(pp-target))}
    if measured_gate["residual_margin_m"] < 0 or norm(pp-target)>0.0005 or angle(s["tcp_quaternion_xyzw"],q)>0.01:
        return finish("blocked", "Actual finger clearance or pad overlap does not authorize closing.", measured_gate)
    ok, rv, check = stationary_review("close the fingers once onto the measured opposing local walls, holding this pose; check both contact strips and palm/counter clearance", pp, measured_gate)
    if not ok: return finish("abort" if rv is not None and rv["status"]=="stop" else "blocked", "Closure remains unsupported; hand stays open.", check)
    closing_pad, closing_q = pp.tolist(), s["tcp_quaternion_xyzw"]
    for closing in range(4):
        before = api.state()
        cr = api.control(closing_pad, closing_q, "close", questions, features={"action":"single bounded closing episode","closure_review_frame":rv["frame_id"],"measured_gate":measured_gate}, tool_point="pad_center", translation_limit=0.001, rotation_limit=0.01, steps=3, position_tolerance=0.0005, rotation_tolerance=0.01)
        after = api.state()
        api.checkpoint("alt.progress", {"phases":phases[-6:],"closing_update":closing,"before":small(before),"after":small(after),"receipt":cr})
        if cr["status"] == "stalled" or cr["choices"]["gripper"] != "close": return finish("blocked","Closing pose stalled or command mismatched; do not reopen or repeat.",{"gate":"closing_execution","action":"lift","receipt":cr})
        closing_screen = screen(after,after["tcp_quaternion_xyzw"])
        remaining_clearance = float(pad(after)[2])+closing_screen["finger_bottom_relative_pad_m"]-closing_screen["support_ceiling_m"]-guard
        if remaining_clearance < 0.003:
            return finish("blocked","Measured counter clearance fell below the preserved requirement during closing.",{"gate":"closing_counter_margin","action":"further closing or lift","frame":after["frame_id"],"clearance_after_guard_m":remaining_clearance,"threshold_m":0.003,"residual_margin_m":remaining_clearance-0.003,"uncertainty_m":guard,"screen":closing_screen})
        if closing > 0 and norm(np.asarray(after["gripper_qpos_m"])-np.asarray(before["gripper_qpos_m"])) < 0.0004: break
    bf = {"identity":["same_package","other","unknown"],"contact":["plausible_opposed_contact","failed","unknown"],"lift_clear":["clear","blocked","unknown"],"landmark_ids":tri_ids,"patch_same_package":"boolean","camera":["agentview","robot0_eye_in_hand"],"polygon":{"type":"array","items":pixel,"minItems":0,"maxItems":16},"notes":short}
    br = ask("After closure, assess the actual state without inferring retention from closure. Does the SAME package have plausible opposed contact, with a clear 30 mm vertical test lift of package plus the current tilted hand? Request l0,l1,l2 at three individually identifiable noncollinear printed landmarks on any CURRENT exposed package patch, and describe these NEW baseline physical IDs. No historical perimeter is needed. Optionally give a 3..16 vertex polygon wholly inside that same textured package face as a replaceable differential-motion measurement. Do not include fingers or counter. An empty polygon is allowed. Contact failure means no blind retry or reopening.", {"state":api.state(),"contact_geometry":measured_gate}, bf)
    if br is None: return finish("blocked","No budget to inspect the result of closure.",{"gate":"postclosure_observation","action":"test lift"})
    if br["status"]=="stop": return finish("abort","Postclosure review requested stop.",{"parameters":br["parameters"]})
    bp = br["parameters"]
    if bp["identity"] != "same_package" or bp["contact"] != "plausible_opposed_contact" or bp["lift_clear"] != "clear":
        return finish("needs_replan" if bp["contact"]=="failed" or bp["identity"]=="other" else "blocked","Current contact or lift path is unsupported; the gripper was not reopened.",{"gate":"postclosure_contact_and_lift","action":"test lift","parameters":bp})
    baseline = api.state(); baseline_points = pts(br,["l0","l1","l2"]) if all(valid(br,n) for n in ["l0","l1","l2"]) else np.empty((0,3))
    handle, tracking_base, tracker_info = None, None, None
    def track_good(t):
        if t is None or t["status"] != "tracked": return False
        u = max(guard,float(t["uncertainty_floor_m"]),2*float(t["rms_m"]))
        return t["inliers"] >= 12 and t["inliers"]/max(1,t["matches"]) >= 0.65 and float(t["rms_m"]) <= 0.0015 and spread(np.asarray(t["current_inlier_world_m"])) > 3*u
    def track_summary(t):
        if t is None: return {"status":"unavailable"}
        if t["status"] != "tracked": return {"status":t["status"],"frame":t["frame_id"],"reason":t.get("reason","unknown")}
        u0 = max(guard,float(t["uncertainty_floor_m"]),2*float(t["rms_m"]))
        sp = spread(np.asarray(t["current_inlier_world_m"]))
        return {"status":"tracked","frame":t["frame_id"],"reference_frame":t["reference_frame_id"],"inliers":t["inliers"],"inlier_minimum":12,"fraction":t["inliers"]/max(1,t["matches"]),"fraction_minimum":0.65,"rms_m":float(t["rms_m"]),"rms_limit_m":0.0015,"uncertainty_floor_m":float(t["uncertainty_floor_m"]),"combined_per_view_allowance_m":u0,"spread_m":sp,"spread_threshold_m":3*u0,"spread_margin_m":sp-3*u0}
    if bp["patch_same_package"] and len(bp["polygon"]) >= 3:
        try:
            init = api.track_init(bp["camera"], bp["polygon"]); handle = init["handle"]
            tracking_base = api.track_update(handle)
            tracker_info = {"handle":handle,"identity":"same cream cheese printed face, postclosure","camera":bp["camera"],"polygon":bp["polygon"],"reference_frame_id":init["frame_id"]}
            if track_good(tracking_base): tracker_info["baseline_transform"] = tracking_base["transform_initial_world_to_current_world"]
        except Exception as exc:
            logs.append({"optional_tracker_error":str(exc),"frame":baseline["frame_id"]}); tracking_base = None
    base_ok = len(baseline_points)==3 and spread(baseline_points)>3*guard
    effect = {"baseline_state":small(baseline),"baseline_landmarks":{n:br["points"][n] for n in ["l0","l1","l2"] if valid(br,n)},"landmark_ids":bp["landmark_ids"],"baseline_review":{k:bp[k] for k in ["identity","contact","lift_clear","patch_same_package","camera","notes"]},"tracker":tracker_info,"baseline_guard_m":guard,"tracker_baseline_quality":track_summary(tracking_base),"contact_gate":measured_gate}
    api.checkpoint("alt.effect",effect)
    if not base_ok and not track_good(tracking_base):
        return finish("blocked","Neither the exposed landmark patch nor the optional tracker supplies a noise-resolved motion baseline.",{"gate":"differential_baseline","action":"test lift","landmark_spread_m":spread(baseline_points),"spread_threshold_m":3*guard,"residual_margin_m":spread(baseline_points)-3*guard,"uncertainty_m":guard,"tracker_quality":track_summary(tracking_base),"frame":baseline["frame_id"]})
    lift = pad(baseline)+np.asarray([0.0,0.0,0.030])
    lifted, lift_receipt = move(lift, baseline["tcp_quaternion_xyzw"], "retention_test_lift", 0.002, {"action":"30 mm vertical differential test, not transport","baseline_frame":baseline["frame_id"],"lift_review_frame":br["frame_id"]})
    if lifted:
        hold = api.state()
        api.control(pad(hold).tolist(),hold["tcp_quaternion_xyzw"],"keep",questions,features={"action":"one 3-step retained-lift settling observation"},tool_point="pad_center",translation_limit=0.001,rotation_limit=0.01,steps=3,position_tolerance=0.002,rotation_tolerance=0.01)
    af = {"identity":["same_package","other","unknown"],"separation":["visible_counter_gap","still_supported","unknown"],"retention":["between_fingers_without_slip","slipped_or_lost","unknown"],"patch_identity":["same_package_patch","other","unknown"],"bowl_visible":"boolean","bowl_observation":short,"nearby_obstacles":short,"notes":short}
    ar = ask("Inspect the completed differential lift and short hold. Request l0,l1,l2 at the SAME baseline physical printed landmarks, using either camera. Check a visible gap from the counter and retained opposed contact, rather than pose attainment. A changed current surface patch is not a landmark correspondence. Request optional low on a visible package lower edge and table on adjacent counter if depth-valid. Also refresh bowl/nearby-obstacle observations; request optional rim0,rim1,rim2 on the visible bowl rim. These bowl observations are handoff only, NOT placement clearance.",effect,af)
    if ar is None: return finish("blocked","Fresh lift verification is unavailable.",{"gate":"lift_observation","action":"declare retained pickup","lift_receipt":lift_receipt})
    if ar["status"]=="stop": return finish("abort","Lift review requested stop.",{"parameters":ar["parameters"]})
    after = api.state(); observed_before, observed_after, u, measurement = None, None, guard, None
    tracking_now = None
    if base_ok and all(valid(ar,n) for n in ["l0","l1","l2"]) and spread(pts(ar,["l0","l1","l2"]))>3*guard:
        observed_before, observed_after, measurement = baseline_points, pts(ar,["l0","l1","l2"]), "independently identified printed landmarks"
    elif handle is not None and track_good(tracking_base):
        tracked = api.track_update(handle); tracking_now = tracked
        if track_good(tracked) and tracked["reference_frame_id"]==tracking_base["reference_frame_id"] and tracked["frame_id"]==after["frame_id"] and ar["parameters"]["patch_identity"]=="same_package_patch":
            observed_before = geo.transform(np.asarray(tracked["reference_inlier_world_m"]),np.asarray(tracking_base["transform_initial_world_to_current_world"]))
            observed_after = np.asarray(tracked["current_inlier_world_m"])
            u = max(guard,float(tracked["uncertainty_floor_m"]),float(tracking_base["uncertainty_floor_m"]),2*float(tracked["rms_m"]),2*float(tracking_base["rms_m"]))
            measurement = "quality-checked same-surface registration, compared with measured hand transform"
    if observed_before is None and base_ok:
        retry = ask("The optional tracker or first-view landmarks did not resolve the motion. Use the COMPLEMENTARY camera and fresh depth-valid samples of the same l0,l1,l2 physical IDs, not the same occluded pixels. Do not request full perimeter recovery. Reassess separation/contact and refresh bowl notes as declared.",effect,af)
        if retry is not None:
            ar = retry
            if ar["status"]=="stop": return finish("abort","Complementary lift review requested stop.",{"parameters":ar["parameters"]})
            if all(valid(ar,n) for n in ["l0","l1","l2"]) and spread(pts(ar,["l0","l1","l2"]))>3*guard:
                observed_before, observed_after, measurement = baseline_points, pts(ar,["l0","l1","l2"]), "complementary-camera identified landmarks"
    if observed_before is None:
        effect["final_review"] = observation_record(ar); api.checkpoint("alt.effect",effect)
        return finish("blocked","Lift occurred, but bounded independent landmark/patch measurements could not verify retention.",{"gate":"observable_attachment","action":"declare retained pickup","baseline_frame":baseline["frame_id"],"current_frame":after["frame_id"],"measurement_errors":ar["measurement_errors"],"tracker_baseline":track_summary(tracking_base),"tracker_current":track_summary(tracking_now),"valid_landmark_names":[n for n in ["l0","l1","l2"] if valid(ar,n)],"current_landmark_spread_m":spread(pts(ar,[n for n in ["l0","l1","l2"] if valid(ar,n)])),"spread_threshold_m":3*guard,"uncertainty_m":guard,"lift_receipt":lift_receipt})
    attachment = float(geo.attachment_error(observed_before,observed_after,baseline,after))
    hand_dz = float(np.asarray(after["tcp_position_world_m"])[2]-np.asarray(baseline["tcp_position_world_m"])[2])
    object_dz = float(np.min(observed_after[:,2]-observed_before[:,2]))
    limit = 2*u+0.002
    diag = {"gate":"retained_lift_effect","action":"declare retained pickup","measurement":measurement,"baseline_frame":baseline["frame_id"],"current_frame":after["frame_id"],"attachment_error_m":attachment,"attachment_limit_m":limit,"uncertainty_per_observation_m":u,"attachment_margin_m":limit-attachment,"hand_lift_m":hand_dz,"hand_lift_threshold_m":max(0.020,6*u),"minimum_observed_object_lift_m":object_dz,"object_lift_threshold_m":max(0.015,4*u),"rotation_change_rad":angle(baseline["tcp_quaternion_xyzw"],after["tcp_quaternion_xyzw"]),"rotation_threshold_rad":0.04,"lift_receipt":lift_receipt,"final_parameters":ar["parameters"]}
    diag["residual_margin_m"] = min(limit-attachment,hand_dz-max(0.020,6*u),object_dz-max(0.015,4*u))
    effect.update({"final_state":small(after),"effect_test":diag,"tracker_current_quality":track_summary(tracking_now),"final_observation":observation_record(ar,False),"baseline_points_used":observed_before[:3].tolist(),"current_points_used":observed_after[:3].tolist(),"point_count_used":len(observed_before)})
    api.checkpoint("alt.effect",effect)
    ap = ar["parameters"]
    if ap["identity"]=="other" or ap["retention"]=="slipped_or_lost" or ap["separation"]=="still_supported":
        return finish("needs_replan","Fresh evidence contradicts the intended retained lift; assess the actual state before recovery.",diag)
    if not lifted or diag["residual_margin_m"]<0 or diag["rotation_change_rad"]>0.04 or ap["identity"]!="same_package" or ap["retention"]!="between_fingers_without_slip" or ap["separation"]!="visible_counter_gap":
        return finish("blocked","The current-stage retained-lift effect is not established at the measured margin.",diag)
    return finish("stage_complete","A materially tilted contact produced a freshly observed, retained lift with object motion matching actual hand motion.",diag)

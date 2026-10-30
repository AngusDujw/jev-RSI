def main(api):
    q = {}
    for axis in ("x", "y", "z", "rx", "ry", "rz"):
        q[axis] = {"type": "choice", "instructions": "Control only the world axis " + axis + ". Read state.processed_features.axes." + axis + ".goal_relation. Use the measured residual, not object-image guesses. Increase means positive, decrease means negative, within_tolerance means hold. The program has already checked this local action's geometry.", "criteria": {"negative": "Decrease this world coordinate or world rotation-vector component when relation is decrease.", "hold": "No correction when relation is within_tolerance.", "positive": "Increase this world coordinate or world rotation-vector component when relation is increase."}}
    q["gripper"] = {"type": "choice", "instructions": "Read state.processed_features.objective.gripper. Preserve the retained carton during transfer. Open only for the explicitly authorized release phase; do not infer release from proximity.", "criteria": {"open": "The objective explicitly requests open at the authorized release pose.", "close": "The objective requests close to preserve retention.", "keep": "The objective requests keep, preserving the last command."}}
    progress = {"phase": "entry", "actions": [], "release_started": False}
    g = {}
    def compact(s):
        return {k: s[k] for k in ("frame_id", "native_steps", "tcp_position_world_m", "tcp_quaternion_xyzw", "gripper_qpos_m", "last_gripper_command")}
    def record(r):
        return {k: r[k] for k in ("frame_id", "status", "parameters", "points", "measurement_errors")}
    def finish(status, reason, evidence=None):
        progress["state"] = compact(api.state())
        progress["stage_status"] = status
        progress["reason"] = reason
        api.checkpoint("place.progress", progress)
        return {"stage_status": status, "reason": reason, "evidence": evidence if evidence is not None else progress, "completion_proposed": False, "handoff": {"checkpoint_keys": [m["key"] for m in api.recall() if m["key"] in ("place.progress", "place.geometry", "place.effect", "secure.geometry", "secure.observations", "secure.local", "secure.retention")], "frames": "World metres, tool-to-world xyzw. Every measurement retains its observation frame. Checkpoint receipts identify method and source.", "references": {"place.geometry": "Measured historical rectangle references and their selected paths; current observed short-end anchors; measured inner-rim model, uncertainty and physical bowl landmark identities.", "place.progress": "Acknowledged local leases, actual before/after states, pending action if interrupted, and whether opening has started.", "place.effect": "Latest fresh review, including failed or partial measurements. Not necessarily successful placement."}, "actual_state": progress["state"], "release_started": progress["release_started"], "assumptions": ["No pickup is repeated. No withdrawal or final stability verification is implemented here.", "The rectangle model is supported by precontact metric boundary measurements, not an inferred hidden perimeter.", "Bowl geometry is local and conditional on fresh stationarity checks; it is not a collision certificate.", "Reobserve after movement. If opening has started, do not repeat release without auditing the actual object state."]}}
    def fail(reason, replan=False):
        progress["failure_status"] = "needs_replan" if replan else "blocked"
        raise Exception(reason)
    def valid_points(r):
        bad = [e["name"] for e in r["measurement_errors"]]
        return {k: v for k, v in r["points"].items() if k not in bad}
    def ask(question, fields, context, required):
        r = api.review(question + " Use English ASCII. Missing or occluded evidence must be unknown, never a stationary projection.", context=context, fields=fields)
        api.checkpoint("place.effect", record(r))
        if r["status"] == "stop":
            fail("Observation review requested a stop: " + r["explanation"])
        good = valid_points(r)
        missing = [n for n in required if n not in good]
        if missing:
            old = r
            r = api.review("Replace these failed depth measurements using a different visible patch on the SAME specified surface or the other camera: " + str(missing) + ". Preserve all physical identities and reference selections. " + question, context={"original_context": context, "previous": record(old)}, fields=fields)
            api.checkpoint("place.effect", record(r))
            if r["status"] == "stop" or r["frame_id"] != old["frame_id"]:
                fail("Replacement review stopped or the observation frame changed.")
            if "corner_ids" in old["parameters"] and old["parameters"]["corner_ids"] != r["parameters"]["corner_ids"]:
                fail("Historical corner identities changed during measurement replacement.")
            good.update(valid_points(r))
            r["replaced_measurement_errors"] = old["measurement_errors"] + r["measurement_errors"]
            r["points"] = good
            r["measurement_errors"] = [e for e in r["measurement_errors"] if e["name"] not in good]
        api.checkpoint("place.effect", record(r))
        if any(n not in good for n in required):
            fail("Unavailable current measurements after one alternate sampling attempt: " + str([n for n in required if n not in good]))
        return r
    def xyz(r, names):
        d = valid_points(r)
        if any(n not in d for n in names):
            fail("Missing or invalid named depth: " + str(names))
        a = np.array([d[n]["world_m"] for n in names], dtype=float)
        if a.shape != (len(names), 3) or not np.all(np.isfinite(a)):
            fail("Malformed or nonfinite depth coordinates.")
        return a
    def plane_fit(points):
        fit = geo.plane(points)
        return {"coefficients": np.array(fit["coefficients"]).tolist(), "center_world_m": np.array(fit["center_world_m"]).tolist(), "rms_m": float(fit["rms_m"]), "in_plane_spread_m": np.array(fit["in_plane_spread_m"]).tolist()}
    def getpath(root, path):
        if not path:
            fail("No measured historical reference path was available.")
        for part in path:
            root = root[int(part)] if isinstance(root, list) else root[part]
        return root
    pixel = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}
    path = {"type": "array", "items": {"type": "string", "maxLength": 100}, "maxItems": 12}
    common = {"identity": ["same_retained_carton", "lost", "unknown"], "bowl": ["same_upright_unchanged", "changed", "unknown"], "end_ids_match": "boolean", "end_camera": ["agentview", "robot0_eye_in_hand"], "end_pixels": {"type": "array", "items": pixel, "maxItems": 2}, "bowl_reference_mode": ["landmarks", "rim_samples", "unknown"]}
    fields = dict(common)
    fields.update({"history_quality": ["metric_rectangle_supported", "unknown"], "corner_paths": {"type": "array", "items": path, "maxItems": 4}, "table_path": path, "extent_uncertainty_path": path, "corner_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 4}, "bowl_mark_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 2}, "rim_camera": ["agentview", "robot0_eye_in_hand"], "rim_pixels": {"type": "array", "items": pixel, "maxItems": 12}, "rim_model": ["circular_horizontal_inner_lip", "unknown"]})
    try:
        manifest = api.recall()
        if any(m["key"] == "place.progress" for m in manifest):
            progress = api.recall("place.progress")["value"]
            return finish("blocked", "Placement already has an execution checkpoint. Audit its actual phase before issuing another transfer or release.")
        entry = api.state()
        progress["entry"] = compact(entry)
        if entry["last_gripper_command"] != "close":
            fail("Entry no longer has the acknowledged retained-grasp command; do not repeat pickup.", True)
        history = {k: api.recall(k) for k in ("secure.geometry", "secure.observations", "secure.local")}
        roots = {k: v["value"] for k, v in history.items()}
        initial_question = "Prepare ONLY placement of the held Cream carton into the same upright patterned bowl. Check retained identity and the rigid, originally table-supported rectangular carton model. From the supplied historical checkpoint VALUES select four actually measured top-boundary world XYZ arrays by corner_paths, ordered c0,c1,c2,c3 around the perimeter. c0,c1 must be the currently visible short end at the start of the Cream logo; assign persistent physical corner_ids, not screen directions. Paths start with the checkpoint key. table_path selects an actually measured bare-table XYZ array from the prelift records. extent_uncertainty_path selects the largest documented scalar metre uncertainty relevant to those boundary coordinates, if present; otherwise return an empty path. Do not select a squared error or a dimension as uncertainty. Do not synthesize coordinates, select a cross section as a full length, or certify undocumented historical corners. Return unknown if references are inadequate. In the CURRENT images request p0,p1,p2,p3 as separated interior depth samples of the planar printed top, avoiding fingers and seams. end_pixels are the CURRENT two visible end corners c0,c1 in end_camera; these are boundary rays, not depth samples. The hidden opposite end need not be visible. For the bowl request s0,s1,s2,s3 on separated depth-valid TOP LIP surface patches, floor on its visible interior floor, and b0,b1 on two distinct recognizable bowl pattern landmarks; describe their physical identities in bowl_mark_ids. Return about eight well-distributed CURRENT inner-opening boundary pixels in rim_pixels and rim_camera, not the outer silhouette or a lower interior contour. Confirm a circular horizontal inner lip only if actually supported. Current bowl landmark mode is landmarks. No motion yet."
        o = ask(initial_question, fields, {"historical_checkpoint_records": history, "acknowledged_retention": api.recall("secure.retention")["value"]}, ["p0", "p1", "p2", "p3", "floor", "b0", "b1"])
        par = o["parameters"]
        if par["identity"] == "lost" or par["bowl"] == "changed":
            fail("Fresh entry evidence invalidates retention or the bowl configuration.", True)
        if par["history_quality"] != "metric_rectangle_supported" or len(par["corner_paths"]) != 4 or len(par["corner_ids"]) != 4:
            fail("Missing measured full carton extent and physical end-corner correspondence; current occluded perimeter is not being invented.")
        h = np.array([getpath(roots, p) for p in par["corner_paths"]], dtype=float)
        table = np.array(getpath(roots, par["table_path"]), dtype=float)
        hp = plane_fit(h)
        edges = np.roll(h, -1, axis=0) - h
        lengths = np.linalg.norm(edges, axis=1)
        if h.shape != (4, 3) or table.shape != (3,) or hp["rms_m"] > 0.0015 or hp["coefficients"][2] < 0.995 or min(lengths) <= 0:
            fail("Historical rectangle or supporting table measurement is invalid.")
        if abs(float(np.dot(edges[0], edges[1]))) > 0.06 * lengths[0] * lengths[1] or max(abs(lengths[0]-lengths[2]), abs(lengths[1]-lengths[3])) > 0.003 or np.linalg.norm(h[0]+h[2]-h[1]-h[3]) > 0.003:
            fail("Historical boundary samples do not support the selected rectangle model.")
        ref_u = float(max(0.0015, 2*hp["rms_m"], 0.5*max(abs(lengths[0]-lengths[2]), abs(lengths[1]-lengths[3]))))
        if par["extent_uncertainty_path"]:
            declared_u = float(getpath(roots, par["extent_uncertainty_path"]))
            if not np.isfinite(declared_u) or declared_u < 0:
                fail("Invalid historical metric uncertainty reference.")
            ref_u = max(ref_u, declared_u)
        g["historical_extent_u"] = ref_u
        g["extent_uncertainty_path"] = par["extent_uncertainty_path"]
        g.update({"length": float((lengths[1]+lengths[3])/2), "width": float((lengths[0]+lengths[2])/2), "thickness_upper": float(max(h[:, 2])-table[2]+0.002), "corner_ids": par["corner_ids"], "bowl_mark_ids": par["bowl_mark_ids"], "historical_paths": par["corner_paths"], "table_path": par["table_path"], "historical_corners": h.tolist(), "historical_support": table.tolist(), "historical_provenance": {k: {a: v[a] for a in ("frame_id", "method_number", "source_sha256")} for k, v in history.items()}})
        if not 0.004 < g["thickness_upper"] < 0.06:
            fail("Unsupported external carton thickness bound.")
        lip_points = [v for k, v in valid_points(o).items() if k in ("s0", "s1", "s2", "s3")]
        bp = None
        if len(lip_points) >= 4:
            try:
                bp = plane_fit(np.array([v["world_m"] for v in lip_points]))
            except Exception as exc:
                progress["rim_fit_error"] = str(exc)
        if bp is None or bp["rms_m"] > 0.0015 or bp["coefficients"][2] < 0.995:
            lip_points = []
            progress["alternate_rim_depth_errors"] = []
            for uv in par["rim_pixels"]:
                try:
                    lip_points.append(api.point(par["rim_camera"], uv, radius=1))
                except Exception as exc:
                    progress["alternate_rim_depth_errors"].append({"pixel": uv, "error": str(exc)})
            progress["alternate_rim_depth_points"] = lip_points
            api.checkpoint("place.progress", progress)
            if len(lip_points) < 4:
                fail("Insufficient top-lip depths even with bounded radius-1 boundary sampling.")
            bp = plane_fit(np.array([v["world_m"] for v in lip_points]))
        g["rim_plane_depth_samples"] = lip_points
        if par["rim_model"] != "circular_horizontal_inner_lip" or len(par["rim_pixels"]) < 6 or bp["rms_m"] > 0.0015 or bp["coefficients"][2] < 0.995:
            fail("Inner-lip identity, plane or angular sampling is inadequate; no transfer authorized.")
        rim = np.array([api.plane_point(par["rim_camera"], uv, bp["coefficients"])["world_m"] for uv in par["rim_pixels"]])
        raw_circle = geo.circle_xy(rim)
        bc = {k: float(raw_circle[k]) for k in ("radius_m", "rms_m", "max_radial_error_m", "largest_angular_gap_rad")}
        bc["center_xy_m"] = np.array(raw_circle["center_xy_m"]).tolist()
        if bc["rms_m"] > 0.0015 or bc["max_radial_error_m"] > 0.0025 or bc["largest_angular_gap_rad"] > 1.8:
            fail("The measured inner opening does not support a sufficiently covered circular model.")
        g.update({"bowl_center": bc["center_xy_m"], "bowl_radius": bc["radius_m"], "rim_plane": bp, "rim_fit": bc, "rim_world_m": rim.tolist(), "rim_high": float(max(rim[:, 2])), "bowl_base_u": float(0.0015+bp["rms_m"]+bc["max_radial_error_m"]), "bowl_u": float(0.0015+bp["rms_m"]+bc["max_radial_error_m"]), "bowl_marks": xyz(o, ["b0", "b1"]).tolist(), "floor": xyz(o, ["floor"])[0].tolist(), "initial_frame": o["frame_id"]})
        if np.linalg.norm(np.array(g["floor"][:2])-np.array(g["bowl_center"])) > 0.65*g["bowl_radius"] or g["floor"][2] > g["rim_high"]-0.005:
            fail("The selected interior floor does not provide a consistent central cavity measurement.")
        def package(r):
            p = r["parameters"]
            if p["identity"] == "lost":
                fail("The carton is no longer retained.", True)
            if p["identity"] != "same_retained_carton" or not p["end_ids_match"] or len(p["end_pixels"]) != 2:
                fail("Current carton identity or the two physical short-end anchors is unresolved.")
            plane = plane_fit(xyz(r, ["p0", "p1", "p2", "p3"]))
            if plane["rms_m"] > 0.0012 or plane["coefficients"][2] < 0.995 or min(plane["in_plane_spread_m"]) < 5*max(0.0005, plane["rms_m"]):
                fail("Current top patch has inadequate planarity, orientation or spread relative to noise.")
            anchors = np.array([api.plane_point(p["end_camera"], uv, plane["coefficients"])["world_m"] for uv in p["end_pixels"]])
            eu = 0.0004
            for uv, anchor in zip(p["end_pixels"], anchors):
                for du, dv in ((2, 0), (-2, 0), (0, 2), (0, -2)):
                    perturbed = api.plane_point(p["end_camera"], [max(0, min(767, uv[0]+du)), max(0, min(767, uv[1]+dv))], plane["coefficients"])
                    eu = max(eu, float(np.linalg.norm(np.array(perturbed["world_m"])-anchor)))
            w = float(np.linalg.norm(anchors[1]-anchors[0]))
            if w < 8*eu or abs(w-g["width"]) > 2*eu+0.002:
                fail("Observed short end disagrees with the historical width or is noise-limited.")
            e = (anchors[1]-anchors[0])/w
            n = np.array(plane["coefficients"][:3])
            d = np.cross(n, e); d = d/np.linalg.norm(d)
            side = float(np.dot(d, np.array(plane["center_world_m"])-np.mean(anchors, axis=0)))
            if abs(side) < 4*eu:
                fail("Visible patch does not disambiguate which side of the measured end contains the carton.")
            if side < 0:
                d = -d
            top = np.array([anchors[0], anchors[1], anchors[1]+g["length"]*d, anchors[0]+g["length"]*d])
            box = np.concatenate((top, top-g["thickness_upper"]*n), axis=0)
            u = float(g["historical_extent_u"]+(1+2*g["length"]/w)*eu+2*plane["rms_m"])
            return {"box": box.tolist(), "anchors": anchors.tolist(), "center": np.mean(box, axis=0).tolist(), "u": u, "edge_u": float(eu), "plane": plane, "frame_id": r["frame_id"]}
        def bowl_check(r):
            if r["parameters"]["bowl"] == "changed":
                fail("The bowl moved or changed orientation.", True)
            if r["parameters"]["bowl"] != "same_upright_unchanged":
                fail("Bowl stationarity and upright identity are unresolved.")
            if r["parameters"]["bowl_reference_mode"] == "landmarks":
                drift = float(max(np.linalg.norm(xyz(r, ["b0", "b1"])-np.array(g["bowl_marks"]), axis=1)))
                if drift > max(0.004, 2*g["bowl_base_u"]):
                    fail("Independent bowl landmarks no longer support the opening reference.", True)
            elif r["parameters"]["bowl_reference_mode"] == "rim_samples":
                v = xyz(r, ["v0", "v1", "v2"])
                pe = max(abs(v @ np.array(g["rim_plane"]["coefficients"][:3])+g["rim_plane"]["coefficients"][3]))
                re = max(abs(np.linalg.norm(v[:, :2]-np.array(g["bowl_center"]), axis=1)-g["bowl_radius"]))
                span = max(float(np.linalg.norm(a-b)) for a in v for b in v)
                if pe > g["bowl_base_u"] or re > g["bowl_base_u"] or span < g["bowl_radius"]:
                    fail("Replacement visible rim samples cannot validate the stationary opening reference.")
                drift = max(float(pe), float(re))
            else:
                fail("Neither physical bowl landmarks nor replacement visible lip measurements are available.")
            g["bowl_u"] = g["bowl_base_u"]+drift
        def clearance(c, centered=False):
            b = np.array(c["box"])[:, :2]
            center = np.array(c["center"][:2]) if centered else np.array(g["bowl_center"])
            return float(g["bowl_radius"]-max(np.linalg.norm(b-center, axis=1))-c["u"]-g["bowl_u"])
        def finger_low(s):
            own = s["own_geometry"]; lo = own["finger_low_offset_tool_m"]; hi = own["finger_high_offset_tool_m"]
            corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
            return float(min((corners @ geo.rotation(s["tcp_quaternion_xyzw"]).T+np.array(s["tcp_position_world_m"]))[:, 2]))
        c = package(o)
        bowl_check(o)
        if clearance(c, True) <= 0.0035:
            fail("Measured carton-to-inner-opening fit margin is insufficient at the declared uncertainty and 1.5 mm controller tolerance.")
        g["current_carton"] = c
        api.checkpoint("place.geometry", g)
        state = api.state()
        rise = max(0.025, g["rim_high"]+0.025+c["u"]+g["bowl_u"]-min(min(np.array(c["box"])[:, 2]), finger_low(state)))
        if rise > 0.065:
            fail("Required local lift exceeds this method's observed upward corridor.")
        high = np.array(state["tcp_position_world_m"]); high[2] += rise
        transfer = high.copy(); transfer[:2] += np.array(g["bowl_center"])-np.array(c["center"][:2])
        if float(np.linalg.norm(transfer-high)) > 0.30:
            fail("The measured transfer is outside this local route's scope.")
        route = api.review("Assess the CURRENT visible local route in context: raise straight up, translate directly at the stated raised height to the bowl, then lower vertically while keeping the carton and finger bottoms above the lip. Check the carton/finger swept envelope against the bottle, bowl exterior, plate and other visible objects. Also assess lateral finger opening at the planned above-lip release location. Do not certify hidden clearance. Return unknown when the local route cannot be judged. No object release yet.", context={"geometry": g, "lift_target_tcp": high.tolist(), "transfer_target_tcp": transfer.tolist(), "actual_state": state, "open_finger_half_span_tool_m": 0.067, "planned_minimum_above_lip_m": c["u"]+g["bowl_u"]+0.0055}, fields={"corridor": ["clear", "obstructed", "unknown"], "opening_sweep": ["clear", "obstructed", "unknown"], "notes": "string"})
        if route["status"] == "stop" or route["parameters"]["corridor"] != "clear" or route["parameters"]["opening_sweep"] != "clear":
            fail("The local lift, transfer or finger-opening corridor is not supported: " + route["parameters"]["notes"])
        orientation = state["tcp_quaternion_xyzw"]
        def move(phase, target, calls, limit):
            before = api.state()
            n = min(calls, int(before["budgets"]["jev_remaining"])-6, int(before["budgets"]["native_steps_remaining"])//3-6)
            if n < 1:
                fail("Insufficient execution budget for a bounded local lease and observation.")
            progress["phase"] = phase
            progress["pending"] = {"target_tcp": target.tolist(), "gripper": "close"}
            api.checkpoint("place.progress", progress)
            receipt = api.drive(target.tolist(), orientation, "close", q, features={"phase": phase, "carton": c, "bowl_center": g["bowl_center"], "bowl_radius": g["bowl_radius"], "bowl_u": g["bowl_u"], "centered_fit_margin": clearance(c, True), "release_authorized": False}, max_calls=n, tool_point="tcp", translation_limit=limit, rotation_limit=0.03, steps=3, position_tolerance=0.0015, rotation_tolerance=0.025)
            after = api.state()
            progress["actions"].append({"phase": phase, "before": compact(before), "after": compact(after), "receipt": receipt})
            progress["pending"] = None
            api.checkpoint("place.progress", progress)
            if receipt["status"] != "reached" or after["last_gripper_command"] != "close":
                fail("Lease stopped without convergence or command agreement; no stalled contact will be repeated.")
            return before, after
        surface_question = "Reidentify the SAME retained carton and its two physical short-end corners c0,c1, as defined in context. Request p0,p1,p2,p3 on separated currently visible planar printed-top patches; return current end_pixels for those two boundary rays, not the hidden opposite corners. Check upright bowl stationarity. Prefer current b0,b1 at the exact stored physical bowl pattern identities; if occluded, use bowl_reference_mode=rim_samples and request v0,v1,v2 on three widely separated currently visible INNER TOP LIP locations instead. Never substitute projected old pixels or an outer rim for the inner lip."
        def refresh(old, before, after):
            r = ask(surface_question, common, {"reference_geometry": g, "previous_carton": old, "actual_before": compact(before), "actual_after": compact(after)}, ["p0", "p1", "p2", "p3"])
            new = package(r)
            error = float(geo.attachment_error(old["anchors"], new["anchors"], before, after))
            hand = float(np.linalg.norm(np.array(after["tcp_position_world_m"])-np.array(before["tcp_position_world_m"])))
            observed = float(np.linalg.norm(np.mean(new["anchors"], axis=0)-np.mean(old["anchors"], axis=0)))
            allowance = 0.002+2*(old["edge_u"]+new["edge_u"])
            progress["retention_check"] = {"frame_id": r["frame_id"], "actual_hand_motion_m": hand, "observed_end_motion_m": observed, "attachment_error_m": error, "allowance_m": allowance, "source": "Independently identified current end-boundary rays on measured current top planes; not commanded motion or closure."}
            if error > allowance or (hand > 4*allowance and observed < hand-allowance):
                fail("Current carton motion does not agree with actual hand motion.", True)
            bowl_check(r)
            g["current_carton"] = new
            api.checkpoint("place.geometry", g)
            return new
        before, after = move("raise_for_transfer", high, 20, 0.009)
        c = refresh(c, before, after)
        target = np.array(after["tcp_position_world_m"]); target[:2] += np.array(g["bowl_center"])-np.array(c["center"][:2])
        before, after = move("transfer_above_bowl", target, 32, 0.014)
        c = refresh(c, before, after)
        if clearance(c) <= 0.0035:
            correction = np.array(g["bowl_center"])-np.array(c["center"][:2])
            if clearance(c, True) <= 0.0035 or np.linalg.norm(correction) > 0.015:
                fail("Fresh overhead geometry does not support a bounded centering correction.")
            target = np.array(after["tcp_position_world_m"]); target[:2] += correction
            before, after = move("single_measured_centering_correction", target, 12, 0.004)
            c = refresh(c, before, after)
        if clearance(c) <= 0.0035:
            fail("Fresh measured opening clearance remains insufficient; do not lower or release.")
        low = min(float(min(np.array(c["box"])[:, 2])), finger_low(after))
        target = np.array(after["tcp_position_world_m"])
        target[2] += g["rim_high"]+c["u"]+g["bowl_u"]+0.0055-low
        if target[2] > after["tcp_position_world_m"][2]+0.003 or after["tcp_position_world_m"][2]-target[2] > 0.07:
            fail("Required release-height adjustment is outside the validated local descent.")
        before, after = move("lower_to_above_lip_release", target, 20, 0.006)
        c = refresh(c, before, after)
        bottom = float(min(np.array(c["box"])[:, 2]))
        if clearance(c) <= 0.0035 or min(bottom, finger_low(after))-g["rim_high"]-c["u"]-g["bowl_u"] < 0.003:
            fail("Actual release pose lacks the measured lateral or vertical lip margin.")
        if bottom-g["floor"][2] > 0.065:
            fail("The measured release drop is too large for this bounded placement.")
        progress["phase"] = "release"
        progress["release_started"] = True
        progress["release_geometry"] = {"carton": c, "opening_margin_m": clearance(c), "bottom_to_floor_m": bottom-g["floor"][2], "state": compact(after)}
        api.checkpoint("place.progress", progress)
        for i in range(4):
            s = api.state()
            receipt = api.control(s["tcp_position_world_m"], orientation, "open", q, features={"phase": "release", "release_authorized": True, "opening_margin_m": clearance(c), "geometry_frame": c["frame_id"]}, tool_point="tcp", translation_limit=0.002, rotation_limit=0.02, steps=3, position_tolerance=0.0015, rotation_tolerance=0.025)
            now = api.state()
            progress["actions"].append({"phase": "release_hold", "before": compact(s), "after": compact(now), "receipt": receipt})
            api.checkpoint("place.progress", progress)
            if now["last_gripper_command"] != "open" or np.linalg.norm(np.array(now["tcp_position_world_m"])-np.array(after["tcp_position_world_m"])) > 0.003:
                fail("Opening command mismatch or unexpected hand motion; opening will not be blindly repeated.")
            if i >= 1 and sum(abs(v) for v in now["gripper_qpos_m"]) >= 0.075:
                break
        end_fields = {"effect": ["contained_free", "still_retained", "rim_supported", "outside", "unknown"], "fingers": ["visibly_separated", "contacting", "unknown"], "bowl": ["same_upright_unchanged", "changed", "unknown"], "bowl_reference_mode": ["landmarks", "rim_samples", "unknown"], "support_description": "string"}
        final = ask("Inspect the actual release EFFECT, not the commanded gripper state. Is the SAME carton inside the upright bowl, free of both fingers, and not balanced on its rim? Request object on the currently visible carton surface inside the opening. Explicitly distinguish hidden support from visible separation. Reobserve b0,b1 at the stored bowl identities, or replace occluded landmarks with current inner-top-lip v0,v1,v2 as specified in context. This review assesses placement only, not final settled stability after withdrawal.", end_fields, {"geometry": g, "release": progress["release_geometry"], "actual_state": api.state()}, ["object"])
        bowl_check(final)
        pp = final["parameters"]
        point = xyz(final, ["object"])[0]
        evidence = {"postrelease": record(final), "actual_state": compact(api.state()), "release_geometry": progress["release_geometry"], "retention_before_release": progress["retention_check"]}
        if pp["effect"] in ("still_retained", "rim_supported", "outside"):
            return finish("needs_replan", "Fresh release evidence requires correction: " + pp["effect"], evidence)
        if pp["effect"] != "contained_free" or pp["fingers"] != "visibly_separated" or np.linalg.norm(point[:2]-np.array(g["bowl_center"])) >= g["bowl_radius"]-g["bowl_u"] or point[2] > g["rim_high"]+0.015:
            return finish("blocked", "Release was acknowledged, but fresh containment and finger separation remain unresolved.", evidence)
        return finish("stage_complete", "Fresh images and depth show the released carton inside the unchanged upright bowl and separated from the open fingers. Withdrawal and settled verification remain for the next stage.", evidence)
    except Exception as exc:
        return finish(progress.get("failure_status", "blocked"), str(exc))

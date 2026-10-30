def main(api):
    questions = {}
    for a in ("x", "y", "z", "rx", "ry", "rz"):
        questions[a] = {"type": "choice", "instructions": "Control world axis " + a + ". Read state.processed_features.axes." + a + ".goal_relation: increase selects positive, decrease selects negative, within_tolerance selects hold. Use host pose residuals, not imagined object measurements.", "criteria": {"negative": "Decrease this world coordinate or world rotation-vector component.", "hold": "This axis is within its declared tolerance.", "positive": "Increase this world coordinate or world rotation-vector component."}}
    questions["gripper"] = {"type": "choice", "instructions": "Read state.processed_features.objective.gripper. Close preserves the held carton; open is permitted only for an explicitly requested release after the program's effect-margin checks; keep preserves the previous command.", "criteria": {"open": "The objective requests open in the authorized release phase.", "close": "The objective requests close to retain the carton.", "keep": "The objective requests keep."}}
    progress = {"phase": "entry_audit", "actions": [], "release_started": False}
    g = {"position_tolerance_m": 0.0015, "rotation_tolerance_rad": 0.015, "required_margin_m": 0.0035}
    def state_record(s):
        return {k: s[k] for k in ("frame_id", "native_steps", "tcp_position_world_m", "tcp_quaternion_xyzw", "gripper_qpos_m", "last_gripper_command")}
    def fail(reason, replan=False):
        progress["failure_status"] = "needs_replan" if replan else "blocked"
        raise Exception(reason)
    def save():
        api.checkpoint("place.geometry", g)
        api.checkpoint("place.progress", progress)
    def finish(status, reason, evidence=None):
        progress["state"] = state_record(api.state())
        progress["stage_status"] = status
        progress["reason"] = reason
        save()
        return {"stage_status": status, "reason": reason, "completion_proposed": False, "evidence": evidence if evidence is not None else {"progress": progress, "geometry": g}, "handoff": {"checkpoint_keys": ["place.revision", "place.geometry", "place.progress", "place.effect", "secure.geometry", "secure.observations", "secure.retention"], "frames": "World metres; tool-to-world xyzw. Observation frame IDs and checkpoint receipt provenance remain authoritative.", "references": {"place.revision": "Original no-action placement rejection, entry audit, and historical reference provenance.", "place.geometry": "Measured historical carton dimensions and conservative uncertainty; current end anchors and top plane; inner-lip geometry; tested tilt candidates; latest observed fit margins.", "place.progress": "Pending phase, acknowledged whole-lease hand states and compact receipts, release flag, attachment tests, and actual terminal state.", "place.effect": "Latest raw or partial current review measurements, not automatically a successful effect."}, "actual_state": progress["state"], "release_started": progress["release_started"], "assumptions": ["Pickup was not repeated. No withdrawal or settled-verification stage is implemented.", "The same measured rigid rectangular carton is used; a short-edge tilt is an alternative projected-footprint candidate, not a reduced safety margin.", "Geometry is an operational visible-evidence model, not a hidden-clearance certificate. Revalidate it after motion.", "If release_started is true, audit actual support and separation before any further opening or transport."]}}
    def review_record(r):
        return {k: r[k] for k in ("frame_id", "status", "parameters", "points", "measurement_errors")}
    def good(r):
        bad = [e["name"] for e in r["measurement_errors"]]
        return {k: v for k, v in r["points"].items() if k not in bad and v["frame_id"] == r["frame_id"]}
    def ask(question, fields, context, required):
        r = api.review(question + " Use English ASCII; unknown means unobserved, never a projected historical point.", context=context, fields=fields)
        api.checkpoint("place.effect", review_record(r))
        if r["status"] == "stop":
            fail("Fresh review requested a stop: " + r["explanation"])
        def needed(rr):
            mode = rr["parameters"].get("bowl_reference_mode")
            return required + (["b0", "b1"] if mode == "landmarks" else ["v0", "v1", "v2"] if mode == "rim_samples" else [])
        missing = [k for k in needed(r) if k not in good(r)]
        if r["parameters"].get("bowl_reference_mode") == "unknown":
            missing.append("bowl_reference_mode")
        if missing:
            old = r
            r = api.review("Use a DIFFERENT depth-valid patch on the same specified surface, or the other camera, to replace missing measurements " + str(missing) + ". Preserve physical identities. For occluded bowl-pattern marks, switch to the declared rim_samples mode and obtain three separated visible inner-top-lip depths instead. " + question, context={"reference": context, "partial": review_record(old)}, fields=fields)
            api.checkpoint("place.effect", review_record(r))
            if r["status"] == "stop" or r["frame_id"] != old["frame_id"]:
                fail("Replacement measurement stopped or changed frame.")
            merged = good(old)
            merged.update(good(r))
            r["points"] = merged
            r["measurement_errors"] = [e for e in r["measurement_errors"] if e["name"] not in merged]
        api.checkpoint("place.effect", review_record(r))
        if any(k not in good(r) for k in needed(r)) or r["parameters"].get("bowl_reference_mode") == "unknown":
            fail("Missing current depths or bowl reference after one alternate observation: " + str([k for k in needed(r) if k not in good(r)]))
        return r
    def xyz(r, names):
        pts = good(r)
        if any(k not in pts for k in names):
            fail("Unavailable or invalid depth names: " + str(names))
        x = np.array([pts[k]["world_m"] for k in names], dtype=float)
        if x.shape != (len(names), 3) or not np.all(np.isfinite(x)):
            fail("Malformed or nonfinite point measurements.")
        return x
    def plane(points):
        f = geo.plane(points)
        return {"coefficients": np.array(f["coefficients"]).tolist(), "center_world_m": np.array(f["center_world_m"]).tolist(), "rms_m": float(f["rms_m"]), "in_plane_spread_m": np.array(f["in_plane_spread_m"]).tolist()}
    def path_value(root, path):
        if not path:
            fail("Missing historical numerical reference path.")
        for key in path:
            root = root[int(key)] if isinstance(root, list) else root[key]
        return root
    pixel = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}
    common = {"identity": ["same_retained_carton", "lost", "unknown"], "end_ids_match": "boolean", "end_camera": ["agentview", "robot0_eye_in_hand"], "end_pixels": {"type": "array", "items": pixel, "maxItems": 2}, "bowl": ["same_upright_unchanged", "changed", "unknown"], "bowl_reference_mode": ["landmarks", "rim_samples", "unknown"]}
    try:
        previous = api.recall("place.progress")
        old_effect = api.recall("place.effect")["value"]
        old = previous["value"]
        entry = api.state()
        progress["entry"] = state_record(entry)
        api.checkpoint("place.revision", {"previous_progress_record": previous, "entry": progress["entry"], "revision": "Test measured short-edge tilt while preserving previous fit and stopping margins."})
        if old.get("release_started", False) or len(old.get("actions", [])) or old.get("phase") != "entry":
            progress["release_started"] = old.get("release_started", False)
            progress["actions"] = old.get("actions", [])
            progress["prior_phase"] = old.get("phase")
            fail("Prior placement was not the acknowledged no-action entry rejection. Audit its actual pending or completed phase before further motion.")
        if entry["frame_id"] != old["state"]["frame_id"] or entry["last_gripper_command"] != "close":
            fail("Physical state changed since the no-action placement rejection; retention and prior action audit must be revised.", True)
        par = old_effect["parameters"]
        roots = {k: api.recall(k)["value"] for k in ("secure.geometry", "secure.observations", "secure.local")}
        if par["history_quality"] != "metric_rectangle_supported" or len(par["corner_paths"]) != 4:
            fail("No supported historical complete carton rectangle is available.")
        h = np.array([path_value(roots, p) for p in par["corner_paths"]], dtype=float)
        table = np.array(path_value(roots, par["table_path"]), dtype=float)
        if h.shape != (4, 3) or table.shape != (3,) or not np.all(np.isfinite(h)) or not np.all(np.isfinite(table)):
            fail("Invalid historical rectangle or support coordinates.")
        hp = plane(h)
        edges = np.roll(h, -1, axis=0)-h
        lengths = np.linalg.norm(edges, axis=1)
        mismatch = float(max(abs(lengths[0]-lengths[2]), abs(lengths[1]-lengths[3])))
        if min(lengths) <= 0 or hp["rms_m"] > 0.0015 or hp["coefficients"][2] < 0.995 or mismatch > 0.003 or np.linalg.norm(h[0]+h[2]-h[1]-h[3]) > 0.003 or abs(np.dot(edges[0], edges[1])) > 0.06*lengths[0]*lengths[1]:
            fail("Historical metric samples do not support the rectangular rigid-carton model.")
        inherited_u = float(path_value(roots, par["extent_uncertainty_path"])) if par["extent_uncertainty_path"] else 0.0015
        if not np.isfinite(inherited_u) or inherited_u < 0:
            fail("Invalid inherited extent uncertainty.")
        g.update({"length_m": float((lengths[1]+lengths[3])/2), "width_m": float((lengths[0]+lengths[2])/2), "thickness_upper_m": float(max(h[:, 2])-table[2]+0.002), "historical_extent_u_m": max(0.0015, inherited_u, 2*hp["rms_m"], mismatch/2), "historical_corners_world_m": h.tolist(), "support_world_m": table.tolist(), "historical_paths": par["corner_paths"], "uncertainty_path": par["extent_uncertainty_path"], "corner_ids": par["corner_ids"], "bowl_mark_ids": par["bowl_mark_ids"]})
        g["historical_provenance"] = [{k: m[k] for k in ("key", "frame_id", "method_number", "source_sha256")} for m in api.recall() if m["key"] in roots]
        if not 0.004 < g["thickness_upper_m"] < 0.06:
            fail("Unsupported thickness bound from historical top and table measurements.")
        fields = dict(common)
        fields.update({"history_matches": "boolean", "rim_model": ["circular_horizontal_inner_lip", "unknown"], "rim_camera": ["agentview", "robot0_eye_in_hand"], "rim_pixels": {"type": "array", "items": pixel, "maxItems": 12}})
        o = ask("Placement revision, not another pickup: the previous horizontal candidate failed its declared margin. We will retain that margin and consider a measured tilt about the carton's short edge, up to 1.20 rad, with its visible short end lower. Audit the supplied physical corner identities and rigid historical rectangle. Request p0,p1,p2,p3 on separated interior parts of the CURRENT printed top face, avoiding seams and fingers. Return end_pixels for the two visible physical corners c0,c1 at the Cream-initial-C short end, in that order; do not request hidden corners. Audit the previous bowl inner-versus-outer lip selection and correct it if necessary: request s0,s1,s2,s3 on separated depth-valid top-lip material, floor on the visible interior floor, and b0,b1 at the two supplied physical bowl-pattern identities. Return 6-12 distributed CURRENT INNER opening boundary pixels, not the outer silhouette or a lower wall contour. The bowl-reference mode here is landmarks. Do not invent a missing boundary.", fields, {"measured_history": g, "previous_current_review": old_effect, "retention": api.recall("secure.retention")["value"]}, ["p0", "p1", "p2", "p3", "floor", "b0", "b1"])
        p = o["parameters"]
        if p["identity"] == "lost" or p["bowl"] == "changed":
            fail("Entry evidence invalidates retention or the bowl configuration.", True)
        if not p["history_matches"] or p["rim_model"] != "circular_horizontal_inner_lip" or len(p["rim_pixels"]) < 6:
            fail("Current identity or inner-opening model is not supported.")
        lip = [v for k, v in good(o).items() if k in ("s0", "s1", "s2", "s3")]
        bp = None
        if len(lip) == 4:
            try:
                bp = plane(np.array([v["world_m"] for v in lip]))
            except Exception as exc:
                g["lip_plane_error"] = str(exc)
        if bp is None or bp["rms_m"] > 0.0015 or bp["coefficients"][2] < 0.995:
            lip = []
            g["alternate_lip_errors"] = []
            for uv in p["rim_pixels"]:
                try:
                    lip.append(api.point(p["rim_camera"], uv, radius=1))
                except Exception as exc:
                    g["alternate_lip_errors"].append({"pixel": uv, "error": str(exc)})
            g["alternate_lip_samples"] = lip
            save()
            if len(lip) < 4:
                fail("Neither broad top-lip patches nor radius-1 inner-lip sampling provides a valid plane.")
            bp = plane(np.array([v["world_m"] for v in lip]))
        if bp["rms_m"] > 0.0015 or bp["coefficients"][2] < 0.995:
            fail("Current top lip is not sufficiently planar and horizontal for the circular opening model.")
        rim = np.array([api.plane_point(p["rim_camera"], uv, bp["coefficients"])["world_m"] for uv in p["rim_pixels"]])
        fit = geo.circle_xy(rim)
        bc = {k: float(fit[k]) for k in ("radius_m", "rms_m", "max_radial_error_m", "largest_angular_gap_rad")}
        bc["center_xy_m"] = np.array(fit["center_xy_m"]).tolist()
        g["rim_fit"] = bc
        if bc["rms_m"] > 0.0015 or bc["max_radial_error_m"] > 0.0025 or bc["largest_angular_gap_rad"] > 1.8:
            fail("Current inner-opening circular fit or angular coverage failed.", False)
        radial_u = 0.0015
        for uv, point in zip(p["rim_pixels"], rim):
            for du, dv in ((2, 0), (-2, 0), (0, 2), (0, -2)):
                v = np.array(api.plane_point(p["rim_camera"], [max(0, min(767, uv[0]+du)), max(0, min(767, uv[1]+dv))], bp["coefficients"])["world_m"])
                radial_u = max(radial_u, float(abs(np.linalg.norm(v[:2]-np.array(bc["center_xy_m"]))-np.linalg.norm(point[:2]-np.array(bc["center_xy_m"])))))
        g.update({"bowl_center_xy_m": bc["center_xy_m"], "bowl_radius_m": bc["radius_m"], "rim_plane": bp, "rim_high_m": float(max(rim[:, 2])), "rim_world_m": rim.tolist(), "rim_depth_samples": lip, "bowl_base_u_m": float(radial_u+bp["rms_m"]+bc["max_radial_error_m"]), "bowl_marks_world_m": xyz(o, ["b0", "b1"]).tolist(), "floor_world_m": xyz(o, ["floor"])[0].tolist(), "reference_frame": o["frame_id"]})
        g["bowl_u_m"] = g["bowl_base_u_m"]
        if np.linalg.norm(np.array(g["floor_world_m"][:2])-np.array(g["bowl_center_xy_m"])) > 0.65*g["bowl_radius_m"] or g["floor_world_m"][2] > g["rim_high_m"]-0.005:
            fail("Interior-floor depth is inconsistent with a usable central cavity.")
        def carton(r):
            p = r["parameters"]
            if p["identity"] == "lost":
                fail("Carton retention was lost.", True)
            if p["identity"] != "same_retained_carton" or not p["end_ids_match"] or len(p["end_pixels"]) != 2:
                fail("Current carton identity or independent short-end corner correspondence is unresolved.")
            pl = None
            try:
                pl = plane(xyz(r, ["p0", "p1", "p2", "p3"]))
            except Exception as exc:
                g["top_plane_error"] = str(exc)
            if pl is None or pl["rms_m"] > 0.0012 or pl["coefficients"][2] < 0.30 or min(pl["in_plane_spread_m"]) < 5*max(0.0005, pl["rms_m"]):
                r = ask("Replace the inadequate top-plane measurement once using a more distributed depth-valid part of the SAME printed carton face or the other camera. Request p0,p1,p2,p3 away from seams, fingers and mixed-depth edges; preserve the two physical short-end identities c0,c1 and return their current end_pixels. Reidentify the same bowl with current b0,b1, or replacement v0,v1,v2 inner-lip samples if those marks are occluded. This is a different measurement region, not a relaxation of planarity or uncertainty.", common, {"geometry": g, "inadequate_review": review_record(r), "fit": pl}, ["p0", "p1", "p2", "p3"])
                p = r["parameters"]
                if p["identity"] == "lost" or p["bowl"] == "changed":
                    fail("Replacement observation shows retention loss or a changed bowl.", True)
                if p["identity"] != "same_retained_carton" or not p["end_ids_match"] or len(p["end_pixels"]) != 2:
                    fail("Replacement measurement has unresolved carton identities.")
                pl = plane(xyz(r, ["p0", "p1", "p2", "p3"]))
            spread = min(pl["in_plane_spread_m"])
            if pl["rms_m"] > 0.0012 or pl["coefficients"][2] < 0.30 or spread < 5*max(0.0005, pl["rms_m"]):
                fail("Top patch remains inadequate after one distinct measurement: orientation, residual or spread relative to noise.")
            anchors = np.array([api.plane_point(p["end_camera"], uv, pl["coefficients"])["world_m"] for uv in p["end_pixels"]])
            eu = 0.0004
            for uv, anchor in zip(p["end_pixels"], anchors):
                for du, dv in ((2, 0), (-2, 0), (0, 2), (0, -2)):
                    v = api.plane_point(p["end_camera"], [max(0, min(767, uv[0]+du)), max(0, min(767, uv[1]+dv))], pl["coefficients"])
                    eu = max(eu, float(np.linalg.norm(np.array(v["world_m"])-anchor)))
            width = float(np.linalg.norm(anchors[1]-anchors[0]))
            if width < 8*eu or abs(width-g["width_m"]) > 2*eu+0.002:
                fail("Current short end is noise-limited or inconsistent with measured historical width.")
            e = (anchors[1]-anchors[0])/width
            n = np.array(pl["coefficients"][:3])
            d = np.cross(n, e)
            d = d/np.linalg.norm(d)
            side = float(np.dot(d, np.array(pl["center_world_m"])-np.mean(anchors, axis=0)))
            if abs(side) < 4*eu:
                fail("Visible face does not disambiguate which side of the identified short edge contains the carton.")
            if side < 0:
                d = -d
            top = np.array([anchors[0], anchors[1], anchors[1]+g["length_m"]*d, anchors[0]+g["length_m"]*d])
            box = np.concatenate((top, top-g["thickness_upper_m"]*n), axis=0)
            radius = float(max(np.linalg.norm(box-np.array(api.state()["tcp_position_world_m"]), axis=1)))
            normal_u = 2*max(pl["rms_m"], 0.0002)/spread
            u = g["historical_extent_u_m"]+(1+2*g["length_m"]/width)*eu+2*pl["rms_m"]+g["length_m"]*normal_u+radius*g["rotation_tolerance_rad"]
            return {"box_world_m": box.tolist(), "center_world_m": np.mean(box, axis=0).tolist(), "anchors_world_m": anchors.tolist(), "short_axis_world": e.tolist(), "plane": pl, "normal_u_rad": float(normal_u), "u_m": float(u), "edge_u_m": eu, "frame_id": r["frame_id"]}
        def bowl_check(r):
            p = r["parameters"]
            if p["bowl"] == "changed":
                fail("Bowl displacement or orientation change invalidates placement references.", True)
            if p["bowl"] != "same_upright_unchanged":
                fail("Bowl identity and upright stationarity are unresolved.")
            if p["bowl_reference_mode"] == "landmarks":
                drift = float(max(np.linalg.norm(xyz(r, ["b0", "b1"])-np.array(g["bowl_marks_world_m"]), axis=1)))
                if drift > max(0.004, 2*g["bowl_base_u_m"]):
                    fail("Independent bowl landmarks no longer validate the opening reference.", True)
            elif p["bowl_reference_mode"] == "rim_samples":
                v = xyz(r, ["v0", "v1", "v2"])
                pe = float(max(abs(v @ np.array(g["rim_plane"]["coefficients"][:3])+g["rim_plane"]["coefficients"][3])))
                re = float(max(abs(np.linalg.norm(v[:, :2]-np.array(g["bowl_center_xy_m"]), axis=1)-g["bowl_radius_m"])))
                if max(pe, re) > g["bowl_base_u_m"] or max(float(np.linalg.norm(a-b)) for a in v for b in v) < g["bowl_radius_m"]:
                    fail("Replacement visible inner-lip samples do not validate the opening.")
                drift = max(pe, re)
            else:
                fail("Neither independently identified bowl landmarks nor replacement lip evidence is available.")
            g["bowl_u_m"] = g["bowl_base_u_m"]+drift
        def margin(c, centered=False, points=None):
            box = np.array(c["box_world_m"]) if points is None else points
            center = np.mean(box[:, :2], axis=0) if centered else np.array(g["bowl_center_xy_m"])
            return float(g["bowl_radius_m"]-max(np.linalg.norm(box[:, :2]-center, axis=1))-c["u_m"]-g["bowl_u_m"])
        def fingers(s):
            own = s["own_geometry"]
            lo = own["finger_low_offset_tool_m"]
            hi = own["finger_high_offset_tool_m"]
            pts = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
            t = np.eye(4)
            t[:3, :3] = geo.rotation(s["tcp_quaternion_xyzw"])
            t[:3, 3] = np.array(s["tcp_position_world_m"])
            return geo.transform(pts, t)
        def rotated(points, s, quaternion):
            rot = geo.rotation(quaternion) @ geo.rotation(s["tcp_quaternion_xyzw"]).T
            t = np.eye(4)
            t[:3, :3] = rot
            pivot = np.array(s["tcp_position_world_m"])
            t[:3, 3] = pivot-rot @ pivot
            return geo.transform(points, t)
        c = carton(o)
        bowl_check(o)
        s = api.state()
        g["current_carton"] = c
        g["candidate_tests"] = []
        chosen = None
        for magnitude in (0.0, 0.45, 0.70, 0.90, 1.05, 1.20):
            valid = []
            for angle in ([0.0] if magnitude == 0 else [-magnitude, magnitude]):
                quat = api.compose(s["tcp_quaternion_xyzw"], (np.array(c["short_axis_world"])*angle).tolist())
                box = rotated(c["box_world_m"], s, quat)
                m = margin(c, True, box)
                candidate = {"angle_rad": angle, "quaternion_xyzw": quat, "predicted_margin_m": m, "visible_end_mean_z_m": float(np.mean(box[:2, 2]))}
                g["candidate_tests"].append(candidate)
                if m > g["required_margin_m"]:
                    valid.append(candidate)
            if valid:
                chosen = sorted(valid, key=lambda item: item["visible_end_mean_z_m"])[0]
                break
        save()
        if chosen is None:
            fail("No measured horizontal or short-edge-tilt candidate through 1.20 rad passes the unchanged 3.5 mm residual fit margin. Numeric candidate deficits are saved; improved extent evidence or a different insertion plan is needed.")
        g["chosen_candidate"] = chosen
        sweep = np.concatenate((np.array(c["box_world_m"]), fingers(s)), axis=0)
        radius = float(max(np.linalg.norm(sweep-np.array(s["tcp_position_world_m"]), axis=1)))
        lowest = float(min(sweep[:, 2]))
        for j in range(9):
            quat = api.compose(s["tcp_quaternion_xyzw"], (np.array(c["short_axis_world"])*chosen["angle_rad"]*j/8).tolist())
            lowest = min(lowest, float(min(rotated(sweep, s, quat)[:, 2])))
        interpolation = radius*abs(chosen["angle_rad"])/16
        rise = max(0.025, g["rim_high_m"]+c["u_m"]+g["bowl_u_m"]+0.015-lowest+interpolation)
        if rise > 0.12:
            fail("Measured rotation envelope requires more than the bounded 0.12 m upward preparation.")
        high = np.array(s["tcp_position_world_m"])
        high[2] += rise
        predicted = rotated(c["box_world_m"], s, chosen["quaternion_xyzw"])+np.array([0.0, 0.0, rise])
        transfer = high.copy()
        transfer[:2] += np.array(g["bowl_center_xy_m"])-np.mean(predicted[:, :2], axis=0)
        if np.linalg.norm(transfer-high) > 0.30:
            fail("Required transfer exceeds this local placement scope.")
        route = ask("Assess this NEW measured placement candidate: raise straight up, tilt about the identified short edge at the raised TCP (no yaw-only substitution), translate at that height, then lower vertically with the entire carton and fingers remaining above the inner lip. The visible short end is preferably lower. Check the supplied sampled rotation/swept envelope and the local route against the bottle, bowl exterior, plate and table. Check the available lateral finger-opening space above the bowl. Do not infer hidden clearance. Is this a supported local route with a plausible retained pinch during the tilt?", {"corridor": ["clear", "obstructed", "unknown"], "tilt_grasp": ["supported", "unsupported", "unknown"], "opening_sweep": ["clear", "obstructed", "unknown"], "notes": "string"}, {"geometry": g, "actual_state": s, "raise_target_tcp": high.tolist(), "transfer_target_tcp": transfer.tolist(), "sampled_lowest_world_z_m": lowest, "between_sample_reserve_m": interpolation, "rise_m": rise, "gripper_policy": "Keep closed through raise, tilt and transport; release only above the lip after fresh checks."}, [])
        if route["parameters"]["corridor"] != "clear" or route["parameters"]["tilt_grasp"] != "supported" or route["parameters"]["opening_sweep"] != "clear":
            fail("The new candidate route or tilted pinch is not supported: " + route["parameters"]["notes"])
        orientation = s["tcp_quaternion_xyzw"]
        def move(phase, target, quat, calls, limit):
            before = api.state()
            n = min(calls, int(before["budgets"]["jev_remaining"])-12, int(before["budgets"]["native_steps_remaining"])//3-12)
            if n < 1 or before["budgets"]["gpt_remaining"] < 2:
                fail("Insufficient budget for this bounded lease and its fresh effect observation.")
            progress["phase"] = phase
            progress["pending"] = {"target_tcp_world_m": target.tolist(), "quaternion_xyzw": quat, "gripper": "close"}
            save()
            receipt = api.drive(target.tolist(), quat, "close", questions, features={"phase": phase, "carton_frame": c["frame_id"], "carton_u_m": c["u_m"], "bowl_u_m": g["bowl_u_m"], "centered_fit_margin_m": margin(c, True), "required_margin_m": g["required_margin_m"], "tilt_candidate": chosen, "release_authorized": False}, max_calls=n, tool_point="tcp", translation_limit=limit, rotation_limit=0.05, steps=3, position_tolerance=0.0015, rotation_tolerance=0.015)
            after = api.state()
            progress["actions"].append({"phase": phase, "before": state_record(before), "after": state_record(after), "receipt": {k: receipt[k] for k in ("frame_id", "status", "lease_calls", "acknowledged_steps", "choices", "position_error_m", "rotation_error_rad")}})
            progress["pending"] = None
            save()
            if receipt["status"] != "reached" or after["last_gripper_command"] != "close":
                fail("Lease failed convergence or closed-command agreement. No stalled contact or exhausted lease will be repeated.")
            return before, after
        surface_question = "After the acknowledged action, independently reidentify the SAME carton and physical short-end corners c0,c1 from context. Request p0,p1,p2,p3 on separated current printed-top face patches, which may now be tilted; return current end_pixels for c0,c1. No hidden opposite corners are required. Recheck the same upright bowl. Prefer b0,b1 at the exact stored physical pattern identities. If those are occluded, use bowl_reference_mode=rim_samples and request v0,v1,v2 on three well-separated visible INNER top-lip points, not the outside silhouette or lower wall. This replacement is allowed instead of repeatedly seeking occluded floor marks."
        def refresh(old_c, before, after):
            r = ask(surface_question, common, {"geometry": g, "actual_before": state_record(before), "actual_after": state_record(after)}, ["p0", "p1", "p2", "p3"])
            new = carton(r)
            error = float(geo.attachment_error(old_c["anchors_world_m"], new["anchors_world_m"], before, after))
            allowance = 0.002+2*(old_c["edge_u_m"]+new["edge_u_m"])
            expected_normal = geo.rotation(after["tcp_quaternion_xyzw"]) @ geo.rotation(before["tcp_quaternion_xyzw"]).T @ np.array(old_c["plane"]["coefficients"][:3])
            normal_error = float(np.arccos(np.clip(np.dot(expected_normal, new["plane"]["coefficients"][:3]), -1.0, 1.0)))
            test = {"before_frame": before["frame_id"], "after_frame": after["frame_id"], "actual_hand_translation_m": (np.array(after["tcp_position_world_m"])-np.array(before["tcp_position_world_m"])).tolist(), "observed_end_translation_m": (np.mean(new["anchors_world_m"], axis=0)-np.mean(old_c["anchors_world_m"], axis=0)).tolist(), "attachment_error_m": error, "allowance_m": allowance, "normal_error_rad": normal_error, "source": "Current independent physical end correspondences plus measured top normals, compared to actual whole-lease TCP rigid motion."}
            progress["retention_check"] = test
            g["current_carton"] = new
            save()
            if error > allowance or normal_error > 0.04+old_c["normal_u_rad"]+new["normal_u_rad"]:
                fail("Carton motion or top normal does not agree with the actual hand transform.", True)
            bowl_check(r)
            save()
            return new
        before, after = move("raise_for_tilt_and_transfer", high, orientation, 24, 0.012)
        c = refresh(c, before, after)
        if chosen["angle_rad"] != 0:
            predicted = rotated(c["box_world_m"], after, chosen["quaternion_xyzw"])
            g["pretilt_revalidated_margin_m"] = margin(c, True, predicted)
            current_sweep = np.concatenate((np.array(c["box_world_m"]), fingers(after)), axis=0)
            sweep_radius = float(max(np.linalg.norm(current_sweep-np.array(after["tcp_position_world_m"]), axis=1)))
            sweep_low = float(min(current_sweep[:, 2]))
            for j in range(9):
                sample_q = api.compose(after["tcp_quaternion_xyzw"], (np.array(c["short_axis_world"])*chosen["angle_rad"]*j/8).tolist())
                sweep_low = min(sweep_low, float(min(rotated(current_sweep, after, sample_q)[:, 2])))
            g["pretilt_vertical_margin_m"] = sweep_low-g["rim_high_m"]-c["u_m"]-g["bowl_u_m"]-sweep_radius*(abs(chosen["angle_rad"])/16+0.03)
            save()
            if g["pretilt_revalidated_margin_m"] <= 0.0035 or g["pretilt_vertical_margin_m"] <= 0.0035:
                fail("Fresh raised-pose measurements invalidate the selected tilt fit or vertical sweep; no rotation authorized.")
            before, after = move("short_edge_tilt", np.array(after["tcp_position_world_m"]), chosen["quaternion_xyzw"], 36, 0.003)
            c = refresh(c, before, after)
            orientation = chosen["quaternion_xyzw"]
        g["pretransfer_vertical_margin_m"] = min(float(min(np.array(c["box_world_m"])[:, 2])), float(min(fingers(after)[:, 2])))-g["rim_high_m"]-c["u_m"]-g["bowl_u_m"]
        save()
        if margin(c, True) <= 0.0035 or g["pretransfer_vertical_margin_m"] <= 0.0035:
            fail("Actual measured orientation lacks the required projected-footprint or above-lip transfer margin.")
        target = np.array(after["tcp_position_world_m"])
        target[:2] += np.array(g["bowl_center_xy_m"])-np.array(c["center_world_m"][:2])
        before, after = move("transfer_above_bowl", target, orientation, 36, 0.016)
        c = refresh(c, before, after)
        if margin(c) <= 0.0035:
            correction = np.array(g["bowl_center_xy_m"])-np.array(c["center_world_m"][:2])
            if margin(c, True) <= 0.0035 or np.linalg.norm(correction) > 0.018:
                fail("Fresh overhead measurements do not support a small centering correction.")
            target = np.array(after["tcp_position_world_m"])
            target[:2] += correction
            before, after = move("single_measured_centering", target, orientation, 12, 0.004)
            c = refresh(c, before, after)
        low = min(float(min(np.array(c["box_world_m"])[:, 2])), float(min(fingers(after)[:, 2])))
        if margin(c) <= 0.0035:
            fail("Observed opening margin is insufficient; descent and release remain unauthorized.")
        target = np.array(after["tcp_position_world_m"])
        target[2] += g["rim_high_m"]+c["u_m"]+g["bowl_u_m"]+0.0055-low
        if target[2] > after["tcp_position_world_m"][2]+0.003 or after["tcp_position_world_m"][2]-target[2] > 0.10:
            fail("Required release-height adjustment exceeds the validated local descent.")
        before, after = move("lower_to_above_lip_release", target, orientation, 22, 0.006)
        c = refresh(c, before, after)
        bottom = float(min(np.array(c["box_world_m"])[:, 2]))
        vertical = min(bottom, float(min(fingers(after)[:, 2])))-g["rim_high_m"]-c["u_m"]-g["bowl_u_m"]
        g["observed_release_margins"] = {"lateral_m": margin(c), "vertical_m": vertical, "drop_to_floor_m": bottom-g["floor_world_m"][2], "frame_id": c["frame_id"]}
        save()
        if margin(c) <= 0.0035 or vertical < 0.003 or bottom-g["floor_world_m"][2] > 0.065:
            fail("Actual pose lacks the declared lateral, vertical, or bounded-drop release condition.")
        release_review = ask("At this CURRENT actual pose, check the immediate finger-opening sweep and impending short drop. Is the carton over the inner opening with no rim contact, both fingers clear of the lip throughout sideways opening, and no visible obstacle in the opening sweep? Judge the tilted carton if applicable. Do not certify unseen contact space; return unknown if occluded. No opening has yet been commanded.", {"opening": ["clear", "obstructed", "unknown"], "contact": ["none_visible", "rim_or_other_contact", "unknown"], "notes": "string"}, {"geometry": g, "actual_state": after}, [])
        if release_review["parameters"]["opening"] != "clear" or release_review["parameters"]["contact"] != "none_visible":
            fail("Fresh release-sweep observation is insufficient: " + release_review["parameters"]["notes"])
        progress["phase"] = "release"
        progress["release_started"] = True
        progress["release_reference"] = {"carton": c, "margins": g["observed_release_margins"], "state": state_record(after)}
        save()
        release_target = after["tcp_position_world_m"]
        for i in range(4):
            before_open = api.state()
            receipt = api.control(release_target, orientation, "open", questions, features={"phase": "release", "release_authorized": True, "measured_release_margins": g["observed_release_margins"]}, tool_point="tcp", translation_limit=0.002, rotation_limit=0.02, steps=3, position_tolerance=0.0015, rotation_tolerance=0.015)
            now = api.state()
            progress["actions"].append({"phase": "release_hold", "before": state_record(before_open), "after": state_record(now), "receipt": {k: receipt[k] for k in ("frame_id", "status", "acknowledged_steps", "choices")}})
            save()
            if now["last_gripper_command"] != "open" or np.linalg.norm(np.array(now["tcp_position_world_m"])-np.array(release_target)) > 0.003 or receipt["choices"]["gripper"] != "open":
                fail("Release command mismatch or unexpected hand drift; do not blindly repeat opening.")
            if i >= 1 and sum(abs(v) for v in now["gripper_qpos_m"]) >= 0.075:
                break
        fields = {"effect": ["inside_free", "still_retained", "rim_supported", "outside", "unknown"], "fingers": ["visibly_separated", "contacting", "unknown"], "bowl": ["same_upright_unchanged", "changed", "unknown"], "bowl_reference_mode": ["landmarks", "rim_samples", "unknown"], "support_description": "string"}
        final = ask("Assess the actual release effect, not the gripper command. inside_free requires the SAME carton visibly inside the upright bowl, free of both fingers, and not balanced on the rim. Request object on a visible carton surface portion inside the cavity, preferably below the inner lip; do not select the bowl or a hidden bottom. Reobserve b0,b1 by physical identity, or replace occluded marks with current widely separated inner-top-lip v0,v1,v2. Explicitly describe visible containment and finger gaps. This is placement assessment only; no withdrawal or settled-stability certification is requested.", fields, {"geometry": g, "release_reference": progress["release_reference"], "actual_state": api.state()}, ["object"])
        bowl_check(final)
        pp = final["parameters"]
        point = xyz(final, ["object"])[0]
        evidence = {"postrelease": review_record(final), "actual_state": state_record(api.state()), "release_margins": g["observed_release_margins"], "retention_before_release": progress["retention_check"]}
        if pp["effect"] in ("still_retained", "rim_supported", "outside"):
            return finish("needs_replan", "Fresh release evidence requires correction: " + pp["effect"], evidence)
        if pp["effect"] != "inside_free" or pp["fingers"] != "visibly_separated" or np.linalg.norm(point[:2]-np.array(g["bowl_center_xy_m"])) >= g["bowl_radius_m"]-g["bowl_u_m"] or point[2] > g["rim_high_m"]+g["bowl_u_m"]:
            return finish("blocked", "Opening was acknowledged, but visible containment, a carton depth inside the lip, or independent finger separation is unresolved.", evidence)
        return finish("stage_complete", "Fresh images and carton depth show release inside the unchanged upright bowl, with visible separation from both fingers. Withdrawal and settled verification remain.", evidence)
    except Exception as exc:
        return finish(progress.get("failure_status", "blocked"), str(exc))

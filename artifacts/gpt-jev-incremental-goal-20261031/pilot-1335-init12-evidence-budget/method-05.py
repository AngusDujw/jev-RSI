def main(api):
    d = {"reviews": 0, "calls": 0, "effects": [], "geometry": {}, "failure": None}
    labels = ["p0: apex of thin blue outline above capital C in Cream", "p1: center of light oval inside right curl of capital C", "p2: center of light counter of lowercase e in Cream", "p3: center of light counter of lowercase a in Cream"]
    tri = ["clear", "blocked", "unknown"]
    fields = {"identity": ["correct", "wrong", "unknown"], "valid_landmarks": {"type": "array", "items": {"type": "boolean"}, "minItems": 4, "maxItems": 4}, "bowl_stationary": ["yes", "no", "unknown"], "slip": ["none", "observed", "unknown"], "upward": tri, "lateral": tri, "placement": tri, "release": tri, "withdrawal": tri, "upward_observation_gain": ["supported", "unknown"], "hazards": {"type": "string", "maxLength": 1000}}
    pixel = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}
    mf = dict(fields)
    mf.update({"extent_model": ["supported", "changed", "unknown"], "face_model": ["planar_package_face", "other", "unknown"], "table_model": ["same_horizontal_table", "other", "unknown"], "edge_identity": ["complete_short_end", "other", "unknown"], "edge_camera": ["agentview", "robot0_eye_in_hand"], "edge_pixels": {"type": "array", "items": pixel, "minItems": 0, "maxItems": 2}, "rim_identity": ["horizontal_circular_inner_boundary", "other", "unknown"], "rim_camera": ["agentview", "robot0_eye_in_hand"], "rim_pixels": {"type": "array", "items": pixel, "minItems": 0, "maxItems": 8}, "surface_exclusions": {"type": "array", "items": {"type": "string", "maxLength": 32}, "maxItems": 16}})
    mf["rim_regions_valid"] = {"type": "array", "items": {"type": "boolean"}, "minItems": 3, "maxItems": 3}
    questions = {}
    for axis in ["x", "y", "z", "rx", "ry", "rz"]:
        questions[axis] = {"type": "choice", "instructions": "For world axis " + axis + ", use state.processed_features.axes." + axis + ".goal_relation. Select positive for increase, negative for decrease, hold for within_tolerance. This is bounded fixed-orientation transport of an already held package; do not infer object geometry or change phase.", "criteria": {"negative": "Decrease this world translation or world rotation-vector component.", "hold": "No correction on this component; its residual is within the supplied deadband.", "positive": "Increase this world translation or world rotation-vector component."}}
    questions["gripper"] = {"type": "choice", "instructions": "Read state.processed_features.objective.gripper. Keep means maintain the existing closed grasp, not another grasp attempt. Match the objective exactly.", "criteria": {"open": "Deliver an explicitly requested opening.", "close": "Deliver an explicitly requested closure.", "keep": "Preserve the existing gripper command without reopening or retrying contact."}}
    def fail(name, action, operands, status="blocked"):
        d["failure"] = {"gate": name, "prevented_action": action, "operands": operands, "frame_id": api.state()["frame_id"], "classification": "Runtime budgets are external constraints; historical extents are measured/model bounds; uncertainty allowances, fit tests and stopping margins are operational heuristics."}
        d["status"] = status
        api.checkpoint("deliver_gate", d["failure"])
        raise Exception(name)
    def need(ok, name, action, operands, status="blocked"):
        if not ok:
            fail(name, action, operands, status)
    def review(question, context, schema):
        s = api.state()
        need(d["reviews"] < 3 and s["budgets"]["gpt_remaining"] > 13, "Review allocation", "observation before further action", {"repair_reviews_used": d["reviews"], "maximum": 3, "remaining": s["budgets"]["gpt_remaining"], "reserve_including_supervision": 13})
        d["reviews"] += 1
        r = api.review(question, context=context, fields=schema)
        compact = {"frame_id": r["frame_id"], "parameters": r["parameters"], "points": r["points"], "measurement_errors": [{"name": v["name"], "error": str(v["error"])[:200]} for v in r["measurement_errors"]]}
        d["measurement_history"] = (d.get("measurement_history", [])+[compact])[-2:]
        api.checkpoint("deliver_measure", {"observations": d["measurement_history"]})
        need(r["status"] != "stop", "Observation stop", "any further motion", {"explanation": r["explanation"]}, "abort")
        return r
    def points(r, names):
        bad = [v["name"] for v in r["measurement_errors"]]
        excluded = r["parameters"].get("surface_exclusions", [])
        return {k: r["points"][k] for k in names if k in r["points"] and k not in bad and k not in excluded}
    def error(p):
        k = api.camera(p["camera"])["K"]
        return 0.0005 + math.sqrt(2.0) * p["depth_m"] / min(k[0][0], k[1][1])
    def landmarks(r):
        pp = points(r, ["p0", "p1", "p2", "p3"])
        return {k: v for k, v in pp.items() if r["parameters"]["valid_landmarks"][int(k[1])]}
    def xyz(pp):
        return np.array([v["world_m"] for v in pp.values()])
    def checked_plane(pp, name, minimum):
        need(len(pp) >= minimum, name + " membership", "geometric calculation", {"valid_measurements": pp, "minimum": minimum})
        try:
            fit = geo.plane(xyz(pp))
        except Exception as exc:
            fail(name+" fit rejected", "use of planar model", {"error": str(exc), "measurements": pp})
        u = max([error(v) for v in pp.values()]) + 2.0 * fit["rms_m"]
        need(fit["rms_m"] <= 0.0015, name + " planarity", "use of planar model", {"rms_m": fit["rms_m"], "threshold_m": 0.0015, "residual_margin_m": 0.0015-fit["rms_m"], "uncertainty_m": u, "frames": [v["frame_id"] for v in pp.values()]})
        return fit, u
    def geometry(r, dims):
        p = r["parameters"]
        need(p["identity"] == "correct" and p["extent_model"] == "supported" and p["face_model"] == "planar_package_face" and p["table_model"] == "same_horizontal_table", "Package and extent identity", "separation calculation", {"identity": p["identity"], "extent_model": p["extent_model"], "face": p["face_model"], "table": p["table_model"]})
        ff = points(r, ["f0", "f1", "f2", "f3", "f4", "f5"])
        tt = points(r, ["t0", "t1", "t2", "t3"])
        f, u = checked_plane(ff, "Wide package patch", 5)
        t, tu = checked_plane(tt, "Table patch", 3)
        n = np.array(f["coefficients"][:3])
        spread = min(f["in_plane_spread_m"])
        need(spread > u, "Observable face normal", "separation calculation", {"spread_m": spread, "point_and_model_uncertainty_m": u, "threshold_m": u, "residual_margin_m": spread-u})
        angle = math.acos(min(1.0, max(0.0, float(n[2])))) + math.asin(min(1.0, u/spread))
        need(angle < 0.30 and t["coefficients"][2] > math.cos(0.05), "Horizontal face and table model", "bounded box interpretation", {"tilt_upper_rad": angle, "tilt_threshold_rad": 0.30, "residual_margin_rad": 0.30-angle, "table_normal_z": t["coefficients"][2], "table_threshold": math.cos(0.05), "uncertainty_m": [u, tu]})
        table_upper = float(np.max(xyz(tt)[:, 2])) + tu
        bottom = float(np.min(xyz(ff)[:, 2])) - u - dims["thickness_upper_m"] - dims["diagonal_upper_m"]*math.sin(angle)
        sep = {"lower_m": bottom-table_upper, "threshold_m": 0.002, "residual_margin_m": bottom-table_upper-0.002, "bottom_lower_world_z_m": bottom, "table_upper_world_z_m": table_upper, "face_uncertainty_m": u, "table_uncertainty_m": tu, "normal_sine_uncertainty": u/spread, "tilt_upper_rad": angle, "spread_m": spread, "frame_id": r["frame_id"], "dimensions": dims}
        need(sep["residual_margin_m"] > 0, "Whole-package table separation", "lateral transport", sep)
        need(p["edge_identity"] == "complete_short_end" and len(p["edge_pixels"]) == 2, "Exposed short-end identity", "package envelope alignment", {"identity": p["edge_identity"], "pixels": p["edge_pixels"]})
        ep = [api.plane_point(p["edge_camera"], v, f["coefficients"]) for v in p["edge_pixels"]]
        ee = np.array([v["world_m"] for v in ep]); mid = np.mean(ee, axis=0); edge = ee[1, :2]-ee[0, :2]
        cam = api.camera(p["edge_camera"]); origin = np.array(cam["camera_to_world_opencv"])[:3, 3]
        eu = 0.0
        for v in ee:
            ray = v-origin; plane_error = u+float(np.linalg.norm(v-np.array(f["center_world_m"])))*min(1.0, u/spread)
            eu = max(eu, math.sqrt(2.0)*float(np.linalg.norm(ray))/min(cam["K"][0][0], cam["K"][1][1])+plane_error*float(np.linalg.norm(ray[:2]))/max(0.000001, abs(float(np.dot(n, ray)))))
        width = float(np.linalg.norm(edge))
        need(width > 4*eu and width+2*eu < dims["diagonal_upper_m"], "Short-edge extent", "enclosing rectangle construction", {"width_m": width, "edge_uncertainty_m": eu, "lower_threshold_m": 4*eu, "upper_threshold_m": dims["diagonal_upper_m"]-2*eu, "residual_margin_m": min(width-4*eu, dims["diagonal_upper_m"]-2*eu-width)})
        direction = np.array([-edge[1], edge[0]])/width
        if float(np.dot(direction, np.mean(xyz(ff), axis=0)[:2]-mid[:2])) < 0:
            direction = -direction
        length = math.sqrt(dims["diagonal_upper_m"]**2-max(0.0, width-2*eu)**2)
        center_xy = mid[:2]+0.5*length*direction
        skew = math.asin(min(1.0, math.sin(angle)**2/(2*math.cos(angle))))
        direction_error = math.atan2(2*eu, width-2*eu) + skew
        center_u = eu + 0.5*length*(2*math.sin(direction_error/2)+1-math.cos(angle))
        radius = 0.5*math.sqrt(length**2+(width+2*eu)**2) + center_u + dims["thickness_upper_m"]*math.sin(angle)
        center_z = -(f["coefficients"][0]*center_xy[0]+f["coefficients"][1]*center_xy[1]+f["coefficients"][3])/n[2]
        return {"pose_tolerance_m": 0.002, "separation": sep, "package_center_world_m": [float(center_xy[0]), float(center_xy[1]), float(center_z)], "package_radius_upper_m": radius, "package_center_uncertainty_m": center_u, "face_plane": f, "short_edge": ep, "face_points_world_m": xyz(ff).tolist(), "table_points_world_m": xyz(tt).tolist(), "floor": points(r, ["floor"]), "dimensions": dims, "frame_id": r["frame_id"]}
    def rim_support(r, minimum):
        p = r["parameters"]; bad = [v["name"] for v in r["measurement_errors"]]
        selected = {}; sectors = []
        for i in range(3):
            key = "rim"+str(i)
            if key not in r["regions"] or key in bad or not p["rim_regions_valid"][i]:
                continue
            region = r["regions"][key]
            box = region["box"]
            need(region["stride"] == 4 and max(box[2]-box[0], box[3]-box[1]) <= 32, "Scoped rim region", "lip sample selection", {"box": box, "stride": region["stride"], "maximum_side_px": 32, "required_stride": 4, "frame_id": r["frame_id"]})
            if region["frame_id"] != r["frame_id"] or len(region["world_m"]) < 3:
                continue
            cloud = np.array(region["world_m"])
            if not bool(np.all(np.isfinite(cloud))):
                continue
            # Only reviewed bowl-lip/table boxes qualify. Never select maxima
            # from boxes containing fingers, bottle or unidentified foreground.
            top = float(np.max(cloud[:, 2]))
            ids = np.where(cloud[:, 2] >= top-0.001)[0]
            ids = ids[::max(1, int(len(ids)//4))][:4]
            cam = api.camera(region["camera"]); origin = np.array(cam["camera_to_world_opencv"])[:3, 3]
            for j in ids:
                pt = cloud[j]
                selected[key+"_"+str(int(j))] = {"world_m": pt.tolist(), "depth_m": float(np.linalg.norm(pt-origin)), "camera": region["camera"], "pixel": region["pixels"][int(j)], "frame_id": region["frame_id"], "source": "reviewed_upper_lip_cloud_range_bound"}
            sectors.append({"name": key, "top_z_m": top, "box": region["box"], "count": len(ids)})
        api.checkpoint("deliver_measure", {"observations": [{"frame_id": r["frame_id"], "parameters": p, "points": r["points"], "rim_support": selected, "sectors": sectors, "measurement_errors": r["measurement_errors"]}]})
        need(len(sectors) >= minimum and len(selected) >= 3, "Depth-valid lip sectors", "opening geometry or final validation", {"sectors": sectors, "required_sectors": minimum, "valid_points": len(selected), "frame_id": r["frame_id"], "measurement_errors": r["measurement_errors"]}, "needs_replan")
        heights = [v["top_z_m"] for v in sectors]; delta = max(heights)-min(heights)
        need(delta <= 0.0025, "Common lip height", "horizontal opening model", {"sector_tops_world_z_m": heights, "threshold_m": 0.0025, "residual_margin_m": 0.0025-delta, "upper_layer_m": 0.001, "frame_id": r["frame_id"]}, "needs_replan")
        return selected
    def opening(r, g):
        p = r["parameters"]
        need(p["rim_identity"] == "horizontal_circular_inner_boundary" and len(p["rim_pixels"]) >= 5, "Inner boundary identity", "opening estimate", {"identity": p["rim_identity"], "visible_boundary_count": len(p["rim_pixels"]), "frame_id": r["frame_id"]}, "needs_replan")
        support = rim_support(r, 3); bf, noise = checked_plane(support, "Current lip sectors", 6)
        zs = xyz(support)[:, 2]; level_z = float(np.mean(zs))
        # A level-rim model is checked by sector heights and the unconstrained
        # fit. Surface sampling is not landmark correspondence uncertainty.
        bu = 0.0005+2*bf["rms_m"]+0.001+0.5*float(np.max(zs)-np.min(zs))
        level = [0.0, 0.0, 1.0, -level_z]
        spread = min(bf["in_plane_spread_m"])
        need(bf["coefficients"][2] > math.cos(0.08) and spread > 4*bu, "Opening plane observability", "boundary ray intersection", {"normal_z": bf["coefficients"][2], "normal_threshold": math.cos(0.08), "spread_m": spread, "uncertainty_m": bu, "spread_threshold_m": 4*bu, "residual_margin_m": spread-4*bu, "normal_margin": bf["coefficients"][2]-math.cos(0.08), "frame_id": r["frame_id"]}, "needs_replan")
        rr = []
        try:
            for pix in p["rim_pixels"]:
                rr.append(api.plane_point(p["rim_camera"], pix, level))
            cc = geo.circle_xy(np.array([v["world_m"] for v in rr]))
        except Exception as exc:
            fail("Opening ray or circle fit", "opening estimate", {"error": str(exc), "points": rr, "level_plane": level, "plane_fit": bf, "height_uncertainty_m": bu, "frame_id": r["frame_id"]}, "needs_replan")
        cam = api.camera(p["rim_camera"]); origin = np.array(cam["camera_to_world_opencv"])[:3, 3]; n = np.array(level[:3])
        ray_u = 0.0
        for v in rr:
            x = np.array(v["world_m"]); ray = x-origin
            plane_u = bu
            ray_u = max(ray_u, math.sqrt(2.0)*float(np.linalg.norm(ray))/min(cam["K"][0][0], cam["K"][1][1])+plane_u*float(np.linalg.norm(ray[:2]))/max(0.000001, abs(float(np.dot(n, ray)))))
        u = ray_u+cc["max_radial_error_m"]
        gate = {"gap_rad": cc["largest_angular_gap_rad"], "gap_threshold_rad": 2.0, "radial_error_m": cc["max_radial_error_m"], "error_threshold_m": 0.003, "plane_uncertainty_m": bu, "ray_uncertainty_m": ray_u, "residual_margin_m": 0.003-cc["max_radial_error_m"], "frame_id": r["frame_id"]}
        need(cc["largest_angular_gap_rad"] < 2.0 and cc["max_radial_error_m"] < 0.003, "Visible opening coverage", "opening fit", gate, "needs_replan")
        radii = [float(np.linalg.norm(np.array(v["world_m"][:2])-np.array(cc["center_xy_m"]))) for v in support.values()]
        bowl = {"center_xy_m": cc["center_xy_m"], "radius_lower_m": cc["radius_m"]-u, "rim_upper_z_m": max([v["world_m"][2] for v in support.values()])+bu, "rim_lower_z_m": min([v["world_m"][2] for v in support.values()])-bu, "circle": cc, "uncertainty_m": u, "plane": bf, "intersection_plane": level, "height_uncertainty_m": bu, "height_error_terms_m": [0.0005, 2*bf["rms_m"], 0.001, 0.5*float(np.max(zs)-np.min(zs))], "rim_measurements": rr, "support_points": support, "support_radial_range_m": [min(radii), max(radii)], "frame_id": r["frame_id"]}
        free = bowl["radius_lower_m"]-g["package_radius_upper_m"]
        g["pose_tolerance_m"] = min(0.002, max(0.0005, (free-0.001)/2))
        g["fit_margin_m"] = free-g["pose_tolerance_m"]; g["bowl"] = bowl
        return bowl
    def semantic(p, phase):
        need(p["identity"] == "correct" and p["slip"] != "observed", "Held-object identity and slip", phase, {"identity": p["identity"], "slip": p["slip"]}, "needs_replan")
        for k in ["placement", "release", "withdrawal"]:
            need(p[k] != "blocked", "Established " + k + " obstruction", phase, {"condition": p[k], "hazards": p["hazards"]}, "needs_replan")
    def finger_low(s):
        lo = s["own_geometry"]["finger_low_offset_tool_m"]; hi = s["own_geometry"]["finger_high_offset_tool_m"]
        corners = np.array([[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]])
        return float(s["tcp_position_world_m"][2] + np.min((geo.rotation(s["tcp_quaternion_xyzw"]) @ corners.T)[2]))
    def effect(phase, final=False):
        ef = dict(mf)
        r = review("Verify the acknowledged " + phase + ". Request p0..p3 at the independently identified physical graphic landmarks, not old pixel projections. Judge actual slip and bowl stationarity. Reassess the exact remaining admitted route and separately descent, finger opening and straight upward withdrawal; unknown remains unknown. For final=true also request f0..f5 widely spread on the visible planar package face and t0..t3 on the same table, validate extent_model and give the SAME complete short-end edge pixels. These fresh measurements determine final package geometry rather than assuming perfect hand attachment. For final=true request up to three small rim0,rim1,rim2 cloud regions as specified by rim_sampling, using whichever camera has valid visible sectors. Two distinct sectors suffice for checking the existing bowl model; do not request discontinuous boundary depth points. Set irrelevant pixel arrays empty and irrelevant fields unknown on departure. Do not infer hidden clearance or authorize release.", {"labels": labels, "reference_landmarks": d["baseline_points"], "whole_motion_start_state": d["baseline_state"], "geometry": d["geometry"], "route": d["route"], "final": final, "rim_sampling": d["rim_sampling"]}, ef)
        pp = landmarks(r); common = [k for k in pp if k in d["baseline_points"]]
        need(len(common) >= 3, "Current identified landmark membership", "further transport or stage acceptance", {"common": common, "measurement_errors": r["measurement_errors"], "frame_id": r["frame_id"]})
        before = d["baseline_state"]; after = api.state()
        old = [d["baseline_points"][k]["world_m"] for k in common]; new = [pp[k]["world_m"] for k in common]
        u0 = max([error(d["baseline_points"][k]) for k in common]); u1 = max([error(pp[k]) for k in common])
        ae = float(geo.attachment_error(old, new, before, after)); limit = u0+u1+0.001
        hand = float(np.linalg.norm(np.array(after["tcp_position_world_m"])-np.array(before["tcp_position_world_m"])))
        obj = float(np.linalg.norm(np.mean(np.array(new)-np.array(old), axis=0)))
        ev = {"phase": phase, "frames": [before["frame_id"], after["frame_id"]], "hand_motion_m": hand, "object_motion_m": obj, "attachment_error_m": ae, "uncertainties_m": [u0, u1], "attachment_threshold_m": limit, "attachment_margin_m": limit-ae, "excitation_margin_m": hand-4*limit, "nonresponse_margin_m": obj-3*(u0+u1)}
        d["effects"].append(ev); d["effects"] = d["effects"][-5:]
        api.checkpoint("deliver_effect", {"effects": d["effects"], "landmarks": pp, "state": after, "parameters": r["parameters"]})
        need(ae <= limit and hand > 4*limit and obj > 3*(u0+u1), "Independent retention effect", "further transport or stage acceptance", ev, "needs_replan")
        semantic(r["parameters"], phase)
        need(r["parameters"]["bowl_stationary"] == "yes", "Bowl stationarity", "reuse of opening geometry", {"interpretation": r["parameters"]["bowl_stationary"], "frame_id": r["frame_id"]}, "needs_replan")
        if "partial-lease" not in phase:
            d["baseline_points"] = pp; d["baseline_state"] = after
        d["latest"] = r
        return r
    def move(target, phase):
        for lease in range(3):
            s = api.state(); budgets = s["budgets"]
            need(d["reviews"] < 3 and budgets["gpt_remaining"] > 13, "Reserved effect observation", phase, {"repair_reviews_used": d["reviews"], "maximum_reviews": 3, "remaining_model_calls": budgets["gpt_remaining"], "reserve_including_supervision": 13})
            allowance = min(60-d["calls"], budgets["jev_remaining"]-48, (budgets["native_steps_remaining"]-144)//3, 30)
            need(allowance >= 1, "Control reserve", phase, {"stage_calls": d["calls"], "remaining": budgets, "reserved_calls": 48, "reserved_steps": 144})
            rec = api.drive(target, d["orientation"], "keep", questions, features={"phase": phase, "source": "current depth, calibrated own geometry and scoped observation admission", "geometry_checkpoint": "deliver_ref", "no_release": True, "table_separation_lower_m": d["geometry"]["separation"]["lower_m"], "package_envelope_radius_m": d["geometry"]["package_radius_upper_m"], "opening_fit_margin_m": d["geometry"]["fit_margin_m"], "pose_tolerance_m": d["geometry"]["pose_tolerance_m"], "stage_calls_used": d["calls"]}, max_calls=int(allowance), translation_limit=0.015, rotation_limit=0.04, steps=3, position_tolerance=d["geometry"]["pose_tolerance_m"], rotation_tolerance=0.01)
            a = api.state(); d["calls"] += rec["lease_calls"]
            progress = float(np.linalg.norm(np.array(a["tcp_position_world_m"])-np.array(s["tcp_position_world_m"])))
            decrease = float(np.linalg.norm(np.array(target)-np.array(s["tcp_position_world_m"]))-np.linalg.norm(np.array(target)-np.array(a["tcp_position_world_m"])))
            api.checkpoint("deliver_progress", {"phase": phase, "target_world_m": target, "before": s, "after": a, "status": rec["status"], "lease_calls": rec["lease_calls"], "stage_calls": d["calls"], "whole_lease_motion_m": progress, "residual_decrease_m": decrease})
            if rec["status"] == "reached":
                return
            need(rec["status"] == "lease_exhausted" and progress > 0.001 and decrease > 0.0005, "Feedback lease progress", phase, {"status": rec["status"], "whole_lease_motion_m": progress, "residual_decrease_m": decrease, "progress_threshold_m": 0.001, "residual_margin_m": decrease-0.0005}, "needs_replan")
            # Continue only this admitted free-space segment, not a new action.
            jaw_change = max([abs(a["gripper_qpos_m"][i]-s["gripper_qpos_m"][i]) for i in range(2)])
            need(a["last_gripper_command"] == s["last_gripper_command"] == "close" and jaw_change < 0.003, "Lease grasp assumptions", phase, {"jaw_change_m": jaw_change, "threshold_m": 0.003, "residual_margin_m": 0.003-jaw_change, "frames": [s["frame_id"], a["frame_id"]]}, "needs_replan")
        fail("Finite lease bound", phase, {"maximum_leases": 3, "state": api.state()})
    try:
        start = api.state(); d["start"] = start
        old = api.recall("retain_gate")["value"]["operands"]["separation"]
        dims = {"thickness_upper_m": old["historical_thickness_upper_m"], "diagonal_upper_m": old["historical_diagonal_upper_m"], "source": "retain_gate measured/model bounds, already validated by frame-240 review against pick_reference; not external thresholds"}
        saved = api.recall("deliver_measure")["value"]["observations"][-1]
        need(saved["frame_id"] == start["frame_id"] == 240, "Unchanged measurement frame", "reuse of face/table data", {"measurement_frame": saved["frame_id"], "state_frame": start["frame_id"], "acknowledged_transfer": False})
        g = geometry(saved, dims); pp = landmarks(saved)
        need(len(pp) >= 3, "Saved landmark membership", "retention test baseline", {"valid": list(pp), "errors": saved["measurement_errors"]})
        d["geometry"] = g; d["baseline_points"] = pp; d["baseline_state"] = start; d["orientation"] = start["tcp_quaternion_xyzw"]
        pos = np.array(start["tcp_position_world_m"])
        low_offset = min(g["separation"]["bottom_lower_world_z_m"]-pos[2], finger_low(start)-pos[2])
        proposed_rim_ceiling = g["separation"]["table_upper_world_z_m"]+0.08
        z = max(float(pos[2])+0.025, proposed_rim_ceiling+0.025-low_offset)
        need(z-pos[2] <= 0.15, "Bounded departure height", "departure", {"rise_m": z-pos[2], "threshold_m": 0.15, "residual_margin_m": 0.15-z+pos[2], "frame_id": start["frame_id"]})
        need("floor" in g["floor"], "Bowl interior reference membership", "route proposal", {"available": list(g["floor"])})
        anchor = np.array(g["floor"]["floor"]["world_m"][:2])
        end_xy = pos[:2]+anchor-np.array(g["package_center_world_m"][:2])
        d["route"] = {"departure": [float(pos[0]), float(pos[1]), float(z)], "above_bowl": [float(end_xy[0]), float(end_xy[1]), float(z)], "center_refinement_radius_m": 0.025, "anchor_world_xy_m": anchor.tolist(), "proposal_only_rim_ceiling_world_z_m": proposed_rim_ceiling, "scope": "Vertical departure then ONE straight elevated lateral segment to any endpoint in this 25 mm XY disk. Review the complete wrist/finger/package swept tube. Floor anchor is NOT a bowl center; the 80 mm table-relative height window and disk are proposed admission scope, not measured bounds. Final endpoint is selected only from fresh opening geometry."}
        d["rim_sampling"] = "Use agentview or the other camera. Request rim0,rim1,rim2 as cloud regions with explicit camera, small box (at most 32 by 32 pixels), stride=4 at widely separated visible top-lip sectors. Each region must contain ONLY the bowl lip/wall and table or empty background, NEVER fingers, bottle, package or unknown foreground. Set rim_regions_valid individually; false if this cannot be identified. Selection uses each sector's highest measured 1 mm layer, requiring consistent heights and planar fit. This is not an object-isolating cloud sensor. Supply 5..8 clearly visible INNER opening boundary pixels on that same lip level, not outer silhouette, floor or descending wall. Do not request depth at those discontinuous pixels: calibrated rays will intersect the independently validated lip plane. Missing/occluded sectors remain missing."
        api.checkpoint("deliver_ref", {"geometry": g, "initial_state": start, "initial_landmarks": pp, "route": d["route"], "labels": labels, "provenance": "Unchanged frame-240 face/table data retained; failed rim/wall/floor boundary depths discarded."})
        r = review("One combined corrected opening measurement and scoped route admission. Revalidate the supplied same-frame package geometry and historical extent interpretation; do NOT remeasure its unchanged face/table/graphic points. Follow rim_sampling for actual cloud region requests and boundary pixels; never repeat the failed mixed-depth rim points. Validate approximate horizontal circular opening identity; if its level or sector membership is ambiguous report unknown. Check the proposed vertical departure and entire elevated lateral endpoint tube separately using package envelope, own finger/wrist geometry and visible obstacles. Request o0..o3 only at relevant obstacle surfaces if needed. Judge bowl_stationary and slip. Assess later placement, finger opening and upward withdrawal individually; later unknown does not block a separately supported departure, while an observed obstruction requires replanning. If lateral is unknown, set upward_observation_gain=supported only if this departure should expose its missing clearance evidence. No release is authorized. Retain the supplied edge identity and pixels only if still valid; list excluded saved surface names.", {"same_frame_package": g, "saved_parameters": saved["parameters"], "route": d["route"], "state": start, "rim_sampling": d["rim_sampling"]}, mf)
        semantic(r["parameters"], "departure")
        need(r["parameters"]["extent_model"] == "supported" and r["parameters"]["face_model"] == "planar_package_face" and r["parameters"]["table_model"] == "same_horizontal_table" and len(r["parameters"]["surface_exclusions"]) == 0, "Revalidated separation inputs", "departure and transport", {"parameters": r["parameters"], "saved_frame": saved["frame_id"]}, "needs_replan")
        need(r["parameters"]["lateral"] != "blocked", "Observed lateral obstruction", "departure toward delivery", {"hazards": r["parameters"]["hazards"]}, "needs_replan")
        need(r["parameters"]["lateral"] == "clear" or r["parameters"]["upward_observation_gain"] == "supported", "Departure observation value", "departure with unresolved lateral admission", {"lateral": r["parameters"]["lateral"], "gain": r["parameters"]["upward_observation_gain"]})
        bowl = opening(r, g)
        end_xy = pos[:2]+np.array(bowl["center_xy_m"])-np.array(g["package_center_world_m"][:2])
        delta = float(np.linalg.norm(np.array(bowl["center_xy_m"])-anchor))
        clearance = z+low_offset-bowl["rim_upper_z_m"]
        need(delta <= 0.025 and clearance >= 0.025 and bowl["rim_upper_z_m"] <= proposed_rim_ceiling, "Measured route within admission scope", "departure and lateral travel", {"center_refinement_m": delta, "scope_radius_m": 0.025, "clearance_lower_m": clearance, "clearance_threshold_m": 0.025, "rim_upper_m": bowl["rim_upper_z_m"], "proposal_ceiling_m": proposed_rim_ceiling, "residual_margins_m": [0.025-delta, clearance-0.025, proposed_rim_ceiling-bowl["rim_upper_z_m"]], "frame_id": r["frame_id"]}, "needs_replan")
        d["route"]["above_bowl"] = [float(end_xy[0]), float(end_xy[1]), float(z)]
        need(r["parameters"]["upward"] == "clear", "Departure admission", "vertical departure", {"condition": r["parameters"]["upward"], "hazards": r["parameters"]["hazards"]})
        need(g["fit_margin_m"] > 0.001, "Package-opening fit", "lateral delivery in current orientation", {"radius_lower_m": bowl["radius_lower_m"], "package_radius_upper_m": g["package_radius_upper_m"], "rim_uncertainty_m": bowl["uncertainty_m"], "center_uncertainty_m": g["package_center_uncertainty_m"], "stopping_allowance_m": g["pose_tolerance_m"], "threshold_m": 0.001, "residual_margin_m": g["fit_margin_m"]-0.001, "frames": [g["frame_id"], r["frame_id"]]}, "needs_replan")
        d["admission"] = {"frame_id": r["frame_id"], "parameters": r["parameters"], "obstacle_measurements": points(r, ["o0", "o1", "o2", "o3"])}
        api.checkpoint("deliver_ref", {"geometry": g, "initial_state": start, "initial_landmarks": pp, "route": d["route"], "labels": labels, "admission": d["admission"], "envelope_semantics": "Dimension-bounded enclosing disk; not reconstructed hidden corners."})
        for phase in ["departure", "above_bowl"]:
            if phase != "departure":
                need(r["parameters"]["lateral"] == "clear", "Lateral corridor admission", phase, {"parameters": r["parameters"], "route": d["route"]})
            move(d["route"][phase], phase)
            r = effect(phase, phase == "above_bowl")
        now = api.state()
        current_package = geometry(r, dims)
        center = np.array(current_package["package_center_world_m"])
        offset = float(np.linalg.norm(center[:2]-np.array(bowl["center_xy_m"])))
        drift_allowance = 0.0
        fit_margin = bowl["radius_lower_m"]-current_package["package_radius_upper_m"]-offset
        bottom = current_package["separation"]["bottom_lower_world_z_m"]
        clearance = min(bottom, finger_low(now))-bowl["rim_upper_z_m"]
        need(fit_margin > 0.001 and clearance > 0.010, "Measured placement-ready alignment", "stage acceptance", {"center_world_m": center.tolist(), "offset_m": offset, "radial_margin_m": fit_margin, "radial_threshold_m": 0.001, "height_clearance_m": clearance, "height_threshold_m": 0.010, "rotation_allowance_m": drift_allowance, "current_center_uncertainty_m": current_package["package_center_uncertainty_m"], "current_envelope_radius_m": current_package["package_radius_upper_m"], "rim_uncertainty_m": bowl["uncertainty_m"], "pose_geometry_frame": current_package["frame_id"], "residual_margins_m": [fit_margin-0.001, clearance-0.010], "frames": [start["frame_id"], now["frame_id"]]})
        rim_now = rim_support(r, 2)
        radii = [float(np.linalg.norm(np.array(v["world_m"][:2])-np.array(bowl["center_xy_m"]))) for v in rim_now.values()]
        radial_range = bowl["support_radial_range_m"]
        errors = [max(radial_range[0]-v, v-radial_range[1], 0.0) for v in radii]
        rim_limit = max([error(v) for v in rim_now.values()])+0.001
        vertical_error = max([max(bowl["rim_lower_z_m"]-v["world_m"][2], v["world_m"][2]-bowl["rim_upper_z_m"], 0.0) for v in rim_now.values()])
        need(max(errors) <= rim_limit and vertical_error <= rim_limit, "Current bowl geometry consistency", "stage acceptance", {"radial_errors_m": errors, "reference_support_radial_range_m": radial_range, "vertical_error_m": vertical_error, "threshold_m": rim_limit, "residual_margin_m": rim_limit-max(max(errors), vertical_error), "frames": [bowl["frame_id"], r["frame_id"]]}, "needs_replan")
        for key in ["placement", "release", "withdrawal"]:
            need(r["parameters"][key] == "clear", "Final " + key + " gate", "placement-ready stage acceptance", {"condition": r["parameters"][key], "hazards": r["parameters"]["hazards"], "frame_id": r["frame_id"]})
        d["final_geometry"] = {"envelope_center_world_m": center.tolist(), "envelope_radius_upper_m": current_package["package_radius_upper_m"], "package_face_plane": current_package["face_plane"], "package_short_edge": current_package["short_edge"], "package_center_in_tool_m": (geo.rotation(now["tcp_quaternion_xyzw"]).T @ (center-np.array(now["tcp_position_world_m"]))).tolist(), "package_pose_source": "Fresh final wide face/table measurements and identified short end, not commanded hand motion", "radial_margin_m": fit_margin, "package_bottom_lower_z_m": bottom, "rim_clearance_m": clearance, "fresh_rim_points": rim_now, "state": now, "placement_parameters": r["parameters"]}
        api.checkpoint("deliver_effect", {"effects": d["effects"], "current_landmarks": d["baseline_points"], "final_geometry": d["final_geometry"]})
        d["status"] = "stage_complete"; reason = "Fresh co-motion, table separation, bowl alignment and separately supported placement clearances."
    except Exception as exc:
        reason = str(exc)
        if d["failure"] is None:
            d["status"] = "blocked"
            d["failure"] = {"gate": "Runtime or measurement limitation", "prevented_action": "further control", "error": reason, "frame_id": api.state()["frame_id"]}
            api.checkpoint("deliver_gate", d["failure"])
    result = {"stage_status": d.get("status", "blocked"), "reason": reason, "evidence": {"gate": d["failure"], "effects": d["effects"], "current_geometry": d.get("final_geometry", {}), "reviews_used": d["reviews"], "control_calls_used": d["calls"]}, "handoff": {"stage": "clear_deliver", "checkpoint_keys": [v["key"] for v in api.recall() if v["key"].startswith("deliver_")], "frames": "World meters; tool quaternion xyzw. Points have individual observation frames. deliver_ref contains original consumed depth, validated historical extent provenance, enclosing-disk semantics, route and obstacle admission. deliver_effect contains actual hand/object differential evidence and latest state.", "assumptions": "Gripper kept closed throughout. No placement, release or withdrawal executed. Envelope center is a bound construction, not an observed hidden center. Bowl geometry requires stationarity; revalidate after contact or scene change, and recheck release geometry after descent before opening. Existing retain_* and pick_* evidence remains historical, not reset.", "actual_state": api.state(), "placement_ready": {"established": d.get("status") == "stage_complete", "geometry_checkpoint": "deliver_effect"}, "separation": d["geometry"].get("separation", {})}, "completion_proposed": False}
    api.checkpoint("deliver_result", result)
    return result

def main(api):
    d = {"reviews": 0, "calls": 0, "effects": [], "geometry": {}, "failure": None}
    labels = ["p0: apex of thin blue outline above capital C in Cream", "p1: center of light oval inside right curl of capital C", "p2: center of light counter of lowercase e in Cream", "p3: center of light counter of lowercase a in Cream"]
    tri = ["clear", "blocked", "unknown"]
    fields = {"identity": ["correct", "wrong", "unknown"], "valid_landmarks": {"type": "array", "items": {"type": "boolean"}, "minItems": 4, "maxItems": 4}, "bowl_stationary": ["yes", "no", "unknown"], "slip": ["none", "observed", "unknown"], "upward": tri, "lateral": tri, "placement": tri, "release": tri, "withdrawal": tri, "upward_observation_gain": ["supported", "unknown"], "hazards": {"type": "string", "maxLength": 1000}}
    pixel = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}
    mf = dict(fields)
    mf.update({"extent_model": ["supported", "changed", "unknown"], "face_model": ["planar_package_face", "other", "unknown"], "table_model": ["same_horizontal_table", "other", "unknown"], "edge_identity": ["complete_short_end", "other", "unknown"], "edge_camera": ["agentview", "robot0_eye_in_hand"], "edge_pixels": {"type": "array", "items": pixel, "minItems": 0, "maxItems": 2}, "rim_identity": ["horizontal_circular_inner_boundary", "other", "unknown"], "rim_camera": ["agentview", "robot0_eye_in_hand"], "rim_pixels": {"type": "array", "items": pixel, "minItems": 0, "maxItems": 8}, "surface_exclusions": {"type": "array", "items": {"type": "string", "maxLength": 32}, "maxItems": 16}})
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
        need(d["reviews"] < 7 and s["budgets"]["gpt_remaining"] > 13, "Review allocation", "observation before further action", {"used": d["reviews"], "maximum": 7, "remaining": s["budgets"]["gpt_remaining"], "reserve": 13})
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
        need(p["rim_identity"] == "horizontal_circular_inner_boundary" and len(p["rim_pixels"]) == 8, "Bowl boundary identity", "opening fit", {"identity": p["rim_identity"], "boundary_count": len(p["rim_pixels"])})
        rim = {}; rim_errors = []
        for i, pix in enumerate(p["rim_pixels"]):
            try:
                rim[str(i)] = api.point(p["rim_camera"], pix, radius=1)
            except Exception as exc:
                rim_errors.append({"index": i, "error": str(exc)[:250]})
        bf, bu = checked_plane(rim, "Inner rim", 4)
        need(bf["coefficients"][2] > math.cos(0.08), "Horizontal opening", "XY circular opening model", {"normal_z": bf["coefficients"][2], "threshold": math.cos(0.08), "residual_margin": bf["coefficients"][2]-math.cos(0.08), "uncertainty_m": bu})
        rr = [rim[str(i)] if str(i) in rim else api.plane_point(p["rim_camera"], pix, bf["coefficients"]) for i, pix in enumerate(p["rim_pixels"])]
        try:
            circle = geo.circle_xy(np.array([v["world_m"] for v in rr]))
        except Exception as exc:
            fail("Inner opening circle rejected", "opening geometry", {"error": str(exc), "rim_measurements": rr, "plane": bf})
        radial_u = bu + circle["max_radial_error_m"]
        lower_radius = circle["radius_m"]-radial_u
        available_margin = lower_radius-radius
        pose_tolerance = min(0.002, max(0.0005, (available_margin-0.001)/2))
        fit_margin = available_margin-pose_tolerance
        bg = {"center_xy_m": circle["center_xy_m"], "radius_lower_m": lower_radius, "rim_upper_z_m": max([v["world_m"][2] for v in rr])+bu, "rim_lower_z_m": min([v["world_m"][2] for v in rr])-bu, "circle": circle, "uncertainty_m": radial_u, "plane": bf, "rim_measurements": rr, "depth_errors": rim_errors}
        need(circle["largest_angular_gap_rad"] < 2.0 and circle["max_radial_error_m"] < 0.003, "Opening model coverage", "opening fit", {"largest_gap_rad": circle["largest_angular_gap_rad"], "gap_threshold_rad": 2.0, "max_radial_error_m": circle["max_radial_error_m"], "error_threshold_m": 0.003, "uncertainty_m": bu, "residual_margin_m": 0.003-circle["max_radial_error_m"], "frame_id": r["frame_id"]})
        return {"fit_margin_m": fit_margin, "pose_tolerance_m": pose_tolerance, "separation": sep, "package_center_world_m": [float(center_xy[0]), float(center_xy[1]), float(center_z)], "package_radius_upper_m": radius, "package_center_uncertainty_m": center_u, "bowl": bg, "face_plane": f, "short_edge": ep, "face_points": ff, "table_points": tt, "floor": points(r, ["floor"]), "dimensions": dims, "frame_id": r["frame_id"]}
    def semantic(p, phase):
        need(p["identity"] == "correct" and p["slip"] != "observed", "Held-object identity and slip", phase, {"identity": p["identity"], "slip": p["slip"]}, "needs_replan")
        for k in ["placement", "release", "withdrawal"]:
            need(p[k] != "blocked", "Established " + k + " obstruction", phase, {"condition": p[k], "hazards": p["hazards"]}, "needs_replan")
    def finger_low(s):
        lo = s["own_geometry"]["finger_low_offset_tool_m"]; hi = s["own_geometry"]["finger_high_offset_tool_m"]
        corners = np.array([[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]])
        return float(s["tcp_position_world_m"][2] + np.min((geo.rotation(s["tcp_quaternion_xyzw"]) @ corners.T)[2]))
    def effect(phase, final=False):
        ef = dict(fields)
        ef.update({"visible_rim_pixels": {"type": "array", "items": pixel, "maxItems": 3}, "rim_check_camera": ["agentview", "robot0_eye_in_hand"]})
        r = review("Check the just acknowledged " + phase + ". Independently reidentify and request depth points p0..p3 using the supplied physical labels, not old pixel projections. Report valid_landmarks individually. Compare the actual resulting scene; closure is not retention. Reassess the EXACT remaining route and separately the later placement, opening and straight upward withdrawal. Unknown later gates must stay unknown. At every reached endpoint request r0,r1,r2 at three widely separated currently visible points of the SAME inner rim, radius 1, also supply their visible_rim_pixels and rim_check_camera (empty only if these are occluded), and judge whether the stationary upright empty bowl and previously measured interior still support placement, release and withdrawal. No release is authorized.", {"labels": labels, "reference_landmarks": d["baseline_points"], "whole_motion_start_state": d["baseline_state"], "geometry": d["geometry"], "route": d["route"], "final": final}, ef)
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
            need(d["reviews"] < 7 and budgets["gpt_remaining"] > 13, "Reserved effect observation", phase, {"reviews_used": d["reviews"], "maximum_reviews": 7, "remaining_model_calls": budgets["gpt_remaining"], "reserve": 13})
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
            r = effect(phase + " partial-lease effect")
            need(r["parameters"]["upward" if phase == "departure" else "lateral"] == "clear", "Remaining corridor", phase, {"parameters": r["parameters"]})
        fail("Finite lease bound", phase, {"maximum_leases": 3, "state": api.state()})
    try:
        start = api.state(); d["start"] = start
        old = api.recall("retain_gate")["value"]["operands"]["separation"]
        dims = {"thickness_upper_m": old["historical_thickness_upper_m"], "diagonal_upper_m": old["historical_diagonal_upper_m"], "source": "retain_gate historical bound, to be validated against pick_reference; not an external constraint"}
        pick = api.recall("pick_reference")["value"]
        for attempt in range(2):
            r = review("Replacement separation measurement, without movement or reopening. Validate the SAME undamaged rigid rectangular cream-cheese package and the semantics and adequacy of the saved full-face diagonal and thickness bounds using pick_reference. Do not inherit the failed narrow-patch angular gate. Request f0..f5 spread widely in BOTH directions across the currently visible planar printed face, excluding fingers, seams and background; t0..t3 widely separated on the same tabletop near the package; p0..p3 at the supplied persistent graphic landmarks; floor at the visible bowl interior bottom. Give two pixels at the complete exposed SHORT top-face end edge, and eight distributed pixels on the actual INNER bowl opening boundary, not the outer rim. Boundary pixels can be ray-intersected with independently measured planes. List any falsely sampled names in surface_exclusions. Report each semantic field separately; later corridor questions may be unknown. On attempt 2 request only missing or genuinely replacement measurements, using another camera or better-spread patch for the failed evidence. Valid supplied same-frame points will be explicitly merged; validate their surface membership and retain their physical identities. Do not repeat an unchanged narrow fit.", {"attempt": attempt+1, "labels": labels, "extent_bounds": dims, "pick_reference": pick, "failed_gate": d["failure"], "same_frame_partial": d.get("replacement_reference", {})}, mf)
            if attempt > 0 and d["replacement_reference"]["frame_id"] == r["frame_id"]:
                merged = dict(d["replacement_reference"]["points"]); merged.update(r["points"]); r["points"] = merged
            d["replacement_reference"] = {"frame_id": r["frame_id"], "points": r["points"]}
            try:
                g = geometry(r, dims)
                pp = landmarks(r)
                need(len(pp) >= 3, "Baseline landmark membership", "differential transport test", {"valid": list(pp), "errors": r["measurement_errors"]})
                break
            except Exception:
                if attempt == 1 or d.get("status") in ["abort", "needs_replan"]:
                    raise
        d["failure"] = None; d["geometry"] = g; d["baseline_points"] = pp; d["baseline_state"] = api.state(); d["orientation"] = start["tcp_quaternion_xyzw"]
        pos = np.array(start["tcp_position_world_m"]); bowl = g["bowl"]
        low_offset = min(g["separation"]["bottom_lower_world_z_m"]-pos[2], finger_low(start)-pos[2])
        z = max(float(pos[2])+0.015, bowl["rim_upper_z_m"]+0.025-low_offset)
        end_xy = pos[:2]+np.array(bowl["center_xy_m"])-np.array(g["package_center_world_m"][:2])
        need(z-pos[2] <= 0.15, "Bounded departure height", "upward departure", {"required_rise_m": z-pos[2], "threshold_m": 0.15, "residual_margin_m": 0.15-z+pos[2], "frame_id": start["frame_id"]})
        d["route"] = {"center_refinement_radius_m": min(0.003, bowl["uncertainty_m"]), "departure": [float(pos[0]), float(pos[1]), float(z)], "midpoint": [float((pos[0]+end_xy[0])/2), float((pos[1]+end_xy[1])/2), float(z)], "above_bowl": [float(end_xy[0]), float(end_xy[1]), float(z)], "future_only": "No placement or release in this method. Later descent to first support inside the opening, opening fingers, then straight upward withdrawal require their separate gates."}
        api.checkpoint("deliver_ref", {"geometry": g, "initial_state": start, "initial_landmarks": pp, "route": d["route"], "labels": labels, "envelope_semantics": "Disk encloses a dimension-bounded rectangle extending inward from the observed short end; its center is not a measured hidden package center."})
        r = review("Admit only the specified bounded route. Use current images, measured table separation, package envelope, bowl rim, own finger geometry and visible wrist. Check the exact upward departure and two elevated straight lateral segments separately, including every lateral waypoint refinement within route.center_refinement_radius_m; this bounded tube is the full requested route admission. Request o0..o3 only where relevant, at visible obstacle extremal surfaces with physical labels in hazards. Do not certify hidden clearance or mistake old upward-only reviews for lateral admission. Separately judge later descent into the bowl to first support, finger opening and straight upward withdrawal. Unknown later gates do not reject a separately clear departure or high lateral observation move; an established later obstruction requires replanning now. If the numerical opening margin is unresolved, distinguish uncertainty from an observed obstruction and set upward_observation_gain supported only when the specified departure exposes a better inner-rim view for a new metric fit. No release is authorized.", {"geometry": g, "route": d["route"], "state": start}, fields)
        semantic(r["parameters"], "departure")
        need(r["parameters"]["upward"] == "clear", "Upward corridor admission", "departure", {"parameters": r["parameters"], "route": d["route"]})
        need(g["fit_margin_m"] > 0.001 or r["parameters"]["upward_observation_gain"] == "supported", "Observation-producing departure", "departure while later fit is unresolved", {"opening_margin_m": g["fit_margin_m"], "needed_margin_m": 0.001, "observation_gain": r["parameters"]["upward_observation_gain"]})
        d["obstacle_measurements"] = points(r, ["o0", "o1", "o2", "o3"])
        d["admission"] = {"frame_id": r["frame_id"], "parameters": r["parameters"], "obstacle_measurements": d["obstacle_measurements"]}
        api.checkpoint("deliver_ref", {"geometry": g, "initial_state": start, "initial_landmarks": pp, "route": d["route"], "labels": labels, "admission": d["admission"], "envelope_semantics": "Dimension-bounded enclosing disk, not hidden reconstructed corners."})
        for phase in ["departure", "midpoint", "above_bowl"]:
            if phase != "departure":
                need(r["parameters"]["lateral"] == "clear", "Lateral corridor admission", phase, {"parameters": r["parameters"], "route": d["route"]})
            move(d["route"][phase], phase)
            r = effect(phase, phase == "above_bowl")
            if phase == "departure":
                if g["fit_margin_m"] <= 0.001:
                    fresh = points(r, ["r0", "r1", "r2"])
                    for i, pix in enumerate(r["parameters"]["visible_rim_pixels"]):
                        try:
                            fresh["r"+str(i)] = api.point(r["parameters"]["rim_check_camera"], pix, radius=1)
                        except Exception:
                            api.note("Alternative current rim depth unavailable.")
                    pf, pu = checked_plane(fresh, "Changed-view rim", 3)
                    cc = geo.circle_xy(xyz(fresh))
                    nu = pu+bowl["circle"]["max_radial_error_m"]
                    center_change = float(np.linalg.norm(np.array(cc["center_xy_m"])-np.array(bowl["center_xy_m"])))
                    threshold = nu+bowl["uncertainty_m"]
                    need(cc["largest_angular_gap_rad"] < 2.5 and pf["coefficients"][2] > math.cos(0.08) and min(pf["in_plane_spread_m"]) > 4*pu and center_change <= d["route"]["center_refinement_radius_m"] and center_change < threshold and abs(cc["radius_m"]-bowl["circle"]["radius_m"]) < threshold, "Changed-view circular model consistency", "replacement opening estimate", {"gap_rad": cc["largest_angular_gap_rad"], "gap_threshold_rad": 2.5, "spread_m": pf["in_plane_spread_m"], "point_uncertainty_m": pu, "center_change_m": center_change, "admitted_refinement_radius_m": d["route"]["center_refinement_radius_m"], "normal_z": pf["coefficients"][2], "normal_threshold": math.cos(0.08), "radius_change_m": abs(cc["radius_m"]-bowl["circle"]["radius_m"]), "threshold_m": threshold, "residual_margin_m": threshold-max(center_change, abs(cc["radius_m"]-bowl["circle"]["radius_m"])), "frames": [g["frame_id"], r["frame_id"]]})
                    bowl.update({"center_xy_m": cc["center_xy_m"], "radius_lower_m": cc["radius_m"]-nu, "uncertainty_m": nu, "replacement_circle": cc, "replacement_points": fresh, "replacement_frame_id": r["frame_id"]})
                    free = bowl["radius_lower_m"]-g["package_radius_upper_m"]
                    g["pose_tolerance_m"] = min(0.002, max(0.0005, (free-0.001)/2))
                    g["fit_margin_m"] = free-g["pose_tolerance_m"]
                    end_xy = pos[:2]+np.array(bowl["center_xy_m"])-np.array(g["package_center_world_m"][:2])
                    d["route"]["midpoint"][:2] = [float((pos[0]+end_xy[0])/2), float((pos[1]+end_xy[1])/2)]
                    d["route"]["above_bowl"][:2] = [float(end_xy[0]), float(end_xy[1])]
                need(g["fit_margin_m"] > 0.001, "Package-opening fit", "lateral delivery in this orientation", {"opening_radius_lower_m": bowl["radius_lower_m"], "package_envelope_radius_m": g["package_radius_upper_m"], "center_uncertainty_in_envelope_m": g["package_center_uncertainty_m"], "pose_stopping_allowance_m": g["pose_tolerance_m"], "threshold_m": 0.001, "residual_margin_m": g["fit_margin_m"]-0.001, "frames": [g["frame_id"], r["frame_id"]]})
                api.checkpoint("deliver_ref", {"geometry": g, "initial_state": start, "initial_landmarks": pp, "route": d["route"], "labels": labels, "admission": d["admission"], "envelope_semantics": "Dimension-bounded enclosing disk, not hidden reconstructed corners."})
        now = api.state(); rot0 = geo.rotation(start["tcp_quaternion_xyzw"]); rot1 = geo.rotation(now["tcp_quaternion_xyzw"])
        transform = np.eye(4); transform[:3, :3] = rot1 @ rot0.T
        transform[:3, 3] = np.array(now["tcp_position_world_m"])-transform[:3, :3] @ np.array(start["tcp_position_world_m"])
        center = geo.transform([g["package_center_world_m"]], transform)[0]
        offset = float(np.linalg.norm(center[:2]-np.array(bowl["center_xy_m"])))
        drift_allowance = float(np.linalg.norm(rot1-rot0, 2))*(dims["diagonal_upper_m"]+dims["thickness_upper_m"])
        fit_margin = bowl["radius_lower_m"]-g["package_radius_upper_m"]-offset-drift_allowance
        bottom = g["separation"]["bottom_lower_world_z_m"]+now["tcp_position_world_m"][2]-pos[2]-drift_allowance
        clearance = min(bottom, finger_low(now))-bowl["rim_upper_z_m"]
        need(fit_margin > 0.001 and clearance > 0.010, "Measured placement-ready alignment", "stage acceptance", {"center_world_m": center.tolist(), "offset_m": offset, "radial_margin_m": fit_margin, "radial_threshold_m": 0.001, "height_clearance_m": clearance, "height_threshold_m": 0.010, "rotation_allowance_m": drift_allowance, "residual_margins_m": [fit_margin-0.001, clearance-0.010], "frames": [start["frame_id"], now["frame_id"]]})
        rim_now = points(r, ["r0", "r1", "r2"])
        for i, pix in enumerate(r["parameters"]["visible_rim_pixels"]):
            if "r"+str(i) not in rim_now:
                try:
                    rim_now["r"+str(i)] = api.point(r["parameters"]["rim_check_camera"], pix, radius=1)
                except Exception:
                    api.note("Current inner-rim radius-1 replacement unavailable; no historical ray substitute.")
        need(len(rim_now) == 3, "Current rim validation membership", "stage acceptance", {"valid": list(rim_now), "errors": r["measurement_errors"]})
        errors = [abs(float(np.linalg.norm(np.array(v["world_m"][:2])-np.array(bowl["center_xy_m"])))-bowl["circle"]["radius_m"]) for v in rim_now.values()]
        rim_limit = bowl["uncertainty_m"]+max([error(v) for v in rim_now.values()])+0.001
        vertical_error = max([max(bowl["rim_lower_z_m"]-v["world_m"][2], v["world_m"][2]-bowl["rim_upper_z_m"], 0.0) for v in rim_now.values()])
        need(max(errors) <= rim_limit and vertical_error <= rim_limit, "Current bowl geometry consistency", "stage acceptance", {"radial_errors_m": errors, "vertical_error_m": vertical_error, "threshold_m": rim_limit, "residual_margin_m": rim_limit-max(max(errors), vertical_error), "frames": [g["frame_id"], r["frame_id"]]})
        for key in ["placement", "release", "withdrawal"]:
            need(r["parameters"][key] == "clear", "Final " + key + " gate", "placement-ready stage acceptance", {"condition": r["parameters"][key], "hazards": r["parameters"]["hazards"], "frame_id": r["frame_id"]})
        d["final_geometry"] = {"envelope_center_world_m": center.tolist(), "envelope_radius_upper_m": g["package_radius_upper_m"], "radial_margin_m": fit_margin, "package_bottom_lower_z_m": bottom, "rim_clearance_m": clearance, "fresh_rim_points": rim_now, "state": now, "placement_parameters": r["parameters"]}
        api.checkpoint("deliver_effect", {"effects": d["effects"], "current_landmarks": d["baseline_points"], "final_geometry": d["final_geometry"]})
        d["status"] = "stage_complete"; reason = "Fresh co-motion, table separation, bowl alignment and separately supported placement clearances."
    except Exception as exc:
        reason = str(exc)
        if d["failure"] is None:
            d["status"] = "blocked"
            d["failure"] = {"gate": "Runtime or measurement limitation", "prevented_action": "further control", "error": reason, "frame_id": api.state()["frame_id"]}
            api.checkpoint("deliver_gate", d["failure"])
    result = {"stage_status": d.get("status", "blocked"), "reason": reason, "evidence": {"gate": d["failure"], "effects": d["effects"], "current_geometry": d.get("final_geometry", {}), "reviews_used": d["reviews"], "control_calls_used": d["calls"]}, "handoff": {"stage": "clear_deliver", "checkpoint_keys": [v["key"] for v in api.recall() if v["key"].startswith("deliver_")], "frames": "World meters; tool quaternion xyzw. Points have individual observation frames. deliver_ref contains original consumed depth, validated historical extent provenance, enclosing-disk semantics, route and obstacle admission. deliver_effect contains actual hand/object differential evidence and latest state.", "assumptions": "Gripper kept closed throughout. No placement, release or withdrawal executed. Envelope center is a bound construction, not an observed hidden center. Bowl geometry requires stationarity; revalidate after contact or scene change, and recheck release geometry after descent before opening. Existing retain_* and pick_* evidence remains historical, not reset.", "actual_state": api.state(), "placement_ready": d.get("final_geometry", {}), "separation": d["geometry"].get("separation", {})}, "completion_proposed": False}
    api.checkpoint("deliver_result", result)
    return result

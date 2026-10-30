def main(api):
    key = "grasp_stage_v2"
    g, d, log, used = {}, {}, [], 0
    entry_steps = api.state()["native_steps"]
    def clean(v):
        if isinstance(v, np.ndarray): return v.tolist()
        if isinstance(v, dict): return {k: clean(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)): return [clean(x) for x in v]
        if isinstance(v, np.floating): return float(v)
        if isinstance(v, np.integer): return int(v)
        return v
    def save():
        api.checkpoint(key, clean({"geometry": g, "progress": d, "recent_evidence": log[-3:]}))
    def finish(status, reason):
        if status in ["blocked", "needs_replan", "abort"] and "stop_gate" not in d:
            d["stop_gate"] = {"status": status, "reason": reason, "phase": d.get("phase", "access_measurement")}
        save()
        return clean({"stage_status": status, "reason": reason, "evidence": log[-12:],
            "handoff": {"checkpoint_key": key, "prior_measurement_key": "grasp_stage_v1",
                "phase": d.get("phase", "access_measurement"), "stop_gate": d.get("stop_gate"), "possibly_holding": d.get("closure_attempted", False) or bool(d.get("pending_action")),
                "tracker_handle": g.get("handle"), "dimensions_m": g.get("dimensions_m"),
                "package_in_tool_m": d.get("package_in_tool_m"), "last_acknowledged_state": d.get("last_state"),
                "frames": "World metres; tool-to-world xyzw quaternion. Tracker maps its original world reference to current world.",
                "provenance": "v1 retains valid frame-0 top/table measurements and the failed sampling polygon. v2 stores the fresh access polygon and depth fit, original visible top boundary, inferred table-supported box bottom, own-finger envelope, tracker identity/creation, action receipts and retention measurements.",
                "assumptions": "Rectangular cream-cheese package initially on stationary table. Original bottom is inferred from that support model, not a hidden-surface observation. Access polygon certifies only the reviewed local corridor, not future travel.",
                "revalidation": "Refresh the same package tracker, visible identity, table reference and relevant clearance after motion. Check pending_action and native_steps before resuming. Do not reopen a possibly held object."},
            "completion_proposed": False})
    def review(question, fields, names, context):
        for attempt in range(2):
            r = api.review(question, context=clean(context), fields=fields)
            log.append({"review_frame": r["frame_id"], "parameters": r["parameters"], "points": r["points"], "measurement_errors": r["measurement_errors"]})
            save()
            bad = [x["name"] for x in r["measurement_errors"]]
            valid = all(n in r["points"] and n not in bad and r["points"][n]["frame_id"] == r["frame_id"] for n in names)
            if valid or r["status"] == "stop": return r, valid
            question += " The last depth attempt failed. Use DIFFERENT clean interior pixels or the other existing camera for the same physical surfaces, not the same invalid patches. Missing names: " + str([n for n in names if n not in r["points"] or n in bad])
        return r, valid
    def margins(poly, points):
        p, v = np.array(poly)[:, :2], np.array(points)[:, :2]
        area = sum(p[i, 0]*p[(i+1)%len(p), 1]-p[(i+1)%len(p), 0]*p[i, 1] for i in range(len(p)))
        sign, result = (1.0 if area > 0 else -1.0), []
        for i in range(len(p)):
            a, b, c = p[i], p[(i+1)%len(p)], p[(i+2)%len(p)]
            e, f = b-a, c-b
            if np.linalg.norm(e) < 0.004 or sign*(e[0]*f[1]-e[1]*f[0]) <= 0: return None
            result.extend([float(sign*(e[0]*w[1]-e[1]*w[0])/np.linalg.norm(e)) for w in v-a])
        return min(result)
    def expanded_hull(points):
        p = sorted(set(tuple(float(x) for x in v[:2]) for v in points))
        def cross(a, b, c): return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        lower, upper = [], []
        for seq, chain in [(p, lower), (list(reversed(p)), upper)]:
            for v in seq:
                for removal in range(len(chain)):
                    if len(chain) < 2 or cross(chain[-2], chain[-1], v) > 0: break
                    chain.pop()
                chain.append(v)
        h = np.array(lower[:-1]+upper[:-1])
        edges = np.roll(h, -1, axis=0)-h
        normals = np.stack((edges[:, 1], -edges[:, 0]), axis=1)/np.linalg.norm(edges, axis=1)[:, None]
        limits = np.sum(normals*h, axis=1)+0.010
        return np.array([np.linalg.solve(np.array([normals[i-1], normals[i]]), np.array([limits[i-1], limits[i]])) for i in range(len(h))])
    def tracking():
        t = api.track_update(g["handle"])
        summary = {k: t.get(k) for k in ["status", "frame_id", "reference_frame_id", "reason", "matches", "inliers", "rms_m", "inlier_spread_m", "uncertainty_floor_m", "candidates"]}
        d["last_tracking"] = summary
        if t["status"] != "tracked": return t, None, None
        sp = t["inlier_spread_m"]
        spread = sorted(sp, reverse=True)[1] if isinstance(sp, (list, tuple)) and len(sp) >= 2 else 0.0
        u = max(0.001, float(t["rms_m"]), float(t["uncertainty_floor_m"]))
        if t["reference_frame_id"] != g["tracker_creation"]["frame_id"] or t["inliers"] < 12 or t["inliers"]/max(1, t["matches"]) < 0.60 or spread < 0.006 or t["rms_m"] > 0.002 or u > 0.003: return t, None, None
        return t, geo.transform(g["package_prism_world_m"], t["transform_initial_world_to_current_world"]), u
    def tracking_gap(reason):
        fields = {"identity": ["same_package", "different", "unknown"], "visibility": ["surface_visible", "occluded", "unknown"], "detail": {"type": "string", "maxLength": 500}}
        r, valid = review("Registration is unavailable or inadequate. Obtain a DIFFERENT public measurement, not an extrapolated tracker pose: request package_probe at a currently visible, clean-depth interior point of the SAME cream-cheese surface, in whichever existing camera has visibility. State identity and actual visibility. One point is only a recovery location, not an orientation or retention certificate. Do not ask whether the grasp succeeded when the package is still on the table.",
            fields, ["package_probe"], {"tracker": d.get("last_tracking"), "original_boundary_world_m": g["boundary_world_m"], "phase": d.get("phase")})
        g["recovery_probe"] = {"frame_id": r["frame_id"], "parameters": r["parameters"], "point": r["points"].get("package_probe"), "valid": valid}
        if r["status"] == "stop": return finish("abort", "Observation review requested stopping during tracking diagnosis.")
        if r["parameters"]["identity"] == "different": return finish("needs_replan", "Alternative observation contradicts the package identity.")
        return finish("blocked", reason+" A bounded alternative surface measurement is saved; it does not replace the missing rigid registration.")
    questions = {}
    for axis in ["x", "y", "z", "rx", "ry", "rz"]:
        questions[axis] = {"type": "choice", "instructions": "For the " + axis + " world component, read state.processed_features.axes." + axis + ".goal_relation. Decrease means negative, increase means positive, within_tolerance means hold. Rotations are world rotation-vector components. Do not infer obstacles or change the objective.",
            "criteria": {"negative": "Decrease this world component.", "hold": "This component is within tolerance; zero motion.", "positive": "Increase this world component."}}
    questions["gripper"] = {"type": "choice", "instructions": "Read state.processed_features.objective.gripper exactly. Open is only for the confirmed empty pre-grasp hand; close is one acquisition attempt; keep preserves the delivered command. No choice certifies retention.",
        "criteria": {"open": "The objective requests open.", "close": "The objective requests close.", "keep": "The objective requests keep."}}
    try:
        manifest = api.recall()
        if any(m["key"] == key for m in manifest):
            saved = api.recall(key)["value"]
            g, d, log = saved["geometry"], saved["progress"], saved.get("recent_evidence", [])
            if d.get("stop_gate"):
                return finish("blocked", "Prior v2 stop requires an explicit revised recovery, not replay: "+d["stop_gate"]["reason"])
        s = api.state()
        if d.get("phase"):
            if d.get("pending_action") or s["native_steps"] != d["last_state"]["native_steps"]:
                return finish("blocked", "Unreconciled physical execution; inspect pending_action and host receipts before any motion.")
            if d.get("closure_attempted", False) and d["phase"] in ["approach", "descent", "close"]:
                return finish("blocked", "Closure may already have occurred. Do not reopen or repeat contact.")
            if not d.get("closure_attempted", False) and s["last_gripper_command"] != "open":
                return finish("blocked", "Unexpected gripper state before acquisition.")
            if d["phase"] == "verified": d["phase"] = "verify"
        else:
            if s["native_steps"] != 0 or s["frame_id"] != 0 or s["last_gripper_command"] != "open":
                return finish("blocked", "The measurement-only repair requires the acknowledged untouched frame-0 state.")
            old = api.recall("grasp_stage_v1")["value"]
            base = old["geometry"]
            if base["measurement_frame"] != s["frame_id"]:
                return finish("blocked", "Historical top boundary is not from the unchanged current frame.")
            pf, tf = base["top_fit"], base["table_fit"]
            if pf["rms_m"] > 0.0015 or min(pf["in_plane_spread_m"]) < 0.006 or pf["coefficients"][2] < 0.99:
                return finish("blocked", "Saved top-plane fit is inadequate.")
            box = np.array([api.plane_point(base["camera"], uv, pf["coefficients"])["world_m"] for uv in base["outline_pixels"]])
            edges = np.roll(box[:, :2], -1, axis=0)-box[:, :2]
            lengths = np.linalg.norm(edges, axis=1)
            if min(lengths) < 0.018 or max(lengths) > 0.15 or abs(lengths[0]-lengths[2]) > 0.004 or abs(lengths[1]-lengths[3]) > 0.004 or abs(float(np.dot(edges[0], edges[1])))/(lengths[0]*lengths[1]) > 0.12:
                return finish("blocked", "Projected top boundary does not support a rectangular side pinch.")
            axis = edges[int(np.argmax(lengths))]
            if np.dot(axis, geo.rotation(s["tcp_quaternion_xyzw"])[:2, 0]) < 0: axis = -axis
            q = api.compose([1.0, 0.0, 0.0, 0.0], [0.0, 0.0, math.atan2(float(axis[1]), float(axis[0]))])
            own, rot, center = s["own_geometry"], geo.rotation(q), np.mean(box, axis=0)
            lo, hi = own["finger_low_offset_tool_m"], own["finger_high_offset_tool_m"]
            corners = np.array([[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]])
            rel = (corners-np.array(own["pad_center_in_tool_m"])) @ rot.T
            footprint = np.concatenate((center[None, :]+rel, box), axis=0)
            hull = expanded_hull(footprint)
            if len(hull) < 3 or len(hull) > 16: return finish("blocked", "Unexpected sampling-polygon complexity.")
            n, pd = np.array(tf["coefficients"][:3]), tf["coefficients"][3]
            samples = np.column_stack((hull, -(hull @ n[:2]+pd)/n[2]))
            projected = {}
            for camera in ["agentview", "robot0_eye_in_hand"]:
                cal = api.camera(camera)
                cp = geo.transform(samples, np.linalg.inv(np.array(cal["camera_to_world_opencv"])))
                if min(cp[:, 2]) <= 0: return finish("blocked", "Proposed measurement lies behind the camera.")
                uvh = cp @ np.array(cal["K"]).T
                projected[camera] = (uvh[:, :2]/uvh[:, 2, None]).tolist()
            g = {"measurement_frame": 0, "top_fit": pf, "initial_table_fit": tf, "original_outline_pixels": base["outline_pixels"],
                 "camera": base["camera"], "patch_pixels": base["patch_pixels"], "boundary_world_m": box.tolist(),
                 "own_finger_corners_tool_m": corners.tolist(), "quaternion": q, "proposed_access_samples_world_m": samples.tolist(),
                 "sampling_projections": projected, "old_polygon_failure_m": -0.00878391,
                 "required_planned_footprint_margin_m": 0.007, "planned_floor_margin_m": 0.005,
                 "required_actual_footprint_margin_m": 0.003, "required_actual_floor_margin_m": 0.0025}
            names = ["a"+str(i) for i in range(len(samples))]
            fields = {"identity": ["same_rectangular_package_on_table", "different_or_moved", "unknown"],
                      "access": ["visible_clear_except_package", "observed_obstacle", "insufficient_view"], "detail": {"type": "string", "maxLength": 500}}
            accepted, gap = False, "The old polygon truncated the planned open-finger footprint; that is not evidence of collision."
            for attempt in range(2):
                r, valid = review("Repair ONLY local grasp-access evidence. No actions have occurred; preserve the same cream-cheese identity and frame-0 physical top corners. Request named top_check well inside its top. Request tabletop depth points " + str(names) + " in cyclic order around the package AND open-finger footprint. Context gives proposed world sample positions and current-camera pixel projections, NOT measured clearance. Use those locations if truly visible tabletop, otherwise choose nearby clean depth pixels or the other camera. A thin convex enclosing polygon is preferable to a large rectangle crossing the bowl. The entire selected polygon except the package must be visibly unobstructed, including no overhanging bowl rim or hidden corridor; do not bridge occluded space. Access requires room for the vertical open-hand sweep, not merely isolated clear pixels. The fixed 7 mm footprint margin will be checked numerically. Distinguish observed obstacle from inadequate sampled coverage. On this attempt address the supplied gap with different measurements, not an unchanged question.",
                    fields, names+["top_check"], {"geometry": g, "attempt": attempt, "gap": gap, "candidate_footprint_world_m": footprint.tolist()})
                if r["status"] == "stop": return finish("abort", "Observation review requested stopping.")
                if r["parameters"]["identity"] == "different_or_moved": return finish("needs_replan", "Fresh identity or support contradicts the unchanged package model.")
                if not valid:
                    gap = {"missing_or_invalid": [name for name in names+["top_check"] if name not in r["points"] or any(e["name"] == name for e in r["measurement_errors"])]}
                    continue
                if r["parameters"]["access"] == "observed_obstacle":
                    return finish("blocked", "Fresh review identifies an actual obstacle in this candidate corridor: "+r["parameters"]["detail"])
                if r["parameters"]["identity"] != "same_rectangular_package_on_table" or r["parameters"]["access"] != "visible_clear_except_package":
                    gap = {"problem": "Use the other existing camera to resolve identity or visible coverage", "detail": r["parameters"]["detail"]}
                    continue
                table = np.array([r["points"][name]["world_m"] for name in names])
                try:
                    fresh = clean(geo.plane(table))
                except Exception as exc:
                    gap = {"problem": "Rejected support-plane fit; select a different nondegenerate visible perimeter", "error": str(exc)}
                    log.append(gap); save()
                    continue
                nn, dd = np.array(fresh["coefficients"][:3]), fresh["coefficients"][3]
                top_check = np.array(r["points"]["top_check"]["world_m"])
                top_error = abs(float(np.dot(top_check, np.array(pf["coefficients"][:3]))+pf["coefficients"][3]))
                margin = margins(table, footprint)
                g.update({"access_frame": r["frame_id"], "table_fit": fresh, "table_polygon_world_m": table.tolist(), "access_depth_points": {name: r["points"][name] for name in names}, "top_check": r["points"]["top_check"], "footprint_margin_m": margin})
                log.append({"access_attempt": attempt, "footprint_margin_m": margin, "top_plane_check_error_m": top_error})
                save()
                if top_error > 0.003 or float(np.max(np.abs(table @ n+pd))) > 0.003:
                    return finish("needs_replan", "Fresh depths contradict the saved top/support geometry.")
                if fresh["rms_m"] > 0.0015 or min(fresh["in_plane_spread_m"]) < 0.025 or nn[2] < 0.995 or float(np.max(np.abs(table @ nn+dd))) > 0.002:
                    gap = {"problem": "Inadequate support-plane fit", "fit": fresh}
                    continue
                if margin is None or margin < 0.007:
                    gap = {"problem": "Insufficient measured enclosing coverage, not an inferred obstacle", "margin_m": margin, "required_m": 0.007, "selected_polygon_world_m": table.tolist()}
                    continue
                accepted = True
                break
            if not accepted: return finish("blocked", "Two different measurement attempts did not establish the unchanged 7 mm footprint margin; exact fit/coverage gap is saved.")
            n, pd = np.array(g["table_fit"]["coefficients"][:3]), g["table_fit"]["coefficients"][3]
            bottom = box.copy(); bottom[:, 2] = -(bottom[:, :2] @ n[:2]+pd)/n[2]
            heights = box[:, 2]-bottom[:, 2]
            if min(heights) < 0.009 or max(heights) > 0.06: return finish("blocked", "Package height cannot support this side pinch.")
            grasp = center.copy()
            floor_z = max((0.005-pd-n[0]*(center[0]+v[0])-n[1]*(center[1]+v[1])-n[2]*v[2])/n[2] for v in rel)
            grasp[2] = max(float(center[2]-min(0.004, min(heights)*0.25)), float(floor_z))
            halfpad = own["pad_extent_in_tool_m"][2]/2
            overlap = min(float(min(box[:, 2])), float(grasp[2]+halfpad))-max(float(max(bottom[:, 2])), float(grasp[2]-halfpad))
            g["pad_package_overlap_m"] = overlap
            if overlap < 0.004: return finish("blocked", "The fixed 4 mm pad/package overlap margin failed.")
            hover = grasp.copy(); hover[2] = float(geo.pad_position(s)[2])
            if hover[2] < max(box[:, 2])+0.12: return finish("blocked", "Insufficient entry height for the elevated approach.")
            tr = api.track_init(g["camera"], g["patch_pixels"])
            g.update({"handle": tr["handle"], "tracker_creation": {k: tr.get(k) for k in ["handle", "frame_id", "camera", "method_number", "source_sha256"]},
                "tracker_identity": "Inset textured top face of this cream-cheese package; original frame 0.",
                "package_prism_world_m": np.concatenate((box, bottom), axis=0).tolist(),
                "dimensions_m": [float(max(lengths)), float(min(lengths)), float(max(heights))],
                "grasp_pad_world_m": grasp.tolist(), "hover_pad_world_m": hover.tolist()})
            d = {"phase": "approach", "target": hover.tolist(), "closure_attempted": False, "last_state": s, "pending_action": None}
            save()
        phase_fields = {"identity": ["same_package", "different", "unknown"],
                        "corridor": ["visible_clear", "observed_obstacle", "unknown"],
                        "support": ["on_table", "straddled_open", "straddled_closed", "held_clear", "not_held", "unknown"], "detail": {"type": "string", "maxLength": 500}}
        for phase_index in range(6):
            phase = d["phase"]
            t, pts, u = tracking()
            r, valid = review("Grasp phase: "+phase+". Confirm the same physical package. Request table_check on an unobstructed part of the saved tabletop polygon, using a different view/interior pixel if needed. For approach, inspect the elevated straight open-hand sweep to hover including yaw. For descent, inspect the vertical open-hand corridor and package stationarity. For close, require both package sides visibly straddled by open fingers, not a grasp yet. For lift1, closure has been delivered: straddled_closed may still be table-supported and is sufficient for ONE observation-producing 25 mm upward test if that corridor is clear. Do NOT require retention or lifted clearance before this test. For lift2 and verify, require actual held_clear evidence, not just closure or command delivery; lift2 also needs its next 25 mm upward corridor clear. Unknown/occluded clearance is not clear. No bowl transport or release is requested.",
                phase_fields, ["table_check"], {"geometry": g, "progress": d, "tracked_package_world_m": None if pts is None else pts.tolist(), "tracker": d["last_tracking"]})
            if r["status"] == "stop": return finish("abort", "Fresh observation requested stopping.")
            if not valid: return finish("blocked", "Fresh table measurement failed; valid partial observation is checkpointed.")
            p = r["parameters"]
            if p["identity"] == "different": return finish("needs_replan", "Fresh evidence invalidates tracked package identity.")
            if p["identity"] != "same_package" or (phase != "verify" and p["corridor"] != "visible_clear"):
                return finish("blocked", "Identity or next local corridor is unresolved: "+p["detail"])
            n, pd = np.array(g["table_fit"]["coefficients"][:3]), g["table_fit"]["coefficients"][3]
            if abs(float(np.dot(n, r["points"]["table_check"]["world_m"])+pd)) > 0.003:
                return finish("needs_replan", "Current table depth contradicts the support reference.")
            if pts is None and phase != "lift1":
                log.append({"tracking_gap": d["last_tracking"]})
                return tracking_gap("No adequate current registration of the original package patch.")
            if phase in ["approach", "descent", "close"]:
                if float(np.max(np.linalg.norm(pts-np.array(g["package_prism_world_m"]), axis=1))) > 0.004:
                    return finish("needs_replan", "Package moved before acquisition; saved pinch geometry is stale.")
                allowed = ["straddled_open"] if phase == "close" else ["on_table", "straddled_open"]
            else:
                allowed = ["straddled_closed", "held_clear"] if phase == "lift1" else ["held_clear"]
            if p["support"] not in allowed:
                return finish("needs_replan" if p["support"] == "not_held" else "blocked", "Observed package/finger relationship does not support this local action: "+p["support"])
            state = api.state()
            if phase == "close":
                d["target"] = geo.pad_position(state).tolist()
                d["hold_quaternion"] = state["tcp_quaternion_xyzw"]
            if phase in ["lift2", "verify"]:
                clearance = float(min(pts @ n+pd))-u-0.002
                log.append({"phase": phase, "package_lower_clearance_m": clearance, "frame_id": t["frame_id"], "tracker_quality": d["last_tracking"]})
                if clearance < 0.008: return finish("blocked", "No conservative 8 mm package/table separation after the test lift.")
                if phase == "lift2":
                    if "retention_baseline" not in d:
                        refs, current = np.array(t["reference_inlier_world_m"]), t["current_inlier_world_m"]
                        ids = [0]
                        for j in range(min(16, len(refs))-1):
                            distances = np.min(np.linalg.norm(refs[:, None, :]-refs[np.array(ids)][None, :, :], axis=2), axis=1)
                            ids.append(int(np.argmax(distances)))
                        d["retention_baseline"] = {"state": state, "frame_id": t["frame_id"], "uncertainty_m": u,
                            "reference_points": refs[np.array(ids)].tolist(), "current_points": [current[i] for i in ids],
                            "visual_observation": {"frame_id": r["frame_id"], "parameters": p}, "package_lower_clearance_m": clearance}
                else:
                    b = d["retention_baseline"]
                    refs, now = np.array(t["reference_inlier_world_m"]), np.array(t["current_inlier_world_m"])
                    first, second = [], []
                    for i, ref in enumerate(b["reference_points"]):
                        dist = np.linalg.norm(refs-np.array(ref), axis=1); j = int(np.argmin(dist))
                        if dist[j] < 0.00001:
                            first.append(b["current_points"][i]); second.append(now[j].tolist())
                    if len(first) < 6 or min(geo.plane(first)["in_plane_spread_m"]) < 0.003:
                        return finish("blocked", "Too few shared, spread-out measured feature correspondences for retention.")
                    error = float(geo.attachment_error(first, second, b["state"], state))
                    rise = float(state["tcp_position_world_m"][2]-b["state"]["tcp_position_world_m"][2])
                    log.append({"attachment_error_m": error, "hand_rise_m": rise, "shared_features": len(first), "first_lift_frame": b["frame_id"], "second_lift_frame": t["frame_id"]})
                    if t["frame_id"] == b["frame_id"] or rise < 0.015 or error > 0.004+u+b["uncertainty_m"]:
                        return finish("blocked", "Measured hand/package motion does not establish retention across two lifted observations.")
                    d["package_in_tool_m"] = ((pts-np.array(state["tcp_position_world_m"])) @ geo.rotation(state["tcp_quaternion_xyzw"])).tolist()
                    d["verification"] = {"frame_id": r["frame_id"], "visual_parameters": p, "package_lower_clearance_m": clearance,
                        "attachment_error_m": error, "hand_rise_m": rise, "common_features": len(first)}
                    d["verified_frame"], d["phase"] = t["frame_id"], "verified"
                    return finish("stage_complete", "Two fresh lifted observations show the package held clear; shared measured features follow the measured hand motion.")
            save()
            reached = False
            for call in range(24-used):
                before = api.state()
                if used >= 24 or before["native_steps"]-entry_steps+3 > 72 or before["budgets"]["jev_remaining"] < 1 or before["budgets"]["native_steps_remaining"] < 3:
                    return finish("yield", "Control slice or episode budget reached; resume only after fresh phase validation.")
                if phase == "descent":
                    t, pts, u = tracking()
                    if pts is None: return tracking_gap("Package registration became inadequate during descent; no blind continuation.")
                    if float(np.max(np.linalg.norm(pts-np.array(g["package_prism_world_m"]), axis=1))) > 0.004:
                        return finish("needs_replan", "Package moved during the approach to contact.")
                own_now = before["own_geometry"]
                low, high = own_now["finger_low_offset_tool_m"], own_now["finger_high_offset_tool_m"]
                current_corners = np.array([[x, y, z] for x in [low[0], high[0]] for y in [low[1], high[1]] for z in [low[2], high[2]]])
                finger = current_corners @ geo.rotation(before["tcp_quaternion_xyzw"]).T+np.array(before["tcp_position_world_m"])
                floor, actual_margin = float(min(finger @ n+pd)), margins(g["table_polygon_world_m"], finger)
                d["actual_clearances"] = {"floor_m": floor, "footprint_m": actual_margin, "frame_id": before["frame_id"]}
                if phase in ["descent", "close"] and (floor < 0.0025 or actual_margin is None or actual_margin < 0.003):
                    return finish("blocked", "Actual own-finger floor/footprint margin is below its fixed execution threshold.")
                gripper = "open" if phase in ["approach", "descent"] else ("close" if phase == "close" else "keep")
                if phase == "close": d["closure_attempted"] = True
                d["pending_action"] = {"phase": phase, "target_pad_world_m": d["target"], "gripper": gripper, "before_native_steps": before["native_steps"]}
                save()
                receipt = api.control(d["target"], d.get("hold_quaternion", g["quaternion"]), gripper, questions,
                    features={"phase": phase, "review_frame": r["frame_id"], "tracker_frame": t["frame_id"], "tracker_uncertainty_m": u,
                        "access_frame": g["access_frame"], "planned_footprint_margin_m": g["footprint_margin_m"],
                        "actual_floor_margin_m": floor, "actual_footprint_margin_m": actual_margin, "local_table_margin_applicable": phase in ["descent", "close"],
                        "grasp_overlap_m": g["pad_package_overlap_m"], "observation_test_not_grasp_certification": phase == "lift1"},
                    tool_point="pad_center", translation_limit=0.02 if phase == "approach" else 0.012,
                    rotation_limit=0.06, steps=3, position_tolerance=0.004 if phase == "approach" else 0.0015, rotation_tolerance=0.025)
                used += 1
                d["last_receipt"], d["last_state"], d["pending_action"] = receipt, api.state(), None
                if receipt["choices"]["gripper"] == "close": d["closure_attempted"] = True
                save()
                desired = np.array(receipt["target_tcp"])-np.array(receipt["before"])
                delta = np.array(receipt["after"])-np.array(receipt["before"])
                tolerance = (0.004 if phase == "approach" else 0.0015)/math.sqrt(3.0)
                mismatch = receipt["choices"]["gripper"] != gripper
                for i, ax in enumerate(["x", "y", "z"]):
                    expected = "hold" if abs(desired[i]) <= tolerance else ("positive" if desired[i] > 0 else "negative")
                    if receipt["choices"][ax] != expected: mismatch = True
                if mismatch or float(np.dot(desired, delta)) < -0.000001:
                    return finish("blocked", "Acknowledged Jev choice or motion conflicts with the objective; no answer was corrected.")
                if receipt["status"] == "stalled": return finish("blocked", "Motion stalled; stop without repeating contact or reopening.")
                if phase == "close":
                    if receipt["position_error_m"] > 0.004 or receipt["rotation_error_rad"] > 0.05:
                        return finish("blocked", "Single closure was delivered but pose changed excessively; holding remains uncertain.")
                    reached = True
                else: reached = receipt["status"] == "reached"
                if reached: break
            if not reached: return finish("yield", "The 24-call / 72-step slice ended; exact acknowledged phase and target are saved.")
            if phase == "approach": d["phase"], d["target"] = "descent", g["grasp_pad_world_m"]
            elif phase == "descent": d["phase"] = "close"
            elif phase in ["close", "lift1"]:
                d["phase"] = "lift1" if phase == "close" else "lift2"
                target = geo.pad_position(d["last_state"]); target[2] += 0.025; d["target"] = target.tolist()
            elif phase == "lift2": d["phase"] = "verify"
            save()
            if used >= 24 and d["phase"] != "verify":
                return finish("yield", "Slice ended after an acknowledged phase; no action or release is implied on restart.")
        return finish("yield", "Bounded phase loop ended; continue from the saved phase after revalidation.")
    except Exception as exc:
        log.append({"runtime_error": str(exc), "phase": d.get("phase"), "used_controls": used, "pending_action": d.get("pending_action")})
        return finish("blocked", "Rejected measurement or runtime limitation; preserve actual execution and request supervision.")

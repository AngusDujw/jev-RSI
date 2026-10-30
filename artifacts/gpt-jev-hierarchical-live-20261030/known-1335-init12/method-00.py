def main(api):
    key = "grasp_stage_v1"
    evidence, used, g, d = [], 0, {}, {}
    def clean(value):
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(v) for v in value]
        if isinstance(value, np.floating):
            return float(value)
        if isinstance(value, np.integer):
            return int(value)
        return value
    def save():
        api.checkpoint(key, clean({"geometry": g, "progress": d, "recent_evidence": evidence[-3:]}))
    def end(status, reason):
        save()
        return {"stage_status": status, "reason": reason, "evidence": evidence[-12:],
                "handoff": {"checkpoint_key": key, "phase": d.get("phase", "measurement"),
                            "possibly_holding": d.get("closure_attempted", False),
                            "tracker_handle": g.get("handle"), "identity": "cream cheese package, not bowl",
                            "frames": "Metric world frame; quaternions xyzw; tracker maps its initial world frame to current world.",
                            "provenance": "Checkpoint contains RGB-D fitted table/top planes, projected visible top boundary, conservative package prism, measured own-finger envelope, acknowledged receipts, and retention observations with frame IDs.",
                            "requirements": "Revalidate identity, tracker quality, table stationarity and visible clearance after movement. Never reopen on restart. Initial boundary and free-table polygon are historical, not current detections.",
                            "package_dimensions_m": g.get("dimensions"), "package_in_tool_m": d.get("package_in_tool_m")},
                "completion_proposed": False}
    def ask(question, context, fields, names):
        last = None
        for attempt in range(2):
            last = api.review(question + (" Use DIFFERENT interior depth pixels or the other camera for failed measurements; do not repeat a failed boundary depth patch." if attempt else ""), context=context, fields=fields)
            evidence.append({"review_frame": last["frame_id"], "parameters": last["parameters"],
                             "points": last["points"], "measurement_errors": last["measurement_errors"]})
            save()
            if last["status"] == "stop":
                return last, False
            bad = [e["name"] for e in last["measurement_errors"]]
            if all(n in last["points"] and n not in bad for n in names):
                return last, True
        return last, False
    def tracking():
        t = api.track_update(g["handle"])
        summary = {k: t.get(k) for k in ["status", "frame_id", "reference_frame_id", "reason", "matches", "inliers", "rms_m", "inlier_spread_m", "uncertainty_floor_m"]}
        evidence.append({"tracking": summary})
        if t["status"] != "tracked":
            return t, None, None
        spread = t["inlier_spread_m"]
        coverage = sorted(spread, reverse=True)[1] if isinstance(spread, (list, tuple)) and len(spread) >= 2 else (float(spread) if isinstance(spread, (float, int)) else 0.0)
        u = max(0.001, t["rms_m"], t["uncertainty_floor_m"])
        if t["inliers"] < 12 or t["inliers"] / max(1, t["matches"]) < 0.60 or coverage < 0.006 or t["rms_m"] > 0.002 or u > 0.003:
            return t, None, None
        pts = geo.transform(g["package_prism_world_m"], t["transform_initial_world_to_current_world"])
        return t, pts, u
    questions = {}
    for axis in ["x", "y", "z", "rx", "ry", "rz"]:
        questions[axis] = {"type": "choice",
            "instructions": "For the " + axis + " world axis use its supplied state.processed_features.axes." + axis + ".goal_relation. Select decrease/within_tolerance/increase as negative/hold/positive respectively. Positive rotation means the positive world rotation-vector component. Program geometry is measured and prechecked; do not infer scene geometry or alter the target.",
            "criteria": {"negative": "goal_relation is decrease; negative world-axis motion", "hold": "goal_relation is within_tolerance; zero axis motion", "positive": "goal_relation is increase; positive world-axis motion"}}
    questions["gripper"] = {"type": "choice",
        "instructions": "Use state.processed_features.objective.gripper exactly. open opens only the pre-grasp empty hand; close attempts package acquisition; keep preserves the previous command. Closure is not retention evidence.",
        "criteria": {"open": "objective.gripper is open", "close": "objective.gripper is close", "keep": "objective.gripper is keep"}}
    try:
        manifest = api.recall()
        if any(m["key"] == key for m in manifest):
            old = api.recall(key)["value"]
            g, d = old["geometry"], old["progress"]
            evidence = old.get("recent_evidence", [])[-4:]
            current = api.state()
            acknowledged = d.get("last_state", {"native_steps": 0})
            if current["native_steps"] != acknowledged["native_steps"]:
                return end("blocked", "Physical steps occurred beyond the last saved acknowledgment; reconcile host receipts before resuming.")
            if not d.get("closure_attempted", False) and current["last_gripper_command"] != "open":
                return end("blocked", "Unexpected gripper command since the open-hand checkpoint; do not reopen.")
            if d.get("phase") == "verified":
                d["phase"] = "verify"
            if not g.get("handle") or "phase" not in d:
                return end("blocked", "Partial measurement checkpoint exists; revise using its valid partial measurements rather than resetting the physical episode.")
        else:
            s = api.state()
            if s["native_steps"] != 0 or s["last_gripper_command"] != "open":
                return end("blocked", "No grasp checkpoint, but this is not the untouched open-hand entry state. Reconcile acknowledged execution first.")
            pixel = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}
            polygon = {"type": "array", "items": pixel, "minItems": 4, "maxItems": 4}
            fields = {"identity": ["cream_cheese_on_table", "different", "unknown"], "box_model": ["visible_rectangular_box", "unsupported", "unknown"],
                      "free_area": ["visible_clear_except_package", "blocked", "unknown"], "camera": ["agentview", "robot0_eye_in_hand"],
                      "outline": polygon, "patch": polygon}
            r, ok = ask("Measure ONLY the cream cheese package and local access. Return identity and box_model only if its visible faces support a rectangular package resting on the tabletop. In the chosen camera return outline: four actual top-face boundary corners in cyclic physical order, and patch: an inset textured logo polygon on that same top face. Request named depth points p0,p1,p2,p3 well INSIDE that top face, distributed near its four corners, not on mixed-depth edges. Request t0,t1,t2,t3 in cyclic order on visible tabletop corners of a convex local area enclosing the package and the open fingers' eventual footprint. Except for the package, this whole area must be visibly free of bowl, stove and other obstacles; do not bridge occluded space. Own finger dimensions are in context. These four table samples must be spread around the package, not collinear. Do not substitute bowl or cheese graphics for the package boundary.", {"robot": s}, fields, ["p0", "p1", "p2", "p3", "t0", "t1", "t2", "t3"])
            if not ok:
                return end("abort" if r["status"] == "stop" else "blocked", "Could not obtain all required top/table depth samples; valid partial observations are checkpointed.")
            p = r["parameters"]
            if p["identity"] != "cream_cheese_on_table" or p["box_model"] != "visible_rectangular_box" or p["free_area"] != "visible_clear_except_package":
                return end("blocked", "Package identity, supported box model, or visible local access is unresolved.")
            top = np.array([r["points"]["p" + str(i)]["world_m"] for i in range(4)])
            table = np.array([r["points"]["t" + str(i)]["world_m"] for i in range(4)])
            tf, pf = clean(geo.plane(table)), clean(geo.plane(top))
            g.update({"measurement_frame": r["frame_id"], "table_fit": tf, "top_fit": pf, "table_polygon_world_m": table.tolist(), "camera": p["camera"], "outline_pixels": p["outline"], "patch_pixels": p["patch"]})
            save()
            n = np.array(tf["coefficients"][:3]); plane_d = tf["coefficients"][3]
            pn = np.array(pf["coefficients"][:3])
            if tf["rms_m"] > 0.0015 or pf["rms_m"] > 0.0015 or min(tf["in_plane_spread_m"]) < 0.025 or min(pf["in_plane_spread_m"]) < 0.006 or n[2] < 0.995 or pn[2] < 0.99:
                return end("blocked", "Top or table plane lacks adequate spread, horizontality, or fit accuracy.")
            boundary = [api.plane_point(p["camera"], uv, pf["coefficients"]) for uv in p["outline"]]
            box = np.array([x["world_m"] for x in boundary])
            edges = np.roll(box[:, :2], -1, axis=0) - box[:, :2]
            lengths = np.linalg.norm(edges, axis=1)
            if min(lengths) < 0.018 or max(lengths) > 0.15 or abs(lengths[0]-lengths[2]) > 0.004 or abs(lengths[1]-lengths[3]) > 0.004 or abs(float(np.dot(edges[0], edges[1]))) / (lengths[0]*lengths[1]) > 0.12:
                return end("blocked", "Measured top boundary does not support the required rectangular grasp geometry.")
            center = np.mean(box, axis=0)
            bottom = box.copy(); bottom[:, 2] = -(bottom[:, :2] @ n[:2] + plane_d) / n[2]
            heights = box[:, 2] - bottom[:, 2]
            if min(heights) < 0.009 or max(heights) > 0.06:
                return end("blocked", "Measured package height cannot support this table-clear side pinch.")
            axis = edges[0] if lengths[0] >= lengths[1] else edges[1]
            if float(np.dot(axis, geo.rotation(s["tcp_quaternion_xyzw"])[:2, 0])) < 0:
                axis = -axis
            q = api.compose([1.0, 0.0, 0.0, 0.0], [0.0, 0.0, math.atan2(float(axis[1]), float(axis[0]))])
            rot = geo.rotation(q); own = s["own_geometry"]
            lo, hi = own["finger_low_offset_tool_m"], own["finger_high_offset_tool_m"]
            own_corners = np.array([[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]])
            rel = (own_corners - np.array(own["pad_center_in_tool_m"])) @ rot.T
            zmin = max((0.005 - plane_d - n[0]*(center[0]+v[0]) - n[1]*(center[1]+v[1]) - n[2]*v[2]) / n[2] for v in rel)
            grasp = center.copy(); grasp[2] = max(float(center[2]-min(0.004, min(heights)*0.25)), zmin)
            overlap = min(float(min(box[:, 2])), float(grasp[2]+own["pad_extent_in_tool_m"][2]/2)) - max(float(max(bottom[:, 2])), float(grasp[2]-own["pad_extent_in_tool_m"][2]/2))
            poly = table[:, :2]; area = sum(poly[i, 0]*poly[(i+1)%4, 1]-poly[(i+1)%4, 0]*poly[i, 1] for i in range(4))
            sign = 1.0 if area > 0 else -1.0
            margins = []
            for i in range(4):
                a, b, c = poly[i], poly[(i+1)%4], poly[(i+2)%4]
                e = b-a; f = c-b
                if sign*(e[0]*f[1]-e[1]*f[0]) <= 0 or np.linalg.norm(e) < 0.03:
                    return end("blocked", "Local tabletop polygon is not a valid convex access area.")
                for v in np.concatenate((grasp[None, :] + rel, box), axis=0):
                    w = v[:2]-a
                    margins.append(float(sign*(e[0]*w[1]-e[1]*w[0])/np.linalg.norm(e)))
            if overlap < 0.004 or min(margins) < 0.007:
                evidence.append({"pad_package_overlap_m": float(overlap), "minimum_footprint_margin_m": min(margins)})
                return end("blocked", "The measured finger/table/obstacle margins do not permit this pinch; margins were not relaxed.")
            hover = grasp.copy(); hover[2] = geo.pad_position(s)[2]
            if hover[2] < max(box[:, 2]) + 0.12:
                return end("blocked", "Entry hand height is insufficient for the proposed elevated approach.")
            tr = api.track_init(p["camera"], p["patch"])
            g.update({"handle": tr["handle"], "tracker_creation": {k: tr.get(k) for k in ["handle", "frame_id", "camera", "method_number", "source_sha256"]}, "boundary_projection": boundary,
                      "package_prism_world_m": np.concatenate((box, bottom), axis=0).tolist(), "dimensions": [float(max(lengths)), float(min(lengths)), float(max(heights))],
                      "quaternion": q, "grasp_pad_world_m": grasp.tolist(), "hover_pad_world_m": hover.tolist(), "own_finger_corners_tool_m": own_corners.tolist(),
                      "planned_floor_margin_m": 0.005, "required_floor_margin_m": 0.0025, "required_footprint_margin_m": 0.003, "footprint_margin_m": min(margins), "pad_overlap_m": float(overlap)})
            d = {"phase": "approach", "target": hover.tolist(), "closure_attempted": False, "acknowledged_commands": 0}
            save()
        if d.get("closure_attempted", False) and d["phase"] in ["approach", "descent", "close"]:
            return end("blocked", "A closure may already have been delivered. Reconcile the saved receipt and fresh holding evidence; do not reopen or repeat contact.")
        fields = {"identity": ["same_package", "different", "unknown"], "clearance": ["visible_clear", "blocked", "unknown"],
                  "support": ["on_table", "between_open_fingers", "between_closed_fingers_on_table", "held_clear", "not_held", "unknown"]}
        for phase_index in range(6):
            phase = d["phase"]
            t, pts, uncertainty = tracking()
            r, ok = ask("Current grasp phase is " + phase + ". Confirm same physical cream cheese patch, not just similar texture. Request one fresh named tabletop depth point table_check on an unobstructed portion of the saved local table polygon. For approach, assess the entire elevated straight sweep of the open hand from current pose to the supplied hover, including yaw, from visible evidence. For descent, assess the vertical open-finger corridor within the measured free area and absence of package disturbance. For close, require package sides visibly straddled by the open fingers and table clearance. For lift1, assess closed fingers around the package (table support is allowed) and a clear 25 mm upward test corridor. For lift2 and verify, require the package visibly held between fingers and lifted clear of the table; lift2 also needs the next 25 mm upward corridor clear. Use unknown rather than certify occluded clearance. Do not infer holding from closure or a reached receipt.",
                        {"geometry": g, "progress": d, "tracker_status": t["status"], "tracked_package_world_m": None if pts is None else pts.tolist()}, fields, ["table_check"])
            if not ok or r["status"] == "stop":
                return end("abort" if r["status"] == "stop" else "blocked", "Fresh table reference unavailable; valid review measurements are preserved.")
            if r["parameters"]["identity"] == "different":
                return end("needs_replan", "Fresh observation invalidates the tracked package identity.")
            if pts is None:
                return end("blocked", "Package registration is unknown or inadequate. Fresh visual observations are saved; no extrapolated pose or blind motion was used.")
            n = np.array(g["table_fit"]["coefficients"][:3]); plane_d = g["table_fit"]["coefficients"][3]
            check = np.array(r["points"]["table_check"]["world_m"])
            if abs(float(np.dot(n, check)+plane_d)) > 0.003:
                return end("needs_replan", "Fresh table depth contradicts the saved support plane.")
            p = r["parameters"]
            if p["identity"] != "same_package" or p["clearance"] != "visible_clear":
                return end("blocked", "Current identity or the next local swept-volume clearance remains unresolved.")
            if phase in ["approach", "descent", "close"]:
                if float(np.max(np.linalg.norm(pts-np.array(g["package_prism_world_m"]), axis=1))) > 0.004:
                    return end("needs_replan", "Package moved before acquisition; the saved pinch target is no longer justified.")
                allowed = ["between_open_fingers"] if phase == "close" else ["on_table", "between_open_fingers"]
            else:
                allowed = ["between_closed_fingers_on_table", "held_clear"] if phase == "lift1" else ["held_clear"]
            if p["support"] not in allowed:
                return end("needs_replan" if p["support"] == "not_held" else "blocked", "Fresh package/finger relationship does not support this phase.")
            state = api.state()
            if phase == "close":
                fingers = np.array(g["own_finger_corners_tool_m"]) @ geo.rotation(state["tcp_quaternion_xyzw"]).T + np.array(state["tcp_position_world_m"])
                floor_margin = float(min(fingers @ n + plane_d))
                poly = np.array(g["table_polygon_world_m"])[:, :2]
                area = sum(poly[i, 0]*poly[(i+1)%4, 1]-poly[(i+1)%4, 0]*poly[i, 1] for i in range(4))
                sign = 1.0 if area > 0 else -1.0
                actual_margins = []
                for i in range(4):
                    a = poly[i]; e = poly[(i+1)%4]-a
                    for v in fingers:
                        w = v[:2]-a
                        actual_margins.append(float(sign*(e[0]*w[1]-e[1]*w[0])/np.linalg.norm(e)))
                evidence.append({"actual_finger_floor_margin_m": floor_margin, "actual_footprint_margin_m": min(actual_margins)})
                if floor_margin < g["required_floor_margin_m"] or min(actual_margins) < g["required_footprint_margin_m"]:
                    return end("blocked", "Measured current finger/table or footprint clearance is below the predeclared execution margin.")
                d["target"] = geo.pad_position(state).tolist(); d["hold_quaternion"] = state["tcp_quaternion_xyzw"]
            if phase in ["lift2", "verify"]:
                clearance = float(min(pts @ n + plane_d)) - uncertainty - 0.002
                evidence.append({"phase": phase, "package_lower_clearance_m": clearance, "state": state, "tracker_frame": t["frame_id"]})
                if clearance < 0.008:
                    return end("blocked", "No reliable positive package/table separation after the test lift.")
                if phase == "lift2":
                    refs = t["reference_inlier_world_m"]; current_points = t["current_inlier_world_m"]
                    count = min(24, len(refs))
                    ids = [int(round(i*(len(refs)-1)/(count-1))) for i in range(count)]
                    d["retention_baseline"] = {"state": state, "reference_points": [refs[i] for i in ids],
                                               "current_points": [current_points[i] for i in ids], "frame_id": t["frame_id"], "uncertainty_m": uncertainty}
                else:
                    b = d["retention_baseline"]
                    refs = np.array(t["reference_inlier_world_m"]); now = np.array(t["current_inlier_world_m"])
                    first, second = [], []
                    for i, ref in enumerate(b["reference_points"]):
                        distances = np.linalg.norm(refs-np.array(ref), axis=1); j = int(np.argmin(distances))
                        if distances[j] < 0.00001:
                            first.append(b["current_points"][i]); second.append(now[j].tolist())
                    evidence.append({"common_measured_surface_features": len(first)})
                    if len(first) < 6 or min(geo.plane(first)["in_plane_spread_m"]) < 0.003:
                        return end("blocked", "Insufficient shared, spread-out measured surface correspondences for the second-lift retention test.")
                    error = float(geo.attachment_error(first, second, b["state"], state))
                    hand_rise = float(state["tcp_position_world_m"][2]-b["state"]["tcp_position_world_m"][2])
                    evidence.append({"attachment_error_m": error, "hand_rise_m": hand_rise, "first_lift_frame": b["frame_id"], "second_lift_frame": t["frame_id"]})
                    if t["frame_id"] == b["frame_id"] or hand_rise < 0.015 or error > 0.004 + uncertainty + b["uncertainty_m"]:
                        return end("blocked", "Two lifted observations do not establish rigid retention within the declared error bound.")
                    d["package_in_tool_m"] = ((pts-np.array(state["tcp_position_world_m"])) @ geo.rotation(state["tcp_quaternion_xyzw"])).tolist()
                    d["verified_frame"] = t["frame_id"]; d["phase"] = "verified"
                    return end("stage_complete", "Fresh images show the package held clear in two lifted observations; measured package motion agrees with measured hand motion.")
            save()
            reached = False
            for j in range(24-used):
                before = api.state()
                gripper = "open" if phase in ["approach", "descent"] else ("close" if phase == "close" else "keep")
                if phase == "close":
                    d["closure_attempted"] = True
                    save()
                receipt = api.control(d["target"], d.get("hold_quaternion", g["quaternion"]), gripper, questions,
                    features={"phase": phase, "reference_frame": g["measurement_frame"], "fresh_review_frame": r["frame_id"],
                              "tracker_frame": t["frame_id"], "tracker_uncertainty_m": uncertainty,
                              "visible_local_clearance_approved": True, "planned_floor_margin_m": g["planned_floor_margin_m"],
                              "footprint_margin_m": g["footprint_margin_m"], "holding_not_inferred_from_closure": True},
                    tool_point="pad_center", translation_limit=0.02 if phase == "approach" else 0.012,
                    rotation_limit=0.06, steps=3, position_tolerance=0.004 if phase == "approach" else 0.0015, rotation_tolerance=0.025)
                used += 1
                d["last_receipt"] = receipt; d["last_state"] = api.state(); d["acknowledged_commands"] += 1
                save()
                if receipt["choices"]["gripper"] != gripper:
                    return end("blocked", "Jev gripper choice differed from the objective; receipt preserved without correction.")
                delta = np.array(receipt["after"])-np.array(receipt["before"])
                desired = np.array(receipt["target_tcp"])-np.array(receipt["before"])
                if float(np.dot(delta, desired)) < -0.000001:
                    return end("blocked", "Acknowledged translation moved against the target; no automatic retry.")
                if receipt["status"] == "stalled":
                    return end("blocked", "Motion stalled; no repeated contact or automatic reopening.")
                if phase == "close":
                    if receipt["position_error_m"] > 0.004 or receipt["rotation_error_rad"] > 0.05:
                        return end("blocked", "Closure was delivered but pose changed excessively; inspect actual contact before further motion.")
                    reached = True
                else:
                    reached = receipt["status"] == "reached"
                if reached:
                    break
            if not reached:
                return end("yield", "Reached the 24-call / 72-step slice bound; resume only after fresh phase validation.")
            if phase == "approach":
                d["phase"], d["target"] = "descent", g["grasp_pad_world_m"]
            elif phase == "descent":
                d["phase"] = "close"
            elif phase == "close":
                d["phase"] = "lift1"; target = geo.pad_position(api.state()); target[2] += 0.025; d["target"] = target.tolist()
            elif phase == "lift1":
                d["phase"] = "lift2"; target = geo.pad_position(api.state()); target[2] += 0.025; d["target"] = target.tolist()
            elif phase == "lift2":
                d["phase"] = "verify"
            save()
            if used >= 24 and d["phase"] != "verify":
                return end("yield", "Control slice exhausted after an acknowledged phase; checkpoint preserves the exact next phase and holding uncertainty.")
        return end("yield", "Bounded phase processing ended; checkpoint records the next required observation.")
    except Exception as exc:
        evidence.append({"runtime_error": str(exc), "phase": d.get("phase"), "used_control_calls": used, "closure_may_have_been_delivered": d.get("closure_attempted", False)})
        return end("blocked", "Runtime limitation or rejected measurement; reconcile checkpoint and acknowledged execution before revision.")

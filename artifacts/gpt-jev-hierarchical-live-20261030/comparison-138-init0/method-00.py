def main(api):
    def outcome(status, reason, evidence, handoff):
        return {"stage_status": status, "reason": reason, "evidence": evidence, "handoff": handoff, "completion_proposed": False}
    questions = {}
    for axis in ["x", "y", "z", "rx", "ry", "rz"]:
        questions[axis] = {"type": "choice", "instructions": "Subject: world " + axis + " observation-pose component. Read state.processed_features.axes." + axis + ".goal_relation and state.processed_features.program.motion_authorized. Without authorization choose hold. Otherwise follow decrease, within_tolerance, or increase.", "criteria": {"negative": "Authorized decrease of this world component.", "hold": "No motion authorization, or this component is within tolerance.", "positive": "Authorized increase of this world component."}}
    questions["gripper"] = {"type": "choice", "instructions": "Subject: observation-stage gripper. Read state.processed_features.program.motion_authorized and state.processed_features.objective.gripper. Observation alone authorizes no opening or closing; choose keep.", "criteria": {"open": "Explicitly authorized empty-hand opening with objective open.", "close": "Explicitly authorized closing with objective close.", "keep": "Preserve the gripper during this observation-only stage."}}
    s = api.state()
    history, refs, gap = [], None, "No adequate geometry acquired."
    handoff = {"stage": "establish", "checkpoint_keys": ["establish.partial"], "frame": "World coordinates in meters; image pixels have top-left origin.", "physical_actions": 0}
    if s["budgets"]["gpt_remaining"] < 2:
        return outcome("yield", "Two observation reviews are needed; insufficient current review budget.", {"state": s}, handoff)
    def cross(a, b):
        return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]
    def horizontal(points, label):
        a = np.asarray(points, dtype=float)
        if a.ndim != 2 or a.shape[1] != 3 or not bool(np.isfinite(a).all()):
            raise RuntimeError(label + ": malformed measurements")
        f = geo.plane(a)
        z = float(f["center_world_m"][2])
        if f["rms_m"] > 0.002 or min(f["in_plane_spread_m"]) < 0.015 or float(np.max(np.abs(a[:, 2] - z))) > 0.003:
            raise RuntimeError(label + ": horizontal-plane adequacy or spatial spread failed; fit=" + str(f))
        return f, [0.0, 0.0, 1.0, -z]
    pixel = {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}
    fields = {"bowl_identity": ["patterned_bowl", "unknown"], "cabinet_identity": ["cabinet_table_1", "unknown"], "bowl_upright": ["yes", "no", "unknown"], "safe_patch": ["fully_visible_clear", "not_clear", "unknown"], "outer_rim": ["entire_visible_circular_lip", "unknown"], "body_profile": ["narrows_below_rim", "unknown"], "rim_camera": ["agentview", "robot0_eye_in_hand"], "rim_pixels": {"type": "array", "items": pixel, "minItems": 0, "maxItems": 8}, "grasp_index": {"type": "integer", "minimum": -1, "maximum": 7}, "note": {"type": "string", "maxLength": 400}}
    names = ["lip" + str(i) for i in range(6)] + ["top" + str(i) for i in range(4)] + ["check" + str(i) for i in range(3)] + ["counter" + str(i) for i in range(3)]
    prompt = "Establish geometry only; no robot action. Identify the patterned bowl and the dark cabinet table 1 at the left, NOT the white hotplate. Request named depth points lip0..lip5 on actual uppermost lip material, distributed around the rim, radius=1, using either current camera. Do not substitute inner-wall or background depths. Request top0..top3, in perimeter order, as vertices of the largest convex, entirely visible, unobstructed patch on the cabinet TOP. These are measured interior support vertices, not guessed hidden cabinet corners. Request check0..check2 spread inside that patch, and counter0..counter2 on noncollinear exposed counter near the bowl. Provide eight outer-lip boundary pixels in rim_camera, ordered around the perimeter with index 0 on the side nearest the cabinet; use [] when unknown. These pixels will only be intersected with a measured horizontal lip plane. Select grasp_index for a lip sector with visible interior and exterior finger neighborhoods, away from bottle, package, plate and cabinet; -1 if none. Assess the declared identity, uprightness, visible body profile and patch fields conservatively. Unknown or failed depth must remain unknown. Do not certify hidden space."
    for attempt in range(min(2, int(s["budgets"]["gpt_remaining"]) - 1)):
        try:
            r = api.review(prompt + (" Complementary retry: use a different camera or different depth-valid surface samples and a revised genuinely visible support patch. Do not repeat failed pixels or reduce margins." if attempt else ""), context={"previous_gap": gap, "previous_observations": history, "own_geometry": s["own_geometry"]}, fields=fields)
            p, frame = r["parameters"], r["frame_id"]
            errors = [{"name": e["name"], "error": e["error"][:240]} for e in r["measurement_errors"]]
            pts = {n: r["points"][n] for n in names if n in r["points"] and r["points"][n]["frame_id"] == frame and not any(e["name"] == n for e in errors)}
            compact = {n: {"world_m": v["world_m"], "camera": v["camera"], "pixel": v["pixel"], "frame_id": v["frame_id"]} for n, v in pts.items()}
            history.append({"frame_id": frame, "parameters": p, "points": compact, "measurement_errors": errors})
            api.checkpoint("establish.partial", {"observations": history, "native_steps": s["native_steps"], "provenance": "Fresh reviews and successful named depth measurements; no motion."})
            if r["status"] == "stop":
                return outcome("abort", r["explanation"], history[-1], handoff)
            if api.state()["native_steps"] != s["native_steps"]:
                return outcome("needs_replan", "Unexpected physical state change during observation; references require reacquisition.", history[-1], handoff)
            if p["bowl_upright"] == "no":
                return outcome("needs_replan", "Observed bowl is not upright; the upright rim-grasp plan needs revision.", history[-1], handoff)
            if p["bowl_identity"] != "patterned_bowl" or p["cabinet_identity"] != "cabinet_table_1" or p["bowl_upright"] != "yes" or p["safe_patch"] != "fully_visible_clear" or p["outer_rim"] != "entire_visible_circular_lip" or p["body_profile"] != "narrows_below_rim":
                raise RuntimeError("Identity, visible support coverage, uprightness or rim-envelope interpretation remains unresolved.")
            lip = [pts["lip" + str(i)]["world_m"] for i in range(6) if "lip" + str(i) in pts]
            checks = [pts["check" + str(i)]["world_m"] for i in range(3) if "check" + str(i) in pts]
            missing = [n for n in ["top0", "top1", "top2", "top3", "counter0", "counter1", "counter2"] if n not in pts]
            if missing or len(lip) < 4 or len(checks) < 2 or len(p["rim_pixels"]) != 8 or p["grasp_index"] < 0:
                raise RuntimeError("Insufficient successful measurements: missing=" + str(missing) + "; lip_count=" + str(len(lip)) + "; check_count=" + str(len(checks)) + "; errors=" + str(errors))
            lf, lp = horizontal(lip, "Bowl lip")
            boundary = [api.plane_point(p["rim_camera"], px, lp) for px in p["rim_pixels"]]
            if any(b["frame_id"] != frame for b in boundary):
                raise RuntimeError("Boundary intersections are not from the measured frame.")
            rim = np.asarray([b["world_m"] for b in boundary], dtype=float)
            circle = geo.circle_xy(rim)
            center = np.asarray(circle["center_xy_m"], dtype=float)
            if not 0.035 <= circle["radius_m"] <= 0.13 or circle["rms_m"] > 0.003 or circle["max_radial_error_m"] > 0.005 or circle["largest_angular_gap_rad"] > 1.6:
                raise RuntimeError("Observed outer-rim circle model or coverage failed: " + str(circle))
            if float(np.max(np.abs(np.linalg.norm(np.asarray(lip)[:, :2] - center, axis=1) - circle["radius_m"]))) > 0.007:
                raise RuntimeError("Actual lip depths and derived outer-boundary circle disagree by more than 7 mm.")
            top = [pts["top" + str(i)]["world_m"] for i in range(4)]
            tf, tp = horizontal(top + checks, "Cabinet support")
            cf, cp = horizontal([pts["counter" + str(i)]["world_m"] for i in range(3)], "Counter")
            poly = np.asarray(top, dtype=float)[:, :2]
            if float(np.sum(cross(poly, np.roll(poly, -1, axis=0)))) < 0:
                poly = poly[::-1].copy()
            edges = np.roll(poly, -1, axis=0) - poly
            lengths = np.linalg.norm(edges, axis=1)
            if float(np.min(lengths)) < 0.03 or not bool((cross(edges, np.roll(edges, -1, axis=0)) > 0.000001).all()):
                raise RuntimeError("Support vertices do not define an adequate convex visible polygon.")
            if any(float(np.min(cross(edges, np.asarray(c)[:2] - poly) / lengths)) < 0 for c in checks):
                raise RuntimeError("A support validation point is outside the declared visible polygon.")
            best, best_xy = -1.0, None
            for x in np.linspace(float(np.min(poly[:, 0])), float(np.max(poly[:, 0])), 25):
                for y in np.linspace(float(np.min(poly[:, 1])), float(np.max(poly[:, 1])), 25):
                    d = float(np.min(cross(edges, np.asarray([x, y]) - poly) / lengths))
                    if d > best:
                        best, best_xy = d, [float(x), float(y)]
            uncertainty = max(0.004, 3.0 * lf["rms_m"], 3.0 * tf["rms_m"], 3.0 * circle["rms_m"])
            radius_bound = circle["radius_m"] + circle["max_radial_error_m"] + uncertainty
            margin = best - radius_bound
            if margin < 0.012:
                raise RuntimeError("Measured visible support patch too small: inscribed_radius=" + str(best) + "; bowl_bound=" + str(radius_bound) + "; remaining_margin=" + str(margin) + "; required=0.012 m.")
            refs = {"frame_id": frame, "native_steps": s["native_steps"], "bowl": {"circle": circle, "lip_plane": lp, "lip_fit": lf, "rim_world_m": rim.tolist(), "rim_pixels": p["rim_pixels"], "rim_camera": p["rim_camera"], "radius_bound_m": radius_bound}, "support": {"polygon_xy_m": poly.tolist(), "plane": tp, "fit": tf, "candidate_center_xy_m": best_xy, "inscribed_radius_m": best, "remaining_margin_m": margin}, "counter": {"plane": cp, "fit": cf}, "uncertainty_floor_m": uncertainty, "grasp_index": p["grasp_index"], "selected_depth_points": compact}
            break
        except Exception as e:
            gap = str(e)
            history.append({"attempt": attempt, "gap": gap[:1200]})
            api.checkpoint("establish.partial", {"observations": history, "native_steps": s["native_steps"], "latest_gap": gap[:1200]})
    if refs is None:
        return outcome("blocked", gap, {"observations": history, "physical_actions": 0}, handoff)
    api.checkpoint("establish.geometry", refs)
    handoff["checkpoint_keys"].append("establish.geometry")
    try:
        g = rim[p["grasp_index"]].copy()
        radial = (g[:2] - center) / np.linalg.norm(g[:2] - center)
        tangent = np.asarray([radial[1], -radial[0]])
        old_rotation = geo.rotation(s["tcp_quaternion_xyzw"])
        if float(old_rotation[2, 2]) > -0.98:
            raise RuntimeError("Current tool is not sufficiently downward for the proposed yaw-only observation envelope.")
        yaw = math.atan2(float(radial[1]), float(radial[0])) - math.atan2(float(old_rotation[1, 1]), float(old_rotation[0, 1]))
        q = api.compose(s["tcp_quaternion_xyzw"], [0.0, 0.0, yaw])
        own = s["own_geometry"]
        lo, hi = own["finger_low_offset_tool_m"], own["finger_high_offset_tool_m"]
        corners = np.asarray([[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]])
        offsets = (corners - np.asarray(own["pad_center_in_tool_m"])) @ geo.rotation(q).T
        projected = np.column_stack((offsets[:, :2] @ tangent, offsets[:, :2] @ radial))
        padding = uncertainty + 0.006
        low, high = np.min(projected, axis=0) - padding, np.max(projected, axis=0) + padding
        context = {"geometry": refs, "candidate_lip_world_m": g.tolist(), "closing_axis_world_xy": radial.tolist(), "tangent_world_xy": tangent.tolist(), "open_finger_envelope_local_xy_m": [low.tolist(), high.tolist()], "own_geometry": own, "current_state": s, "note": "The envelope is centered at the selected lip; first coordinate is tangent and second is radial. No grasp, hidden clearance or route has been established."}
        f2 = {"candidate_identity": ["same_bowl_lip", "unknown"], "inner_surface": ["visible_bowl_interior", "unknown"], "outer_surface": ["visible_counter", "obstructed", "unknown"], "approach_visibility": ["visible_no_overhang", "occluded", "unknown"], "support_still_valid": ["yes", "no", "unknown"], "hand_state": ["empty_open", "possibly_holding", "unknown"], "note": {"type": "string", "maxLength": 500}}
        v = api.review("Focused complementary evidence for the selected lip sector. Request named depth points inner and outer on visible surfaces beneath the inward and outward open-finger neighborhoods, approximately 35-50 mm from the lip along the supplied radial axis, near its tangent center. Never measure a hidden surface. Request regions approach_eye and approach_agent, each with explicit camera, tight image box covering this entire projected open-finger envelope plus nearby obstacles, and stride=4. The crops are unsegmented evidence, not object masks. Use both views where possible. Inspect all of the envelope for occlusion, overhangs or nearby bottle/package/cabinet intrusion; visible_no_overhang means observed coverage only, not hidden-space certification. Reconfirm the support polygon is on the same clear cabinet top and the selected sector is the same bowl lip. Report the declared fields.", context=context, fields=f2)
        if v["status"] == "stop":
            return outcome("abort", v["explanation"], {"geometry": refs}, handoff)
        if api.state()["native_steps"] != s["native_steps"] or v["frame_id"] != refs["frame_id"]:
            return outcome("needs_replan", "Scene changed between geometry and clearance observations.", {"geometry": refs, "review_frame": v["frame_id"]}, handoff)
        bad = [e["name"] for e in v["measurement_errors"]]
        valid_points = {n: v["points"][n] for n in ["inner", "outer"] if n in v["points"] and n not in bad and v["points"][n]["frame_id"] == v["frame_id"]}
        clearance = {"frame_id": v["frame_id"], "parameters": v["parameters"], "points": valid_points, "measurement_errors": [{"name": e["name"], "error": e["error"][:240]} for e in v["measurement_errors"]]}
        refs["clearance_review"] = clearance
        api.checkpoint("establish.geometry", refs)
        a = v["parameters"]
        if a["hand_state"] == "possibly_holding":
            return outcome("needs_replan", "Fresh review indicates a possibly occupied hand; do not open it blindly.", clearance, handoff)
        if a["candidate_identity"] != "same_bowl_lip" or a["inner_surface"] != "visible_bowl_interior" or a["outer_surface"] != "visible_counter" or a["approach_visibility"] != "visible_no_overhang" or a["support_still_valid"] != "yes":
            raise RuntimeError("Selected lip, local visibility, exterior clearance or support confirmation is unresolved: " + str(a))
        if len(valid_points) != 2:
            raise RuntimeError("Missing inner/outer surface depth: " + str(clearance["measurement_errors"]))
        clouds = [np.asarray(v["regions"][n]["world_m"], dtype=float) for n in ["approach_eye", "approach_agent"] if n in v["regions"] and n not in bad and v["regions"][n]["frame_id"] == v["frame_id"] and len(v["regions"][n]["world_m"]) > 0]
        if not clouds:
            raise RuntimeError("No successful current approach cloud.")
        cloud = np.concatenate(clouds, axis=0)
        cloud = cloud[np.isfinite(cloud).all(axis=1)]
        uv = np.column_stack(((cloud[:, :2] - g[:2]) @ tangent, (cloud[:, :2] - g[:2]) @ radial))
        mask = ((uv >= low) & (uv <= high)).all(axis=1)
        if int(np.sum(mask)) < 30:
            raise RuntimeError("Too few visible samples in the actual open-finger envelope.")
        coverage_gap = 0.0
        for x in np.linspace(float(low[0]), float(high[0]), 5):
            for y in np.linspace(float(low[1]), float(high[1]), 15):
                coverage_gap = max(coverage_gap, float(np.min(np.linalg.norm(uv - np.asarray([x, y]), axis=1))))
        exterior_high = (np.linalg.norm(cloud[:, :2] - center, axis=1) > radius_bound) & (cloud[:, 2] > g[2] - 0.015)
        clearance["coverage_gap_m"] = coverage_gap
        clearance["envelope_samples"] = int(np.sum(mask))
        clearance["external_high_samples_in_envelope"] = int(np.sum(mask & exterior_high))
        if coverage_gap > 0.008 or bool(np.any(mask & exterior_high)):
            raise RuntimeError("Local approach sampling gap exceeds 8 mm or a measured neighboring high surface enters the padded finger envelope: " + str(clearance))
        for name, sign in [("inner", -1), ("outer", 1)]:
            point = np.asarray(valid_points[name]["world_m"])
            d = point[:2] - g[:2]
            if not 0.015 < sign * float(d @ radial) < float(max(abs(low[1]), abs(high[1]))) + 0.015 or abs(float(d @ tangent)) > 0.025 or float(point[2]) > float(g[2]) - 0.012:
                raise RuntimeError(name + " depth does not validate the selected low finger-neighborhood surface.")
        top_visible = float(np.max(cloud[mask, 2]))
        hover = [float(g[0]), float(g[1]), top_visible + 0.025 - float(np.min(offsets[:, 2]))]
        refs["approach"] = {"lip_world_m": g.tolist(), "radial_world_xy": radial.tolist(), "candidate_quaternion_xyzw": q, "open_finger_offsets_world_m": offsets.tolist(), "padded_local_envelope_m": [low.tolist(), high.tolist()], "observed_max_surface_z_m": top_visible, "local_hover_pad_world_m": hover, "hover_lowest_finger_margin_m": 0.025, "clearance": clearance}
        refs["limitations"] = ["No motion, contact, grasp or retention test occurred.", "The 4 mm minimum uncertainty allowance is conservative engineering padding, not calibrated confidence.", "Cloud coverage and visual review describe visible surfaces only; hidden volume is not certified.", "The local hover envelope is not a certified swept route from the present robot pose.", "Contact depth, closing clearance, underside/base offset and subsequent transport/release clearances remain unmeasured.", "Revalidate all affected geometry after movement; recompute finger bounds if opening or orientation changes."]
        refs["control"] = {"motion_authorized": False, "jev_calls": 0, "native_steps_added": 0, "question_keys": list(questions)}
        api.checkpoint("establish.geometry", refs)
        handoff.update({"geometry_checkpoint": "establish.geometry", "provenance": "Successful current RGB-D points; outer rim ray intersections with the measured horizontal lip model; numerical fits; focused current two-view clearance review.", "freshness": {"frame_id": refs["frame_id"], "native_steps": s["native_steps"]}, "next_scope": "Acquire only after validating the actual next swept approach and contact clearance. Use the measured visible support polygon, not hidden cabinet edges. No bowl attachment or base offset is available.", "assumptions": refs["limitations"]})
        evidence = {"bowl_circle": circle, "support_remaining_margin_m": margin, "support_candidate_center_xy_m": best_xy, "uncertainty_floor_m": uncertainty, "selected_lip_world_m": g.tolist(), "local_hover_pad_world_m": hover, "clearance_review": clearance, "physical_actions": 0}
        return outcome("stage_complete", "Fresh calibrated observations establish the bowl rim, a sufficiently large visible cabinet support patch, and an observed accessible local pregrasp sector. No grasp or whole-task completion is claimed.", evidence, handoff)
    except Exception as e:
        refs["latest_gap"] = str(e)[:1600]
        api.checkpoint("establish.geometry", refs)
        return outcome("blocked", str(e)[:1600], {"geometry": refs, "physical_actions": 0}, handoff)

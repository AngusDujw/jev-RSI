def main(api):
    axes = ("x", "y", "z", "rx", "ry", "rz")
    questions = {a: {"type": "choice", "instructions": "For world axis " + a + ", use its supplied goal_relation only: increase means positive, decrease means negative, within_tolerance means hold. Do not infer clearance from pose residuals.", "criteria": {"negative": "Decrease this world coordinate or world rotation-vector component.", "hold": "No correction within the supplied tolerance.", "positive": "Increase this world coordinate or world rotation-vector component."}} for a in axes}
    questions["gripper"] = {"type": "choice", "instructions": "Use state.processed_features.objective.gripper; do not infer possession from closure.", "criteria": {"open": "Deliver the explicitly authorized open objective.", "close": "Deliver the explicitly authorized close objective.", "keep": "Preserve the existing command."}}
    start = api.state()
    logs, keys, geometry = [], [], {}
    assumptions = ["All positions are world meters; pixels have top-left origin and their saved camera/frame.", "Measurements are visible surfaces, not hidden collision geometry.", "Uncertainty margins are conservative engineering allowances, not calibrated confidence bounds.", "No motion, grasp, retention, or base contact is established by this observation stage.", "Landing size uses the rim-enclosed visible bowl silhouette, not an invented hidden base; recheck the bowl extent after lifting."]
    def save(key, value):
        api.checkpoint(key, value)
        if key not in keys:
            keys.append(key)
    def finish(status, reason):
        end = api.state()
        evidence = {"start_frame": start["frame_id"], "end_frame": end["frame_id"], "native_steps_start": start["native_steps"], "native_steps_end": end["native_steps"], "physical_commands": 0, "geometry": geometry, "diagnostics": logs}
        save("observe.result", {"evidence": evidence, "assumptions": assumptions, "control_questions": questions})
        return {"stage_status": status, "reason": reason, "evidence": evidence, "handoff": {"checkpoint_keys": keys, "reference_frame": end["frame_id"], "coordinate_frame": "world meters, xyzw tool-to-world quaternions", "assumptions": assumptions, "scope": "References concern the identified patterned bowl and dark cabinet table 1. Revalidate affected references after any motion. The high alignment envelope is not clearance for descent, closure, lifting, transport, or release. Exact aperture, lower contact geometry, hidden bowl base, and subsequent retention must be assessed by the next method.", "next_observation": "Use the saved rim section and visible inner/outer contact samples to plan a rim pinch, not an across-mouth grasp. No action has been taken."}, "completion_proposed": False}
    if start["last_gripper_command"] != "open":
        return finish("blocked", "The current gripper is not known open; observation must not reopen a possibly held object.")
    selector = {"type": "object", "properties": {"visible": {"type": "boolean"}, "camera": {"type": "string", "enum": ["agentview", "robot0_eye_in_hand"]}, "pixel": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}}, "required": ["visible", "camera", "pixel"], "additionalProperties": False}
    names = ["rim" + str(i) for i in range(8)] + ["table" + str(i) for i in range(5)] + ["inner", "outer", "band0", "band1"]
    fields = {n: selector for n in names}
    fields.update({"target": ["confirmed", "ambiguous", "wrong"], "bowl": ["confirmed", "ambiguous"], "table_patch": ["clear_visible_planar_convex", "obstructed", "occluded", "unknown"], "rim": ["level_outer_rim", "unknown"], "outline": ["rim_encloses_visible_bowl_outline", "unknown"], "grasp_band": ["both_walls_and_continuous_rim_visible", "obstructed", "occluded", "unknown"]})
    prompt = "Observe only; no task completion claim. Identify patterned bowl and the upper horizontal dark cabinet table 1 at left, not the counter or cabinet side. Return typed pixel selectors, not metric estimates; the program will depth-sample radius=1. Mark visible=false if unavailable. rim0..rim7: eight cyclic, evenly distributed points on actual upper OUTER rim material, using the overhead view where useful, not background or inner floor. table0..table3: cyclic corners of the largest fully visible clear convex INTERIOR tabletop quadrilateral, inside real edges, never invent an image-clipped boundary. table4: an independent central surface sample inside that patch. inner and outer: corresponding visible inner and outer wall surfaces at one front-facing accessible rim section, approximately 6-15 mm below the lip, same radial section and height; choose respective cameras as needed. band0 and band1: actual lip endpoints of a continuous unobstructed approximately 35-45 mm tangential rim section centered on those wall samples. Do not project an occluded wall or infer a hidden contact point. The outline classification requires the visible bowl silhouette to lie inside its outer mouth footprint, with no outward extension. The table_patch classification requires the entire chosen interior area to be visible and vacant. Return unknown if that is not supported. Request no clouds."
    def measure(review, requested):
        p, out, errors = review["parameters"], {}, list(review.get("measurement_errors", []))
        for name in requested:
            if name not in p or not p[name]["visible"]:
                errors.append({"name": name, "error": "Visible pixel selector unavailable."})
                continue
            try:
                item = api.point(p[name]["camera"], p[name]["pixel"], radius=1)
                if item["frame_id"] != review["frame_id"] or not np.all(np.isfinite(np.array(item["world_m"]))):
                    raise ValueError("Point frame or finite-depth validation failed.")
                out[name] = item
            except Exception as error:
                errors.append({"name": name, "error": str(error)[:400]})
        return out, errors
    valid = False
    for attempt in range(2):
        review = api.review(prompt + (" Retry only with a different valid pixel, section, or larger visible table patch addressing the supplied gaps; do not repeat an unchanged unsupported assertion." if attempt else ""), context={"previous_gaps": logs[-1:], "previous_measured_geometry": geometry}, fields=fields)
        p = review["parameters"]
        points, errors = measure(review, names)
        sample_key = "observe.samples" + str(attempt)
        save(sample_key, {"frame_id": review["frame_id"], "selectors_and_identity": p, "points": points, "measurement_errors": errors, "own_geometry": start["own_geometry"], "tcp_position_world_m": start["tcp_position_world_m"], "tcp_quaternion_xyzw": start["tcp_quaternion_xyzw"]})
        if p["target"] == "wrong":
            return finish("needs_replan", "Fresh identification invalidates the proposed cabinet target.")
        if p["target"] != "confirmed" or p["bowl"] != "confirmed":
            return finish("blocked", "Object identity remains ambiguous in the existing views; saved selectors require a complementary observation, not another identical review.")
        gaps = []
        if review["status"] == "stop":
            return finish("blocked", "Observation review stopped: " + review["explanation"])
        if errors or any(n not in points for n in names):
            gaps.append("Missing or invalid named surface depths; see " + sample_key)
        expected = {"target": "confirmed", "bowl": "confirmed", "table_patch": "clear_visible_planar_convex", "rim": "level_outer_rim", "outline": "rim_encloses_visible_bowl_outline", "grasp_band": "both_walls_and_continuous_rim_visible"}
        gaps += [k + ": " + p[k] for k in expected if p[k] != expected[k]]
        if not gaps:
            try:
                rim = np.array([points["rim" + str(i)]["world_m"] for i in range(8)])
                table = np.array([points["table" + str(i)]["world_m"] for i in range(5)])
                rp, tp, circle = geo.plane(rim), geo.plane(table), geo.circle_xy(rim)
                rn, tn = np.array(rp["coefficients"]), np.array(tp["coefficients"])
                center, radius = np.array(circle["center_xy_m"]), float(circle["radius_m"])
                u = max(0.003, 3.0 * float(rp["rms_m"]), 3.0 * float(circle["rms_m"]), float(circle["max_radial_error_m"]))
                tu = max(0.003, 3.0 * float(tp["rms_m"]))
                if rn[2] < 0.985 or rp["rms_m"] > 0.0025 or min(rp["in_plane_spread_m"]) < 0.025 or not 0.03 <= radius <= 0.12 or circle["largest_angular_gap_rad"] > 1.7 or u > 0.008:
                    gaps.append("Outer rim horizontal-circle model or coverage fails its fixed margins.")
                if tn[2] < 0.985 or tp["rms_m"] > 0.0025 or min(tp["in_plane_spread_m"]) < 0.035:
                    gaps.append("Table patch is not adequately sampled horizontal planar support.")
                poly = table[:4, :2]
                edges = np.roll(poly, -1, axis=0) - poly
                crosses = [float(edges[i, 0] * edges[(i+1)%4, 1] - edges[i, 1] * edges[(i+1)%4, 0]) for i in range(4)]
                landing = np.mean(poly, axis=0)
                distances = [float(abs(e[0]*(landing-v)[1]-e[1]*(landing-v)[0])/np.linalg.norm(e)) for e, v in zip(edges, poly)]
                central_signs = [float(e[0]*(table[4, :2]-v)[1]-e[1]*(table[4, :2]-v)[0]) for e, v in zip(edges, poly)]
                convex = all(x > 0.0 for x in crosses) or all(x < 0.0 for x in crosses)
                inside = all(x > 0.0 for x in central_signs) or all(x < 0.0 for x in central_signs)
                margin = min(distances) - radius - u - tu
                if not convex or not inside or not np.isfinite(margin) or margin < 0.012:
                    gaps.append("Visible interior support polygon fails the full-mouth-footprint plus 12 mm clearance test.")
                inner, outer = np.array(points["inner"]["world_m"]), np.array(points["outer"]["world_m"])
                band = np.array([points["band0"]["world_m"], points["band1"]["world_m"]])
                grip = (inner + outer) / 2.0
                radial = grip[:2] - center
                radial = radial / np.linalg.norm(radial)
                tangent = np.array([-radial[1], radial[0]])
                thickness = float(np.dot((outer-inner)[:2], radial))
                span = float(abs(np.dot((band[1]-band[0])[:2], tangent)))
                rim_z = float(np.mean(rim[:, 2]))
                below = [float(rim_z-inner[2]), float(rim_z-outer[2])]
                if not 0.0 < thickness <= 0.025 or abs(inner[2]-outer[2]) > 0.006 or abs(float(np.dot((outer-inner)[:2], tangent))) > 0.008 or min(below) < 0.002 or max(below) > 0.025:
                    gaps.append("Wall samples do not establish a narrow same-section sub-rim pinch candidate.")
                if span < float(start["own_geometry"]["pad_extent_in_tool_m"][0]) + 0.016 or span > 0.075 or np.linalg.norm(np.mean(band[:, :2], axis=0)-grip[:2]) > 0.025 or any(abs(float(np.linalg.norm(b[:2]-center))-radius) > u+0.004 for b in band):
                    gaps.append("Visible continuous grasp-band coverage is inadequate for the finger tangential width plus margin.")
                if not all(np.isfinite(x) for x in [thickness, span, rim_z]) or not np.all(np.isfinite(radial)):
                    gaps.append("Nonfinite grasp geometry.")
                landing3 = [float(landing[0]), float(landing[1]), float(-(tn[0]*landing[0]+tn[1]*landing[1]+tn[3])/tn[2])]
                geometry = {"frame_id": review["frame_id"], "sample_checkpoint": sample_key, "bowl": {"center_xy_m": center.tolist(), "rim_z_m": rim_z, "outer_rim_radius_m": radius, "allowance_m": u, "plane": rn.tolist(), "plane_rms_m": float(rp["rms_m"]), "circle_rms_m": float(circle["rms_m"]), "largest_angular_gap_rad": float(circle["largest_angular_gap_rad"])}, "table": {"plane": tn.tolist(), "rms_m": float(tp["rms_m"]), "visible_interior_polygon_world_m": table[:4].tolist(), "landing_center_world_m": landing3, "inscribed_xy_radius_m": min(distances), "remaining_margin_m": margin, "allowance_m": tu}, "grasp_region": {"inner_world_m": inner.tolist(), "outer_world_m": outer.tolist(), "band_world_m": band.tolist(), "candidate_center_world_m": grip.tolist(), "outward_radial_xy": radial.tolist(), "measured_wall_thickness_m": thickness, "wall_thickness_allowance_m": 2.0*u, "tangent_span_m": span, "actuator_qpos_m": start["gripper_qpos_m"], "aperture_certified": False}}
            except Exception as error:
                gaps.append("Geometry rejected: " + str(error)[:500])
        logs.append({"measurement_attempt": attempt, "frame_id": review["frame_id"], "gaps": gaps})
        if not gaps:
            valid = True
            break
    if not valid:
        return finish("blocked", "Two bounded measurements did not establish the required grasp/support geometry; inspect saved exact gaps and partial depths.")
    R, pad = geo.rotation(start["tcp_quaternion_xyzw"]), np.array(geo.pad_position(start))
    own = start["own_geometry"]
    lo, hi = own["finger_low_offset_tool_m"], own["finger_high_offset_tool_m"]
    corners = np.array([[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]])
    offsets = corners @ R.T - R @ np.array(own["pad_center_in_tool_m"])
    if R[2, 2] > -0.97:
        return finish("blocked", "Current tool is not sufficiently downward for the proposed yaw-only overhead envelope.")
    high = max(float(pad[2]), rim_z + 0.10)
    target = np.array([grip[0], grip[1], high])
    swept_radius = max(float(np.linalg.norm(v[:2])) for v in offsets) + 0.005
    bottom = min(float(pad[2]), high) + float(np.min(offsets[:, 2]))
    envelope = {"pad_start_world_m": pad.tolist(), "high_pad_alignment_world_m": target.tolist(), "xy_min_m": (np.minimum(pad[:2], target[:2])-swept_radius).tolist(), "xy_max_m": (np.maximum(pad[:2], target[:2])+swept_radius).tolist(), "yaw_invariant_finger_xy_radius_m": swept_radius, "lowest_finger_z_m": bottom, "required_height_margin_m": 0.020, "height_measurement_allowance_m": 0.005, "scope": "Open fingers, high alignment and downward-tool world-yaw rotation only; no descent."}
    geometry["next_approach_envelope"] = envelope
    cf = {"coverage": ["complete", "occluded", "obstructed", "unknown", "too_many"], "robot_clear": ["visible_clear", "obstructed", "unknown"], "count": {"type": "integer", "minimum": 0, "maximum": 4}}
    cf.update({"high" + str(i): selector for i in range(4)})
    for attempt in range(2):
        rr = api.review("Check only the supplied conservative high-alignment finger envelope in BOTH current views. Identify each distinct scene object/surface whose XY footprint overlaps it, including the bowl and bottle if relevant. Return high0..high(count-1) pixel selectors on their actual highest visible points. Samples are upper extrema only if the entire relevant upper silhouette supports that interpretation; an arbitrary surface sample is not a height bound. At most four objects; otherwise too_many. Coverage complete requires all relevant surfaces and their upper extrema observable, not extrapolated through occlusion. Set robot_clear=visible_clear only if the images additionally support unobstructed motion of the visible hand/palm along this short high path. Do not certify hidden arm clearance or clearance for descent. If high volume is occupied use obstructed. Unused selectors must have visible=false. A retry must use a genuinely different visible sample addressing the previous error, or report unknown.", context={"envelope": envelope, "bowl_and_table": geometry, "previous_gaps": logs[-1:]}, fields=cf)
        cp = rr["parameters"]
        needed = ["high" + str(i) for i in range(cp["count"])]
        hp, he = measure(rr, needed)
        save("observe.clearance" + str(attempt), {"frame_id": rr["frame_id"], "interpretation": cp, "points": hp, "measurement_errors": he, "envelope": envelope})
        if rr["status"] == "stop":
            return finish("blocked", "Clearance observation stopped: " + rr["explanation"])
        if cp["coverage"] == "obstructed" or cp["robot_clear"] == "obstructed":
            return finish("needs_replan", "Fresh observations show an obstruction of the proposed high alignment approach.")
        ready = cp["coverage"] == "complete" and cp["robot_clear"] == "visible_clear" and cp["count"] > 0 and not he and all(n in hp for n in needed)
        clearance = float(bottom - max(hp[n]["world_m"][2] for n in needed) - 0.005) if ready else None
        logs.append({"clearance_attempt": attempt, "coverage": cp["coverage"], "robot_clear": cp["robot_clear"], "measurement_errors": he, "available_height_margin_m": clearance})
        if ready and clearance < 0.020:
            return finish("needs_replan", "Measured high-approach height clearance fails the fixed 20 mm margin; inspect the saved extrema and envelope.")
        if ready and clearance >= 0.020:
            geometry["next_approach_envelope"]["measured_height_margin_m"] = clearance
            geometry["next_approach_envelope"]["extrema_checkpoint"] = "observe.clearance" + str(attempt)
            end = api.state()
            if end["native_steps"] != start["native_steps"] or end["frame_id"] != start["frame_id"]:
                return finish("needs_replan", "The observation-only reference frame changed; revalidate all dependent geometry.")
            return finish("stage_complete", "Fresh visible RGB-D establishes a measured rim-pinch region, a vacant tabletop patch enclosing the conservative bowl mouth footprint with margin, and observed clearance for high open-hand alignment only.")
    return finish("blocked", "Two bounded clearance observations did not establish the next high approach; no motion was authorized.")

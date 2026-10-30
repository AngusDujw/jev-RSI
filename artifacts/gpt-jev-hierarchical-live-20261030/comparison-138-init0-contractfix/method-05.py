def main(api):
    start = api.state()
    evidence = {"stage": "resolve", "entry_state": start, "physical_commands": 0, "retention_established": False, "reviews_used": 0}
    written = []
    allowance = 0.003
    questions = {}
    for axis in ["x", "y", "z", "rx", "ry", "rz"]:
        questions[axis] = {"type": "choice", "instructions": "This observation-only resolve stage authorizes no motion. Select hold for this world axis. A residual is not motion authorization.", "criteria": {"negative": "Decrease this world coordinate or rotation component; not authorized here.", "hold": "Do not change this component.", "positive": "Increase this world coordinate or rotation component; not authorized here."}}
    questions["gripper"] = {"type": "choice", "instructions": "Preserve the actual gripper state. No opening, closing, or grasp retry is authorized in resolve.", "criteria": {"open": "Request opening; not authorized here.", "close": "Request closure; not authorized here.", "keep": "Preserve the delivered gripper command."}}
    evidence["control_policy"] = {"question_keys": list(questions), "motion_authorized": False, "jev_calls": 0, "native_step_limit": 0}
    def save(key, value):
        api.checkpoint(key, value)
        if key not in written:
            written.append(key)
    def finish(status, reason):
        evidence["end_state"] = api.state()
        save("resolve.result", evidence)
        return {"stage_status": status, "reason": reason, "evidence": evidence, "handoff": {"checkpoint_keys": list(written), "frames": "World meters; xyzw tool-to-world quaternions. Tool points use (world - measured TCP) times the tool-to-world matrix. Every depth retains its camera and frame.", "provenance": "resolve.contact0 and optional contact1 contain fresh observations and partial measurements. resolve.clearance contains the separate envelope review. resolve.result contains computations, assumptions, gaps and actual states. Earlier lift and observe checkpoints remain unchanged historical records.", "scope": "Feasibility evidence only, not a grasp, retention, dynamics guarantee, or cabinet placement assessment. No action, gripper change, old turn, or recentering was executed. Start from end_state, not the old anchor.", "dependencies": "Revalidate opening and finger identity after any gripper change, and affected bowl/clearance references after motion. Joint spread is reported proprioception, not a calibrated aperture formula. The observed medial extrema bound fingers only if both complete inward boundaries were visible. A fitted inclined patch is not extrapolated beyond its measured footprint.", "next_requirement": "Use the saved exact gap if blocked. If geometry is ready but clearance is pending, obtain that missing review without repeating unchanged contact questions. Before any later physical approach, revalidate the route, use bounded Jev updates, and stop on reversed or stalled progress; no progress toward the old anchor is assumed."}, "completion_proposed": False}
    gap = {"names": []}
    def require(ok, reason, names):
        if not bool(ok):
            gap.update({"reason": reason, "names": list(names)})
            raise ValueError(reason)
    pos = ["p0", "p1", "p2", "p3"]
    neg = ["n0", "n1", "n2", "n3"]
    outer = ["o" + str(i) for i in range(8)]
    inner = ["i" + str(i) for i in range(6)]
    wall = ["wi0", "wo0", "wi1", "wo1"]
    names = pos + neg + ["mp", "mn"] + outer + inner + wall
    points = {}
    fields = {"bowl": ["same_upright_supported", "changed_or_not_supported", "unknown"], "faces": ["two_actual_inward_contact_patches", "partial_or_ambiguous"], "medial_boundary": ["both_complete_visible", "occluded_or_unknown"], "rim": ["same_two_circular_lips", "ambiguous"], "wall": ["one_visible_contiguous_rim_sector", "ambiguous"], "hand": ["open_and_clear", "contact_or_possibly_holding", "unknown"], "alternative": ["different_visible_samples", "none"]}
    request = "Evidence-only feasibility inspection from the ACTUAL current pose. Request ZERO regions. Use both current cameras, not old screen identities. Request only the named points listed in context.request_names; omit genuinely unavailable points. p0..p3 and n0..n3: four separated interior samples around each of TWO distinct opposing inward lower contact patches, positive/negative tool-y respectively. Select actual contact material, not outer backs, rounded tips, chamfers mistaken for pads, or silhouettes. The patch may be inclined: do not force constant tool-y. Samples must span tool-x and tool-z. mp is the most medial positive-y finger surface point, mn the most medial negative-y finger surface point. both_complete_visible means the ENTIRE relevant inward boundaries, including tips, are visible across the two views so no more-medial protrusion is hidden; otherwise report occluded_or_unknown. o0..o7 sample the bowl OUTER lip around the full circumference; i0..i5 sample its INNER lip around the full circumference. These are distinct actual surface depths, not estimated circles. wi0/wo0 and wi1/wo1 are paired inner/outer wall samples just below the rim at opposite tangential ends of ONE accessible visible sector, preferably the world +X sector if available; use the same two physical cross-sections, with the wall band between them visible. Do not sample across the mouth. Assess the same patterned bowl's support and the actual hand state. alternative=different_visible_samples only if a different currently visible patch or camera can resolve missing or inconsistent samples without motion. Do not infer hidden geometry or certify a route in this review."
    R = geo.rotation(start["tcp_quaternion_xyzw"])
    tcp = np.asarray(start["tcp_position_world_m"], dtype=float)
    own = start["own_geometry"]
    lo = np.asarray(own["finger_low_offset_tool_m"], dtype=float)
    hi = np.asarray(own["finger_high_offset_tool_m"], dtype=float)
    cameras = {}
    def vectors(group):
        require(all(n in points for n in group), "Missing successful depth samples: " + str([n for n in group if n not in points]), group)
        a = np.asarray([points[n]["world_m"] for n in group], dtype=float)
        require(a.shape == (len(group), 3) and np.all(np.isfinite(a)), "Invalid world measurements.", group)
        return a
    def fit_lip(group):
        a = vectors(group)
        pl, ci = geo.plane(a), geo.circle_xy(a)
        cf = np.asarray(pl["coefficients"], dtype=float)
        require(float(pl["rms_m"]) <= 0.0015 and cf[2] >= 0.99875, "Lip is not an adequately horizontal measured plane.", group)
        limit = 1.35 if len(group) == 8 else 1.8
        require(float(ci["max_radial_error_m"]) <= 0.002 and float(ci["largest_angular_gap_rad"]) <= limit, "Circular boundary fit or angular coverage failed.", group)
        return {"center_xy_m": np.asarray(ci["center_xy_m"]).tolist(), "radius_m": float(ci["radius_m"]), "rms_m": float(ci["rms_m"]), "max_radial_error_m": float(ci["max_radial_error_m"]), "largest_angular_gap_rad": float(ci["largest_angular_gap_rad"]), "plane": cf.tolist(), "plane_rms_m": float(pl["rms_m"]), "mean_z_m": float(np.mean(a[:, 2]))}
    def analyze(params):
        for n in names:
            require(n in points, "Missing depth for " + n, [n])
            p = points[n]
            require(p["frame_id"] == start["frame_id"], "Stale measurement for " + n, [n])
            cam = p["camera"]
            if cam not in cameras:
                cameras[cam] = api.camera(cam)
            cal = cameras[cam]
            require(cal["frame_id"] == start["frame_id"], "Camera calibration frame changed.", [n])
            c = geo.transform(np.asarray([p["world_m"]]), np.linalg.inv(np.asarray(cal["camera_to_world_opencv"])))[0]
            require(np.all(np.isfinite(c)) and c[2] > 0 and p["depth_m"] > 0, "Invalid calibrated camera depth.", [n])
            uvw = np.asarray(cal["K"]) @ c
            require(np.linalg.norm(uvw[:2] / uvw[2] - np.asarray(p["pixel"])) <= 4.0, "World/camera reprojection inconsistency.", [n])
        require(params["faces"] == "two_actual_inward_contact_patches", "Two identified opposing contact patches are not available; one face cannot establish aperture.", pos + neg)
        models, polygons, tools = [], [], []
        for group, sign in [(pos, 1), (neg, -1)]:
            a = (vectors(group) - tcp) @ R
            tools.append(a)
            require(np.all(a >= lo - allowance) and np.all(a <= hi + allowance) and np.all(sign * a[:, 1] > allowance), "Patch identity disagrees with measured own-finger bounds or side.", group)
            f = geo.plane(a)
            co = np.asarray(f["coefficients"], dtype=float)
            require(abs(co[1]) >= 0.75 and float(f["rms_m"]) <= 0.0015 and np.max(np.abs(a @ co[:3] + co[3])) <= allowance, "A locally planar inward contact patch is not supported; do not flatten a curved or misidentified surface.", group)
            xz = a[:, [0, 2]]
            center = np.mean(xz, axis=0)
            poly = xz[np.argsort(np.arctan2(xz[:, 1] - center[1], xz[:, 0] - center[0]))]
            for j in range(4):
                edge = poly[(j + 1) % 4] - poly[j]
                d = poly - poly[j]
                require(np.linalg.norm(edge) > 0.001 and np.min(edge[0] * d[:, 1] - edge[1] * d[:, 0]) >= -1e-10, "Patch samples do not bound a convex observed footprint.", group)
            polygons.append(poly)
            models.append({"coefficients_tool": co.tolist(), "rms_m": float(f["rms_m"]), "sample_points_tool_m": a.tolist()})
        best, contact_xz = -1.0, None
        lower = np.maximum(np.min(polygons[0], axis=0), np.min(polygons[1], axis=0))
        upper = np.minimum(np.max(polygons[0], axis=0), np.max(polygons[1], axis=0))
        for x in np.linspace(lower[0], upper[0], 9):
            for z in np.linspace(lower[1], upper[1], 9):
                c, ds = np.asarray([x, z]), []
                for poly in polygons:
                    for j in range(4):
                        e = poly[(j + 1) % 4] - poly[j]
                        d = c - poly[j]
                        ds.append(float((e[0] * d[1] - e[1] * d[0]) / np.linalg.norm(e)))
                if min(ds) > best:
                    best, contact_xz = min(ds), c
        evidence["contact_patch_models"] = models
        evidence["common_patch_interior_margin_m"] = float(best)
        require(best >= allowance, "No common contact cross-section lies 3 mm inside both measured patch footprints.", pos + neg)
        ys = []
        for m in models:
            co = np.asarray(m["coefficients_tool"])
            ys.append(float(-(co[0] * contact_xz[0] + co[2] * contact_xz[1] + co[3]) / co[1]))
        gap_error = sum(allowance / abs(m["coefficients_tool"][1]) for m in models)
        opening = ys[0] - ys[1]
        require(params["rim"] == "same_two_circular_lips", "Inner and outer lip identities are not resolved.", outer + inner)
        oc, ic = fit_lip(outer), fit_lip(inner)
        evidence["bowl_lips"] = {"outer": oc, "inner": ic, "allowance_m": allowance}
        center = np.asarray(oc["center_xy_m"])
        require(np.linalg.norm(center - np.asarray(ic["center_xy_m"])) <= 0.004 and 0.02 < ic["radius_m"] < oc["radius_m"] < 0.15, "Inner/outer lip fits are inconsistent.", outer + inner)
        require(params["wall"] == "one_visible_contiguous_rim_sector", "A visible same-wall pinch sector is missing.", wall)
        w = vectors(wall)
        grasp = np.mean(w, axis=0)
        radial = grasp[:2] - center
        distance = float(np.linalg.norm(radial))
        require(ic["radius_m"] - allowance <= distance <= oc["radius_m"] + allowance, "Wall samples do not belong to the measured rim sector.", wall)
        radial = radial / distance
        tangent = np.asarray([-radial[1], radial[0]])
        th = [float(np.dot(w[j + 1, :2] - w[j, :2], radial)) for j in [0, 2]]
        span = abs(float(np.dot((w[2, :2] + w[3, :2] - w[0, :2] - w[1, :2]) / 2, tangent)))
        require(min(th) >= -allowance and max(th) <= 0.012 and max(abs(w[1, 2] - w[0, 2]), abs(w[3, 2] - w[2, 2])) <= 0.004, "Paired wall samples are geometrically inconsistent.", wall)
        require(span >= float(hi[0] - lo[0]) + 2 * allowance and 0.003 <= oc["mean_z_m"] - grasp[2] <= 0.025, "Insufficient measured tangential wall band or below-rim contact depth.", wall)
        wall_upper = max(0.0, max(th)) + 2 * allowance
        joint_spread = float(max(start["gripper_qpos_m"]) - min(start["gripper_qpos_m"]))
        require(opening - gap_error >= wall_upper + 0.010 and opening + gap_error <= float(own["pad_extent_in_tool_m"][1]) + 2 * allowance and joint_spread > wall_upper, "Observed opposed aperture, wall thickness, own pad extent, or reported opening is inconsistent.", pos + neg + wall)
        evidence["opening"] = {"observed_gap_m": opening, "allowance_m": gap_error, "reported_joint_spread_m": joint_spread, "wall_thickness_upper_m": wall_upper, "joint_spread_is_not_aperture": True}
        require(params["medial_boundary"] == "both_complete_visible", "Full inward finger boundaries are occluded; patch fits alone cannot bound hidden medial protrusions.", ["mp", "mn"])
        medial = (vectors(["mp", "mn"]) - tcp) @ R
        require(np.all(medial >= lo - allowance) and np.all(medial <= hi + allowance), "Medial extrema disagree with own geometry.", ["mp", "mn"])
        yp, yn = float(medial[0, 1] - allowance), float(medial[1, 1] + allowance)
        require(yp > 0 and yn < 0 and np.min(tools[0][:, 1]) >= yp and np.max(tools[1][:, 1]) <= yn, "Medial extrema do not consistently bound the two fingers.", ["mp", "mn"])
        phi = 0.5 * math.atan2(float(radial[0]), float(-radial[1]))
        quat = [math.cos(phi), math.sin(phi), 0.0, 0.0]
        Rd = geo.rotation(quat)
        local = np.asarray([contact_xz[0], sum(ys) / 2, contact_xz[1]])
        goal_tcp = grasp - Rd @ local
        require(0.03 < tcp[2] - goal_tcp[2] < 0.40 and np.linalg.norm(goal_tcp - tcp) < 0.6, "Candidate approach is outside the local feasible geometry.", wall)
        paths = {}
        for label, low, high in [("outside", np.asarray([lo[0] - allowance, yp, lo[2] - allowance]), hi + allowance), ("inside", lo - allowance, np.asarray([hi[0] + allowance, yn, hi[2] + allowance]))]:
            corners = np.asarray([[x, y, z] for x in [low[0], high[0]] for y in [low[1], high[1]] for z in [low[2], high[2]]])
            world = corners @ Rd.T + goal_tcp
            poly = np.asarray([[low[0], low[1], 0], [high[0], low[1], 0], [high[0], high[1], 0], [low[0], high[1], 0]]) @ Rd.T + goal_tcp
            paths[label] = {"polygon_xy_m": poly[:, :2].tolist(), "lowest_finger_z_m": float(np.min(world[:, 2])), "xy_tracking_reserve_m": 0.005}
            if label == "inside":
                margin = ic["radius_m"] - allowance - float(np.max(np.linalg.norm(poly[:, :2] - np.asarray(ic["center_xy_m"]), axis=1))) - 0.005
            else:
                ds = []
                for j in range(4):
                    a, b = poly[j, :2] - center, poly[(j + 1) % 4, :2] - center
                    d = b - a
                    t = min(1.0, max(0.0, float(-np.dot(a, d) / np.dot(d, d))))
                    ds.append(float(np.linalg.norm(a + t * d)))
                margin = min(ds) - oc["radius_m"] - allowance - 0.005
            paths[label]["radial_margin_m"] = float(margin)
            require(margin >= 0.005, "Open finger footprint fails the measured lip clearance margin: " + label, ["mp", "mn"] + outer + inner)
        radius = float(np.linalg.norm(np.maximum(np.abs(lo), np.abs(hi)))) + allowance + 0.015
        high = {"xy_min_m": (np.minimum(tcp[:2], goal_tcp[:2]) - radius).tolist(), "xy_max_m": (np.maximum(tcp[:2], goal_tcp[:2]) + radius).tolist(), "lowest_finger_z_m": float(tcp[2] - radius), "required_height_margin_m": 0.020, "pose_reserve_m": 0.015}
        model = {"frame_id": start["frame_id"], "candidate_contact_world_m": grasp.tolist(), "contact_cross_section_tool_m": local.tolist(), "candidate_tcp_world_m": goal_tcp.tolist(), "candidate_quaternion_xyzw": quat, "observed_medial_extrema_tool_m": medial.tolist(), "open_vertical_paths": paths, "high_rotation_and_alignment": high, "height_measurement_allowance_m": 0.005, "lower_path_tracking_reserve_m": 0.005, "required_lower_height_margin_m": 0.010, "scope": "Nominal high orientation/alignment then open vertical approach geometry only. Reserves are engineering allowances, not certified dynamics bounds. No closure path, force stability, or retained lift is certified."}
        evidence["geometry"] = model
        return model
    try:
        if start["budgets"]["gpt_remaining"] < 1:
            return finish("yield", "No review budget is available; fresh grasp evidence remains necessary.")
        targets = list(names)
        for attempt in range(2):
            if api.state()["budgets"]["gpt_remaining"] < 1:
                return finish("yield", "Partial contact measurements saved; the specified different measurement still needs review budget.")
            r = api.review(request + (" This is a bounded replacement: use a DIFFERENT visible patch or complementary camera for the listed failed samples, not the same pixels or the old constant-y assumption." if attempt else ""), context={"request_names": targets, "state": start, "previous_gap": gap, "prior_stop": "At frame 120 the old recenter moved away from its anchor; the old single-face constant-y check failed. Neither is reused as authorization."}, fields=fields)
            evidence["reviews_used"] += 1
            save("resolve.contact" + str(attempt), {"frame_id": r["frame_id"], "parameters": r["parameters"], "points": r["points"], "measurement_errors": r["measurement_errors"], "explanation": r["explanation"]})
            if r["status"] == "stop":
                return finish("abort", "Fresh observation requested stop: " + r["explanation"])
            require(r["frame_id"] == start["frame_id"] and api.state()["frame_id"] == start["frame_id"], "Scene advanced during this measurement-only stage; references need reacquisition.", targets)
            for n in targets:
                if n in points:
                    points.pop(n)
            bad = set(e["name"] for e in r["measurement_errors"])
            for n in r["points"]:
                if n in names and n not in bad:
                    points[n] = r["points"][n]
            p = r["parameters"]
            if p["bowl"] == "changed_or_not_supported" or p["hand"] == "contact_or_possibly_holding":
                return finish("needs_replan", "Fresh support or hand evidence contradicts an undisturbed, unheld bowl.")
            try:
                require(p["bowl"] == "same_upright_supported" and p["hand"] == "open_and_clear", "Bowl support or empty open hand is ambiguous.", targets)
                model = analyze(p)
                break
            except Exception as err:
                evidence["gap"] = {"reason": str(err), "names": list(gap["names"]), "measurement_errors": r["measurement_errors"]}
                if attempt or p["alternative"] != "different_visible_samples":
                    return finish("blocked", str(err))
                targets = list(gap["names"]) if gap["names"] else list(names)
        if evidence["reviews_used"] >= 2 or api.state()["budgets"]["gpt_remaining"] < 1:
            return finish("yield", "Contact and opening model is saved, but its computed approach envelopes still require a fresh coverage/height review.")
        cfields = {"bowl": ["same_upright_supported", "changed", "unknown"], "high_coverage": ["complete_visible_height_bound", "occluded_or_unknown"], "inside_coverage": ["complete_visible_height_bound", "occluded_or_unknown"], "outside_coverage": ["complete_visible_height_bound", "occluded_or_unknown"], "local_bowl_wall": ["relevant_wall_within_measured_outer_lip", "unbounded_or_occluded"], "proximal_robot": ["proposed_visible_hand_wrist_sweeps_clear", "collision_or_unknown"]}
        cr = api.review("Request ZERO regions. Assess ONLY the supplied computed geometric envelopes from the actual pose, not the old anchor. For each group high, inside, outside request two named real surface depth points high0/high1, inside0/inside1, outside0/outside1 at the highest relevant surfaces under that entire XY footprint, including its tracking reserve. Inside means the bowl interior under the negative-y finger, not an assumed hidden flat floor. Outside includes the bowl exterior, plate and any counter obstacles under the positive-y finger. High covers the full XY box for elevated finger rotation and alignment. Coverage is complete only if both current images reveal all relevant potentially higher surfaces; sparse maxima samples alone cannot certify coverage. If no visible supporting surface or any hidden higher surface could matter, report unknown instead of inventing a point. Verify the relevant outer bowl wall is bounded by the measured lip in the outside corridor. Separately inspect the proposed visible proximal hand/wrist sweep for high orientation/alignment and the vertical descent; the finger bounding box is not a full-arm model. Do not claim hidden robot clearance. Confirm the bowl is still upright supported and undisturbed.", context={"geometry": model, "actual_state": start, "bowl_lips": evidence["bowl_lips"], "no_actions_executed": True}, fields=cfields)
        evidence["reviews_used"] += 1
        save("resolve.clearance", {"frame_id": cr["frame_id"], "parameters": cr["parameters"], "points": cr["points"], "measurement_errors": cr["measurement_errors"], "explanation": cr["explanation"]})
        if cr["status"] == "stop":
            return finish("abort", "Clearance review requested stop: " + cr["explanation"])
        if cr["parameters"]["bowl"] == "changed":
            return finish("needs_replan", "The fresh clearance review reports bowl disturbance.")
        require(cr["frame_id"] == start["frame_id"] and api.state()["frame_id"] == start["frame_id"], "Clearance is not in the contact measurement frame.", [])
        cp, bad = cr["parameters"], set(e["name"] for e in cr["measurement_errors"])
        require(cp["bowl"] == "same_upright_supported" and cp["proximal_robot"] == "proposed_visible_hand_wrist_sweeps_clear" and cp["local_bowl_wall"] == "relevant_wall_within_measured_outer_lip", "Support, local wall containment, or proximal robot approach clearance is unresolved.", [])
        margins = {}
        for label in ["high", "inside", "outside"]:
            ns = [label + "0", label + "1"]
            require(cp[label + "_coverage"] == "complete_visible_height_bound", "Occluded or incomplete " + label + " approach coverage.", ns)
            require(all(n in cr["points"] and n not in bad for n in ns), "Missing valid approach height samples: " + label, ns)
            a = np.asarray([cr["points"][n]["world_m"] for n in ns], dtype=float)
            require(np.all(np.isfinite(a)) and all(cr["points"][n]["frame_id"] == start["frame_id"] for n in ns), "Invalid or stale clearance depths.", ns)
            floor = model["high_rotation_and_alignment"]["lowest_finger_z_m"] if label == "high" else model["open_vertical_paths"][label]["lowest_finger_z_m"] - model["lower_path_tracking_reserve_m"]
            required = 0.020 if label == "high" else 0.010
            margin = float(floor - np.max(a[:, 2]) - model["height_measurement_allowance_m"])
            margins[label] = {"available_height_margin_m": margin, "required_m": required, "highest_observed_z_m": float(np.max(a[:, 2]))}
            evidence["clearance_margins"] = margins
            require(margin >= required, "Measured " + label + " approach height margin failed; no tolerance relaxation is permitted.", ns)
        evidence["effect"] = {"fresh_frame_id": cr["frame_id"], "bowl_undisturbed": True, "opposed_opening_measured": True, "approach_geometry_reviewed": True, "motion_executed": False, "scope": "Current resolve-stage evidence only; later physical execution and retention are untested."}
        return finish("stage_complete", "Fresh opposing contact patches, observed medial bounds, bowl rim geometry and separately reviewed approach heights consistently support a local rim-grasp approach; the bowl remains undisturbed.")
    except Exception as err:
        evidence["gap"] = {"reason": str(err), "names": list(gap["names"]), "preserved_partial_checkpoints": list(written)}
        return finish("blocked", "Resolve evidence remains incomplete: " + str(err))

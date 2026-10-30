def main(api):
    gr, hr = api.recall("place.geometry"), api.recall("place.progress")
    G, H = gr["value"], hr["value"]
    entry = api.state()
    E = {"stage": "restage", "entry": entry, "actions": [], "retention": [], "reviews": 0, "release_started": False,
         "retired_pending": H.get("pending"), "acknowledged_since_old_checkpoint_steps": entry["native_steps"] - H["actions"][-1]["after"]["native_steps"],
         "strategy": "Translate with actual attitude to the central bowl workspace before considering one object-centered attitude change."}
    F = {"historical_keys": ["place.geometry", "place.progress", "secure.geometry"], "historical_geometry_frame": G["current_carton"]["frame_id"],
         "dimensions_m": [G["length_m"], G["width_m"], G["thickness_upper_m"]], "extent_uncertainty_m": G["historical_extent_u_m"],
         "corner_ids": G["corner_ids"], "end_identity_reference": G["end_identity_reference"]}
    F["source_records"] = [{k: r[k] for k in ["key", "frame_id", "method_number", "source_sha256"]} for r in [gr, hr]]
    F["uncertainty_scope"] = "The 0.4 mm measurement floor is a conservative operational floor, not calibrated confidence. Historical carton dimensions bound unseen extent; current short-edge width, plane residual, feature spread and identities revalidate their use."
    def plain(x):
        if isinstance(x, np.ndarray):
            return x.tolist()
        if isinstance(x, np.generic):
            return x.item()
        if isinstance(x, dict):
            return {k: plain(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [plain(v) for v in x]
        return x
    def brief(s):
        return {k: s[k] for k in ["frame_id", "native_steps", "tcp_position_world_m", "tcp_quaternion_xyzw", "gripper_qpos_m", "last_gripper_command"]}
    Q = {}
    for a in ["x", "y", "z", "rx", "ry", "rz"]:
        Q[a] = {"type": "choice", "instructions": "For world axis " + a + ", use state.processed_features.axes." + a + ".goal_relation: increase means positive, decrease means negative, within_tolerance means hold. Follow measured hand residuals, not an imagined object pose.",
                "criteria": {"negative": "Decrease this world coordinate or world rotation-vector component.", "hold": "This axis is within its supplied deadband.", "positive": "Increase this world coordinate or world rotation-vector component."}}
    Q["gripper"] = {"type": "choice", "instructions": "Read state.processed_features.objective.gripper and deliver that command unchanged. This stage requests close throughout, never release; closure is not retention evidence.",
                    "criteria": {"open": "Objective requests opening.", "close": "Objective requests continued closure.", "keep": "Objective requests preserving the previous command."}}
    pt, rt, margin = 0.0015, 0.015, 0.0035
    def save():
        api.checkpoint("restage.reference", F)
        api.checkpoint("restage.progress", E)
    def finish(status, reason):
        E["actual_state"] = api.state()
        E["reason"] = reason
        save()
        return {"stage_status": status, "reason": reason, "evidence": E, "completion_proposed": False,
                "handoff": {"checkpoint_keys": ["restage.reference", "restage.progress", "place.geometry", "place.progress"],
                            "provenance": "restage.reference holds current RGB-D models and original dimension/identity provenance. restage.progress holds actual state, pending commands, receipts and differential tests. Old place targets are retired, not replayable.",
                            "frames": "World metres, active tool-to-world xyzw quaternions; each model has its observation frame. Projected boxes are historical dimension envelopes attached to currently measured faces, not observations of hidden faces.",
                            "actual_state": E["actual_state"], "placement_option": E.get("placement_option"),
                            "release_authorized": False,
                            "assumptions": ["No opening or release in this stage.", "Revalidate retention, opening fit and jaw corridor before placement.", "The proposed release option is above-rim opening, not finger insertion or a hidden-clearance certificate."]}}
    pixel = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}
    fields = {"identity": ["same_carton", "lost_or_changed", "unknown"], "patch": ["same_printed_face", "unknown"],
              "end_ids_match": "boolean", "end_camera": ["agentview", "robot0_eye_in_hand"],
              "end_pixels": {"type": "array", "items": pixel, "maxItems": 2},
              "bowl": ["same_upright", "moved_or_tipped", "unknown"], "bowl_mode": ["rim", "landmarks", "unknown"],
              "rim_camera": ["agentview", "robot0_eye_in_hand"], "rim_pixels": {"type": "array", "items": pixel, "maxItems": 8},
              "closed_route": ["clear", "obstructed", "unknown"], "opening_corridor": ["clear", "obstructed", "unknown"], "notes": "string"}
    def valid_points(r):
        bad = set(x["name"] for x in r["measurement_errors"])
        return {k: v for k, v in r["points"].items() if k not in bad and v["frame_id"] == r["frame_id"]}
    def rays(camera, pixels, plane, xy=False):
        out, u = [], 0.0
        for p in pixels:
            x = np.array(api.plane_point(camera, p, plane)["world_m"])
            out.append(x.tolist())
            for d in [[1, 0], [-1, 0], [0, 1], [0, -1]]:
                pp = [p[0] + d[0], p[1] + d[1]]
                if min(pp) < 0 or max(pp) > 767:
                    raise ValueError("Boundary uncertainty rays leave the image.")
                y = np.array(api.plane_point(camera, pp, plane)["world_m"])
                u = max(u, float(np.linalg.norm((y-x)[:2] if xy else y-x)))
        return np.array(out), u
    def geometry(r, base):
        p, v = r["parameters"], valid_points(r)
        if p["identity"] != "same_carton" or p["patch"] != "same_printed_face" or not p["end_ids_match"] or len(p["end_pixels"]) != 2:
            raise ValueError("Current printed-face identity or physical end-corner identity unavailable.")
        names = [k for k in ["p0", "p1", "p2", "p3", "p4", "p5"] if k in v]
        if len(names) < 4:
            raise ValueError("Fewer than four valid current same-face samples: " + str(r["measurement_errors"]))
        plane = plain(geo.plane([v[k]["world_m"] for k in names]))
        noise = max(0.0004, 3.0 * plane["rms_m"])
        spread = min(plane["in_plane_spread_m"])
        if plane["rms_m"] > 0.0008 or spread < 8.0 * noise:
            raise ValueError("Face coverage cannot resolve its normal relative to residual/noise: " + str(plane))
        A, pixu = rays(p["end_camera"], p["end_pixels"], plane["coefficients"])
        edgeu = max(0.0004, pixu + plane["rms_m"])
        n = np.array(plane["coefficients"][:3])
        w = A[1] - A[0]
        width = float(np.linalg.norm(w))
        if abs(width - G["width_m"]) > 2.0 * (G["historical_extent_u_m"] + edgeu):
            raise ValueError("Fresh visible short-edge width disagrees with preserved carton dimensions.")
        w = w / width
        long = np.cross(w, n)
        long = long / np.linalg.norm(long)
        L, t = G["length_m"], G["thickness_upper_m"]
        top = np.array([A[0], A[1], A[1] + L*long, A[0] + L*long])
        box = np.concatenate([top, top - t*n])
        nu = noise / spread
        u = G["historical_extent_u_m"] + edgeu + (L+t)*nu + 2.0*edgeu*L/width
        C = {"frame_id": r["frame_id"], "anchors_world_m": A.tolist(), "normal_world": n.tolist(), "short_axis_world": w.tolist(),
             "box_world_m": box.tolist(), "u_m": float(u), "edge_u_m": edgeu, "normal_u_rad": float(nu), "plane": plane}
        if p["bowl"] != "same_upright":
            raise ValueError("Bowl identity/upright stationarity is not established.")
        if p["bowl_mode"] == "unknown":
            raise ValueError("No supported current bowl-opening validation mode.")
        marks = {k: v[k] for k in ["b0", "b1"] if k in v}
        if p["bowl_mode"] == "rim":
            dn = [k for k in ["d0", "d1", "d2", "d3"] if k in v]
            if len(dn) < 3 or len(p["rim_pixels"]) != 8:
                raise ValueError("Fresh opening requires at least three depth-valid lip samples and eight identified inner-boundary pixels.")
            bp = plain(geo.plane([v[k]["world_m"] for k in dn]))
            if bp["coefficients"][2] < 0.985 or bp["rms_m"] > 0.001 or min(bp["in_plane_spread_m"]) < 8*max(0.0004, 3*bp["rms_m"]):
                raise ValueError("Lip measurements do not support a sufficiently horizontal opening plane.")
            rim, ru = rays(p["rim_camera"], p["rim_pixels"], bp["coefficients"], True)
            circle = plain(geo.circle_xy(rim))
            if circle["largest_angular_gap_rad"] > 1.4 or circle["max_radial_error_m"] > 0.0025 or circle["rms_m"] > 0.0013:
                raise ValueError("Inner opening circle lacks coverage or adequate residual: " + str(circle))
            bu = circle["max_radial_error_m"] + ru + 2*bp["rms_m"] + 0.0004
            B = {"frame_id": r["frame_id"], "center_xy_m": circle["center_xy_m"], "radius_m": circle["radius_m"], "u_m": bu,
                 "base_u_m": bu, "rim_high_m": float(max(rim[:, 2])), "rim_world_m": rim.tolist(), "plane": bp, "circle": circle, "marks": marks}
            if base is not None and (np.linalg.norm(np.array(B["center_xy_m"])-base["center_xy_m"]) > 0.004 or abs(B["radius_m"]-base["radius_m"]) > 0.004):
                raise ValueError("Fresh bowl fit differs materially from the pre-transfer opening.")
        else:
            if base is None:
                raise ValueError("Initial fresh bowl opening measurements are required; historical fit alone is not authorization.")
            common = [k for k in marks if k in base["marks"]]
            if not common:
                raise ValueError("No current independently identified bowl mark survives; request a fresh rim measurement instead.")
            delta = max(float(np.linalg.norm(np.array(marks[k]["world_m"])-base["marks"][k]["world_m"])) for k in common)
            if delta > 0.002:
                raise ValueError("Bowl stationarity discrepancy exceeds 2 mm: " + str(delta))
            B = dict(base)
            B.update({"frame_id": r["frame_id"], "u_m": base["base_u_m"] + delta + 0.0004, "stationarity_marks": marks, "stationarity_discrepancy_m": delta})
        F["current_valid_measurements"] = v
        return C, B
    def sense(label, base=None):
        gap = ""
        for attempt in range(2):
            if E["reviews"] >= 4:
                E["measurement_gap"] = gap + " Observation allowance exhausted."
                return None
            question = ("Restage only; no release. Identify the SAME cream-cheese carton printed face and the two physical Cream/C short-end corners c0/c1 using supplied identities, NOT stationary projections. "
                        "Return end_pixels in physical c0,c1 order and end_camera. Request p0..p5 as six spread-out actual depth samples wholly on that face, away from seams/fingers; these are plane samples, not correspondences. "
                        "Identify b0, the bowl interior large pale floor medallion center, and b1, the separate bottle-side rear inner-wall rosette. Request their depth only if unambiguous. "
                        "Initially use bowl_mode rim: request d0..d3 as spread-out valid upper-lip surface depths and select eight well-distributed INNER opening boundary rim_pixels in rim_camera. Do not sample the sloping interior as the lip plane. "
                        "After motion, same upright bowl plus current known marks can validate the existing opening; if marks are obscured, substitute a fresh rim measurement instead of repeating obscured marks. "
                        "Assess the visible closed-assembly route: initial vertical rise of 20 to 60 mm followed by fixed-attitude translation over the bowl; at the raised approach assess one additional tilt of at most 0.32 rad. "
                        "opening_corridor asks whether fingers and outward jaw corridors of 20 mm per side are visibly free above the rim and away from the bottle/other bodies, including a short upward withdrawal corridor, not whether release has succeeded. "
                        "Do not infer hidden clearance or hidden carton corners. Unknown is allowed. Current observation purpose: " + label)
            if attempt:
                question += " Bounded replacement: use a DIFFERENT valid patch/camera or fresh rim rather than unchanged failed evidence. Previous exact gap: " + gap
            r = api.review(question, context={"reference": F, "bowl_reference": base, "actual_state": api.state()}, fields=fields)
            E["reviews"] += 1
            E["last_review"] = {"frame_id": r["frame_id"], "parameters": r["parameters"], "measurement_errors": r["measurement_errors"]}
            F["partial_valid_measurements"] = valid_points(r)
            save()
            if r["status"] == "stop" or r["parameters"]["identity"] == "lost_or_changed" or r["parameters"]["bowl"] == "moved_or_tipped":
                E["invalidated"] = "Review reports stop, changed retention, or displaced bowl."
                return None
            try:
                C, B = geometry(r, base)
                F["current_carton"], F["current_bowl"] = C, B
                save()
                return C, B, r["parameters"]
            except Exception as ex:
                gap = str(ex)
                E["measurement_gap"] = gap
        return None
    def rigid(s0, s1):
        R = geo.rotation(s1["tcp_quaternion_xyzw"]) @ geo.rotation(s0["tcp_quaternion_xyzw"]).T
        T = np.eye(4)
        T[:3, :3] = R
        T[:3, 3] = np.array(s1["tcp_position_world_m"]) - R @ np.array(s0["tcp_position_world_m"])
        return T
    def retention(c0, c1, s0, s1):
        T = rigid(s0, s1)
        predicted = geo.transform(c0["anchors_world_m"], T)
        signal = float(max(np.linalg.norm(predicted-np.array(c0["anchors_world_m"]), axis=1)))
        error = float(geo.attachment_error(c0["anchors_world_m"], c1["anchors_world_m"], s0, s1))
        normal_error = float(math.acos(float(np.clip(np.dot(T[:3, :3] @ np.array(c0["normal_world"]), c1["normal_world"]), -1, 1))))
        allowance = max(0.0036, 2*(c0["edge_u_m"]+c1["edge_u_m"])+0.0008)
        good = error <= allowance and normal_error <= c0["normal_u_rad"]+c1["normal_u_rad"] and signal > 2*allowance
        E["retention"].append({"before_frame": s0["frame_id"], "after_frame": s1["frame_id"], "attachment_error_m": error,
                               "allowance_m": allowance, "normal_error_rad": normal_error, "predicted_feature_motion_m": signal,
                               "actual_hand_translation_m": (np.array(s1["tcp_position_world_m"])-s0["tcp_position_world_m"]).tolist(), "supported": bool(good)})
        return good
    def fingers(s, opening=0.0):
        lo, hi = np.array(s["own_geometry"]["finger_low_offset_tool_m"]), np.array(s["own_geometry"]["finger_high_offset_tool_m"])
        lo[1] -= opening
        hi[1] += opening
        corners = [[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]]
        T = np.eye(4)
        T[:3, :3], T[:3, 3] = geo.rotation(s["tcp_quaternion_xyzw"]), s["tcp_position_world_m"]
        return geo.transform(corners, T)
    def move(label, target, quaternion, calls):
        before = api.state()
        E["pending"] = {"phase": label, "before": brief(before), "target_tcp_world_m": list(target), "quaternion_xyzw": list(quaternion), "gripper": "close"}
        save()
        r = api.drive(list(target), list(quaternion), "close", Q, features={"phase": label, "geometry_frame": F["current_carton"]["frame_id"],
                      "release_authorized": False, "carton_u_m": F["current_carton"]["u_m"], "required_fit_margin_m": margin,
                      "strategy": E["strategy"]}, max_calls=calls, tool_point="tcp", translation_limit=0.02, rotation_limit=0.05,
                      steps=3, position_tolerance=pt, rotation_tolerance=rt)
        after = api.state()
        initial_error = float(np.linalg.norm(np.array(target)-before["tcp_position_world_m"]))
        initial_angle = 2*math.acos(float(np.clip(abs(np.dot(quaternion, before["tcp_quaternion_xyzw"])), 0, 1)))
        E["actions"].append({"phase": label, "before": brief(before), "after": brief(after), "receipt": r,
                             "net_position_error_reduction_m": initial_error-r["position_error_m"],
                             "net_rotation_error_reduction_rad": initial_angle-r["rotation_error_rad"],
                             "actual_hand_translation_m": (np.array(after["tcp_position_world_m"])-before["tcp_position_world_m"]).tolist()})
        E["pending"] = None
        save()
        if r["status"] != "reached" or r["choices"]["gripper"] != "close" or after["last_gripper_command"] != "close":
            E["control_gap"] = "New staging command did not converge or gripper delivery mismatched; no retry of this objective."
            return None
        return after
    def fit(C, B, s):
        box = np.array(C["box_world_m"])
        lever = float(max(np.linalg.norm(box-np.array(s["tcp_position_world_m"]), axis=1)))
        return float(B["radius_m"]-max(np.linalg.norm(box[:, :2]-np.array(B["center_xy_m"]), axis=1))-C["u_m"]-B["u_m"]-pt-lever*rt)
    save()
    initial = sense("fresh pre-translation validation")
    if initial is None:
        return finish("needs_replan" if E.get("invalidated") else "blocked", E.get("invalidated", E.get("measurement_gap", "Missing current geometry.")))
    C0, B0, sem = initial
    S0 = api.state()
    oldS = H.get("objective_reference", {}).get("state", H["entry"])
    if oldS["frame_id"] != G["current_carton"]["frame_id"] or not retention(G["current_carton"], C0, oldS, S0):
        return finish("needs_replan", "Current differential retention does not support continuing the historical grasp.")
    F["baseline_carton"], F["baseline_bowl"], F["baseline_state"] = C0, B0, S0
    if sem["closed_route"] != "clear":
        return finish("blocked", "The materially different raised translation route lacks current visible clearance evidence.")
    box0 = np.array(C0["box_world_m"])
    rise = max(0.02, B0["rim_high_m"]+B0["u_m"]+C0["u_m"]+0.018-float(min(box0[:, 2])))
    if rise > 0.06:
        return finish("blocked", "Required preparatory rise exceeds the reviewed 60 mm local staging envelope.")
    up = np.array(S0["tcp_position_world_m"]) + [0, 0, rise]
    S1 = move("fixed_attitude_raise", up.tolist(), S0["tcp_quaternion_xyzw"], 12)
    if S1 is None:
        return finish("needs_replan", E["control_gap"])
    if np.linalg.norm(np.array(S1["tcp_position_world_m"])[:2]-np.array(S0["tcp_position_world_m"])[:2]) > 0.006:
        return finish("needs_replan", "Raise drift exceeded 6 mm; do not continue the transfer.")
    predicted = geo.transform(C0["box_world_m"], rigid(S0, S1))
    if min(predicted[:, 2])-C0["u_m"] < B0["rim_high_m"]+B0["u_m"]+0.012:
        return finish("blocked", "Actual raised hand pose does not preserve the above-rim transfer reserve.")
    target = np.array(S1["tcp_position_world_m"])
    target[:2] += np.array(B0["center_xy_m"])-np.mean(predicted[:, :2], axis=0)
    S2 = move("translate_to_central_bowl_workspace_without_tilt", target.tolist(), S1["tcp_quaternion_xyzw"], 28)
    if S2 is None:
        return finish("needs_replan", E["control_gap"])
    current = sense("verify actual translation, retention, and optional local attitude change at the NEW workspace", B0)
    if current is None:
        return finish("needs_replan" if E.get("invalidated") else "blocked", E.get("invalidated", E.get("measurement_gap", "Approach observation unavailable.")))
    C, B, sem = current
    S = api.state()
    if not retention(C0, C, S0, S):
        return finish("needs_replan", "Object motion does not agree with the actual whole-transfer hand motion.")
    E["fit_margin_m"] = fit(C, B, S)
    if E["fit_margin_m"] < margin:
        if E["reviews"] >= 4:
            return finish("blocked", "The current approach needs an attitude change, but no allocated fresh effect observation remains; no additional motion is authorized.")
        if sem["closed_route"] != "clear":
            return finish("blocked", "Approach reached, but the one alternate attitude sweep lacks visible clearance.")
        chosen = None
        E["candidate_tests"] = []
        for angle in [0.12, 0.22, 0.32]:
            q = api.compose(S["tcp_quaternion_xyzw"], (-angle*np.array(C["short_axis_world"])).tolist())
            dest = dict(S)
            dest["tcp_quaternion_xyzw"] = q
            rb = geo.transform(C["box_world_m"], rigid(S, dest))
            xyz = np.array(S["tcp_position_world_m"])
            xyz[:2] += np.array(B["center_xy_m"])-np.mean(rb[:, :2], axis=0)
            dest["tcp_position_world_m"] = xyz.tolist()
            pred = dict(C)
            pred["box_world_m"] = geo.transform(C["box_world_m"], rigid(S, dest)).tolist()
            fm = fit(pred, B, dest)
            sweep = 1.0
            for i in range(9):
                f = i/8.0
                ss = dict(S)
                ss["tcp_position_world_m"] = (np.array(S["tcp_position_world_m"])+f*(xyz-S["tcp_position_world_m"])).tolist()
                ss["tcp_quaternion_xyzw"] = api.compose(S["tcp_quaternion_xyzw"], (-f*angle*np.array(C["short_axis_world"])).tolist())
                bb = geo.transform(C["box_world_m"], rigid(S, ss))
                sweep = min(sweep, float(min(bb[:, 2]))-C["u_m"], float(min(fingers(ss)[:, 2])))
            lever = float(max(np.linalg.norm(np.array(C["box_world_m"])-S["tcp_position_world_m"], axis=1)))
            clearance = sweep-B["rim_high_m"]-B["u_m"]-lever*angle/16.0-0.004
            E["candidate_tests"].append({"additional_tilt_rad": angle, "fit_margin_m": fm, "sweep_vertical_reserve_m": clearance})
            if fm >= margin+0.0015 and clearance >= 0.012:
                chosen = dest
                break
        if chosen is None:
            return finish("blocked", "No tested local attitude supports the required margin and above-rim sweep. This is not global infeasibility.")
        S3 = move("one_object_centered_attitude_change_at_new_workspace", chosen["tcp_position_world_m"], chosen["tcp_quaternion_xyzw"], 16)
        if S3 is None:
            return finish("needs_replan", E["control_gap"])
        current = sense("fresh final restaging effect and bounded above-rim jaw-opening corridor", B0)
        if current is None:
            return finish("needs_replan" if E.get("invalidated") else "blocked", E.get("invalidated", E.get("measurement_gap", "Final approach evidence unavailable.")))
        C, B, sem = current
        S = api.state()
        if not retention(C0, C, S0, S):
            return finish("needs_replan", "Fresh final carton motion is inconsistent with actual hand motion.")
    fm = fit(C, B, S)
    low = float(min(np.array(C["box_world_m"])[:, 2]))-C["u_m"]
    descent = max(0.0, low-B["rim_high_m"]-B["u_m"]-0.010)
    opened_low = float(min(fingers(S, 0.020)[:, 2]))
    finger_reserve = opened_low-descent-B["rim_high_m"]-B["u_m"]-0.004
    E["fit_margin_m"], E["approach_bottom_clearance_m"] = fm, low-B["rim_high_m"]-B["u_m"]
    if fm < margin:
        return finish("needs_replan", "Fresh achieved attitude fails the retained 3.5 mm fit margin; do not descend or release.")
    if E["approach_bottom_clearance_m"] < 0.012 or finger_reserve < 0.012 or sem["opening_corridor"] != "clear":
        return finish("blocked", "Fit is supported, but an observable above-rim opening/withdrawal option is not yet supported.")
    progress = float(np.linalg.norm(np.mean(np.array(C["box_world_m"]), axis=0)-np.mean(box0, axis=0)))
    if progress < 0.03:
        return finish("blocked", "Fresh carton displacement is too small to establish the requested restaging effect.")
    E["placement_option"] = {"type": "Above-rim release after revalidation; no finger insertion", "observation_frame": C["frame_id"],
                             "maximum_candidate_downward_shift_m": descent, "carton_bottom_reserve_at_that_shift_m": 0.010,
                             "conservative_fit_margin_m": fm, "required_fit_margin_m": margin,
                             "bounded_additional_jaw_excursion_each_side_m": 0.020, "finger_vertical_reserve_at_candidate_shift_m": finger_reserve,
                             "opening_extent_is_a_proposed_bound_not_a_measured_open_state": True,
                             "current_carton": C, "current_bowl": B, "actual_state": S, "carton_displacement_m": progress,
                             "position_tolerance_m": pt, "rotation_tolerance_rad": rt}
    return finish("stage_complete", "Fresh carton-to-hand differential motion, above-rim clearance and uncertainty-adjusted opening fit support the new central approach. Gripper remains closed; placement and release are not performed.")

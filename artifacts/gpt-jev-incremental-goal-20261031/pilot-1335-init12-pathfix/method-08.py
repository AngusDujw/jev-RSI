def main(api):
    rr, pr = api.recall("restage.reference"), api.recall("restage.progress")
    old, prior, entry = rr["value"], pr["value"], api.state()
    F = {k: old[k] for k in ["dimensions_m", "extent_uncertainty_m", "corner_ids", "end_identity_reference", "baseline_carton", "baseline_bowl", "baseline_state"]}
    F["provenance"] = [{k: r[k] for k in ["key", "frame_id", "method_number", "source_sha256"]} for r in [rr, pr]]
    F["dimension_source_records"] = old.get("source_records", old.get("dimension_source_records", []))
    F["scope"] = "Historical dimensions and physical identities; current face-anchored extent envelopes are not observations of hidden corners. The 0.4 mm floor and propagated uncertainties are conservative operational allowances, not calibrated confidence bounds."
    E = {"entry": entry, "retired_pending": prior.get("pending"), "preserved_actions": prior.get("actions", [])[-2:], "preserved_retention": prior.get("retention", [])[-2:], "reviews": 0, "actions": [], "retention": [], "release_authorized": False}
    pending = prior.get("pending")
    if pending:
        E["acknowledged_since_pending_steps"] = entry["native_steps"] - pending["before"]["native_steps"]
        E["actual_since_pending_translation_m"] = (np.array(entry["tcp_position_world_m"]) - pending["before"]["tcp_position_world_m"]).tolist()
        E["retired_target_residual_m"] = float(np.linalg.norm(np.array(pending["target_tcp_world_m"]) - entry["tcp_position_world_m"]))
    E["revision"] = "The raise and transfer already happened. Retire the stalled residual target; assess the achieved object pose before any new action."
    pt, rt, required = 0.0015, 0.015, 0.0035
    def plain(x):
        if isinstance(x, np.ndarray): return x.tolist()
        if isinstance(x, np.generic): return x.item()
        if isinstance(x, dict): return {k: plain(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)): return [plain(v) for v in x]
        return x
    def save():
        api.checkpoint("restage.reference", plain(F))
        api.checkpoint("restage.progress", plain(E))
    def finish(status, reason):
        E["actual_state"], E["reason"] = api.state(), reason
        save()
        return {"stage_status": status, "reason": reason, "evidence": plain(E), "completion_proposed": False,
                "handoff": {"checkpoint_keys": ["restage.reference", "restage.progress"], "actual_state": E["actual_state"],
                "reference_contents": "Dimension provenance, frame-324 baseline face/end/bowl measurements and hand state, latest valid partial measurements, current models with observation frames.",
                "progress_contents": "Retired interrupted command, acknowledged transfer inferred from actual states, preserved earlier receipts, new pending/actual action and differential evidence.",
                "frames": "World metres; active tool-to-world xyzw quaternions. All geometry is valid only at its recorded observation frame.",
                "placement_option": E.get("placement_option"), "release_authorized": False,
                "assumptions": ["No pickup, release or failed old tilt is replayed.", "Hidden carton extent uses the preserved rigid-package dimensions, revalidated by current identity, face and short-edge width.", "The 20 mm per-side opening envelope is a tested prospective corridor, not a measured open state or a hardware travel limit.", "Revalidate retention, fit, actual opening travel and local clearance before placement. No below-rim clearance or stable containment is certified."]}}
    Q = {}
    for a in ["x", "y", "z", "rx", "ry", "rz"]:
        Q[a] = {"type": "choice", "instructions": "For world axis " + a + ", read state.processed_features.axes." + a + ".goal_relation. Choose positive for increase, negative for decrease, hold for within_tolerance. Use actual hand residuals, not guessed carton motion.",
                "criteria": {"negative": "Decrease this world coordinate or world rotation-vector component.", "hold": "Keep this axis within its supplied deadband.", "positive": "Increase this world coordinate or world rotation-vector component."}}
    Q["gripper"] = {"type": "choice", "instructions": "Read state.processed_features.objective.gripper and deliver it unchanged. This restaging method requests close only; do not infer retention from closure.",
                    "criteria": {"open": "The objective explicitly requests opening.", "close": "The objective requests continued closure.", "keep": "The objective requests preserving the previous command."}}
    pixel = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}
    fields = {"identity": ["same_carton", "lost_or_changed", "unknown"], "shape": ["same_rigid_printed_face", "changed", "unknown"],
              "end_ids": ["matched", "unknown"], "end_camera": ["agentview", "robot0_eye_in_hand"], "end_pixels": {"type": "array", "items": pixel, "maxItems": 2},
              "bowl": ["same_upright", "moved_or_tipped", "unknown"], "bowl_mode": ["rim", "landmarks", "unknown"],
              "rim_camera": ["agentview", "robot0_eye_in_hand"], "rim_pixels": {"type": "array", "items": pixel, "maxItems": 8},
              "closed_route": ["clear", "obstructed", "unknown"], "opening_corridor": ["clear", "obstructed", "unknown"], "notes": "string"}
    def rays(camera, pixels, plane):
        pts, uncertainty = [], 0.0
        for p in pixels:
            x = np.array(api.plane_point(camera, p, plane)["world_m"])
            pts.append(x.tolist())
            for d in [[1, 0], [-1, 0], [0, 1], [0, -1]]:
                pp = [p[0] + d[0], p[1] + d[1]]
                if min(pp) < 0 or max(pp) > 767: raise ValueError("Pixel uncertainty ray leaves image.")
                y = np.array(api.plane_point(camera, pp, plane)["world_m"])
                uncertainty = max(uncertainty, float(np.linalg.norm(y - x)))
        return np.array(pts), uncertainty
    def geometry(r, v):
        p = r["parameters"]
        if p["identity"] != "same_carton" or p["shape"] != "same_rigid_printed_face" or p["end_ids"] != "matched" or len(p["end_pixels"]) != 2: raise ValueError("Current face or physical end identities unresolved.")
        names = [k for k in ["p0", "p1", "p2", "p3", "p4", "p5"] if k in v]
        if len(names) < 4: raise ValueError("Need four valid current face samples; failures: " + str(r["measurement_errors"]))
        plane = plain(geo.plane([v[k]["world_m"] for k in names]))
        noise, spread = max(0.0004, 3 * plane["rms_m"]), min(plane["in_plane_spread_m"])
        if plane["rms_m"] > 0.0008 or spread < 8 * noise: raise ValueError("Face normal is insufficiently observable relative to residual/noise: " + str(plane))
        A, pu = rays(p["end_camera"], p["end_pixels"], plane["coefficients"])
        n, w = np.array(plane["coefficients"][:3]), A[1] - A[0]
        width, eu = float(np.linalg.norm(w)), max(0.0004, pu + plane["rms_m"])
        L, W, t = F["dimensions_m"]
        if abs(width - W) > 2 * (F["extent_uncertainty_m"] + eu): raise ValueError("Fresh short-edge width disagrees with historical rigid-package dimensions.")
        w = w / width
        long = np.cross(w, n)
        long = long / np.linalg.norm(long)
        if np.dot(np.array(plane["center_world_m"]) - np.mean(A, axis=0), long) <= 2 * noise: raise ValueError("End ordering does not point into the observed printed face.")
        top = np.array([A[0], A[1], A[1] + L * long, A[0] + L * long])
        u = F["extent_uncertainty_m"] + eu + (L + t) * noise / spread + 2 * eu * L / width
        C = {"frame_id": r["frame_id"], "anchors_world_m": A.tolist(), "normal_world": n.tolist(), "short_axis_world": w.tolist(), "box_world_m": np.concatenate([top, top - t * n]).tolist(), "u_m": float(u), "edge_u_m": eu, "normal_u_rad": noise / spread, "plane": plane}
        if p["bowl"] != "same_upright": raise ValueError("Current upright bowl identity is unresolved.")
        base = F["baseline_bowl"]
        marks = {k: v[k] for k in ["b0", "b1"] if k in v}
        if p["bowl_mode"] == "rim":
            dn = [k for k in ["d0", "d1", "d2", "d3"] if k in v]
            if len(dn) < 3 or len(p["rim_pixels"]) != 8: raise ValueError("Need three valid lip-plane depths and eight current inner-boundary pixels.")
            bp = plain(geo.plane([v[k]["world_m"] for k in dn]))
            if bp["coefficients"][2] < 0.985 or bp["rms_m"] > 0.001 or min(bp["in_plane_spread_m"]) < 8 * max(0.0004, 3 * bp["rms_m"]): raise ValueError("Lip samples do not resolve a horizontal opening plane.")
            rim, ru = rays(p["rim_camera"], p["rim_pixels"], bp["coefficients"])
            circle = plain(geo.circle_xy(rim))
            if circle["largest_angular_gap_rad"] > 1.4 or circle["max_radial_error_m"] > 0.0025 or circle["rms_m"] > 0.0013: raise ValueError("Opening circle coverage or residual failed: " + str(circle))
            bu = circle["max_radial_error_m"] + ru + 2 * bp["rms_m"] + 0.0004
            B = {"frame_id": r["frame_id"], "center_xy_m": circle["center_xy_m"], "radius_m": circle["radius_m"], "u_m": bu, "rim_high_m": float(max(rim[:, 2])), "plane": bp, "circle": circle, "rim_world_m": rim.tolist(), "marks": marks, "source": "Fresh identified lip and inner boundary"}
            if np.linalg.norm(np.array(B["center_xy_m"]) - base["center_xy_m"]) > 0.004 or abs(B["radius_m"] - base["radius_m"]) > 0.004:
                E["invalidated"] = "Fresh bowl opening differs materially from the preserved opening; reassess bowl stationarity."
                raise ValueError(E["invalidated"])
        elif p["bowl_mode"] == "landmarks":
            common = [k for k in marks if k in base["marks"]]
            if len(common) < 2: raise ValueError("Fewer than two independent bowl marks; use a fresh visible rim instead.")
            delta = max(float(np.linalg.norm(np.array(marks[k]["world_m"]) - base["marks"][k]["world_m"])) for k in common)
            if delta > 0.002:
                E["invalidated"] = "Current independent bowl marks invalidate the 2 mm stationarity allowance."
                raise ValueError(E["invalidated"])
            B = dict(base)
            B.update({"frame_id": r["frame_id"], "u_m": base["u_m"] + delta + 0.0004, "stationarity_marks": marks, "stationarity_discrepancy_m": delta, "source": "Historical opening validated by current independent marks and upright identity"})
        else: raise ValueError("Neither a fresh rim nor independent bowl-stationarity measurements are available.")
        return C, B
    def sense(label, attempts):
        gap = ""
        for attempt in range(attempts):
            if E["reviews"] >= 3 or api.state()["budgets"]["gpt_remaining"] < 2:
                E["measurement_gap"] = gap + " Fresh-observation allowance unavailable."
                return None
            question = ("Restage only, no release. " + label + ". Identify the same rigid cream-cheese printed face and physical c0/c1 Cream/C short-end corners in that order, using supplied identity references, not stationary projections. Return end_camera/end_pixels. Request p0..p5 as six spread-out depth samples strictly within that printed face, away from seams and fingers; these are plane samples, not correspondences. Do not require hidden corners. Prefer a FRESH bowl opening using the close wrist view: request d0..d3 as spread-out actual horizontal upper-lip surface depths, and eight well-distributed INNER opening rim_pixels with rim_camera. Do not use the sloping interior as the lip plane. If lip depth is unavailable, bowl_mode landmarks may instead request BOTH b0 (large pale floor medallion center) and b1 (separate bottle-side rear inner-wall rosette), independently identified against the supplied baseline. Choose unknown rather than invent measurements. closed_route concerns only one possible 15 mm upward move, at most 12 mm horizontal recentering, and at most 0.32 rad additional tilt about the observed short axis, compensated about the carton center in this NEW workspace. opening_corridor concerns the visible nonrobot surroundings of the current finger envelope plus 20 mm outward on each jaw and a 20 mm upward withdrawal, above the rim; robot self-occlusion alone is not an observed obstacle, but unseen external clearance is not certified. No descent or opening will occur.")
            if attempt: question += " Use a different valid patch, camera or bowl measurement mode, not the same failed evidence. Exact gap: " + gap
            r = api.review(question, context={"references": F, "actual_state": api.state(), "retired_target": E["retired_pending"]}, fields=fields)
            E["reviews"] += 1
            bad = set(x["name"] for x in r["measurement_errors"])
            v = {k: x for k, x in r["points"].items() if k not in bad and x["frame_id"] == r["frame_id"]}
            F["partial_valid_measurements"] = v
            E["last_review"] = {"frame_id": r["frame_id"], "parameters": r["parameters"], "measurement_errors": r["measurement_errors"]}
            save()
            if r["status"] == "stop":
                E["review_stop"] = True
                return None
            if r["parameters"]["identity"] == "lost_or_changed" or r["parameters"]["shape"] == "changed" or r["parameters"]["bowl"] == "moved_or_tipped":
                E["invalidated"] = "Fresh observation reports changed object identity/shape or displaced bowl."
                return None
            try:
                C, B = geometry(r, v)
                F["current_carton"], F["current_bowl"] = C, B
                F["models_stale_after_frame"] = None
                E["last_measurement_resolved_frame"] = r["frame_id"]
                save()
                return C, B, r["parameters"], api.state()
            except Exception as ex:
                gap, E["measurement_gap"] = str(ex), str(ex)
                if E.get("invalidated"): return None
        return None
    def failed_sense():
        return finish("abort" if E.get("review_stop") else ("needs_replan" if E.get("invalidated") else "blocked"), E.get("invalidated", E.get("measurement_gap", "Review requested stopping.")))
    def rigid(s0, s1):
        T = np.eye(4)
        T[:3, :3] = geo.rotation(s1["tcp_quaternion_xyzw"]) @ geo.rotation(s0["tcp_quaternion_xyzw"]).T
        T[:3, 3] = np.array(s1["tcp_position_world_m"]) - T[:3, :3] @ np.array(s0["tcp_position_world_m"])
        return T
    def retained(c0, c1, s0, s1):
        T = rigid(s0, s1)
        predicted = geo.transform(c0["anchors_world_m"], T)
        signal = float(max(np.linalg.norm(predicted - c0["anchors_world_m"], axis=1)))
        error = float(geo.attachment_error(c0["anchors_world_m"], c1["anchors_world_m"], s0, s1))
        normal_error = float(math.acos(float(np.clip(np.dot(T[:3, :3] @ np.array(c0["normal_world"]), c1["normal_world"]), -1, 1))))
        allowance = max(0.0036, 2 * (c0["edge_u_m"] + c1["edge_u_m"]) + 0.0008)
        good = error <= allowance and signal > 2 * allowance and normal_error <= c0["normal_u_rad"] + c1["normal_u_rad"]
        E["retention"].append({"before_frame": s0["frame_id"], "after_frame": s1["frame_id"], "attachment_error_m": error, "allowance_m": allowance, "normal_error_rad": normal_error, "predicted_feature_motion_m": signal, "actual_hand_translation_m": (np.array(s1["tcp_position_world_m"]) - s0["tcp_position_world_m"]).tolist(), "supported": bool(good)})
        return good
    def fingers(s, opening=0.0):
        lo, hi = np.array(s["own_geometry"]["finger_low_offset_tool_m"]), np.array(s["own_geometry"]["finger_high_offset_tool_m"])
        lo[1], hi[1] = lo[1] - opening, hi[1] + opening
        pts = [[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]]
        T = np.eye(4)
        T[:3, :3], T[:3, 3] = geo.rotation(s["tcp_quaternion_xyzw"]), s["tcp_position_world_m"]
        return geo.transform(pts, T)
    def fit(C, B, S):
        box = np.array(C["box_world_m"])
        lever = float(max(np.linalg.norm(box - S["tcp_position_world_m"], axis=1)))
        return float(B["radius_m"] - max(np.linalg.norm(box[:, :2] - B["center_xy_m"], axis=1)) - C["u_m"] - B["u_m"] - pt - lever * rt)
    def option(C, B, S, sem):
        fm = fit(C, B, S)
        bottom = float(min(np.array(C["box_world_m"])[:, 2])) - C["u_m"] - B["rim_high_m"] - B["u_m"]
        jaw = float(min(fingers(S, 0.020)[:, 2])) - B["rim_high_m"] - B["u_m"] - 0.004
        out = {"observation_frame": C["frame_id"], "fit_margin_m": fm, "required_margin_m": required, "carton_bottom_above_rim_m": bottom, "expanded_finger_above_rim_reserve_m": jaw, "position_tolerance_m": pt, "rotation_tolerance_rad": rt, "tested_additional_jaw_excursion_each_side_m": 0.020, "candidate_above_rim_downward_shift_limit_m": max(0.0, min(bottom - 0.010, jaw - 0.012)), "type": "Above-rim placement/opening option only; not permission to release"}
        return fm >= required and bottom >= 0.012 and jaw >= 0.012 and sem["opening_corridor"] == "clear", out
    save()
    if entry["last_gripper_command"] != "close": return finish("needs_replan", "Actual gripper command changed; do not blindly reclose or reopen.")
    if F["baseline_carton"]["frame_id"] != F["baseline_state"]["frame_id"]: return finish("blocked", "Historical carton and hand baseline frames do not match.")
    current = sense("Validate the achieved post-transfer pose at the actual current frame; the old 3 mm residual target is retired", 2)
    if current is None: return failed_sense()
    C, B, sem, S = current
    if not retained(F["baseline_carton"], C, F["baseline_state"], S): return finish("needs_replan", "Fresh carton motion does not support retention across the acknowledged raise and transfer.")
    good, opt = option(C, B, S, sem)
    E["achieved_option_test"] = opt
    if not good:
        if sem["closed_route"] != "clear": return finish("blocked", "Current fit/opening option is insufficient and the one different raised local route lacks observable clearance.")
        if E["reviews"] >= 3 or api.state()["budgets"]["gpt_remaining"] < 3: return finish("blocked", "No fresh effect-review allowance remains for another physical action.")
        chosen = None
        E["candidate_tests"] = []
        for angle in [0.0, 0.12, 0.22, 0.32]:
            dest = dict(S)
            dest["tcp_quaternion_xyzw"] = api.compose(S["tcp_quaternion_xyzw"], (-angle * np.array(C["short_axis_world"])).tolist())
            rb = geo.transform(C["box_world_m"], rigid(S, dest))
            xyz = np.array(S["tcp_position_world_m"]) + [0, 0, 0.015]
            xyz[:2] += np.array(B["center_xy_m"]) - np.mean(rb[:, :2], axis=0)
            if np.linalg.norm(xyz[:2] - np.array(S["tcp_position_world_m"])[:2]) > 0.012: continue
            dest["tcp_position_world_m"] = xyz.tolist()
            pred = dict(C)
            pred["box_world_m"] = geo.transform(C["box_world_m"], rigid(S, dest)).tolist()
            fm, sweep = fit(pred, B, dest), 10.0
            lever = float(max(np.linalg.norm(np.array(C["box_world_m"]) - S["tcp_position_world_m"], axis=1)))
            for i in range(9):
                f, ss = i / 8.0, dict(S)
                ss["tcp_position_world_m"] = S["tcp_position_world_m"]
                ss["tcp_quaternion_xyzw"] = api.compose(S["tcp_quaternion_xyzw"], (-f * angle * np.array(C["short_axis_world"])).tolist())
                bb = geo.transform(C["box_world_m"], rigid(S, ss))
                sweep = min(sweep, float(min(bb[:, 2])) - C["u_m"], float(min(fingers(ss)[:, 2])))
            reserve = sweep - B["rim_high_m"] - B["u_m"] - lever * angle / 16.0 - float(np.linalg.norm(xyz - S["tcp_position_world_m"])) / 16.0 - 0.004
            E["candidate_tests"].append({"angle_rad": angle, "fit_margin_m": fm, "above_rim_sweep_reserve_m": reserve})
            if fm >= required + pt and reserve >= 0.012:
                chosen = dest
                break
        if chosen is None: return finish("blocked", "No bounded raised/recentered candidate supports the unchanged fit and sweep margins; this is not global infeasibility.")
        E["pending"] = {"phase": "one_raised_object_centered_restage", "before": S, "target": chosen["tcp_position_world_m"], "quaternion": chosen["tcp_quaternion_xyzw"], "gripper": "close"}
        save()
        r = api.drive(chosen["tcp_position_world_m"], chosen["tcp_quaternion_xyzw"], "close", Q,
                      features={"phase": "one_raised_object_centered_restage", "geometry_frame": C["frame_id"], "required_fit_margin_m": required, "carton_uncertainty_m": C["u_m"], "bowl_uncertainty_m": B["u_m"], "rise_m": 0.015, "tilt_rad": angle, "sweep_reserve_m": reserve, "release_authorized": False},
                      max_calls=18, tool_point="tcp", translation_limit=0.012, rotation_limit=0.05, steps=3, position_tolerance=pt, rotation_tolerance=rt)
        after = api.state()
        e0 = float(np.linalg.norm(np.array(chosen["tcp_position_world_m"]) - S["tcp_position_world_m"]))
        a0 = 2 * math.acos(float(np.clip(abs(np.dot(chosen["tcp_quaternion_xyzw"], S["tcp_quaternion_xyzw"])), 0, 1)))
        travel = float(np.linalg.norm(np.array(after["tcp_position_world_m"]) - S["tcp_position_world_m"]))
        E["actions"].append({"before": S, "after": after, "receipt": r, "actual_translation_m": travel, "position_error_reduction_m": e0 - r["position_error_m"], "rotation_error_reduction_rad": a0 - r["rotation_error_rad"]})
        E["pose_feedback_scope"] = "The new lease is never retried. Reached is not object evidence; a stalled or exhausted tail can only be accepted after useful nondivergent whole-lease progress and fresh unchanged geometric effect tests."
        E["pending"], F["models_stale_after_frame"] = None, after["frame_id"]
        save()
        if r["choices"]["gripper"] != "close" or after["last_gripper_command"] != "close": return finish("needs_replan", "Actual gripper delivery mismatched; no retry.")
        if travel < 0.004 or r["position_error_m"] > e0 + 0.002 or r["rotation_error_rad"] > a0 + 0.015 or r["position_error_m"] > 0.012 or r["rotation_error_rad"] > 0.08: return finish("needs_replan", "The one different restaging action stalled without useful motion or diverged; its actual state is preserved and no correction is repeated.")
        current = sense("Measure the actual achieved effect, not target attainment; recheck the above-rim opening corridor after the one bounded action", 1)
        if current is None: return failed_sense()
        C2, B2, sem2, S2 = current
        if not retained(C, C2, S, S2): return finish("needs_replan", "Fresh local differential object motion disagrees with actual hand motion.")
        C, B, sem, S = C2, B2, sem2, S2
        F["models_stale_after_frame"] = None
        good, opt = option(C, B, S, sem)
        E["achieved_option_test"] = opt
        if not good: return finish("blocked", "Fresh achieved geometry or visible opening corridor fails the unchanged placement-option margins. Do not repeat the residual command.")
    displacement = float(np.linalg.norm(np.mean(np.array(C["box_world_m"]), axis=0) - np.mean(np.array(F["baseline_carton"]["box_world_m"]), axis=0)))
    if displacement < 0.03: return finish("blocked", "Measured carton displacement is insufficient to establish the restaging effect.")
    E["carton_displacement_from_frame324_m"], E["placement_option"] = displacement, opt
    return finish("stage_complete", "Fresh object-to-hand differential motion and uncertainty-adjusted fit establish an above-rim approach with a supported local finger-opening option. Historical residual targets are retired; no descent or release occurred.")

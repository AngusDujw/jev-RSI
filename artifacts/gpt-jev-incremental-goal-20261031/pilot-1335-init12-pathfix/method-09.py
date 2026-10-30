def main(api):
    rr, pr, entry = api.recall("restage.reference"), api.recall("restage.progress"), api.state()
    old, prior = rr["value"], pr["value"]
    keys = ["dimensions_m", "extent_uncertainty_m", "corner_ids", "end_identity_reference", "baseline_carton", "baseline_bowl", "baseline_state"]
    F = {k: old[k] for k in keys}
    F["provenance"] = [{k: r[k] for k in ["key", "frame_id", "method_number", "source_sha256"]} for r in [rr, pr]]
    F["dimension_source_records"] = old.get("dimension_source_records", old.get("source_records", []))
    E = {"entry": entry, "reviews": 0, "actions": [], "retention": [], "release_authorized": False, "retired_target": prior.get("retired_pending", prior.get("pending")), "preserved_actions": prior.get("preserved_actions", prior.get("actions", []))[-2:], "preserved_retention": prior.get("preserved_retention", [])[-2:]}
    E["revision"] = "Preserve the completed raise and transfer. The old residual target remains retired. A different fitted radius alone does not establish bowl motion."
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
        return {"stage_status": status, "reason": reason, "evidence": plain(E), "completion_proposed": False, "handoff": {"checkpoint_keys": ["restage.reference", "restage.progress"], "reference_contents": "Historical dimensions, physical end identities and frame-324 object/hand baseline; fresh segmented lip and boundary models, current carton envelope, valid partial samples, and any pre-action reference.", "progress_contents": "Retired target, preserved acknowledged actions, actual states, differential retention, measurement-model discrepancy, pending/acknowledged new action and effect tests.", "frames": "World metres; tool-to-world xyzw quaternions. Observation frame IDs determine freshness; checkpoint metadata records method/source provenance.", "actual_state": E["actual_state"], "placement_option": E.get("placement_option"), "release_authorized": False, "assumptions": ["The old opening is not reused as current geometry or as a bowl-motion detector.", "The carton envelope uses historical rigid-package dimensions anchored to a current identified face and end, not observed hidden corners.", "The supported option, if present, is above-rim opening and upward withdrawal within the tested additional 20 mm per tool-y side envelope, not an actuator travel specification.", "No descent, opening, release, hidden clearance or stable containment has been tested. Revalidate geometry and actual opening travel before placement."]}}
    Q = {}
    for a in ["x", "y", "z", "rx", "ry", "rz"]:
        Q[a] = {"type": "choice", "instructions": "For world axis " + a + ", read state.processed_features.axes." + a + ".goal_relation. Select positive for increase, negative for decrease, and hold for within_tolerance. Follow measured hand residuals, not imagined object motion.", "criteria": {"negative": "Decrease this world coordinate or world rotation-vector component.", "hold": "Keep this axis within its supplied deadband.", "positive": "Increase this world coordinate or world rotation-vector component."}}
    Q["gripper"] = {"type": "choice", "instructions": "Read state.processed_features.objective.gripper and deliver that requirement unchanged. This stage requests close only; closure is not retention evidence.", "criteria": {"open": "The objective explicitly requests opening.", "close": "The objective requests continued closure.", "keep": "The objective requests preservation of the previous command."}}
    pixel = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}
    pixels = {"type": "array", "items": pixel, "maxItems": 8}
    patch = {"type": "array", "items": pixel, "minItems": 3, "maxItems": 6}
    fields = {"carton": ["same_rigid_carton", "changed", "unknown"], "end_ids": ["matched", "unknown"], "end_camera": ["agentview", "robot0_eye_in_hand"], "end_pixels": {"type": "array", "items": pixel, "maxItems": 2}, "bowl": ["same_upright", "different_or_tipped", "unknown"], "boundary": ["inner_upper_lip", "unknown"], "rim_camera": ["agentview", "robot0_eye_in_hand"], "inner_pixels": pixels, "outer_pixels": pixels, "lip_patches": {"type": "array", "items": patch, "maxItems": 4}, "carton_free": ["clear", "contact", "unknown"], "up_route": ["clear", "obstructed", "unknown"], "opening": ["measured_tops", "only_bowl", "obstructed", "unknown"], "tops_count": {"type": "integer", "minimum": 0, "maximum": 4}, "notes": "string"}
    def inside(p, poly):
        signs = [(poly[(i + 1) % len(poly)][0] - a[0]) * (p[1] - a[1]) - (poly[(i + 1) % len(poly)][1] - a[1]) * (p[0] - a[0]) for i, a in enumerate(poly)]
        return all(x >= 0 for x in signs) or all(x <= 0 for x in signs)
    def rays(camera, pixels_, plane, perturb=True):
        out, u = [], 0.0
        for p in pixels_:
            x = np.array(api.plane_point(camera, p, plain(plane))["world_m"])
            out.append(x)
            if perturb:
                for dx, dy in [[1, 0], [-1, 0], [0, 1], [0, -1]]:
                    pp = [p[0] + dx, p[1] + dy]
                    if min(pp) < 0 or max(pp) > 767: raise ValueError("Boundary uncertainty ray leaves the image.")
                    u = max(u, float(np.linalg.norm(np.array(api.plane_point(camera, pp, plain(plane))["world_m"]) - x)))
        return np.array(out), u
    def sense(label):
        if E["reviews"] >= 2 or api.state()["budgets"]["gpt_remaining"] < 1: raise ValueError("Fresh observation allowance unavailable.")
        question = ("Restage only, no opening or release. " + label + ". Resolve the prior opening-model disagreement by physical boundary identity, not by assuming the bowl moved. Identify the same rigid carton and c0/c1 Cream/C short-end corners in their preserved physical order; return end_camera/end_pixels. Request p0..p5 as six spread-out interior printed-face depth samples, avoiding fingers and seams. They are plane samples, not correspondences. In the clearest bowl view, distinguish the INNER upper opening edge from the OUTER lip silhouette, not a decorative ring on the sloping interior. Return eight angularly distributed inner_pixels and eight corresponding outer_pixels and rim_camera. Return four small convex lip_patches lying strictly on the actual horizontal upper lip, at separated locations. Request d0..d3 as lip depths within these patches and one region lip_surface with explicit camera, tight encompassing box and stride=4. The program will segment this cloud by the patches and test its plane; do not label the whole cloud as isolated. If the lip is too narrow, provide accurate patches for radius-1 depth sampling, or unknown. carton_free concerns separation from external bodies, not fingers. up_route concerns only fixed-current-attitude upward travel of 15 mm and at most 12 mm horizontal recentering; no tilt or descent. opening concerns the current finger envelope expanded by 20 mm on each tool-y side and a 20 mm upward withdrawal, above the bowl. For measured_tops, request o0..o(tops_count-1) at the exposed highest points of ALL nearby external bodies relevant to that local envelope, especially the adjacent green bottle. Use this mode only when visible top shape establishes these samples as local height bounds. only_bowl requires a visible locally empty corridor apart from the bowl below. Self-occlusion is not an obstacle, but a hidden nearby body is not certified absent: use unknown and explain the exact missing relation. No exhaustive scene reconstruction is requested.")
        r = api.review(question, context={"references": F, "actual_state": api.state(), "retired_target": E["retired_target"], "required_fit_margin_m": required}, fields=fields)
        E["reviews"] += 1
        p, bad = r["parameters"], set(x["name"] for x in r["measurement_errors"])
        v = {k: x for k, x in r["points"].items() if k not in bad and x["frame_id"] == r["frame_id"]}
        F["partial_valid_measurements"] = v
        E["last_review"] = {"frame_id": r["frame_id"], "parameters": {k: (x[:900] if k == "notes" else x) for k, x in p.items()}, "measurement_errors": r["measurement_errors"]}
        save()
        if r["status"] == "stop": E["review_stop"] = True; raise ValueError("Observation review requested stopping.")
        if p["carton"] == "changed" or p["bowl"] == "different_or_tipped" or p["carton_free"] == "contact": E["invalidated"] = True; raise ValueError("Current identity, upright bowl or external-contact evidence invalidates this local approach.")
        if p["carton"] != "same_rigid_carton" or p["end_ids"] != "matched" or len(p["end_pixels"]) != 2: raise ValueError("Current carton face/end identities unresolved.")
        face = [v[k]["world_m"] for k in ["p0", "p1", "p2", "p3", "p4", "p5"] if k in v]
        if len(face) < 4: raise ValueError("Fewer than four valid current face samples; see saved measurement errors.")
        cp = plain(geo.plane(face)); noise, spread = max(0.0004, 3 * cp["rms_m"]), min(cp["in_plane_spread_m"])
        if cp["rms_m"] > 0.0008 or spread < 8 * noise: raise ValueError("Face normal insufficiently observable relative to residual/noise: " + str(cp))
        A, pu = rays(p["end_camera"], p["end_pixels"], cp["coefficients"])
        n, w = np.array(cp["coefficients"][:3]), A[1] - A[0]
        width, eu = float(np.linalg.norm(w)), max(0.0004, pu + cp["rms_m"])
        L, W, thickness = F["dimensions_m"]
        if abs(width - W) > 2 * (F["extent_uncertainty_m"] + eu): raise ValueError("Observed short edge does not validate the preserved package dimensions.")
        w = w / width; along = np.cross(w, n); along = along / np.linalg.norm(along)
        if np.dot(np.array(cp["center_world_m"]) - np.mean(A, axis=0), along) <= 2 * noise: raise ValueError("Physical end ordering does not lead into the observed face.")
        top = np.array([A[0], A[1], A[1] + L * along, A[0] + L * along])
        C = {"frame_id": r["frame_id"], "anchors_world_m": A.tolist(), "normal_world": n.tolist(), "box_world_m": np.concatenate([top, top - thickness * n]).tolist(), "edge_u_m": eu, "normal_u_rad": noise / spread, "u_m": F["extent_uncertainty_m"] + eu + (L + thickness) * noise / spread + 2 * eu * L / width, "plane": cp}
        F["current_carton"] = C
        save()
        if p["bowl"] != "same_upright" or p["boundary"] != "inner_upper_lip" or len(p["inner_pixels"]) != 8 or len(p["outer_pixels"]) != 8 or len(p["lip_patches"]) != 4: raise ValueError("Need distinct current inner/outer boundaries and four identified lip patches.")
        seed = [v[k]["world_m"] for k in ["d0", "d1", "d2", "d3"] if k in v]
        segmented, region = [], r["regions"].get("lip_surface")
        if "lip_surface" not in bad and region is not None and region["frame_id"] == r["frame_id"] and region["camera"] == p["rim_camera"]:
            segmented = [x for x, pix in zip(region["world_m"], region["pixels"]) if all(np.isfinite(x)) and any(inside(pix, poly) for poly in p["lip_patches"])]
        if len(seed) < 4 or len(segmented) < 8:
            replacements = []
            for poly in p["lip_patches"]:
                pix = [int(round(sum(q[j] for q in poly) / len(poly))) for j in [0, 1]]
                try: replacements.append(api.point(p["rim_camera"], pix, radius=1))
                except Exception as ex: E["lip_depth_gap"] = str(ex)
            F["lip_replacement_samples"] = replacements
            seed += [x["world_m"] for x in replacements if x["frame_id"] == r["frame_id"]]
        if len(seed) < 4 and len(segmented) < 8: raise ValueError("Neither segmented lip cloud nor alternate radius-1 identified lip depths resolve the opening plane.")
        bp = plain(geo.plane(seed if len(seed) >= 4 else segmented))
        gate = max(0.0012, 3 * bp["rms_m"])
        accepted = [x for x in segmented if abs(float(np.dot(x, bp["coefficients"][:3]) + bp["coefficients"][3])) <= gate]
        if len(segmented) >= 8 and len(accepted) < 0.65 * len(segmented): raise ValueError("Identified lip depths and segmented cloud disagree; do not project the boundary onto an unsupported plane.")
        support = seed + accepted
        if len(support) < 4: raise ValueError("Insufficient consistent lip-plane support.")
        bp = plain(geo.plane(support))
        if bp["coefficients"][2] < 0.985 or bp["rms_m"] > 0.001 or min(bp["in_plane_spread_m"]) < 8 * max(0.0004, 3 * bp["rms_m"]): raise ValueError("Current lip plane is not adequately horizontal and resolved: " + str(bp))
        inner, ru = rays(p["rim_camera"], p["inner_pixels"], bp["coefficients"])
        outer, unused = rays(p["rim_camera"], p["outer_pixels"], bp["coefficients"], False)
        ci, co = plain(geo.circle_xy(inner)), plain(geo.circle_xy(outer))
        for circle in [ci, co]:
            if circle["largest_angular_gap_rad"] > 1.4 or circle["max_radial_error_m"] > 0.0025 or circle["rms_m"] > 0.0013: raise ValueError("Current identified rim circle fails coverage/residual checks: " + str(circle))
        if co["radius_m"] <= ci["radius_m"] or np.linalg.norm(np.array(co["center_xy_m"]) - ci["center_xy_m"]) > 0.003: raise ValueError("Inner/outer lip identity is not metrically consistent.")
        B = {"frame_id": r["frame_id"], "center_xy_m": ci["center_xy_m"], "radius_m": ci["radius_m"], "u_m": ci["max_radial_error_m"] + ru + 2 * bp["rms_m"] + 0.0004, "rim_high_m": float(max(inner[:, 2].max(), outer[:, 2].max())), "plane": bp, "circle": ci, "outer_circle": co, "segmented_count": len(segmented), "accepted_count": len(accepted), "lip_depth_count": len(seed), "rim_world_m": inner.tolist(), "source": "Fresh identified inner upper edge, distinct outer lip, depth-supported horizontal plane; not historical stationarity."}
        E["opening_model_discrepancy"] = {"old_frame": F["baseline_bowl"]["frame_id"], "new_frame": B["frame_id"], "center_change_m": float(np.linalg.norm(np.array(B["center_xy_m"]) - F["baseline_bowl"]["center_xy_m"])), "radius_change_m": B["radius_m"] - F["baseline_bowl"]["radius_m"], "interpretation": "Replace the old opening for this local action. Without matched landmark displacement this discrepancy is not evidence of bowl movement."}
        S = api.state()
        if S["frame_id"] != r["frame_id"]: raise ValueError("State changed during geometry acquisition; models cannot be treated as simultaneous.")
        F["current_carton"], F["current_bowl"], F["models_stale"] = C, B, False
        O = {"parameters": p, "tops": [v["o" + str(i)] for i in range(p["tops_count"]) if "o" + str(i) in v]}
        save()
        return C, B, O, S
    def transform(s0, s1):
        T = np.eye(4); T[:3, :3] = geo.rotation(s1["tcp_quaternion_xyzw"]) @ geo.rotation(s0["tcp_quaternion_xyzw"]).T
        T[:3, 3] = np.array(s1["tcp_position_world_m"]) - T[:3, :3] @ np.array(s0["tcp_position_world_m"])
        return T
    def retained(c0, c1, s0, s1):
        if c0["frame_id"] != s0["frame_id"] or c1["frame_id"] != s1["frame_id"]: return False
        T = transform(s0, s1); pred = geo.transform(c0["anchors_world_m"], T)
        signal = float(max(np.linalg.norm(pred - c0["anchors_world_m"], axis=1)))
        error = float(geo.attachment_error(c0["anchors_world_m"], c1["anchors_world_m"], s0, s1))
        normal = float(math.acos(float(np.clip(np.dot(T[:3, :3] @ np.array(c0["normal_world"]), c1["normal_world"]), -1, 1))))
        allowance = max(0.0036, 2 * (c0["edge_u_m"] + c1["edge_u_m"]) + 0.0008)
        good = error <= allowance and signal > 2 * allowance and normal <= c0["normal_u_rad"] + c1["normal_u_rad"]
        E["retention"].append({"before_frame": s0["frame_id"], "after_frame": s1["frame_id"], "attachment_error_m": error, "allowance_m": allowance, "predicted_landmark_motion_m": signal, "normal_error_rad": normal, "actual_hand_translation_m": (np.array(s1["tcp_position_world_m"]) - s0["tcp_position_world_m"]).tolist(), "supported": bool(good)})
        return good
    def finger_bottom(S):
        lo, hi = np.array(S["own_geometry"]["finger_low_offset_tool_m"]), np.array(S["own_geometry"]["finger_high_offset_tool_m"])
        lo[1] -= 0.020; hi[1] += 0.020
        corners = [[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]]
        T = np.eye(4); T[:3, :3], T[:3, 3] = geo.rotation(S["tcp_quaternion_xyzw"]), S["tcp_position_world_m"]
        return float(min(geo.transform(corners, T)[:, 2]))
    def fit(C, B, S):
        box = np.array(C["box_world_m"])
        lever = float(max(np.linalg.norm(box - S["tcp_position_world_m"], axis=1)))
        return float(B["radius_m"] - max(np.linalg.norm(box[:, :2] - B["center_xy_m"], axis=1)) - C["u_m"] - B["u_m"] - pt - lever * rt)
    def assess(C, B, O, S):
        p = O["parameters"]; ceiling = B["rim_high_m"] + B["u_m"]
        known = p["opening"] == "only_bowl" and p["tops_count"] == 0
        if p["opening"] == "measured_tops" and p["tops_count"] > 0 and len(O["tops"]) == p["tops_count"]:
            ceiling = max(ceiling, max(x["world_m"][2] for x in O["tops"]) + 0.002)
            known = True
        bottom = float(min(np.array(C["box_world_m"])[:, 2])) - C["u_m"] - B["rim_high_m"] - B["u_m"]
        jaw = finger_bottom(S) - ceiling - 0.004
        result = {"observation_frame": C["frame_id"], "fit_margin_m": fit(C, B, S), "required_margin_m": required, "carton_above_rim_reserve_m": bottom, "expanded_jaw_above_relevant_tops_reserve_m": jaw if known else None, "local_external_height_bound_m": ceiling if known else None, "external_top_measurements": O["tops"], "opening_relation_known": known, "opening_mode": p["opening"], "position_tolerance_m": pt, "rotation_tolerance_rad": rt, "additional_tool_y_excursion_each_side_m": 0.020, "upward_withdrawal_envelope_m": 0.020, "scope": "Above-rim prospective opening option only, without release authorization."}
        result["failed_relations"] = [name for name, ok in [("uncertainty_adjusted_fit", result["fit_margin_m"] >= required), ("carton_above_rim", bottom >= 0.012), ("finger_height_reserve", known and jaw >= 0.012), ("visible_local_opening_relation", known), ("carton_external_separation", p["carton_free"] == "clear")] if not ok]
        return len(result["failed_relations"]) == 0, result
    def observation_failure(ex):
        return finish("abort" if E.get("review_stop") else ("needs_replan" if E.get("invalidated") else "blocked"), str(ex))
    save()
    if entry["last_gripper_command"] != "close": return finish("needs_replan", "Actual gripper command changed; no automatic reclosure or reopening.")
    try: C, B, O, S = sense("Measure the achieved post-transfer pose, with the old stalled target retired")
    except Exception as ex: return observation_failure(ex)
    if not retained(F["baseline_carton"], C, F["baseline_state"], S): return finish("needs_replan", "Fresh physical end/face motion does not support retention across the acknowledged raise and transfer.")
    good, result = assess(C, B, O, S); E["effect_tests"] = [result]
    if not good:
        if O["parameters"]["up_route"] != "clear" or O["parameters"]["carton_free"] != "clear": return finish("blocked", "Unsupported relations: " + str(result["failed_relations"]) + "; the separate closed-gripper route is not established. " + O["parameters"]["notes"][:700])
        if prior.get("pending"): return finish("blocked", "An earlier pending action requires reconciliation; no action is replayed.")
        if api.state()["budgets"]["gpt_remaining"] < 2: return finish("blocked", "Insufficient review reserve for motion followed by fresh effect evidence.")
        shift = np.array([0.0, 0.0, 0.015]); shift[:2] = np.array(B["center_xy_m"]) - np.mean(np.array(C["box_world_m"])[:, :2], axis=0)
        if np.linalg.norm(shift[:2]) > 0.012: return finish("blocked", "Required recentering exceeds the observed local route; no tilt retry or margin reduction.")
        dest, predicted = dict(S), dict(C)
        dest["tcp_position_world_m"] = (np.array(S["tcp_position_world_m"]) + shift).tolist()
        predicted["box_world_m"] = (np.array(C["box_world_m"]) + shift).tolist()
        E["candidate"] = {"shift_world_m": shift.tolist(), "predicted_fit_margin_m": fit(predicted, B, dest), "attitude": "Hold the actual current attitude, not the retired quaternion."}
        if E["candidate"]["predicted_fit_margin_m"] < required + pt or result["carton_above_rim_reserve_m"] < 0.012 or finger_bottom(S) - B["rim_high_m"] - B["u_m"] < 0.016: return finish("blocked", "The one raised fixed-attitude candidate lacks the unchanged fit or above-rim reserve; this is not global infeasibility.")
        calls = min(12, api.state()["budgets"]["jev_remaining"], api.state()["budgets"]["native_steps_remaining"] // 3)
        if calls < 6: return finish("blocked", "Insufficient bounded control allowance for a distinct upward staging action.")
        F["action_baseline"] = {"carton": C, "bowl": {k: B[k] for k in ["frame_id", "center_xy_m", "radius_m", "u_m"]}, "state": S}
        E["pending"] = {"before": S, "target_tcp_world_m": dest["tcp_position_world_m"], "quaternion_xyzw": S["tcp_quaternion_xyzw"], "gripper": "close", "phase": "one_fixed_current_attitude_raise_and_recenter"}
        F["models_stale"] = True
        save()
        try:
            receipt = api.drive(dest["tcp_position_world_m"], S["tcp_quaternion_xyzw"], "close", Q, features={"phase": "one_fixed_current_attitude_raise_and_recenter", "geometry_frame": C["frame_id"], "rise_m": 0.015, "horizontal_shift_m": float(np.linalg.norm(shift[:2])), "carton_uncertainty_m": C["u_m"], "opening_uncertainty_m": B["u_m"], "predicted_fit_margin_m": E["candidate"]["predicted_fit_margin_m"], "required_margin_m": required, "release_authorized": False}, max_calls=calls, tool_point="tcp", translation_limit=0.01, rotation_limit=0.04, steps=3, position_tolerance=pt, rotation_tolerance=rt)
        except Exception as ex: return finish("blocked", "Control interrupted; pending action and actual state are preserved, not replayed: " + str(ex))
        after = api.state()
        travel = float(np.linalg.norm(np.array(after["tcp_position_world_m"]) - S["tcp_position_world_m"]))
        residual = float(np.linalg.norm(np.array(dest["tcp_position_world_m"]) - after["tcp_position_world_m"]))
        angle = 2 * math.acos(float(np.clip(abs(np.dot(after["tcp_quaternion_xyzw"], S["tcp_quaternion_xyzw"])), 0, 1)))
        E["actions"].append({"before": S, "after": after, "receipt": receipt, "actual_translation_m": travel, "whole_lease_position_error_reduction_m": float(np.linalg.norm(shift)) - residual, "attitude_change_rad": angle})
        E["pending"] = None
        save()
        if receipt["choices"]["gripper"] != "close" or after["last_gripper_command"] != "close": return finish("needs_replan", "Gripper delivery mismatched; no retry.")
        if travel < 0.007 or residual > float(np.linalg.norm(shift)) - 0.004 or angle > 0.04: return finish("needs_replan", "The distinct raise/recenter failed to make useful nondivergent progress. Do not repeat its residual target.")
        try: C2, B2, O2, S2 = sense("Measure the actual effect of the single raised approach, not its target; reobserve the local external-top relation")
        except Exception as ex: return observation_failure(ex)
        if not retained(C, C2, S, S2): return finish("needs_replan", "Current differential carton motion does not match actual whole-lease hand motion.")
        if np.linalg.norm(np.array(B2["center_xy_m"]) - B["center_xy_m"]) > B["u_m"] + B2["u_m"] + 0.002: return finish("needs_replan", "Two consistently identified current opening models changed beyond their allowance after motion; reassess this local approach.")
        C, B, O, S = C2, B2, O2, S2
        good, result = assess(C, B, O, S); E["effect_tests"].append(result)
        if not good: return finish("blocked", "Fresh unsupported relations: " + str(result["failed_relations"]) + ". The different action is not repeated. " + O["parameters"]["notes"][:700])
    displacement = float(np.linalg.norm(np.mean(np.array(C["box_world_m"]), axis=0) - np.mean(np.array(F["baseline_carton"]["box_world_m"]), axis=0)))
    if displacement < 0.03: return finish("blocked", "Fresh carton displacement does not establish a materially changed approach.")
    E["carton_displacement_from_frame324_m"], E["placement_option"] = displacement, result
    return finish("stage_complete", "Fresh differential retention, corrected inner-opening geometry and unchanged uncertainty-adjusted margins support the achieved above-rim approach and a local finger-opening option. No descent or release occurred.")

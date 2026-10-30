def main(api):
    rr, pr, S = api.recall("restage.reference"), api.recall("restage.progress"), api.state()
    old, prior = rr["value"], pr["value"]
    keep = ["dimensions_m", "extent_uncertainty_m", "corner_ids", "end_identity_reference", "baseline_carton", "baseline_bowl", "baseline_state", "current_carton", "current_bowl", "dimension_source_records"]
    F = {k: old[k] for k in keep if k in old}
    F["source_records"] = [{k: r[k] for k in ["key", "frame_id", "method_number", "source_sha256"]} for r in [rr, pr]]
    E = {"entry": S, "actions": [], "release_authorized": False, "retired_target": prior.get("retired_target"), "preserved_actions": prior.get("preserved_actions", [])[-2:], "preserved_retention": prior.get("retention", [])[-2:], "previous_failed_relations": prior.get("effect_tests", [])[-1:], "measurement_errors": []}
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
        return {"stage_status": status, "reason": reason, "evidence": plain(E), "completion_proposed": False, "handoff": {"checkpoint_keys": ["restage.reference", "restage.progress"], "frames": "World metres; tool-to-world xyzw. All samples and camera calibrations retain observation frame IDs.", "reference_contents": "Provenanced rigid-carton dimensions, physical endpoint identities, frame-324 hand/object baseline, validated frame-396 carton and opening models, and new cross-camera local obstacle samples.", "progress_contents": "Completed motion and retention preserved; retired correction remains retired. New local separation tests, exact missing evidence, actual state and no new physical actions.", "actual_state": E["actual_state"], "placement_option": E.get("supported_option"), "release_authorized": False, "assumptions": ["No reset, descent, opening, release or renewed correction occurred.", "The carton model uses previously validated rigid dimensions, not newly observed hidden corners.", "Any accepted separation is scoped to the measured local band and the documented envelope, not a hidden-clearance certificate.", "Opening travel of 20 mm per tool-y side and upward withdrawal of 20 mm are a prospective envelope, not a hardware travel specification. Revalidate actual required travel and placement evidence in the next stage."]}}
    def corners(lo, hi):
        return np.array([[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]])
    def project(V, camera):
        X = geo.transform(V, np.linalg.inv(np.array(camera["camera_to_world_opencv"])))
        if min(X[:, 2]) <= 0.005: return None
        H = X @ np.array(camera["K"]).T
        return H[:, :2] / H[:, 2:3]
    if prior.get("pending"):
        E["pending"] = prior["pending"]
        return finish("blocked", "An unreconciled pending action exists; it is not replayed.")
    if S["last_gripper_command"] != "close": return finish("needs_replan", "Actual gripper state no longer matches the retained-carton entry.")
    if "current_carton" not in F or "current_bowl" not in F: return finish("blocked", "Current carton/opening reference missing.")
    C, B = F["current_carton"], F["current_bowl"]
    if old.get("models_stale", True) or C["frame_id"] != S["frame_id"] or B["frame_id"] != S["frame_id"] or prior.get("actual_state", {}).get("frame_id") != S["frame_id"]:
        F["models_stale"] = True
        return finish("blocked", "The no-motion sensing repair requires the unchanged measured frame; affected geometry must be reacquired.")
    F["models_stale"] = False
    try:
        pt, rt, required = 0.0015, 0.015, 0.0035
        box = np.array(C["box_world_m"]); tcp = np.array(S["tcp_position_world_m"])
        lever = float(max(np.linalg.norm(box - tcp, axis=1)))
        margin = float(B["radius_m"] - max(np.linalg.norm(box[:, :2] - B["center_xy_m"], axis=1)) - C["u_m"] - B["u_m"] - pt - lever * rt)
        bottom = float(min(box[:, 2]) - C["u_m"] - B["rim_high_m"] - B["u_m"])
        error = float(geo.attachment_error(F["baseline_carton"]["anchors_world_m"], C["anchors_world_m"], F["baseline_state"], S))
        movement = float(np.linalg.norm(np.mean(box, axis=0) - np.mean(np.array(F["baseline_carton"]["box_world_m"]), axis=0)))
        allowance = max(0.0036, 2 * (C["edge_u_m"] + F["baseline_carton"]["edge_u_m"]) + 0.0008)
        R = geo.rotation(S["tcp_quaternion_xyzw"]); R0 = geo.rotation(F["baseline_state"]["tcp_quaternion_xyzw"])
        normal_error = float(math.acos(float(np.clip(np.dot(R @ R0.T @ np.array(F["baseline_carton"]["normal_world"]), C["normal_world"]), -1, 1))))
        E["retention"] = {"before_frame": F["baseline_state"]["frame_id"], "after_frame": S["frame_id"], "attachment_error_m": error, "allowance_m": allowance, "normal_error_rad": normal_error, "observed_carton_displacement_m": movement, "actual_hand_translation_m": (tcp - F["baseline_state"]["tcp_position_world_m"]).tolist()}
        if error > allowance or movement <= max(0.03, 2 * allowance) or normal_error > C["normal_u_rad"] + F["baseline_carton"]["normal_u_rad"]:
            return finish("needs_replan", "Preserved current measurements do not support the acknowledged differential retention and material transfer.")
        if margin < required or bottom < 0.012: return finish("blocked", "Unchanged fit or above-rim margin fails; no margin is weakened and no old target is retried.")
        lo, hi = np.array(S["own_geometry"]["finger_low_offset_tool_m"]), np.array(S["own_geometry"]["finger_high_offset_tool_m"])
        lo[1] -= 0.020; hi[1] += 0.020
        finger_pad = 0.004 + pt + rt * float(max(np.linalg.norm(corners(lo, hi), axis=1)))
        T = np.eye(4); T[:3, :3], T[:3, 3] = R, tcp
        fingers = geo.transform(corners(lo - finger_pad, hi + finger_pad), T)
        carton_pad = C["u_m"] + pt + lever * rt
        V = np.concatenate([corners(box.min(axis=0) - carton_pad, box.max(axis=0) + carton_pad), fingers, fingers + [0.0, 0.0, 0.020]])
        jaw_reserve = float(min(fingers[:, 2]) - B["rim_high_m"] - B["u_m"])
        E["envelope"] = {"fit_margin_m": margin, "required_margin_m": required, "carton_above_rim_reserve_m": bottom, "expanded_finger_above_rim_reserve_m": jaw_reserve, "position_tolerance_m": pt, "rotation_tolerance_rad": rt, "finger_padding_m": finger_pad, "additional_opening_each_side_m": 0.020, "withdrawal_world_z_m": 0.020}
        if jaw_reserve < 0.012: return finish("blocked", "The locally expanded finger envelope lacks the unchanged bowl-height reserve.")
        cameras = {c: api.camera(c) for c in ["agentview", "robot0_eye_in_hand"]}
        if any(c["frame_id"] != S["frame_id"] for c in cameras.values()): return finish("blocked", "Calibration and retained geometry are not simultaneous.")
        projections = {c: project(V, cam) for c, cam in cameras.items()}
        F["local_envelope_world_m"], F["local_cameras"] = V.tolist(), cameras
        save()
        if api.state()["budgets"]["gpt_remaining"] < 1: return finish("blocked", "No observation-review allowance remains for the new cross-camera bottle separation measurement.")
        pixel = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}
        outline = {"type": "array", "items": pixel, "maxItems": 12}
        fields = {"carton": ["same_retained_carton", "changed", "unknown"], "bowl": ["same_upright", "changed", "unknown"], "bottle": ["same_neighboring_bottle", "unknown"], "contact": ["none_visible", "external_contact", "unknown"], "other_external": ["visible_local_separation", "contact", "unknown"], "notes": {"type": "string", "maxLength": 2000}}
        for tag in ["agent", "wrist"]:
            fields[tag + "_coverage"] = ["complete_local_boundary", "surface_only", "unknown"]
            fields[tag + "_outline"] = outline
            fields[tag + "_support_edges"] = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 11}, "maxItems": 4}
            fields[tag + "_spares"] = {"type": "array", "items": pixel, "maxItems": 2}
        question = ("New local separation measurement only, at the unchanged achieved approach. Do not repeat rim fitting or demand a global bottle-top height certificate. The context projects a conservative carton plus finger-opening and upward-withdrawal envelope into both cameras. Identify the neighboring green bottle, not the carton or robot. Request b0,b1,b2 as agentview depth points and b3,b4,b5 as wrist depth points on exposed envelope-facing bottle surfaces and transitions immediately adjacent to the overlap. Choose interior depth-valid patches, not mixed silhouette pixels; they need not be corresponding landmarks. Provide up to two DIFFERENT spare interior pixels per camera if depth fails. For each view, supply a conservative convex polygon around the locally relevant bottle silhouette in perimeter order ONLY when its envelope-facing boundary is observable across the whole relevant band. The polygon may end outside that band; remote bottle extrema are not needed. support_edges are zero-based polygon-edge indices whose supporting line bounds the bottle on its far side throughout the band; never mark an artificial crop edge or a chord cutting into a curved silhouette. The program will require the entire projected assembly to lie within that edge's tangential span and will test a metric separating camera-ray plane with pixel and metric allowances. complete_local_boundary means no hidden section in that band could invalidate the observed local boundary; otherwise use surface_only or unknown and give the exact missing segment. Do not infer hidden clearance from a few depth points or from the robot occluding the bottle. If a polygon is supplied, its bottle depth samples should lie inside it. Check the same carton and upright bowl without requesting another rim reconstruction. other_external concerns only other bodies relevant to this local envelope, not all scene objects. Report contact only if observed. No motion or release is authorized by this review.")
        r = api.review(question, context=plain({"frame_id": S["frame_id"], "projected_envelope_pixels": projections, "envelope": E["envelope"], "current_carton": C, "bowl_center_xy_m": B["center_xy_m"], "bowl_rim_high_m": B["rim_high_m"], "retired_correction": E["retired_target"]}), fields=fields)
        p, bad = r["parameters"], set(x["name"] for x in r["measurement_errors"])
        E["review"] = {"frame_id": r["frame_id"], "parameters": p}; E["measurement_errors"] = r["measurement_errors"]
        valid = {}
        for i in range(6):
            name = "b" + str(i); cam = "agentview" if i < 3 else "robot0_eye_in_hand"
            if name in r["points"] and name not in bad:
                v = r["points"][name]
                if v["frame_id"] == r["frame_id"] and v["camera"] == cam and all(np.isfinite(v["world_m"])): valid[name] = v
        F["local_obstacle_samples"] = valid
        save()
        if r["status"] == "stop": return finish("abort", "Fresh observation review requested stopping.")
        if r["frame_id"] != S["frame_id"] or api.state()["frame_id"] != S["frame_id"]: return finish("blocked", "Physical frame changed during this sensing-only repair.")
        if p["carton"] == "changed" or p["bowl"] == "changed" or p["contact"] == "external_contact" or p["other_external"] == "contact":
            return finish("needs_replan", "Fresh identity or external-contact evidence invalidates the present approach.")
        E["local_gaps"], E["separation_tests"] = [], []
        for tag, cam in [("agent", "agentview"), ("wrist", "robot0_eye_in_hand")]:
            samples = [v for v in valid.values() if v["camera"] == cam]
            for j, pix in enumerate(p[tag + "_spares"]):
                if len(samples) >= 2: break
                try:
                    v = api.point(cam, pix, radius=1)
                    if v["frame_id"] == S["frame_id"] and all(np.isfinite(v["world_m"])):
                        valid[tag + "_spare" + str(j)] = v; samples.append(v)
                except Exception as ex: E["measurement_errors"].append({"name": tag + "_spare" + str(j), "error": str(ex)})
            if len(samples) < 2:
                E["local_gaps"].append(tag + ": fewer than two valid current bottle surfaces"); continue
            W = np.array([v["world_m"] for v in samples])
            if float(max(np.linalg.norm(W - W[0], axis=1))) < 4 * 0.0005:
                E["local_gaps"].append(tag + ": samples insufficiently distinct relative to the working depth floor"); continue
            P = np.array(p[tag + "_outline"]); U = projections[cam]
            if p[tag + "_coverage"] != "complete_local_boundary" or len(P) < 3 or U is None:
                E["local_gaps"].append(tag + ": local envelope-facing boundary unresolved; surface depths alone are not a clearance bound"); continue
            H = np.concatenate([P, np.ones((len(P), 1))], axis=1)
            Z = np.array([[v["pixel"][0], v["pixel"][1], 1.0] for v in samples])
            lines, usable = [], True
            for i in range(len(P)):
                line = np.cross(H[i], H[(i + 1) % len(P)]); values = H @ line
                if max(values) <= 0: line = -line; values = -values
                if min(values) < -0.00001 or max(values) < 0.00001 or min(Z @ line) < -0.00001: usable = False
                lines.append(line)
            if not usable:
                E["local_gaps"].append(tag + ": polygon is degenerate, nonconvex, or does not enclose its measured bottle samples"); continue
            K, M = np.array(cameras[cam]["K"]), np.array(cameras[cam]["camera_to_world_opencv"])
            for i in p[tag + "_support_edges"]:
                if i >= len(P): continue
                edge = P[(i + 1) % len(P)] - P[i]; length = float(np.linalg.norm(edge))
                if length < 4: continue
                tangent = edge / length; interval = (U - P[i]) @ tangent
                if min(interval) < 2 or max(interval) > length - 2: continue
                line = lines[i].copy(); line[2] += 2 * float(np.linalg.norm(line[:2]))
                n = M[:3, :3] @ (K.T @ line); n = n / np.linalg.norm(n)
                gap = float(-max((V - M[:3, 3]) @ n) - 0.0005)
                E["separation_tests"].append({"camera": cam, "support_edge_index": i, "plane_normal_world": n.tolist(), "camera_origin_world_m": M[:3, 3].tolist(), "gap_after_allowances_m": gap, "required_gap_m": required, "pixel_allowance": 2, "working_depth_floor_m": 0.0005, "tangential_band_covered": True})
        F["local_obstacle_samples"] = valid
        adequate = [t for t in E["separation_tests"] if t["gap_after_allowances_m"] >= required]
        cross_view = all(sum(1 for v in valid.values() if v["camera"] == cam) >= 2 for cam in cameras)
        identities = p["carton"] == "same_retained_carton" and p["bowl"] == "same_upright" and p["bottle"] == "same_neighboring_bottle"
        if not identities or not cross_view or p["contact"] != "none_visible" or p["other_external"] != "visible_local_separation" or len(adequate) == 0:
            return finish("blocked", "Cross-camera local evidence remains insufficient: " + str(E["local_gaps"]) + "; no supporting ray-plane gap, identity, or other-body relation is silently assumed. " + p["notes"])
        E["supported_option"] = {"frame_id": S["frame_id"], "mode": "current_attitude_above_rim_opening_then_upward_withdrawal_envelope", "envelope": E["envelope"], "local_bottle_separation": adequate, "scope": "Current measured approach and local opening option only; no release authorization, descent, actuator-travel test or containment result."}
        return finish("stage_complete", "Fresh cross-camera local separation evidence supports the already achieved retained approach, unchanged fit margin and bounded finger-clearance option. No new motion or release occurred.")
    except Exception as ex:
        return finish("blocked", "Local sensing/geometry could not be completed; preserved actual state and measurements require supervision: " + str(ex))

def main(api):
    key, m, calls = "grasp_recovery_v3", {}, [0]
    start = api.state()
    questions = {}
    for a in ["x", "y", "z", "rx", "ry", "rz"]:
        subject = "world translation " + a if len(a) == 1 else "world rotation-vector component " + a
        questions[a] = {"type": "choice", "instructions": "For " + subject + ", read state.processed_features.axes." + a + ".goal_relation. Select negative for decrease, positive for increase, hold for within_tolerance. Do not infer object geometry.", "criteria": {"negative": "Decrease this world component.", "hold": "This component is within tolerance.", "positive": "Increase this world component."}}
    questions["gripper"] = {"type": "choice", "instructions": "Deliver state.processed_features.objective.gripper exactly. Keep preserves the existing command; it does not mean reopen.", "criteria": {"open": "Deliver requested opening.", "close": "Deliver requested closing.", "keep": "Preserve the previous command."}}

    def save():
        m["last_state"], m["slice_calls"] = api.state(), calls[0]
        api.checkpoint(key, m)

    def halt(reason, status="blocked"):
        m["return_status"] = status
        raise Exception(reason)

    def finish(status, reason):
        m["reason"] = reason
        save()
        return {"stage_status": status, "reason": reason, "evidence": {"phase": m.get("phase"), "prior_execution": m.get("prior_execution"), "old_registration_diagnosis": m.get("old_registration_diagnosis"), "registration": m.get("registration"), "geometry": m.get("geometry"), "contact_candidate": m.get("contact_candidate"), "last_review": m.get("last_review"), "last_receipt": m.get("receipt"), "measurement_gap": m.get("measurement_gap"), "state": m["last_state"]}, "handoff": {"checkpoint_keys": ["grasp_stage_v1", "grasp_stage_v2", key], "phase": m.get("phase"), "pending": m.get("pending"), "tracker": m.get("tracker"), "reference_rules": "World meters and xyzw tool quaternions. grasp_stage_v1/v2 remain untouched historical records, including five acknowledged approach controls through frame 15. grasp_recovery_v3 contains new depth and visible-boundary measurements with their frames/cameras, tracker creation identity and reference samples, registration diagnostics, actual receipts, free-air target and current finite-pad candidate. Derived boundary points use the measured locally horizontal top plane, not unseen geometry. Tracker uncertainty is not contact-height accuracy. Revalidate affected references after movement. A ready_for_contact phase is only a sensing handoff within grasp, NOT a grasp-stage effect. No closure, descent, lift or release is performed by this recovery slice; preserve the actual gripper command. Contact corridor, actual contact margins and subsequent independent lift/rigid-following evidence remain necessary."}, "completion_proposed": False}

    def observe(question, context, fields):
        if api.state()["budgets"]["gpt_remaining"] < 2:
            halt("Observation budget reserve reached; preserve partial measurements.", "yield")
        r = api.review(question, context=context, fields=fields)
        m["last_review"] = {"frame_id": r["frame_id"], "parameters": r["parameters"], "measurement_errors": r["measurement_errors"], "explanation": r["explanation"][:900]}
        if r["status"] == "stop":
            halt("Fresh observation requested a stop: " + r["explanation"][:600], "abort")
        return r

    def compact_reference(g):
        return {n: g[n] for n in ["reference_frame_id", "top_corners_world_m", "top_z_m", "table_z_m", "width_m", "length_m"]}

    def measure(reference, require_side):
        fields = {"identity": ["same_cream_cheese", "wrong", "unknown"], "support": ["flat_on_table", "changed", "unknown"], "boundary": ["full_top_rectangle", "occluded", "unknown"], "camera": ["agentview", "robot0_eye_in_hand"], "corners": {"type": "array", "minItems": 0, "maxItems": 4, "items": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "number", "minimum": 0, "maximum": 767}}}, "side_identity": ["visible_long_side", "unavailable", "unknown"]}
        names, cache, gap, gap_status = ["t0", "t1", "t2", "t3", "s0", "s1", "s2", "s3"], {}, "", "blocked"
        frame = api.state()["frame_id"]
        for attempt in range(2):
            r = observe("Measure the SAME cream cheese, not the bowl or table texture. Supply four visible TOP boundary corners in cyclic order and their camera; use an empty corners array if unavailable. Request t0,t1,t2,t3 on four separated top-interior quadrants, inset from edges, and s0,s1,s2,s3 on distributed bare TABLE patches around the package, not stove or shadows. Request side on a visible LONG SIDE wall interior, preferably from the oblique agentview, not its top or mixed-depth silhouette. Side depth is optional for the distant free-air approach but required for the closer sensing handoff. Only request missing/rejected point names from the retained same-frame samples. A retry must use different interior patches or the other camera, resolving the supplied gap; do not repeat failed edge pixels. These are measurements, not authorization for contact.", {"attempt": attempt, "require_side": require_side, "historical_reference": reference, "retained_current_points": cache, "gap": gap, "state": api.state()}, fields)
            p = r["parameters"]
            if r["frame_id"] != frame:
                halt("Measurement batch changed physical frame unexpectedly.")
            if p["identity"] == "wrong" or p["support"] == "changed":
                halt("Fresh identity or support contradicts the stationary approach.", "needs_replan")
            errors = [e["name"] for e in r["measurement_errors"]]
            if p["identity"] == "same_cream_cheese" and p["support"] == "flat_on_table":
                for n in names + ["side"]:
                    if n in r["points"] and n not in errors and r["points"][n]["frame_id"] == frame:
                        cache[n] = r["points"][n]
            m["partial"] = {"frame_id": frame, "points": cache, "parameters": p, "measurement_errors": r["measurement_errors"]}
            save()
            if not all(n in cache for n in names) or p["identity"] != "same_cream_cheese" or p["support"] != "flat_on_table" or p["boundary"] != "full_top_rectangle" or len(p["corners"]) != 4:
                gap = "Missing valid distributed top/table depths, same-package support, or visible top boundary."
                continue
            try:
                top = np.array([cache[n]["world_m"] for n in names[:4]])
                table = np.array([cache[n]["world_m"] for n in names[4:]])
                ft, fs = geo.plane(top), geo.plane(table)
                zt, zs = float(np.mean(top[:, 2])), float(np.mean(table[:, 2]))
                if max(ft["rms_m"], fs["rms_m"]) > 0.0015 or min(ft["in_plane_spread_m"]) < 0.006 or min(fs["in_plane_spread_m"]) < 0.015 or max(float(np.ptp(top[:, 2])), float(np.ptp(table[:, 2]))) > 0.003:
                    raise ValueError("Distributed samples fail the unchanged plane/spread/horizontal-model thresholds.")
                corners = np.array([api.plane_point(p["camera"], pixel, [0.0, 0.0, 1.0, -zt])["world_m"] for pixel in p["corners"]])
                edges = np.roll(corners, -1, axis=0) - corners
                lengths = np.linalg.norm(edges, axis=1)
                units = edges / lengths[:, None]
                if min(lengths) < 0.020 or max(lengths) > 0.180 or not 0.012 <= zt - zs <= 0.070 or abs(float(np.dot(units[0], units[1]))) > 0.12 or float(np.dot(units[0], units[2])) > -0.98 or float(np.dot(units[1], units[3])) > -0.98 or max(abs(float(lengths[0] - lengths[2])), abs(float(lengths[1] - lengths[3]))) > 0.005:
                    raise ValueError("Visible boundary or dimensions fail the rectangular-package model.")
                distances = np.linalg.norm(corners[:, None, :] - np.array(reference["top_corners_world_m"])[None, :, :], axis=2)
                drift = max(float(np.max(np.min(distances, axis=0))), float(np.max(np.min(distances, axis=1))))
                if drift > 0.004 or abs(zt - reference["top_z_m"]) > 0.002 or abs(zs - reference["table_z_m"]) > 0.002:
                    gap_status = "needs_replan"
                    raise ValueError("Current distributed geometry disagrees with the stationary reference; confirm using another view.")
                direction = units[0] if lengths[0] >= lengths[1] else units[1]
                center = np.mean(corners, axis=0)
                g = {"reference_frame_id": frame, "camera": p["camera"], "corner_pixels": p["corners"], "top_samples_world_m": top.tolist(), "table_samples_world_m": table.tolist(), "top_corners_world_m": corners.tolist(), "top_center_world_m": center.tolist(), "top_z_m": zt, "table_z_m": zs, "width_m": float(min(lengths)), "length_m": float(max(lengths)), "long_axis_world": direction.tolist(), "top_fit": ft, "table_fit": fs, "boundary_drift_m": drift, "surface_allowance_m": max(0.001, 3.0 * float(ft["rms_m"]), 3.0 * float(fs["rms_m"]), float(np.ptp(top[:, 2])) / 2.0, float(np.ptp(table[:, 2])) / 2.0), "point_provenance": {n: {"camera": cache[n]["camera"], "frame_id": cache[n]["frame_id"], "source": cache[n]["source"], "pixel": cache[n]["pixel"]} for n in names}, "side_valid": False, "assumptions": "Same visible flat package on a locally horizontal table. Boundary rays intersect a validated horizontal top approximation. Surface allowance is an engineering reserve, not calibrated accuracy; no hidden bottom or side is reconstructed."}
                if "side" in cache and p["side_identity"] == "visible_long_side":
                    side = np.array(cache["side"]["world_m"])
                    transverse = np.array([-direction[1], direction[0], 0.0])
                    transverse = transverse / np.linalg.norm(transverse)
                    side_error = abs(abs(float(np.dot(side - center, transverse))) - g["width_m"] / 2.0)
                    g["side"], g["side_plane_residual_m"] = cache["side"], side_error
                    g["side_valid"] = bool(side_error <= 0.004 and abs(float(np.dot(side - center, direction))) <= g["length_m"] / 2.0 - 0.002 and zs + 0.001 < float(side[2]) < zt - 0.001)
                m["geometry"] = g
                if require_side and not g["side_valid"]:
                    gap = "Top, boundary and table are valid, but a depth-valid identified long-side wall remains unresolved."
                    cache.pop("side", None)
                    save()
                    continue
                m.pop("partial", None)
                m.pop("measurement_gap", None)
                return g
            except Exception as error:
                gap = str(error)
                m["rejected_measurement"] = {"frame_id": frame, "attempt": attempt, "reason": gap}
                cache = {}
        m["measurement_gap"] = gap
        halt(gap, gap_status)

    def registration(tr):
        t = api.track_update(tr["handle"])
        d = {n: t[n] for n in ["status", "frame_id", "reference_frame_id"]}
        d["accepted"] = False
        if t["status"] != "tracked":
            d["reason"] = t.get("reason", "Unknown patch registration in both-view search.")
            return d
        for n in ["camera", "matches", "inliers", "rms_m", "inlier_spread_m", "uncertainty_floor_m", "transform_initial_world_to_current_world"]:
            d[n] = t[n]
        spread = sorted(t["inlier_spread_m"])
        checks = {"reference_identity": t["reference_frame_id"] == tr["reference_frame_id"], "inliers": t["inliers"] >= 12, "inlier_fraction": t["inliers"] / max(1, t["matches"]) >= 0.60, "rms": t["rms_m"] <= 0.002, "uncertainty": t["uncertainty_floor_m"] <= 0.003, "distributed_support": len(spread) >= 2 and spread[-2] >= 0.006}
        d["failed_checks"], d["accepted"] = [n for n in checks if not checks[n]], all(checks.values())
        if d["accepted"]:
            pts = geo.transform(tr["reference_top_samples_world_m"], t["transform_initial_world_to_current_world"])
            d["stationarity_displacement_m"] = float(np.max(np.linalg.norm(pts - np.array(tr["reference_top_samples_world_m"]), axis=1)))
        return d

    def new_tracker(g):
        poly = np.array(g["corner_pixels"])
        poly = np.mean(poly, axis=0) + 0.90 * (poly - np.mean(poly, axis=0))
        m["tracker_initializations"] = m.get("tracker_initializations", 0) + 1
        try:
            t = api.track_init(g["camera"], poly.tolist())
            tr = {"handle": t["handle"], "camera": g["camera"], "polygon": poly.tolist(), "reference_frame_id": t["frame_id"], "reference_top_samples_world_m": g["top_samples_world_m"], "identity": "The same cream cheese printed top interior, freshly bounded in this camera/frame; not table or gripper."}
            m["tracker"], m["registration"] = tr, registration(tr)
            m["tracker_history"] = (m.get("tracker_history", []) + [tr])[-2:]
        except Exception as error:
            m["registration"] = {"accepted": False, "reason": str(error), "frame_id": api.state()["frame_id"]}
        save()

    def finger_bottom(s):
        own, R = s["own_geometry"], geo.rotation(s["tcp_quaternion_xyzw"])
        lo, hi = own["finger_low_offset_tool_m"], own["finger_high_offset_tool_m"]
        box = np.array([[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]])
        return float(np.min(((box - np.array(own["pad_center_in_tool_m"])) @ R.T)[:, 2]))

    try:
        old = api.recall("grasp_stage_v2")["value"]
        for record in api.recall():
            if record["key"] == key:
                m = api.recall(key)["value"]
        if m.get("pending"):
            halt("An action intent lacks a saved receipt. Reconcile acknowledged execution; do not repeat it.")
        if m and m["last_state"]["native_steps"] != start["native_steps"]:
            halt("Physical steps occurred outside this saved recovery slice; revalidate its dependencies.")
        if start["last_gripper_command"] != "open":
            halt("The gripper is not in the acknowledged open approach state; never reopen automatically.")
        if not m:
            if old["phase"] != "hover" or old.get("pending") or old["last_state"]["native_steps"] != start["native_steps"]:
                halt("Legacy approach checkpoint does not match actual acknowledged execution.")
            m = {"phase": "measure_initial", "prior_execution": {"checkpoint": "grasp_stage_v2", "frame_id": old["last_state"]["frame_id"], "native_steps": old["last_state"]["native_steps"], "approach_controls": old["slice_calls"], "last_receipt": old["receipt"], "contact_or_closure_acknowledged": False}, "tracker_initializations": 0}
            tr = dict(old["tracker"])
            tr["reference_top_samples_world_m"] = old["geometry"]["top_samples_world_m"]
            m["old_registration_diagnosis"] = registration(tr)
        if m["phase"] == "ready_for_contact":
            return finish("yield", "Recovery handoff already exists. No additional motion or repeated unchanged review; current grasp still needs contact and lift evidence.")
        if m["phase"] == "measure_initial":
            g = measure(compact_reference(old["geometry"]), False)
            m["initial_reference"] = compact_reference(g)
            new_tracker(g)
            direction = np.array(g["long_axis_world"])
            if float(np.dot(direction, geo.rotation(api.state()["tcp_quaternion_xyzw"])[:, 0])) < 0:
                direction = -direction
            m["quaternion"] = api.compose([1.0, 0.0, 0.0, 0.0], [0.0, 0.0, math.atan2(float(direction[1]), float(direction[0]))])
            m["hover_target"] = [g["top_center_world_m"][0], g["top_center_world_m"][1], g["top_z_m"] + 0.105]
            m["phase"] = "authorize_hover"
            save()
        if m["phase"] in ["authorize_hover", "hover"]:
            r = observe("Authorize ONLY the remaining observation-producing free-air approach from the actual current pose to hover_target with the supplied orientation and own finger envelope. The target is 105 mm above the newly measured package top, higher than the old 75 mm target, to keep more top texture visible. Is this remaining swept route visibly free of bottle, bowl, stove and cabinet with at least 10 mm separation? Confirm the same package remains on the table and the gripper is visibly empty. Do not infer hidden clearance. A rejected tracker is diagnostic only: direct current distributed depth/boundary measurements, not that transform, define this high approach. No descent to contact or closure is authorized.", {"state": api.state(), "hover_target": m["hover_target"], "quaternion": m["quaternion"], "geometry": m["geometry"], "registration": m["registration"]}, {"identity": ["same_package", "wrong", "unknown"], "support": ["on_table", "changed", "unknown"], "gripper": ["visibly_empty", "not_empty", "unknown"], "sweep": ["visibly_clear", "obstructed", "unknown"]})
            if r["parameters"] != {"identity": "same_package", "support": "on_table", "gripper": "visibly_empty", "sweep": "visibly_clear"}:
                halt("The remaining high observation approach lacks current identity, empty-gripper or visible-corridor evidence.")
            m["phase"] = "hover"
            save()
            for unused in range(22):
                s = api.state()
                if calls[0] >= 22 or s["native_steps"] - start["native_steps"] + 3 > 66 or s["budgets"]["jev_remaining"] < 1 or s["budgets"]["native_steps_remaining"] < 3:
                    return finish("yield", "Bounded recovery slice ended with acknowledged free-air progress; no contact or grasp claimed.")
                m["pending"] = {"phase": "hover", "before_frame_id": s["frame_id"], "target_pad_world_m": m["hover_target"], "quaternion": m["quaternion"], "gripper": "keep"}
                save()
                r = api.control(m["hover_target"], m["quaternion"], "keep", questions, features={"source": "Fresh selected RGB-D top/table patches, visible-boundary ray intersections, own finger geometry and typed visible-route review.", "phase": "grasp_observation_approach_only", "geometry_frame_id": m["geometry"]["reference_frame_id"], "top_z_m": m["geometry"]["top_z_m"], "table_z_m": m["geometry"]["table_z_m"], "observation_height_above_top_m": 0.105, "registration_accepted": m["registration"]["accepted"], "contact_authorized": False}, tool_point="pad_center", translation_limit=0.020, rotation_limit=0.10, steps=3, position_tolerance=0.003, rotation_tolerance=0.01)
                calls[0] += 1
                m["receipt"], m["pending"] = r, None
                save()
                if r["choices"].get("gripper") != "keep":
                    halt("Acknowledged gripper choice mismatched keep.")
                delta = np.array(r["target_tcp"]) - np.array(r["before"])
                for i, a in enumerate(["x", "y", "z"]):
                    if abs(float(delta[i])) > 0.003 / math.sqrt(3) and ((delta[i] > 0 and r["choices"][a] == "negative") or (delta[i] < 0 and r["choices"][a] == "positive")):
                        halt("Acknowledged translation direction opposed its target.")
                if r["status"] == "stalled":
                    halt("First translation stall; no repeated contact or automatic retry.")
                s = api.state()
                clearance = float(geo.pad_position(s)[2]) + finger_bottom(s) - m["geometry"]["table_z_m"] - m["geometry"]["surface_allowance_m"]
                m["measured_finger_table_clearance_m"] = clearance
                if clearance < 0.006:
                    halt("Actual finger/table clearance fails the unchanged 6 mm requirement.")
                if "tracker" in m and (calls[0] % 4 == 0 or r["status"] == "reached"):
                    m["registration"] = registration(m["tracker"])
                    if m["registration"]["accepted"] and m["registration"]["stationarity_displacement_m"] > 0.004:
                        halt("Accepted same-patch observations show package movement during the approach.", "needs_replan")
                if r["status"] == "reached":
                    m["phase"] = "measure_closer"
                    save()
                    break
            if m["phase"] == "hover":
                return finish("yield", "Free-air control bound reached; resume from the saved actual pose, not frame 0.")
        if m["phase"] == "measure_closer":
            g = measure(m["initial_reference"], True)
            if "tracker" in m:
                m["registration"] = registration(m["tracker"])
            if not m["registration"]["accepted"] and m["tracker_initializations"] < 2:
                new_tracker(g)
            if not m["registration"]["accepted"]:
                halt("Closer direct geometry is saved, but distributed same-package registration still fails unchanged acceptance thresholds.")
            if m["registration"]["stationarity_displacement_m"] > 0.004:
                halt("Fresh accepted patch registration contradicts package stationarity.", "needs_replan")
            s = api.state()
            R, own = geo.rotation(s["tcp_quaternion_xyzw"]), s["own_geometry"]
            if float(R[2, 2]) > -0.98:
                halt("Current attitude does not support the near-downward finite-pad candidate.")
            h = np.array(own["pad_extent_in_tool_m"]) / 2.0
            lower = np.array([[x, y, h[2]] for x in [-h[0], h[0]] for y in [-h[1], h[1]]]) @ R.T
            upper = np.array([[x, y, -h[2]] for x in [-h[0], h[0]] for y in [-h[1], h[1]]]) @ R.T
            fb, pb, pt, u = finger_bottom(s), float(np.max(lower[:, 2])), float(np.min(upper[:, 2])), g["surface_allowance_m"]
            low, high = g["table_z_m"] + 0.006 + u - fb, g["top_z_m"] - u - 0.003 - pb
            m["contact_candidate"] = {"frame_id": s["frame_id"], "finger_bottom_relative_to_pad_m": fb, "common_pad_bottom_relative_m": pb, "common_pad_top_relative_m": pt, "minimum_pad_center_z_m": low, "maximum_pad_center_z_m": high, "feasible_interval_m": high - low, "candidate_z_m": (low + high) / 2.0, "surface_allowance_m": u, "required_table_clearance_m": 0.006, "required_vertical_overlap_m": 0.003, "pose_reserve_each_end_m": 0.0006, "contact_authorized": False}
            if high - low < 0.0012 or pt <= pb:
                halt("Fresh closer surfaces and actual attitude leave insufficient finite-pad height reserve; no descent was attempted.")
            m["phase"] = "ready_for_contact"
            return finish("yield", "Recovered distributed current boundary, side and table evidence at a checked free-air observation pose. Grasp remains unperformed; hand off the measured contact candidate for the next local grasp decision.")
        halt("Unknown recovery phase; reconcile saved physical execution.")
    except Exception as error:
        status = m.pop("return_status", "blocked")
        return finish(status, str(error))

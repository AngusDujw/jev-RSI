def main(api):
    key, m, count = "grasp_stage_v1", {}, [0]
    questions = {}
    for axis in ["x", "y", "z", "rx", "ry", "rz"]:
        questions[axis] = {"type": "choice", "instructions": "For this world position or world rotation-vector component use its explicit goal_relation: decrease means negative, increase means positive, within_tolerance means hold. Do not infer contact or unseen geometry.", "criteria": {"negative": "Decrease this world component.", "hold": "The component is within its supplied tolerance.", "positive": "Increase this world component."}}
    questions["gripper"] = {"type": "choice", "instructions": "Use objective.gripper exactly: open for open, close for close, keep for keep. Keep does not reopen a possibly held package. Closure is not retention evidence.", "criteria": {"open": "Deliver requested opening.", "close": "Deliver requested closing.", "keep": "Preserve the existing gripper command."}}

    def save():
        m["state"], m["slice_calls"] = api.state(), count[0]
        api.checkpoint(key, m)

    def stop(reason, status="blocked"):
        m["fault_status"] = status
        raise Exception(reason)

    def result(status, reason):
        save()
        return {"stage_status": status, "reason": reason, "evidence": {"state": m["state"], "last_receipt": m.get("receipt"), "partial_measurements": m.get("partial"), "retention": m.get("retention"), "effect": m.get("effect"), "error": m.get("error")}, "handoff": {"checkpoint_key": key, "phase": m.get("phase"), "pending_action": m.get("pending"), "geometry": m.get("geometry"), "tracker": m.get("tracker"), "latest_track": m.get("track"), "package_top_center_in_tool_m": m.get("top_center_in_tool_m"), "reference_rules": "World meters; tool quaternions xyzw. Pixels belong only to their recorded frame and camera. Geometry contains historical visible top/table measurements, not a bowl model. Revalidate the same package patch and affected clearance after motion. prelift_state and prelift_transform preserve the measured lift-test baseline. Preserve current gripper command; never reopen automatically or infer retention from closure."}, "completion_proposed": False}

    def observe(question, context, fields):
        r = api.review(question, context=context, fields=fields)
        if r["status"] == "stop":
            stop("Observation reviewer requested stop: " + r["explanation"], "abort")
        return r

    def measured(r, names):
        return all(n in r["points"] for n in names) and not any(e["name"] in names for e in r["measurement_errors"])

    def remember_partial(r):
        m["partial"] = {"frame_id": r["frame_id"], "points": r["points"], "measurement_errors": r["measurement_errors"], "parameters": r["parameters"]}
        save()

    def track(mode):
        t = api.track_update(m["tracker"]["handle"])
        if t["status"] != "tracked":
            m["track"] = t
            stop("Package patch tracking unknown; no pose extrapolation or further contact.")
        spread = sorted(t["inlier_spread_m"])
        u = max(float(t["rms_m"]), float(t["uncertainty_floor_m"]))
        m["track"] = {k: t[k] for k in ["frame_id", "reference_frame_id", "camera", "transform_initial_world_to_current_world", "inliers", "matches", "rms_m", "uncertainty_floor_m", "inlier_spread_m"]}
        if t["inliers"] < 12 or t["inliers"] / max(1, t["matches"]) < 0.55 or t["rms_m"] > 0.002 or u > 0.003 or len(spread) < 2 or spread[-2] < 0.008:
            stop("Registration quality or two-dimensional feature coverage is inadequate.")
        initial = m["geometry"]["top_samples_world_m"]
        pts = geo.transform(initial, t["transform_initial_world_to_current_world"])
        s = api.state()
        if mode == "stationary":
            error = float(np.max(np.linalg.norm(pts - np.array(initial), axis=1)))
            m["stationarity_error_m"] = error
            if error > 0.005:
                stop("Package moved before grasp; old approach is invalid.", "needs_replan")
        if mode == "follow":
            before = geo.transform(initial, m["prelift_transform"])
            error = float(geo.attachment_error(before, pts, m["prelift_state"], s))
            dz_hand = float(geo.pad_position(s)[2] - geo.pad_position(m["prelift_state"])[2])
            dz_package = float(np.mean(pts[:, 2] - before[:, 2]))
            m["retention"] = {"frame_id": t["frame_id"], "attachment_error_m": error, "hand_rise_m": dz_hand, "package_rise_m": dz_package, "registration_uncertainty_m": u, "point_source": "Original measured top samples propagated by accepted same-patch registrations before and after hand motion."}
            if error > 0.008:
                stop("Package failed measured hand-following within 8 mm; stop without reopening.", "needs_replan")
        return t, pts, s

    def act(target, grip, limit):
        if count[0] >= 22:
            stop("Internal slice guard reached before an unbudgeted action.")
        m["pending"] = {"phase": m["phase"], "target_pad_world_m": target, "quaternion_xyzw": m["quaternion"], "gripper": grip, "before_state": api.state()}
        save()
        features = {"source": "Program RGB-D measurements, patch registration, own geometry and fresh visual corridor review.", "phase": m["phase"], "registration": m.get("track"), "measured_jaw_gap": m.get("jaw_gap"), "retention": m.get("retention"), "geometry_uncertainty_m": 0.003, "interpretation": "Direction and gripper delivery only. These features do not certify collision clearance or retention."}
        r = api.control(target, m["quaternion"], grip, questions, features=features, tool_point="pad_center", translation_limit=limit, rotation_limit=0.10, steps=3, position_tolerance=0.003, rotation_tolerance=0.025)
        count[0] += 1
        m["receipt"], m["pending"] = r, None
        save()
        if r["choices"].get("gripper") != grip:
            stop("Acknowledged Jev gripper choice differs from requested command.")
        delta = np.array(r["target_tcp"]) - np.array(r["before"])
        for i, axis in enumerate(["x", "y", "z"]):
            c = r["choices"].get(axis)
            if abs(float(delta[i])) > 0.003 / math.sqrt(3) and ((delta[i] > 0 and c == "negative") or (delta[i] < 0 and c == "positive")):
                stop("Acknowledged Jev translation direction opposes target.")
        if r["status"] == "stalled":
            stop("Motion stalled; do not repeat this contact or silently change target.")
        return r

    def move(target, grip, limit, mode):
        for unused in range(22 - count[0]):
            track(mode)
            r = act(target, grip, limit)
            track(mode)
            if r["status"] == "reached":
                return True
        return False

    try:
        for record in api.recall():
            if record["key"] == key:
                m = api.recall(key)["value"]
        if m.get("pending"):
            return result("blocked", "Previous action intent lacks a saved receipt. Reconcile actual acknowledged execution before resuming.")
        if not m:
            m = {"phase": "setup", "initial_state": api.state()}
        if m.get("phase") == "complete":
            m["phase"] = "verify"
        if m["phase"] == "setup":
            if api.state()["last_gripper_command"] != "open":
                return result("blocked", "No checkpoint explains a non-open gripper; observe before any gripper command.")
            fields = {"identity": ["cream_cheese", "ambiguous", "not_visible"], "support": ["flat_on_table", "other", "unknown"], "boundary": ["full_rectangle", "partial", "unknown"], "camera": ["agentview", "robot0_eye_in_hand"], "corners": {"type": "array", "minItems": 0, "maxItems": 4, "items": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "number", "minimum": 0, "maximum": 767}}}}
            names = ["t0", "t1", "t2", "t3", "s0", "s1", "s2", "s3"]
            for attempt in range(2):
                r = observe("Identify the cream cheese separately from the bowl. Return four cyclic true TOP FACE corner pixels in the declared camera if its entire rectangular top boundary is visible, not shadows or lower-side corners. Request named RGB-D points t0,t1,t2,t3 on widely separated interior textured patches of that top and s0,s1,s2,s3 on noncollinear visible tabletop around the package. Avoid depth mixtures. Confirm whether the package rests flat on that table. On retry use different interior depth patches or the other camera, not the same failed pixels.", {"attempt": attempt, "previous_partial": m.get("partial")}, fields)
                remember_partial(r)
                if measured(r, names):
                    break
            p = r["parameters"]
            if p["identity"] != "cream_cheese" or p["support"] != "flat_on_table" or p["boundary"] != "full_rectangle" or len(p["corners"]) != 4 or not measured(r, names):
                return result("blocked", "Need unambiguous flat package identity, visible top boundary and valid distributed top/table depth samples.")
            top = np.array([r["points"][n]["world_m"] for n in names[:4]])
            table = np.array([r["points"][n]["world_m"] for n in names[4:]])
            ft, fs = geo.plane(top), geo.plane(table)
            if ft["rms_m"] > 0.0015 or fs["rms_m"] > 0.0015 or min(ft["in_plane_spread_m"]) < 0.006 or min(fs["in_plane_spread_m"]) < 0.015 or float(np.ptp(top[:, 2])) > 0.003 or float(np.ptp(table[:, 2])) > 0.003:
                stop("Measured top/table do not support distributed horizontal-plane models.")
            zt, zs = float(np.mean(top[:, 2])), float(np.mean(table[:, 2]))
            plane = [0.0, 0.0, 1.0, -zt]
            corners = np.array([api.plane_point(p["camera"], pixel, plane)["world_m"] for pixel in p["corners"]])
            edges = np.roll(corners, -1, axis=0) - corners
            lengths = np.linalg.norm(edges, axis=1)
            if min(lengths) < 0.020 or max(lengths) > 0.180:
                stop("Package boundary dimensions are outside this local grasp model.")
            units = edges / lengths[:, None]
            if abs(float(np.dot(units[0], units[1]))) > 0.12 or float(np.dot(units[0], units[2])) > -0.98 or float(np.dot(units[1], units[3])) > -0.98 or abs(float(lengths[0] - lengths[2])) > 0.005 or abs(float(lengths[1] - lengths[3])) > 0.005 or not 0.012 <= zt - zs <= 0.070:
                stop("Measured boundary or thickness fails the rectangular top-down model.")
            direction = edges[0] if lengths[0] >= lengths[1] else edges[1]
            s = api.state()
            if float(np.dot(direction, geo.rotation(s["tcp_quaternion_xyzw"])[:, 0])) < 0:
                direction = -direction
            yaw = math.atan2(float(direction[1]), float(direction[0]))
            quat = api.compose([1.0, 0.0, 0.0, 0.0], [0.0, 0.0, yaw])
            own = s["own_geometry"]
            lo, hi = own["finger_low_offset_tool_m"], own["finger_high_offset_tool_m"]
            box = np.array([[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]])
            relative = (box - np.array(own["pad_center_in_tool_m"])) @ geo.rotation(quat).T
            bottom = float(np.min(relative[:, 2]))
            grip_z = max(zt - 0.006, zs + 0.006 - bottom)
            if grip_z > zt - 0.003:
                stop("No pad engagement with 6 mm finger/table clearance; do not relax margin.")
            center = np.mean(corners, axis=0)
            m["geometry"] = {"reference_frame_id": r["frame_id"], "camera": p["camera"], "corner_pixels": p["corners"], "top_corners_world_m": corners.tolist(), "top_samples_world_m": top.tolist(), "table_samples_world_m": table.tolist(), "top_plane": plane, "table_plane": [0.0, 0.0, 1.0, -zs], "top_fit_rms_m": float(ft["rms_m"]), "table_fit_rms_m": float(fs["rms_m"]), "top_center_world_m": center.tolist(), "width_m": float(min(lengths)), "length_m": float(max(lengths)), "top_above_table_m": zt - zs, "pad_z_relative_to_top_m": grip_z - zt, "finger_bottom_relative_to_pad_m": bottom, "uncertainty_allowance_m": 0.003, "assumptions": "Visibly flat rectangular package; horizontal top/table models validated only over measured supports. No hidden perimeter or bowl clearance certified."}
            m["quaternion"], m["hover_target"] = quat, [float(center[0]), float(center[1]), zt + 0.070]
            polygon = np.array(p["corners"])
            polygon = np.mean(polygon, axis=0) + 0.78 * (polygon - np.mean(polygon, axis=0))
            tr = api.track_init(p["camera"], polygon.tolist())
            m["tracker"] = {"handle": tr["handle"], "camera": p["camera"], "polygon": polygon.tolist(), "reference_frame_id": tr["frame_id"], "identity": "Textured cream cheese top, not table, bowl or gripper."}
            m.pop("partial", None)
            m["phase"] = "hover"
            save()
        g = m["geometry"]
        if m["phase"] == "hover":
            r = observe("Inspect the proposed straight free-air pad-center transfer and top-down yaw adjustment to hover_target, including the supplied own finger envelope. Is the entire relevant swept approach visibly clear of bowl, bottle, stove, cabinet and package with at least 10 mm clearance? Do not certify hidden clearance. Confirm the tracker reference remains the cream cheese top and the package/table have not shifted.", {"from_state": api.state(), "hover_target": m["hover_target"], "quaternion": m["quaternion"], "geometry": g, "tracker": m["tracker"]}, {"sweep": ["clear", "obstructed", "unknown"], "identity": ["same", "different", "unknown"], "stationary": ["yes", "no", "unknown"]})
            if r["parameters"] != {"sweep": "clear", "identity": "same", "stationary": "yes"}:
                return result("blocked", "Visible free-air approach not established.")
            if not move(m["hover_target"], "open", 0.020, "stationary"):
                return result("yield", "Free-air approach incomplete within 22-call slice; actual progress checkpointed.")
            m["phase"] = "descend"
            save()
        if m["phase"] == "descend":
            t, pts, s = track("stationary")
            center = geo.transform([g["top_center_world_m"]], t["transform_initial_world_to_current_world"])[0]
            target = center.copy()
            target[2] += g["pad_z_relative_to_top_m"]
            m["grasp_target"] = target.tolist()
            fields = {"identity": ["same", "different", "unknown"], "descent": ["clear", "obstructed", "unknown"], "table_stationary": ["yes", "no", "unknown"], "jaw_samples": ["opposed_inner_pad_faces", "unavailable", "uncertain"]}
            for attempt in range(2):
                r = observe("Check remaining descent to grasp_target: both open fingers need visibly unobstructed side corridors beside the short sides, not over the package or another object. Confirm tabletop stationarity. Request ja and jb, one depth-valid point on each opposed INNER FLAT CONTACT PAD FACE, not outer finger edges. Use either camera. These measure the actual open gap along tool Y. If occluded say unavailable; never invent a face. Retry uses the other view or a different valid face patch.", {"attempt": attempt, "target": m["grasp_target"], "geometry": g, "state": s}, fields)
                remember_partial(r)
                if measured(r, ["ja", "jb"]) and r["parameters"]["jaw_samples"] == "opposed_inner_pad_faces":
                    break
            p = r["parameters"]
            if p["identity"] != "same" or p["descent"] != "clear" or p["table_stationary"] != "yes" or p["jaw_samples"] != "opposed_inner_pad_faces" or not measured(r, ["ja", "jb"]):
                return result("blocked", "Need visible descent corridors and depth-valid opposed inner-pad faces; no blind contact.")
            axis = geo.rotation(s["tcp_quaternion_xyzw"])[:, 1]
            a, b = np.array(r["points"]["ja"]["world_m"]), np.array(r["points"]["jb"]["world_m"])
            gap = abs(float(np.dot(b - a, axis)))
            boundary = geo.transform(g["top_corners_world_m"], t["transform_initial_world_to_current_world"])
            projected = boundary @ axis
            projected_width = float(np.max(projected) - np.min(projected))
            offset = abs(float(np.mean(projected)) - 0.5 * float(np.dot(a + b, axis)))
            clearance = (gap - projected_width) / 2.0 - offset
            m["jaw_gap"] = {"frame_id": r["frame_id"], "gap_m": gap, "projected_package_width_m": projected_width, "package_center_offset_m": offset, "minimum_side_margin_m": clearance, "samples": [r["points"]["ja"], r["points"]["jb"]]}
            if clearance < 0.005 or gap > 0.120:
                return result("blocked", "Measured lateral margin below 5 mm per side or implausible jaw samples.")
            m.pop("partial", None)
            save()
            if not move(m["grasp_target"], "open", 0.008, "stationary"):
                return result("yield", "Open descent incomplete; revalidate current corridors and gap before resuming.")
            m["phase"] = "close"
            save()
        if m["phase"] == "close":
            track("stationary")
            r = observe("Before closing, are actual open pads visibly straddling opposite short sides of the cream cheese at an overlapping side-face height, with fingers clear of table and neighbors? This is contact-position evidence, not retention. Reject a finger on the top, table contact, displaced package or uncertain identity.", {"state": api.state(), "geometry": g, "target": m["grasp_target"], "jaw_gap": m.get("jaw_gap")}, {"contact_position": ["valid", "invalid", "unknown"], "identity": ["same", "different", "unknown"]})
            if r["parameters"] != {"contact_position": "valid", "identity": "same"}:
                return result("blocked", "Actual opposing contact position not verified; do not close.")
            if count[0] >= 22:
                return result("yield", "Contact position reached; closing does not fit this slice.")
            m["phase"] = "closed_unverified"
            act(m["grasp_target"], "close", 0.006)
            save()
        if m["phase"] == "closed_unverified":
            t, pts, s = track("free")
            m["prelift_state"], m["prelift_transform"] = s, t["transform_initial_world_to_current_world"]
            target = np.array(geo.pad_position(s))
            target[2] += 0.050
            m["lift_target"], m["phase"] = target.tolist(), "lift"
            save()
        if m["phase"] == "lift":
            track("follow")
            r = observe("Close was delivered but does not prove retention. Is the cream cheese still between opposed pads with no visible miss, escape, slipping displacement or entanglement, and is the remaining purely vertical diagnostic lift to lift_target visibly clear? Confirm the registered patch is the package itself, not gripper/background. A partially completed lift can continue only without apparent slipping.", {"state": api.state(), "lift_target": m["lift_target"], "retention": m.get("retention"), "tracker": m["tracker"]}, {"candidate": ["valid", "missed_or_slipping", "unknown"], "lift_corridor": ["clear", "blocked", "unknown"], "patch_identity": ["same_package", "wrong", "unknown"]})
            p = r["parameters"]
            if p["candidate"] == "missed_or_slipping" or p["patch_identity"] == "wrong":
                return result("needs_replan", "Observed grasp candidate or patch identity failed; preserve actual gripper state.")
            if p != {"candidate": "valid", "lift_corridor": "clear", "patch_identity": "same_package"}:
                return result("blocked", "Diagnostic lift is not currently observable/safe; do not open or continue blindly.")
            if not move(m["lift_target"], "keep", 0.012, "follow"):
                return result("yield", "Diagnostic lift incomplete; preserve closure and original measured baseline.")
            m["phase"] = "verify"
            save()
        if m["phase"] == "verify":
            t, pts, s = track("follow")
            if m["retention"]["hand_rise_m"] < 0.035 or m["retention"]["package_rise_m"] < 0.030:
                return result("blocked", "Measured hand/package motion is too short to establish the lift effect.")
            fields = {"identity": ["same_package", "wrong", "unknown"], "grasp": ["between_pads_no_apparent_slip", "slipping_or_not_held", "unknown"], "table_gap": ["visible_clear_gap", "contact", "unknown"], "other_support": ["none_visible", "present", "unknown"], "bottom_sample": ["true_lowest_visible_package_edge", "uncertain"]}
            for attempt in range(2):
                r = observe("Assess only the grasp-stage effect using both current views and measured rigid following. Is the same package between the pads, visibly clear of table, without apparent slipping or other support? Request low on a true lowest visible package bottom edge and table on nearby unobstructed tabletop. Do not substitute a top-face point or certify an occluded gap. On failed depth try the other camera or a different visible point on the same physical bottom edge.", {"attempt": attempt, "retention": m["retention"], "tracker": m["tracker"], "historical_table_plane": g["table_plane"]}, fields)
                remember_partial(r)
                if measured(r, ["low", "table"]):
                    break
            p = r["parameters"]
            if p["grasp"] == "slipping_or_not_held" or p["table_gap"] == "contact" or p["identity"] == "wrong" or p["other_support"] == "present":
                return result("needs_replan", "Fresh observation contradicts stable independent lifting.")
            if p != {"identity": "same_package", "grasp": "between_pads_no_apparent_slip", "table_gap": "visible_clear_gap", "other_support": "none_visible", "bottom_sample": "true_lowest_visible_package_edge"} or not measured(r, ["low", "table"]):
                return result("blocked", "Need fresh visible independent support and valid bottom-edge/table measurements; rigid following alone is insufficient.")
            low_z, table_z = r["points"]["low"]["world_m"][2], r["points"]["table"]["world_m"][2]
            if abs(table_z + g["table_plane"][3]) > 0.003 or low_z - table_z < 0.015:
                return result("blocked", "Fresh table reference or 15 mm observed bottom-edge clearance failed.")
            center = geo.transform([g["top_center_world_m"]], t["transform_initial_world_to_current_world"])[0]
            m["top_center_in_tool_m"] = (geo.rotation(s["tcp_quaternion_xyzw"]).T @ (center - np.array(s["tcp_position_world_m"]))).tolist()
            m["effect"] = {"frame_id": r["frame_id"], "observed_bottom_edge_gap_m": low_z - table_z, "parameters": p, "points": r["points"], "current_top_samples_world_m": pts.tolist(), "gripper_qpos_m": s["gripper_qpos_m"], "interpretation": "Fresh visible table separation and measured hand following without apparent slip; not whole-task completion."}
            m.pop("partial", None)
            m["phase"] = "complete"
            return result("stage_complete", "Package visibly cleared the table and followed the gripper without apparent slipping.")
        return result("blocked", "Unrecognized grasp checkpoint phase; reconcile before acting.")
    except Exception as error:
        m["error"] = {"message": str(error), "phase": m.get("phase"), "recovery_motion": "none"}
        return result(m.pop("fault_status", "blocked"), "Stopped for supervision: " + str(error))

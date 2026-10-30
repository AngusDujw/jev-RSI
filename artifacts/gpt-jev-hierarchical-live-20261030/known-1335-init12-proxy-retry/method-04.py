def main(api):
    key = "reassess_v1"
    e = {"stage": "reassess", "phase": "fresh_assessment", "receipts": [], "observations": [], "pending": None}
    limits = {"table_clearance_m": 0.006, "pad_overlap_m": 0.003, "surface_allowance_floor_m": 0.001, "new_contact_target_inset_m": 0.0006}
    questions = {}
    for axis in ["x", "y", "z", "rx", "ry", "rz"]:
        questions[axis] = {"type": "choice", "instructions": "Read state.processed_features.axes." + axis + ".goal_relation for this world translation or world rotation-vector component. Select negative for decrease, positive for increase, hold for within_tolerance. Do not infer clearance or object state.", "criteria": {"negative": "Decrease this world component.", "hold": "This component is within its declared deadband.", "positive": "Increase this world component."}}
    questions["gripper"] = {"type": "choice", "instructions": "Read state.processed_features.objective.gripper. Deliver that exact command. In this reassessment it is keep: preserve the already open command, never close or newly reopen.", "criteria": {"open": "Deliver an explicitly requested opening.", "close": "Deliver an explicitly requested closing.", "keep": "Preserve the existing gripper command."}}
    edge_schema = {"type": "array", "maxItems": 4, "items": {"type": "object", "properties": {"id": {"type": "string", "enum": ["b0", "b1", "b2", "b3"]}, "camera": {"type": "string", "enum": ["agentview", "robot0_eye_in_hand"]}, "u": {"type": "integer", "minimum": 0, "maximum": 767}, "v": {"type": "integer", "minimum": 0, "maximum": 767}}}}
    fields = {"identity": ["same_cream_cheese", "different", "unknown"], "support": ["flat_on_table", "other", "unknown"], "gripper": ["empty_open", "other", "unknown"], "boundary_band": ["both_bands_visible", "occluded", "unknown"], "closure_corridor": ["visible_clear", "obstructed", "unknown"], "upward_sweep_30mm": ["visible_clear", "obstructed", "unknown"], "alternate_measurement": ["available", "unavailable"], "edges": edge_schema, "top_labels": {"type": "object", "properties": {"t0": {"type": "string", "maxLength": 200}, "t1": {"type": "string", "maxLength": 200}, "t2": {"type": "string", "maxLength": 200}}}, "occlusions": {"type": "string", "maxLength": 400}}
    def finish(status, reason):
        e["reason"], e["last_state"], e["limits"] = reason, api.state(), limits
        api.checkpoint(key, e)
        handoff = {"checkpoint_keys": [key, "grasp_direct_v4", "grasp_recovery_v3"], "phase": e["phase"], "fresh_frame_id": e.get("observation", {}).get("frame_id"), "state_frame_id": e["last_state"]["frame_id"], "last_gripper_command": e["last_state"]["last_gripper_command"], "metrics": e.get("metrics", {}), "pending": e["pending"], "rules": "World meters; tool-to-world xyzw; image pixels top-left. reassess_v1 contains fresh depth records, printed-mark labels, ray-derived visible boundary points, own-geometry margins, observation frames and acknowledged recovery receipts. Older checkpoints remain historical, including rejected patch_1/patch_2. Boundary band labels are geometric locations, NOT material correspondences. Top labels identify material points only when unambiguous. Revalidate references after any movement. No closure, lift or retention has been attempted here. A pending intent is not an execution receipt. The 0.6 mm inset applies to planning a new contact endpoint, not to replacing the measured 6 mm clearance and 3 mm overlap tests. Equal parallel pad bands and prismatic inward tool-y closure are explicit own-gripper models, supported by the fresh opposing-pad observations. No hidden object surfaces or lift clearance are certified."}
        return {"stage_status": status, "reason": reason, "evidence": e, "handoff": handoff, "completion_proposed": False}
    def fit(records, names):
        try:
            raw = geo.plane([records[n]["world_m"] for n in names])
        except Exception as err:
            e["fit_error"] = {"names": names, "error": str(err)[:400]}
            return None
        return {"coefficients": np.array(raw["coefficients"]).tolist(), "center_world_m": np.array(raw["center_world_m"]).tolist(), "rms_m": float(raw["rms_m"]), "in_plane_spread_m": np.array(raw["in_plane_spread_m"]).tolist()}
    def observe(purpose):
        s = api.state()
        context = {"purpose": purpose, "historical_reference_only": historical, "actual_state": s, "pad_center_world_m": np.array(geo.pad_position(s)).tolist(), "tool_axes_world": geo.rotation(s["tcp_quaternion_xyzw"]).tolist(), "limits": limits, "previous_gap": e.get("gap"), "previous_partial": e.get("observation")}
        r = api.review("Reassess ONLY, with no closure or lift. Identify the same cream cheese, actual support, and open empty fingers. Request named depth points t0,t1,t2 on three distinct, well-spread, currently visible printed top landmarks; describe their physical identities in top_labels. Request s0,s1,s2 on bare TABLE: one in each lateral finger passage and a third forward, spread in two directions. Request fp and fm on the actual INNER contact pad faces on respectively positive and negative tool-y sides, within their central contact bands; do not select another link or infer hidden points. For boundaries return visible edge pixels in edges, not guessed corners: b0/b1 on the positive tool-y long side at respectively lower/higher tool-x than the pad footprint; b3/b2 likewise on the negative tool-y side. Choose these beyond each end of the 16 mm pad-x footprint by about 4-6 mm, only where the actual top boundary is visible. They will be intersected with a freshly fitted top plane; the ray is not a surface detector. Mark both_bands_visible only if the opposing package side contact bands across the entire pad footprint are directly supported by the views, not extrapolated through occlusion. closure_corridor refers only to inward finger travel at the CURRENT pose: intended package contact is allowed, but the rest of the finite finger sweep must be visibly unobstructed. Independently assess a 30 mm WORLD +Z observation retreat with unchanged orientation and open command, allowing 2 mm lateral tracking variation: the whole finite hand sweep must be visibly clear, not inferred from old descent. Do not require a lift outcome as a prerequisite. Use both views; omit unavailable measurements and report occlusions. On a complementary request use different visible depth patches/camera, not the failed pixels. Return exactly the declared parameters.", context=context, fields=fields)
        bad = [x["name"] for x in r["measurement_errors"]]
        pts = {n: p for n, p in r["points"].items() if n not in bad and p["frame_id"] == r["frame_id"]}
        obs = {"frame_id": r["frame_id"], "parameters": r["parameters"], "points": pts, "measurement_errors": r["measurement_errors"], "explanation": r["explanation"][:400], "status": r["status"]}
        if "observation" in e:
            previous = e["observation"]
            e["previous_partial"] = {"frame_id": previous["frame_id"], "points": {n: v for n, v in previous["points"].items() if n in ["t0","t1","t2","s0","s1","s2"]}, "top_labels": previous["parameters"]["top_labels"]}
        e["observation"], e["boundary_records"], e["metrics"] = obs, {}, {}
        e["observations"].append({"frame_id": r["frame_id"], "point_names": list(pts), "measurement_errors": r["measurement_errors"], "purpose": purpose[:250]})
        api.checkpoint(key, e)
        if r["status"] == "stop":
            return "review requested stop"
        p, m = r["parameters"], e["metrics"]
        if api.state()["frame_id"] != r["frame_id"]:
            return "observation and robot frames differ"
        if not all(n in pts for n in ["s0", "s1", "s2"]):
            return "missing fresh table depth: " + str([n for n in ["s0", "s1", "s2"] if n not in pts])
        tf = fit(pts, ["s0", "s1", "s2"])
        if tf is None:
            return "table fit rejected: " + e["fit_error"]["error"]
        m["table_fit"] = tf
        nt = np.array(tf["coefficients"][:3])
        if nt[2] < 0.999 or tf["rms_m"] > 0.0007 or min(tf["in_plane_spread_m"]) < 0.01 or max(tf["in_plane_spread_m"]) < 0.025:
            return "fresh table plane lacks adequate horizontal distributed support"
        R, tcp = geo.rotation(s["tcp_quaternion_xyzw"]), np.array(s["tcp_position_world_m"])
        own = s["own_geometry"]
        lo, hi = own["finger_low_offset_tool_m"], own["finger_high_offset_tool_m"]
        corners = np.array([[x,y,z] for x in [lo[0],hi[0]] for y in [lo[1],hi[1]] for z in [lo[2],hi[2]]])
        finger_world = tcp + corners @ R.T
        table_raw = float(np.min(finger_world @ nt + tf["coefficients"][3]))
        m["finger_table_clearance_lower_m"] = table_raw - max(0.001, 3*tf["rms_m"])
        if not all(n in pts for n in ["t0", "t1", "t2"]):
            return "missing fresh top depth: " + str([n for n in ["t0", "t1", "t2"] if n not in pts])
        top = fit(pts, ["t0", "t1", "t2"])
        if top is None:
            return "top fit rejected: " + e["fit_error"]["error"]
        m["top_fit"] = top
        n = np.array(top["coefficients"][:3])
        if top["rms_m"] > 0.0007 or min(top["in_plane_spread_m"]) < 0.004 or max(top["in_plane_spread_m"]) < 0.012 or float(n @ nt) < 0.999:
            return "fresh top plane lacks sufficient spread, rigidity or parallel-to-table support"
        u = max(0.001, 3*top["rms_m"], 3*tf["rms_m"])
        m["allowance_m"], m["finger_table_clearance_lower_m"] = u, table_raw-u
        if p["boundary_band"] != "both_bands_visible":
            return "opposing package contact-band boundaries remain occluded or ambiguous"
        edges = p["edges"]
        if len(edges) != 4 or set(x["id"] for x in edges) != set(["b0", "b1", "b2", "b3"]):
            return "four visible local boundary samples are unavailable"
        for b in edges:
            try:
                e["boundary_records"][b["id"]] = api.plane_point(b["camera"], [b["u"], b["v"]], top["coefficients"])
            except Exception as err:
                return "boundary ray failed for " + b["id"] + ": " + str(err)
        B = np.array([e["boundary_records"][n]["world_m"] for n in ["b0", "b1", "b2", "b3"]])
        pc, half = np.array(geo.pad_position(s)), np.array(own["pad_extent_in_tool_m"])/2
        b = (B-pc) @ R
        m["boundary_in_tool_relative_pad_m"], m["pad_center_world_m"] = b.tolist(), pc.tolist()
        if max(b[0,0], b[3,0]) > -half[0]-0.002-u or min(b[1,0], b[2,0]) < half[0]+0.002+u:
            return "visible contact bands do not cover both pad-x ends with 2 mm plus uncertainty reserve"
        if min(b[0,1], b[1,1]) < 0.008 or max(b[2,1], b[3,1]) > -0.008 or abs(b[0,1]-b[1,1]) > 0.004 or abs(b[2,1]-b[3,1]) > 0.004:
            return "fresh opposing side geometry is not compatible with the actual pad alignment"
        projected = n @ R
        lateral = abs(projected[0])*half[0] + abs(projected[1])*half[1]
        vertical, d = abs(projected[2])*half[2], float(n @ pc + top["coefficients"][3])
        thickness = float(np.min(B @ nt + tf["coefficients"][3]) / float(n @ nt))
        overlap = float(min(d-lateral+vertical, -u)-max(d+lateral-vertical, -thickness+u))
        m["common_pad_interval_from_top_m"], m["package_thickness_lower_m"] = [float(d+lateral-vertical), float(d-lateral+vertical)], thickness-u
        m["opposing_overlap_lower_m"] = overlap
        if not all(k in pts for k in ["fp", "fm"]):
            return "missing directly measured inner pad-face locations"
        f = (np.array([pts[k]["world_m"] for k in ["fp", "fm"]])-pc) @ R
        if f[0,1] <= 0 or f[1,1] >= 0 or np.any(np.abs(f[:,0]) > half[0]+0.005) or np.any(np.abs(f[:,2]) > half[2]+0.003) or np.any(np.abs(f[:,1]) > half[1]+0.003):
            return "selected inner pad samples do not agree with current own pad geometry"
        gaps = [float(f[0,1]-max(b[0,1], b[1,1])-u), float(min(b[2,1], b[3,1])-f[1,1]-u)]
        m["open_side_gap_lower_m"] = gaps
        failed = []
        if p["identity"] != "same_cream_cheese" or p["support"] != "flat_on_table" or p["gripper"] != "empty_open":
            failed.append("identity/support/open-empty evidence incomplete")
        if p["closure_corridor"] != "visible_clear":
            failed.append("closure sweep not visibly clear")
        if min(gaps) < 0.002:
            failed.append("less than 2 mm robust initial side gap")
        if m["finger_table_clearance_lower_m"] < 0.006:
            failed.append("less than 6 mm robust table clearance")
        if overlap < 0.003:
            failed.append("less than 3 mm robust opposing pad overlap")
        return "; ".join(failed)
    try:
        old = api.recall("grasp_direct_v4")["value"]
        historical = {"reference": old["reference"], "boundary_frame54": old["frame54_geometry"], "not_current": True}
        e["inherited"] = {"checkpoint": "grasp_direct_v4", "last_receipt": old.get("last_receipt"), "rejected_trackers": ["patch_1", "patch_2"], "old_target_not_replayed": True}
        entry = api.state()
        e["entry_state"] = entry
        if entry["last_gripper_command"] != "open" or min(abs(x) for x in entry["gripper_qpos_m"]) < 0.035:
            return finish("needs_replan", "Entry is no longer the acknowledged open-gripper configuration; preserve the actual command.")
        if entry["budgets"]["gpt_remaining"] < 1:
            return finish("blocked", "Fresh observation budget unavailable.")
        gap = observe("Evaluate actual frame and physical contact margins, not the old target residual.")
        e["gap"] = gap
        if not gap:
            return finish("stage_complete", "Fresh local boundary, pad-face, top and table evidence establishes grasp readiness at the measured pose; no closure performed.")
        p = e["observation"]["parameters"]
        if e["observation"]["status"] == "stop":
            return finish("abort", gap)
        if p["identity"] == "different" or p["support"] == "other" or p["gripper"] == "other":
            return finish("needs_replan", "Fresh observation contradicts the flat supported package/open-empty entry assumption.")
        if p["alternate_measurement"] == "available" and api.state()["budgets"]["gpt_remaining"] >= 2:
            gap = observe("One complementary measurement for this exact gap: " + gap + ". Preserve visible physical identities; use an alternative view or valid interior patch. Do not repeat failed pixels.")
            e["gap"], p = gap, e["observation"]["parameters"]
            if not gap:
                return finish("stage_complete", "Complementary fresh measurements establish actual grasp readiness without replaying descent.")
        if e["observation"]["status"] == "stop":
            return finish("abort", gap)
        if p["identity"] != "same_cream_cheese" or p["support"] != "flat_on_table" or p["gripper"] != "empty_open":
            return finish("blocked", "Recovery lacks unambiguous current identity, support or open-empty evidence: " + gap)
        m, s = e["metrics"], api.state()
        if p["upward_sweep_30mm"] != "visible_clear" or m.get("finger_table_clearance_lower_m", -1) < 0.006:
            return finish("blocked", "Current readiness gap: " + gap + ". No verified-clear observation retreat with preserved table margin.")
        if s["budgets"]["gpt_remaining"] < 1 or s["budgets"]["jev_remaining"] < 8 or s["budgets"]["native_steps_remaining"] < 24:
            return finish("yield", "Useful fresh partial measurements saved; insufficient reserved resources for retreat plus remeasurement.")
        e["phase"] = "observation_retreat"
        start, q = np.array(s["tcp_position_world_m"]), s["tcp_quaternion_xyzw"]
        target = start + np.array([0.0, 0.0, 0.03])
        for i in range(8):
            before = api.state()
            e["pending"] = {"before_frame_id": before["frame_id"], "target_tcp_world_m": target.tolist(), "quaternion_xyzw": q, "gripper": "keep"}
            api.checkpoint(key, e)
            r = api.control(target.tolist(), q, "keep", questions, features={"source": "Fresh GPT visible-sweep interpretation, RGB-D table plane and own geometry; no tracker or object oracle.", "phase": "observation_retreat_only", "verified_frame_id": e["observation"]["frame_id"], "clearance_lower_m": m["finger_table_clearance_lower_m"], "target_delta_world_m": [0.0,0.0,0.03], "current_state_frame_id": before["frame_id"], "no_contact_target_or_closure": True}, tool_point="tcp", translation_limit=0.012, rotation_limit=0.01, steps=3, position_tolerance=0.002, rotation_tolerance=0.01)
            after = api.state()
            e["receipts"].append({k: r[k] for k in ["decision", "frame_id", "choices", "status", "before", "after", "acknowledged_steps", "position_error_m", "rotation_error_rad"] if k in r})
            e["pending"] = None
            api.checkpoint(key, e)
            pos = np.array(after["tcp_position_world_m"])
            angle = math.acos(max(-1.0, min(1.0, float((np.trace(geo.rotation(q).T @ geo.rotation(after["tcp_quaternion_xyzw"]))-1)/2))))
            if r["choices"]["gripper"] != "keep" or after["last_gripper_command"] != "open" or float(np.linalg.norm(pos[:2]-start[:2])) > 0.002 or pos[2] < start[2]-0.0005 or pos[2] > target[2]+0.002 or angle > 0.006:
                return finish("abort", "Acknowledged recovery departed from the verified open vertical corridor; do not retry or reopen.")
            if r["status"] == "reached":
                break
            if r["status"] == "stalled" or float(np.linalg.norm(pos-np.array(before["tcp_position_world_m"]))) < 0.0001:
                e["motion_stop"] = "First stalled or negligible-progress update; no repetition."
                break
        e["phase"] = "post_retreat_remeasurement"
        gap = observe("Fresh evidence after the acknowledged observation retreat. Reacquire all affected references; old pixels and boundaries are not current. This pose need not yet have contact overlap.")
        e["gap"] = gap
        if e["observation"]["status"] == "stop":
            return finish("abort", gap)
        if not gap:
            return finish("stage_complete", "Fresh post-motion measurements establish actual physical grasp readiness.")
        if e["observation"]["parameters"]["identity"] != "same_cream_cheese" or e["observation"]["parameters"]["support"] != "flat_on_table":
            return finish("needs_replan", "Post-retreat support or package identity is not confirmed; inspect actual scene.")
        if len(e["boundary_records"]) == 4 and "opposing_overlap_lower_m" in e["metrics"]:
            return finish("yield", "Observation retreat produced fresh local geometry for endpoint reconsideration. Current readiness gap: " + gap)
        return finish("blocked", "Bounded observation recovery exhausted; unresolved fresh geometry gap: " + gap)
    except Exception as err:
        e["runtime_error"] = str(err)
        return finish("blocked", "API/geometry failure requires supervision; preserve all acknowledged actions and reconcile any pending intent: " + str(err))

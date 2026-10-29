def main(api):
    task = "could you put the cream cheese into the bowl"
    D = {"g": None, "p": {"phase": "approach"}, "handle": None, "anchor": np.eye(4), "log": [], "reserve": 18}
    pixel = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 767}, "minItems": 2, "maxItems": 2}
    polygon = {"type": "array", "items": pixel, "minItems": 0, "maxItems": 16}
    cameras = ["agentview", "robot0_eye_in_hand"]
    views = ["none", "xplus", "xminus", "yplus", "yminus", "up"]
    Q = {}
    for axis in ["x", "y", "z", "rx", "ry", "rz"]:
        Q[axis] = {"type": "choice", "instructions": "For world axis " + axis + ", use the explicitly bound axes." + axis + ".goal_relation. Choose positive for increase, negative for decrease, hold for within_tolerance. Do not infer direction from an image.", "criteria": {"negative": "Decrease this world coordinate or rotation component.", "hold": "This axis is within its deadband.", "positive": "Increase this world coordinate or rotation component."}}
    Q["gripper"] = {"type": "choice", "instructions": "Read processed_features.objective.gripper and deliver that exact requested gripper operation.", "criteria": {"open": "Objective requests open.", "close": "Objective requests close.", "keep": "Objective requests keep; preserve the grip."}}
    def log(x):
        D["log"].append(x); api.note(str(x))
    def review(question, fields, context=None):
        if api.state()["budgets"]["gpt_remaining"] < 1: raise RuntimeError("No observation-review budget remains")
        r = api.review(question, context=context, fields=fields)
        if r["measurement_errors"]: log({"measurement_errors": r["measurement_errors"]})
        if r["status"] == "stop": raise RuntimeError("Review stopped: " + r["explanation"])
        return r
    def points(r, names):
        missing = [n for n in names if n not in r["points"]]
        if missing: raise RuntimeError("Missing current depth measurements: " + str(missing))
        return np.array([r["points"][n]["world_m"] for n in names], dtype=float)
    def save(phase, **values):
        D["p"].update(values); D["p"]["phase"] = phase
        api.checkpoint("phase", D["p"])
    def drive(target, q, label, calls=14, gripper="keep"):
        s = api.state(); n = min(calls, s["budgets"]["jev_remaining"] - D["reserve"], s["budgets"]["native_steps_remaining"] // 3)
        if n < 1: raise RuntimeError("Insufficient action reserve for " + label)
        r = api.drive(np.array(target).tolist(), list(q), gripper, Q, features={"phase": label, "source": "RGB-D geometry and current proprioception"}, max_calls=int(n), tool_point="pad_center", translation_limit=0.015, rotation_limit=0.08, steps=3, position_tolerance=0.003, rotation_tolerance=0.04)
        log({"motion": label, "status": r["status"], "position_error_m": r["position_error_m"], "rotation_error_rad": r["rotation_error_rad"], "lease_calls": r["lease_calls"]})
        if r["status"] == "stalled": raise RuntimeError("Stalled motion; no repeated contact push: " + label)
        if r["status"] not in ["reached", "lease_exhausted"]: raise RuntimeError("Unexpected drive receipt")
        return r
    def view_move(v, label):
        offsets = {"xplus": [0.025, 0, 0], "xminus": [-0.025, 0, 0], "yplus": [0, 0.025, 0], "yminus": [0, -0.025, 0], "up": [0, 0, 0.03]}
        if v not in offsets: raise RuntimeError("No justified observation-producing view action")
        s = api.state(); r = drive(geo.pad_position(s) + np.array(offsets[v]), s["tcp_quaternion_xyzw"], label, 10)
        if r["status"] != "reached": raise RuntimeError("View motion did not converge")
    def move(target, q, label):
        target = np.array(target, dtype=float); used_view = False
        for leg in range(16):
            s = api.state(); pad = geo.pad_position(s); delta = target - pad; dist = float(np.linalg.norm(delta))
            if dist <= 0.003 and leg > 0: return
            end = pad + delta * min(1.0, 0.085 / max(dist, 0.0001))
            f = {"external": ["observed_obstacle", "none_seen", "unknown"], "visibility": ["observed_local", "partial", "self_occluded", "unobserved"], "action": ["bounded_progress", "view_only", "stop"], "view": views, "reason": "string"}
            r = review("Assess only this bounded next leg, not the entire future route. external distinguishes an observed external obstacle from none seen and inability to tell. visibility distinguishes partial/unobserved space from occlusion by our hand or held package. None seen is NOT certified clearance. action=bounded_progress only when current local evidence, measured geometry and the phase justify this leg; self-occlusion alone is not an external obstacle. For grasp descent require the open fingers remain outside the package sides. action=view_only requires view to name a justified 25 mm horizontal or 30 mm upward view-changing displacement with no observed obstacle, expected to expose a specific missing feature. Otherwise stop and explain the exact gap. Use all declared fields.", f, {"task": task, "phase": label, "start_pad_world_m": pad.tolist(), "next_pad_world_m": end.tolist(), "remaining_m": dist, "geometry": D["g"], "last_object_evidence": D["p"].get("held")})
            a = r["parameters"]
            if a["external"] == "observed_obstacle" or a["action"] == "stop": raise RuntimeError("Local motion gap: " + a["reason"])
            if a["action"] == "view_only":
                if used_view: raise RuntimeError("One view change did not resolve local motion evidence")
                view_move(a["view"], label + " view"); used_view = True; continue
            if a["external"] == "unknown" or a["visibility"] == "unobserved": raise RuntimeError("No justified local motion evidence: " + a["reason"])
            out = drive(end, q, label)
            if out["status"] == "lease_exhausted" and float(np.linalg.norm(geo.pad_position(api.state()) - pad)) < min(0.04, max(0.005, dist - 0.003)):
                raise RuntimeError("Insufficient measured progress within lease")
        raise RuntimeError("Bounded route did not finish")
    def actuate(command):
        for k in range(3):
            s = api.state()
            if s["budgets"]["jev_remaining"] < 1 or s["budgets"]["native_steps_remaining"] < 3: raise RuntimeError("Gripper action budget exhausted")
            r = api.control(geo.pad_position(s).tolist(), s["tcp_quaternion_xyzw"], command, Q, features={"phase": D["p"]["phase"], "claim": "command only, not contact evidence"}, tool_point="pad_center", translation_limit=0.005, rotation_limit=0.02, steps=3, position_tolerance=0.003, rotation_tolerance=0.04)
            if r["status"] == "stalled" or r["status"] not in ["reached", "moved"] or r["choices"]["gripper"] != command: raise RuntimeError("Gripper delivery or pose hold failed")
    def acquire():
        fields = {"identity": ["certain", "unknown"], "shape": ["rigid_box", "unknown"], "support": ["flat_on_table", "unknown"], "rim": ["horizontal_circular", "unknown"], "hand": ["empty_open", "other", "unknown"], "camera": cameras, "corners": {"type": "array", "items": pixel, "minItems": 4, "maxItems": 4}, "labels": {"type": "array", "items": {"type": "string", "maxLength": 350}, "minItems": 3, "maxItems": 3}, "patch_camera": cameras, "patch": polygon}
        for attempt in range(2):
            r = review("Interpret the task using current images. Identify the cream cheese package and the destination bowl, not the plate. identity must be certain. Establish a rigid rectangular package resting flat on the table, and a circular nearly horizontal bowl opening; otherwise return unknown. hand=empty_open requires visibly empty open fingers. Request regions top and table, each a small uncontaminated planar interior region, with explicit camera, box and stride=4. Request points side on the visible vertical package side, bottom on the visible bowl interior floor, r0 through r5 distributed around the INNER rim on actual lip material, and l0,l1,l2 on three noncollinear uniquely identifiable interior printed package landmarks. labels must persistently define those same physical l0,l1,l2 features, never camera-relative corners. camera and corners give four visible package TOP outline corner pixels in cyclic order, all belonging to the fitted top plane; these pixels are ray-plane intersections, not raw boundary depth. patch_camera and patch select a textured visible package interior polygon, or [] if unavailable. Do not guess hidden corners or an underside.", fields, {"instruction": task, "prior_issue": D["log"][-1:]})
            api.checkpoint("acquisition", {"frame_id": r["frame_id"], "parameters": r["parameters"], "points": r["points"], "measurement_errors": r["measurement_errors"]})
            try:
                p = r["parameters"]
                if p["identity"] != "certain" or p["shape"] != "rigid_box" or p["support"] != "flat_on_table" or p["rim"] != "horizontal_circular" or p["hand"] != "empty_open": raise RuntimeError("Required visible object, support, rim or open-hand identity unavailable")
                if "top" not in r["regions"] or "table" not in r["regions"]: raise RuntimeError("Missing top/table cloud")
                tp = geo.plane(r["regions"]["top"]["world_m"]); tb = geo.plane(r["regions"]["table"]["world_m"])
                n = np.array(tp["coefficients"]); table = np.array(tb["coefficients"])
                if n[2] < 0.97 or table[2] < 0.97 or max(tp["rms_m"], tb["rms_m"]) > 0.0025: raise RuntimeError("Unreliable or tilted supporting planes")
                corners = np.array([api.plane_point(p["camera"], px, n.tolist())["world_m"] for px in p["corners"]])
                cam = api.camera(p["camera"]); local = geo.transform(corners, np.linalg.inv(np.array(cam["camera_to_world_opencv"])))
                u = max(0.0015, float(tp["rms_m"]) + 2 * float(np.max(local[:, 2])) / float(cam["K"][0][0]))
                c = np.mean(corners, axis=0); z0 = float(-(table[0] * c[0] + table[1] * c[1] + table[3]) / table[2]); h = float(c[2] - z0)
                lm = points(r, ["l0", "l1", "l2"]); side = points(r, ["side"])[0]; rim = points(r, ["r0", "r1", "r2", "r3", "r4", "r5"]); floor = points(r, ["bottom"])[0]
                circle = geo.circle_xy(rim); rp = geo.plane(rim); radius = float(circle["radius_m"]); rz = float(np.mean(rim[:, 2])); bc = list(circle["center_xy_m"])
                edges = [corners[1] - corners[0], corners[2] - corners[1]]; lengths = [float(np.linalg.norm(e)) for e in edges]; short = edges[int(np.argmin(lengths))]
                diag = float(np.max(np.linalg.norm(corners[:, :2] - c[:2], axis=1))); margin = 2 * u + 0.003
                log({"package_edges_m": lengths, "height_m": h, "corner_uncertainty_m": u, "package_radius_m": diag, "bowl_radius_m": radius, "fit_margin_m": margin, "rim_rms_m": float(rp["rms_m"]), "circle_max_error_m": float(circle["max_radial_error_m"])})
                if h <= 2*u or not z0-u <= side[2] <= c[2]+u or np.max(np.abs(lm @ n[:3] + n[3])) > 3*u: raise RuntimeError("Package side/height/landmark plane inconsistent")
                if np.linalg.norm(corners[0]+corners[2]-corners[1]-corners[3]) > 4*u or abs(float(np.dot(edges[0], edges[1]))) > 4*u*max(lengths): raise RuntimeError("Visible outline does not support a rectangular top")
                if np.linalg.norm(np.cross(lm[1]-lm[0], lm[2]-lm[0])) < (4*u)**2: raise RuntimeError("Printed landmarks insufficiently spread for independent registration")
                if rp["coefficients"][2] < 0.97 or rp["rms_m"] > 3*u or circle["max_radial_error_m"] > 3*u or circle["largest_angular_gap_rad"] > math.pi or diag+margin >= radius: raise RuntimeError("Opening fit or measured insertion clearance inadequate")
                if floor[2] >= rz-u or np.linalg.norm(floor[:2]-np.array(bc)) > radius*0.45: raise RuntimeError("No measured central interior support surface")
                s = api.state(); own = s["own_geometry"]; R = geo.rotation(s["tcp_quaternion_xyzw"]); opening = int(np.argmax(own["pad_extent_in_tool_m"])); axis = R[:, opening]
                if abs(axis[2]) > 0.15: raise RuntimeError("Current gripper not suitable for a preserved-tilt top grasp")
                if np.dot(axis[:2], short[:2]) < 0: short = -short
                yaw = math.atan2(axis[0]*short[1]-axis[1]*short[0], float(np.dot(axis[:2], short[:2])))
                q = api.compose(s["tcp_quaternion_xyzw"], [0, 0, yaw]); RR = geo.rotation(q)
                bounds = np.array([[x,y,z] for x in [own["finger_low_offset_tool_m"][0], own["finger_high_offset_tool_m"][0]] for y in [own["finger_low_offset_tool_m"][1], own["finger_high_offset_tool_m"][1]] for z in [own["finger_low_offset_tool_m"][2], own["finger_high_offset_tool_m"][2]]])
                low = float(np.min((bounds - np.array(own["pad_center_in_tool_m"])) @ RR[2])); halfpad = float(np.dot(np.abs(RR[2]), own["pad_extent_in_tool_m"]) / 2)
                gz = max(z0+h/2, z0+margin-low)
                if gz-halfpad >= c[2]-u: raise RuntimeError("Finger/table clearance incompatible with side overlap: " + str({"grasp_z": gz, "pad_half_height": halfpad, "top_z": float(c[2]), "lowest_finger_relative_pad": low}))
                g = {"task": task, "frame": r["frame_id"], "lm": lm.tolist(), "labels": p["labels"], "corners": corners.tolist(), "center": (c-n[:3]*h/2).tolist(), "bottom": [float(c[0]),float(c[1]),z0], "height": h, "u": u, "bowl_xy": bc, "rim_z": rz, "radius": radius, "floor": floor.tolist(), "q": list(q), "grasp": [float(c[0]),float(c[1]),gz], "pregrasp": [float(c[0]),float(c[1]),float(c[2]+0.025-low)], "finger_low": low, "opening_axis_tool": opening}
                D["g"] = g; api.checkpoint("geometry", g)
                if len(p["patch"]) >= 3:
                    try: D["handle"] = api.track_init(p["patch_camera"], p["patch"])["handle"]
                    except Exception as e: log({"patch_init": str(e), "fallback": "persistent printed landmarks"})
                return
            except Exception as e: log({"acquisition_attempt": attempt, "gap": str(e)})
        raise RuntimeError("Two acquisitions could not establish essential geometry")
    def rigid(a, b):
        ac = np.mean(a, axis=0); bc = np.mean(b, axis=0); U, S, V = np.linalg.svd((a-ac).T @ (b-bc)); R = V.T @ U.T
        if np.linalg.det(R) < 0: V[-1, :] *= -1; R = V.T @ U.T
        M = np.eye(4); M[:3,:3] = R; M[:3,3] = bc-R@ac
        return M, float(np.max(np.linalg.norm(geo.transform(a, M)-b, axis=1)))
    def observe(label):
        g = D["g"]; M = None; uncertainty = g["u"]; quality = {}; measured = None
        if D["handle"] is not None:
            try:
                t = api.track_update(D["handle"])
                if t["status"] == "tracked":
                    spread = sorted(np.array(t["inlier_spread_m"]).reshape(-1).tolist(), reverse=True); span = spread[min(1,len(spread)-1)]
                    quality = {"inliers": t["inliers"], "matches": t["matches"], "rms_m": t["rms_m"], "uncertainty_floor_m": t["uncertainty_floor_m"], "frame_id": t["frame_id"], "reference_frame_id": t["reference_frame_id"]}
                    if t["inliers"] >= 12 and t["inliers"] / max(1,t["matches"]) >= 0.6 and t["rms_m"] <= 0.003 and t["uncertainty_floor_m"] <= 0.006 and span > max(0.003,3*t["rms_m"]):
                        M = np.array(t["transform_initial_world_to_current_world"]) @ D["anchor"]; uncertainty += float(t["rms_m"] + t["uncertainty_floor_m"])
                else: quality = {"unknown_registration": t["reason"], "frame_id": t["frame_id"]}
            except Exception as e: quality = {"tracker_error": str(e)}
        if M is None:
            log({"phase": label, "registration": quality})
            for attempt in range(2):
                r = review("Recover an independent CURRENT package observation. Request points l0,l1,l2 at the exact saved physical printed landmarks. Their labels and reference world coordinates are historical identity aids, not current detections. identity=confirmed only for unambiguous correspondence on this same rigid package; otherwise ambiguous or occluded. Do not require its entire perimeter. patch_camera/patch may identify a new usable interior textured patch, [] if absent. If measurements cannot be obtained, view may name one locally justified 25 mm horizontal or 30 mm upward displacement of the hand, preserving its grip, that would expose those features. Select none unless local evidence supports this observation-producing move without an observed obstacle. Explain why in reason.", {"identity": ["confirmed", "ambiguous", "occluded"], "view": views, "reason": "string", "patch_camera": cameras, "patch": polygon}, {"phase": label, "labels": g["labels"], "reference_world_m": g["lm"], "reference_frame": g["frame"], "tracker": quality})
                p = r["parameters"]
                if p["identity"] == "confirmed" and all(n in r["points"] for n in ["l0","l1","l2"]):
                    measured = points(r, ["l0","l1","l2"]); M, residual = rigid(np.array(g["lm"]), measured)
                    if residual > 3*g["u"] or np.linalg.norm(np.cross(measured[1]-measured[0], measured[2]-measured[0])) < (4*g["u"])**2: raise RuntimeError("Ambiguous or inconsistent physical landmark registration: " + str(residual))
                    uncertainty = 2*g["u"] + residual; quality = {"source": "fresh corresponding RGB-D printed landmarks", "fit_residual_m": residual, "frame_id": r["frame_id"]}
                    D["handle"] = None
                    if len(p["patch"]) >= 3:
                        try: D["handle"] = api.track_init(p["patch_camera"], p["patch"])["handle"]; D["anchor"] = M.copy()
                        except Exception as e: log({"replacement_patch": str(e)})
                    break
                if attempt == 0 and p["identity"] != "ambiguous" and p["view"] != "none": view_move(p["view"], "registration recovery view")
                else: raise RuntimeError("Unknown registration; no unambiguous current correspondence or justified view: " + p["reason"])
        out = geo.transform(np.array(g["lm"] + g["corners"] + [g["bottom"],g["center"]]), M)
        o = {"lm": (out[:3] if measured is None else measured).tolist(), "corners": out[3:7].tolist(), "bottom": out[7].tolist(), "center": out[8].tolist(), "u": float(uncertainty), "state": api.state(), "quality": quality}
        log({"observation": label, "quality": quality, "uncertainty_m": uncertainty}); return o
    def retained(a, b, probe=False):
        err = float(geo.attachment_error(a["lm"], b["lm"], a["state"], b["state"]))
        hand = geo.pad_position(b["state"]) - geo.pad_position(a["state"]); obj = np.mean(np.array(b["lm"])-np.array(a["lm"]), axis=0)
        tol = min(0.014, a["u"]+b["u"]+0.003)
        log({"retention_attachment_error_m": err, "tolerance_m": tol, "actual_hand_motion_m": hand.tolist(), "observed_package_motion_m": obj.tolist(), "probe": probe})
        if err > tol or (probe and (hand[2] < 0.025 or obj[2] < 0.018 or np.linalg.norm(obj) < 0.55*np.linalg.norm(hand))): raise RuntimeError("Retention not established by independent package/hand motion")
    try:
        manifest = api.recall(); keys = [v["key"] for v in manifest]
        if "geometry" in keys:
            D["g"] = api.recall("geometry")["value"]
            if "phase" in keys: D["p"] = api.recall("phase")["value"]
            r = review("This is a repair, not a reset. Revalidate the historical bowl identity and stationary rim/floor geometry against current images. bowl=same_stationary only if there is no evidence it moved and current identifiable rim/support observations agree. State uncertainty, not certification. Do not reinterpret saved package landmark labels. No tracker handle survived.", {"bowl": ["same_stationary", "changed", "unknown"], "reason": "string"}, {"geometry": D["g"], "phase_evidence": D["p"]})
            if r["parameters"]["bowl"] != "same_stationary": raise RuntimeError("Historical bowl geometry needs new measurement: " + r["parameters"]["reason"])
        else: acquire(); save("approach")
        g = D["g"]; q = g["q"]
        if D["p"]["phase"] == "approach":
            current = observe("source before approach")
            if np.max(np.linalg.norm(np.array(current["lm"])-np.array(g["lm"]), axis=1)) > 3*g["u"]: raise RuntimeError("Source moved; original approach geometry is stale")
            high = list(g["pregrasp"]); high[2] = max(high[2], float(geo.pad_position(api.state())[2]))
            move(high, q, "empty open hand above source"); move(g["pregrasp"], q, "open hand pregrasp"); save("grasp")
        if D["p"]["phase"] == "grasp":
            r = review("Check actual open pads straddle the package's shorter opposing sides, with room to descend to the supplied grasp height. Do not infer finger clearance from a target pose. straddle=yes requires visible side clearance and the package between the opening faces. No/unknown stops rather than blindly closing.", {"straddle": ["yes", "no", "unknown"], "reason": "string"}, {"geometry": g})
            if r["parameters"]["straddle"] != "yes": raise RuntimeError("Pregrasp clearance gap: " + r["parameters"]["reason"])
            move(g["grasp"], q, "grasp descent"); save("closing")
        if D["p"]["phase"] == "closing":
            actuate("close")
            r = review("Observe the actual closure. capture=opposed means the package lies between opposing closed/contacting pads, with no visible miss, table pinch, or bowl contact. This does NOT yet establish retention. upward_probe=justified means a bounded 40 mm upward measurement lift has locally plausible headroom and no observed external obstruction. Partial perimeter occlusion by fingers is acceptable; do not demand the result of a lift before authorizing that lift.", {"capture": ["opposed", "miss", "unknown"], "upward_probe": ["justified", "blocked", "unknown"], "reason": "string"}, {"geometry": g})
            if r["parameters"]["capture"] != "opposed" or r["parameters"]["upward_probe"] != "justified": raise RuntimeError("Closure/probe gap: " + r["parameters"]["reason"])
            a = observe("closure baseline"); lift = (geo.pad_position(a["state"]) + np.array([0,0,0.04])).tolist(); save("probe", baseline=a, lift=lift)
        if D["p"]["phase"] == "probe":
            move(D["p"]["lift"], q, "retention measurement lift"); b = observe("after lift"); retained(D["p"]["baseline"], b, True); save("transfer", held=b)
        if D["p"]["phase"] == "transfer":
            a = observe("transfer start"); retained(D["p"]["held"], a)
            pad = geo.pad_position(a["state"]); bottom_offset = np.array(a["bottom"])-pad
            drop_z = max(g["rim_z"]+0.008-bottom_offset[2], g["rim_z"]+0.008-g["finger_low"])
            drop = [float(g["bowl_xy"][0]-bottom_offset[0]), float(g["bowl_xy"][1]-bottom_offset[1]), float(drop_z)]
            high = list(drop); high[2] = max(drop_z+0.025, float(pad[2]))
            move([float(pad[0]),float(pad[1]),high[2]], q, "lift to transfer level"); b = observe("transfer clearance height"); retained(D["p"]["held"], b)
            move(high, q, "bounded transfer above bowl"); b = observe("above bowl"); retained(D["p"]["held"], b)
            move(drop, q, "lower to above-rim release"); b = observe("release alignment"); retained(D["p"]["held"], b)
            cc = np.array(b["corners"]); radial = float(np.max(np.linalg.norm(cc[:,:2]-np.array(g["bowl_xy"]),axis=1)))
            if radial+2*b["u"] >= g["radius"] or b["bottom"][2] < g["rim_z"]+0.002: raise RuntimeError("Observed release geometry inadequate: " + str({"package_radial_extent": radial, "bowl_radius": g["radius"], "bottom_z": b["bottom"][2], "rim_z": g["rim_z"], "uncertainty": b["u"]}))
            save("releasing", release_observation=b)
        if D["p"]["phase"] == "releasing":
            D["reserve"] = 0; actuate("open"); save("verify")
        if D["p"]["phase"] == "verify":
            D["reserve"] = 0; s = api.state(); move(geo.pad_position(s)+np.array([0,0,0.07]), s["tcp_quaternion_xyzw"], "open-hand withdrawal for release inspection")
            samples = []; definition = None
            for k in range(2):
                if k == 1:
                    s = api.state(); move(geo.pad_position(s)+np.array([0,0,0.025]), s["tcp_quaternion_xyzw"], "second noncontact stability view")
                r = review("Assess the actual result, not the commanded placement. relation=inside_supported requires the cream cheese package inside the bowl opening and supported by its interior, not balanced on the rim, held by the hand, on the plate, or on the table. released=yes requires visible separation from the gripper. Request point v on a uniquely identifiable visible interior printed package feature. definition describes that physical feature. On the second observation use EXACTLY the supplied previous definition; correspondence=certain only for that same point. Report uncertain rather than inventing occluded geometry.", {"relation": ["inside_supported", "outside_or_rim", "uncertain"], "released": ["yes", "no", "uncertain"], "correspondence": ["certain", "unknown"], "definition": "string"}, {"instruction": task, "previous_definition": definition, "historical_bowl": {"xy": g["bowl_xy"], "rim_z": g["rim_z"], "radius": g["radius"]}})
                p = r["parameters"]
                if p["relation"] != "inside_supported" or p["released"] != "yes" or p["correspondence"] != "certain": raise RuntimeError("Final relation, release or stability landmark remains unresolved: " + str(p))
                v = points(r, ["v"])[0]; samples.append(v); definition = p["definition"] if definition is None else definition
                api.checkpoint("final_observation", {"frame_id": r["frame_id"], "parameters": p, "point_world_m": v.tolist()})
            drift = float(np.linalg.norm(samples[1]-samples[0])); log({"post_release_landmark_drift_m": drift, "stability_tolerance_m": 2*g["u"]+0.003})
            if drift > 2*g["u"]+0.003: raise RuntimeError("Package did not remain stable between independent post-release views")
            save("done", final_relation="visually inside and supported; released; stable across two views", stability_drift_m=drift)
        return {"completion_proposed": D["p"]["phase"] == "done", "evidence": {"phase": D["p"], "measurements": D["log"], "limitation": "Local RGB-D and visual evidence, not a certified swept volume or official task evaluation."}}
    except Exception as e:
        log({"stopped": str(e), "phase": D["p"]["phase"], "gripper_policy": "Do not reopen an uncertain held object"})
        return {"completion_proposed": False, "evidence": {"phase": D["p"], "measurements": D["log"], "gap": str(e)}}

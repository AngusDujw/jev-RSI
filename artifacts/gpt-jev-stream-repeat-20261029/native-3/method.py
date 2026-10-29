def main(api):
    D, E, tracker, handles = {}, [], {}, [0]
    pixels = {"type":"array","minItems":4,"maxItems":8,"items":{"type":"array","minItems":2,"maxItems":2,"items":{"type":"integer","minimum":0,"maximum":767}}}
    Q = {a:{"type":"choice","instructions":"For world axis "+a+", use its bound goal_relation only: increase means positive, decrease negative, within_tolerance hold. Preserve the other axes.","criteria":{"negative":"Decrease this world coordinate or world rotation component.","hold":"This axis is within tolerance.","positive":"Increase this world coordinate or world rotation component."}} for a in ["x","y","z","rx","ry","rz"]}
    Q["gripper"] = {"type":"choice","instructions":"Use state.processed_features.objective.gripper. Deliver exactly open, close, or keep as requested; pose arrival is not contact evidence.","criteria":{"open":"Objective requests open.","close":"Objective requests close.","keep":"Objective requests keep."}}
    def clean(v):
        if isinstance(v,np.ndarray): return v.tolist()
        if isinstance(v,np.generic): return v.item()
        if isinstance(v,dict): return {k:clean(x) for k,x in v.items()}
        if isinstance(v,(list,tuple)): return [clean(x) for x in v]
        return v
    def record(kind, value):
        E.append({"kind":kind,"value":clean(value)})
        api.note(str(E[-1]))
    def save():
        api.checkpoint("bottle_plan", clean(D)); api.checkpoint("bottle_evidence", E[-8:])
    def ask(question, fields, context=None):
        if api.state()["budgets"]["gpt_remaining"] < 1: raise RuntimeError("No review budget for required observation")
        r = api.review(question, context=clean(context), fields=fields)
        record("review", {"frame":r["frame_id"],"parameters":r["parameters"],"measurement_errors":r["measurement_errors"]})
        if r["status"] == "stop": raise RuntimeError(r["explanation"])
        return r
    def require(r, kind, names):
        missing = [n for n in names if n not in r[kind]]
        if missing: raise RuntimeError("Missing "+kind+": "+str(missing)+"; "+str(r["measurement_errors"]))
    def plane(region):
        p = geo.plane(region["world_m"]); record("plane_fit",p)
        if p["rms_m"] > 0.002 or min(p["in_plane_spread_m"]) < 0.001: raise RuntimeError("Insufficient planar surface support")
        return p
    def circle(points):
        c = geo.circle_xy(points); record("circle_fit",c)
        if c["rms_m"] > 0.002 or c["max_radial_error_m"] > 0.004 or c["largest_angular_gap_rad"] > 5.2 or c["radius_m"] <= 3*c["rms_m"]: raise RuntimeError("Insufficient circular surface evidence")
        return c
    def cap(r):
        require(r,"regions",["cap"]); p = plane(r["regions"]["cap"]); n = np.array(p["coefficients"][:3])
        if n[2] < math.cos(0.12): raise RuntimeError("Current cork face does not support the upright-axis model")
        pts = [api.plane_point(r["regions"]["cap"]["camera"],x,clean(p["coefficients"]))["world_m"] for x in r["parameters"]["cap_rim"]]
        c = circle(pts); xy = c["center_xy_m"]; z = -(p["coefficients"][3]+np.dot(n[:2],xy))/n[2]
        u = 0.001+2*p["rms_m"]+c["rms_m"]
        return {"c":[xy[0],xy[1],float(z)],"n":n.tolist(),"u":u,"radius":c["radius_m"],"frame":r["frame_id"],"source":"current cap plane and visible circular rim"}
    def init_track(r, o):
        if handles[0] >= 16: tracker.clear(); return
        b = r["regions"]["cap"]["box"]; m = min(2,(b[2]-b[0])/4,(b[3]-b[1])/4)
        try:
            t = api.track_init(r["regions"]["cap"]["camera"],[[b[0]+m,b[1]+m],[b[2]-m,b[1]+m],[b[2]-m,b[3]-m],[b[0]+m,b[3]-m]])
            handles[0] += 1; tracker.update({"handle":t["handle"],"c":o["c"],"n":o["n"],"radius":o["radius"]}); record("tracker_init",t)
        except Exception as ex: tracker.clear(); record("tracker_unavailable",str(ex))
    def observe():
        if "handle" in tracker:
            try: t = api.track_update(tracker["handle"])
            except Exception as ex: t = {"status":"unknown","frame_id":api.state()["frame_id"]}; record("tracker_error",str(ex))
            if t["status"] == "tracked":
                p = np.array(t["reference_inlier_world_m"]); spread = np.linalg.svd(p-p.mean(axis=0),compute_uv=False)
                if t["inliers"] >= 8 and t["inliers"]/max(1,t["matches"]) >= 0.55 and t["rms_m"] <= 0.002 and t["uncertainty_floor_m"] <= 0.003 and spread[1]/math.sqrt(len(p)) > 0.001:
                    T = np.array(t["transform_initial_world_to_current_world"]); c = geo.transform([tracker["c"]],T)[0]; n = T[:3,:3]@np.array(tracker["n"])
                    return {"c":c.tolist(),"n":n.tolist(),"u":max(0.001,t["rms_m"]+t["uncertainty_floor_m"]),"radius":tracker["radius"],"frame":t["frame_id"],"source":"RGB-D rigid registration","inliers":t["inliers"],"reference_frame":t["reference_frame_id"]}
            record("registration_unknown",{"frame":t["frame_id"],"status":t["status"]})
        r = ask("Registration is unavailable or inadequate. Independently identify the SAME bottle's upper circular cork face, whose center and outward axis are the saved semantic references, not screen-relative corners. Request a named cap region (camera, interior box, stride 4) and cap_rim pixels on its visible rim in that SAME camera. These must identify the same intact upright bottle, not a detached cork. Return identity=corresponding only if unambiguous; otherwise ambiguous or unavailable. A new patch without a correspondence to this cap cannot establish motion.",{"identity":["corresponding","ambiguous","unavailable"],"cap_rim":pixels},{"reference":D["reference"],"historical_cap":D["cap"],"height":D["height"]})
        if r["parameters"]["identity"] != "corresponding": raise RuntimeError("No independently identifiable current cap landmark in either view; no geometry-supported alternative view action supplied")
        o = cap(r)
        if abs(o["radius"]-D["cap"]["radius"]) > 0.003+o["u"]: raise RuntimeError("Cap correspondence radius inconsistent")
        init_track(r,o); return o
    def move(target, gripper, label, calls=18, limit=0.02, reserve=25, tolerance=0.0025):
        s = api.state(); b = s["budgets"]; count = min(calls,int(b["jev_remaining"])-reserve,int(b["native_steps_remaining"])//3-reserve)
        if count < 1: raise RuntimeError("Action budget reserved for verification/recovery")
        D["pending"] = {"label":label,"target":list(target),"frame":s["frame_id"]}; save()
        r = api.drive(np.array(target).tolist(),D["q"],gripper,Q,features={"phase":label,"reference":D["reference"],"historical_geometry_frame":D["cap"]["frame"]},tool_point="pad_center",max_calls=count,translation_limit=limit,rotation_limit=0.08,steps=3,position_tolerance=tolerance,rotation_tolerance=0.04)
        record("drive",{"phase":label,"status":r["status"],"position_error_m":r["position_error_m"],"rotation_error_rad":r["rotation_error_rad"],"lease_calls":r["lease_calls"],"frame":r["frame_id"]})
        D["pending"] = None; save()
        if r["status"] != "reached": raise RuntimeError("No repeated contact push: "+r["status"]+" in "+label)
    def hold(gripper, label, repeats=3):
        b = api.state()["budgets"]
        if b["jev_remaining"] < repeats or b["native_steps_remaining"] < 3*repeats: raise RuntimeError("No budget for contact transition or stability interval")
        target = geo.pad_position(api.state()).tolist(); D["pending"] = {"label":label,"target":target}; save()
        for k in range(repeats):
            r = api.control(target,D["q"],gripper,Q,features={"phase":label},tool_point="pad_center",steps=3,translation_limit=0.003,rotation_limit=0.04,position_tolerance=0.0025,rotation_tolerance=0.04)
            record("control",{"phase":label,"status":r["status"],"frame":r["frame_id"]})
            if r["status"] == "stalled": raise RuntimeError("Unexpected stall during "+label)
            if r["status"] not in ["reached","moved"]: raise RuntimeError("Unexpected control status")
        D["pending"] = None; save()
    def permit(target, label, raise_option=False):
        r = ask("Assess ONLY the proposed local motion, not certify an entire later corridor. obstruction: none_observed means no visible external obstacle intersects this motion, observed_external means one does, unresolved means external obstacle versus occlusion cannot be distinguished. visibility: observed, partly_unobserved, or self_occluded (robot/held bottle). Partial visibility is not clearance, and self-occlusion is not an external obstacle. action: progress if the measured start and visible local surroundings justify this bounded motion; raise only if an observed obstacle blocks horizontal travel but an unobstructed local vertical raise is justified; otherwise stop. For raise request named point obstacle_top on the blocking object's highest relevant visible surface. For a retention-test lift, progress additionally requires fresh visual evidence that pads have closed around the neck without an obvious miss; plausible engagement is enough to start the test, not proof of retention. Do not require the full bottle outline.",{"obstruction":["none_observed","observed_external","unresolved"],"visibility":["observed","partly_unobserved","self_occluded"],"action":["progress","raise","stop"]},{"phase":label,"target_pad_world_m":list(target),"state":api.state(),"geometry":D,"allow_raise":raise_option})
        p = r["parameters"]
        if p["obstruction"] == "none_observed" and p["action"] == "progress": return None
        if raise_option and p["obstruction"] == "observed_external" and p["action"] == "raise":
            require(r,"points",["obstacle_top"]); return r["points"]["obstacle_top"]["world_m"][2]
        raise RuntimeError("Local action not justified: "+str(p))
    def attached(o):
        a = D["grasp"]; s = api.state(); err = geo.attachment_error([a["observation"]["c"]],[o["c"]],a["state"],s)
        angle = float(np.linalg.norm(np.array(o["n"])-geo.rotation(s["tcp_quaternion_xyzw"])@geo.rotation(a["state"]["tcp_quaternion_xyzw"]).T@np.array(a["observation"]["n"])))
        record("retention",{"attachment_error_m":err,"limit_m":0.004+a["observation"]["u"]+o["u"],"axis_discrepancy":angle,"observation":o})
        if err > 0.004+a["observation"]["u"]+o["u"] or angle > 0.12 or o["n"][2] < math.cos(0.12):
            if o["source"] == "RGB-D rigid registration":
                tracker.clear(); fresh = observe(); o.clear(); o.update(fresh); return attached(o)
            raise RuntimeError("Independent retention or upright-axis evidence failed; keep gripper state")
    def base(o): return np.array(o["c"])-np.array(o["n"])*D["height"]
    def relation(o):
        v = base(o); P = np.array(D["polygon"])[:,:2]; edges = np.roll(P,-1,axis=0)-P; w = v[:2]-P
        clearance = np.min(D["winding"]*(edges[:,0]*w[:,1]-edges[:,1]*w[:,0])/np.linalg.norm(edges,axis=1)); gap = float(np.dot(D["landing_plane"][:3],v)+D["landing_plane"][3])
        record("placement_geometry",{"base_axis_intersection":v.tolist(),"support_gap_m":gap,"edge_clearance_m":float(clearance),"body_radius_m":D["radius"],"uncertainty_m":o["u"],"source":o["source"]})
        valid = abs(gap) <= 0.006+o["u"] and clearance > D["radius"]+0.005+o["u"]
        if not valid and o["source"] == "RGB-D rigid registration":
            tracker.clear(); fresh = observe(); o.clear(); o.update(fresh); return relation(o)
        return bool(valid)
    try:
        if any(m["key"] == "bottle_plan" for m in api.recall()):
            D = api.recall("bottle_plan")["value"]; record("resumed_historical_phase",D["phase"])
            r = ask("Revalidate the saved semantic bottle identity and stationary rack table 1 support geometry. These checkpoints are historical, not current observations. dependencies=valid only if those identities and unchanged support remain justified. If done, also verify the completed bottle/support relation and open-hand separation remain unchanged. If planned, also verify source remains seated and neck model unchanged; never call a held bottle source-stationary. Report gripper_relation as holding, empty, or unknown.",{"dependencies":["valid","changed","unknown"],"gripper_relation":["holding","empty","unknown"]},D)
            if r["parameters"]["dependencies"] != "valid" or (D["phase"] == "planned" and r["parameters"]["gripper_relation"] != "empty"): raise RuntimeError("Repair dependencies not revalidated")
            if D["phase"] in ["held","transfer","lower"] and r["parameters"]["gripper_relation"] == "empty": raise RuntimeError("Repair observes loss of held bottle")
        else:
            r = ask("Task: put the wine bottle on rack table 1. Identify that physical support, not another rack tier; ambiguous identity must be reported. Acquire named interior regions cap (textured cork top), neck (constant-radius bare neck), body (widest cylindrical body), floor (table at bottle base), landing (usable rack table 1 surface), each with camera, box, stride 4. Exclude background and boundaries. Request points neck_hi and neck_lo at ends of the usable bare-neck band, and base_contact at a visible bottle/table contact. Return cap_rim: 4-8 visible circular cork rim pixels in cap camera; landing_rim: 4-8 ordered boundary pixels of a convex usable support area in landing camera. Return bottle_model=upright_coaxial_seated only if cap, neck and widest body are coaxial circles and bottle is seated upright. Return target=rack_table_1 only for the identified requested support, otherwise ambiguous; reference must describe persistent physical bottle/cap and target identities, not camera-relative corners.",{"bottle_model":["upright_coaxial_seated","unknown"],"target":["rack_table_1","ambiguous"],"cap_rim":pixels,"landing_rim":pixels,"reference":{"type":"string","maxLength":900}})
            seed = {"frame":r["frame_id"],"parameters":r["parameters"],"points":r["points"],"regions":{k:{"camera":v["camera"],"box":v["box"],"frame":v["frame_id"],"world_m":np.array(v["world_m"])[np.linspace(0,len(v["world_m"])-1,min(32,len(v["world_m"]))).astype(int)].tolist()} for k,v in r["regions"].items() if len(v["world_m"]) > 0}}
            api.checkpoint("measurement_seed",clean(seed))
            require(r,"regions",["cap","neck","body","floor","landing"]); require(r,"points",["neck_hi","neck_lo","base_contact"])
            if r["parameters"]["bottle_model"] != "upright_coaxial_seated" or r["parameters"]["target"] != "rack_table_1": raise RuntimeError("Unresolved task identity or bottle model")
            o = cap(r); f = plane(r["regions"]["floor"]); l = plane(r["regions"]["landing"]); neck = circle(r["regions"]["neck"]["world_m"]); body = circle(r["regions"]["body"]["world_m"])
            if min(f["coefficients"][2],l["coefficients"][2]) < math.cos(0.10): raise RuntimeError("Support not sufficiently horizontal")
            n = np.array(o["n"]); c = np.array(o["c"]); height = float((np.dot(f["coefficients"][:3],c)+f["coefficients"][3])/np.dot(f["coefficients"][:3],n))
            contact = np.array(r["points"]["base_contact"]["world_m"]); contact_error = abs(float(np.dot(f["coefficients"][:3],contact)+f["coefficients"][3]))
            s = api.state(); R = geo.rotation(s["tcp_quaternion_xyzw"]); own = s["own_geometry"]; half = np.abs(R)@np.array(own["pad_extent_in_tool_m"])/2
            lo, hi = sorted([r["points"]["neck_lo"]["world_m"][2],r["points"]["neck_hi"]["world_m"][2]]); margin = 0.0015+o["u"]; band = hi-lo-2*(half[2]+margin)
            record("grasp_geometry",{"usable_band_m":band,"neck_diameter_m":2*neck["radius_m"],"pad_extent":own["pad_extent_in_tool_m"],"opening_axis_world":R[:,1].tolist(),"base_contact_error_m":contact_error,"height_m":height})
            if band <= 0 or abs(R[2,1]) > 0.15 or contact_error > 0.005 or height <= hi-lo or 2*neck["radius_m"]+2*margin >= own["pad_extent_in_tool_m"][1]: raise RuntimeError("Measured neck/finger geometry has no supported candidate")
            if max(np.linalg.norm(np.array(x["center_xy_m"])-c[:2]) for x in [neck,body]) > 0.006: raise RuntimeError("Coaxial model inconsistent with visible surfaces")
            polygon = [api.plane_point(r["regions"]["landing"]["camera"],p,clean(l["coefficients"]))["world_m"] for p in r["parameters"]["landing_rim"]]; P = np.array(polygon); center = P.mean(axis=0)
            e = np.roll(P[:,:2],-1,axis=0)-P[:,:2]; winding = 1 if np.sum(P[:,0]*np.roll(P[:,1],-1)-P[:,1]*np.roll(P[:,0],-1)) > 0 else -1
            if float(np.min(np.linalg.norm(e,axis=1))) < 0.001: raise RuntimeError("Degenerate landing polygon edge")
            distances = [winding*(e[:,0]*(v[1]-P[:,1])-e[:,1]*(v[0]-P[:,0]))/np.linalg.norm(e,axis=1) for v in P]
            if min(float(np.min(x)) for x in distances) < -0.002: raise RuntimeError("Landing polygon is not convex and consistently ordered")
            clearance = float(np.min(winding*(e[:,0]*(center[1]-P[:,1])-e[:,1]*(center[0]-P[:,0]))/np.linalg.norm(e,axis=1)))
            record("landing_margin",{"edge_clearance_m":clearance,"required_m":body["radius_m"]+0.008+height*0.08})
            if clearance <= body["radius_m"]+0.008+height*0.08: raise RuntimeError("Measured support footprint insufficient")
            corners = [[x,y,z] for x in [own["finger_low_offset_tool_m"][0],own["finger_high_offset_tool_m"][0]] for y in [own["finger_low_offset_tool_m"][1],own["finger_high_offset_tool_m"][1]] for z in [own["finger_low_offset_tool_m"][2],own["finger_high_offset_tool_m"][2]]]
            low = float(np.min((R@(np.array(corners)-np.array(own["pad_center_in_tool_m"])).T)[2]))
            D = {"phase":"planned","reference":r["parameters"]["reference"]+"; landmark is center and outward normal of this same circular cork top, yaw unobserved","cap":o,"height":height,"radius":body["radius_m"],"landing_plane":l["coefficients"],"polygon":polygon,"landing":center.tolist(),"winding":winding,"g":[neck["center_xy_m"][0],neck["center_xy_m"][1],(lo+hi)/2],"q":s["tcp_quaternion_xyzw"],"pre_z":o["c"][2]-low+0.015,"source_plane":f["coefficients"],"initial_frame":r["frame_id"]}
            save(); init_track(r,o)
        if D["phase"] == "planned":
            o = D["cap"] if D["cap"]["frame"] == api.state()["frame_id"] else observe(); delta = np.array(o["c"])-np.array(D["cap"]["c"]); g = np.array(D["g"])+delta
            pre = g.copy(); pre[2] = max(g[2]+0.03,D["pre_z"]+delta[2]); permit(pre,"open approach above neck"); move(pre,"open","pregrasp")
            permit(g,"open descent to measured neck band"); move(g,"open","neck approach",18,0.01)
            r = ask("Check actual open finger pads, not commanded pose: are opposite pads straddling the bare neck with visible side clearance and no shoulder/cork/external contact? grip=aligned permits closure, misaligned permits one small center correction, obstructed or unknown stops. Full body perimeter visibility is unnecessary.",{"grip":["aligned","misaligned","obstructed","unknown"]},D)
            if r["parameters"]["grip"] == "misaligned":
                o = observe(); corrected = np.array(D["g"])+np.array(o["c"])-np.array(D["cap"]["c"])
                if np.linalg.norm(corrected-geo.pad_position(api.state())) > 0.012: raise RuntimeError("Correction exceeds local allowance")
                permit(corrected,"single open neck correction"); move(corrected,"open","neck correction",8,0.004)
                r = ask("After correction, are the actual opposing open pads straddling the same bare neck with side clearance and no external contact?",{"grip":["aligned","obstructed","unknown"]},D)
            if r["parameters"]["grip"] != "aligned": raise RuntimeError("No observed grasp aperture")
            D["anchor"] = observe(); D["anchor_state"] = api.state(); D["phase"] = "closing"; save()
        if D["phase"] == "closing":
            hold("close","neck closure"); D["phase"] = "closed"; save()
        if D["phase"] == "closed":
            t = geo.pad_position(api.state())+np.array([0,0,0.035]); permit(t,"retention test: closure at aligned neck is plausible; lift 35 mm to observe whole-bottle response"); move(t,"close","retention lift",12,0.008)
            o = observe(); err = geo.attachment_error([D["anchor"]["c"]],[o["c"]],D["anchor_state"],api.state()); hand = np.linalg.norm(np.array(api.state()["tcp_position_world_m"])-np.array(D["anchor_state"]["tcp_position_world_m"])); object_motion = np.linalg.norm(np.array(o["c"])-np.array(D["anchor"]["c"]))
            if err > 0.005+D["anchor"]["u"]+o["u"] and o["source"] == "RGB-D rigid registration":
                tracker.clear(); o = observe(); err = geo.attachment_error([D["anchor"]["c"]],[o["c"]],D["anchor_state"],api.state()); object_motion = np.linalg.norm(np.array(o["c"])-np.array(D["anchor"]["c"]))
            record("lift_test",{"hand_motion_m":float(hand),"cap_motion_m":float(object_motion),"attachment_error_m":err,"observation":o})
            if hand < 0.02 or object_motion < 0.018 or err > 0.005+D["anchor"]["u"]+o["u"]: raise RuntimeError("Lift did not establish correlated object/hand motion")
            r = ask("Assess the actual lift result: whole_bottle_airborne means the intact bottle, not merely its cork or a reflection, is held upright above its old support. supported_or_lost and unknown do not establish retention. The complete perimeter need not be visible.",{"effect":["whole_bottle_airborne","supported_or_lost","unknown"]},{"before":D["anchor"],"after":o,"source_plane":D["source_plane"]})
            if r["parameters"]["effect"] != "whole_bottle_airborne": raise RuntimeError("No whole-bottle retention evidence")
            D["grasp"] = {"observation":o,"state":api.state()}; D["offset"] = (geo.pad_position(api.state())-base(o)).tolist(); D["phase"] = "held"; save()
        if D["phase"] in ["held","transfer"]:
            o = D["grasp"]["observation"] if D["grasp"]["observation"]["frame"] == api.state()["frame_id"] else observe(); attached(o); p = geo.pad_position(api.state()); high = max(p[2],D.get("route_z",0),D["landing"][2]+D["offset"][2]+0.04)
            t = p.copy(); t[2] = high
            if high-p[2] > 0.003: permit(t,"vertical source-side raise with retained bottle"); move(t,"keep","raise to transfer height",24); attached(observe())
            D["phase"] = "transfer"; D["route_z"] = high; save(); detours = 0
            for leg in range(22):
                p = geo.pad_position(api.state()); goal = np.array(D["landing"])+np.array(D["offset"]); goal[2] = D["route_z"]; distance = float(np.linalg.norm(goal-p))
                if distance <= 0.004: break
                if distance > 0.6 or api.state()["budgets"]["gpt_remaining"] < 8: raise RuntimeError("Route bound or reserved verification budget reached")
                t = p+(goal-p)*min(1,0.04/distance); obstacle_z = permit(t,"bounded horizontal transfer leg",True)
                if obstacle_z is not None:
                    if detours >= 2: raise RuntimeError("Obstacle recovery bound reached")
                    t = p.copy(); t[2] = max(p[2]+0.025,obstacle_z+D["offset"][2]+0.025)
                    if t[2]-p[2] > 0.20: raise RuntimeError("Required obstacle raise exceeds local recovery bound")
                    permit(t,"measured obstacle-height vertical detour"); move(t,"keep","vertical detour",18); D["route_z"] = float(t[2]); detours += 1
                else: move(t,"keep","transfer leg",8)
                o = observe(); attached(o); D["last_observation"] = o; save()
            if np.linalg.norm((np.array(D["landing"])+np.array(D["offset"]))[:2]-geo.pad_position(api.state())[:2]) > 0.005: raise RuntimeError("Bounded route incomplete")
            D["phase"] = "lower"; save()
        if D["phase"] == "lower":
            o = D["last_observation"] if "last_observation" in D and D["last_observation"]["frame"] == api.state()["frame_id"] else observe(); attached(o); target = np.array(D["landing"])+geo.pad_position(api.state())-base(o); above = target+np.array([0,0,0.03])
            permit(above,"lower toward the same stationary landing support; distinguish table/held-object occlusion from external obstructions"); move(above,"keep","preplacement",24); attached(observe())
            target[2] += 0.003; permit(target,"final gentle lower, predicted base 3 mm above support"); move(target,"keep","final lower",12,0.004,14,0.0015)
            o = observe(); attached(o)
            if not relation(o): raise RuntimeError("Current measured base/support relation does not permit release")
            r = ask("Before release, compare current images with the measured base/support relation. relation=consistent only if the intact upright bottle is over rack table 1 with small gap or contact and no visible side/backstop interference. Self-occluded base alone is not contradiction: the current cap/axis and measured height supply the geometric estimate. unknown means identity or contradictory geometry cannot be resolved.",{"relation":["consistent","contradiction","unknown"]},{"geometry":D,"current":o})
            if r["parameters"]["relation"] != "consistent": raise RuntimeError("Release relation unresolved")
            D["before_release"] = o; D["phase"] = "releasing"; save()
        if D["phase"] == "releasing":
            o = D["before_release"] if D["before_release"]["frame"] == api.state()["frame_id"] else observe()
            if not relation(o): raise RuntimeError("Support relation changed before/while releasing")
            hold("open","release"); D["phase"] = "released"; save()
        if D["phase"] == "released":
            r = ask("Observe actual opening outcome. effect=on_support_or_separating permits a short upward empty-hand observation retreat if the bottle remains over the support and there is no visible snag. following_hand, displaced, or unknown do not. Do not infer release from the command.",{"effect":["on_support_or_separating","following_hand","displaced","unknown"]},D)
            if r["parameters"]["effect"] != "on_support_or_separating": raise RuntimeError("Release effect unresolved")
            t = geo.pad_position(api.state())+np.array([0,0,0.07]); permit(t,"open-hand upward observation retreat"); move(t,"open","retreat",16,0.012,4)
            first = observe(); still_start = api.state()["native_steps"]; hold("open","stationarity interval",2); second = observe(); support_ok = relation(second); drift = float(np.linalg.norm(np.array(first["c"])-np.array(second["c"])))
            if drift > 0.003+first["u"]+second["u"]:
                tracker.clear(); first = observe(); hold("open","one bounded stability recheck",2); second = observe(); support_ok = relation(second); drift = float(np.linalg.norm(np.array(first["c"])-np.array(second["c"])))
            record("post_release_stability",{"first":first,"second":second,"drift_m":drift,"tcp_separation_m":float(np.linalg.norm(geo.pad_position(api.state())-np.array(second["c"])))})
            if api.state()["native_steps"] <= still_start: raise RuntimeError("No acknowledged physical interval for stability observation")
            if not support_ok or drift > 0.003+first["u"]+second["u"]: raise RuntimeError("Post-release relation or finite-interval stability failed")
            r = ask("From the new post-retreat views, assess the actual task: whole wine bottle resting upright on rack table 1, separated from the open hand, not on a different tier, not falling or leaning on another object. goal=yes requires that observed relation; no or unknown prevents completion. This is a proposal, not official success.",{"goal":["yes","no","unknown"]},{"reference":D["reference"],"first":first,"second":second,"drift_m":drift})
            if r["parameters"]["goal"] != "yes": raise RuntimeError("Final visual goal relation not established")
            D["phase"] = "done"; D["final"] = {"first":first,"second":second,"drift_m":drift,"review_frame":r["frame_id"]}; save()
        return {"completion_proposed":D["phase"] == "done","evidence":E[-24:],"phase":D["phase"],"limitations":["Finite RGB-D evidence, not certified collision clearance or indefinite stability; yaw of an untextured circular cap remains unobserved."]}
    except Exception as ex:
        record("incomplete",str(ex))
        if D: save()
        return {"completion_proposed":False,"evidence":E[-24:],"phase":D.get("phase","initial_measurement"),"reason":str(ex)}

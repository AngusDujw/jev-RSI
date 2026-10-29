def main(api):
    log=[]; run={"g":None,"phase":"survey","anchor":None,"retained":False,"q":None,"last":None}; tr={"handle":None,"attempts":0}
    pix={"type":"array","items":{"type":"integer","minimum":0,"maximum":767},"minItems":2,"maxItems":2}
    def arr(item,lo,hi): return {"type":"array","items":item,"minItems":lo,"maxItems":hi}
    cam=["agentview","robot0_eye_in_hand"]; yn=["yes","no","unknown"]
    patch_fields={"patch_camera":cam,"patch_polygon":{"type":["array","null"],"items":pix,"minItems":3,"maxItems":16}}
    questions={}
    for axis in ["x","y","z","rx","ry","rz"]:
        questions[axis]={"type":"choice","instructions":"For world axis "+axis+", use state.processed_features.axes."+axis+".goal_relation. Select the matching direction, not an image direction.","criteria":{"negative":"decrease","hold":"within_tolerance","positive":"increase"}}
    questions["gripper"]={"type":"choice","instructions":"Read state.processed_features.objective.gripper and select that exact requested operation.","criteria":{"open":"The objective requests open.","close":"The objective requests close.","keep":"The objective requests keep."}}
    def note(x):
        log.append(x); api.note(str(x))
    def save():
        api.checkpoint("phase",run)
    def review(question,fields,context=None):
        if api.state()["budgets"]["gpt_remaining"]<1: raise RuntimeError("No observation review budget.")
        r=api.review(question,context=context,fields=fields)
        if r["measurement_errors"]: note({"measurement_errors":r["measurement_errors"],"frame_id":r["frame_id"]})
        if r["status"]=="stop": raise RuntimeError(r["explanation"])
        return r
    def point(r,name):
        if name not in r["points"]: raise RuntimeError("Missing current point: "+name)
        p=r["points"][name]
        if p["frame_id"]!=r["frame_id"]: raise RuntimeError("Point freshness mismatch.")
        return np.array(p["world_m"],dtype=float)
    def cloud(r,name):
        if name not in r["regions"]: raise RuntimeError("Missing current region: "+name)
        p=r["regions"][name]
        if p["frame_id"]!=r["frame_id"]: raise RuntimeError("Cloud freshness mismatch.")
        a=np.array(p["world_m"],dtype=float)
        if len(a)<6 or not np.all(np.isfinite(a)): raise RuntimeError("Insufficient finite surface samples: "+name)
        return a
    def plane(a,label):
        f=geo.plane(a); note({"fit":label,"rms_m":float(f["rms_m"]),"coefficients":np.asarray(f["coefficients"]).tolist(),"spread_m":np.asarray(f["in_plane_spread_m"]).tolist()})
        if f["rms_m"]>0.004 or f["coefficients"][2]<0.97 or min(f["in_plane_spread_m"])<0.001: raise RuntimeError("Unresolved horizontal surface fit: "+label)
        return f
    def z_at(p,xy): return float(-(p[0]*xy[0]+p[1]*xy[1]+p[3])/p[2])
    def margin(xy,poly):
        a=np.array(poly); b=np.roll(a,-1,axis=0); e=b-a; d=e[:,0]*(xy[1]-a[:,1])-e[:,1]*(xy[0]-a[:,0])
        sign=1 if np.sum(a[:,0]*b[:,1]-b[:,0]*a[:,1])>0 else -1
        return float(np.min(sign*d/np.maximum(np.linalg.norm(e,axis=1),0.000001)))
    def start_track(camera,polygon,c,frame):
        if polygon is None or tr["attempts"]>=3: return
        tr["attempts"]+=1
        try:
            t=api.track_init(camera,polygon)
            if t["frame_id"]!=frame: raise RuntimeError("Patch/reference frame mismatch.")
            tr.update({"handle":t["handle"],"c":list(c),"frame":t["frame_id"]})
            note({"tracker_reference_frame":t["frame_id"],"features":t["reference_features"]})
        except Exception as e: tr["handle"]=None; note({"patch_initialization_error":str(e)})
    def tracked():
        if tr["handle"] is None: return None
        try:
            t=api.track_update(tr["handle"])
            if t["status"]!="tracked": tr["reason"]=t["reason"]; return None
            u=max(run["g"]["u"],float(t["rms_m"])+float(t["uncertainty_floor_m"]))
            good=t["frame_id"]==api.state()["frame_id"] and t["reference_frame_id"]==tr["frame"] and t["inliers"]>=12 and t["inliers"]/max(1,t["matches"])>=0.6 and t["rms_m"]<=0.0025 and u<=0.006 and float(np.max(np.asarray(t["inlier_spread_m"])))>=0.003
            if not good: tr["reason"]="Registration quality or freshness insufficient."; return None
            T=np.array(t["transform_initial_world_to_current_world"]); c=geo.transform(np.array([tr["c"]]),T)[0]
            return {"c":c.tolist(),"u":u,"upright":bool(T[2,2]>0.99),"frame":t["frame_id"],"source":"RGB-D rigid registration"}
        except Exception as e: tr["reason"]=str(e); return None
    def receipt(r,requested):
        note({"phase":run["phase"],"status":r["status"],"after_tcp":r["after"],"frame_id":r["frame_id"]})
        run["receipt"]={"status":r["status"],"frame_id":r["frame_id"],"after_tcp":r["after"]}; save()
        if r["choices"]["gripper"]!=requested or r["status"]=="stalled":
            run["explicit_failure"]="Unexpected gripper choice or stalled motion; do not repeat this physical action."; save(); raise RuntimeError(run["explicit_failure"])
    def act(target,gripper,lease=1,quat=None):
        if api.state()["budgets"]["jev_remaining"]<lease+6 or api.state()["budgets"]["native_steps_remaining"]<3*lease+18: raise RuntimeError("Reserved verification control budget reached.")
        run["intent"]={"pad_target":list(target),"gripper":gripper}; save()
        kw={"target":list(target),"quaternion":run["q"] if quat is None else quat,"gripper":gripper,"questions":questions,"features":{"phase":run["phase"],"retention_observed":run["retained"],"uncertainty_m":run["g"]["u"]},"tool_point":"pad_center","translation_limit":0.02,"rotation_limit":0.08,"steps":3,"position_tolerance":0.002,"rotation_tolerance":0.04}
        r=api.drive(max_calls=lease,**kw) if lease>1 else api.control(**kw)
        receipt(r,gripper); return r
    def sense(target=None,probe=False,preclose=False):
        g=run["g"]
        for attempt in range(2):
            o=tracked(); fields={"identity":["same_item","ambiguous","not_visible"],"upright":yn}
            if target is not None: fields.update({"obstruction":["external_obstacle","none_observed","unknown"],"visibility":["locally_visible","robot_or_load_occlusion","unobserved"]})
            if preclose or probe: fields["engagement"]=["neck_between_pads","miss_or_displaced","unknown"]
            if o is None: fields.update(patch_fields)
            if o is None or target is not None: fields["yaw_view"]=["justified","not_useful","unsafe_or_unknown"]
            ctx={"reference":g,"phase":run["phase"],"pad_target":target,"registration":o,"tracker_problem":tr.get("reason"),"last_observation":run["last"],"anchor":run["anchor"],"preserved_orientation":run["q"],"current_pad_center_world_m":geo.pad_position(api.state()).tolist()}
            r=review("Identify the SAME instructed item. identity and upright describe current evidence. For a pad_target assess ONLY the immediate bounded leg, including measured finger envelope and the upright bottle down to its base, not the entire later route. obstruction distinguishes an observed external obstacle, none observed, and inability to assess. visibility distinguishes a locally observed neighborhood, occlusion only by robot/load, and genuinely unobserved external space. No clearance certificate is requested. Report external obstacles even when partly occluded. If engagement is requested, say neck_between_pads only when the neck is visibly aligned inside the pads; it is NOT a retention claim. If registration is absent, request named point mark at the visible geometric CENTER OF THE CIRCULAR CORK TOP, the saved persistent landmark; use either camera, never a historical projection as a detection. Reject ambiguous identity or an obscured center. Also supply patch_camera and patch_polygon for a better textured interior patch on this same rigid item, or null if none. If yaw_view is declared, justified means a positive 0.15 rad world-z rotation about the current pad center would genuinely expose the missing landmark OR unresolved immediate neighborhood to agentview, and its OWN local swept envelope has supporting visible evidence with no observed external obstacle. Use the supplied yaw radius; do not demand visibility of the later translation corridor before this view action. Identical self-occlusion is not useful. Otherwise choose not_useful or unsafe_or_unknown.",fields,ctx)
            p=r["parameters"]
            if p["identity"]!="same_item": raise RuntimeError("Current item identity is unresolved.")
            if target is not None and (p["obstruction"]!="none_observed" or p["visibility"]=="unobserved"):
                if attempt==0 and (run["retained"] or run["phase"]=="approach") and p["yaw_view"]=="justified":
                    run["q"]=api.compose(api.state()["tcp_quaternion_xyzw"],[0,0,0.15]); save(); act(geo.pad_position(api.state()).tolist(),"keep",6); continue
                raise RuntimeError("Local action gap: "+p["obstruction"]+" / "+p["visibility"]+"; no justified useful view change.")
            if (preclose or probe) and p["engagement"]!="neck_between_pads": raise RuntimeError("Neck alignment/contact transition is not supported.")
            if o is None and "mark" in r["points"]:
                c=point(r,"mark"); o={"c":c.tolist(),"u":g["u"]+0.002,"upright":p["upright"]=="yes","frame":r["frame_id"],"source":"independently reidentified cork-center landmark"}
                start_track(p["patch_camera"],p["patch_polygon"],c.tolist(),r["frame_id"])
            if o is not None:
                if p["upright"]=="no" or not o["upright"]: raise RuntimeError("Upright geometry no longer justified.")
                if run["anchor"] is not None:
                    a=run["anchor"]; err=float(geo.attachment_error([a["c"]],[o["c"]],a["hand"],api.state())); tol=a["u"]+o["u"]+0.003
                    note({"attachment_error_m":err,"tolerance_m":tol,"observed_center":o["c"],"frame_id":o["frame"]})
                    if err>tol: raise RuntimeError("Observed object motion does not match measured hand motion; retention unresolved.")
                elif np.linalg.norm(np.array(o["c"])-g["c"])>g["u"]+o["u"]+0.004: raise RuntimeError("Source object moved; old approach geometry is stale.")
                run["last"]=o; save(); return o
            if probe and attempt==0:
                note({"probe_authorized_without_current_registration":True,"basis":"preclosure reference plus visible neck alignment; lift will measure retention"}); return None
            if attempt==0 and run["retained"] and p["yaw_view"]=="justified":
                run["q"]=api.compose(api.state()["tcp_quaternion_xyzw"],[0,0,0.15]); save(); act(geo.pad_position(api.state()).tolist(),"keep",6); continue
            raise RuntimeError("Unknown registration and no identifiable current cork center or justified useful view change.")
    def move(goal,gripper="keep",probe=False,contact=False):
        distance=float(np.linalg.norm(np.array(goal)-geo.pad_position(api.state())))
        if distance>0.6: raise RuntimeError("Requested phase exceeds the measured local workspace policy.")
        for leg in range(int(math.ceil(distance/0.01))+8):
            state=api.state(); p=geo.pad_position(state); delta=np.array(goal)-p; d=float(np.linalg.norm(delta))
            if d<=0.003: return
            if state["budgets"]["gpt_remaining"]<4: raise RuntimeError("Reserved release/final observation budget reached.")
            nxt=p+delta*min(1,0.075/d); sense(nxt.tolist(),probe=probe)
            if run["phase"]=="lower" or probe or contact:
                for update in range(8):
                    r=act(nxt.tolist(),gripper)
                    if r["status"]=="reached": break
            else: r=act(nxt.tolist(),gripper,8)
            remaining=float(np.linalg.norm(np.array(goal)-geo.pad_position(api.state()))); progress=d-remaining
            if r["status"] in ["moved","lease_exhausted"] and progress<min(0.01,0.5*d):
                note({"remaining_m":remaining,"target_directed_progress_m":progress}); raise RuntimeError("Insufficient progress for the finite route bound; stop rather than push.")
        raise RuntimeError("Finite route bound exhausted; smallest local progress and remaining distance are not assumed sufficient.")
    try:
        manifest=api.recall(); keys=[x["key"] for x in manifest]
        if "phase" in keys:
            run=api.recall("phase")["value"]
            if "explicit_failure" in run: raise RuntimeError(run["explicit_failure"])
            if run["g"] is None: raise RuntimeError("Only partial survey exists; inspect saved measurements before repair.")
            r=review("Reidentify the saved item and destination from current images. target_state=unchanged only if the same stationary rack support still agrees with saved reference geometry. Check current observations, not projected old markers. Explain changes or ambiguity.",{"target_state":["unchanged","changed","unknown"]},{"reference":run["g"],"phase":run["phase"]})
            if r["parameters"]["target_state"]!="unchanged": raise RuntimeError("Saved destination dependency is not revalidated.")
        else:
            fields={"suitable":["yes","no","unknown"],"labels":{"type":"string","maxLength":900},"rim_camera":cam,"rim_pixels":arr(pix,6,6),"target_camera":cam,"target_corners":arr(pix,4,4)}
            fields.update(patch_fields)
            r=review("Interpret the runtime instruction and identify its wine bottle and rack-table destination, not the stove or unrelated table. labels must identify the requested item and destination and explain any naming ambiguity. suitable=yes requires a currently supported upright bottle, circular horizontal cork top centered on a round body, a straight graspable neck no wider than the cork, and an identifiable horizontal supporting shelf of the requested rack. Choose a reachable open shelf landing area; do not infer hidden boundaries. Request named regions top (cork interior), neck (full straight neck height, excluding background/shoulder), body (cylindrical body interior), source (support beside its base), target_a and target_b (two separated visible shelf-top interiors), each with explicit camera, box, stride=4. Request named point mark at the geometric center of the cork top. rim_camera/rim_pixels are six visible cork-rim pixels around its perimeter; target_camera/target_corners are four visible corners in perimeter order bounding a supporting landing area, excluding rails and holes. These boundary pixels will be intersected with measured planes, not trusted mixed boundary depth. Give patch_camera/patch_polygon for a textured rigid interior patch on the cork/bottle, preferably from the best texture view, or null.",fields)
            p=r["parameters"]; raw={}
            for name,v in r["regions"].items(): raw[name]={"world_m":v["world_m"][::max(1,int(len(v["world_m"])/20)+1)],"camera":v["camera"],"frame_id":v["frame_id"]}
            api.checkpoint("survey",{"parameters":p,"regions":raw,"points":r["points"],"measurement_errors":r["measurement_errors"],"frame_id":r["frame_id"]})
            if p["suitable"]!="yes": raise RuntimeError("Task identity, visible support, or upright neck-grasp geometry unresolved: "+p["labels"])
            top=plane(cloud(r,"top"),"cork"); source=plane(cloud(r,"source"),"source"); dest=plane(np.concatenate([cloud(r,"target_a"),cloud(r,"target_b")]),"destination")
            rim=np.array([api.plane_point(p["rim_camera"],xy,np.asarray(top["coefficients"]).tolist())["world_m"] for xy in p["rim_pixels"]]); cap=geo.circle_xy(rim); body=geo.circle_xy(cloud(r,"body")); neck=cloud(r,"neck"); c=point(r,"mark")
            u=0.002+max(float(top["rms_m"]),float(source["rms_m"]),float(dest["rms_m"]),float(cap["max_radial_error_m"]),float(body["max_radial_error_m"]))
            note({"uncertainty_heuristic_m":u,"cap_radius_m":float(cap["radius_m"]),"body_radius_m":float(body["radius_m"]),"body_angular_gap_rad":float(body["largest_angular_gap_rad"]),"cap_angular_gap_rad":float(cap["largest_angular_gap_rad"]),"cap_center_error_m":float(np.linalg.norm(np.array(cap["center_xy_m"])-c[:2])),"body_axis_error_m":float(np.linalg.norm(np.array(body["center_xy_m"])-c[:2])),"neck_observed_radial_extent_m":float(np.max(np.linalg.norm(neck[:,:2]-c[:2],axis=1)))})
            if u>0.006 or cap["largest_angular_gap_rad"]>2 or body["largest_angular_gap_rad"]>5.5 or np.linalg.norm(np.array(cap["center_xy_m"])-c[:2])>2*u or np.linalg.norm(np.array(body["center_xy_m"])-c[:2])>3*u: raise RuntimeError("Circular geometry or upright axis evidence is inadequate.")
            poly=np.array([api.plane_point(p["target_camera"],xy,np.asarray(dest["coefficients"]).tolist())["world_m"][:2] for xy in p["target_corners"]]); center=np.mean(poly,axis=0); radius=float(body["radius_m"])+float(np.linalg.norm(np.array(body["center_xy_m"])-c[:2]))+u; available=margin(center,poly.tolist())
            s=api.state(); own=s["own_geometry"]; R=geo.rotation(s["tcp_quaternion_xyzw"]); ext=np.array(own["pad_extent_in_tool_m"]); opening=abs(s["gripper_qpos_m"][0]-s["gripper_qpos_m"][1]); gap=2*opening-ext[1]
            low=own["finger_low_offset_tool_m"]; high=own["finger_high_offset_tool_m"]; corners=np.array([[x,y,z] for x in [low[0],high[0]] for y in [low[1],high[1]] for z in [low[2],high[2]]]); rel=(corners-np.array(own["pad_center_in_tool_m"]))@R.T
            half=float(np.sum(np.abs(R[2])*ext)/2); down=max(0,float(-np.min(rel[:,2]))); lo=float(np.min(neck[:,2]))+max(half,down)+u+0.002; hi=float(np.max(neck[:,2]))-half-u-0.002
            note({"tool_world_z_row":R[2].tolist(),"open_inner_gap_m":float(gap),"required_neck_aperture_m":2*(float(cap["radius_m"])+u+0.002),"grasp_z_interval_m":[lo,hi],"landing_inradius_m":available,"required_landing_radius_m":radius+u+0.004,"finger_bounds_relative_to_pad": [np.min(rel,axis=0).tolist(),np.max(rel,axis=0).tolist()]})
            if int(np.argmax(ext))!=1 or abs(R[2,1])>0.15 or R[2,2]>-0.95 or gap<2*(cap["radius_m"]+u+0.002) or hi<lo or available<radius+u+0.004: raise RuntimeError("Measured finger, neck, or landing geometry is infeasible; see numerical evidence.")
            if float(np.max(np.linalg.norm(neck[:,:2]-c[:2],axis=1)))>cap["radius_m"]+2*u: raise RuntimeError("Neck samples contradict the observed narrow-neck model.")
            H=float(c[2]-z_at(source["coefficients"],c[:2])); gz=min(hi,max(lo,float(np.median(neck[:,2]))))
            if H<=0 or gz>=c[2] or radius<=0: raise RuntimeError("Invalid measured height/neck model.")
            g={"labels":p["labels"],"mark_definition":"Geometric center of the same circular cork top; not a camera-relative corner or a historical projection.","c":c.tolist(),"H":H,"radius":radius,"u":u,"offset":[0,0,gz-float(c[2])],"target":[float(center[0]),float(center[1]),z_at(dest["coefficients"],center)],"target_plane":np.asarray(dest["coefficients"]).tolist(),"poly":poly.tolist(),"finger_bounds": [np.min(rel,axis=0).tolist(),np.max(rel,axis=0).tolist()],"yaw_finger_radius_m":float(np.max(np.linalg.norm(rel[:,:2],axis=1))),"frame_id":r["frame_id"],"uncertainty_note":"Geometric/marking heuristic, not a calibrated confidence bound."}
            run.update({"g":g,"phase":"approach","q":s["tcp_quaternion_xyzw"]}); save(); start_track(p["patch_camera"],p["patch_polygon"],g["c"],r["frame_id"])
        g=run["g"]; offset=np.array(g["offset"]); target=np.array(g["target"])
        if run["phase"]=="approach":
            grasp=np.array(g["c"])+offset; move((grasp+[0,0,0.07]).tolist(),"open"); move(grasp.tolist(),"open",contact=True); o=sense(preclose=True)
            run["anchor"]={"c":o["c"],"u":o["u"],"hand":api.state()}; run["phase"]="closing"; save()
        if run["phase"]=="closing":
            previous=abs(api.state()["gripper_qpos_m"][0]-api.state()["gripper_qpos_m"][1]); stable=0
            for k in range(6):
                act(geo.pad_position(api.state()).tolist(),"close"); s=api.state(); width=abs(s["gripper_qpos_m"][0]-s["gripper_qpos_m"][1]); stable=stable+1 if abs(width-previous)<0.0005 else 0; previous=width
                if k>=2 and stable>=2: break
            run["phase"]="probe"; save()
        if run["phase"]=="probe":
            if "probe_target" not in run: run["probe_target"]=(geo.pad_position(api.state())+[0,0,max(0.04,2*(run["anchor"]["u"]+g["u"]+0.005)+0.01)]).tolist(); save()
            move(run["probe_target"],probe=True); o=sense(); a=run["anchor"]; hand=api.state(); dz=float(o["c"][2]-a["c"][2]); hd=float(geo.pad_position(hand)[2]-geo.pad_position(a["hand"])[2]); tol=a["u"]+o["u"]+0.003
            note({"retention_test_object_rise_m":dz,"actual_pad_rise_m":hd,"required_resolved_motion_m":2*tol})
            if dz<=2*tol or hd<=2*tol: raise RuntimeError("Lift did not independently resolve retained object motion.")
            run["retained"]=True; run["phase"]="lift"; save()
        if run["phase"]=="lift":
            pad=geo.pad_position(api.state()); z=max(float(pad[2]),float(target[2]+g["H"]+offset[2]+max(0.03,g["radius"]+g["u"])))
            run["transfer_z"]=z; save(); move([float(pad[0]),float(pad[1]),z]); run["phase"]="transfer"; save()
        if run["phase"]=="transfer":
            move([float(target[0]),float(target[1]),run["transfer_z"]]); run["phase"]="lower"; save()
        if run["phase"]=="lower":
            move((target+offset+[0,0,g["H"]+0.004]).tolist()); run["phase"]="release"; save()
        if run["phase"]=="release":
            for correction in range(2):
                pad=geo.pad_position(api.state()); o=sense((pad+[0,0,0.075]).tolist()); c=np.array(o["c"]); gap=float(c[2]-g["H"]-z_at(g["target_plane"],c[:2])); inside=margin(c[:2],g["poly"])
                note({"release_base_gap_m":gap,"release_edge_margin_m":inside,"center":o["c"]})
                if -g["u"]<=gap<=0.010 and inside>=g["radius"]+g["u"]: break
                if correction or abs(gap)>0.025: raise RuntimeError("Release relation unresolved; object kept closed.")
                run["phase"]="lower"; move((pad+np.array([target[0]-c[0],target[1]-c[1],0.004-gap])).tolist()); run["phase"]="release"; save()
            for k in range(6): act(geo.pad_position(api.state()).tolist(),"open")
            run["phase"]="released"; run["retained"]=False; save()
            pad=geo.pad_position(api.state()); act((pad+[0,0,0.075]).tolist(),"open",12)
        if run["phase"]=="released":
            observations=[]
            for k in range(2):
                r=review("Assess the ACTUAL released item, not the commanded goal. relation=supported_on_requested_target only when this same bottle base is visibly supported by the instructed rack shelf, not another surface; otherwise wrong_target_or_off or uncertain. upright describes actual bottle attitude. stability=visibly_stable requires no visible sliding/tipping, and second review must compare with the first. target_state=unchanged means the same measured stationary support remains valid. Request named point mark at the current visible cork-top center in either camera, never its old projection.",{"relation":["supported_on_requested_target","wrong_target_or_off","uncertain"],"upright":yn,"stability":["visibly_stable","moving_or_tipping","uncertain"],"target_state":["unchanged","changed","unknown"]},{"reference":g,"prior_final_observations":observations})
                p=r["parameters"]; observed=tracked() if "mark" not in r["points"] else None
                if "mark" not in r["points"] and observed is None: raise RuntimeError("Final cork landmark depth failed and registration is unavailable; no fabricated final pose.")
                c=point(r,"mark") if "mark" in r["points"] else np.array(observed["c"]); gap=float(c[2]-g["H"]-z_at(g["target_plane"],c[:2])); good=p["relation"]=="supported_on_requested_target" and p["upright"]=="yes" and p["stability"]=="visibly_stable" and p["target_state"]=="unchanged" and abs(gap)<=2*g["u"]+0.006 and margin(c[:2],g["poly"])>=g["radius"]
                observations.append({"frame_id":r["frame_id"],"center":c.tolist(),"base_gap_m":gap,"assessment":p,"good":bool(good)}); api.checkpoint("final",observations)
                if not good: raise RuntimeError("Post-release support, identity, or stability is not established.")
                if k==0:
                    for j in range(2): act(geo.pad_position(api.state()).tolist(),"open")
            drift=float(np.linalg.norm(np.array(observations[1]["center"])-observations[0]["center"])); note({"post_release_drift_m":drift,"observations":observations})
            if drift>2*g["u"]+0.004: raise RuntimeError("Post-release motion exceeds measurement allowance.")
            return {"completion_proposed":True,"evidence":{"measurements":log,"final":observations,"limitation":"Bounded visual/geometric assessment only; no collision certificate or official success claim."}}
        raise RuntimeError("Unsupported persisted phase.")
    except Exception as e:
        note({"incomplete_reason":str(e),"phase":run["phase"],"retention_last_observed":run["retained"]})
        return {"completion_proposed":False,"evidence":log}

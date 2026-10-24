def main(api):
    task = {'instruction': 'could you put the cream cheese into the bowl'}
    evidence = []; m = {'phase': 'observe', 'holding': 'none', 'reserve': 18, 'metrics': {}}; tol = 0.003
    def log(x):
        evidence.append(x); api.note(str(x))
    def need(ok, text, values=None):
        if not ok:
            log({'failure': text, 'values': values}); raise RuntimeError(text)
    def R(q):
        x,y,z,w = q
        return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
    def pad(s):
        return np.array(s['tcp_position_world_m']) + R(s['tcp_quaternion_xyzw']) @ np.array(s['own_geometry']['pad_center_in_tool_m'])
    def span(s):
        return float(np.ptp(s['gripper_qpos_m']))
    def gap(s):
        return max(0.0, 2*span(s)-float(s['own_geometry']['pad_extent_in_tool_m'][1]))
    def envelope(s, q):
        g=s['own_geometry']; lo=g['finger_low_offset_tool_m']; hi=g['finger_high_offset_tool_m']; p=np.array(g['pad_center_in_tool_m'])
        return (np.array([[x,y,z] for x in [lo[0],hi[0]] for y in [lo[1],hi[1]] for z in [lo[2],hi[2]]])-p) @ R(q).T
    def ask(text, context=None):
        need(api.state()['budgets']['gpt_remaining'] > 0, 'Observation budget unavailable')
        v=api.review(text, context); log({'review_frame':v['frame_id'], 'observation':v['explanation'][:500]})
        need(v['status'] != 'stop', 'Visual reviewer requested stop'); return v
    Q={}
    for a in ['x','y','z','rx','ry','rz']:
        subject=('translation along world '+a) if len(a)==1 else ('rotation about world '+a[1])
        Q[a]={'type':'choice','instructions':'For '+subject+', read state.processed_features.axes.'+a+'.goal_relation. Choose positive for increase, negative for decrease, and hold for within_tolerance. Do not infer a direction from images or task semantics.', 'criteria':{'negative':'The named world component must decrease.','hold':'The named component is within tolerance.','positive':'The named world component must increase.'}}
    Q['gripper']={'type':'choice','instructions':'Read state.processed_features.objective.gripper. Deliver exactly that open, close, or keep requirement; do not decide whether the object is grasped.','criteria':{'open':'The objective requests open.','close':'The objective requests close.','keep':'The objective requests keep.'}}
    def move(p, g, phase, calls=20, custom=False):
        m['phase']=phase; b=api.state()['budgets']; cap=min(calls,int(b['jev_remaining'])-m['reserve'],int(b['native_steps_remaining'])//3-m['reserve'])
        need(cap>0, 'Motion budget reserve reached', b)
        f={'phase':phase,'reference_measurements':m['metrics'],'reference_only':True}
        kw={'tool_point':'pad_center','translation_limit':0.02,'rotation_limit':0.10,'steps':3,'position_tolerance':tol,'rotation_tolerance':0.06}
        if custom:
            for k in range(cap):
                f['control_frame']=api.state()['frame_id']; r=api.control(np.asarray(p).tolist(),m['q'],g,Q,features=f,**kw)
                if r['status'] in ['reached','stalled']: break
        else:
            r=api.drive(np.asarray(p).tolist(),m['q'],g,Q,features=f,max_calls=cap,**kw)
        log({'phase':phase,'status':r['status'],'position_error_m':r['position_error_m'],'rotation_error_rad':r['rotation_error_rad']})
        if r['status'] != 'reached' and phase=='grasp_descent' and m['holding']=='none':
            s=api.state(); rr=api.control((pad(s)+[0,0,0.015]).tolist(),s['tcp_quaternion_xyzw'],'keep',Q,features={'phase':'single_reverse_retreat'},tool_point='pad_center',steps=3)
            log({'retreat_status':rr['status']})
        need(r['status']=='reached', 'Bounded motion did not converge; no repeated contact push', {'phase':phase,'status':r['status']}); return api.state()
    def grip(g):
        old=span(api.state())
        for k in range(5):
            s=api.state(); b=s['budgets']; need(b['jev_remaining']>m['reserve'] and b['native_steps_remaining']>=3, 'Insufficient gripper budget')
            r=api.control(pad(s).tolist(),s['tcp_quaternion_xyzw'],g,Q,features={'phase':'gripper_transition','holding_claim':m['holding']},tool_point='pad_center',steps=3)
            need(r['status'] in ['reached','moved'], 'Gripper transition stalled')
            new=span(api.state())
            if k>=2 and abs(new-old)<0.0008: break
            old=new
        log({'gripper_request':g,'joint_span_m':new,'estimated_inner_gap_m':gap(api.state())})
    def plane(region):
        P=np.asarray(region['world_m'],dtype=float); need(len(P)>=8,'Too few visible plane samples')
        c=np.mean(P,axis=0); _,_,v=np.linalg.svd(P-c,full_matrices=False); n=v[-1]
        if n[2]<0: n=-n
        d=-float(n@c); rms=float(np.sqrt(np.mean((P@n+d)**2)))
        need(rms<0.0035,'Visible region is not sufficiently planar',{'rms_m':rms}); return n,d,rms
    def face(v):
        reg=v['regions']['top']; n,d,err=plane(reg); camera=reg['camera']; pixels=v['parameters']['corners']
        need(len(pixels)==4,'Four genuinely visible face vertices are needed for extent measurement')
        C=np.array([api.plane_point(camera,p,[*n.tolist(),d])['world_m'] for p in pixels]); cal=api.camera(camera); K=np.array(cal['K']); W=np.array(cal['camera_to_world_opencv'])
        rays=C-W[:3,3]; ranges=np.linalg.norm(rays,axis=1); incidence=np.abs((rays/ranges[:,None])@n)
        u=float(np.max(err/np.maximum(incidence,0.1)+2*ranges/min(K[0,0],K[1,1])/np.maximum(incidence,0.1)))
        return C,max(0.001,u),n
    def bowl(v, normal):
        samples=[]; scales=[]; n=np.asarray(normal,dtype=float)
        for i in range(8):
            p=v['points'].get('rim'+str(i))
            if p is None: continue
            try:
                p=api.point(p['camera'],p['pixel'],radius=1); K=np.asarray(api.camera(p['camera'])['K'])
                samples.append(p['world_m']); scales.append(0.0005+float(p['depth_m'])/min(K[0,0],K[1,1]))
            except Exception as exc:
                log({'lip_sample_rejected':i,'reason':str(exc)})
        P=np.asarray(samples); need(len(P)>=4 and n[2]>0.98,'Insufficient upright lip-plane evidence',{'lip_samples_m':samples})
        H=P@n; band=max(0.0015,2*float(np.median(scales)))
        groups=[np.flatnonzero(np.abs(H-h)<band) for h in H]
        ids=max(groups,key=lambda a:(len(a),float(np.mean(H[a]))))
        need(len(ids)>=4,'No consistent measured lip layer',{'heights_m':H.tolist(),'layer_band_m':band})
        S=P[ids]; spread=float(np.linalg.svd(S[:,:2]-np.mean(S[:,:2],axis=0),compute_uv=False)[1]/math.sqrt(len(S)))
        need(spread>2*band,'Lip samples are too concentrated',{'spread_m':spread,'layer_band_m':band})
        d=-float(np.median(H[ids])); plane_error=max(0.0005,float(np.sqrt(np.mean((H[ids]+d)**2))))
        edge=v['parameters'].get('bowl_boundary',{}); camera=edge.get('camera'); pixels=edge.get('pixels',[])
        need(camera in ['agentview','robot0_eye_in_hand'] and 5<=len(pixels)<=12,'Need visible opening pixels distinct from lip depth samples')
        C=np.array([api.plane_point(camera,p,[*n.tolist(),d])['world_m'] for p in pixels])
        cal=api.camera(camera); K=np.asarray(cal['K']); W=np.asarray(cal['camera_to_world_opencv'])
        rays=C-W[:3,3]; ranges=np.linalg.norm(rays,axis=1); incidence=np.maximum(0.1,np.abs((rays/ranges[:,None])@n))
        pixel_error=ranges/min(K[0,0],K[1,1])/incidence
        measured_u=max(0.001,float(np.max(np.sqrt(pixel_error**2+(plane_error/incidence)**2))))
        o=np.mean(C[:,:2],axis=0); X=C[:,:2]-o
        sol=np.linalg.lstsq(np.column_stack((2*X,np.ones(len(X)))),np.sum(X*X,axis=1),rcond=None)[0]; c=o+sol[:2]
        radii=np.linalg.norm(C[:,:2]-c,axis=1); radius=float(np.mean(radii)); fit_error=float(np.std(radii))
        angles=np.sort(np.arctan2(C[:,1]-c[1],C[:,0]-c[0])); coverage=float(np.max(np.diff(np.r_[angles,angles[0]+2*math.pi])))
        metrics={'lip_depth_heights_m':H.tolist(),'accepted_lip_indices':ids.tolist(),'lip_plane_rms_m':plane_error,'opening_radii_m':radii.tolist(),'circle_rms_m':fit_error,'largest_angular_gap_rad':coverage,'boundary_measurement_uncertainty_m':measured_u,'lip_parallel_to_measured_support_model':True}
        log(metrics)
        need(coverage<math.pi and fit_error<2*measured_u and float(np.max(np.abs(radii-radius)))<3*measured_u,'Visible opening does not support this circular model',metrics)
        return c,radius,float(np.max(C[:,2])),math.sqrt(measured_u**2+fit_error**2)
    def transform(T,P):
        return P@T[:3,:3].T+T[:3,3]
    def track():
        t=api.track_update(m['handle'])
        if t['status']!='tracked': return None
        u=max(float(t['rms_m']),float(t['uncertainty_floor_m'])); spread=float(np.max(np.asarray(t['inlier_spread_m'])))
        good=t['inliers']>=12 and t['inliers']/max(1,t['matches'])>=0.45 and u<=0.005 and spread>2*u
        log({'tracking_frame':t['frame_id'],'inliers':t['inliers'],'matches':t['matches'],'uncertainty_m':u,'spread_m':spread,'accepted':bool(good)})
        return (np.array(t['transform_initial_world_to_current_world']),u) if good else None
    def attachment(A,B,s0,s1,C):
        P=transform(A,C); expected=(P-np.array(s0['tcp_position_world_m']))@R(s0['tcp_quaternion_xyzw'])@R(s1['tcp_quaternion_xyzw']).T+np.array(s1['tcp_position_world_m'])
        return float(np.max(np.linalg.norm(transform(B,C)-expected,axis=1)))
    def init_patch(v):
        need(v['frame_id']==api.state()['frame_id'],'Tracking selection is not current')
        for item in v['parameters'].get('tracking_patches',[])[:2]:
            camera=item.get('camera'); polygon=item.get('polygon',[])
            if camera not in ['agentview','robot0_eye_in_hand'] or not 3<=len(polygon)<=16: continue
            P=np.asarray(polygon,dtype=float)
            if P.shape!=(len(polygon),2) or not np.all(np.isfinite(P)) or np.any(P<0) or np.any(P>=768): continue
            info={'selection_frame':v['frame_id'],'camera':camera,'polygon_bounds_px':[np.min(P,axis=0).tolist(),np.max(P,axis=0).tolist()]}
            try:
                t=api.track_init(camera,P.tolist()); m['handle']=t['handle']; m['tracker_reference_frame']=t['frame_id']
                log({'tracker_initialized':info,'reference_features':t['reference_features']}); return True
            except Exception as exc:
                log({'tracker_initialization_failed':info,'error':str(exc),'required_depth_valid_features':12})
        return False
    face_request='Return named region top: choose a tight interior rectangle wholly on the carton printed broad top face, with explicit current camera, integer box, and stride=4. Return parameters corners: four ordered pixel vertices of that same genuinely visible face, in the top region camera. Boundary depth can mix surfaces; these pixels will be intersected with the measured interior plane. Vertices are shape samples, not persistent corner identities.'
    tracking_request='Return parameters tracking_patches: a list of at most two objects, each with camera (agentview or robot0_eye_in_hand) and polygon (3..16 current pixel vertices). Rank by usable texture coverage. Select a broad visible interior of this same carton printed face, including multiple letters and graphic details, not one tiny glyph. Exclude background, side faces and fingers. Prefer the larger unobstructed view; its camera need not match region top. A second candidate should use a genuinely different visible patch or camera. The tracker itself will measure whether at least 12 depth-valid features exist.'
    rim_request='Separate lip height samples from opening outline pixels. Return named points rim0 through rim7, as available, on genuinely visible upper ceramic lip material at the mouth height, away from fingers. At least four spatially spread top-lip samples are needed; do not substitute points down the inner wall or floor to obtain angular coverage. Separately return parameters bowl_boundary: an object with camera and pixels, containing 5..12 current pixel locations on the genuinely visible INNER edge of that upper lip, distributed over more than half the opening. Mark the visible mouth boundary as precisely as possible, not the lower wall, outer silhouette, or hidden arc. These boundary rays will be intersected with the measured lip plane, not trusted as direct boundary depth. Use an upright bowl with mouth approximately parallel to the measured tabletop; do not invent occluded perimeter points.'
    def acquire_open():
        s=api.state(); m['q']=s['tcp_quaternion_xyzw']; m['phase']='repair_observation'
        m['holding']='none' if s['last_gripper_command']=='open' else 'possible'
        need(s['last_gripper_command']=='open', 'Restart cannot assume an unladen gripper; preserve its current command', {'last_gripper_command':s['last_gripper_command'],'joint_span_m':span(s)})
        m['phase']='fresh_geometry'; m['metrics']={'restart_frame':s['frame_id'],'prior_object_coordinates_reused':False}
        for observation_attempt in range(2):
            v=ask('Interpret this runtime task and identify its source and destination. '+face_request+' '+tracking_request+' '+rim_request+' Return named region support on exposed flat tabletop immediately adjacent to the carton, with explicit camera, integer box, stride=4; named point floor at the visible bowl interior floor. Parameters supported: true only for a rigid rectangular carton resting upright directly on that support and an empty upright approximately circular open bowl. Parameters approach_clear: no visible obstruction to the elevated robot-to-carton approach and local vertical approach. Also return observation_up_clear if raising the current open hand 0.02 m, without rotation, is locally unobstructed and does not lift a trapped carton. This is visual evidence, not swept-volume certification. The previous failed circle used inner-wall depth as lip depth; make the two measurement types distinct.',{'task':task,'attempt':observation_attempt,'current_pad_world_m':pad(api.state()).tolist()})
            need(v['parameters'].get('supported') and v['parameters'].get('approach_clear'),'Unsupported geometry or visibly obstructed local approach')
            C,u,n=face(v); tn,td,tu=plane(v['regions']['support'])
            try:
                bc,br,bz,bu=bowl(v,tn); break
            except Exception as exc:
                log({'bowl_measurement_attempt':observation_attempt,'error':str(exc)})
                need(observation_attempt==0 and v['parameters'].get('observation_up_clear'),'Bowl evidence unresolved after bounded observation opportunity')
                move(pad(api.state())+[0,0,0.02],'keep','single_bowl_observation_lift',8)
        need(n[2]>0.98 and tn[2]>0.98,'Initial face/support are not approximately horizontal')
        floor=float(v['points']['floor']['world_m'][2]); need(floor<bz-bu,'Bowl interior depth unresolved',{'floor_z_m':floor,'rim_z_m':bz})
        s=api.state(); m['q']=s['tcp_quaternion_xyzw']; rg=R(m['q']); ex=np.array(s['own_geometry']['pad_extent_in_tool_m'])
        need(int(np.argmax(ex))==1 and abs(rg[2,2])>0.97,'Opening axis or downward tool geometry unsupported')
        edges=np.roll(C,-1,axis=0)-C; lengths=np.linalg.norm(edges,axis=1); j=int(np.argmin(lengths)); short=edges[j]/lengths[j]; margin=u+tu+tol
        width=float(np.ptp(C@rg[:,1])); estimated_gap=gap(s)
        if width+2*margin>estimated_gap:
            if np.dot(short,rg[:,1])<0: short=-short
            yaw=math.atan2(rg[0,1]*short[1]-rg[1,1]*short[0],np.dot(rg[:2,1],short[:2])); m['q']=api.compose(m['q'],[0,0,yaw]); rg=R(m['q'])
        width=float(np.ptp(C@rg[:,1])); log({'face_edge_lengths_m':lengths.tolist(),'grasp_width_m':width,'estimated_open_gap_m':estimated_gap,'margin_m':margin})
        need(width+2*margin<estimated_gap,'Measured opening margin is insufficient; visual gap is still required')
        reference_C=C.copy(); reference_u=u; initialized=init_patch(v)
        center=np.mean(C,axis=0); high=max(pad(s)[2],center[2]+0.09,bz+0.09)
        move([center[0],center[1],high],'open','elevated_approach',24)
        if not initialized:
            view_z=min(high,center[2]+0.11)
            need(view_z+float(np.min(envelope(api.state(),m['q'])[:,2]))>center[2]+u+tol,'Closer texture view lacks local vertical separation')
            move([center[0],center[1],view_z],'open','single_closer_texture_view',18)
            rv=ask(face_request+' '+tracking_request+' The earlier candidates failed texture initialization. This is a new closer observation, not a request to repeat the old tiny polygon. Return supported only if the same carton still rests broad-face-up on the tabletop; no grasp has been attempted.',{'task':task,'previous_texture_failures':evidence[-5:]})
            need(rv['parameters'].get('supported'),'Texture-view object/support relation changed')
            reference_C,reference_u,rn=face(rv); need(rn[2]>0.98,'Closer view does not support the horizontal face model')
            need(init_patch(rv),'Insufficient visible texture after alternate candidates and one closer view')
            C=reference_C.copy(); center=np.mean(C,axis=0)
        move([center[0],center[1],center[2]+0.055],'open','carton_hover',30)
        v=ask(face_request+' Parameters descent_clear: the actual fingers can descend on opposite sides of the carton without visible obstruction; access is local, not a claim about the later transfer. Confirm the same printed face and upright support relation with parameter supported.',{'task':task,'opening_axis_world':rg[:,1].tolist(),'estimated_gap_m':estimated_gap,'previous_face_world_m':C.tolist()})
        need(v['parameters'].get('descent_clear') and v['parameters'].get('supported'),'Local finger access unresolved')
        C,u,n=face(v); center=np.mean(C,axis=0); table_z=-(td+tn[:2]@center[:2])/tn[2]; h=float(center[2]-table_z); margin=u+tu+tol
        s=api.state(); low=float(np.min(envelope(s,m['q'])[:,2])); padhalf=float(np.abs(rg[2])@np.array(s['own_geometry']['pad_extent_in_tool_m']))/2; engage=max(u,min(h*0.2,padhalf*0.4))
        lower=max(table_z+margin-low,table_z+engage-padhalf); upper=center[2]-engage+padhalf; z=float(np.clip(center[2]-min(h/2,padhalf*0.6),lower,max(lower,upper)))
        m['metrics']={'measurement_frame':v['frame_id'],'height_from_support_m':h,'grasp_z_interval_m':[float(lower),float(upper)],'finger_low_relative_pad_m':low,'uncertainty_m':u,'bowl_center_xy_m':bc.tolist(),'bowl_radius_m':br}
        log(m['metrics']); need(h>u+tu and lower<upper and np.ptp(C@rg[:,1])+2*margin<gap(s),'No measured feasible grasp band',m['metrics'])
        height_u=u+tu
        C=reference_C.copy(); u=reference_u
        log({'rigid_geometry_reference_frame':m['tracker_reference_frame'],'reference_face_uncertainty_m':u,'grasp_geometry_frame':v['frame_id'],'height_uncertainty_m':height_u})
        move([center[0],center[1],z],'open','grasp_descent',18,True)
        check=ask('Inspect the actual carton/finger relationship, not the requested pose. Parameters straddled: pads are on opposite short side faces with no visible obstruction and the carton has not been pushed out of the grasp. Parameter patch_identity: the tracked printed interior belongs to this carton. Full perimeter visibility is not required.',{'reference_face_world_m':C.tolist(),'opening_axis_world':rg[:,1].tolist()})
        need(check['parameters'].get('straddled') and check['parameters'].get('patch_identity'),'Actual preclosure alignment unresolved')
        a=track(); need(a is not None,'Preclosure patch measurement unavailable; no closure attempted'); s0=api.state()
        need(np.linalg.norm(np.mean(transform(a[0],C),axis=0)[:2]-pad(s0)[:2])<margin+tol,'Carton shifted outside measured grasp center')
        m['holding']='possible'; grip('close'); closure=track(); log({'closure_track_available':closure is not None,'closure_is_not_grasp_proof':True})
        move(pad(api.state())+[0,0,0.032],'close','retention_test_lift',12,True); b=track()
        if b is None:
            v=ask('The patch tracker is uncertain after a short test lift. Is the same carton visibly plausibly between the fingers, with upward space for one additional 0.02 m observation lift? Return parameters plausible_hold and up_clear. Do not require its entire outline. Do not assert a grasp merely from the closed gripper.')
            need(v['parameters'].get('plausible_hold') and v['parameters'].get('up_clear'),'Retention unknown; preserve current gripper state')
            move(pad(api.state())+[0,0,0.02],'close','single_tracking_view_lift',8,True); b=track()
        need(b is not None,'Tracking unresolved after bounded observation lift'); sh=api.state(); hand_dz=float(pad(sh)[2]-pad(s0)[2]); object_dz=float(np.mean(transform(b[0],C)-transform(a[0],C),axis=0)[2]); slip=attachment(a[0],b[0],s0,sh,C); retain_tol=max(0.004,2*(a[1]+b[1]))
        log({'hand_lift_m':hand_dz,'observed_carton_lift_m':object_dz,'hand_object_discrepancy_m':slip,'retention_tolerance_m':retain_tol})
        need(hand_dz>0.02 and object_dz>0.65*hand_dz and slip<retain_tol,'Actual lift does not support retention'); m['holding']='retention_supported'
        V=np.vstack((C,C-[0,0,h])); now=transform(b[0],V); raise_by=max(0.0,bz+0.04-float(np.min(now[:,2])),bz+0.04-pad(sh)[2]-float(np.min(envelope(sh,m['q'])[:,2])))
        move(pad(sh)+[0,0,raise_by],'close','raise_for_transfer',16)
        return C,u,height_u,V,bc,br,bz,bu,floor,width,b,sh,retain_tol
    route_request='Return parameter route_obstruction_visible: true only if an external obstacle is actually visible intersecting the elevated carton/finger route toward the bowl, false if none is visible. Separately report route_visibility_complete. Occlusion by the robot is incomplete visibility, not an observed external obstruction. This is evidence for short monitored local trials, NOT a request to certify a swept volume.'
    def acquire_held():
        s=api.state(); m['q']=s['tcp_quaternion_xyzw']; m['holding']='possible'; m['phase']='held_restart_geometry'
        # Public earlier RGB-D face samples: shape reference only, never current pose.
        prior=np.array([[-0.06820358392151649,0.12291987132777935,0.9193958238780932],[-0.06773815228404978,0.1639410304972688,0.9183549545079996],[0.011068966264160318,0.16200862212322625,0.9181709313622589],[0.014741608483846202,0.12206399156042645,0.9191722869401193]])
        lengths=np.sort(np.linalg.norm(np.roll(prior,-1,axis=0)-prior,axis=1)); length=float(np.mean(lengths[2:])); old_width=float(np.mean(lengths[:2]))
        shape_u=max(0.001,float(np.ptp(lengths[2:]))/2); h=0.9193958238780932-0.9013587361451063
        v=ask('Resume the runtime task without reopening the current hand. Return supported only if this is the same rigid rectangular printed cream-cheese carton, with its broad face approximately horizontal and visibly plausibly between the closed fingers, and the intended bowl is upright and empty. This is not a retention certificate. Return named region top, a tight interior rectangle wholly on the visible printed broad face, explicit camera, integer box, stride=4. Return parameters exposed_short_end_pixels: exactly TWO current pixel corners where the exposed short end meets the two long edges of that face, in the top region camera. This is the end opposite the occluding fingers, not screen-relative persistent labels. Do not invent the two hidden corners. The program uses prior measured length, not a hidden-outline detector. Return named region support on exposed flat tabletop beside the bowl, explicit camera, integer box, stride=4; named point floor on the visible bowl interior floor. Return up_clear if a 0.02 m local upward retention-measurement motion is visibly unobstructed. '+tracking_request+' '+rim_request+' '+route_request,{'task':task,'shape_reference_only':{'long_edge_m':length,'short_edge_m':old_width,'support_derived_thickness_m':h,'opposite_long_edge_half_difference_m':shape_u},'current_pad_world_m':pad(s).tolist(),'finger_offsets_world_m':envelope(s,m['q']).tolist()})
        need(v['parameters'].get('supported') and v['parameters'].get('up_clear'),'Held restart identity or local test-lift access unresolved')
        reg=v['regions']['top']; n,d,pe=plane(reg); tn,td,tu=plane(v['regions']['support'])
        need(n[2]>0.98 and tn[2]>0.98,'Current face/support do not support the upright rectangular model')
        pixels=v['parameters'].get('exposed_short_end_pixels',[]); need(len(pixels)==2,'Need two genuinely visible exposed-end corners, not a full perimeter')
        camera=reg['camera']; E=np.array([api.plane_point(camera,p,[*n.tolist(),d])['world_m'] for p in pixels])
        cal=api.camera(camera); K=np.asarray(cal['K']); W=np.asarray(cal['camera_to_world_opencv']); rays=E-W[:3,3]; ranges=np.linalg.norm(rays,axis=1)
        incidence=np.maximum(0.1,np.abs((rays/ranges[:,None])@n)); eu=max(0.001,float(np.max(np.sqrt((2*ranges/min(K[0,0],K[1,1])/incidence)**2+(pe/incidence)**2))))
        edge=E[1]-E[0]; width=float(np.linalg.norm(edge)); u=math.sqrt(eu*eu+shape_u*shape_u); height_u=max(0.0035,shape_u+pe)
        log({'current_end_width_m':width,'prior_measured_short_edge_m':old_width,'prior_measured_long_edge_m':length,'current_endpoint_uncertainty_m':eu,'shape_uncertainty_m':shape_u,'support_derived_thickness_m':h,'thickness_uncertainty_allowance_m':height_u})
        need(width>2*eu and abs(width-old_width)<2*(eu+shape_u),'Current exposed end is inconsistent with prior rigid shape',{'current_width_m':width,'reference_width_m':old_width,'allowed_difference_m':2*(eu+shape_u)})
        along=np.cross(n,edge/width); along=along/np.linalg.norm(along); interior=np.mean(np.asarray(reg['world_m']),axis=0)-np.mean(E,axis=0)
        if float(along@interior)<0: along=-along
        need(float(along@interior)>eu,'Visible interior does not resolve the direction of the occluded end',{'inward_projection_m':float(along@interior),'uncertainty_m':eu})
        C=np.array([E[0],E[1],E[1]+length*along,E[0]+length*along]); V=np.vstack((C,C-h*n))
        bc,br,bz,bu=bowl(v,tn); floor=float(v['points']['floor']['world_m'][2]); need(floor<bz-bu,'Current bowl interior depth unresolved',{'floor_z_m':floor,'rim_z_m':bz})
        need(init_patch(v),'Fresh held-patch tracker initialization failed; no blind transfer')
        a=track(); need(a is not None,'Fresh held reference patch not measurable'); s0=api.state()
        m['metrics']={'measurement_frame':v['frame_id'],'model_source':'Current measured face plane and exposed end; prior public RGB-D rigid dimensions only','face_world_m_at_tracker_reference':C.tolist(),'bowl_center_xy_m':bc.tolist(),'bowl_radius_m':br,'extent_uncertainty_m':u,'route_visual_frame':v['frame_id']}
        m['route_observation']=v
        move(pad(s0)+[0,0,0.02],'close','fresh_retention_measurement_lift',8,True)
        b=track(); need(b is not None,'Held patch motion unknown after bounded lift; preserve closure'); sh=api.state()
        hand_dz=float(pad(sh)[2]-pad(s0)[2]); object_dz=float(np.mean(transform(b[0],C)-transform(a[0],C),axis=0)[2]); slip=attachment(a[0],b[0],s0,sh,C); retain_tol=max(0.004,2*(a[1]+b[1]))
        test={'hand_lift_m':hand_dz,'observed_carton_lift_m':object_dz,'hand_object_discrepancy_m':slip,'retention_tolerance_m':retain_tol}; log(test)
        need(hand_dz>max(0.01,3*(a[1]+b[1])) and object_dz>0.65*hand_dz and slip<retain_tol,'Fresh motion does not support retention',test); m['holding']='retention_supported'
        now=transform(b[0],V); raise_by=max(0.0,bz+0.025-float(np.min(now[:,2])),bz+0.025-pad(sh)[2]-float(np.min(envelope(sh,m['q'])[:,2])))
        if raise_by>tol: move(pad(sh)+[0,0,raise_by],'close','raise_resumed_load_for_transfer',12,True)
        return C,u,height_u,V,bc,br,bz,bu,floor,width,b,sh,retain_tol
    try:
        if api.state()['last_gripper_command']=='open':
            C,u,height_u,V,bc,br,bz,bu,floor,width,b,sh,retain_tol=acquire_open()
        else:
            C,u,height_u,V,bc,br,bz,bu,floor,width,b,sh,retain_tol=acquire_held()
        v=m.get('route_observation')
        if v is None:
            v=ask(route_request,{'destination_xy_m':bc.tolist(),'current_pad_world_m':pad(api.state()).tolist(),'rim_height_m':bz,'finger_offsets_world_m':envelope(api.state(),m['q']).tolist(),'maximum_next_lateral_trial_m':0.025})
        need(v['parameters'].get('route_obstruction_visible') is False,'Visible obstruction or missing local route evidence; holding without release',v['parameters'])
        log({'route_observation_frame':v['frame_id'],'route_visibility_complete':v['parameters'].get('route_visibility_complete'),'certified_clearance':False,'policy':'Short elevated trials with measured retention; robot occlusion alone is not an obstacle'})
        c=track(); need(c is not None,'Current transfer geometry unavailable')
        for leg in range(8):
            s=api.state(); now=transform(c[0],V); slip=attachment(b[0],c[0],sh,s,C); retain_limit=max(retain_tol,2*(b[1]+c[1]))
            need(slip<retain_limit,'Retention changed during transfer',{'leg':leg,'discrepancy_m':slip,'tolerance_m':retain_limit})
            offset=bc-np.mean(now[:,:2],axis=0); distance=float(np.linalg.norm(offset))
            if distance<=tol: break
            separation=min(float(np.min(now[:,2])),float(pad(s)[2]+np.min(envelope(s,s['tcp_quaternion_xyzw'])[:,2])))-bz
            margin=u+height_u+c[1]+bu+tol
            need(separation>margin,'Elevated local trial lacks measured rim separation',{'separation_m':separation,'margin_m':margin,'leg':leg})
            delta=offset*min(1.0,0.025/distance)
            m['metrics']['local_trial']={'leg':leg,'step_xy_m':delta.tolist(),'rim_separation_m':separation,'hand_object_discrepancy_m':slip,'tracking_frame':s['frame_id']}
            move(pad(s)+[float(delta[0]),float(delta[1]),0],'close','monitored_transfer_waypoint',8,True)
            c=track(); need(c is not None,'Transfer patch unavailable; stop held without release')
        s=api.state(); now=transform(c[0],V); slip=attachment(b[0],c[0],sh,s,C)
        need(slip<max(retain_tol,2*(b[1]+c[1])),'Object slipped at transfer endpoint',{'discrepancy_m':slip})
        endpoint_error=float(np.linalg.norm(bc-np.mean(now[:,:2],axis=0)))
        need(endpoint_error<=2*tol,'Bounded transfer waypoints exhausted',{'centering_error_m':endpoint_error,'tolerance_m':2*tol})
        now=transform(c[0],V); xy=np.mean(now[:,:2],axis=0); radius=float(np.max(np.linalg.norm(now[:,:2]-xy,axis=1)))
        pu=math.sqrt(u*u+c[1]*c[1]+bu*bu)+height_u*float(np.linalg.norm(c[0][:2,2])); available=br-radius
        log({'carton_projected_radius_m':radius,'bowl_opening_radius_m':br,'measurement_margin_m':pu,'nominal_centering_clearance_m':available,'uncertainty_adjusted_clearance_m':available-pu})
        need(available>0,'Nominal measured footprint exceeds opening; no release trial',{'opening_radius_m':br,'object_radius_m':radius,'uncertainty_m':pu})
        tol=min(tol,max(0.0005,available/2))
        clear=max(0.004,pu+tol); dz=max(bz+clear-float(np.min(now[:,2])),bz+clear-pad(s)[2]-float(np.min(envelope(s,m['q'])[:,2])))
        target=pad(s)+[bc[0]-xy[0],bc[1]-xy[1],dz]; drop=float(np.min(now[:,2])+dz-floor); need(drop<0.12,'Required release drop exceeds this method limit',{'drop_m':drop})
        move(target,'close','lower_to_release_height',20,True); c=track(); need(c is not None,'No fresh object measurement at release pose'); s=api.state(); now=transform(c[0],V)
        pu=math.sqrt(u*u+c[1]*c[1]+bu*bu)+height_u*float(np.linalg.norm(c[0][:2,2]))
        radial=float(np.max(np.linalg.norm(now[:,:2]-bc,axis=1)))
        need(attachment(b[0],c[0],sh,s,C)<max(retain_tol,2*(b[1]+c[1])) and radial<br,'Fresh nominal release alignment or retention failed',{'observed_extent_radius_m':radial,'uncertainty_m':pu,'opening_radius_m':br,'controller_tolerance_m':tol})
        finger_low_z=float(pad(s)[2]+np.min(envelope(s,s['tcp_quaternion_xyzw'])[:,2]))
        need(float(np.min(now[:,2]))>bz-pu and finger_low_z>bz-bu,'Unexpected contact-height geometry before release',{'object_low_z_m':float(np.min(now[:,2])),'finger_low_z_m':finger_low_z,'rim_z_m':bz})
        if radial+pu>=br:
            need(s['budgets']['gpt_remaining']>=3,'No reserve for uncertainty-limited release review and final verification')
            trial=ask('Assess a bounded release trial, NOT completed placement or certified clearance. The current metric footprint fits nominally but its uncertainty overlaps the lip. Return parameters placement_plausible if the same retained carton is above and approximately centered over the intended empty bowl mouth, with no visible obstructing contents, gross misalignment, or lip contact. Partial occlusion is acceptable; do not demand every corner or infer success from the closed gripper. Return false if visible evidence contradicts that relation or the source/destination identity is unresolved. The program will release only from above the lip and then assess the actual outcome.',{'task':task,'current_carton_face_world_m':transform(c[0],C).tolist(),'bowl_center_xy_m':bc.tolist(),'opening_radius_m':br,'observed_extent_radius_m':radial,'uncertainty_m':pu,'estimated_release_drop_m':drop,'actual_finger_low_z_m':finger_low_z,'rim_z_m':bz})
            need(trial['parameters'].get('placement_plausible'),'Uncertainty-limited release trial not supported by current view')
            log({'release_trial':'nominal fit with visual relation support','certified_clearance':False,'nominal_radial_margin_m':br-radial,'uncertainty_m':pu})
        need(s['budgets']['gpt_remaining']>=2 and s['budgets']['jev_remaining']>=20,'Verification reserve unavailable')
        m['reserve']=0; grip('open'); need(gap(api.state())>width+u,'Fingers have not measurably opened enough; do not drag object'); m['holding']='release_unverified'
        tol=0.003; move(pad(api.state())+[0,0,0.07],'open','post_release_new_view',16)
        ft=track()
        verify='Assess the actual carton/bowl relation. Parameters inside and free are true only if the carton rests inside this bowl, not perched on the lip or table, and has no gripper contact. A partially hidden perimeter is acceptable; distinguish visible support evidence from uncertainty.'
        marks='' if ft is not None else ' Return named points ink0, ink1, ink2 on three distinct, well-spread, noncollinear visible print details of the same carton face. Do not use silhouette corners or screen-relative identities. Return parameters ink_labels describing the exact physical letter or graphic feature for each point. If this is a subsequent review, reidentify exactly the supplied features and return same_ink_labels only if correspondence is unambiguous.'
        v=ask(verify+marks+' Return bowl_unchanged only if the bowl remains at the same table location and upright posture as before transfer. The carton may now occlude its opening, so a complete fresh rim reconstruction is not required. Historical bowl geometry is a reference, not a current detection.',{'task':task,'tracking_available':ft is not None,'reference_bowl_center_xy_m':bc.tolist(),'reference_opening_radius_m':br,'reference_rim_height_m':bz})
        fc,fr,fz,fbu=bc,br,bz,bu
        for k in range(3):
            move(pad(api.state()),'open','settling_observation_interval',1,True)
        v2=ask(verify+marks+' This follows additional physical settling steps. Return bowl_unchanged and stable_pose only if current images support unchanged bowl location and carton posture/support relative to the previous review. Historical projections are not current detections.',{'ink_labels':v['parameters'].get('ink_labels',{}),'previous_observation_frame':v['frame_id'],'previous_bowl_center_xy_m':fc.tolist()})
        if ft is not None:
            gt=track(); need(gt is not None,'Final patch pose unavailable; visual relation recorded but metric stability unresolved')
            F=transform(ft[0],V); G=transform(gt[0],V); fu=ft[1]; gu=gt[1]
            geometry_u=u+height_u*max(float(np.linalg.norm(ft[0][:2,2])),float(np.linalg.norm(gt[0][:2,2])))
            stability_source='RGB-D rigid patch, with reference geometry'
        else:
            need(bool(v['parameters'].get('ink_labels')) and v2['parameters'].get('same_ink_labels'),'Post-release feature correspondence unresolved')
            measured=[]; errors=[]
            for review in [v,v2]:
                need(all('ink'+str(i) in review['points'] for i in range(3)),'Insufficient fresh visible print landmarks')
                points=[review['points']['ink'+str(i)] for i in range(3)]; P=np.array([p['world_m'] for p in points]); scales=[]
                for p in points:
                    K=np.array(api.camera(p['camera'])['K']); scales.append(0.001+3*float(p['depth_m'])/min(K[0,0],K[1,1]))
                err=max(scales); spread=float(np.linalg.svd(P-np.mean(P,axis=0),compute_uv=False)[1])
                need(spread>2*err,'Print landmarks do not resolve posture',{'spread_m':spread,'sampling_uncertainty_m':err})
                measured.append(P); errors.append(err)
            F,G=measured; fu,gu=errors; geometry_u=0.0; stability_source='Three current corresponding print landmarks; full containment interpreted from images'
        drift=float(np.max(np.linalg.norm(G-F,axis=1))); stable_tol=max(0.003,fu+gu)
        radius=max(float(np.max(np.linalg.norm(F[:,:2]-fc,axis=1))),float(np.max(np.linalg.norm(G[:,:2]-fc,axis=1))))
        inside=bool(v['parameters'].get('inside') and v['parameters'].get('free') and v2['parameters'].get('inside') and v2['parameters'].get('free'))
        consistent=radius<fr+fbu+max(fu,gu)+geometry_u
        success=inside and consistent and bool(v['parameters'].get('bowl_unchanged') and v2['parameters'].get('bowl_unchanged') and v2['parameters'].get('stable_pose')) and drift<stable_tol
        log({'released_relation_observed':inside,'stability_source':stability_source,'post_release_drift_m':drift,'stability_tolerance_m':stable_tol,'observed_projection_radius_m':radius,'current_bowl_radius_m':fr,'projection_consistent':bool(consistent),'completion_is_proposal_only':True})
        return {'completion_proposed':bool(success),'evidence':evidence,'limitations':['Initial lower-face extent is support-derived, not a hidden underside measurement. Circular bowl and visible landmark approximations are not collision or success certification.']}
    except Exception as exc:
        log({'stopped_phase':m['phase'],'holding_claim':m['holding'],'error':str(exc),'recovery_policy':'Physical state persists. No further motion or automatic reopening.'})
        return {'completion_proposed':False,'evidence':evidence}

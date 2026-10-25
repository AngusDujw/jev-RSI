def main(api):
    keys = [x['key'] for x in api.recall()]
    D = {k: api.recall(k)['value'] for k in keys if k in ['geom','phase','patch','evidence','survey','partial']}
    M = D.get('phase', {'name':'survey','jaw':'open','tests':0}); D['phase'] = M
    Q = {}
    for axis in ['x','y','z','rx','ry','rz']:
        Q[axis] = {'type':'choice','instructions':'For world axis '+axis+', use its bound goal_relation. Select positive for increase, negative for decrease, hold for within_tolerance. Do not infer object effects.','criteria':{'negative':'This axis requires decrease.','hold':'This axis is within tolerance.','positive':'This axis requires increase.'}}
    Q['gripper'] = {'type':'choice','instructions':'Use state.processed_features.objective.gripper exactly: open, close, or keep. Pose arrival does not establish contact.','criteria':{'open':'The objective requests open.','close':'The objective requests close.','keep':'The objective requests keep.'}}
    text = {'type':'string','maxLength':240}
    pixel = {'type':'array','items':{'type':'integer','minimum':0,'maximum':767},'minItems':2,'maxItems':2}
    polygon = {'type':['array','null'],'items':pixel,'minItems':3,'maxItems':8}
    definitions = {'type':'array','items':text,'minItems':3,'maxItems':3}
    def save(k,v):
        D[k] = v; api.checkpoint(k,v)
    def note(v):
        save('evidence',(D.get('evidence',[])+[v])[-8:])
    def phase(n):
        M['name'] = n; save('phase',M)
    def need(ok,message):
        if not ok: raise RuntimeError(message)
    def ask(question,context,fields):
        need(api.state()['budgets']['gpt_remaining'] > (0 if M['name'] in ['verify','done'] else 3), 'Review reserve reached')
        r = api.review(question, context=context, fields=fields)
        if r['measurement_errors']: note({'measurement_errors':r['measurement_errors']})
        need(r['status'] != 'stop', 'Observation review requested stop: '+r['explanation'])
        return r
    def pull(r,names,defs):
        p = {n:r['points'][n] for n in names if n in r['points']}
        missing = [n for n in names if n not in p]
        save('partial',{'frame_id':r['frame_id'],'points':p,'missing':missing,'definitions':defs})
        if missing:
            z = ask('Replace only the failed named depth samples in missing, using the same physical surface or fiducial definitions. Choose an interior depth-valid pixel, not a mixed boundary. Return identity=certain only for unambiguous correspondence. Do not substitute a hidden point.',{'missing':missing,'definitions':defs,'saved_points':p},{'identity':['certain','unknown']})
            if z['parameters']['identity'] == 'certain' and z['frame_id'] == r['frame_id']:
                p.update({n:z['points'][n] for n in missing if n in z['points']})
            save('partial',{'frame_id':r['frame_id'],'points':p,'missing':[n for n in names if n not in p],'definitions':defs})
        need(all(n in p for n in names),'Missing current measurements: '+str([n for n in names if n not in p]))
        return np.array([p[n]['world_m'] for n in names],dtype=float)
    def fingers(s,q):
        o=s['own_geometry']; a=o['finger_low_offset_tool_m']; b=o['finger_high_offset_tool_m']
        v=np.array([[x,y,z] for x in [a[0],b[0]] for y in [a[1],b[1]] for z in [a[2],b[2]]])-np.array(o['pad_center_in_tool_m'])
        return v @ geo.rotation(q).T
    def move(target,q,label,calls=20,tol=None):
        g=D['geom']; tol=g['tol'] if tol is None else tol
        for lease in range(2):
            available=api.state()['budgets']['jev_remaining']-(0 if M['name']=='verify' else 16)
            need(available>0,'Control reserve reached before '+label)
            r=api.drive(np.array(target).tolist(),q,'keep',Q,features={'phase':label,'gate_is_historical':True},tool_point='pad_center',max_calls=int(min(calls,available,40)),translation_limit=0.015,rotation_limit=0.07,steps=3,position_tolerance=tol,rotation_tolerance=0.04)
            note({'motion':label,'status':r['status'],'position_error_m':r['position_error_m'],'rotation_error_rad':r['rotation_error_rad'],'frame_id':r['frame_id']})
            need(r['status']!='stalled','Stalled at '+label+'; no further pushing')
            if r['status']=='reached': return
            need(r['status']=='lease_exhausted','Unexpected drive status')
        raise RuntimeError('Bounded pose lease exhausted at '+label)
    def jaw(command):
        s=api.state(); r=api.control(geo.pad_position(s).tolist(),s['tcp_quaternion_xyzw'],command,Q,features={'phase':M['name'],'jaw_transition':command},tool_point='pad_center',translation_limit=0.002,rotation_limit=0.02,steps=3,position_tolerance=0.002,rotation_tolerance=0.04)
        note({'jaw_receipt':command,'status':r['status'],'choices':r['choices'],'frame_id':r['frame_id']})
        need(r['status'] in ['reached','moved','stalled'],'Unknown control result')
        need(r['acknowledged_steps']>0 and r['choices']['gripper']==command,'Jaw command not acknowledged')
        M['jaw']=command; M['jaw_frame']=r['frame_id']
        if command=='open' and M['name']=='release_intent': M['name']='verify'
        save('phase',M); need(r['status']!='stalled','Unexpected stalled stationary jaw transition')
    def init_patch(camera,poly,identity,mapping):
        try:
            t=api.track_init(camera,poly)
            save('patch',{'handle':t['handle'],'frame_id':t['frame_id'],'camera':camera,'polygon':poly,'identity':identity,'map':mapping,'anchors':None})
            return True
        except Exception as e:
            note({'patch_initialization':str(e)}); return False
    def registration(a,b,u):
        ac=a.mean(axis=0); bc=b.mean(axis=0); U,S,V=np.linalg.svd((a-ac).T@(b-bc)); R=V.T@U.T
        if np.linalg.det(R)<0: V[-1,:]*=-1; R=V.T@U.T
        T=np.eye(4); T[:3,:3]=R; T[:3,3]=bc-R@ac
        spread=np.linalg.svd(a-ac,compute_uv=False)
        err=float(np.max(np.linalg.norm(geo.transform(a,T)-b,axis=1)))
        need(spread[1]>4*u and err<3*u,'Ambiguous rigid correspondence: '+str({'spread':spread.tolist(),'residual_m':err,'u':u}))
        return T
    def observe(full=False):
        g=D['geom']
        for attempt in range(2):
            t=D.get('patch',{})
            if t and (not full or t['map'] is not None):
                try:
                    r=api.track_update(t['handle'])
                    if r['status']=='tracked':
                        P=np.array(r['reference_inlier_world_m']); spread=np.linalg.svd(P-P.mean(axis=0),compute_uv=False)/math.sqrt(len(P)); u=max(g['u'],r['rms_m'],r['uncertainty_floor_m'])
                        good=r['reference_frame_id']==t['frame_id'] and r['inliers']>=12 and r['inliers']/max(1,r['matches'])>=0.55 and r['rms_m']<=0.0025 and spread[1]>3*u
                        if good:
                            T=np.array(r['transform_initial_world_to_current_world'])
                            if t['map'] is not None:
                                T=T@np.array(t['map']); pts=geo.transform(np.array(g['marks']),T); v=geo.transform(np.array(g['vertices']),T); key='global'
                            else:
                                if t['anchors'] is None:
                                    i=int(np.argmax(np.linalg.norm(P-P.mean(axis=0),axis=1))); j=int(np.argmax(np.linalg.norm(P-P[i],axis=1))); k=int(np.argmax(np.linalg.norm(np.cross(P-P[i],P[j]-P[i]),axis=1)))
                                    t['anchors']=P[[i,j,k]].tolist(); save('patch',t)
                                pts=geo.transform(np.array(t['anchors']),T); v=None; key=str(t['handle'])
                            return {'key':key,'points':pts.tolist(),'vertices':None if v is None else v.tolist(),'u':float(u),'frame_id':r['frame_id'],'state':api.state()}
                    note({'tracking':r['status'],'frame_id':r['frame_id'],'reason':r.get('reason','quality rejected')})
                except Exception as e: note({'tracking_error':str(e)})
            if attempt==1: break
            r=ask('Recover current observation of the SAME item. Prefer mode=correspondences with named m0,m1,m2 at the saved physical print fiducials, never camera-relative corners. Reject ambiguous identity. If these are hidden, mode=new_patch may identify a visible textured rigid interior patch without registering it to old landmarks: return camera, polygon and a physical surface description. This supplies only a NEW LOCAL motion reference, not a global shape pose. Use unknown if neither is obtainable. A polygon may also accompany correspondences.',{'item':g['item'],'definitions':g['definitions'],'reference_world_m':g['marks'],'reference_frame_id':g['frame_id'],'full_envelope_needed_now':full,'saved_patch':t},{'mode':['correspondences','new_patch','unknown'],'camera':['agentview','robot0_eye_in_hand'],'polygon':polygon,'surface':text})
            p=r['parameters']
            if p['mode']=='correspondences':
                b=pull(r,['m0','m1','m2'],g['definitions']); T=registration(np.array(g['marks']),b,g['u'])
                if p['polygon'] is not None: init_patch(p['camera'],p['polygon'],p['surface'],T.tolist())
                return {'key':'global','points':b.tolist(),'vertices':geo.transform(np.array(g['vertices']),T).tolist(),'u':g['u'],'frame_id':r['frame_id'],'state':api.state()}
            if p['mode']!='new_patch' or p['polygon'] is None or not init_patch(p['camera'],p['polygon'],p['surface'],None): break
            if full: break
        return None
    def comparison(a,b,test=False):
        if a is None or b is None or a['key']!=b['key']: return False
        u=max(a['u'],b['u']); err=float(geo.attachment_error(a['points'],b['points'],a['state'],b['state']))
        hand=np.array(geo.pad_position(b['state']))-np.array(geo.pad_position(a['state'])); obj=np.mean(b['points'],axis=0)-np.mean(a['points'],axis=0)
        ok=err<=3*u and (not test or (hand[2]>5*u and obj[2]>max(2*u,0.4*hand[2])))
        note({'retention_test':test,'attachment_error_m':err,'hand_delta_m':hand.tolist(),'object_delta_m':obj.tolist(),'uncertainty_m':u,'consistent':bool(ok)})
        return bool(ok)
    def permit(target,label,static=False,bowl=False,local=None):
        g=D['geom']; fields={'external':['present','none_observed','unresolved_identity'],'visibility':['visible','self_occluded','unobserved'],'basis':['visible_local_geometry','consistent_measured_prior','none'],'view':['upward_2cm_supported','none']}
        if static: fields['item_prior']=['consistent','changed','unknown']
        if bowl: fields['bowl_prior']=['consistent','changed','unknown']
        question='Assess ONLY the proposed bounded local action, not the whole later route. external=present means a visible external object intersects it; unresolved_identity means a possible obstruction cannot be distinguished from the robot/item; none_observed is NOT certified clearance. visibility distinguishes visible, occlusion by the robot/held item, and genuinely unobserved space. basis must name actual visible local evidence or a still-consistent measured short-horizon prior; self-occlusion alone is not an external obstacle. view=upward_2cm_supported only if that separate small upward observation action has local geometric support. Never require hidden perimeter corners for a prospective retention lift.'
        if static: question+=' Return item_prior and one named o on a currently visible interior part of the item TOP face, if obtainable. Check whether any prior action displaced the item.'
        if bowl: question+=' Return bowl_prior and named b0,b1,b2 on separated visible locations of the SAME inner rim. These need not be old landmark identities.'
        for attempt in range(2):
            r=ask(question,{'action':label,'pad_target_world_m':np.array(target).tolist(),'geometry':g,'local_motion_reference':local,'robot':api.state()},fields); p=r['parameters']
            need(p['external']!='present','Observed external obstruction at '+label)
            valid=p['external']=='none_observed' and p['basis']!='none'
            if static:
                need(p['item_prior']!='changed','Item prior invalidated by observed displacement')
                if 'o' in r['points']:
                    x=np.array(r['points']['o']['world_m']); v=np.array(g['vertices']); C=np.array(g['top_plane']); valid=valid and abs(float(x@C[:3]+C[3]))<3*g['u'] and all(np.min(v[:,j])-3*g['u']<=x[j]<=np.max(v[:,j])+3*g['u'] for j in [0,1])
                else:
                    a=observe(False); valid=valid and a is not None and a['key']=='global' and np.max(np.linalg.norm(np.array(a['points'])-np.array(g['marks']),axis=1))<3*g['u']
            if bowl:
                need(p['bowl_prior']!='changed','Bowl prior invalidated; no release authorized')
                b=pull(r,['b0','b1','b2'],'Separated current inner-rim surface locations; not hidden extrapolations')
                residual=np.abs(np.linalg.norm(b[:,:2]-np.array(g['bowl_xy']),axis=1)-g['radius'])
                valid=valid and float(np.max(residual))<3*g['u'] and float(np.max(np.abs(b[:,2]-g['rim_z'])))<3*g['u'] and float(np.max(np.linalg.norm(b[:,:2]-b[0,:2],axis=1)))>0.5*g['radius']
                note({'bowl_prior_residual_m':residual.tolist(),'rim_z_samples':b[:,2].tolist()})
            if valid: return
            if attempt==0 and p['view']=='upward_2cm_supported' and p['external']!='present':
                s=api.state(); up=geo.pad_position(s)+np.array([0.,0.,0.02]); move(up,s['tcp_quaternion_xyzw'],'bounded observation view',8)
            else: break
        raise RuntimeError('No justified local action at '+label+'; visibility='+p['visibility']+', basis='+p['basis'])
    def envelope():
        a=observe(True)
        if a is not None: return a
        a=observe(False); need(a is not None,'No current local item reference for envelope recovery')
        s=api.state(); target=geo.pad_position(s)+np.array([0.,0.,0.022]); permit(target,'upward view for envelope recovery',local=a); move(target,s['tcp_quaternion_xyzw'],'envelope observation',8)
        b=observe(False); need(comparison(a,b,True),'Envelope-recovery motion lacks retained-load evidence')
        a=observe(True); need(a is not None,'Local retention observed, but full transported envelope is still unregistered'); return a
    def held_sample():
        a=envelope(); previous=M.get('held')
        if previous is not None and previous['key']==a['key']: need(comparison(previous,a),'Load no longer consistent with its measured retention reference')
        M['held']=a; save('phase',M); return a
    def plan_descent():
        g=D['geom']; s=api.state(); V=np.array(g['vertices']); top=V[:4]; u=g['u']; q=g['q']
        need(s['last_gripper_command']=='open' and M['jaw']=='open','Descent replan requires an acknowledged open, nonholding approach')
        fields={'item_prior':['consistent','changed','unknown'],'bowl_prior':['consistent','changed','unknown'],'wall_model':['upright_flared_within_outer_rim','unknown'],'camera':['agentview','robot0_eye_in_hand'],'outer_boundary':{'type':['array','null'],'items':pixel,'minItems':6,'maxItems':8},'view':['upward_2cm_supported','none']}
        question='Measurement-only descent replan; NO centered descent is authorized. The nearby bowl can obstruct the OUTER finger even when pads fit the package. item_prior and bowl_prior mean the same identified bodies remain consistent with their saved supported poses; changed invalidates them, unknown is insufficient. wall_model=upright_flared_within_outer_rim requires visible wall evidence for an upright bowl whose exterior does not bulge beyond its outer rim projection; otherwise unknown. Request rim_surface0 through rim_surface5 at spread depth-valid interior locations on the narrow TOP rim surface, not the bowl floor, wall, or background. Return camera and outer_boundary: six to eight cyclic pixels distributed around the genuinely VISIBLE outermost rim boundary, or null if unavailable. Code will intersect these rays with the measured rim plane; do not invent hidden boundary pixels. Request o on the current interior package TOP face. view=upward_2cm_supported only if a separate straight 20 mm upward open-hand observation move is justified by current local geometry without observed external interference; none otherwise. An infeasible old descent is a reason to replan, not to assert that this observation-only request executed it.'
        for attempt in range(2):
            r=ask(question,{'geometry':g,'robot':api.state(),'purpose':'Find a finite-overlap grasp shifted along the package away from the measured bowl exterior.'},fields); p=r['parameters']
            need(p['item_prior']!='changed' and p['bowl_prior']!='changed','Source or bowl prior changed before descent replan')
            ready=p['item_prior']=='consistent' and p['bowl_prior']=='consistent' and p['wall_model']=='upright_flared_within_outer_rim' and p['outer_boundary'] is not None
            if ready: break
            if attempt==0 and p['view']=='upward_2cm_supported':
                s=api.state(); move(geo.pad_position(s)+np.array([0.,0.,0.02]),s['tcp_quaternion_xyzw'],'descent-replan observation',8)
            else: raise RuntimeError('No measured exterior-bowl model for a revised descent; no supported remaining observation action')
        need(ready,'Exterior-bowl observation bound exhausted')
        A=pull(r,['rim_surface'+str(i) for i in range(6)]+['o'],'rim_surface0..5: spread current top-lip interior samples on the same bowl; o: current package top interior')
        C=np.array(g['top_plane']); x=A[6]
        need(abs(float(x@C[:3]+C[3]))<3*u and all(np.min(top[:,j])-3*u<=x[j]<=np.max(top[:,j])+3*u for j in [0,1]),'Current package top contradicts the supported source prior')
        pl=geo.plane(A[:6]); need(pl['coefficients'][2]>0.98,'Exterior-rim plane is not approximately horizontal')
        boundary=np.array([api.plane_point(p['camera'],px,pl['coefficients'])['world_m'] for px in p['outer_boundary']]); circle=geo.circle_xy(boundary)
        ou=float(max(u,2*pl['rms_m'],circle['max_radial_error_m'])); bc=np.array(circle['center_xy_m']); radius=float(circle['radius_m']+2*ou)
        note({'descent_obstacle_fit':{'frame_id':r['frame_id'],'center_xy_m':bc.tolist(),'radius_m':circle['radius_m'],'radial_error_m':circle['max_radial_error_m'],'rim_plane_rms_m':pl['rms_m'],'u_m':ou}})
        need(min(pl['in_plane_spread_m'])>4*ou and circle['largest_angular_gap_rad']<math.pi,'Exterior rim coverage is insufficient relative to fit uncertainty')
        need(np.linalg.norm(bc-np.array(g['bowl_xy']))<3*(ou+u) and abs(pl['center_world_m'][2]-g['rim_z'])<3*(ou+u),'Exterior observation contradicts the retained bowl pose')
        s=api.state(); R=geo.rotation(q); ext=np.array(s['own_geometry']['pad_extent_in_tool_m']); F=fingers(s,q)
        edges=[top[1]-top[0],top[3]-top[0]]; d=edges[0] if np.linalg.norm(edges[0])>np.linalg.norm(edges[1]) else edges[1]; d=d.copy(); d[2]=0.; d=d/np.linalg.norm(d)
        if float((top.mean(axis=0)[:2]-bc)@d[:2])<0: d=-d
        need(abs(float(d@R[:,1]))<0.08,'No orientation-preserving longitudinal slide compatible with the opening axis')
        h=float(np.min(top[:,2]-V[4:,2])); band=float(np.abs(R[2])@ext); vertical_overlap=0.5*min(h,band)
        zlo=max(float(np.max(V[4:,2]))+vertical_overlap-band/2,float(np.max(V[4:,2]))+2*u-float(np.min(F[:,2]))); zhi=float(np.min(top[:,2]))-vertical_overlap+band/2
        tol=float(min(g['tol'],0.4*(zhi-zlo)))
        note({'replanned_pad_z_interval_m':[zlo,zhi],'vertical_overlap_m':vertical_overlap,'position_tolerance_m':tol})
        need(vertical_overlap>2*u and tol>=0.0005,'No resolvable vertical overlap/support interval for the open fingers')
        half=float(0.5*(ext[0]*abs(d@R[:,0])+ext[2]*abs(d@R[:,2]))); skew=float(0.5*ext[1]*abs(d@R[:,1])); a=float(np.min(top@d)); b=float(np.max(top@d)); overlap=0.5*min(b-a,2*half)
        margin=u+tol+skew; lo=a+margin+overlap-half; hi=b-margin-overlap+half
        need(overlap>2*u and hi>=lo,'No finite longitudinal pad/side overlap interval')
        base=np.array(g['grasp']); c0=float(base@d); rotation_allowance=float(np.max(np.linalg.norm(F,axis=1))*0.04); guard=2*u+tol+rotation_allowance
        candidates=[float(np.clip(c0,lo,hi))]+np.linspace(lo,hi,41).tolist(); selected=None; best=-1.
        for c in sorted(candidates,key=lambda value:abs(value-c0)):
            target=base+d*(c-c0); target[2]=(zlo+zhi)/2; low=target[:2]+np.min(F[:,:2],axis=0); high=target[:2]+np.max(F[:,:2],axis=0)
            clearance=float(np.linalg.norm(np.clip(bc,low,high)-bc)-radius); best=max(best,clearance)
            if clearance>=guard:
                selected=target; break
        note({'descent_slide_interval_m':[lo,hi],'required_side_overlap_m':overlap,'best_exterior_clearance_m':best,'required_clearance_m':guard,'outer_radius_bound_m':radius})
        need(selected is not None,'No feasible shifted grasp clears the observed bowl with finite side overlap: '+str({'best_clearance_m':best,'required_m':guard,'slide_interval_m':[lo,hi]}))
        g['descent_plan']={'frame_id':r['frame_id'],'camera':p['camera'],'old_grasp_world_m':base.tolist(),'slide_world':d.tolist(),'minimum_overlap_m':float(overlap),'side_coordinate_interval_m':[float(lo),float(hi)],'bowl_outer_center_xy_m':bc.tolist(),'bowl_outer_radius_bound_m':radius,'obstacle_u_m':ou,'rotation_allowance_m':rotation_allowance,'predicted_clearance_m':clearance,'required_clearance_m':float(guard),'finger_xy_min_m':low.tolist(),'finger_xy_max_m':high.tolist(),'scope':'Vertical open-finger descent at this XY and orientation only. High relocation needs its own review. Invalidate after item/bowl interaction or inconsistent current observations; not a collision certificate.'}
        g['grasp']=selected.tolist(); g['tol']=tol; save('geom',g)
    def actual_alignment_geometry():
        g=D['geom']; need('descent_plan' in g,'No saved finite-overlap descent plan for current alignment')
        plan=g['descent_plan']; V=np.array(g['vertices']); s=api.state(); pad=geo.pad_position(s); R=geo.rotation(s['tcp_quaternion_xyzw']); ext=np.array(s['own_geometry']['pad_extent_in_tool_m']); F=fingers(s,s['tcp_quaternion_xyzw']); u=g['u']; d=np.array(plan['slide_world'])
        half=float(0.5*(ext[0]*abs(d@R[:,0])+ext[2]*abs(d@R[:,2]))); skew=float(0.5*ext[1]*abs(d@R[:,1])); c=float(pad@d)
        side_overlap=float(min(np.max(V[:4]@d)-u,c-skew+half)-max(np.min(V[:4]@d)+u,c+skew-half))
        band=float(np.abs(R[2])@ext); vertical_overlap=float(min(np.min(V[:4,2]),pad[2]+band/2)-max(np.max(V[4:,2]),pad[2]-band/2)); table_clearance=float(pad[2]+np.min(F[:,2])-np.max(V[4:,2]))
        gap=float(min(abs(s['gripper_qpos_m'][0]-s['gripper_qpos_m'][1]),ext[1]-2*max(ext[0],ext[2]))); item_axis=V@R[:,1]; center=float(pad@R[:,1]); opening_slack=float(min(np.min(item_axis)-(center-gap/2),(center+gap/2)-np.max(item_axis)))
        bc=np.array(plan['bowl_outer_center_xy_m']); low=pad[:2]+np.min(F[:,:2],axis=0); high=pad[:2]+np.max(F[:,:2],axis=0); bowl_clearance=float(np.linalg.norm(np.clip(bc,low,high)-bc)-plan['bowl_outer_radius_bound_m'])
        metrics={'actual_side_overlap_m':side_overlap,'required_side_overlap_m':plan['minimum_overlap_m'],'vertical_overlap_m':vertical_overlap,'table_clearance_m':table_clearance,'opening_slack_m':opening_slack,'bowl_clearance_m':bowl_clearance,'u_m':u,'frame_id':s['frame_id']}; note(metrics)
        need(side_overlap>=plan['minimum_overlap_m'] and vertical_overlap>2*u and table_clearance>u and opening_slack>u and bowl_clearance>2*u,'Actual alignment geometry is inadequate; no closure authorized: '+str(metrics))
    try:
        if 'geom' not in D:
            r=D.get('survey')
            if r is None or r['frame_id']!=api.state()['frame_id']:
                r=ask('Runtime request: put the cream cheese into the bowl. Identify the item and receptacle from CURRENT images. model is supported_rigid_box_and_open_bowl only if visible side/top evidence supports an upright rigid rectangular package resting on the measured table, and an open approximately circular horizontal bowl rim. Otherwise unknown. Return camera and four cyclic top-face boundary pixels corners, plus an interior textured patch polygon on the SAME item. Define three spread, physically identifiable printed fiducials m0,m1,m2; descriptions must survive view changes. Request named depth points m0,m1,m2 and top0,top1,top2 on spread interior top locations, table0,table1,table2 on spread bare support near the item, rim0 through rim5 distributed around the INNER bowl rim, floor on the visible bowl interior floor, and side on a visible package side. Do not select background at boundaries.',{}, {'item':text,'receptacle':text,'model':['supported_rigid_box_and_open_bowl','unknown'],'camera':['agentview','robot0_eye_in_hand'],'corners':{'type':'array','items':pixel,'minItems':4,'maxItems':4},'patch':polygon,'definitions':definitions})
                r={k:r[k] for k in ['parameters','points','measurement_errors','frame_id','status']}; save('survey',r)
            p=r['parameters']; need(p['model']=='supported_rigid_box_and_open_bowl','Visible geometry does not support this manipulation model')
            names=['m0','m1','m2','top0','top1','top2','table0','table1','table2','rim0','rim1','rim2','rim3','rim4','rim5','floor','side']; A=pull(r,names,p['definitions'])
            top=geo.plane(A[:6]); table=geo.plane(A[6:9]); rim=geo.plane(A[9:15]); circle=geo.circle_xy(A[9:15]); C=np.array(top['coefficients']); B=np.array(table['coefficients'])
            need(C[2]>0.98 and B[2]>0.98 and rim['coefficients'][2]>0.98 and float(C[:3]@B[:3])>0.995,'Nonhorizontal or inconsistent support/top/rim model')
            V=np.array([api.plane_point(p['camera'],px,C.tolist())['world_m'] for px in p['corners']]); bottom=V.copy(); bottom[:,2]=(-B[3]-bottom[:,:2]@B[:2])/B[2]
            u=float(max(0.001,2*top['rms_m'],2*table['rms_m'],2*rim['rms_m'],circle['max_radial_error_m'])); e0=V[1]-V[0]; e1=V[3]-V[0]; h=float(np.min(V[:,2]-bottom[:,2])); center=V.mean(axis=0)
            need(np.linalg.norm(V[0]+V[2]-V[1]-V[3])<3*u and abs(float(e0@e1))<3*u*max(np.linalg.norm(e0),np.linalg.norm(e1)) and min(top['in_plane_spread_m'])>3*u,'Top boundary or planar observability is inadequate')
            need(h>2*u and np.min(bottom[:,2])-u<A[16,2]<np.max(V[:,2])+u and circle['largest_angular_gap_rad']<math.pi and A[15,2]<rim['center_world_m'][2]-2*u,'Side/support or bowl opening evidence is inadequate')
            s=api.state(); q=s['tcp_quaternion_xyzw']; R=geo.rotation(q); ext=np.array(s['own_geometry']['pad_extent_in_tool_m']); gap=min(abs(s['gripper_qpos_m'][0]-s['gripper_qpos_m'][1]),ext[1]-2*max(ext[0],ext[2])); width=float(np.ptp(V@R[:,1]))
            need(R[2,2]<-0.95 and gap>0,'Unsupported finger attitude or opening geometry')
            if width+6*u>=gap:
                d=e0 if np.linalg.norm(e0)<np.linalg.norm(e1) else e1; d=d/np.linalg.norm(d)
                if float(d@R[:,1])<0: d=-d
                yaw=math.atan2(d[1],d[0])-math.atan2(R[1,1],R[0,1]); yaw=math.atan2(math.sin(yaw),math.cos(yaw)); q=api.compose(q,[0.,0.,yaw]); R=geo.rotation(q); width=float(np.ptp(V@R[:,1]))
            band=float(np.abs(R[2])@ext); overlap=0.5*min(h,band); lo=max(float(np.max(bottom[:,2]))+overlap-band/2,float(np.max(bottom[:,2]))+2*u-float(np.min(fingers(s,q)[:,2]))); hi=float(np.min(V[:,2]))-overlap+band/2
            tol=float(min(0.003,(gap-width-4*u)/4,overlap/4)); note({'gap_m':float(gap),'width_m':width,'height_m':h,'overlap_m':overlap,'pad_z_interval_m':[lo,hi],'uncertainty_m':u,'tolerance_m':tol})
            need(overlap>2*u and hi>=lo and tol>=0.0005,'No feasible uncertain finger overlap/support-clearance interval')
            radius=circle['radius_m']; need(max(np.linalg.norm(V[:,:2]-center[:2],axis=1))+3*u+tol<radius,'Measured package envelope does not fit the bowl opening')
            G={'item':p['item'],'receptacle':p['receptacle'],'vertices':np.vstack([V,bottom]).tolist(),'marks':A[:3].tolist(),'definitions':p['definitions'],'frame_id':r['frame_id'],'top_plane':C.tolist(),'table_plane':B.tolist(),'u':u,'tol':tol,'q':q,'grasp':[float(center[0]),float(center[1]),float((lo+hi)/2)],'bowl_xy':circle['center_xy_m'],'radius':radius,'rim_z':rim['center_world_m'][2],'bowl_floor_world_m':A[15].tolist(),'support_assumption':'Measured upright rigid package resting on table; invalid after contact except rigid shape dimensions.'}
            save('geom',G)
            if p['patch'] is not None: init_patch(p['camera'],p['patch'],p['item']+' visible printed top',np.eye(4).tolist())
            phase('approach')
        G=D['geom']; u=G['u']; q=G['q']
        if M['name']=='release_intent': phase('verify' if api.state()['last_gripper_command']=='open' else 'release')
        if M['name']=='approach':
            plan_descent(); q=G['q']
            s=api.state(); target=np.array(G['grasp']); target[2]=max(float(geo.pad_position(s)[2]),float(np.max(np.array(G['vertices'])[:,2]))-float(np.min(fingers(s,q)[:,2]))+0.025)
            permit(target,'high approach',static=True); move(target,q,'high approach',24); permit(G['grasp'],'open-finger descent beside item',static=True); move(G['grasp'],q,'grasp alignment',24); phase('align')
        if M['name']=='align':
            actual_alignment_geometry()
            r=ask('Check current local grasp alignment, not full shape registration. The grasp may be shifted along the package: geometry.descent_plan records the measured finite pad/side overlap and exterior-bowl avoidance plan, and actual proprioceptive geometry has just been checked. alignment=both_sides_flanked requires a current visual witness that open fingers flank the intended opposing package sides with usable pad-band overlap and no observed table, bowl-wall, or other interference. Positive finite overlap is sufficient; neither the entire pad band nor its center must be contained in the side. Numerical geometry alone is not contact evidence. Report blocked for observed interference, unknown when no local witness exists. support=consistent requires current partial package evidence consistent with the supported-box prior and no observed displacement. A hidden old corner is not displacement.',{'geometry':G,'robot':api.state()},{'alignment':['both_sides_flanked','blocked','unknown'],'support':['consistent','changed','unknown']})
            need(r['parameters']['alignment']=='both_sides_flanked' and r['parameters']['support']=='consistent','No current local finger/side alignment witness'); need(observe(False) is not None,'No obtainable reference for prospective retention test'); M['close_count']=0; phase('closing')
        if M['name']=='closing':
            for i in range(3-int(M.get('close_count',0))):
                jaw('close'); M['close_count']=int(M.get('close_count',0))+1; save('phase',M)
            phase('test')
        if M['name']=='test':
            passed=False; prior=M.get('test_reference')
            if prior is not None:
                a=observe(False); passed=comparison(prior,a,True)
                if passed: M['held']=a
            for trial in range(3-int(M.get('tests',0))):
                if passed: break
                a=observe(False); need(a is not None,'No current independent reference for retention trial'); s=api.state(); target=geo.pad_position(s)+np.array([0.,0.,max(0.022,7*a['u'])]); need(target[2]-geo.pad_position(s)[2]<=0.04,'Retention uncertainty too large for a bounded trial')
                permit(target,'prospective retention lift',local=a); M['test_reference']=a; M['tests']=int(M.get('tests',0))+1; save('phase',M); move(target,s['tcp_quaternion_xyzw'],'retention lift',10)
                b=observe(False); passed=comparison(a,b,True)
                if passed: M['held']=b
                elif b is not None and a['key']==b['key']: raise RuntimeError('Observed package motion does not demonstrate retention')
            need(passed,'Retention remains unknown after bounded reference recovery'); phase('held')
        if M['name']=='held':
            a=held_sample(); s=api.state(); v=np.array(a['vertices']); pad=geo.pad_position(s); low=min(float(np.min(v[:,2])-pad[2]),float(np.min(fingers(s,q)[:,2]))); target=pad.copy(); target[2]=max(pad[2],G['rim_z']+0.025+3*a['u']-low)
            permit(target,'raise retained envelope above rim',bowl=True,local=a); move(target,q,'transfer height',18); held_sample(); phase('transfer')
        if M['name']=='transfer':
            for leg in range(8):
                a=held_sample(); pad=geo.pad_position(api.state()); v=np.array(a['vertices']); delta=np.array(G['bowl_xy'])-v[:,:2].mean(axis=0); distance=float(np.linalg.norm(delta))
                if distance<=G['tol']: break
                target=pad.copy(); target[:2]+=delta*min(1.,0.055/distance); permit(target,'local horizontal transfer leg',local=a); move(target,q,'transfer leg',14)
            a=held_sample(); need(np.linalg.norm(np.array(G['bowl_xy'])-np.mean(a['vertices'],axis=0)[:2])<=2*G['tol'],'Transfer route bound exhausted'); phase('lower')
        if M['name']=='lower':
            a=held_sample(); s=api.state(); pad=geo.pad_position(s); v=np.array(a['vertices']); low=min(float(np.min(v[:,2])-pad[2]),float(np.min(fingers(s,q)[:,2]))); target=pad.copy(); target[:2]+=np.array(G['bowl_xy'])-v[:,:2].mean(axis=0); target[2]=G['rim_z']+3*a['u']+G['tol']-low
            permit(target,'lower above bowl without inserting fingers',bowl=True,local=a); move(target,q,'release height',18); held_sample(); phase('release')
        if M['name']=='release':
            a=held_sample(); v=np.array(a['vertices']); radial=float(np.max(np.linalg.norm(v[:,:2]-np.array(G['bowl_xy']),axis=1))); bottom=float(np.min(v[:,2])); s=api.state(); finger_low=float(geo.pad_position(s)[2]+np.min(fingers(s,q)[:,2]))
            note({'release_radial_extent_m':radial,'inner_radius_m':G['radius'],'item_bottom_m':bottom,'finger_bottom_m':finger_low,'rim_m':G['rim_z'],'u':a['u']})
            need(radial+3*a['u']<G['radius'] and min(bottom,finger_low)>G['rim_z']+a['u'] and bottom-G['rim_z']<max(0.04,0.5*G['radius']),'Actual release envelope is not acceptable')
            permit(geo.pad_position(s),'open jaws over measured bowl',bowl=True,local=a); phase('release_intent'); jaw('open'); phase('verify')
        if M['name']=='verify':
            jaw('open'); jaw('open'); s=api.state(); target=geo.pad_position(s)+np.array([0.,0.,0.065]); permit(target,'open-gripper post-release observation retreat'); move(target,s['tcp_quaternion_xyzw'],'post-release new view',16)
            previous=None; defs=None; final=[]
            for observation in range(2):
                r=ask('Assess the ACTUAL item/bowl relation after release. relation=inside_supported means the package is visibly inside the bowl, supported by its interior, not bridging or resting on the rim, and separated from the gripper. rim_or_outside and still_held are failures; unknown is not success. Request f0,f1,f2 at three spread visible physical package fiducials, with persistent definitions; on the second observation measure EXACTLY the saved physical fiducials and set correspondence=certain only if identifiable. Request rim0 through rim5 on the current inner bowl rim. These are current depth measurements, not old projections.',{'item':G['item'],'receptacle':G['receptacle'],'saved_fiducial_definitions':defs,'previous':previous},{'relation':['inside_supported','rim_or_outside','still_held','unknown'],'correspondence':['certain','unknown'],'definitions':definitions})
                p=r['parameters']; need(p['relation']=='inside_supported' and p['correspondence']=='certain','Final relation or physical correspondence unresolved: '+p['relation']); A=pull(r,['f0','f1','f2','rim0','rim1','rim2','rim3','rim4','rim5'],defs if defs is not None else p['definitions']); c=geo.circle_xy(A[3:]); pl=geo.plane(A[3:]); fu=max(u,2*c['max_radial_error_m'],2*pl['rms_m']); rz=pl['center_world_m'][2]
                measured=bool(c['largest_angular_gap_rad']<math.pi and pl['coefficients'][2]>0.98 and np.max(np.linalg.norm(A[:3,:2]-np.array(c['center_xy_m']),axis=1))+fu<c['radius_m'] and np.min(A[:3,2])<rz-2*fu)
                need(measured,'Measured final samples do not corroborate interior placement: '+str({'points':A[:3].tolist(),'rim_z':rz,'radius':c['radius_m'],'u':fu}))
                now={'points':A[:3].tolist(),'bowl_xy':c['center_xy_m'],'rim_z':rz,'u':float(fu),'frame_id':r['frame_id'],'native_steps':api.state()['native_steps']}; final.append(now)
                if previous is not None:
                    drift=float(np.max(np.linalg.norm(A[:3]-np.array(previous['points']),axis=1))); bowl_drift=float(np.linalg.norm(np.array(now['bowl_xy'])-np.array(previous['bowl_xy'])))
                    need(now['native_steps']-previous['native_steps']>=6 and drift<=3*max(fu,previous['u']) and bowl_drift<=3*max(fu,previous['u']) and abs(rz-previous['rim_z'])<=3*max(fu,previous['u']),'Placement not measurably stable: '+str({'item_drift_m':drift,'bowl_drift_m':bowl_drift}))
                    note({'final_relation':'inside_supported_and_separated','stability_displacement_m':drift,'observations':final,'uncertainty_is_heuristic':True}); phase('done')
                    return {'completion_proposed':True,'evidence':D['evidence'],'limitations':['Completion is a measured proposal, not native evaluator success.','RGB-D and registration uncertainty thresholds are heuristic, not collision certificates.']}
                previous=now; defs=p['definitions']; save('partial',{'final_reference':previous,'definitions':defs}); jaw('open'); jaw('open')
        if M['name']=='done':
            phase('verify'); return {'completion_proposed':False,'evidence':{'reason':'Historical completion retained; a repaired execution must obtain fresh final verification.','history':D.get('evidence',[])}}
        return {'completion_proposed':False,'evidence':{'phase':M['name'],'reason':'No authorized next phase','history':D.get('evidence',[])}}
    except Exception as e:
        return {'completion_proposed':False,'evidence':{'phase':M['name'],'reason':str(e),'history':D.get('evidence',[]),'jaw_history':M.get('jaw','unknown'),'physical_state_not_reset':True}}

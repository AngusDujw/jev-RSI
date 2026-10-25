def main(api):
    Q = {}
    for axis in ['x','y','z','rx','ry','rz']:
        Q[axis] = {'type':'choice','instructions':'For world axis '+axis+', use its compiled goal_relation. Increase means positive; decrease means negative; within_tolerance means hold. Do not infer object contact.','criteria':{'negative':'This axis needs decrease.','hold':'This axis is within tolerance.','positive':'This axis needs increase.'}}
    Q['gripper'] = {'type':'choice','instructions':'Follow the objective gripper request exactly; keep preserves the last command. A command is not evidence of retention.','criteria':{'open':'The objective requests open.','close':'The objective requests close.','keep':'The objective requests keep.'}}
    def array(item,n,m=None):
        return {'type':'array','items':{'type':item} if isinstance(item,str) else item,'minItems':n,'maxItems':n if m is None else m}
    pixel = array({'type':'integer','minimum':0,'maximum':767},2)
    C = {'phase':'new','holding':'no','events':[]}; M = {}
    def log(kind,data):
        if isinstance(data,str): data=data[:1200]
        if kind=='measurement_errors': data=[{'name':str(e['name'])[:64],'error':str(e['error'])[:240]} for e in data[:4]]
        C['events'] = (C['events']+[{'kind':kind,'data':data}])[-8:]
        api.checkpoint('run',C)
    def phase(p):
        C['phase']=p; api.checkpoint('run',C)
    def review(question,fields,context=None):
        combined=C.get('compact',False) and question.startswith('Registration is unknown.')
        if combined:
            if api.state()['budgets']['gpt_remaining']<2: raise RuntimeError('Registration recovery would consume the reserved final observation')
            fields=dict(fields); fields.update({'obstruction':['external_obstacle','none_observed','unknown'],'visibility':['observed','partial','self_occluded','unknown'],'local_step':['supported','unsupported','unknown'],'world_prior':['consistent','contradicted','unobservable'],'load':['consistent','slipped_or_disturbed','unknown'],'camera':['agentview','robot0_eye_in_hand'],'polygon':{'type':['array','null'],'items':pixel,'minItems':3,'maxItems':16}})
            context=dict(context); context.update({'stationary_geometry':M['plan']['world'],'current_pad':pad(api.state()).tolist(),'historical_shape_not_detection':M['ref']['shape'],'ascent_ceiling':api.recall('economy')['value'].get('lift_ceiling'),'own_finger_offsets':finger_offsets(api.state()).tolist()})
            question+=' Also assess the remaining local actions: straight ascent no higher than ascent_ceiling, above-rim centering of this carton over the measured bowl, opening ONLY if independent retention and numerical envelope/rim gates later pass, and 45 mm upward retreat. local_step supported requires observed partial local geometry sufficient for these bounded actions, not complete corridor visibility. obstruction external_obstacle means visible external intersection; none_observed is not certified clearance. visibility observed/partial/self_occluded/unknown separates external uncertainty from robot or carton occlusion. world_prior consistent means current partial bowl/table evidence agrees with the saved geometry; camera change is not object motion. load consistent means the identified rigid carton has no observed slip or deformation, not that attachment has already been proved. Otherwise use the declared negative or unknown outcomes. Return camera and a currently visible textured interior polygon on this SAME carton, or null. Prefer a different usable surface if the old patch is occluded. Historical points and shape are hypotheses, not detections; do not redefine a,b,c to new features.'
        r=api.review(question,context=context,fields=fields)
        if r['measurement_errors']: log('measurement_errors',r['measurement_errors'])
        if r['status']=='stop': raise RuntimeError('Observation review stopped: '+r['explanation'])
        if combined:
            C['route_cache']={'parameters':{n:r['parameters'][n] for n in ['obstruction','visibility','local_step','world_prior','load']},'frame_id':r['frame_id'],'native_steps':api.state()['native_steps'],'scope':'Reviewed remaining bounded ascent, centering, gated release and retreat; historical, not current sensing'}
            api.checkpoint('run',C)
        return r
    def points(r,names,minimum):
        bad=[e['name'] for e in r['measurement_errors']]
        valid=[n for n in names if n in r['points'] and n not in bad]
        if len(valid)<minimum: raise RuntimeError('Missing measured points: '+str([n for n in names if n not in valid]))
        return np.array([r['points'][n]['world_m'] for n in valid],dtype=float)
    def pad(s): return np.array(geo.pad_position(s),dtype=float)
    def finger_offsets(s,q=None):
        g=s['own_geometry']; lo=g['finger_low_offset_tool_m']; hi=g['finger_high_offset_tool_m']; o=np.array(g['pad_center_in_tool_m'])
        v=np.array([[x,y,z] for x in [lo[0],hi[0]] for y in [lo[1],hi[1]] for z in [lo[2],hi[2]]])-o
        return v @ np.array(geo.rotation(s['tcp_quaternion_xyzw'] if q is None else q)).T
    def face():
        fields={'identity':['requested_item','ambiguous','unavailable'],'rectangle':['supported','unsupported','unknown'],'camera':['agentview','robot0_eye_in_hand'],'corners':{'type':['array','null'],'items':pixel,'minItems':4,'maxItems':4}}
        r=review('Measure only the requested carton top face. Return identity and rectangle: supported means a rigid planar rectangular carton face, not an inferred hidden outline. Give camera and corners as four currently visible cyclic boundary pixels, or null. Request t0,t1,t2,t3 well inside that same face, spread across it, avoiding mixed boundary depth. A subsequent call replaces failed samples, not hidden corners.',fields,{'request':'could you put the cream cheese into the bowl','phase':C['phase']})
        p=r['parameters']
        if p['identity']!='requested_item' or p['rectangle']!='supported' or p['corners'] is None: raise RuntimeError('Current full-envelope face is not identifiable')
        fit=geo.plane(points(r,['t0','t1','t2','t3'],3)); u=max(0.0015,2*float(fit['rms_m']))
        if fit['rms_m']>0.003 or min(fit['in_plane_spread_m'])<3*u: raise RuntimeError('Face fit lacks spread or planarity: '+str(fit))
        c=np.array([api.plane_point(p['camera'],v,fit['coefficients'])['world_m'] for v in p['corners']])
        e=np.roll(c,-1,axis=0)-c; lengths=np.linalg.norm(e,axis=1)
        if min(lengths)<=4*u or abs(float(np.dot(e[0],e[1])))>0.12*lengths[0]*lengths[1] or max(abs(lengths[0]-lengths[2]),abs(lengths[1]-lengths[3]))>4*u: raise RuntimeError('Visible rectangle model inconsistent: '+str(lengths.tolist()))
        return c,fit,u
    def new_reference(shape=None):
        flds={'identity':['requested_item','ambiguous','unavailable'],'definitions':array({'type':'string','maxLength':300},3),'camera':['agentview','robot0_eye_in_hand'],'polygon':{'type':['array','null'],'items':pixel,'minItems':3,'maxItems':16}}
        failure=None
        for attempt in range(2):
            r=review('Identify a currently visible rigid textured surface on the requested carton. Give camera and an interior textured polygon, or null. Independently request a,b,c on identifiable physical print features and define their exact identities in definitions, never screen-relative corners. Prefer separated features, but narrow landmark spread does not forbid a local motion test or tracker initialization. Missing depth samples may remain missing. No registration to old corners is needed. Exclude hand and background. If the preceding selection failed, select a different usable interior patch in either camera rather than repeat it.',flds,{'item':M['plan']['item'],'previous_reference':M.get('ref',{}).get('definitions',[]),'previous_failure':failure})
            p=r['parameters']
            if p['identity']!='requested_item': raise RuntimeError('Replacement surface identity ambiguous')
            bad=[e['name'] for e in r['measurement_errors']]; valid=[n for n in ['a','b','c'] if n in r['points'] and n not in bad]
            a=np.array([r['points'][n]['world_m'] for n in valid],dtype=float) if len(valid)==3 else np.empty((0,3))
            spread=float(np.linalg.svd(a-a.mean(axis=0),compute_uv=False)[1]/math.sqrt(3)) if len(a)==3 else None
            f={'marks':a.tolist(),'definitions':p['definitions'],'camera':p['camera'],'polygon':p['polygon'],'frame':r['frame_id'],'handle':None,'shape':None if shape is None else shape.tolist(),'shape_u':M['plan']['u'] if shape is not None else 0.0,'semantic_spread_m':spread}
            api.checkpoint('reference_candidate',f)
            if p['polygon'] is not None:
                try:
                    receipt=api.track_init(p['camera'],p['polygon']); f['handle']=receipt['handle']; f['creation']=receipt
                    api.checkpoint('reference_candidate',f)
                except Exception as e: failure={'tracker_error':str(e)[:600],'camera':p['camera'],'polygon':p['polygon']}; log('tracker_initialization',str(e))
            if f['handle'] is not None or len(a)==3:
                M['ref']=f; api.checkpoint('reference',f)
                log('reference_ready',{'measured_semantic_points':len(a),'semantic_spread_m':spread,'handle':f['handle'],'scope':'Local motion reference; envelope rotation has a separate gate.'})
                return f
            failure={'previous_selection':failure,'missing_points':[n for n in ['a','b','c'] if n not in valid],'reason':'Neither tracker nor corresponding measured landmarks obtained'}
        raise RuntimeError('No identified measurable local reference after two selections: '+str(failure))
    def sample(f,recover=True,need_pose=False):
        if f['handle'] is not None:
            try: t=api.track_update(f['handle'])
            except Exception as e: log('tracker_update_failure',str(e)); t={'status':'unknown'}
            if t['status']=='tracked':
                u=max(0.0015,float(t['rms_m']),float(t['uncertainty_floor_m'])); spread=np.sort(np.array(t['inlier_spread_m']).reshape(-1))
                if t['inliers']>=8 and t['inliers']/max(1,t['matches'])>=0.5 and t['rms_m']<=0.003 and u<=0.004 and len(spread)>0 and spread[max(0,len(spread)-2)]>2*u:
                    probes=np.array(f['marks'] if len(f['marks'])==3 else f.get('track_probes',[]))
                    if len(probes)<3:
                        ref=np.array(t['reference_inlier_world_m'])
                        if len(ref)>=3:
                            probes=ref[[0,len(ref)//2,len(ref)-1]]; f['track_probes']=probes.tolist()
                            api.checkpoint('reference' if f is M.get('ref') else 'original',f)
                    if len(probes)>=3:
                        T=np.array(t['transform_initial_world_to_current_world'])
                        return {'points':geo.transform(probes,T).tolist(),'T':T.tolist(),'u':u,'frame':t['frame_id'],'source':'RGBD_patch'}
        if len(f['marks'])!=3: return None
        if api.state()['frame_id']==f['frame']:
            return {'points':f['marks'],'T':np.eye(4).tolist(),'u':0.0025,'frame':f['frame'],'source':'measured_reference_at_identical_physical_frame'}
        if not recover: return None
        r=review('Registration is unknown. Request current a,b,c at exactly the saved physical features. Definitions and historical world points are references, not detections. correspondence is exact only if all three physical identities are unambiguous; otherwise ambiguous or unavailable. Direct point motion can be measured without fitting a full object pose.',{'correspondence':['exact','ambiguous','unavailable']},{'definitions':f['definitions'],'reference_world_m':f['marks'],'reference_frame':f['frame'],'item':M['plan']['item']})
        if r['parameters']['correspondence']!='exact': return None
        try: b=points(r,['a','b','c'],3)
        except Exception: return None
        a=np.array(f['marks']); u=0.0025
        rigidity=float(np.max(abs(np.linalg.norm(a[:,None,:]-a[None,:,:],axis=2)-np.linalg.norm(b[:,None,:]-b[None,:,:],axis=2))))
        if rigidity>4*u: log('semantic_rigidity_gap',{'pair_distance_error_m':rigidity,'tolerance_m':4*u}); return None
        if not need_pose: return {'points':b.tolist(),'T':None,'u':u,'frame':r['frame_id'],'source':'direct_semantic_RGBD_motion'}
        ac=a.mean(axis=0); bc=b.mean(axis=0); U,d,V=np.linalg.svd((a-ac).T@(b-bc)); R=V.T@U.T
        if np.linalg.det(R)<0: V[-1]*=-1; R=V.T@U.T
        T=np.eye(4); T[:3,:3]=R; T[:3,3]=bc-R@ac; residual=float(np.max(np.linalg.norm(geo.transform(a,T)-b,axis=1)))
        spread=float(min(np.linalg.svd(a-ac,compute_uv=False)[1],np.linalg.svd(b-bc,compute_uv=False)[1])/math.sqrt(3))
        if spread<=3*u or residual>0.0035:
            log('semantic_pose_unresolved',{'spread_m':spread,'required_spread_m':3*u,'rigid_residual_m':residual,'scope':'Envelope transform only; raw motion points remain usable'})
            return None
        if C.get('compact',False) and r['parameters'].get('polygon') is not None and r['parameters'].get('load')=='consistent':
            try:
                receipt=api.track_init(r['parameters']['camera'],r['parameters']['polygon'])
                api.checkpoint('reference_candidate',dict(f))
                if f['shape'] is not None: f['shape']=geo.transform(np.array(f['shape']),T).tolist()
                f.update({'marks':b.tolist(),'frame':r['frame_id'],'camera':r['parameters']['camera'],'polygon':r['parameters']['polygon'],'handle':receipt['handle'],'creation':receipt,'shape_u':max(f.get('shape_u',0.0),u)})
                api.checkpoint('reference',f); T=np.eye(4)
                log('semantic_reference_rebased',{'frame':r['frame_id'],'handle':receipt['handle'],'rigid_residual_m':residual,'spread_m':spread})
            except Exception as e: log('replacement_patch_unavailable',str(e))
        return {'points':b.tolist(),'T':T.tolist(),'u':u,'frame':r['frame_id'],'source':'semantic_RGBD_rigid_pose'}
    def envelope():
        f=M['ref']; v=sample(f,need_pose=True)
        if v is not None and f['shape'] is not None:
            return geo.transform(np.array(f['shape']),np.array(v['T'])),max(v['u'],M['plan']['u'],f.get('shape_u',0.0))
        old=M.get('original')
        if old is not None and old['shape'] is not None and (old['handle']!=f['handle'] or old['frame']!=f['frame']):
            ov=sample(old,False,True)
            if ov is not None:
                M['ref']=old; api.checkpoint('reference',old)
                return geo.transform(np.array(old['shape']),np.array(ov['T'])),max(ov['u'],M['plan']['u'],old.get('shape_u',0.0))
        c,fit,u=face(); dims=sorted(np.linalg.norm(np.roll(c,-1,axis=0)-c,axis=1).tolist())
        if max(abs(np.array(dims)-np.array(M['plan']['dimensions'])))>4*max(u,M['plan']['u']): raise RuntimeError('Recovered envelope does not match the measured carton')
        if v is not None:
            f['shape']=geo.transform(c,np.linalg.inv(np.array(v['T']))).tolist(); f['shape_u']=u; api.checkpoint('reference',f)
        elif api.state()['frame_id']==f['frame']:
            f['shape']=c.tolist(); f['shape_u']=u; api.checkpoint('reference',f)
        return c,u
    def grasp_site(c,u):
        P=M['plan']; W=P['world']; s=api.state(); g=s['own_geometry']; R=np.array(geo.rotation(P['quaternion']))
        if C['holding']!='no' or s['last_gripper_command']!='open': raise RuntimeError('Offset approach requires an unheld item and acknowledged open jaws')
        normal=np.array(geo.plane(c)['coefficients'][:3]); edges=np.roll(c,-1,axis=0)-c; lengths=np.linalg.norm(edges,axis=1); edge=edges[int(np.argmax(lengths))]
        if normal[2]<0.98 or abs(float(np.dot(edge/np.linalg.norm(edge),R[:,0])))<0.97: raise RuntimeError('Offset side-band model lacks a horizontal face and aligned long edge')
        body=np.concatenate([c,c-P['height']*normal]); uv=body@R[:,:2]; lo=uv.min(axis=0); hi=uv.max(axis=0)
        band=float(g['pad_extent_in_tool_m'][0]); gap=float(2*abs(s['gripper_qpos_m'][0]-s['gripper_qpos_m'][1])-g['pad_extent_in_tool_m'][1])
        offsets=finger_offsets(s,P['quaternion']); rot_allow=0.03*float(max(np.linalg.norm(offsets,axis=1)))
        margin=float(u+P.get('grasp_tolerance',0.001)+rot_allow); overlap=min(0.8*band,0.5*max(0.0,float(hi[0]-lo[0])-2*margin))
        lower=np.array([lo[0]+margin+overlap-band/2,hi[1]-gap/2+margin]); upper=np.array([hi[0]-margin-overlap+band/2,lo[1]+gap/2-margin])
        diagnostics={'frame':s['frame_id'],'aperture_m':gap,'band_width_m':band,'desired_overlap_m':overlap,'margin_m':margin,'tool_coordinate_intervals_m':[lower.tolist(),upper.tolist()]}
        if overlap<=2*u or np.any(lower>upper):
            log('offset_grasp_search',diagnostics); raise RuntimeError('No measured offset-grasp aperture/contact interval; see offset_grasp_search')
        A=R[:2,:2].T
        if abs(float(np.linalg.det(A)))<0.8: raise RuntimeError('Horizontal offset search is ill conditioned for this tool orientation')
        center=c.mean(axis=0); bc=np.array(W['bowl_center']); z=float(P['grasp_z']); rim_u=W.get('rim_uncertainty_m',P['u'])
        required=float(W['bowl_radius']+3*(u+rim_u)+P.get('position_tolerance',0.001)+rot_allow)
        best=None; best_cost=None; maximum_separation=0.0
        for i in range(17):
            for j in range(17):
                a=lower+(upper-lower)*np.array([i/16.0,j/16.0]); xy=np.linalg.solve(A,a-z*R[2,:2])
                footprint=offsets[:,:2]+xy; fmin=footprint.min(axis=0); fmax=footprint.max(axis=0)
                distance=np.maximum(np.maximum(fmin-bc,bc-fmax),0.0); separation=float(np.linalg.norm(distance)); maximum_separation=max(maximum_separation,separation)
                cost=float(np.sum((xy-center[:2])**2)+3*(a[1]-float(center@R[:,1]))**2)
                if separation>=required and (best_cost is None or cost<best_cost):
                    best_cost=cost; best={'xy_world_m':xy.tolist(),'pad_z_m':z,'bowl_proxy_separation_m':separation,'side_band_overlap_m':float(min(a[0]+band/2,hi[0])-max(a[0]-band/2,lo[0])),'aperture_edge_margin_m':float(gap/2-max(abs(uv[:,1]-a[1]))),'finger_xy_bounds_m':[fmin.tolist(),fmax.tolist()]}
        diagnostics['required_proxy_separation_m']=required; diagnostics['maximum_candidate_separation_m']=maximum_separation
        if best is None:
            log('offset_grasp_search',diagnostics); raise RuntimeError('No candidate offset site passes the conservative bowl exclusion proxy; another approach model is needed')
        best['reference_frame']=s['frame_id']; best['uncertainty_m']=u; best['required_proxy_separation_m']=required
        best['scope']='Geometric proposal only. Inner rim is not the outer shell; fresh local review must check actual external obstruction.'
        C['grasp_candidate']=best; diagnostics['selected']=best; log('offset_grasp_search',diagnostics)
        return np.array(best['xy_world_m'])
    def pose_tolerance():
        p=M['plan']
        return float(p.get('grasp_tolerance',0.001) if C['phase']=='descend' else p.get('position_tolerance',0.001))
    def motor(target,grip,features,calls=18):
        s=api.state(); b=s['budgets']; reserve=0 if C['phase'] in ['releasing','verify'] else 15
        if b['jev_remaining']<calls+reserve or b['native_steps_remaining']<3*calls+3*reserve: raise RuntimeError('Reserved control budget reached')
        C['intent']={'target_pad':target.tolist(),'gripper':grip,'frame':s['frame_id']}; api.checkpoint('run',C)
        r=api.drive(target.tolist(),M['plan']['quaternion'],grip,Q,features=features,tool_point='pad_center',max_calls=calls,translation_limit=0.02,rotation_limit=0.07,steps=3,position_tolerance=pose_tolerance(),rotation_tolerance=0.03)
        log('motion_receipt',{'status':r['status'],'frame':r['frame_id'],'position_error_m':r['position_error_m'],'lease_calls':r['lease_calls']})
        if r['status']=='stalled': raise RuntimeError('Stalled; do not push contact or assume world priors remain valid')
        if r['status'] not in ['reached','lease_exhausted','moved']: raise RuntimeError('Unexpected motion failure')
        return r
    def move(goal,grip,purpose,held=False):
        probe=held and C['holding']=='possible'; recoveries=0; views=0
        for leg in range(20):
            s=api.state(); start=pad(s); delta=goal-start; dist=float(np.linalg.norm(delta))
            if dist<=max(pose_tolerance(),0.0015 if C['phase']=='descend' else 0.0) and not probe: return
            reserve=2 if C['phase']=='verify' else (4 if C['phase'] in ['approach','descend'] else 3)
            if s['budgets']['gpt_remaining']<=reserve: raise RuntimeError('Reserved observation budget reached at '+purpose)
            before=None
            if held:
                before=sample(M['ref'])
                if before is None:
                    if recoveries>=2: raise RuntimeError('No usable retention reference after bounded recovery')
                    new_reference(); before=sample(M['ref']); recoveries+=1; probe=True
                if before is None: raise RuntimeError('Neither tracker nor identifiable points can observe a prospective test')
            leg_limit=0.05 if held else 0.07
            step=np.array([0.0,0.0,0.025]) if probe else delta*min(1.0,leg_limit/max(dist,0.000001))
            flds={'obstruction':['external_obstacle','none_observed','unknown'],'visibility':['observed','partial','self_occluded','unknown'],'local_step':['supported','unsupported','unknown'],'world_prior':['consistent','contradicted','unobservable'],'item':['consistent','slipped_or_disturbed','occluded','unknown'],'up_view':['supported','unsupported','unknown']}
            r=review('Assess ONLY this bounded local leg. obstruction external_obstacle means a visible external object intersects the proposed motion; none_observed is not certified clearance. visibility distinguishes unobserved space from robot/item self-occlusion. local_step supported requires visible local free space or consistent measured local geometry justifying bounded progress, including a prospective retention lift; it does not require the entire future route. world_prior refers only to the stationary bowl/table, not the manipulated carton; camera change is not motion. item slipped_or_disturbed requires observed uncommanded slip or disturbance, not commanded rigid transport or expected settling after release. up_view supported means a separate 25 mm world-up observation move is locally justified. Do not call self-occlusion an external obstacle. An offset grasp intentionally need not center the pad on the carton centroid. Check the actual finger corridor and side-band overlap. grasp_candidate is a numerical proposal, not a clearance certificate: its bowl circle is the INNER rim, so reject any visible OUTER rim or wall intersection as well.',flds,{'purpose':purpose,'start_pad':start.tolist(),'proposed_end_pad':(start+step).tolist(),'stationary_geometry':M['plan']['world'],'prior_last_consistent_step':C['world_step'],'holding_claim':C['holding'],'own_finger_offsets':finger_offsets(s).tolist(),'grasp_candidate':C.get('grasp_candidate'),'desired_orientation_xyzw':M['plan']['quaternion']})
            p=r['parameters']
            if p['obstruction']=='external_obstacle' or (C['phase']!='verify' and p['item']=='slipped_or_disturbed'): raise RuntimeError('Observed external obstruction or disturbed load at '+purpose)
            if C['phase']!='verify':
                if p['world_prior']=='contradicted': raise RuntimeError('Stationary support/container prior invalidated')
                if p['world_prior']=='consistent': C['world_step']=s['native_steps']
                elif s['native_steps']-C['world_step']>45: raise RuntimeError('Stationary world prior expired without partial consistency evidence')
            if p['obstruction']=='unknown' or p['local_step']!='supported':
                if views>=1 or p['up_view']!='supported': raise RuntimeError('No justified local progress or obtainable view at '+purpose)
                step=np.array([0.0,0.0,0.025]); views+=1
            elif p['visibility']=='unknown' and np.linalg.norm(step)>0.025: step=step*(0.025/np.linalg.norm(step))
            if held: api.checkpoint('baseline',{'sample':before,'state':s,'reference_frame':M['ref']['frame'],'purpose':purpose})
            motor(start+step,grip,{'purpose':purpose,'local_observation':p,'test':probe})
            afterstate=api.state(); hand=float(np.linalg.norm(pad(afterstate)-start))
            if hand<0.001 and dist>0.003: raise RuntimeError('Lease made no measurable progress')
            if held:
                after=sample(M['ref'])
                if after is None:
                    if recoveries>=2: raise RuntimeError('Post-motion registration and correspondence remain unknown; retention unresolved')
                    C['holding']='possible'; new_reference(); recoveries+=1; probe=True; continue
                err=float(geo.attachment_error(np.array(before['points']),np.array(after['points']),s,afterstate)); obj=float(np.linalg.norm(np.mean(after['points'],axis=0)-np.mean(before['points'],axis=0))); tol=2*(before['u']+after['u'])
                log('independent_motion_test',{'hand_m':hand,'object_m':obj,'attachment_error_m':err,'tolerance_m':tol,'source':after['source']})
                if err>tol or (hand>0.012 and obj<0.55*hand): raise RuntimeError('Independent motion contradicts retention')
                if probe and (hand<max(0.012,3*max(before['u'],after['u'])) or obj<0.55*hand): raise RuntimeError('Prospective test did not produce a resolvable retained-load effect')
                C['holding']='retained'; probe=False; api.checkpoint('baseline',{'sample':after,'state':afterstate,'reference_frame':M['ref']['frame'],'purpose':'verified_local_retention'})
        raise RuntimeError('Finite route bound exhausted at '+purpose)
    def jaw(command,calls=4):
        s=api.state(); target=pad(s); q=s['tcp_quaternion_xyzw']
        for k in range(calls):
            C['jaw_intent']=command; api.checkpoint('run',C)
            r=api.control(target.tolist(),q,command,Q,features={'purpose':'jaw transition; object effect requires observation'},tool_point='pad_center',steps=3,translation_limit=0.005,rotation_limit=0.03,position_tolerance=0.001,rotation_tolerance=0.03)
            if r['choices']['gripper']==command:
                C['jaw_ack']=command
                if command=='open': C['holding']='released'
                elif command=='close': C['holding']='possible'
                api.checkpoint('run',C)
            if r['status']=='stalled' or r['position_error_m']>0.006: raise RuntimeError('Jaw transition displaced or stalled the hand')
        if C.get('jaw_ack')!=command: raise RuntimeError('Jev did not acknowledge requested jaw transition')
    def economical():
        P=M['plan']; W=P['world']; keys=[v['key'] for v in api.recall()]
        E=api.recall('economy')['value'] if 'economy' in keys else {}
        def contact_review(question,fields,context):
            s=api.state()
            same=M.get('frame519_receipt',False) and s['frame_id']==519 and np.linalg.norm(np.array(s['tcp_position_world_m'])-np.array([-0.0202482,0.120242,0.914271]))<0.00001
            if not same: return review(question,fields,context)
            if s['last_gripper_command']!='open' or C['holding']!='no': raise RuntimeError('Recorded preclosure observation invalidated by a jaw transition')
            definitions=['a: Top corner of the physical narrow carton end initially facing world +X, at the end of its top seam with initially larger world Y. Initial wrist pixel [306,615].','b: Other top corner of that SAME physical narrow end, with initially smaller world Y. Initial wrist pixel [525,613].','c: Center of the dark blue oval emblem on that exposed narrow end face, not the main-label emblem. Initial wrist pixel [414,590].']
            params={'identity':'requested_item','correspondence':'unavailable','definitions':definitions,'camera':'robot0_eye_in_hand','polygon':[[323,578],[500,574],[515,599],[516,637],[313,637],[313,611]],'alignment':'supported','model':'consistent','world_prior':'consistent','upward':'supported','edge_camera':'robot0_eye_in_hand','edge_pixels':[[306,615],[525,613]]}
            r={'parameters':params,'points':{},'measurement_errors':[],'frame_id':519,'source':'Recorded semantic review at identical physical frame; new calibrated measurements and newly defined local reference'}
            for n,px in [('w0',[334,629]),('w1',[493,629]),('c',[414,590])]:
                try: r['points'][n]=api.point('robot0_eye_in_hand',px,radius=2)
                except Exception as e: r['measurement_errors'].append({'name':n,'error':str(e)})
            plane=geo.plane(np.array(context['shape_hypothesis_world']))['coefficients']
            witness=points(r,['w0','w1'],1)
            if max(abs(witness@np.array(plane[:3])+plane[3]))>3*context['shape_uncertainty_m']: raise RuntimeError('Reacquired surface contradicts same-frame face hypothesis')
            for n,px in [('a',[306,615]),('b',[525,613])]:
                try: r['points'][n]=api.plane_point('robot0_eye_in_hand',px,plane)
                except Exception as e: r['measurement_errors'].append({'name':n,'error':str(e)})
            if all(n in r['points'] for n in ['a','b','c']): params['correspondence']='exact'
            log('same_frame_contact_evidence',{'frame':519,'semantic_review_source':'method 4 recorded preclosure review; no physical steps since','new_patch':'Visible printed end surface, excluding hand; not the failed lower strip','new_reference_definitions':definitions,'measurement_errors':r['measurement_errors'],'scope':'Historical interpretations reused only at identical physical frame; fresh depth and calibrated ray measurements'})
            return r
        def route_review(question,fields,context):
            cached=C.get('route_cache')
            if cached is not None and api.state()['native_steps']-cached['native_steps']<=45:
                log('scoped_route_review_reuse',{'review_frame':cached['frame_id'],'current_frame':api.state()['frame_id'],'scope':cached['scope']})
                return cached
            if api.state()['budgets']['gpt_remaining']<2: raise RuntimeError('No unexpired local route assessment while preserving final verification')
            return review(question,fields,context)
        def save(name=None):
            C['compact']=True
            if name is not None: C['phase']=name
            api.checkpoint('economy',E); api.checkpoint('run',C)
        ref_fields={'identity':['requested_item','ambiguous','unavailable'],'correspondence':['exact','ambiguous','unavailable'],'definitions':array({'type':'string','maxLength':240},3),'camera':['agentview','robot0_eye_in_hand'],'polygon':{'type':['array','null'],'items':pixel,'minItems':3,'maxItems':16}}
        def adopt(r,shape=None,u=0.0):
            p=r['parameters']; bad=[v['name'] for v in r['measurement_errors']]
            if p['identity']!='requested_item': raise RuntimeError('Current patch identity is ambiguous')
            marks=[r['points'][n]['world_m'] for n in ['a','b','c'] if n in r['points'] and n not in bad]
            if len(marks)!=3 or p['correspondence']!='exact': marks=[]
            f={'marks':marks,'definitions':p['definitions'],'camera':p['camera'],'polygon':p['polygon'],'frame':r['frame_id'],'handle':None,'shape':None if shape is None else shape.tolist(),'shape_u':float(u),'identity':P['item']}
            api.checkpoint('reference_candidate',f)
            if p['polygon'] is not None:
                try:
                    receipt=api.track_init(p['camera'],p['polygon']); f['handle']=receipt['handle']; f['creation']=receipt
                except Exception as e: log('current_patch_initialization',str(e))
            M['ref']=f; api.checkpoint('reference',f)
            if f['handle'] is None and len(marks)!=3: raise RuntimeError('Neither current textured patch nor exact measured landmarks obtained')
        def current():
            f=M['ref']; v=sample(f,False,True)
            if v is None and api.state()['budgets']['gpt_remaining']>1: v=sample(f,True,True)
            if v is None or v['T'] is None or f['shape'] is None:
                raise RuntimeError('Current envelope registration unresolved; a local patch alone cannot replace its shape relationship')
            c=geo.transform(np.array(f['shape']),np.array(v['T'])); u=max(P['u'],f.get('shape_u',0.0))+v['u']
            return v,c,float(u)
        def body(c):
            normal=np.array(geo.plane(c)['coefficients'][:3])
            if normal[2]<0.98: raise RuntimeError('Observed carton tilt invalidates horizontal release model')
            return np.concatenate([c,c-P['height']*normal])
        def compare(v0,s0,v1,s1):
            hand=float(np.linalg.norm(pad(s1)-pad(s0))); obj=float(np.linalg.norm(np.mean(v1['points'],axis=0)-np.mean(v0['points'],axis=0)))
            err=float(geo.attachment_error(np.array(v0['points']),np.array(v1['points']),s0,s1)); tol=2*(v0['u']+v1['u'])
            log('economical_motion_test',{'hand_m':hand,'object_m':obj,'attachment_error_m':err,'tolerance_m':tol})
            if err>tol or (hand>0.012 and obj<0.55*hand): raise RuntimeError('Independent measured motion contradicts retained-load hypothesis')
            return hand>max(0.012,3*max(v0['u'],v1['u'])) and obj>0.55*hand
        def leg(goal,cap,tol,purpose,held,reserve):
            s=api.state(); b=s['budgets']; cap=min(cap,int(b['jev_remaining'])-reserve,int(b['native_steps_remaining']//3)-reserve)
            if cap<1: raise RuntimeError('Insufficient control reserve for '+purpose)
            prospective=purpose=='bounded prospective lift'
            before=E['test']['sample'] if prospective else (current()[0] if held else None)
            baseline_state=E['test']['state'] if prospective else s
            if held: api.checkpoint('baseline',{'sample':before,'state':baseline_state,'reference_frame':M['ref']['frame'],'purpose':purpose})
            C['intent']={'target_pad':goal.tolist(),'gripper':'keep','frame':s['frame_id'],'purpose':purpose}; save()
            r=api.drive(goal.tolist(),P['quaternion'],'keep',Q,features={'purpose':purpose,'independent_object_check':held,'target_pad_world_m':goal.tolist(),'arrival_is_not_object_effect':True},tool_point='pad_center',max_calls=cap,translation_limit=0.02,rotation_limit=0.07,steps=3,position_tolerance=tol,rotation_tolerance=0.03)
            log('economical_lease',{'status':r['status'],'frame':r['frame_id'],'calls':r['lease_calls'],'position_error_m':r['position_error_m']})
            if r['status']=='stalled': raise RuntimeError('Stalled economical leg; no repeated contact push')
            if r['status'] not in ['reached','moved','lease_exhausted']: raise RuntimeError('Unexpected economical motion status')
            after=api.state()
            if held:
                v=sample(M['ref'],False) if prospective else current()[0]
                if v is None:
                    C['holding']='possible'; log('prospective_observation_gap',{'frame':after['frame_id'],'scope':'Lift occurred; registration unknown. Recover current correspondence before further ascent or transport.'})
                elif compare(before,baseline_state,v,after): C['holding']='retained'
            if np.linalg.norm(pad(after)-pad(s))<0.001 and np.linalg.norm(goal-pad(s))>max(0.003,tol): raise RuntimeError('Economical lease produced no measurable progress')
            save()
        if C['phase']=='descend':
            s=api.state()
            needed_reviews=2 if M.get('frame519_receipt',False) and s['frame_id']==519 else 3
            if s['budgets']['gpt_remaining']<needed_reviews or s['budgets']['jev_remaining']<22: raise RuntimeError('Insufficient remaining budget for contact, transport and verification')
            if C['holding']!='no' or s['last_gripper_command']!='open': raise RuntimeError('Economical preclosure requires acknowledged open, unheld state')
            f=M['ref']; v=sample(f,False,True); u=P['u']
            if v is None and M.get('original',{}).get('handle') is not None:
                candidate=M['original']; measured=sample(candidate,False,True)
                if measured is not None and candidate['shape'] is not None:
                    f=candidate; v=measured; M['ref']=f; api.checkpoint('reference',f)
            if v is not None and f['shape'] is not None: c=geo.transform(np.array(f['shape']),np.array(v['T'])); u=max(u,v['u'],f.get('shape_u',0.0))
            else:
                v=None; old=M.get('original',f)
                if old['shape'] is None or s['native_steps']-C.get('world_step',-1000)>45: raise RuntimeError('No current envelope or admissible short-horizon stationary hypothesis')
                c=np.array(old['shape']); u=max(u,old.get('shape_u',0.0))
            now=pad(s); support=np.array(W['support_plane']); plane=geo.plane(c)['coefficients']; rise=max(0.025,W['rim_z']+0.020-min(float(min(body(c)[:,2])),float(min((finger_offsets(s)+now)[:,2]))))
            fields=dict(ref_fields); fields.update({'alignment':['supported','obstructed','unknown'],'model':['consistent','contradicted','unknown'],'world_prior':['consistent','contradicted','unobservable'],'upward':['supported','unsupported','unknown'],'edge_camera':['agentview','robot0_eye_in_hand'],'edge_pixels':{'type':['array','null'],'items':pixel,'minItems':2,'maxItems':2}})
            r=contact_review('Preclosure only: alignment supported means actual open fingers straddle carton sides and no observed outer-bowl/table obstruction to inward closure. The small residual is not a reason for more descent. model consistent requires current partial face/edge evidence consistent with the supplied supported rigid rectangle, with no observed disturbance; hidden corners alone do not contradict it. world_prior addresses bowl/table stationarity. upward assesses the proposed straight upward observation-producing ascent, initially at most 25 mm, not a later transfer. Request w0,w1 on visible top interior. Optionally give edge_camera and edge_pixels for both genuinely visible endpoints of one physical top edge; null if hidden. If a new reference is needed, return camera/polygon on current textured carton interior, and request a,b,c at exactly identifiable print features with physical definitions. identity requested_item also confirms that displayed tracked features belong to this carton. correspondence exact requires unambiguous a,b,c identities; absent measurements remain absent. Polygon may be null if unavailable. Do not require the complete outline for closure or a prospective lift.',fields,{'item':P['item'],'shape_hypothesis_world':c.tolist(),'shape_uncertainty_m':u,'world':W,'pad_world':now.tolist(),'finger_offsets_world':finger_offsets(s).tolist(),'upward_end_pad':(now+np.array([0.0,0.0,rise])).tolist(),'need_new_reference':v is None,'reference_definitions':f['definitions'],'tracked_points':None if v is None else v['points']})
            p=r['parameters']; witness=points(r,['w0','w1'],1)
            if p['alignment']!='supported' or p['model']!='consistent' or p['world_prior']!='consistent' or p['upward']!='supported' or p['identity']!='requested_item': raise RuntimeError('Current closure/ascent witness or stationary prior is unresolved')
            if max(abs(witness@np.array(plane[:3])+plane[3]))>3*u: raise RuntimeError('Visible face contradicts retained face plane')
            if p['edge_pixels'] is not None:
                e=np.array([api.plane_point(p['edge_camera'],px,plane)['world_m'] for px in p['edge_pixels']]); errors=[]
                for i in range(4):
                    pair=c[[i,(i+1)%4]]; errors.append(float(min(max(np.linalg.norm(e-pair,axis=1)),max(np.linalg.norm(e-pair[::-1],axis=1)))))
                if min(errors)>4*u: raise RuntimeError('Current visible edge conflicts with shape hypothesis: '+str(errors))
                u=max(u,min(errors)/2)
            elif v is None: u+=0.0015
            R=np.array(geo.rotation(s['tcp_quaternion_xyzw'])); ext=np.array(s['own_geometry']['pad_extent_in_tool_m']); uv=body(c)@R[:,:2]; a=now@R[:,:2]; gap=2*abs(s['gripper_qpos_m'][0]-s['gripper_qpos_m'][1])-ext[1]
            overlap=float(min(a[0]+ext[0]/2,max(uv[:,0]))-max(a[0]-ext[0]/2,min(uv[:,0]))); aperture=float(gap/2-max(abs(uv[:,1]-a[1])))
            half=float(0.5*(abs(R[2,0])*ext[0]+abs(R[2,2])*ext[2])); vertical=float(min(max(c[:,2]),now[2]+half)-max(min(body(c)[:,2]),now[2]-half)); clearance=float(min((finger_offsets(s)+now)@support[:3]+support[3]))
            log('actual_preclosure_effect_geometry',{'side_band_overlap_m':overlap,'vertical_overlap_m':vertical,'aperture_margin_m':aperture,'finger_support_separation_m':clearance,'uncertainty_m':u,'pose_error_is_not_this_gate':True})
            if min(overlap,vertical)<=2*u or min(aperture,clearance)<=u: raise RuntimeError('Actual preclosure overlap/aperture/support gate fails')
            if v is None: adopt(r,c,u)
            else: f['shape_u']=u; api.checkpoint('reference',f)
            baseline=sample(M['ref'],False)
            if baseline is None: raise RuntimeError('No independently measurable preclosure local motion reference')
            E['test']={'sample':baseline,'state':api.state(),'scope':'Measured before closure; cumulative contact-plus-lift motion must be observed independently'}
            E['lift_ceiling']=float(now[2]+rise+0.005); C['world_step']=s['native_steps']; save('economical_close')
        if C['phase']=='economical_close':
            if C.get('jaw_ack')!='close' or api.state()['last_gripper_command']!='close': jaw('close',3)
            C['holding']='possible'; save('economical_test')
        if C['phase']=='economical_test':
            if 'test' not in E: raise RuntimeError('Interrupted closure lacks an independent measured preclosure baseline')
            leg(pad(api.state())+np.array([0.0,0.0,0.025]),3,0.004,'bounded prospective lift',True,20); save('economical_raise')
        if C['phase']=='economical_raise':
            v,c,u=current(); s=api.state(); low=min(float(min(body(c)[:,2])),float(pad(s)[2]+min(P['open_low_z'],min(finger_offsets(s)[:,2])))); goal=pad(s)
            goal[2]=min(E['lift_ceiling'],goal[2]+max(0.0,W['rim_z']+0.012+u+W.get('rim_uncertainty_m',P['u'])-low))
            if goal[2]-pad(s)[2]>0.003: leg(goal,4,0.003,'complete locally reviewed clearance ascent',True,16)
            v,c,u=current()
            if not compare(E['test']['sample'],E['test']['state'],v,api.state()): raise RuntimeError('Cumulative lift still does not resolve retention')
            C['holding']='retained'; save('economical_route')
        if C['phase']=='economical_route':
            v,c,u=current(); s=api.state(); low=min(float(min(body(c)[:,2])),float(pad(s)[2]+min(P['open_low_z'],min(finger_offsets(s)[:,2])))); margin=low-W['rim_z']-u-W.get('rim_uncertainty_m',P['u'])
            log('transport_height',{'lowest_envelope_m':low,'rim_z_m':W['rim_z'],'remaining_clearance_m':margin})
            if margin<=0.003: raise RuntimeError('Measured ascent did not establish local rim clearance')
            goal=pad(s); goal[:2]+=np.array(W['bowl_center'])-c.mean(axis=0)[:2]
            fields={'obstruction':['external_obstacle','none_observed','unknown'],'visibility':['observed','partial','self_occluded','unknown'],'local_step':['supported','unsupported','unknown'],'world_prior':['consistent','contradicted','unobservable'],'load':['consistent','slipped_or_disturbed','unknown']}
            r=route_review('Assess this measured retained carton and proposed above-rim translation, then only its local centered release-height adjustment/opening and upward 45 mm retreat. obstruction external_obstacle requires a visible external object intersecting these local actions; none_observed is not a clearance certificate. visibility separates incomplete external space from robot/item self-occlusion. local_step supported requires visible partial evidence plus supplied measured envelopes sufficient for bounded progress, not complete corridor visibility. Reject actual outer rim/wall interference. world_prior consistent requires current partial bowl/table evidence consistent with their measurements. load consistent means the identified rigid carton matches the tracked envelope without observed slip/deformation; missing corners alone are not slip. Report unknown when no justified local action exists.',fields,{'item':P['item'],'start_pad':pad(s).tolist(),'transfer_end_pad':goal.tolist(),'current_body_world':body(c).tolist(),'object_uncertainty_m':u,'finger_offsets_world':finger_offsets(s).tolist(),'world':W,'observed_clearance_margin_m':margin,'reference_definitions':M['ref']['definitions'],'current_tracked_points':v['points']})
            p=r['parameters']
            if p['obstruction']!='none_observed' or p['local_step']!='supported' or p['world_prior']!='consistent' or p['load']!='consistent': raise RuntimeError('No justified local transfer/release path: '+str(p))
            C['world_step']=r.get('native_steps',s['native_steps']); E['route_review']={'parameters':p,'frame':r['frame_id'],'native_steps':C['world_step']}; save('economical_transfer')
        if C['phase']=='economical_transfer':
            v,c,u=current(); goal=pad(api.state()); goal[:2]+=np.array(W['bowl_center'])-c.mean(axis=0)[:2]
            leg(goal,6,0.002,'measured above-rim centering',True,10); save('economical_gate')
        if C['phase']=='economical_gate':
            for attempt in range(2):
                v,c,u=current(); s=api.state(); b=body(c); rim_u=W.get('rim_uncertainty_m',P['u']); radial=float(max(np.linalg.norm(b[:,:2]-np.array(W['bowl_center']),axis=1))); bottom=float(min(b[:,2])); finger=float(pad(s)[2]+min(P['open_low_z'],min(finger_offsets(s)[:,2]))); slack=W['bowl_radius']-radial-u-rim_u
                valid=slack>0 and bottom>W['rim_z']+u+rim_u and bottom<=W['rim_z']+0.025 and finger>W['rim_z']+rim_u
                log('economical_release_geometry',{'radial_slack_m':slack,'bottom_above_rim_m':bottom-W['rim_z'],'open_fingers_above_rim_m':finger-W['rim_z'],'object_uncertainty_m':u,'rim_uncertainty_m':rim_u,'valid':bool(valid)})
                if s['native_steps']-C['world_step']>45: raise RuntimeError('Stationary bowl/table evidence horizon expired before release')
                if valid: break
                if attempt==1: raise RuntimeError('Measured release geometry still fails after one bounded correction')
                goal=pad(s); goal[:2]+=np.array(W['bowl_center'])-c.mean(axis=0)[:2]
                if bottom>W['rim_z']+0.025 or bottom<=W['rim_z']+u+rim_u: goal[2]+=W['rim_z']+0.012+u+rim_u-bottom
                if goal[2]>E['lift_ceiling']+0.005: raise RuntimeError('Release correction exceeds reviewed local height scope')
                leg(goal,3,0.0008 if slack<=0 else 0.002,'one effect-driven release correction',True,7)
            save('economical_release')
        if C['phase']=='economical_release':
            if C['holding']!='released': jaw('open',3)
            if api.state()['last_gripper_command']!='open': raise RuntimeError('Release was not acknowledged open')
            save('economical_verify')
        if C['phase']=='economical_verify':
            if not E.get('retracted',False):
                start=pad(api.state()); leg(start+np.array([0.0,0.0,0.045]),3,0.006,'upward post-release observation retreat',False,1)
                if pad(api.state())[2]-start[2]<0.015: raise RuntimeError('No adequate post-release view change')
                E['retracted']=True; save()
            old=sample(M['ref'],False); fields=dict(ref_fields); fields['relation']=['supported_inside','bridging','outside','held','unknown']; fields['bowl']=['stationary','disturbed','unknown']
            r=review('Assess the actual released carton in this new view. relation supported_inside means inside and supported by the bowl, not bridging, outside or still held. bowl stationary requires current partial evidence of no bowl displacement. identity requested_item must confirm the supplied tracked points belong to this carton when available. If tracking is unavailable, supply camera/polygon for a currently visible rigid textured carton patch, and request a,b,c on physically identifiable print features with exact definitions. correspondence exact requires unambiguous identities, not historical projections; otherwise ambiguous/unavailable. A new reference is for subsequent stability observation, not proof of the placement relation. Return unknown for unresolved relations.',fields,{'item':P['item'],'container':P['container'],'reference_definitions':M['ref']['definitions'],'tracked_points':None if old is None else old['points'],'need_new_reference':old is None,'historical_world':W})
            p=r['parameters']
            if p['identity']!='requested_item' or p['relation']!='supported_inside' or p['bowl']!='stationary': raise RuntimeError('Post-release relation unresolved or unsuccessful: '+str(p['relation']))
            if old is None: adopt(r)
            first=sample(M['ref'],False)
            if first is None: raise RuntimeError('No current measured stability reference after release')
            E['release_observation']={'sample':first,'relation':p['relation'],'frame':r['frame_id'],'definitions':M['ref']['definitions']}; save()
            jaw('keep',1); second=sample(M['ref'],False)
            if second is None and api.state()['budgets']['gpt_remaining']>0: second=sample(M['ref'],True)
            if second is None: raise RuntimeError('Post-settling registration/correspondence unavailable; released item left undisturbed')
            drift=float(max(np.linalg.norm(np.array(second['points'])-np.array(first['points']),axis=1))); ok=drift<=0.005 and max(first['u'],second['u'])<=0.0025
            log('economical_post_release',{'relation':p['relation'],'first_frame':first['frame'],'second_frame':second['frame'],'observed_world_drift_m':drift,'uncertainty_m':[first['u'],second['u']],'heuristic_stability_threshold_m':0.005,'completion_proposed':bool(ok)})
            C['completion']=bool(ok); save('economical_done')
        return bool(C.get('completion',False))
    try:
        keys=[r['key'] for r in api.recall()]
        if 'run' in keys:
            record=api.recall('run'); C=record['value']
            M['frame519_receipt']=record['frame_id']==519 and record['source_sha256']=='73ef9d2756615da46aab8dae5fa17152a5af3a6baa77391a667f26d765c69d40' and C['phase']=='descend' and C['holding']=='no'
        for key,name in [('plan','plan'),('reference','ref'),('original','original')]:
            if key in keys:
                saved=api.recall(key); M[name]=saved['value']
                if key=='plan': M['plan_frame']=saved['frame_id']
        if C['phase']=='new' and 'plan' in M and M['plan_frame']==api.state()['frame_id']:
            c,fit,u=face(); P=M['plan']; dims=sorted(np.linalg.norm(np.roll(c,-1,axis=0)-c,axis=1).tolist())
            dim_error=float(max(abs(np.array(dims)-np.array(P['dimensions'])))); height_error=abs(float(c[:,2].mean())-P['top_z'])
            if dim_error>4*max(u,P['u']) or height_error>2*max(u,P['u']): raise RuntimeError('Same-frame face conflicts with accepted plan: '+str({'dimension_error_m':dim_error,'height_error_m':height_error,'uncertainty_m':max(u,P['u'])}))
            f=new_reference(c); f['shape_u']=max(u,P['u']); api.checkpoint('reference',f); M['original']=dict(f); api.checkpoint('original',f)
            C['world_step']=api.state()['native_steps']; log('same_frame_plan_reuse',{'frame':M['plan_frame'],'dimension_error_m':dim_error,'height_error_m':height_error,'scope':'Accepted support, bowl and grasp geometry; current face independently measured'})
            phase('approach')
        if C['phase']=='new':
            c,fit,u=face()
            r=review('Interpret the runtime request as item into container. Return item and container names. model supported means the identified carton rests on a horizontal table, and the destination is an open approximately circular bowl with a visible inner rim. Request s0..s3 on the local supporting tabletop; r0..r5 distributed around the INNER bowl rim, not the outer silhouette; bottom on a visible interior surface near the bowl bottom. Missing samples must remain missing. No hidden underside or object center is directly measured.',{'item':'string','container':'string','model':['supported','unsupported','unknown']},{'request':'could you put the cream cheese into the bowl'})
            if r['parameters']['model']!='supported': raise RuntimeError('Required local carton/support/open-bowl model not established')
            sf=geo.plane(points(r,['s0','s1','s2','s3'],3)); rp=points(r,['r0','r1','r2','r3','r4','r5'],4); rf=geo.plane(rp); circle=geo.circle_xy(rp); bottom=points(r,['bottom'],1)[0]
            if min(sf['coefficients'][2],rf['coefficients'][2],fit['coefficients'][2])<0.98 or max(sf['rms_m'],rf['rms_m'],circle['rms_m'])>0.003 or circle['largest_angular_gap_rad']>3.5: raise RuntimeError('Support/rim model inadequate: '+str({'support':sf,'rim':rf,'circle':circle}))
            center=c.mean(axis=0); coeff=np.array(sf['coefficients']); base=float(-(np.dot(coeff[:2],center[:2])+coeff[3])/coeff[2]); h=float(center[2]-base); s=api.state(); q=s['tcp_quaternion_xyzw']; R=np.array(geo.rotation(q)); ext=np.array(s['own_geometry']['pad_extent_in_tool_m']); gap=2*abs(s['gripper_qpos_m'][0]-s['gripper_qpos_m'][1])-ext[1]
            width=float(np.ptp(c@R[:,1])); edge=c[1]-c[0] if np.linalg.norm(c[1]-c[0])<np.linalg.norm(c[2]-c[1]) else c[2]-c[1]
            if width+4*u>gap:
                yaw=math.atan2(edge[1],edge[0])-math.atan2(R[1,1],R[0,1]); yaw=(yaw+math.pi/2)%math.pi-math.pi/2; q=api.compose(q,[0.0,0.0,yaw]); R=np.array(geo.rotation(q)); width=float(np.ptp(c@R[:,1]))
            half=float(0.5*(abs(R[2,0])*ext[0]+abs(R[2,2])*ext[2])); low=float(np.min(finger_offsets(s,q)[:,2])); overlap=min(h/2,half); lower=max(base+overlap-half,base+0.002+u-low); upper=float(center[2]-overlap+half)
            radius=float(np.max(np.linalg.norm(c[:,:2]-center[:2],axis=1))); rimz=float(np.max(rp[:,2])); opening=float(circle['radius_m'])
            rim_u=max(0.0015,float(rf['rms_m']),float(circle['max_radial_error_m']))
            fit_slack=opening-radius-u-rim_u; contact_span=upper-lower
            placement_tol=max(0.0005,min(0.001,fit_slack/3)); grasp_tol=max(0.0005,min(0.001,0.45*contact_span))
            failed=[name for name,ok in [('height',h>2*u),('contact_overlap',overlap>2*u),('jaw_span',width+4*u<gap),('pad_interval_and_controller',contact_span>=2*grasp_tol),('opening_and_centering',fit_slack>placement_tol),('bowl_depth',rimz-bottom[2]>2*u)] if not ok]
            log('grasp_and_fit_geometry',{'height_m':h,'opening_proxy_m':float(gap),'carton_width_m':width,'pad_z_interval_m':[lower,upper],'desired_overlap_m':overlap,'carton_radius_m':radius,'bowl_radius_m':opening,'object_uncertainty_m':u,'rim_uncertainty_m':rim_u,'available_centering_slack_m':fit_slack,'position_tolerance_m':placement_tol,'grasp_tolerance_m':grasp_tol,'failed_gates':failed})
            if failed: raise RuntimeError('Failed measured feasibility gates: '+str(failed))
            P={'item':r['parameters']['item'],'container':r['parameters']['container'],'height':h,'u':u,'quaternion':q,'grasp_z':float((lower+upper)/2),'grasp_tolerance':grasp_tol,'position_tolerance':placement_tol,'grasp_interval':[lower,upper],'top_z':float(center[2]),'open_low_z':low,'dimensions':sorted(np.linalg.norm(np.roll(c,-1,axis=0)-c,axis=1).tolist()),'world':{'support_plane':sf['coefficients'],'bowl_center':circle['center_xy_m'],'bowl_radius':opening,'rim_z':rimz,'rim_uncertainty_m':rim_u,'interior_sample':bottom.tolist()}}
            M['plan']=P; api.checkpoint('plan',P); f=new_reference(c); M['original']=dict(f); api.checkpoint('original',f); C['world_step']=s['native_steps']; phase('approach')
        P=M['plan']; W=P['world']
        if C.get('compact',False) or (C['phase']=='descend' and api.state()['budgets']['jev_remaining']<50):
            ok=economical()
            return {'completion_proposed':bool(ok),'evidence':{'phase':C['phase'],'holding':C['holding'],'events':C['events'],'scope':'Measured proposal only; no native task predicates inspected.'}}
        if C['phase']=='closing':
            if api.state()['last_gripper_command']!='close': raise RuntimeError('Interrupted closure has no acknowledged close; inspect current contact before repair')
            C['holding']='possible'; phase('test')
        if C['phase']=='releasing':
            if C.get('jaw_ack')=='open' or api.state()['last_gripper_command']=='open': C['holding']='released'; phase('verify')
            else: raise RuntimeError('Interrupted release remains unresolved; do not automatically regrasp')
        if C['phase'] in ['approach','descend']:
            c,u=envelope(); center=c.mean(axis=0)
            if abs(center[2]-P['top_z'])>3*u: raise RuntimeError('Carton support-height prior invalidated')
            site=grasp_site(c,u); approach_z=max(float(center[2])+0.06,W['rim_z']+0.04)
            if C['phase']=='approach':
                move(np.array([site[0],site[1],approach_z]),'open','approach above offset carton grasp site'); phase('descend')
            current=pad(api.state())
            if float(np.linalg.norm(current[:2]-site))>max(pose_tolerance(),0.0015):
                safe_z=max(float(current[2]),approach_z)
                if safe_z-current[2]>pose_tolerance(): move(np.array([current[0],current[1],safe_z]),'open','rise before changing the blocked descent corridor')
                move(np.array([site[0],site[1],safe_z]),'open','relocate above rim to offset carton grasp site')
            move(np.array([site[0],site[1],P['grasp_z']]),'open','descend along alternate finger corridor beside supported carton')
            r=review('Check the local preclosure gate, not full perimeter registration. alignment supported means the open fingers straddle the identified carton sides without an observed external obstruction, with a visible face witness consistent with the saved stationary rectangular model. Return obstructed or unknown otherwise. Request w on the currently visible top interior. The pose target alone proves neither clearance nor contact.',{'alignment':['supported','obstructed','unknown']},{'carton_top_world':c.tolist(),'pad_center':pad(api.state()).tolist(),'opening_axis_world':np.array(geo.rotation(P['quaternion']))[:,1].tolist(),'uncertainty_m':u,'intentional_offset_site':C.get('grasp_candidate')})
            witness=points(r,['w'],1)[0]; pl=geo.plane(c)['coefficients']
            if r['parameters']['alignment']!='supported' or abs(float(np.dot(pl[:3],witness)+pl[3]))>3*u: raise RuntimeError('Local closure alignment or stationary-face witness missing')
            s=api.state(); now=pad(s); R=np.array(geo.rotation(s['tcp_quaternion_xyzw'])); ext=np.array(s['own_geometry']['pad_extent_in_tool_m']); support=np.array(W['support_plane'])
            half_now=float(0.5*(abs(R[2,0])*ext[0]+abs(R[2,2])*ext[2])); base_now=float(-(np.dot(support[:2],c.mean(axis=0)[:2])+support[3])/support[2])
            overlap_now=max(0.0,min(float(c[:,2].mean()),float(now[2])+half_now)-max(base_now,float(now[2])-half_now))
            support_clearance=float(np.min((finger_offsets(s)+now)@support[:3]+support[3]))
            log('measured_preclosure_band',{'pad_z_m':float(now[2]),'target_z_m':P['grasp_z'],'pose_tolerance_m':pose_tolerance(),'side_overlap_m':overlap_now,'finger_support_separation_m':support_clearance,'uncertainty_m':u})
            if overlap_now<=2*u or support_clearance<=u: raise RuntimeError('Actual pad band or finger/support separation is insufficient; no closure commanded')
            phase('closing'); jaw('close'); phase('test')
        if C['phase']=='test':
            move(pad(api.state())+np.array([0.0,0.0,0.025]),'keep','prospective retention lift',True); phase('raise')
        if C['phase']=='raise':
            c,u=envelope(); s=api.state(); goal=pad(s); bottomz=float(min(c[:,2])-P['height']); goal[2]+=max(0.0,W['rim_z']+0.05-bottomz)
            move(goal,'keep','raise retained carton above rim',True); phase('transfer')
        if C['phase']=='transfer':
            c,u=envelope(); goal=pad(api.state()); goal[:2]+=np.array(W['bowl_center'])-c.mean(axis=0)[:2]
            move(goal,'keep','center retained carton over bowl',True); phase('lower')
        if C['phase']=='lower':
            c,u=envelope(); normal=np.array(geo.plane(c)['coefficients'][:3]); bottom=c-P['height']*normal; s=api.state(); goal=pad(s); goal[:2]+=np.array(W['bowl_center'])-c.mean(axis=0)[:2]
            offset=float(min(bottom[:,2])-pad(s)[2]); floorlow=min(P['open_low_z'],float(min(finger_offsets(s)[:,2])))
            release_clearance=max(0.005,u+W.get('rim_uncertainty_m',P['u'])+2*pose_tolerance())
            goal[2]=max(W['rim_z']+release_clearance-offset,W['rim_z']+release_clearance-floorlow)
            if normal[2]<0.98: raise RuntimeError('Carton tilt exceeds the measured upright placement model')
            move(goal,'keep','bounded descent to above-rim release',True); phase('release_gate')
        if C['phase']=='release_gate':
            c,u=envelope(); normal=np.array(geo.plane(c)['coefficients'][:3]); body=np.concatenate([c,c-P['height']*normal]); radial=float(max(np.linalg.norm(body[:,:2]-np.array(W['bowl_center']),axis=1))); bottomz=float(min(body[:,2])); fingerz=float(pad(api.state())[2]+P['open_low_z'])
            rim_u=W.get('rim_uncertainty_m',P['u']); release_slack=W['bowl_radius']-radial-u-rim_u
            log('release_geometry',{'radial_extent_m':radial,'opening_radius_m':W['bowl_radius'],'radial_slack_after_uncertainty_m':release_slack,'bottom_above_rim_m':bottomz-W['rim_z'],'open_fingers_above_rim_m':fingerz-W['rim_z'],'object_uncertainty_m':u,'rim_uncertainty_m':rim_u})
            if release_slack<=0 or bottomz<W['rim_z']+u+rim_u or bottomz>W['rim_z']+0.025 or fingerz<W['rim_z']+rim_u: raise RuntimeError('Measured release envelope or finger/rim clearance fails; see release_geometry values')
            phase('releasing'); jaw('open'); phase('verify')
        if C['phase']=='verify':
            move(pad(api.state())+np.array([0.0,0.0,0.07]),'open','retract for independent post-release observation')
            results=[]; definitions=None
            for k in range(2):
                r=review('Assess the actual released carton and bowl. relation supported_inside requires the carton to be inside and supported by the bowl, not bridging its rim, outside, or still held. Distinguish unknown. Request a,b,c on three identifiable physical carton features and r0..r5 on the current inner rim. On the first observation define those exact features; on the next use the same definitions. identity exact means unambiguous correspondences, not historical projections. Return current definitions.',{'relation':['supported_inside','bridging','outside','held','unknown'],'identity':['exact','ambiguous','unavailable'],'definitions':array({'type':'string','maxLength':300},3)},{'item':P['item'],'container':P['container'],'saved_feature_definitions':definitions,'observation_number':k})
                a=points(r,['a','b','c'],3); rim=points(r,['r0','r1','r2','r3','r4','r5'],4); circle=geo.circle_xy(rim)
                if r['parameters']['identity']!='exact' or circle['rms_m']>0.003: raise RuntimeError('Post-release identity or current bowl geometry unresolved')
                results.append({'points':a.tolist(),'bowl_center':circle['center_xy_m'],'relation':r['parameters']['relation'],'frame':r['frame_id']}); definitions=r['parameters']['definitions']
                if k==0:
                    api.checkpoint('release_observation',{'observation':results[0],'definitions':definitions}); jaw('keep')
            drift=float(max(np.linalg.norm(np.array(results[1]['points'])-np.array(results[0]['points']),axis=1))); bowl_drift=float(np.linalg.norm(np.array(results[1]['bowl_center'])-np.array(results[0]['bowl_center'])))
            ok=all(v['relation']=='supported_inside' for v in results) and drift<=0.005 and bowl_drift<=0.004
            log('post_release_assessment',{'observations':results,'carton_motion_m':drift,'bowl_motion_m':bowl_drift,'heuristic_stability_tolerance_m':0.005,'completion_proposed':bool(ok)})
            C['completion']=bool(ok); phase('done')
        return {'completion_proposed':bool(C.get('completion',False)),'evidence':{'phase':C['phase'],'holding':C['holding'],'events':C['events'],'scope':'Observable proposal only; no native success predicate was inspected.'}}
    except Exception as e:
        log('unresolved_gap',str(e))
        return {'completion_proposed':False,'evidence':{'phase':C['phase'],'holding':C['holding'],'gap':str(e),'events':C['events'],'recovery':'Physical state persists. Do not reopen a possibly held item or disturb a released item merely because sensing failed.'}}

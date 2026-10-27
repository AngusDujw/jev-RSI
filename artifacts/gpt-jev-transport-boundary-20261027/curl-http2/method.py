def main(api):
    E, H, K = [], {}, {}
    task = 'could you put the cream cheese into the bowl'
    pixel = {'type':'array','items':{'type':'integer','minimum':0,'maximum':767},'minItems':2,'maxItems':2}
    patch_fields = {'camera':['agentview','robot0_eye_in_hand'],'polygon':{'type':'array','items':pixel,'maxItems':16}}
    Q = {}
    for axis in ['x','y','z','rx','ry','rz']:
        Q[axis] = {'type':'choice','instructions':'For world axis '+axis+', read its bound goal_relation. Select positive for increase, negative for decrease, and hold for within_tolerance. These are measured pose residuals, not object-contact evidence.','criteria':{'negative':'The selected world axis must decrease.','hold':'The selected world axis is within tolerance.','positive':'The selected world axis must increase.'}}
    Q['gripper'] = {'type':'choice','instructions':'Read the objective gripper field. Deliver exactly open, close, or keep as requested. Do not infer retention.','criteria':{'open':'Objective requests open.','close':'Objective requests close.','keep':'Objective requests keep.'}}
    def log(tag, data):
        E.append({'event':tag,'data':data}); api.note(str(E[-1]))
    def need(ok, why):
        if not ok: raise RuntimeError(why)
    def save():
        api.checkpoint('package_bowl_episode', K)
    def review(question, fields, context=None, final=False):
        need(api.state()['budgets']['gpt_remaining'] > (0 if final else 2), 'Observation budget reserve reached')
        r = api.review(question, context=context, fields=fields)
        log('review', {'frame_id':r['frame_id'],'parameters':r['parameters'],'measurement_errors':r['measurement_errors'],'explanation':r['explanation']})
        need(r['status'] != 'stop', 'Observation review requested stop')
        return r
    def points(r, names):
        bad = set(e['name'] for e in r['measurement_errors'])
        return {n:r['points'][n]['world_m'] for n in names if n in r['points'] and n not in bad}
    def region(r, name):
        need(name in r['regions'] and not any(e['name']==name for e in r['measurement_errors']), 'Missing measured region '+name)
        return np.array(r['regions'][name]['world_m'], dtype=float)
    def bowl(r):
        p = points(r, ['b'+str(i) for i in range(6)]+['floor'])
        rim = np.array([p['b'+str(i)] for i in range(6) if 'b'+str(i) in p])
        need(len(rim)>=5 and 'floor' in p, 'Need five distributed inner rim samples and an interior floor sample')
        pl, ci = geo.plane(rim), geo.circle_xy(rim)
        log('rim_fit', {'plane':pl,'circle':ci,'floor':p['floor']})
        need(pl['coefficients'][2]>.97 and pl['rms_m']<.004 and ci['max_radial_error_m']<.004 and ci['largest_angular_gap_rad']<math.pi, 'Inner rim is not a supported horizontal circle')
        c, z = np.array(ci['center_xy_m']), float(np.mean(rim[:,2]))
        need(np.linalg.norm(np.array(p['floor'][:2])-c)<ci['radius_m']*.5 and p['floor'][2]<z, 'Interior floor identity or depth is inconsistent')
        return {'xy':c.tolist(),'z':z,'radius':ci['radius_m'],'floor':p['floor'],'u':max(.002,pl['rms_m']+ci['max_radial_error_m']),'frame_id':r['frame_id']}
    def init_patch(parameters, reference):
        H.clear()
        if len(parameters['polygon'])>=3:
            try:
                t = api.track_init(parameters['camera'], parameters['polygon'])
                H.update({'handle':t['handle'],'reference':reference,'frame_id':t['frame_id']})
                log('patch_initialized', t)
            except Exception as ex: log('patch_unavailable', str(ex))
    def observe():
        if 'handle' in H:
            try:
                t = api.track_update(H['handle'])
                if t['status']=='tracked':
                    spread = float(np.max(np.asarray(t['inlier_spread_m'])))
                    u = max(.002, t['uncertainty_floor_m']+2*t['rms_m'])
                    log('registration', {'frame_id':t['frame_id'],'reference_frame_id':t['reference_frame_id'],'inliers':t['inliers'],'matches':t['matches'],'rms_m':t['rms_m'],'spread_m':spread,'u_m':u})
                    if t['inliers']>=12 and t['inliers']/max(1,t['matches'])>=.55 and t['rms_m']<.003 and spread>.004 and u<=.006:
                        P = geo.transform(H['reference'], t['transform_initial_world_to_current_world'])
                        return {'points':P.tolist(),'u':u,'state':api.state(),'frame_id':t['frame_id'],'source':'RGB-D rigid patch registration'}
                else: log('registration_unknown', {'frame_id':t['frame_id'],'reason':t['reason']})
            except Exception as ex: log('tracker_error', str(ex))
        f = dict(patch_fields); f['identity'] = ['unambiguous','ambiguous']
        r = review('Registration recovery: independently identify the SAME physical landmarks p0..p6 defined in context. Request named depth points for every currently identifiable landmark, preferring textured interior p4..p6. Omit hidden or ambiguous points. Camera-relative corner names and stationary historical projections are NOT correspondences. identity is unambiguous only for the points actually requested. Give camera and polygon for another currently visible textured patch belonging exclusively to this package, or polygon=[] if unavailable. Do not invent an object transform.', f, {'task':task,'labels':K['labels'],'reference':K['reference'],'reference_frame_id':K['reference_frame_id'],'last_observation':K.get('last')})
        p = points(r, ['p'+str(i) for i in range(7)])
        ids = [i for i in range(7) if 'p'+str(i) in p]
        need(r['parameters']['identity']=='unambiguous' and len(ids)>=3, 'Unknown registration: fewer than three unambiguous current corresponding landmarks; no justified transform')
        A = np.array(K['reference'])[ids]; B = np.array([p['p'+str(i)] for i in ids])
        ac, bc = A.mean(axis=0), B.mean(axis=0)
        U, S, V = np.linalg.svd((A-ac).T@(B-bc)); R = V.T@U.T
        if np.linalg.det(R)<0: V[-1,:] *= -1; R = V.T@U.T
        T = np.eye(4); T[:3,:3] = R; T[:3,3] = bc-R@ac
        residual = float(np.max(np.linalg.norm(geo.transform(A,T)-B,axis=1)))
        log('landmark_registration', {'ids':ids,'max_error_m':residual,'spread_m':float(math.sqrt(max(0,S[1])/len(ids)))})
        need(S[1]/len(ids)>.004**2 and residual<.004, 'Ambiguous or inconsistent landmark geometry')
        P = geo.transform(K['reference'], T).tolist()
        init_patch(r['parameters'], P)
        return {'points':P,'u':.003+residual,'state':api.state(),'frame_id':r['frame_id'],'source':'independent semantic landmark registration'}
    def deliver(target, quaternion, grip, phase):
        reserve = 10 if K.get('phase',0)>=6 else 30
        for attempt in range(2):
            n = min(28, api.state()['budgets']['jev_remaining']-reserve)
            need(n>=1, 'Control reserve reached during '+phase)
            before = api.state()
            receipt = api.drive(target, quaternion, grip, Q, features={'phase':phase,'target_pad_world_m':target,'interpretation':'Pose feedback only; no implicit contact or retention'}, max_calls=n, tool_point='pad_center', translation_limit=.015, rotation_limit=.08, steps=3, position_tolerance=.002, rotation_tolerance=.04)
            log('motion', {'phase':phase,'status':receipt['status'],'position_error_m':receipt['position_error_m'],'rotation_error_rad':receipt['rotation_error_rad'],'lease_calls':receipt['lease_calls'],'frame_id':receipt['frame_id']})
            if receipt['status']=='reached': return
            need(receipt['status']!='stalled', 'Stalled '+phase+'; no repeated contact pushing')
            after = api.state()
            progress = np.linalg.norm(np.array(after['tcp_position_world_m'])-np.array(before['tcp_position_world_m']))
            need(receipt['status']=='lease_exhausted' and progress>.003, 'No useful measured progress in '+phase)
        raise RuntimeError('Bounded pose lease did not reach '+phase)
    def move(target, quaternion, grip, phase):
        target = np.array(target,dtype=float).tolist()
        K['pending'] = phase; save()
        fields = {'external':['observed','none_visible','unknown'],'visibility':['local_visible','self_occluded','unobserved'],'up_view':['supported','unsupported','unknown']}
        for trial in range(2):
            r = review('Assess the proposed bounded pose-feedback action. external=observed means a visible external obstacle blocks it (exclude intentional package contact for grasp); none_visible means no blocking external object is observed, NOT certified clearance; unknown means obstruction evidence cannot be interpreted. visibility=local_visible means useful local approach evidence, self_occluded means missing evidence is due to robot/held item, unobserved means relevant space is otherwise unseen. Consider measured reference geometry and current local scene, not a requirement to see the entire later transfer corridor. up_view=supported only if current visible surroundings justify a 0.025 m upward observation move keeping grip and orientation. Do not call self-occlusion an external obstacle. Check package identity and report observed ejection or dangerous interference in explanation.', fields, {'task':task,'phase':phase,'target_pad_world_m':target,'current_pad_world_m':geo.pad_position(api.state()).tolist(),'geometry':K['geometry'],'last':K.get('last')})
            p = r['parameters']
            need(p['external']!='observed', 'Observed external obstruction during '+phase)
            if p['external']=='none_visible' and p['visibility'] in ['local_visible','self_occluded']:
                deliver(target,quaternion,grip,phase); return
            need(trial==0 and p['up_view']=='supported', 'No justified local progress or useful view action during '+phase)
            s = api.state(); up = geo.pad_position(s)+np.array([0,0,.025])
            deliver(up.tolist(),s['tcp_quaternion_xyzw'],'keep','upward observation')
            if 2<=K.get('phase',0)<7:
                o = observe(); retention(K['last'],o,False); K['last']=o; save()
        raise RuntimeError('Unresolved local observation gap')
    def grip(command):
        K['pending'] = command; save()
        for i in range(3):
            s = api.state(); need(s['budgets']['jev_remaining']>4, 'Gripper control reserve exhausted')
            r = api.control(geo.pad_position(s).tolist(),s['tcp_quaternion_xyzw'],command,Q,features={'phase':command,'object_effect':'unverified'},tool_point='pad_center',steps=3,position_tolerance=.002,rotation_tolerance=.04)
            log('gripper', {'command':command,'status':r['status'],'frame_id':r['frame_id']})
            need(r['status'] in ['reached','moved'], 'Gripper pose control stalled')
    def retention(before, after, probe):
        A, B = np.array(before['points']), np.array(after['points'])
        error = geo.attachment_error(A,B,before['state'],after['state'])
        dz = float(np.mean(B[:4,2]-A[:4,2])); hand = float(geo.pad_position(after['state'])[2]-geo.pad_position(before['state'])[2])
        uncertainty = before['u']+after['u']; limit = 2*uncertainty+.003
        log('retention_test', {'attachment_error_m':error,'limit_m':limit,'object_dz_m':dz,'hand_dz_m':hand,'combined_u_m':uncertainty,'probe':probe})
        need(uncertainty<=.012 and error<=limit, 'Observed object motion is not sufficiently consistent with actual hand motion')
        if probe: need(hand>.025 and dz>max(.018,2*uncertainty), 'Lift did not independently demonstrate retained load')
    def finish_phase(number, observation=None):
        K['phase']=number; K['pending']=''
        if observation is not None: K['last']=observation
        save()
    def held_move(target, phase, number):
        before=K['last']; move(target,K['geometry']['quaternion'],'keep',phase)
        after=observe(); retention(before,after,False); finish_phase(number,after)
    try:
        existing = [m for m in api.recall() if m['key']=='package_bowl_episode']
        if existing:
            K.update(api.recall('package_bowl_episode')['value']); task=K['task']
            log('repair_history', {'phase':K['phase'],'pending':K['pending'],'reference_frame_id':K['reference_frame_id']})
            if K['pending']=='open' and api.state()['last_gripper_command']=='open': K['phase']=7
            if K['pending']=='close' and api.state()['last_gripper_command']=='close': K['phase']=2
            if K['phase']<7:
                current=observe()
                if 3<=K['phase']<7: retention(K['last'],current,False)
                if K['phase']!=2: K['last']=current
            save()
        else:
            f=dict(patch_fields); f.update({'identity':['confirmed','unknown'],'support':['flat_supported_package','unknown'],'corners':{'type':'array','items':pixel,'minItems':4,'maxItems':4},'labels':{'type':'array','items':{'type':'string'},'minItems':7,'maxItems':7}})
            r=review('Runtime instruction: '+task+'. Identify the requested package and bowl. identity=confirmed only if identities are clear. support=flat_supported_package requires visible side and flat table support evidence, not a guessed hidden underside. In camera, give four visible top corners in cyclic order as corners, and a textured top-only polygon (or []). Define persistent physical labels p0..p3 for those corners and p4..p6 for three well-spaced identifiable printed interior marks; labels must use physical printing/package features, not screen directions. Request named points p4,p5,p6 on those marks and side on a visible vertical package side. Request named regions top and table as interior-only rectangles with explicit camera, box, stride=4; table must be the support beside the package. Request b0..b5 distributed on the bowl INNER lip and floor on its visible central interior bottom. Avoid adjacent surfaces and omit unmeasurable points.', f)
            p=points(r,['p4','p5','p6','side']); params=r['parameters']
            need(params['identity']=='confirmed' and params['support']=='flat_supported_package' and len(p)==4, 'Package identity, support, side, or reference landmarks unavailable')
            top, table=geo.plane(region(r,'top')),geo.plane(region(r,'table'))
            log('surface_fits', {'top':top,'table':table})
            need(top['coefficients'][2]>.97 and table['coefficients'][2]>.97 and max(top['rms_m'],table['rms_m'])<.0025, 'Top/table planar horizontal model unsupported')
            C=np.array([api.plane_point(params['camera'],v,top['coefficients'])['world_m'] for v in params['corners']]); c=C.mean(axis=0)
            a,b=C[1]-C[0],C[3]-C[0]; lengths=[float(np.linalg.norm(a)),float(np.linalg.norm(b))]
            u=max(.002,2*top['rms_m'],2*table['rms_m']); co=table['coefficients']; tablez=float(-(co[0]*c[0]+co[1]*c[1]+co[3])/co[2]); height=float(c[2]-tablez)
            need(min(lengths)>4*u and abs(float(a@b))/max(1e-9,lengths[0]*lengths[1])<.15 and np.linalg.norm(C[0]+C[2]-C[1]-C[3])<.006, 'Visible top boundaries do not support a rectangular package')
            need(height>3*u and tablez-u<=p['side'][2]<=c[2]+u, 'Package height/support is inconsistent with the visible side')
            for name in ['p4','p5','p6']: need(abs(float(np.array(top['coefficients'][:3])@np.array(p[name])+top['coefficients'][3]))<.004,'Interior landmark depth disagrees with top plane')
            B=bowl(r); s=api.state(); own=s['own_geometry']; ext=np.array(own['pad_extent_in_tool_m']); R=geo.rotation(s['tcp_quaternion_xyzw'])
            need(int(np.argmax(ext))==1, 'Opening-axis interpretation unsupported by supplied pad geometry')
            short=a if lengths[0]<lengths[1] else b; angle=math.atan2(short[1],short[0])-math.atan2(R[1,1],R[0,1]); angle=(angle+math.pi/2)%math.pi-math.pi/2
            q=s['tcp_quaternion_xyzw'] if abs(angle)<.08 else api.compose(s['tcp_quaternion_xyzw'],[0,0,angle]); R=geo.rotation(q)
            sep=abs(s['gripper_qpos_m'][0]-s['gripper_qpos_m'][1]); pad_thickness=max(0,float(ext[1])-sep); gap=sep-pad_thickness
            offsets=np.array([[x,y,z] for x in [own['finger_low_offset_tool_m'][0],own['finger_high_offset_tool_m'][0]] for y in [own['finger_low_offset_tool_m'][1],own['finger_high_offset_tool_m'][1]] for z in [own['finger_low_offset_tool_m'][2],own['finger_high_offset_tool_m'][2]]])
            low=float(np.min(((offsets-np.array(own['pad_center_in_tool_m']))@R.T)[:,2])); halfpad=float(np.abs(R[2])@ext/2)
            graspz=max(float(c[2])-min(height/2,.75*halfpad),tablez-low+u+.002); overlap=min(float(c[2]),graspz+halfpad)-max(tablez,graspz-halfpad)
            width=float(np.max(C@R[:,1])-np.min(C@R[:,1])); radius=float(np.max(np.linalg.norm(C[:,:2]-c[:2],axis=1)))
            log('grasp_geometry', {'height_m':height,'opening_gap_estimate_m':gap,'package_span_m':width,'uncertainty_m':u,'grasp_pad_z_m':graspz,'finger_min_relative_pad_m':low,'side_overlap_m':overlap,'package_radius_m':radius,'bowl_radius_m':B['radius']})
            need(abs(R[2,1])<.15 and gap>width+2*(u+.002) and overlap>2*u and B['radius']>radius+2*(u+B['u']), 'Measured grasp clearance, side overlap, or bowl opening margin insufficient')
            reference=C.tolist()+[p['p4'],p['p5'],p['p6']]
            G={'height':height,'radius':radius,'u':u,'table_z':tablez,'top_z':float(c[2]),'grasp_delta_z':graspz-float(c[2]),'finger_low':low,'quaternion':q,'bowl':B,'safe_z':max(float(c[2]),B['z'])+max(-low,height+graspz-float(c[2]))+.045}
            K.update({'task':task,'phase':0,'pending':'','geometry':G,'labels':params['labels'],'reference':reference,'reference_frame_id':r['frame_id'],'last':{'points':reference,'u':u,'state':s,'frame_id':r['frame_id'],'source':'measured top plane, visible landmarks, calibrated visible-boundary intersections'}}); save(); init_patch(params,reference)
        G=K['geometry']; B=G['bowl']; q=G['quaternion']
        if K['phase']==0:
            need(api.state()['last_gripper_command']=='open','Pregrasp state is not confirmed open; refusing an automatic reopen')
            c=np.mean(np.array(K['last']['points'])[:4],axis=0); move([float(c[0]),float(c[1]),G['safe_z']],q,'open','approach above package')
            o=observe(); c=np.mean(np.array(o['points'])[:4],axis=0); K['last']=o; save()
            move([float(c[0]),float(c[1]),float(c[2])+G['grasp_delta_z']],q,'open','straddle package sides')
            finish_phase(1,observe())
        if K['phase']==1:
            grip('close'); finish_phase(2)
            r=review('Inspect the actual closure effect, not command success. effect=plausible means the intended package is between side pads without visible ejection; self_occluded means outline is hidden by fingers but no contradictory effect is visible; miss means visibly missed/ejected; unknown means identity/effect cannot be interpreted. This is permission for a small retention-measurement lift, NOT a retained-load claim.',{'effect':['plausible','self_occluded','miss','unknown']},{'labels':K['labels'],'preclosure':K['last']})
            need(r['parameters']['effect'] in ['plausible','self_occluded'],'Closure effect does not justify a retention probe')
        if K['phase']==2:
            before=K['last']; target=geo.pad_position(api.state())+np.array([0,0,.045]); move(target,q,'keep','retention probe lift')
            o=observe(); retention(before,o,True); finish_phase(3,o)
        if K['phase']==3:
            p=geo.pad_position(api.state()); held_move([float(p[0]),float(p[1]),max(float(p[2]),G['safe_z'])],'raise for transfer',4)
        if K['phase']==4:
            p=geo.pad_position(api.state()); c=np.mean(np.array(K['last']['points'])[:4],axis=0)
            held_move([float(p[0]+B['xy'][0]-c[0]),float(p[1]+B['xy'][1]-c[1]),max(float(p[2]),G['safe_z'])],'transfer above bowl',5)
        if K['phase']==5:
            for i in range(2):
                P=np.array(K['last']['points'])[:4]; c=P.mean(axis=0); p=geo.pad_position(api.state())
                need(geo.plane(P)['coefficients'][2]>.96,'Package tilted beyond measured horizontal placement model')
                z=max(B['z']+.007+float(p[2]-c[2])+G['height'],B['z']+.007-G['finger_low'])
                held_move([float(p[0]+B['xy'][0]-c[0]),float(p[1]+B['xy'][1]-c[1]),z],'center and lower above inner rim',5)
                P=np.array(K['last']['points'])[:4]; c=P.mean(axis=0)
                if np.linalg.norm(c[:2]-np.array(B['xy']))<.004: break
            p=geo.pad_position(api.state()); edge=float(np.max(np.linalg.norm(P[:,:2]-np.array(B['xy']),axis=1))); bottom=float(c[2])-G['height']
            log('release_geometry',{'farthest_corner_radius_m':edge,'opening_radius_m':B['radius'],'bottom_above_rim_m':bottom-B['z'],'finger_above_rim_m':float(p[2])+G['finger_low']-B['z']})
            need(edge+K['last']['u']+B['u']<B['radius'] and -.002<bottom-B['z']<.03 and float(p[2])+G['finger_low']>B['z']+.002,'Release footprint or rim clearance remains unresolved')
            finish_phase(6)
        if K['phase']==6: grip('open'); finish_phase(7)
        if K['phase']==7:
            move(geo.pad_position(api.state())+np.array([0,0,.09]),q,'keep','retreat after release'); finish_phase(8)
        results=[]
        for trial in range(2):
            if trial:
                for j in range(2):
                    s=api.state(); rr=api.control(geo.pad_position(s).tolist(),s['tcp_quaternion_xyzw'],'keep',Q,features={'phase':'post-release stability interval'},tool_point='pad_center',steps=3)
                    need(rr['status'] in ['reached','moved'],'Post-release holding control stalled')
            r=review('Assess actual task outcome after release and retreat. relation=inside only if the requested package is inside the bowl opening, not on the lip or beside it. support=resting means visibly supported by the bowl and separated from the gripper; moving means still falling/sliding; unknown is unresolved. identity=confirmed requires the same requested package and bowl. Request every visible corresponding p0..p6 using saved physical definitions, preferring interior p4..p6. Also request current b0..b5 on the inner rim and floor on visible interior bottom; omit floor if package now occludes it. These are fresh observations, not projected historical points.',{'relation':['inside','outside','unknown'],'support':['resting','moving','unknown'],'identity':['confirmed','unknown']},{'task':task,'labels':K['labels'],'reference':K['reference'],'reference_frame_id':K['reference_frame_id']},final=True)
            p=points(r,['p'+str(i) for i in range(7)]+['b'+str(i) for i in range(6)])
            results.append({'parameters':r['parameters'],'points':p,'frame_id':r['frame_id'],'native_steps':api.state()['native_steps']})
            K['final_observations']=results; save()
        ids=[n for n in results[0]['points'] if n.startswith('p') and n in results[1]['points']]
        need(len(ids)>=2,'Post-release stability lacks two independently reobserved corresponding package landmarks')
        drift=max(float(np.linalg.norm(np.array(results[0]['points'][n])-np.array(results[1]['points'][n]))) for n in ids)
        rim=np.array([results[1]['points']['b'+str(i)] for i in range(6) if 'b'+str(i) in results[1]['points']])
        need(len(rim)>=5,'Final containment needs a current observed opening, not a stale bowl center')
        ci=geo.circle_xy(rim); pl=geo.plane(rim)
        inside_points=all(np.linalg.norm(np.array(results[1]['points'][n][:2])-np.array(ci['center_xy_m']))<ci['radius_m']+.003 for n in ids)
        success=all(x['parameters']=={'relation':'inside','support':'resting','identity':'confirmed'} for x in results) and drift<=.006 and inside_points and ci['max_radial_error_m']<.004 and ci['largest_angular_gap_rad']<math.pi and pl['rms_m']<.004 and results[1]['native_steps']-results[0]['native_steps']>=6
        log('final_assessment',{'completion_proposed':bool(success),'landmark_motion_m':drift,'final_rim_fit':ci,'observations':results,'limitations':'RGB-D uncertainty floors are heuristic. Stability is observed over a bounded interval, not certified. Hidden underside and a full collision-free corridor were not sensed. Native success evaluation is independent.'})
        finish_phase(9)
        return {'completion_proposed':bool(success),'evidence':E}
    except Exception as ex:
        log('incomplete',{'reason':str(ex),'phase':K.get('phase'),'pending':K.get('pending'),'state':api.state()})
        return {'completion_proposed':False,'evidence':E}

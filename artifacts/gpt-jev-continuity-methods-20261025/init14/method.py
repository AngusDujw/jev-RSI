def main(api):
    task = 'could you put the cream cheese into the bowl'
    D = {}; tol = 0.003
    pix = {'type':'array','items':{'type':'integer','minimum':0,'maximum':767},'minItems':2,'maxItems':2}
    poly = {'type':'array','items':pix,'minItems':0,'maxItems':16}
    definitions = {'type':'array','items':{'type':'string'},'minItems':3,'maxItems':3}
    Q = {}
    for axis in ['x','y','z','rx','ry','rz']:
        selector = 'state.processed_features.axes.' + axis + '.goal_relation'
        Q[axis] = {'type':'choice','instructions':'Control world axis '+axis+'. Read '+selector+'. Follow its semantic direction; do not infer direction from images or other axes.','criteria':{'negative':'Select when '+selector+' is decrease.','hold':'Select when '+selector+' is within_tolerance.','positive':'Select when '+selector+' is increase.'}}
    Q['gripper'] = {'type':'choice','instructions':'Read state.processed_features.objective.gripper and deliver that requested jaw operation unchanged.','criteria':{'open':'The objective requests open.','close':'The objective requests close.','keep':'The objective requests keep; preserve the existing command.'}}
    def log(value):
        D.setdefault('evidence', []).append(value); D['evidence'] = D['evidence'][-18:]; api.note(str(value))
    def require(condition, gap, values=None):
        if not condition:
            log({'gap':gap,'values':values}); raise RuntimeError(gap)
    def save(phase=None):
        if phase is not None: D['phase'] = phase
        api.checkpoint('measured_transfer', D)
    def review(question, fields, context=None):
        require(api.state()['budgets']['gpt_remaining'] > 0, 'No observation-review budget remains')
        r = api.review(question, context=context, fields=fields)
        if r['measurement_errors']: log({'measurement_errors':r['measurement_errors'],'frame_id':r['frame_id']})
        require(r['status'] != 'stop', 'Observation reviewer stopped', r['explanation'])
        return r
    def measured(r, names):
        bad = [e['name'] for e in r['measurement_errors']]
        missing = [n for n in names if n not in r['points'] or n in bad]
        require(not missing, 'Required current surface measurements are unavailable', missing)
        return np.array([r['points'][n]['world_m'] for n in names], dtype=float)
    def finger_offsets(s):
        own = s['own_geometry']; lo = own['finger_low_offset_tool_m']; hi = own['finger_high_offset_tool_m']
        box = np.array([[x,y,z] for x in [lo[0],hi[0]] for y in [lo[1],hi[1]] for z in [lo[2],hi[2]]])
        return (box-np.array(own['pad_center_in_tool_m'])) @ geo.rotation(s['tcp_quaternion_xyzw']).T
    def initialize():
        fields = {'model':['supported_box_and_round_bowl','unknown'],'camera':['agentview','robot0_eye_in_hand'],'corner_pixels':{'type':'array','items':pix,'minItems':4,'maxItems':4},'polygon':poly,'identity':'string','definitions':definitions}
        r = review('Runtime task: '+task+'. Identify its source package and receiving bowl. model=supported_box_and_round_bowl only if the source has a visible rectangular planar top, rests flat at a visible table contact, and the bowl has a round horizontal inner lip; otherwise unknown. camera is the view for corner_pixels (four visible top corners in cyclic order) and polygon (a textured top INTERIOR patch, or [] if unavailable). identity names that physical source surface. definitions are persistent physical descriptions of a0,a1,a2: three spread, noncollinear, uniquely identifiable printed landmarks, not screen-relative corners. Measure named points a0,a1,a2 on those landmarks; base on the visible source lower-side/table contact; b0 through b5 around the bowl INNER lip, spread around its circumference; and floor on the visible interior bottom. Request named regions top and support, each with explicit camera, tightly interior box, stride=4, sampling only the source top and adjacent supporting table respectively. Do not use an outer bowl edge or a mixed boundary-depth sample. All requested parameters have the declared meanings.', fields)
        p = r['parameters']; D['partial_reference'] = {'frame_id':r['frame_id'],'parameters':p,'points':r['points']}; save('measuring')
        require(p['model'] == 'supported_box_and_round_bowl', 'Required shape or visible supporting-contact evidence is missing')
        bad = [e['name'] for e in r['measurement_errors']]
        require(all(n in r['regions'] and n not in bad for n in ['top','support']), 'Missing top or support region', bad)
        top = geo.plane(r['regions']['top']['world_m']); table = geo.plane(r['regions']['support']['world_m'])
        L = measured(r, ['a0','a1','a2']); B = measured(r, ['b0','b1','b2','b3','b4','b5']); base = measured(r,['base'])[0]; floor = measured(r,['floor'])[0]
        bp = geo.plane(B); circle = geo.circle_xy(B); tn = np.array(top['coefficients']); sn = np.array(table['coefficients'])
        fits = {'top_rms_m':float(top['rms_m']),'support_rms_m':float(table['rms_m']),'rim_rms_m':float(bp['rms_m']),'circle_rms_m':float(circle['rms_m']),'rim_gap_rad':float(circle['largest_angular_gap_rad'])}; log(fits)
        require(max(fits['top_rms_m'],fits['support_rms_m'],fits['rim_rms_m'],fits['circle_rms_m']) < 0.003 and min(tn[2],sn[2],bp['coefficients'][2]) > 0.97 and circle['largest_angular_gap_rad'] < math.pi, 'Surface or aperture fits are inadequate', fits)
        C = np.array([api.plane_point(p['camera'],v,tn.tolist())['world_m'] for v in p['corner_pixels']]); center = np.mean(C,axis=0)
        u = max(0.0015,float(top['rms_m'])+float(table['rms_m']),float(bp['rms_m'])+float(circle['rms_m']))
        bottom = -(sn[0]*center[0]+sn[1]*center[1]+sn[3])/sn[2]; height = float(np.min(C[:,2])-bottom)
        require(abs(float(np.dot(sn[:3],base)+sn[3])) < 3*u+0.002 and height > 2*u and np.max(np.abs(L@tn[:3]+tn[3])) < 3*u, 'Visible base, top, or landmark geometry is inconsistent', {'height_m':height,'base_plane_error_m':float(np.dot(sn[:3],base)+sn[3])})
        low = C.copy(); low[:,2] = -(sn[0]*C[:,0]+sn[1]*C[:,1]+sn[3])/sn[2]; V = np.concatenate([C,low])
        edges = [C[1]-C[0],C[3]-C[0]]; lengths = [float(np.linalg.norm(v)) for v in edges]
        require(min(lengths)>4*u and abs(float(np.dot(edges[0],edges[1])))/max(1e-9,lengths[0]*lengths[1]) < 0.15 and np.linalg.norm(C[0]+C[2]-C[1]-C[3]) < 4*u, 'Measured top is not a resolved rectangle', {'edge_lengths_m':lengths})
        s = api.state(); q = s['tcp_quaternion_xyzw']; R = geo.rotation(q); ext = np.array(s['own_geometry']['pad_extent_in_tool_m'])
        joint_span = abs(s['gripper_qpos_m'][0]-s['gripper_qpos_m'][1]); gap = 2*joint_span-ext[1]; margin = 2*u+tol
        width = float(np.ptp(V@R[:,1]))
        if width+2*margin > gap:
            edge = edges[int(lengths[1]<lengths[0])]; a = R[:2,1]; b = edge[:2]; yaw = math.atan2(a[0]*b[1]-a[1]*b[0],float(np.dot(a,b))); yaw = (yaw+math.pi/2)%math.pi-math.pi/2
            q = api.compose(q,[0.0,0.0,float(yaw)]); R = geo.rotation(q); width = float(np.ptp(V@R[:,1]))
        require(R[2,2] < -0.95 and abs(R[2,1]) < 0.12 and width+2*margin <= gap, 'Open pinch geometry is infeasible', {'width_m':width,'conservative_gap_m':float(gap),'margin_m':margin})
        virtual = dict(s); virtual['tcp_quaternion_xyzw'] = q; dz = float(np.min(finger_offsets(virtual)[:,2])); half = float(np.dot(np.abs(R[2]),ext)/2)
        overlap = max(2*u,0.30*min(height,2*half)); lower = max(bottom+overlap-half,bottom-dz+u+tol); upper = float(np.min(C[:,2])-overlap+half)
        require(overlap <= min(height,2*half) and lower <= upper, 'No side-contact band with table clearance', {'pad_z_lower_m':lower,'pad_z_upper_m':upper,'overlap_m':overlap,'finger_low_relative_pad_m':dz})
        grasp = [float(center[0]),float(center[1]),float(max(lower,min((bottom+np.min(C[:,2]))/2,upper)))]; radius = float(circle['radius_m']); rim = float(np.mean(B[:,2]))
        require(float(np.max(np.linalg.norm(V[:,:2]-center[:2],axis=1)))+margin < radius and floor[2] < rim-2*u, 'Measured package does not fit the resolved bowl opening', {'radius_m':radius,'package_radius_m':float(np.max(np.linalg.norm(V[:,:2]-center[:2],axis=1))),'rim_z_m':rim,'floor_z_m':float(floor[2])})
        D['g'] = {'C':C.tolist(),'V':V.tolist(),'landmarks':L.tolist(),'definitions':p['definitions'],'identity':p['identity'],'q':q,'grasp':grasp,'table_plane':sn.tolist(),'bowl_xy':circle['center_xy_m'],'radius':radius,'rim':rim,'floor':floor.tolist(),'u':u,'frame_id':r['frame_id'],'width':width,'bottom':float(bottom),'support_interpretation':'Visible lower-side contact on fitted support; hidden underside is not directly measured.'}
        D['g']['bowl_xy'] = np.array(D['g']['bowl_xy']).tolist()
        if len(p['polygon']) >= 3:
            try:
                tr = api.track_init(p['camera'],p['polygon']); D['track'] = {'receipt':tr,'identity':p['identity'],'polygon':p['polygon'],'base_T':np.eye(4).tolist()}
            except Exception as e: log({'tracker_initialization':str(e),'fallback':'physical landmark correspondence'})
        D.pop('partial_reference',None); save('approach')
    def observe():
        g = D['g']; tr = D.get('track'); M = None; uncertainty = g['u']; provenance = None
        if tr is not None:
            try:
                t = api.track_update(tr['receipt']['handle'])
                if t['status'] == 'tracked':
                    spread = np.array(t['reference_inlier_world_m']); spread = np.linalg.svd(spread-np.mean(spread,axis=0),compute_uv=False)/math.sqrt(max(1,len(spread)))
                    quality = t['inliers'] >= 12 and t['inliers']/max(1,t['matches']) >= 0.55 and t['rms_m'] <= 0.0025 and t['uncertainty_floor_m'] <= 0.0035 and len(spread)>1 and spread[1] >= 0.002 and float(np.max(np.array(t['inlier_spread_m']))) >= 0.005
                    if quality and t['reference_frame_id'] == tr['receipt']['frame_id']:
                        M = np.array(t['transform_initial_world_to_current_world']) @ np.array(tr['base_T']); uncertainty = max(g['u'],float(t['rms_m']+t['uncertainty_floor_m'])); provenance = {'kind':'rgbd_patch','frame_id':t['frame_id'],'reference_frame_id':t['reference_frame_id'],'inliers':t['inliers'],'rms_m':t['rms_m'],'uncertainty_m':uncertainty}
                if M is None: log({'registration':'unknown_or_inadequate','frame_id':t['frame_id'],'reason':t.get('reason','quality gate')})
            except Exception as e: log({'registration_error':str(e)})
        if M is None:
            r = review('Recover CURRENT registration of the saved physical source surface. Historical projections are not detections. identity=matched only when a0,a1,a2 can each be independently identified using the saved physical definitions and reference geometry; otherwise ambiguous. Measure those three named corresponding landmarks from current images. Do not rename screen corners or predict points from hand motion. camera and polygon optionally specify a NEW textured interior patch on that SAME source surface, [] if unavailable. This patch will be initialized only after landmark registration succeeds.', {'identity':['matched','ambiguous'],'camera':['agentview','robot0_eye_in_hand'],'polygon':poly}, {'surface':g['identity'],'definitions':g['definitions'],'reference_world_m':g['landmarks'],'reference_frame_id':g['frame_id'],'phase':D['phase']})
            require(r['parameters']['identity']=='matched','Current physical correspondences remain ambiguous')
            A = np.array(g['landmarks']); B = measured(r,['a0','a1','a2']); X = A-np.mean(A,axis=0); Y = B-np.mean(B,axis=0)
            require(min(np.linalg.svd(X,compute_uv=False)[1],np.linalg.svd(Y,compute_uv=False)[1]) > 0.004,'Landmark registration is poorly constrained')
            U,S,W = np.linalg.svd(X.T@Y); rot = W.T@U.T
            if np.linalg.det(rot)<0: W[-1,:] *= -1; rot = W.T@U.T
            M = np.eye(4); M[:3,:3] = rot; M[:3,3] = np.mean(B,axis=0)-rot@np.mean(A,axis=0); residual = float(np.max(np.linalg.norm(geo.transform(A,M)-B,axis=1)))
            require(residual < 0.004,'Landmark correspondences fail rigid consistency',{'residual_m':residual}); uncertainty = max(0.003,g['u'],residual); provenance = {'kind':'identified_landmarks','frame_id':r['frame_id'],'residual_m':residual,'uncertainty_m':uncertainty}
            if len(r['parameters']['polygon'])>=3:
                try:
                    t = api.track_init(r['parameters']['camera'],r['parameters']['polygon']); D['track'] = {'receipt':t,'identity':g['identity'],'polygon':r['parameters']['polygon'],'base_T':M.tolist()}; save()
                except Exception as e: log({'replacement_patch_error':str(e)})
        require(uncertainty <= 0.005,'Registration uncertainty is too large',provenance)
        o = {'points':geo.transform(g['landmarks'],M).tolist(),'C':geo.transform(g['C'],M).tolist(),'V':geo.transform(g['V'],M).tolist(),'u':uncertainty,'provenance':provenance}; D['last_observation'] = o; return o
    def move(target, label, reserve=4):
        target = np.array(target,dtype=float); views = 0
        for k in range(18):
            s = api.state(); p = geo.pad_position(s); d = target-p; distance = float(np.linalg.norm(d)); q = D['g']['q']; angle = 2*math.acos(min(1.0,abs(float(np.dot(q,s['tcp_quaternion_xyzw'])))))
            if distance <= tol and angle <= 0.05: return
            require(s['budgets']['gpt_remaining']>reserve and s['budgets']['jev_remaining']>max(8,4*reserve),'Insufficient reserved resources for a bounded local leg',s['budgets'])
            dest = p+d*min(1.0,0.10/max(distance,1e-9)); context = {'task':task,'phase':label,'pad_world_m':p.tolist(),'next_pad_world_m':dest.tolist(),'orientation_xyzw':q,'finger_offsets_world_m':finger_offsets(s).tolist(),'source_identity':D['g']['identity'],'support_plane':D['g']['table_plane'],'bowl_xy':D['g']['bowl_xy'],'rim_z_m':D['g']['rim'],'latest_object_observation':D.get('last_observation')}
            r = review('Review ONLY the proposed local leg, not the entire later route. obstruction=external means a visible external object intersects the proposed hand/item motion (ordinary source contact is allowed only during jaw closure); none_observed means no external obstruction is observed, NOT certified clearance; unknown means the local evidence cannot distinguish this. visibility=observed_local means useful local scene evidence, self_occluded means the missing region is occluded by this robot or its carried item, unobserved means genuinely unobserved external space. Self-occlusion alone is not an obstacle. For grasp descent, flag a visibly misaligned source outside the open pinch gap as external. up_view=justified only if a separate 18 mm upward view-changing move has phase-local support from the visible scene and known own envelope without an observed obstruction; otherwise unknown or blocked. Do not demand full perimeter visibility or certify a swept volume.', {'obstruction':['external','none_observed','unknown'],'visibility':['observed_local','self_occluded','unobserved'],'up_view':['justified','blocked','unknown']},context)['parameters']
            require(r['obstruction']!='external','Observed external obstruction; no repeated pushing',context)
            if r['obstruction']=='unknown' or r['visibility']=='unobserved':
                sn = np.array(D['g']['table_plane']); lowest = p+finger_offsets(s)[int(np.argmin(finger_offsets(s)[:,2]))]; clearance = float(np.dot(sn[:3],lowest)+sn[3])
                require(views<1 and r['up_view']=='justified' and clearance>0.025,'No justified observation-producing local action',{'review':r,'support_clearance_m':clearance}); views += 1; dest = p+np.array([0,0,0.018])
            elif r['visibility']=='self_occluded': dest = p+d*min(1.0,0.04/max(distance,1e-9))
            D['motion_intent'] = {'phase':label,'pad_target':dest.tolist(),'frame_id':s['frame_id']}; save()
            receipt = api.drive(dest.tolist(),q,'keep',Q,features={'phase':label,'local_evidence':r,'uncertainty_m':D['g']['u']},tool_point='pad_center',translation_limit=0.006 if label in ['descend_grasp','lower_for_release'] else 0.018,rotation_limit=0.08,steps=3,position_tolerance=tol,rotation_tolerance=0.05,max_calls=min(18,max(1,s['budgets']['jev_remaining']-max(8,4*reserve))))
            progress = float(np.linalg.norm(geo.pad_position(api.state())-p)); D['motion_receipt'] = {'status':receipt['status'],'frame_id':receipt['frame_id'],'position_error_m':receipt['position_error_m'],'actual_pad_motion_m':progress}; save()
            require(receipt['status']!='stalled','Local controller stalled; contact is not repeatedly pushed',D['motion_receipt'])
            require(receipt['status']=='reached' or progress>0.002,'Pose lease exhausted without useful progress',D['motion_receipt'])
        require(False,'Local route bound exhausted',{'remaining_m':float(np.linalg.norm(target-geo.pad_position(api.state())))})
    def jaw(command):
        save('close_intent' if command=='close' else 'release_intent')
        for i in range(4):
            s = api.state(); r = api.control(geo.pad_position(s).tolist(),s['tcp_quaternion_xyzw'],command,Q,features={'phase':D['phase'],'purpose':'jaw delivery, not proof of object effect'},tool_point='pad_center',translation_limit=0.005,rotation_limit=0.05,steps=3,position_tolerance=tol,rotation_tolerance=0.05)
            D['jaw_receipt'] = {'choice':r['choices']['gripper'],'acknowledged_steps':r['acknowledged_steps'],'frame_id':r['frame_id'],'status':r['status']}
            if r['choices']['gripper']==command and r['acknowledged_steps']>0: save('possible_holding' if command=='close' else 'released')
            else: save(); require(False,'Jaw request was not acknowledged as requested',D['jaw_receipt'])
            require(r['status']!='stalled' and (r['status']=='reached' or r['position_error_m']<0.008),'Unexpected motion during jaw transition',D['jaw_receipt'])
    def retained(o):
        h = D['hold']; error = float(geo.attachment_error(h['points'],o['points'],h['state'],api.state())); limit = 0.004+h['u']+o['u']
        log({'attachment_error_m':error,'limit_m':limit,'observation':o['provenance']}); require(error <= limit,'Measured package motion no longer agrees with hand motion'); return o
    def release_check(o):
        g = D['g']; V = np.array(o['V']); radial = float(np.max(np.linalg.norm(V[:,:2]-np.array(g['bowl_xy']),axis=1))); bottom = float(np.min(V[:,2])); values = {'outer_radius_m':radial,'opening_radius_m':g['radius'],'bottom_above_rim_m':bottom-g['rim'],'uncertainty_m':o['u']}; log({'release_geometry':values})
        require(radial+o['u']<g['radius'] and 0.001 <= bottom-g['rim'] <= 0.04,'Actual pre-release geometry does not support a contained low drop',values)
    try:
        if any(m['key']=='measured_transfer' for m in api.recall()): D = api.recall('measured_transfer')['value']
        require(not D or D.get('task',task)==task,'Checkpoint belongs to a different runtime task'); D['task'] = task
        if D.get('phase') in [None,'measuring']:
            require(api.state()['last_gripper_command']=='open','Unclassified initial jaw state; refusing to reopen a potentially held object'); initialize()
        g = D['g']
        if D['phase']=='approach':
            o = observe(); shift = np.mean(np.array(o['C'])-np.array(g['C']),axis=0); require(float(np.max(np.linalg.norm(np.array(o['C'])-np.array(g['C']),axis=1)))<0.006,'Source moved enough to invalidate saved approach geometry')
            grasp = np.array(g['grasp'])+shift; p = geo.pad_position(api.state()); move([grasp[0],grasp[1],max(p[2],grasp[2]+0.07)],'above_source'); move([grasp[0],grasp[1],grasp[2]+0.05],'source_hover'); move(grasp,'descend_grasp')
            o = observe(); require(float(np.linalg.norm(np.mean(np.array(o['C']),axis=0)[:2]-geo.pad_position(api.state())[:2]))<0.012,'Source shifted out of the planned pinch'); jaw('close')
        if D['phase']=='close_intent': jaw('close')
        if D['phase']=='possible_holding':
            o = observe(); s = api.state(); D['test'] = {'points':o['points'],'u':o['u'],'state':s,'target':(geo.pad_position(s)+np.array([0,0,0.035])).tolist(),'provenance':o['provenance']}; save('testing')
        if D['phase']=='testing':
            test = D['test']; move(test['target'],'retention_test'); o = observe(); s = api.state(); error = float(geo.attachment_error(test['points'],o['points'],test['state'],s)); hand = float(geo.pad_position(s)[2]-geo.pad_position(test['state'])[2]); obj = float(np.mean(np.array(o['points'])[:,2]-np.array(test['points'])[:,2])); limit = 0.004+test['u']+o['u']
            log({'retention_test':{'actual_hand_lift_m':hand,'observed_object_lift_m':obj,'attachment_error_m':error,'limit_m':limit,'provenance':o['provenance']}}); require(hand>0.022 and obj>0.018 and error<=limit,'Retention test failed or remained uncertain; not transferring or reopening')
            D['hold'] = {'points':o['points'],'u':o['u'],'state':s,'provenance':o['provenance']}; save('transfer')
        if D['phase']=='transfer':
            o = retained(observe()); p = geo.pad_position(api.state()); low = float(np.min(np.array(o['V'])[:,2])); release_z = g['rim']+max(float(p[2]-low),-float(np.min(finger_offsets(api.state())[:,2])))+g['u']+0.007; safe_z = max(float(p[2]),release_z+0.04)
            move([p[0],p[1],safe_z],'raise_above_rim'); o = retained(observe()); p = geo.pad_position(api.state()); c = np.mean(np.array(o['C']),axis=0); xy = p[:2]+np.array(g['bowl_xy'])-c[:2]; move([xy[0],xy[1],safe_z],'transfer_over_bowl')
            for attempt in range(2):
                o = retained(observe()); p = geo.pad_position(api.state()); c = np.mean(np.array(o['C']),axis=0); xy = p[:2]+np.array(g['bowl_xy'])-c[:2]; low = float(np.min(np.array(o['V'])[:,2])); z = g['rim']+max(float(p[2]-low),-float(np.min(finger_offsets(api.state())[:,2])))+g['u']+0.007
                move([xy[0],xy[1],z],'lower_for_release'); o = retained(observe())
                if np.linalg.norm(np.mean(np.array(o['C']),axis=0)[:2]-np.array(g['bowl_xy']))<=tol+o['u']: break
            release_check(o); save('release_ready')
        if D['phase'] in ['release_ready','release_intent']:
            if D['phase']=='release_intent' and api.state()['last_gripper_command']=='open': save('released')
            else: release_check(retained(observe())); jaw('open')
        if D['phase'] in ['released','verified']:
            if 'retreat_target' not in D: D['retreat_target'] = (geo.pad_position(api.state())+np.array([0,0,0.075])).tolist(); save()
            move(D['retreat_target'],'post_release_view',reserve=1)
            for attempt in range(2):
                first = observe(); start = api.state()
                for j in range(3):
                    s = api.state(); r = api.control(geo.pad_position(s).tolist(),s['tcp_quaternion_xyzw'],'keep',Q,features={'phase':'released_settling','purpose':'independent stability observation interval'},tool_point='pad_center',translation_limit=0.005,rotation_limit=0.05,steps=3,position_tolerance=tol,rotation_tolerance=0.05)
                    require(r['status']!='stalled' and r['position_error_m']<0.008,'Unexpected robot motion while observing released placement')
                last = observe(); drift = float(np.max(np.linalg.norm(np.array(last['points'])-np.array(first['points']),axis=1))); V = np.array(last['V']); radial = float(np.max(np.linalg.norm(V[:,:2]-np.array(g['bowl_xy']),axis=1))); bottom = float(np.min(V[:,2])); elapsed = api.state()['native_steps']-start['native_steps']
                result = review('Assess the actual runtime goal after release from CURRENT images. relation=inside_supported only if the identified cream-cheese package is resting inside the intended bowl, not balanced on its rim, still held, or beside it; rim_or_hand_supported and outside mean those observed alternatives, unknown means evidence is insufficient. separation=separated means a visible gap between hand and source; contact means contact is visible; unknown means unresolved. Saved geometry and measured drift are supporting evidence, not proof of task success. Occluded bottom surfaces alone do not imply failure, but do not invent support.', {'relation':['inside_supported','rim_or_hand_supported','outside','unknown'],'separation':['separated','contact','unknown']},{'task':task,'identity':g['identity'],'observed_drift_m':drift,'interval_native_steps':elapsed,'current_geometry':last,'bowl_xy':g['bowl_xy'],'rim_z_m':g['rim']})['parameters']
                evidence = {'final_review':result,'observed_drift_m':drift,'interval_native_steps':elapsed,'outer_radius_m':radial,'opening_radius_m':g['radius'],'lowest_measured_model_vertex_z_m':bottom,'rim_z_m':g['rim'],'uncertainty_m':last['u'],'uncertainty_status':'heuristic, not a calibrated confidence bound'}; log(evidence)
                success = result['relation']=='inside_supported' and result['separation']=='separated' and drift<=max(0.003,first['u']+last['u']) and radial<g['radius']+last['u'] and bottom<g['rim']+last['u'] and elapsed>=6
                if success: save('verified'); return {'completion_proposed':True,'evidence':D['evidence']}
                if attempt==0 and result['relation']=='unknown': move((geo.pad_position(api.state())+np.array([0.035,0,0.015])).tolist(),'alternate_post_release_view',reserve=1)
                else: break
            save('released'); return {'completion_proposed':False,'evidence':D['evidence']+['Released placement is unresolved or does not satisfy the observed goal; no automatic regrasp.']}
        return {'completion_proposed':False,'evidence':D.get('evidence',[])+['Unresolved phase: '+str(D.get('phase'))]}
    except Exception as e:
        log({'stopped':str(e),'phase':D.get('phase','uninitialized')})
        try: save()
        except Exception as checkpoint_error: api.note('Checkpoint unavailable: '+str(checkpoint_error))
        return {'completion_proposed':False,'evidence':D.get('evidence',[]),'phase':D.get('phase','uninitialized'),'limitation':str(e)}

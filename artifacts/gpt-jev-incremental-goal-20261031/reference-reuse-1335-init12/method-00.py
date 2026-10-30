def main(api):
    E, P, M = [], {}, {}
    tr = {'handle': None, 'base': np.eye(4), 'u': 0.0, 'frame': None}
    pixel = {'type':'array','items':{'type':'integer','minimum':0,'maximum':767},'minItems':2,'maxItems':2}
    polygon = {'type':['array','null'],'items':pixel,'minItems':3,'maxItems':16}
    cameras = ['agentview','robot0_eye_in_hand']
    Q = {}
    for a in ['x','y','z','rx','ry','rz']:
        Q[a] = {'type':'choice','instructions':'Control world axis '+a+'. Read state.processed_features.axes.'+a+'.goal_relation. Select positive for increase, negative for decrease, and hold for within_tolerance. Rotation signs are world rotation-vector signs.', 'criteria':{'negative':'The selected axis requires decrease.','hold':'The selected axis is within_tolerance.','positive':'The selected axis requires increase.'}}
    Q['gripper'] = {'type':'choice','instructions':'Read state.processed_features.objective.gripper and deliver that exact requirement. Pose arrival is not contact evidence.','criteria':{'open':'The objective requests open.','close':'The objective requests close.','keep':'The objective requests keep.'}}
    def require(ok, text):
        if not ok: raise RuntimeError(text)
    def save():
        api.checkpoint('phase', P)
    def review(text, fields, context=None, points=(), regions=()):
        ctx = {} if context is None else context
        for attempt in range(2):
            require(api.state()['budgets']['gpt_remaining'] > 0, 'No observation-review budget remains.')
            r = api.review(text, context=ctx, fields=fields)
            E.append({'review':text[:75],'frame':r['frame_id'],'measurement_errors':r['measurement_errors']})
            require(r['status'] != 'stop', 'Observation review stopped: '+r['explanation'])
            missing = [n for n in points if n not in r['points']] + [n for n in regions if n not in r['regions']]
            if not missing: return r
            ctx = {'prior_context':context,'previous_parameters':r['parameters'],'missing':missing,'errors':r['measurement_errors']}
            text = 'Replace the failed measurements using a usable current view; preserve physical landmark identities. '+text
        raise RuntimeError('Required RGB-D measurements absent: '+str(missing))
    def xyz(r, names):
        return np.array([r['points'][n]['world_m'] for n in names], dtype=float)
    def pz(plane, xy):
        return float(-(plane[0]*xy[0]+plane[1]*xy[1]+plane[3])/plane[2])
    def init_patch(camera, poly, base, uncertainty):
        tr['handle'] = None
        if poly is None: return
        try:
            t = api.track_init(camera, poly)
            require(t['reference_features'] >= 12, 'Insufficient reference texture.')
            tr.update({'handle':t['handle'],'base':np.array(base),'u':uncertainty,'frame':t['frame_id']})
            E.append({'patch_frame':t['frame_id'],'features':t['reference_features']})
        except Exception as ex: E.append({'patch_unavailable':str(ex)})
    def observed():
        if tr['handle'] is not None:
            t = api.track_update(tr['handle'])
            if t['status'] == 'tracked':
                u = max(M['u'],float(t['rms_m']),float(t['uncertainty_floor_m'])) + tr['u']
                good = t['reference_frame_id'] == tr['frame'] and t['inliers'] >= 12 and t['inliers']/max(1,t['matches']) >= 0.55
                good = good and t['rms_m'] <= 0.003 and u <= 0.006 and float(np.max(np.asarray(t['inlier_spread_m']))) >= 4*M['u']
                if good:
                    T = np.array(t['transform_initial_world_to_current_world']) @ tr['base']
                    return {'T':T.tolist(),'u':u,'state':api.state(),'frame':t['frame_id'],'source':'RGB-D rigid patch registration'}
                E.append({'registration_rejected':{'inliers':t['inliers'],'matches':t['matches'],'rms_m':t['rms_m'],'uncertainty_m':u}})
            else: E.append({'registration_unknown':t['reason'],'frame':t['frame_id']})
        f = {'identity':['unique','ambiguous','unknown'],'camera':cameras,'polygon':polygon}
        r = review('Registration recovery: independently identify the SAME physical l0,l1,l2 texture landmarks using the saved semantic definitions and reference measurements. Request named current depth points l0,l1,l2, from either usable camera. Do not use historical projections as detections or redefine labels by screen position. identity=unique only for unambiguous correspondence. Also supply camera and polygon for a currently visible interior textured patch on this same object, or polygon=null. Use English ASCII.', f, {'definitions':M['definitions'],'reference_landmarks':M['landmarks'],'reference_frame':M['frame'],'object':M['object']}, points=('l0','l1','l2'))
        require(r['parameters']['identity'] == 'unique', 'Unknown registration: independent physical landmark correspondence is ambiguous; attachment cannot be assumed.')
        A, B = np.array(M['landmarks']), xyz(r,['l0','l1','l2'])
        require(float(np.linalg.svd(B-B.mean(axis=0),compute_uv=False)[1]) > 3*M['u'], 'Current landmarks do not constrain rigid motion adequately.')
        ac, bc = A.mean(axis=0), B.mean(axis=0)
        U, S, V = np.linalg.svd((A-ac).T @ (B-bc)); R = V.T @ U.T
        if np.linalg.det(R) < 0: V[-1,:] *= -1; R = V.T @ U.T
        T = np.eye(4); T[:3,:3] = R; T[:3,3] = bc-R@ac
        err = float(np.max(np.linalg.norm(geo.transform(A,T)-B,axis=1)))
        E.append({'landmark_registration_error_m':err,'frame':r['frame_id']})
        require(err <= 3*M['u'], 'Corresponding landmarks do not support a rigid registration.')
        u = max(0.002,2*M['u'],err)
        init_patch(r['parameters']['camera'],r['parameters']['polygon'],T,u)
        return {'T':T.tolist(),'u':u,'state':api.state(),'frame':r['frame_id'],'source':'independently remeasured semantic landmarks'}
    def obj(sample, bottom=False):
        return geo.transform(np.array(M['bottom'] if bottom else M['corners']),np.array(sample['T']))
    def retained(a, b, probe=False):
        A, B = obj(a), obj(b)
        error = float(geo.attachment_error(A,B,a['state'],b['state']))
        hand = geo.pad_position(b['state'])-geo.pad_position(a['state']); motion = B.mean(axis=0)-A.mean(axis=0)
        tolerance = max(0.004,2*(a['u']+b['u'])+M['tol'])
        E.append({'attachment_error_m':error,'threshold_m':tolerance,'hand_motion_m':hand.tolist(),'observed_object_motion_m':motion.tolist(),'probe':probe})
        require(error <= tolerance, 'Observed object motion is inconsistent with actual hand motion; retain grip and stop.')
        if probe:
            require(hand[2] >= max(0.020,5*(a['u']+b['u'])) and motion[2] >= 0.65*hand[2], 'Retention lift did not produce sufficiently resolved independent upward object motion.')
            require(float(np.min(obj(b,True)[:,2])) > M['support_z']+2*b['u'], 'Lift did not establish support separation.')
    def refresh_hold():
        old = P['hold']
        new = old if old['frame'] == api.state()['frame_id'] else observed()
        retained(old,new); P['hold'] = new; save()
        return new
    def move(target, grip, label, reserve=24):
        target = np.array(target,dtype=float)
        f = {'external':['none_seen','observed','uncertain'],'visibility':['observed','partial','self_occluded','unobserved'],'entry':['supported','unsupported','unknown'],'reason':'string'}
        r = review('Assess the proposed local motion, not the entire later task route. external=observed means a visible external obstruction to this motion; none_seen means no such obstruction is observed, NOT certified clearance; uncertain means an apparent external obstruction cannot be identified. visibility distinguishes observed, partial, occlusion by the hand/held item, and unobserved space. entry=supported requires positive local evidence from visible space, measured surfaces and the known robot envelope for bounded progress toward the supplied target. Self-occlusion alone is not an external obstacle. Do not demand every perimeter corner or a global swept-volume certificate. Explain the specific evidence or gap in reason.',f,{'phase':label,'target_pad_world_m':target.tolist(),'quaternion_xyzw':M['q'],'gripper':grip,'source_top_m':M['top_z'],'support_m':M['support_z'],'receiver':M['rim'],'finger_low_relative_pad_m':M['finger_low'],'held_evidence':P.get('stage',0)>=3})
        v = r['parameters']; require(v['external']=='none_seen' and v['visibility']!='unobserved' and v['entry']=='supported', 'Local action not justified: '+str(v))
        P['pending'] = {'label':label,'target_pad':target.tolist(),'gripper':grip}; save()
        for lease in range(2):
            s = api.state(); b = s['budgets']; calls = min(40,int(b['jev_remaining'])-reserve,int(b['native_steps_remaining'])//3-reserve)
            require(calls > 0, 'Insufficient control budget with verification reserve.')
            d = float(np.linalg.norm(target-geo.pad_position(s))); require(d <= 0.59, 'Local target exceeds the API distance bound.')
            receipt = api.drive(target.tolist(),M['q'],grip,Q,features={'phase':label,'geometry_uncertainty_m':M['u'],'direction_meaning':'world residual toward the current pad target'},max_calls=calls,tool_point='pad_center',translation_limit=0.02,rotation_limit=0.10,steps=3,position_tolerance=M['tol'],rotation_tolerance=0.035)
            E.append({'motion':label,'status':receipt['status'],'position_error_m':receipt['position_error_m'],'lease_calls':receipt['lease_calls']})
            require(receipt['status']!='stalled', 'Stalled motion; do not repeatedly push contact. Target and phase are checkpointed.')
            if receipt['status']=='reached': P.pop('pending',None); save(); return
            require(receipt['status']=='lease_exhausted', 'Unexpected drive outcome.')
            require(float(np.linalg.norm(geo.pad_position(api.state())-geo.pad_position(s))) > M['tol'], 'Lease exhausted without useful progress.')
        raise RuntimeError('Bounded pose-feedback leases exhausted.')
    def pulse(grip, label, count=3):
        target = geo.pad_position(api.state()).tolist()
        for k in range(count):
            b = api.state()['budgets']; require(b['jev_remaining'] > 4 and b['native_steps_remaining'] >= 3, 'No budget for contact transition or settling.')
            r = api.control(target,M['q'],grip,Q,features={'phase':label},tool_point='pad_center',translation_limit=0.005,rotation_limit=0.05,steps=3,position_tolerance=M['tol'],rotation_tolerance=0.035)
            require(r['status'] in ['reached','moved'], 'Contact-transition control stalled; inspect rather than push again.')
        E.append({'transition':label,'last_status':r['status'],'frame':r['frame_id']})
    try:
        keys = [x['key'] for x in api.recall()]
        if 'model' in keys:
            M = api.recall('model')['value']; P = api.recall('phase')['value'] if 'phase' in keys else {'stage':0}
            E.append({'resumed_stage':P['stage'],'reference_frame':M['frame'],'historical_not_current':True})
        else:
            fields = {'applicability':['supported_rectangular_package_into_open_round_receiver','unsupported','unknown'],'object':'string','receiver':'string','geometry':['adequate','unknown'],'camera':cameras,'corners':{'type':'array','items':pixel,'minItems':4,'maxItems':4},'definitions':{'type':'array','items':{'type':'string'},'minItems':3,'maxItems':3},'patch_camera':cameras,'patch_polygon':polygon}
            r = review('Interpret the active runtime user instruction, identifying its movable object and receiving object, not a goal inferred solely from appearance. Set applicability. This method supports a rigid rectangular package resting flat on a visible plane and an open approximately horizontal circular receiver. geometry=adequate only if that identity, the flat support relation and visible top perimeter are unambiguous. Supply camera and four cyclic top-face corner pixels, not an object-center depth guess. Request tight named regions top, support and floor using explicit camera, box, stride=4: top is only the flat package top interior; support is adjacent exposed support; floor is a visible low interior receiver surface. Request six distributed inner-rim points r0..r5 at the opening lip, not the outside silhouette. Request three separated noncollinear interior texture landmarks l0,l1,l2 on the package top. definitions must describe their persistent physical printed features, not screen-relative names. Supply patch_camera and an interior textured patch_polygon on the same package, possibly a different camera from the outline; null if unavailable. All text English ASCII.',fields,points=tuple(['r'+str(i) for i in range(6)]+['l0','l1','l2']),regions=('top','support','floor'))
            p = r['parameters']; require(p['applicability']=='supported_rectangular_package_into_open_round_receiver' and p['geometry']=='adequate','Runtime goal or observed geometry is outside this method capability.')
            top = geo.plane(r['regions']['top']['world_m']); support = geo.plane(r['regions']['support']['world_m']); rimpoints = xyz(r,['r'+str(i) for i in range(6)])
            rp = geo.plane(rimpoints); circle = geo.circle_xy(rimpoints)
            u = max(0.001,float(top['rms_m']),float(support['rms_m']),float(rp['rms_m']),float(circle['rms_m']))
            require(u <= 0.003 and min(top['coefficients'][2],support['coefficients'][2],rp['coefficients'][2]) >= 0.98, 'Plane/circular-opening model uncertainty or tilt is too large: '+str({'u':u,'top':top,'support':support,'rim':rp,'circle':circle}))
            C = np.array([api.plane_point(p['camera'],v,top['coefficients'])['world_m'] for v in p['corners']]); center = C.mean(axis=0)
            a, b = C[1]-C[0], C[3]-C[0]; lengths = [float(np.linalg.norm(a)),float(np.linalg.norm(b))]
            require(min(lengths)>6*u and abs(float(a@b))/max(1e-9,lengths[0]*lengths[1])<0.2 and np.linalg.norm(C[0]+C[2]-C[1]-C[3])<5*u,'Top corner geometry does not support the rectangular model: '+str(C.tolist()))
            support_z = pz(support['coefficients'],center[:2]); h = float(center[2]-support_z); tol = max(0.0007,min(0.002,h/8)); margin = 2*u+tol
            rimz = float(np.mean(rimpoints[:,2])); radius = float(circle['radius_m']); floorz = float(np.median(np.array(r['regions']['floor']['world_m'])[:,2]))
            extent = float(np.max(np.linalg.norm(C[:,:2]-center[:2],axis=1)))
            s = api.state(); R = geo.rotation(s['tcp_quaternion_xyzw']); q = s['tcp_quaternion_xyzw']; opening = sum(abs(float(x)) for x in s['gripper_qpos_m'])
            width = float(np.ptp(C@R[:,1])); short = a if lengths[0]<lengths[1] else b
            if width+2*margin > opening:
                v, w = R[:2,1], short[:2]; yaw = math.atan2(float(v[0]*w[1]-v[1]*w[0]),float(v@w)); yaw = (yaw+math.pi/2)%math.pi-math.pi/2
                q = api.compose(q,[0.0,0.0,yaw]); R = geo.rotation(q); width = float(np.ptp(C@R[:,1]))
            g = s['own_geometry']; off = np.array(g['pad_center_in_tool_m']); lo, hi = g['finger_low_offset_tool_m'],g['finger_high_offset_tool_m']
            envelope = np.array([[x,y,z] for x in [lo[0],hi[0]] for y in [lo[1],hi[1]] for z in [lo[2],hi[2]]]); finger_low = float(np.min((envelope-off)@R[2,:]))
            pad_half = float(np.abs(R[2,:])@np.array(g['pad_extent_in_tool_m'])/2); graspz = max(support_z+margin-finger_low,float(center[2])-min(h/3,pad_half/2))
            E.append({'height_m':h,'width_along_opening_m':width,'qpos_opening_coordinate_m':opening,'receiver_radius_m':radius,'object_half_diagonal_m':extent,'margin_m':margin,'grasp_pad_z_m':graspz,'finger_low_relative_pad_m':finger_low})
            require(h>4*u and width+2*margin<opening and extent+margin<radius and floorz<rimz-2*u and circle['largest_angular_gap_rad']<math.pi and circle['max_radial_error_m']<3*u,'Measured grasp/opening/receiver fit is inadequate; see numerical evidence.')
            require(graspz-pad_half<float(center[2])-2*u,'Finger support clearance leaves no resolved side engagement.')
            A = xyz(r,['l0','l1','l2']); require(float(np.linalg.svd(A-A.mean(axis=0),compute_uv=False)[1])>3*u,'Reference texture landmarks have inadequate independent span.')
            require(float(np.max(np.abs(A@np.array(top['coefficients'][:3])+top['coefficients'][3])))<3*u,'Texture landmarks are inconsistent with the measured object top.')
            bottom = C.copy()
            for i in range(4): bottom[i,2] = pz(support['coefficients'],C[i,:2])
            M = {'object':p['object'],'receiver':p['receiver'],'corners':C.tolist(),'bottom':bottom.tolist(),'bottom_source':'Inferred lower bound from observed flat-base support relation, not a hidden underside measurement','landmarks':A.tolist(),'definitions':p['definitions'],'frame':r['frame_id'],'top_plane':top,'support_plane':support,'u':u,'tol':tol,'height':h,'top_z':float(center[2]),'support_z':support_z,'rim':{'center':circle['center_xy_m']+[rimz],'radius':radius,'floor_z':floorz},'q':q,'grasp':[float(center[0]),float(center[1]),graspz],'finger_low':finger_low,'patch_camera':p['patch_camera'],'patch_polygon':p['patch_polygon']}
            P = {'stage':0,'action':'initialized'}; api.checkpoint('model',M); save(); init_patch(p['patch_camera'],p['patch_polygon'],np.eye(4),0.0)
        if P['stage'] < 1:
            if api.state()['frame_id'] != M['frame']:
                c = observed(); require(float(np.max(np.linalg.norm(obj(c)-np.array(M['corners']),axis=1))) < 3*M['u'],'Source moved since the saved pregrasp geometry; a new geometry acquisition is required.')
            high = list(M['grasp']); high[2] = max(float(geo.pad_position(api.state())[2]),M['top_z']+0.09,M['rim']['center'][2]+0.09)
            move(high,'open','above source at conservative height'); pre = list(M['grasp']); pre[2] += 0.04
            move(pre,'open','open-finger pregrasp'); move(M['grasp'],'open','final side-engagement approach')
            P.update({'stage':1,'action':'at grasp'}); save()
        if P['stage'] < 2:
            P['action']='closing'; save(); pulse('close','opposing-finger closure')
            r = review('Observe the actual closure effect. contact=candidate means the intended object is plausibly between opposing pads at the measured side-engagement height, allowing a small retention-measurement lift; it does NOT certify retention. Contact may hide the perimeter. miss means visibly missed or pushed outside the grasp. unknown means even this local lift is unjustified. external=observed means a visible obstruction to a small upward lift, not self-occlusion.',{'contact':['candidate','miss','unknown'],'external':['none_seen','observed','uncertain']},{'object':M['object'],'grasp_pad':M['grasp']})
            require(r['parameters']['contact']=='candidate' and r['parameters']['external']=='none_seen','Closure did not justify a bounded retention trial; do not assume grasp.')
            before = observed(); target = geo.pad_position(before['state']); target[2] += max(0.035,8*before['u'])
            P.update({'stage':2,'action':'probe','probe_before':before,'probe_target':target.tolist()}); save()
        if P['stage'] < 3:
            move(P['probe_target'],'keep','small observation-producing retention lift'); after = observed(); retained(P['probe_before'],after,True)
            P.update({'stage':3,'action':'retained','hold':after}); save()
        if P['stage'] < 4:
            held = refresh_hold(); pad = geo.pad_position(api.state()); bottom_rel = float(np.min(obj(held,True)[:,2])-pad[2]); rim = M['rim']['center']
            high = pad.copy(); high[2] = max(float(pad[2]),rim[2]+0.055-bottom_rel,rim[2]+0.03-M['finger_low'])
            move(high,'keep','raise load above receiver lip'); refresh_hold()
            across = [rim[0],rim[1],float(high[2])]; move(across,'keep','transfer above receiver'); held = refresh_hold()
            pad = geo.pad_position(api.state()); bottom_rel = float(np.min(obj(held,True)[:,2])-pad[2]); releasez = max(rim[2]+max(0.006,3*held['u'])-bottom_rel,rim[2]+2*M['u']+M['tol']-M['finger_low'])
            move([rim[0],rim[1],releasez],'keep','low release hover over opening'); held = refresh_hold()
            reach = float(np.max(np.linalg.norm(obj(held)[:,:2]-np.array(rim[:2]),axis=1)))
            E.append({'release_footprint_radius_m':reach,'opening_radius_m':M['rim']['radius'],'bottom_min_z_m':float(np.min(obj(held,True)[:,2]))})
            require(reach+2*held['u']<M['rim']['radius'],'Observed load is not centered within the receiver opening.')
            P.update({'stage':4,'action':'release ready'}); save()
        if P['stage'] < 5:
            if P.get('action')!='release intent': refresh_hold()
            P['action']='release intent'; save(); pulse('open','release above receiver'); P.update({'stage':5,'action':'released'}); save()
        if 'withdraw_target' not in P:
            withdraw = geo.pad_position(api.state()); withdraw[2] += 0.07; P['withdraw_target']=withdraw.tolist(); save()
        if not P.get('withdrawn',False):
            move(P['withdraw_target'],'open','withdraw for independent placement view',reserve=8); P['withdrawn']=True; save()
        first = observed(); stable = False
        for settling in range(2):
            pulse('keep','unloaded settling observation interval',2); second = observed()
            drift = float(np.max(np.linalg.norm(obj(second)-obj(first),axis=1))); threshold = max(0.003,2*(first['u']+second['u']))
            E.append({'post_release_drift_m':drift,'stability_threshold_m':threshold,'frames':[first['frame'],second['frame']]})
            stable = drift <= threshold
            if stable: break
            first = second
        r = review('Assess the actual runtime goal after release and withdrawal. identity=confirmed only for the instructed object and receiver. relation=inside_resting means the object is supported inside the receiver, not pinched by fingers, bridging the rim, or merely above it; otherwise choose on_rim, outside, or unknown. stability=resting requires visual resting evidence, not elapsed time. Request fresh distributed inner-lip points r0..r5 on the actual receiver to check its current opening; do not assume its old pose. The numerical motion test is separate from this semantic review.',{'identity':['confirmed','unknown'],'relation':['inside_resting','on_rim','outside','unknown'],'stability':['resting','moving','unknown']},{'object':M['object'],'receiver':M['receiver'],'measured_drift_m':drift,'threshold_m':threshold},points=tuple(['r'+str(i) for i in range(6)]))
        rimpoints = xyz(r,['r'+str(i) for i in range(6)]); cp = geo.circle_xy(rimpoints); rp = geo.plane(rimpoints)
        current = obj(second); footprint = float(np.max(np.linalg.norm(current[:,:2]-np.array(cp['center_xy_m']),axis=1))); bottomz = float(np.min(obj(second,True)[:,2])); rimz = float(np.mean(rimpoints[:,2]))
        v = r['parameters']; fit = rp['coefficients'][2]>0.98 and rp['rms_m']<0.003 and cp['max_radial_error_m']<0.006 and cp['largest_angular_gap_rad']<math.pi
        done = bool(stable and fit and footprint+second['u']<cp['radius_m'] and bottomz<rimz-second['u'] and v['identity']=='confirmed' and v['relation']=='inside_resting' and v['stability']=='resting')
        E.append({'final_relation':v,'footprint_radius_m':footprint,'current_opening_radius_m':cp['radius_m'],'inferred_bottom_z_m':bottomz,'current_rim_z_m':rimz,'uncertainty_m':second['u'],'completion_is_proposal_not_official_success':True})
        P.update({'stage':6,'action':'assessed','completion_proposed':done,'final_evidence':E[-2:]}); save()
        return {'completion_proposed':done,'evidence':E}
    except Exception as ex:
        E.append({'gap':str(ex),'phase':P,'current_robot_state':api.state(),'policy':'No reset or automatic reopening; checkpointed measurements are historical, not live state.'})
        api.note(str(ex))
        return {'completion_proposed':False,'evidence':E}

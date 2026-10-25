def main(api):
    E = []; C = {'phase':'new','trials':0,'stage':0,'jaw_calls':0}; M = {}; H = {}; fresh_hold = [-1]
    task = 'could you put the cream cheese into the bowl'
    pixel = {'type':'array','items':{'type':'integer','minimum':0,'maximum':767},'minItems':2,'maxItems':2}
    polygon = {'type':['array','null'],'items':pixel,'minItems':3,'maxItems':16}
    text = {'type':'string','maxLength':240}
    defs3 = {'type':'array','items':text,'minItems':3,'maxItems':3}
    Q = {}
    for axis in ['x','y','z','rx','ry','rz']:
        Q[axis] = {'type':'choice','instructions':'For world axis '+axis+', follow its bound goal_relation only. Increase means positive; decrease means negative; within_tolerance means hold. Do not infer object effects.','criteria':{'negative':'This axis relation is decrease.','hold':'This axis relation is within_tolerance.','positive':'This axis relation is increase.'}}
    Q['gripper'] = {'type':'choice','instructions':'Follow state.processed_features.objective.gripper exactly. This is a command, not evidence of contact.','criteria':{'open':'The objective requests open.','close':'The objective requests close.','keep':'The objective requests keep.'}}
    def log(kind, value):
        E.append({'kind':kind,'value':value}); E[:] = E[-10:]; api.note(str(E[-1]))
    def require(ok, message):
        if not ok: raise ValueError(message)
    def save(): api.checkpoint('phase', C)
    def load(key, default):
        return api.recall(key)['value'] if key in [v['key'] for v in api.recall()] else default
    def review(question, fields, context=None):
        require(api.state()['budgets']['gpt_remaining'] > 0, 'No observation-review budget remains.')
        r = api.review(question, context={'runtime_instruction':task,'data':context}, fields=fields)
        if r['measurement_errors']: log('measurement_errors', r['measurement_errors'])
        require(r['status'] != 'stop', 'Observation review requested stop: '+r['explanation'])
        return r
    def points(r, names):
        return np.array([r['points'][k]['world_m'] for k in names if k in r['points']], dtype=float)
    def quality(handle):
        if handle is None: return None
        try:
            t = api.track_update(handle)
            if t['status'] != 'tracked': log('registration_unknown', t['reason']); return None
            a = np.array(t['reference_inlier_world_m']); u = max(0.0015, float(t['rms_m']), float(t['uncertainty_floor_m']))
            spread = np.linalg.svd(a-a.mean(axis=0), compute_uv=False)/math.sqrt(len(a))
            if t['inliers'] < 12 or t['inliers']/max(1,t['matches']) < 0.55 or t['rms_m'] > 0.0025 or u > 0.004 or spread[1] < 2*u: return None
            t['u'] = u; t['spread'] = float(spread[1]); return t
        except Exception as ex: log('tracker_error', str(ex)); return None
    def patch(camera, poly, identity):
        if poly is None or camera == 'unknown': return None
        try:
            p = api.track_init(camera, poly)
            return {'handle':p['handle'],'frame_id':p['frame_id'],'camera':camera,'polygon':poly,'identity':identity,'method_number':p['method_number'],'source_sha256':p['source_sha256']}
        except Exception as ex: log('patch_init_failed', str(ex)); return None
    def correspond(bank):
        r = review('Measure at least three obtainable, noncollinear corresponding physical landmarks from the supplied bank, using their exact names. Do not redefine identities by screen position. Omit hidden or ambiguous points; another camera is allowed. correspondence must be definite only for independently identifiable matches, ambiguous for competing matches, or unknown for insufficient visible evidence.', {'correspondence':['definite','ambiguous','unknown']}, bank)
        names = [b['name'] for b in bank if b['name'] in r['points']]
        require(r['parameters']['correspondence'] == 'definite' and len(names) >= 3, 'Unknown registration: fewer than three unambiguous current corresponding landmarks.')
        before = np.array([b['world'] for name in names for b in bank if b['name'] == name]); after = points(r,names)
        require(np.linalg.svd(before-before.mean(axis=0),compute_uv=False)[1]/math.sqrt(len(before)) > 2*M['u'], 'Corresponding landmarks have inadequate independent spread.')
        return before, after, M['u']+0.001
    def reference(prefer_original=True):
        base = M.get('pose_reference', {}) if prefer_original else {}
        p = base.get('patch',M.get('patch')) if prefer_original else None; t = quality(p['handle']) if p else None
        bank = []
        if t is not None:
            T = np.array(t['transform_initial_world_to_current_world'])
            bank = [dict(b, world=geo.transform(np.array([b['world']]),T)[0].tolist()) for b in base.get('bank',M['bank'])]
        else:
            r = review('Identify a currently visible rigid textured surface on the runtime movable object, not the hand or bowl. identity is same, other, or unknown. Select camera and an interior polygon for RGB-D tracking, or null if unusable. Supply definitions for three persistent physical marks q0,q1,q2 and request their current named depth points when identifiable. Definitions may be empty for unavailable marks. This is a NEW local reference; no registration to old corners is required.', {'identity':['same','other','unknown'],'camera':['agentview','robot0_eye_in_hand','unknown'],'polygon':polygon,'definitions':defs3}, {'object':M['object'],'phase':C['phase'],'old_reference_definitions':M['bank']})
            z = r['parameters']; require(z['identity'] == 'same','No identified object surface for a prospective motion measurement.')
            bank = [{'name':'q'+str(i),'definition':z['definitions'][i],'world':r['points']['q'+str(i)]['world_m']} for i in range(3) if 'q'+str(i) in r['points'] and z['definitions'][i]]
            p = patch(z['camera'],z['polygon'],M['object']); t = quality(p['handle']) if p else None
        L = {'patch':p,'bank':bank,'before':api.state(),'u':M['u'],'p0':None,'reference_points':None}
        if t is not None:
            a = np.array(t['reference_inlier_world_m']); a = a[::max(1,len(a)//12)][:12]
            L['reference_points'] = a.tolist(); L['p0'] = geo.transform(a,np.array(t['transform_initial_world_to_current_world'])).tolist(); L['u'] = t['u']
        require(t is not None or len(bank) >= 3, 'Neither a usable local tracker nor corresponding physical marks are obtainable.')
        return L
    def compare(L):
        t = quality(L['patch']['handle']) if L['patch'] else None
        if t is not None and L['reference_points'] is not None:
            return np.array(L['p0']), geo.transform(np.array(L['reference_points']),np.array(t['transform_initial_world_to_current_world'])), t['u']
        return correspond(L['bank'])
    def shape():
        original = {'patch':M.get('patch'),'envelope':M['envelope'],'bank':M['bank'],'u':M['u']}
        for base in [M.get('pose_reference'),original]:
            if not base or not base.get('patch'): continue
            t = quality(base['patch']['handle'])
            if t is not None:
                return geo.transform(np.array(base['envelope']),np.array(t['transform_initial_world_to_current_world'])), base['u']+t['u']*(1+M['radius']/(4*t['spread']))
        pair = {'type':['array','null'],'items':{'type':'integer','minimum':0,'maximum':len(M['bank'])-1},'minItems':2,'maxItems':2}
        pp = {'type':['array','null'],'items':pixel,'minItems':2,'maxItems':2}
        r = review('Recover the CURRENT package envelope, not a hand-predicted pose. correspondence is definite only for uniquely identified physical marks on this same rigid package, otherwise ambiguous or unknown. First request any obtainable saved bank points by exact name and physical definition. Alternatively supply pair_indices for TWO distinct identifiable bank marks on the same top face, with their genuinely visible pair_pixels in camera; do not project hidden marks or rename by screen position. For this alternative also request region top, a tight uncontaminated visible planar package-face interior, explicit camera/box/stride=4. This face may be partially occluded; its entire perimeter need not be visible. Use null pairs and unknown camera if unavailable. The region can also initialize a new texture reference after metric pose recovery.', {'correspondence':['definite','ambiguous','unknown'],'camera':['agentview','robot0_eye_in_hand','unknown'],'pair_indices':pair,'pair_pixels':pp}, {'object':M['object'],'bank':M['bank'],'reference_envelope':M['envelope']})
        z = r['parameters']; require(z['correspondence'] == 'definite','Envelope correspondence remains ambiguous or unknown.')
        names = [v['name'] for v in M['bank'] if v['name'] in r['points']]; u = M['u']; T = np.eye(4)
        if len(names) >= 3:
            a = np.array([v['world'] for name in names for v in M['bank'] if v['name'] == name]); b = points(r,names)
            ac = a.mean(axis=0); bc = b.mean(axis=0); spread = float(np.linalg.svd(a-ac,compute_uv=False)[1]/math.sqrt(len(a)))
            require(spread > 2*u,'Envelope landmark spread inadequate: '+str({'spread_m':spread,'u_m':u}))
            U,S,V = np.linalg.svd((a-ac).T@(b-bc)); R = V.T@U.T
            if np.linalg.det(R) < 0: V[-1,:] *= -1; R = V.T@U.T
            T[:3,:3] = R; T[:3,3] = bc-R@ac
            err = float(np.max(np.linalg.norm(geo.transform(a,T)-b,axis=1)))
            require(err < 3*u,'Envelope rigid residual='+str(err)); u += err+u*M['radius']/(4*spread)
        else:
            ids = z['pair_indices']; pix = z['pair_pixels']
            require(ids is not None and pix is not None and ids[0] != ids[1] and z['camera'] != 'unknown' and 'top' in r['regions'],'No obtainable three-mark or face-and-edge envelope witness.')
            face = geo.plane(r['regions']['top']['world_m']); old = geo.plane(M['envelope'][:4]); spread = min(face['in_plane_spread_m'])
            require(face['rms_m'] < u and spread > max(0.0008,3*face['rms_m']),'Visible face does not support a plane: '+str(face))
            a = np.array([M['bank'][i]['world'] for i in ids]); b = np.array([api.plane_point(z['camera'],p,face['coefficients'])['world_m'] for p in pix])
            n0 = np.array(old['coefficients'][:3]); n1 = np.array(face['coefficients'][:3]); e0 = a[1]-a[0]; e1 = b[1]-b[0]
            e0 -= n0*float(e0@n0); e1 -= n1*float(e1@n1); l0 = float(np.linalg.norm(e0)); l1 = float(np.linalg.norm(e1)); err = abs(l1-l0)
            require(min(l0,l1) > 4*u and err < 3*u,'Identified edge rejects the model: '+str({'reference_length':l0,'current_length':l1,'u':u}))
            e0 /= l0; e1 /= l1; B0 = np.column_stack([e0,np.cross(n0,e0),n0]); B1 = np.column_stack([e1,np.cross(n1,e1),n1]); R = B1@B0.T
            T[:3,:3] = R; T[:3,3] = b[0]-R@a[0]
            u += err+M['radius']*face['rms_m']/spread+u*M['radius']/(4*l0)
        env = geo.transform(np.array(M['envelope']),T); log('recovered_envelope',{'frame_id':r['frame_id'],'uncertainty_m':u,'residual_m':err})
        if 'top' in r['regions']:
            reg = r['regions']['top']; box = reg['box']; poly = [[box[0],box[1]],[box[2],box[1]],[box[2],box[3]],[box[0],box[3]]]; p = patch(reg['camera'],poly,M['object'])
            if p is not None:
                bank = [dict(v,world=geo.transform(np.array([v['world']]),T)[0].tolist()) for v in M['bank']]
                M['pose_reference'] = {'patch':p,'envelope':env.tolist(),'bank':bank,'u':u,'frame_id':r['frame_id'],'source':'independent current landmark/face registration, not hand motion'}; api.checkpoint('model',M)
        return env,u
    def refresh_hold():
        s = api.state()
        if H and fresh_hold[0] == s['frame_id']: return np.array(H['envelope']),H['u']
        env,u = shape(); s = api.state()
        if H:
            error = geo.attachment_error(H['envelope'],env.tolist(),H['state'],s)
            log('transfer_attachment', {'error_m':error,'allowance_m':H['u']+u+0.003})
            require(error <= H['u']+u+0.003, 'Current independently observed envelope is inconsistent with retained load.')
        H.clear(); H.update({'envelope':env.tolist(),'u':u,'state':s}); fresh_hold[0] = s['frame_id']; api.checkpoint('hold',H)
        return env,u
    def travel(target, purpose, held=False, final=False):
        target = np.array(target,dtype=float); start = np.array(geo.pad_position(api.state())); views = 0; tol = M['tol']
        require(np.linalg.norm(target-start) <= 0.45, 'Requested route exceeds this bounded local episode method.')
        count = min(14,int(math.ceil(float(np.linalg.norm(target-start))/0.065))+4)
        for k in range(count):
            s = api.state(); now = np.array(geo.pad_position(s)); d = target-now
            if held and H:
                env = np.array(H['envelope']); center = env[:4].mean(axis=0)
                radius = float(np.max(np.linalg.norm(env[:,:2]-center[:2],axis=1)))
                slack = M['bowl']['radius']-radius-H['u']-M['u']-0.0005
                require(slack > 0,'No measured opening slack for this held segment: '+str(slack))
                tol = min(0.003,max(0.0005,slack/3))
            if np.linalg.norm(d) <= tol: return
            b = s['budgets']; reserve = 0 if final else 10
            require(b['jev_remaining'] > reserve+2 and b['native_steps_remaining'] > 3*reserve+6 and b['gpt_remaining'] > (0 if final else 2), 'Insufficient budget with verification reserve.')
            nextp = now+d*min(1,0.075/float(np.linalg.norm(d)))
            away = now[:2]-np.array(M['bowl']['center']); away /= max(0.001,float(np.linalg.norm(away)))
            viewp = now+np.array([0.025*away[0],0.025*away[1],0.03]); sweep = None
            if M.get('approach_plan'):
                plan = M['approach_plan']; lo = np.minimum(now,nextp)+np.array(plan['relative_low']); hi = np.maximum(now,nextp)+np.array(plan['relative_high'])
                sep = np.maximum(np.maximum(lo[:2]-np.array(M['bowl']['center']),np.array(M['bowl']['center'])-hi[:2]),0)
                sweep = {'lowest_z_minus_rim_m':float(lo[2]-M['bowl']['rim_z']),'radial_gap_m':float(np.linalg.norm(sep)-plan['outer_radius_m']),'required_guard_m':plan['guard_m'],'scope':'Whole open-finger bound only; held item is separate. Round stationary bowl model, not a collision certificate.'}
            r = review('Review ONLY this next bounded segment. external: observed means a visible external obstruction to this segment, not_observed means none seen, unknown means undecidable. visibility: local_visible, self_occluded by robot/item, or unobserved. action: progress means current partial observations and the explicit local model justify this segment; view means ONLY the separately supplied outward-and-upward view segment is justified; none means neither is justified. For the stationary round bowl model, a swept-finger height OR radial gap above required_guard_m provides a local geometric witness; hidden rim pixels do not alone contradict it. Reject contradictory observations or other obstacles. No full later-corridor certificate is required. Self-occlusion is not an observed obstacle. A closed object still on support between the fingers may undergo the stated small retention lift without prior proof of attachment.', {'external':['observed','not_observed','unknown'],'visibility':['local_visible','self_occluded','unobserved'],'action':['progress','view','none']}, {'purpose':purpose,'next_pad_target':nextp.tolist(),'view_pad_target':viewp.tolist(),'object':M['object'],'rim':M['bowl'],'swept_finger_model':sweep,'stationary_witness':M.get('stationary_witness'),'held_envelope':H.get('envelope'),'prior':'Stationary bowl/support only while current partial evidence and noncontact history agree. Closure invalidates the stationary package pose; retention and transport need independent motion measurements.'})
            z = r['parameters']; require(z['action'] != 'none', 'No justified local action: '+r['explanation'])
            if z['action'] == 'view':
                require(views < 1, 'Outward view did not resolve this local gap: '+r['explanation']); nextp = viewp; views += 1
            else: require(z['external'] != 'observed', 'Observed external obstruction blocks this segment.')
            C['intent'] = {'purpose':purpose,'target':nextp.tolist(),'frame_id':s['frame_id']}; save()
            receipt = api.drive(nextp.tolist(),M['quaternion'],'keep',Q,features={'purpose':purpose,'review':z,'swept_finger_model':sweep,'uncertainty_m':M['u'],'position_tolerance_m':tol},tool_point='pad_center',max_calls=min(16,b['jev_remaining']-reserve),translation_limit=0.02,rotation_limit=0.08,steps=3,position_tolerance=tol,rotation_tolerance=0.025)
            C['last_motion'] = {'status':receipt['status'],'frame_id':receipt['frame_id'],'position_error_m':receipt['position_error_m']}; save()
            if receipt['status'] != 'reached':
                actual = api.state(); residual = float(np.linalg.norm(nextp-np.array(geo.pad_position(actual))))
                band = min(actual['own_geometry']['pad_extent_in_tool_m'][0],actual['own_geometry']['pad_extent_in_tool_m'][2])/2
                if receipt['status'] == 'lease_exhausted' and purpose == 'visually bracketed open-finger descent' and not held and actual['last_gripper_command'] == 'open' and residual < band:
                    C['approach_effect_pending'] = True; save(); log('descent_effect_gate',{'residual_m':residual,'band_half_extent_m':band,'action':'No further descent; assess actual overlap and clearance before closure.'}); return
                raise ValueError('Motion lease stopped without convergence: '+str(C['last_motion']))
            if held: refresh_hold()
        require(np.linalg.norm(target-np.array(geo.pad_position(api.state()))) <= tol, 'Bounded route exhausted before target; no clearance or progress assumed.')
    def jaw(command):
        for k in range(max(0,3-C['jaw_calls'])):
            s = api.state(); r = api.control(np.array(geo.pad_position(s)).tolist(),s['tcp_quaternion_xyzw'],command,Q,features={'purpose':'Acknowledged jaw transition only; object effect requires observation.'},tool_point='pad_center',translation_limit=0.001,rotation_limit=0.01,steps=3,position_tolerance=M['tol'],rotation_tolerance=0.025)
            C['jaw_calls'] += 1
            if api.state()['last_gripper_command'] == command and r['acknowledged_steps'] > 0: C['phase'] = 'released' if command == 'open' else 'closed'
            save(); require(r['status'] in ['reached','moved'], 'Jaw-transition control stalled; do not push contact.')
        require(api.state()['last_gripper_command'] == command, 'Requested jaw command was not acknowledged.')
    def grasp_check(at_contact=True):
        s = api.state(); require(s['last_gripper_command'] == 'open','Achieved approach assessment requires the acknowledged open hand.')
        env = np.array(M['envelope']); p = np.array(geo.pad_position(s)); R = geo.rotation(s['tcp_quaternion_xyzw']); own = s['own_geometry']; u = M['u']; ext = np.array(own['pad_extent_in_tool_m'])
        local = (env-p)@R; overlaps = [float(min(float(local[:,i].max()),ext[i]/2)-max(float(local[:,i].min()),-ext[i]/2)) for i in [0,2]]
        low = own['finger_low_offset_tool_m']; high = own['finger_high_offset_tool_m']; fc = np.array([[x,y,z] for x in [low[0],high[0]] for y in [low[1],high[1]] for z in [low[2],high[2]]]); rel = (fc-np.array(own['pad_center_in_tool_m']))@R.T
        support_gap = float(p[2]+rel[:,2].min()-env[4:,2].max()); bowl = M['bowl']; plan = M.get('approach_plan',{}); guard = 2*u+0.0005
        sep = np.maximum(np.maximum(p[:2]+rel[:,:2].min(axis=0)-np.array(bowl['center']),np.array(bowl['center'])-p[:2]-rel[:,:2].max(axis=0)),0)
        radial_gap = float(np.linalg.norm(sep)-plan.get('outer_radius_m',bowl['radius']+u)); height_gap = float(p[2]+rel[:,2].min()-bowl['rim_z'])
        actual = {'pad_world_m':p.tolist(),'long_vertical_overlap_m':overlaps,'support_gap_m':support_gap,'bowl_radial_gap_m':radial_gap,'bowl_height_gap_m':height_gap,'guard_m':guard,'uncertainty_m':u,'contact_gate':at_contact}; log('achieved_grasp_geometry',actual)
        require(support_gap > u and (radial_gap > guard or height_gap > guard),'Achieved support or bowl clearance fails: '+str(actual))
        require(not at_contact or min(overlaps) > 2*u,'Achieved finite contact overlap is inadequate: '+str(actual))
        require(float(local[:,1].max()) < ext[1]/2-u and float(local[:,1].min()) > -ext[1]/2+u,'Package is outside the coarse open span; inner clearance still needs review.')
        r = review('Assess the ACHIEVED open-finger pose, not its missed target. fit is straddling only if current images support inner finger paths bracketing the intended package sides with clearance; otherwise blocked or unknown. Finite end-offset pad overlap is intentional. stationary is consistent only if this same package remains flat, supported and unchanged in pose, and the bowl remains unchanged, with no observed contact/displacement contradicting the supplied short-horizon model; otherwise moved or unknown. Request any currently identifiable saved bank points by physical definition. Also request surface on an unobscured package top INTERIOR, not an edge, hand or table. When old marks are hidden this partial surface witness plus independent visual support/orientation/identity evidence may corroborate, but never fully register, the stationary prior. Supply camera and an interior textured package polygon for tracking, or unknown/null. Supply physical definitions and current named points q0,q1,q2 for three usable printed marks if available, empty definitions otherwise. This new local reference does not require old corners.', {'fit':['straddling','blocked','unknown'],'stationary':['consistent','moved','unknown'],'camera':['agentview','robot0_eye_in_hand','unknown'],'polygon':polygon,'definitions':defs3}, {'object':M['object'],'bank':M['bank'],'envelope_prior':M['envelope'],'bowl_prior':bowl,'achieved':actual,'stationary_witness':M.get('stationary_witness'),'invalidation':'Any displaced package, altered support/orientation, moved bowl, or contradictory contact invalidates reuse. No complete global registration is claimed from a partial point.'})
        z = r['parameters']; require(z['fit'] == 'straddling' and z['stationary'] == 'consistent','Actual inner clearance or stationary hypothesis unresolved: '+r['explanation'])
        errors = [float(np.linalg.norm(np.array(r['points'][b['name']]['world_m'])-np.array(b['world']))) for b in M['bank'] if b['name'] in r['points']]
        plane = geo.plane(env[:4]); surface_ok = False; residual = None
        if 'surface' in r['points']:
            v = np.array(r['points']['surface']['world_m']); residual = abs(float(v@np.array(plane['coefficients'][:3])+plane['coefficients'][3])); surface_ok = residual < 3*u and bool(np.all(v >= env[:4].min(axis=0)-3*u) and np.all(v <= env[:4].max(axis=0)+3*u))
        require((not errors or max(errors) < 3*u) and (len(errors) > 0 or surface_ok),'No consistent current partial package witness: '+str({'point_errors_m':errors,'surface_plane_error_m':residual}))
        t = quality(M['patch']['handle']) if M.get('patch') else None
        if t is not None:
            deviation = float(np.max(np.linalg.norm(geo.transform(env,np.array(t['transform_initial_world_to_current_world']))-env,axis=1)))
            require(deviation < 3*u,'Current patch contradicts stationary package pose: '+str(deviation))
        else:
            newp = patch(z['camera'],z['polygon'],M['object'])
            if newp is not None and quality(newp['handle']) is not None: M['patch'] = newp
        bank = [b for b in M['bank'] if b['name'] not in ['q0','q1','q2']]
        for i in range(3):
            name = 'q'+str(i)
            if name in r['points'] and z['definitions'][i]:
                v = np.array(r['points'][name]['world_m'])
                if abs(float(v@np.array(plane['coefficients'][:3])+plane['coefficients'][3])) < 3*u: bank.append({'name':name,'definition':z['definitions'][i],'world':v.tolist()})
        M['bank'] = bank; M['quaternion'] = s['tcp_quaternion_xyzw']; M['finger_min_z'] = float(rel[:,2].min())
        M['stationary_witness'] = {'frame_id':r['frame_id'],'partial_errors_m':errors,'surface_plane_error_m':residual,'achieved':actual,'validity':'Short-horizon supported stationary hypothesis only. Invalid after closure, contradictory contact, displacement, or orientation/support change.'}; api.checkpoint('model',M)
    def prepare_approach():
        s = api.state(); require(s['last_gripper_command'] == 'open', 'Approach repair requires an acknowledged open hand, not a possible load.')
        r = review('Revalidate ONLY the stationary approach model before any descent. prior is consistent only if the same package remains flat on its support with unchanged orientation and the same bowl remains stationary; otherwise changed or unknown. Request at least two current, independently identifiable saved bank points using their exact physical definitions, preferably printed f marks; omit hidden or ambiguous ones. Request three currently visible INNER rim samples v0,v1,v2 (new sample locations, not old landmark correspondences) and current floor at the visible bowl interior low point. Request region edge: a tight visible bowl exterior/outer-rim patch, excluding hand and package, explicit camera/box/stride=4. exterior is round_unflared only if visible bowl profile supports a concentric rounded body whose largest radius is at the rim; otherwise other or unknown. Also choose camera and an interior textured package polygon, or unknown/null if unavailable. This prospective patch needs identity, not registration to hidden old corners.', {'prior':['consistent','changed','unknown'],'exterior':['round_unflared','other','unknown'],'camera':['agentview','robot0_eye_in_hand','unknown'],'polygon':polygon}, {'bank':M['bank'],'bowl_prior':M['bowl'],'object':M['object'],'history':'Open-hand noncontact approach only; saved coordinates are hypotheses, not detections.'})
        z = r['parameters']; errors = [float(np.linalg.norm(np.array(r['points'][b['name']]['world_m'])-np.array(b['world']))) for b in M['bank'] if b['name'] in r['points']]
        rim = points(r,['v0','v1','v2']); u = M['u']; bowl = M['bowl']
        require(z['prior'] == 'consistent' and z['exterior'] == 'round_unflared' and len(errors) >= 2 and max(errors) < 3*u, 'Stationary partial-reference evidence is insufficient or contradictory: '+str(errors))
        require(len(rim) >= 2 and 'floor' in r['points'] and 'edge' in r['regions'], 'Missing current bowl partial witness or visible exterior region.')
        radial_error = float(np.max(np.abs(np.linalg.norm(rim[:,:2]-np.array(bowl['center']),axis=1)-bowl['radius'])))
        floor_error = float(np.linalg.norm(np.array(r['points']['floor']['world_m'])-np.array(bowl['floor'])))
        require(radial_error < 3*u and np.max(np.abs(rim[:,2]-bowl['rim_z'])) < 3*u and floor_error < 3*u, 'Bowl prior contradicted: '+str({'radial_error_m':radial_error,'floor_error_m':floor_error}))
        edge = np.array(r['regions']['edge']['world_m']); edge = edge[(edge[:,2] > bowl['floor'][2]+u)&(edge[:,2] < bowl['rim_z']+3*u)]
        require(len(edge) >= 6, 'Exterior region lacks usable above-floor bowl samples; cannot bound the approach obstacle.')
        outer = max(bowl['radius'],float(np.max(np.linalg.norm(edge[:,:2]-np.array(bowl['center']),axis=1))))+u
        env = np.array(M['envelope']); face = env[:4]; center = face.mean(axis=0); e0 = face[1]-face[0]; e1 = face[3]-face[0]
        long = e0 if np.linalg.norm(e0) > np.linalg.norm(e1) else e1; long = long/np.linalg.norm(long)
        R = geo.rotation(M['quaternion']); own = s['own_geometry']; low = own['finger_low_offset_tool_m']; high = own['finger_high_offset_tool_m']
        fc = np.array([[x,y,zv] for x in [low[0],high[0]] for y in [low[1],high[1]] for zv in [low[2],high[2]]])
        rel = (fc-np.array(own['pad_center_in_tool_m']))@R.T; rlo = rel.min(axis=0); rhi = rel.max(axis=0)
        interval = (face-center)@long; half = float(np.abs(R.T@long)@np.array(own['pad_extent_in_tool_m'])/2)
        overlap = min(float(np.max(interval)-np.min(interval)),2*half)*0.5
        lower = float(np.min(interval)+overlap-half+2*u); upper = float(np.max(interval)-overlap+half-2*u)
        guard = 2*u+M['tol']+0.0005; candidates = []
        require(lower <= upper and overlap > 2*u, 'Longitudinal contact band unobservable: '+str({'lower':lower,'upper':upper,'overlap':overlap,'u':u}))
        for shift in [0.0]+np.linspace(lower,upper,25).tolist():
            if shift < lower or shift > upper: continue
            p = center+shift*long; p[2] = M['grasp'][2]
            sep = np.maximum(np.maximum(p[:2]+rlo[:2]-np.array(bowl['center']),np.array(bowl['center'])-p[:2]-rhi[:2]),0)
            gap = float(np.linalg.norm(sep)-outer); candidates.append({'shift':float(shift),'gap':gap,'pad':p.tolist()})
        feasible = [v for v in candidates if v['gap'] > guard]
        log('offset_grasp_search',{'best_gap_m':max(v['gap'] for v in candidates),'required_guard_m':guard,'outer_radius_m':outer,'long_overlap_m':overlap,'shift_interval_m':[lower,upper]})
        require(len(feasible) > 0, 'No offset grasp has both finite-band contact and bowl clearance; do not repeat the centered descent.')
        selected = sorted(feasible,key=lambda v:abs(v['shift']))[0]
        M['grasp'] = selected['pad']; M['finger_min_z'] = float(rlo[2])
        M['approach_plan'] = {'relative_low':rlo.tolist(),'relative_high':rhi.tolist(),'outer_radius_m':outer,'guard_m':guard,'long_overlap_m':overlap,'selected':selected,'frame_id':r['frame_id']}
        M['stationary_witness'] = {'frame_id':r['frame_id'],'partial_errors_m':errors,'rim_radial_error_m':radial_error,'floor_error_m':floor_error,'validity':'Short horizon only; invalidate on contact, changed support/orientation, or inconsistent current partial observations.'}
        t = quality(M['patch']['handle']) if M.get('patch') else None
        if t is None:
            p = patch(z['camera'],z['polygon'],M['object'])
            if p is not None and quality(p['handle']) is not None: M['patch'] = p
        api.checkpoint('model',M); log('selected_offset_grasp',M['approach_plan'])
    def resume_placement():
        D = load('placement_continuation', {})
        def store():
            C['phase'] = 'compact_'+D['phase']; C['jaw_calls'] = D.get('jaw_calls',0)
            api.checkpoint('placement_continuation',D); save()
        def finger_low(s):
            g = s['own_geometry']; lo = g['finger_low_offset_tool_m']; hi = g['finger_high_offset_tool_m']
            a = np.array([[x,y,z] for x in [lo[0],hi[0]] for y in [lo[1],hi[1]] for z in [lo[2],hi[2]]])
            return float(((a-np.array(g['pad_center_in_tool_m']))@geo.rotation(s['tcp_quaternion_xyzw']).T)[:,2].min())
        def project(a, camera):
            cal = api.camera(camera); b = geo.transform(a,np.linalg.inv(np.array(cal['camera_to_world_opencv'])))
            require(bool(np.all(b[:,2] > 0.02)), 'End-face search is behind or too near the camera.')
            p = b@np.array(cal['K']).T
            return p[:,:2]/p[:,2:3]
        def scan(pred):
            face = pred[[0,1,5,4]]; w = face[1]-face[0]; w /= np.linalg.norm(w)
            v = face[0]-face[3]; v /= np.linalg.norm(v); n = np.cross(w,v); n /= np.linalg.norm(n)
            B = np.column_stack([w,v,n]); c = face.mean(axis=0); limits = (face-c)@B
            pix = project(face,D['camera']); box = [max(0,int(pix[:,0].min())-12),max(0,int(pix[:,1].min())-12),min(767,int(pix[:,0].max())+13),min(767,int(pix[:,1].max())+13)]
            require(box[2]-box[0] > 12 and box[3]-box[1] > 12, 'No usable current end-face search window.')
            cl = api.cloud(D['camera'],box,stride=4); a = np.array(cl['world_m']); rgb = np.array(cl['rgb'],dtype=float); pixels = np.array(cl['pixels'])
            require(len(a) >= 20, 'End-face window has insufficient depth.')
            z = (a-c)@B; mask = (np.abs(z[:,2]) < 0.008)&np.all(z[:,:2] >= limits[:,:2].min(axis=0)-0.006,axis=1)&np.all(z[:,:2] <= limits[:,:2].max(axis=0)+0.006,axis=1)
            a = a[mask]; rgb = rgb[mask]; pixels = pixels[mask]
            for trim in range(2):
                require(len(a) >= 20, 'No sufficiently supported independent end-face plane.')
                fit = geo.plane(a); nf = np.array(fit['coefficients'][:3]); residual = np.abs(a@nf+fit['coefficients'][3]); keep = residual < 0.002
                a = a[keep]; rgb = rgb[keep]; pixels = pixels[keep]
            require(len(a) >= 20, 'End-face plane trimming removed its support.')
            fit = geo.plane(a); nf = np.array(fit['coefficients'][:3])
            if float(nf@n) < 0: nf = -nf
            require(float(nf@n) > 0.98 and fit['rms_m'] < 0.001 and min(fit['in_plane_spread_m']) > max(0.001,3*fit['rms_m']), 'Current end-face plane contradicts the local rigid model: '+str(fit))
            centered = a-a.mean(axis=0); centered -= (centered@nf)[:,None]*nf
            U,S,V = np.linalg.svd(centered,full_matrices=False); wf = V[0]
            if float(wf@w) < 0: wf = -wf
            vf = np.cross(nf,wf); basis = np.column_stack([wf,vf,nf]); coords = a@basis
            bounds = np.quantile(coords,[0.03,0.97],axis=0); span = bounds[1,:2]-bounds[0,:2]; center = basis@((bounds[0]+bounds[1])/2)
            require(span[0] > 1.4*span[1] and float(vf@v) > 0.98, 'Finite face axes are ambiguous or have changed.')
            require(bool(np.all(pixels.min(axis=0) > np.array(box[:2])+2) and np.all(pixels.max(axis=0) < np.array(box[2:])-2)), 'Face support touches the search crop; its extent is not measured.')
            rgb /= 255.0 if float(rgb.max()) > 1 else 1.0
            return {'B':basis.tolist(),'center':center.tolist(),'span':span.tolist(),'color':np.quantile(rgb,[0.2,0.5,0.8],axis=0).tolist(),'count':len(a),'rms':fit['rms_m'],'frame_id':cl['frame_id'],'box':box}
        def pose_from_scan(pred):
            if D.get('template_key'): return template_pose()
            sig = scan(pred); ref = D['signature']; change = float(np.max(np.abs(np.array(sig['span'])-np.array(ref['span']))))
            color = float(np.mean(np.abs(np.array(sig['color'])-np.array(ref['color']))))
            require(change < 2*M['u']+0.001 and color < 0.06 and 0.55*ref['count'] < sig['count'] < 1.8*ref['count'], 'Finite-face correspondence rejected: '+str({'span_change_m':change,'color_change':color,'samples':sig['count']}))
            T = np.eye(4); T[:3,:3] = np.array(sig['B'])@np.array(ref['B']).T; T[:3,3] = np.array(sig['center'])-T[:3,:3]@np.array(ref['center'])
            u = D['u0']+change/2+sig['rms']*(1+D['length']/min(sig['span']))
            return geo.transform(np.array(D['env0']),T),u,'independent finite-face RGB-D geometry'
        def measure():
            s = api.state(); prev = D['state']; T = np.eye(4)
            T[:3,:3] = geo.rotation(s['tcp_quaternion_xyzw'])@geo.rotation(prev['tcp_quaternion_xyzw']).T
            T[:3,3] = np.array(s['tcp_position_world_m'])-T[:3,:3]@np.array(prev['tcp_position_world_m'])
            pred = geo.transform(np.array(D['envelope']),T); measured = None; reason = None
            if D.get('signature'):
                try: measured = pose_from_scan(pred)
                except Exception as ex: reason = str(ex)
            p = D.get('patch'); t = quality(p['handle']) if p else None
            tracked = None
            if t is not None:
                tracked = geo.transform(np.array(D['patch_envelope']),np.array(t['transform_initial_world_to_current_world']))
                tu = D['u0']+t['u']*(1+M['radius']/(6*t['spread']))
            if measured is None:
                require(tracked is not None, 'Current registration unknown; neither finite-face geometry nor saved texture resolves it. '+str(reason))
                measured = (tracked,tu,'independent qualified RGB-D patch')
            env,u,source = measured
            if tracked is not None:
                disagreement = float(np.max(np.linalg.norm(tracked-env,axis=1)))
                require(disagreement < u+tu, 'Independent local witnesses disagree: '+str(disagreement))
            error = geo.attachment_error(D['envelope'],env.tolist(),prev,s)
            hand = float(np.linalg.norm(np.array(s['tcp_position_world_m'])-np.array(prev['tcp_position_world_m'])))
            moved = float(np.linalg.norm(env.mean(axis=0)-np.array(D['envelope']).mean(axis=0)))
            log('local_transport_witness',{'source':source,'attachment_error_m':error,'allowance_m':D['u']+u+0.003,'hand_motion_m':hand,'object_motion_m':moved,'uncertainty_m':u})
            require(error < D['u']+u+0.003 and (hand < max(0.01,3*(D['u']+u)) or moved > 0.55*hand), 'Independent object motion does not support retained transport.')
            D.update({'envelope':env.tolist(),'state':s,'u':float(u),'witness_frame':s['frame_id']}); store()
            return env,float(u)
        def template_pose():
            ref = load(D['template_key'],{}); samples = ref['samples']; box = ref['box']
            search = [max(0,box[0]-12),max(0,box[1]-12),min(767,box[2]+12),min(767,box[3]+12)]
            cl = api.cloud(ref['camera'],search,stride=4); lookup = {tuple(p):i for i,p in enumerate(cl['pixels'])}; candidates = []
            for dx in range(-12,13,4):
                for dy in range(-12,13,4):
                    pairs = [(j,lookup[(v[0][0]+dx,v[0][1]+dy)]) for j,v in enumerate(samples) if (v[0][0]+dx,v[0][1]+dy) in lookup]
                    if len(pairs) < max(24,int(0.8*len(samples))): continue
                    a = np.array([samples[j][1] for j,i in pairs]); b = np.array([cl['world_m'][i] for j,i in pairs])
                    colors = np.array([samples[j][2] for j,i in pairs],dtype=float)-np.array([cl['rgb'][i] for j,i in pairs],dtype=float)
                    ce = np.sqrt(np.mean((colors/ref['scale'])**2,axis=1)); keep = np.argsort(ce)[:max(24,int(0.8*len(pairs)))]; a = a[keep]; b = b[keep]; ce = ce[keep]
                    ac = a.mean(axis=0); bc = b.mean(axis=0); U,S,V = np.linalg.svd((a-ac).T@(b-bc)); R = V.T@U.T
                    if np.linalg.det(R) < 0: V[-1,:] *= -1; R = V.T@U.T
                    T = np.eye(4); T[:3,:3] = R; T[:3,3] = bc-R@ac
                    residual = float(np.quantile(np.linalg.norm(geo.transform(a,T)-b,axis=1),0.9)); color = float(np.sqrt(np.mean(ce**2)))
                    spread = float(np.linalg.svd(a-ac,compute_uv=False)[1]/math.sqrt(len(a)))
                    if residual < 0.0015 and color < 0.055 and spread > max(0.001,3*residual): candidates.append((color+20*residual,T,residual,spread))
            require(len(candidates) > 0,'Current identified end template has no adequate independent RGB-D correspondence; no review budget for reidentification.')
            candidates = sorted(candidates,key=lambda v:v[0]); best = candidates[0]; env = geo.transform(np.array(D['env0']),best[1]); ambiguity = 0.0
            for score,T,residual,spread in candidates:
                if score <= best[0]+0.006: ambiguity = max(ambiguity,float(np.max(np.linalg.norm(geo.transform(np.array(D['env0']),T)-env,axis=1))))
            require(ambiguity < 0.002,'End-template correspondence is ambiguous: '+str({'ambiguity_m':ambiguity,'score':best[0]}))
            u = D['u0']+0.00035+ambiguity+best[2]*(1+D['length']/(4*best[3]))
            return env,float(u),'independent identified RGB-D template; bounded correspondence ambiguity'
        if not D and api.state()['budgets']['gpt_remaining'] == 0:
            s = api.state(); require(s['frame_id'] == 273,'Frame-specific repair annotations are historical; current reidentification is unavailable.')
            L = load('local',{}); require(L and C['phase'] == 'retained','Missing saved local retention provenance.')
            camera = 'robot0_eye_in_hand'; box = [306,603,465,624]; cl = api.cloud(camera,box,stride=4); cloud = np.array(cl['world_m'])
            require(len(cloud) >= 40,'Reviewed end interior lacks current depth support.')
            fit = geo.plane(cloud); require(fit['rms_m'] < 0.0008 and min(fit['in_plane_spread_m']) > max(0.001,4*fit['rms_m']),'Current end plane is inadequate: '+str(fit))
            def sample(camera,px):
                for radius in [1,2,3]:
                    try: return api.point(camera,px,radius=radius)['world_m']
                    except Exception as ex: log('local_depth_retry',{'pixel':px,'radius':radius,'error':str(ex)})
                raise ValueError('No usable current depth at identified pixel '+str(px))
            marks = [api.plane_point(camera,[297,598],fit['coefficients'])['world_m'],sample(camera,[471,593]),sample(camera,[277,631])]
            a = np.array([v['world'] for name in ['q0','q1','q2'] for v in L['bank'] if v['name'] == name]); b = np.array(marks)
            require(len(a) == 3,'Saved semantic local reference is incomplete.')
            hand = np.array(s['tcp_position_world_m'])-np.array(L['before']['tcp_position_world_m']); effect = (b-a).mean(axis=0); ru = L['u']+M['u']+0.0008
            err = geo.attachment_error(a.tolist(),b.tolist(),L['before'],s)
            log('repair_retention',{'hand_m':hand.tolist(),'object_m':effect.tolist(),'attachment_error_m':err,'uncertainty_m':ru})
            require(hand[2] > 4*ru and effect[2] > 0.65*hand[2] and err < ru+0.003,'Current local marks do not corroborate the saved retention test.')
            rim = np.array([sample('agentview',[357,411]),sample('agentview',[343,435])]); bowl = M['bowl']
            re = float(np.max(np.abs(np.linalg.norm(rim[:,:2]-np.array(bowl['center']),axis=1)-bowl['radius']))); he = float(np.max(np.abs(rim[:,2]-bowl['rim_z'])))
            require(re < 3*M['u'] and he < 3*M['u'],'Current partial bowl witness contradicts the prior: '+str([re,he]))
            old = np.array(M['envelope']); width = float(np.linalg.norm(old[1]-old[0])); length = float(np.linalg.norm(old[3]-old[0])); n = np.array(fit['coefficients'][:3])
            require(length > width,'Saved corner order does not identify the reviewed near end.')
            if float(n@(old[3]-old[0])) < 0: n = -n
            w = b[1]-b[0]; w -= n*float(w@n); measured_width = float(np.linalg.norm(w)); w /= measured_width; up = np.cross(n,w)
            require(up[2] > 0.97 and abs(n[2]) < 0.2 and abs(measured_width-width) < 3*M['u'],'Visible width edge rejects the end model: '+str({'width_m':measured_width,'reference_m':width,'up_z':float(up[2])}))
            allp = np.concatenate([cloud,b]); plane_error = float(np.max(np.abs(allp@n-float(np.mean(cloud@n)))))
            require(plane_error < 2*M['u'],'Local marks disagree with the measured end plane: '+str(plane_error))
            heights = allp@up; low = float(heights.max()-M['height']); high = float(heights.min()+M['height'])
            require(low < high and float(heights.max()-heights.min()) <= M['height']+2*M['u'],'Interior witnesses contradict rigid thickness.')
            mid = float(np.mean(b[:2]@w)); base = n*float(np.mean(cloud@n)); sides = [mid-width/2,mid+width/2]
            top = np.array([base+w*sides[0]+up*high,base+w*sides[1]+up*high,base+w*sides[1]+up*high+n*length,base+w*sides[0]+up*high+n*length]); env = np.concatenate([top,top-up*(high-low)])
            u = M['u']+0.0008+fit['rms_m']+abs(measured_width-width)/2
            ids = np.linspace(0,len(cloud)-1,48).astype(int).tolist(); rgb = np.array(cl['rgb'],dtype=float); scale = 255.0 if float(rgb.max()) > 1 else 1.0
            require(float(np.max(np.std(rgb/scale,axis=0))) > 0.035,'Reviewed patch has insufficient distinctive appearance for a metric fallback.')
            api.checkpoint('end_template',{'camera':camera,'box':box,'frame_id':cl['frame_id'],'scale':scale,'identity':M['object']+'; reviewed narrow end interior at frame 273','samples':[[cl['pixels'][i],cl['world_m'][i],cl['rgb'][i]] for i in ids]})
            extent = 1.18*bowl['radius']; corners = np.array([[bowl['center'][0]+x,bowl['center'][1]+y,z] for x in [-extent,extent] for y in [-extent,extent] for z in [bowl['floor'][2],bowl['rim_z']]])
            px = project(corners,'agentview'); bb = [max(0,int(px[:,0].min())-4),max(0,int(px[:,1].min())-4),min(767,int(px[:,0].max())+5),min(767,int(px[:,1].max())+5)]
            bc = api.cloud('agentview',bb,stride=4); ids = np.linspace(0,len(bc['world_m'])-1,min(96,len(bc['world_m']))).astype(int).tolist()
            api.checkpoint('bowl_before_release',{'box':bb,'frame_id':bc['frame_id'],'calibration':api.camera('agentview')['camera_to_world_opencv'],'samples':[[bc['pixels'][i],bc['world_m'][i]] for i in ids]})
            p = patch(camera,[[306,603],[465,603],[465,624],[306,624]],M['object']+' identified near end')
            D.update({'phase':'route','stage':0,'jaw_calls':0,'envelope':env.tolist(),'env0':env.tolist(),'state':s,'u':float(u),'u0':float(u),'length':length,'camera':camera,'quaternion':s['tcp_quaternion_xyzw'],'signature':{'mode':'local_template'},'template_key':'end_template','patch':p,'patch_envelope':env.tolist(),'binding':{'frame_id':273,'source':'Supplied frame-273 identity/local-route review, refreshed calibrated RGB-D; q0 visible junction selected from current supplied image','q_pixels':[[297,598],[471,593],[277,631]],'q0_source':'visible landmark ray intersected with measured end plane; 0.0008 m annotation allowance','reference_definitions':L['bank'],'retention_error_m':err,'bowl_residuals_m':[re,he],'vertical_interval_m':[low,high],'uncertainty_m':float(u),'prior':'Rigid dimensions and identified near-end direction. Upper seam is unobserved; vertical envelope bounds all translations consistent with measured interior points. Stationary bowl retained only during the reviewed noncontact route.'}})
            store(); measured,mu,source = template_pose(); log('repair_binding',{'source':source,'uncertainty_m':mu,'width_m':measured_width,'vertical_interval_m':[low,high]})
        if not D:
            require(api.state()['budgets']['gpt_remaining'] >= 2, 'Need one current binding review and one final review.')
            L = load('local',{}); require(L and C['phase'] == 'retained', 'No saved prospective retention reference for this continuation.')
            fields = {'correspondence':['definite','ambiguous','unknown'],'model':['rigid_narrow_end','unsupported','unknown'],'direction':['same_end','opposite_end','unknown'],'camera':['agentview','robot0_eye_in_hand','unknown'],'seam_pixels':{'type':['array','null'],'items':pixel,'minItems':2,'maxItems':2},'external':['observed','not_observed','unknown'],'visibility':['local_visible','self_occluded','unobserved'],'route':['locally_justified','raise_only','none'],'bowl_prior':['consistent','changed','unknown']}
            r = review('Resolve only the missing current witnesses. Request three obtainable corresponding local-bank marks using their saved physical definitions, not screen renaming; correspondence concerns these marks. Identify the same package visible narrow END face. Request region face, a tight unobstructed planar interior of that end, explicit camera/box/stride=4. Supply camera and seam_pixels for the TWO genuine endpoints of its physical UPPER seam (world-up package edge), not printed artwork; null if hidden. The rigid dimensions are supplied from earlier measured support/top geometry. direction=same_end means this is the near end used for the offset grasp and the body extends toward the saved other end; opposite_end means uniquely identified opposite end; unknown rejects ambiguous inward direction. Partial visibility can corroborate the unchanged discrete orientation hypothesis after the measured upward retention test, but cannot invent an edge. Request current inner rim samples b0,b1,b2, separated and preferably not behind the hand. bowl_prior concerns the same stationary circular bowl. For a short raise, above-rim translation toward that bowl, and noncontact lowering above its rim: external=observed means a visible external obstruction, not_observed means none seen, unknown means undecidable; visibility separates self-occlusion from unseen external space. route=locally_justified means visible local evidence and the explicit above-rim model justify bounded progress, NOT certified clearance of every hidden voxel; raise_only or none do not authorize transfer. Reject contradictory orientation, identity, obstruction, or bowl motion.',fields,{'object':M['object'],'local_bank':L['bank'],'reference_envelope':M['envelope'],'reference_definitions':M['bank'],'bowl':M['bowl'],'retention_reference_frame':L['before']['frame_id'],'scope':'Preserve current tool orientation, keep jaws closed, legs <=0.035m, hold item and fingers >=0.025m above rim during horizontal transfer. Current local observations must independently confirm each object motion.'})
            z = r['parameters']; require(z['model'] == 'rigid_narrow_end' and z['direction'] != 'unknown' and z['seam_pixels'] is not None and z['camera'] != 'unknown' and 'face' in r['regions'], 'No independently identified end-face/seam geometry: '+r['explanation'])
            require(z['external'] == 'not_observed' and z['route'] == 'locally_justified' and z['bowl_prior'] == 'consistent', 'Only a raise or no local route is justified; no clearance assumed: '+r['explanation'])
            names = [b['name'] for b in L['bank'] if b['name'] in r['points']]; p = L.get('patch'); t = quality(p['handle']) if p else None
            if t is not None and L.get('reference_points') is not None:
                a = np.array(L['p0']); b = geo.transform(np.array(L['reference_points']),np.array(t['transform_initial_world_to_current_world'])); ru = L['u']+t['u']
            else:
                require(z['correspondence'] == 'definite' and len(names) >= 3, 'Current local retention correspondences remain unknown.')
                a = np.array([b['world'] for name in names for b in L['bank'] if b['name'] == name]); b = points(r,names); ru = L['u']+M['u']+0.001
                require(np.linalg.svd(a-a.mean(axis=0),compute_uv=False)[1]/math.sqrt(len(a)) > M['u'], 'Local marks lack independent spread.')
            s = api.state(); hand = np.array(s['tcp_position_world_m'])-np.array(L['before']['tcp_position_world_m']); effect = np.mean(b-a,axis=0); err = geo.attachment_error(a.tolist(),b.tolist(),L['before'],s)
            require(hand[2] > 4*ru and effect[2] > 0.65*hand[2] and err < ru+0.004, 'Fresh local measurements do not revalidate the saved retention test.')
            rim = points(r,['b0','b1','b2']); require(len(rim) >= 2, 'Missing current partial bowl witness.')
            re = float(np.max(np.abs(np.linalg.norm(rim[:,:2]-np.array(M['bowl']['center']),axis=1)-M['bowl']['radius'])))
            he = float(np.max(np.abs(rim[:,2]-M['bowl']['rim_z'])))
            require(re < 3*M['u'] and he < 3*M['u'], 'Current bowl model residuals: '+str({'radial_m':re,'height_m':he,'u_m':M['u']}))
            reg = r['regions']['face']; cl = api.cloud(reg['camera'],reg['box'],stride=4); fit = geo.plane(cl['world_m']); n = np.array(fit['coefficients'][:3])
            require(fit['rms_m'] < M['u'] and min(fit['in_plane_spread_m']) > max(0.001,3*fit['rms_m']), 'Visible end plane is inadequate: '+str(fit))
            seam = np.array([api.plane_point(z['camera'],px,fit['coefficients'])['world_m'] for px in z['seam_pixels']]); w = seam[1]-seam[0]; width = float(np.linalg.norm(w)); w /= width
            old = np.array(M['envelope']); lengths = [float(np.linalg.norm(old[1]-old[0])),float(np.linalg.norm(old[3]-old[0]))]; length = max(lengths)
            inward = old[3]-old[0] if lengths[1] > lengths[0] else old[1]-old[0]
            if float(n@inward) < 0: n = -n
            if z['direction'] == 'opposite_end': n = -n
            up = np.cross(n,w)
            if up[2] < 0: up = -up
            up /= np.linalg.norm(up)
            require(abs(width-min(lengths)) < 3*M['u'] and up[2] > 0.95 and abs(n[2]) < 0.2, 'Measured end seam rejects the upright rigid model: '+str({'width_m':width,'reference_width_m':min(lengths),'up_z':float(up[2])}))
            top = np.array([seam[0],seam[1],seam[1]+length*n,seam[0]+length*n]); env = np.concatenate([top,top-M['height']*up]); u = M['u']+fit['rms_m']+0.0008+abs(width-min(lengths))/2
            D.update({'phase':'route','stage':0,'jaw_calls':0,'envelope':env.tolist(),'env0':env.tolist(),'state':s,'u':float(u),'u0':float(u),'length':length,'camera':reg['camera'],'quaternion':s['tcp_quaternion_xyzw'],'signature':None,'patch':None,'binding':{'frame_id':r['frame_id'],'face_region':{'camera':reg['camera'],'box':reg['box']},'seam_pixels':z['seam_pixels'],'seam_camera':z['camera'],'direction':z['direction'],'retention_error_m':err,'retention_uncertainty_m':ru,'bowl_residuals_m':[re,he],'route':z,'prior':'Measured rigid dimensions; stationary bowl only during noncontact, attachment-consistent short transfer. Search predictions are not detections.'}})
            try: D['signature'] = scan(env)
            except Exception as ex: log('finite_face_initialization',str(ex))
            if t is None:
                box = reg['box']; poly = [[box[0],box[1]],[box[2],box[1]],[box[2],box[3]],[box[0],box[3]]]; p = patch(reg['camera'],poly,M['object']+' identified narrow end face'); t = quality(p['handle']) if p else None
            if t is not None:
                D['patch'] = p; D['patch_envelope'] = geo.transform(env,np.linalg.inv(np.array(t['transform_initial_world_to_current_world']))).tolist()
            store(); require(D['signature'] is not None or D['patch'] is not None, 'No current independent motion witness; identified face geometry alone cannot justify blind transfer.')
            log('current_end_binding',{'uncertainty_m':u,'width_m':width,'length_m':length,'retention_error_m':err,'frame_id':r['frame_id']})
        def leg(target, purpose, held=True, reserve=18):
            s = api.state(); now = np.array(geo.pad_position(s)); target = np.array(target); b = s['budgets']
            require(b['jev_remaining'] > reserve+2 and b['native_steps_remaining'] > 3*(reserve+2), 'Insufficient actuation reserve for release and verification.')
            tol = M['tol']
            if held:
                env = np.array(D['envelope']); center = env[:4].mean(axis=0); radial = float(np.max(np.linalg.norm(env[:,:2]-center[:2],axis=1))); slack = M['bowl']['radius']-radial-D['u']-M['u']-0.0005
                require(slack > 0, 'Current fit gap: '+str({'slack_m':slack,'radius_m':radial,'u_m':D['u'],'opening_m':M['bowl']['radius']})); tol = max(0.0005,min(0.002,slack/3))
            D['intent'] = {'purpose':purpose,'target':target.tolist(),'frame_id':s['frame_id']}; store()
            receipt = api.drive(target.tolist(),D['quaternion'],'keep',Q,features={'purpose':purpose,'scope':'Bounded locally reviewed model, not collision certification','envelope_uncertainty_m':D['u']},tool_point='pad_center',max_calls=min(10,b['jev_remaining']-reserve),translation_limit=0.02,rotation_limit=0.05,steps=3,position_tolerance=tol,rotation_tolerance=0.025)
            after = api.state(); residual = float(np.linalg.norm(target-np.array(geo.pad_position(after)))); progress = float(np.linalg.norm(target-now))-residual
            C['last_motion'] = {'status':receipt['status'],'frame_id':receipt['frame_id'],'position_error_m':residual}; save()
            require(receipt['status'] == 'reached' or (receipt['status'] == 'lease_exhausted' and progress > 0.003), 'Local motion stalled or made inadequate progress: '+str(C['last_motion']))
            if held: measure()
            return residual <= tol
        if D['phase'] == 'route':
            env,u = measure()
            for stage in range(D['stage'],3):
                env = np.array(D['envelope']); s = api.state(); p0 = np.array(geo.pad_position(s)); target = p0.copy(); low = finger_low(s); rimz = M['bowl']['rim_z']
                if stage == 0: target[2] += max(0,rimz+0.025-float(env[:,2].min()),rimz+0.025-p0[2]-low)
                if stage == 1: target[:2] += np.array(M['bowl']['center'])-env[:4,:2].mean(axis=0)
                if stage == 2: target[2] += max(rimz+D['u']+0.006-float(env[:,2].min()),rimz+D['u']+0.008-p0[2]-low)
                require(float(np.linalg.norm(target-p0)) < 0.35, 'Continuation target exceeds the reviewed local scope.')
                arrived = False
                for k in range(12):
                    s = api.state(); p0 = np.array(geo.pad_position(s)); delta = target-p0
                    if np.linalg.norm(delta) <= 0.0005: arrived = True; break
                    if stage == 1:
                        require(min(float(np.array(D['envelope'])[:,2].min()),float(p0[2])+finger_low(s)) > rimz+D['u']+M['u'], 'Current height no longer supports noncontact horizontal progress.')
                    nextp = p0+delta*min(1,0.035/float(np.linalg.norm(delta)))
                    reached = leg(nextp,'independently observed retained stage '+str(stage))
                    if reached and np.linalg.norm(target-nextp) < 0.0001: arrived = True; break
                require(arrived, 'Finite leg bound exhausted; no continuation assumed.')
                D['stage'] = stage+1; store()
            for correction in range(2):
                env,u = measure(); s = api.state(); pad = np.array(geo.pad_position(s)); radial = float(np.max(np.linalg.norm(env[:,:2]-np.array(M['bowl']['center']),axis=1))); slack = M['bowl']['radius']-radial-u-M['u']-0.0005
                log('compact_release_gate',{'radial_slack_m':slack,'item_low_z':float(env[:,2].min()),'finger_low_z':float(pad[2])+finger_low(s),'rim_z':M['bowl']['rim_z'],'u_m':u})
                require(float(env[:,2].min()) > M['bowl']['rim_z']+u and float(pad[2])+finger_low(s) > M['bowl']['rim_z']+M['u'], 'Measured release height is insufficient.')
                if slack > 0: break
                delta = np.array(M['bowl']['center'])-env[:4,:2].mean(axis=0)
                require(correction == 0 and np.linalg.norm(delta) < 0.012, 'Containment cannot be resolved by one local correction.')
                pad[:2] += delta; leg(pad,'one measured containment correction')
            require(slack > 0, 'Release containment remains unresolved.'); D['phase'] = 'opening'; store()
        if D['phase'] == 'opening':
            for k in range(max(0,3-D['jaw_calls'])):
                s = api.state(); receipt = api.control(np.array(geo.pad_position(s)).tolist(),s['tcp_quaternion_xyzw'],'open',Q,features={'purpose':'Release transition; outcome still unobserved'},tool_point='pad_center',translation_limit=0.001,rotation_limit=0.01,steps=3,position_tolerance=M['tol'],rotation_tolerance=0.025)
                D['jaw_calls'] += 1; D['release_acknowledged'] = bool(api.state()['last_gripper_command'] == 'open' and receipt['acknowledged_steps'] > 0); store()
                require(D['release_acknowledged'] and receipt['status'] in ['reached','moved'], 'Release delivery failed; physical state remains as acknowledged.')
            D['phase'] = 'released'; D['withdraw_target'] = (np.array(geo.pad_position(api.state()))+np.array([0,0,0.06])).tolist(); store()
        if D['phase'] == 'released':
            reached = False
            for k in range(2):
                reached = leg(D['withdraw_target'],'post-release upward withdrawal',held=False,reserve=5)
                if reached: break
            require(reached, 'Withdrawal did not reach its bounded view target.'); D['phase'] = 'verify'; store()
        require(D['phase'] in ['verify','done'], 'Unrecognized placement continuation phase.')
        def metric_final():
            baseline = load('bowl_before_release',{}); require(bool(baseline),'No pre-release scene witness for metric identity recovery.')
            cal = api.camera('agentview'); require(float(np.max(np.abs(np.array(cal['camera_to_world_opencv'])-np.array(baseline['calibration'])))) < 0.00001,'Agentview changed; fixed-pixel novelty and stability are invalid.')
            cl = api.cloud('agentview',baseline['box'],stride=4); a = np.array(cl['world_m']); bowl = M['bowl']; u = M['u']; rad = np.linalg.norm(a[:,:2]-np.array(bowl['center']),axis=1)
            rim = a[(np.abs(a[:,2]-bowl['rim_z']) < 3*u)&(np.abs(rad-bowl['radius']) < 0.006)]
            require(len(rim) >= 12,'No current post-release rim support.')
            cir = geo.circle_xy(rim); rp = geo.plane(rim)
            require(cir['largest_angular_gap_rad'] < 3.6 and cir['max_radial_error_m'] < 3*u and rp['coefficients'][2] > 0.97 and abs(cir['radius_m']-bowl['radius']) < 3*u and np.linalg.norm(np.array(cir['center_xy_m'])-np.array(bowl['center'])) < 3*u,'Fresh rim contradicts stationary bowl or is insufficient: '+str(cir))
            candidates = np.nonzero((rad < bowl['radius']-u)&(a[:,2] > bowl['floor'][2]+0.5*M['height'])&(a[:,2] < bowl['rim_z']-u))[0]; horizontal = []
            for i in candidates[::max(1,len(candidates)//180)]:
                distances = np.linalg.norm(a-a[i],axis=1); ids = np.argsort(distances)[:9]
                if len(ids) < 9 or distances[ids[-1]] > 0.012: continue
                try:
                    fit = geo.plane(a[ids])
                    if fit['coefficients'][2] > 0.97 and fit['rms_m'] < 0.0007 and min(fit['in_plane_spread_m']) > 0.0008: horizontal.append(int(i))
                except Exception: continue
            require(len(horizontal) >= 24,'No independently observed package-sized horizontal surface below the rim.')
            fit = geo.plane(a[horizontal]); n = np.array(fit['coefficients'][:3]); d = fit['coefficients'][3]
            ids = [int(i) for i in candidates if abs(float(a[i]@n+d)) < 0.0012]; body = a[ids]
            require(len(body) >= 30 and fit['rms_m'] < 0.001 and n[2] > 0.97,'Final surface is not a coherent near-horizontal rigid face: '+str(fit))
            old = np.array(M['envelope']); dimensions = np.array([np.linalg.norm(old[3]-old[0]),np.linalg.norm(old[1]-old[0])]); hypotheses = []; worst = 0.0; highest = -1.0
            angle_margin = float(np.linalg.norm(dimensions)/2)*math.sin(math.pi/72); margin = u+angle_margin
            for k in range(72):
                theta = k*math.pi/72; x = np.array([math.cos(theta),math.sin(theta),0.0]); x -= n*float(x@n); x /= np.linalg.norm(x); y = np.cross(n,x)
                xy = body@np.column_stack([x,y]); lo = xy.min(axis=0); hi = xy.max(axis=0); cmin = hi-dimensions/2-u; cmax = lo+dimensions/2+u
                if bool(np.all(cmin <= cmax) and np.all(hi-lo > 0.7*dimensions)):
                    bound = np.array([x*vx+y*vy-n*d for vx in [cmin[0]-dimensions[0]/2,cmax[0]+dimensions[0]/2] for vy in [cmin[1]-dimensions[1]/2,cmax[1]+dimensions[1]/2]])
                    bound = np.concatenate([bound,bound-M['height']*n]); worst = max(worst,float(np.linalg.norm(bound[:,:2]-np.array(cir['center_xy_m']),axis=1).max())); highest = max(highest,float(bound[:,2].max())); hypotheses.append(k)
            require(len(hypotheses) > 0,'Current planar surface lacks a dimension-consistent finite package hypothesis.')
            opening = min(bowl['radius'],cir['radius_m']); rimz = float(rim[:,2].mean())
            log('metric_final_envelope',{'hypotheses':len(hypotheses),'worst_radius_m':worst,'opening_m':opening,'margin_m':margin,'highest_m':highest,'rim_z':rimz})
            require(worst+margin < opening and highest+margin < rimz,'Final finite-envelope hypotheses do not establish containment below the rim.')
            lookup = {tuple(p):i for i,p in enumerate(cl['pixels'])}; novelty = 0
            for px,world in baseline['samples']:
                if tuple(px) not in lookup: continue
                v = a[lookup[tuple(px)]]
                if abs(float(v@n+d)) < 0.0015 and world[2] < bowl['rim_z']-u and v[2]-world[2] > 0.5*M['height'] and np.linalg.norm(v[:2]-np.array(cir['center_xy_m'])) < opening-u: novelty += 1
            s = api.state(); separation = float(geo.pad_position(s)[2])+finger_low(s)-highest
            require(novelty >= 5 and separation > 0.02 and s['last_gripper_command'] == 'open','Released identity or finger separation is unresolved: '+str({'new_surface_samples':novelty,'finger_separation_m':separation}))
            selected = np.linspace(0,len(ids)-1,min(48,len(ids))).astype(int).tolist(); ids = [ids[i] for i in selected]
            return {'parameters':{'relation':'inside_supported','free':'yes','boundary':'visible'},'assessment_source':'Metric inference from new package-sized planar surface, conservative extent hypotheses, below-rim containment, finger separation, and subsequent stability; not a visual review or force measurement','metric':{'new_surface_samples':novelty,'finger_separation_m':separation,'worst_radius_m':worst,'margin_m':margin,'hypotheses':len(hypotheses)},'rim':rim[::max(1,len(rim)//24)][:32].tolist(),'surface':body[len(body)//2].tolist(),'frame_id':cl['frame_id'],'region':{'camera':'agentview','box':baseline['box']},'samples':[[cl['pixels'][i],cl['world_m'][i],cl['rgb'][i]] for i in ids],'native_steps':s['native_steps'],'wait_calls':0}
        F = load('placement_final_witness',{})
        if not F and api.state()['budgets']['gpt_remaining'] == 0:
            F = metric_final(); api.checkpoint('placement_final_witness',F)
        if not F:
            r = review('Assess the actual released runtime goal in this NEW view. relation=inside_supported only for the identified package visibly resting in the bowl interior, not bridging its rim, outside, above, or held. Other values: bridged, outside, still_held, unknown. free=yes only if visibly separated from both fingers, otherwise no or unknown. Request current package_surface and three separated inner-rim samples b0,b1,b2. Request region settled: a tight view of the visible package including a narrow physical boundary strip, mostly package, no hand, explicit camera/box/stride=4; prefer agentview. This region will measure RGB-D change over six actual steps, so an interior textureless plane alone is inadequate. boundary=visible only for this identifiable package boundary and texture, otherwise unknown.',{'relation':['inside_supported','bridged','outside','still_held','unknown'],'free':['yes','no','unknown'],'boundary':['visible','unknown']},{'object':M['object'],'destination':M['destination'],'release_acknowledged':D.get('release_acknowledged'),'prior_is_not_detection':True})
            rim = points(r,['b0','b1','b2']); require(len(rim) == 3 and 'package_surface' in r['points'] and 'settled' in r['regions'], 'Final relation lacks current rim, package, or stability-region measurements.')
            reg = r['regions']['settled']; cloud = api.cloud(reg['camera'],reg['box'],stride=4); require(len(cloud['world_m']) >= 24, 'Final stability region lacks depth support.')
            ids = np.linspace(0,len(cloud['world_m'])-1,min(48,len(cloud['world_m']))).astype(int).tolist()
            samples = [[cloud['pixels'][i],cloud['world_m'][i],cloud['rgb'][i]] for i in ids]
            F = {'parameters':r['parameters'],'rim':rim.tolist(),'surface':r['points']['package_surface']['world_m'],'frame_id':r['frame_id'],'region':{'camera':reg['camera'],'box':reg['box']},'samples':samples,'native_steps':api.state()['native_steps'],'wait_calls':0}
            api.checkpoint('placement_final_witness',F)
        for j in range(max(0,2-F['wait_calls'])):
            s = api.state(); receipt = api.control(np.array(geo.pad_position(s)).tolist(),s['tcp_quaternion_xyzw'],'keep',Q,features={'purpose':'Post-release six-step RGB-D stability observation'},tool_point='pad_center',translation_limit=0.001,rotation_limit=0.01,steps=3,position_tolerance=M['tol'],rotation_tolerance=0.025)
            F['wait_calls'] += 1; api.checkpoint('placement_final_witness',F); require(receipt['status'] in ['reached','moved'], 'Post-release observation hold failed.')
        cl = api.cloud(F['region']['camera'],F['region']['box'],stride=4); lookup = {tuple(p):i for i,p in enumerate(cl['pixels'])}; distances = []; colors = []
        for pixel0,world0,rgb0 in F['samples']:
            if tuple(pixel0) not in lookup: continue
            i = lookup[tuple(pixel0)]; distances.append(float(np.linalg.norm(np.array(cl['world_m'][i])-np.array(world0)))); colors.extend((np.array(cl['rgb'][i],dtype=float)-np.array(rgb0,dtype=float)).tolist())
        require(len(distances) >= 0.85*len(F['samples']), 'Current final view cannot revalidate the saved package/boundary witness.')
        scale = 255.0 if max(max(v[2]) for v in F['samples']) > 1 else 1.0
        drift = float(np.quantile(distances,0.9)); color_change = float(np.sqrt(np.mean(np.array(colors)**2))/scale); elapsed = api.state()['native_steps']-F['native_steps']
        stable = elapsed >= 6 and drift < max(0.002,1.5*M['u']) and color_change < 0.025 and F['parameters']['boundary'] == 'visible'
        rim = np.array(F['rim']); cir = geo.circle_xy(rim); pl = geo.plane(rim); point = np.array(F['surface'])
        geometric = cir['largest_angular_gap_rad'] < 3.6 and pl['coefficients'][2] > 0.98 and abs(cir['radius_m']-M['bowl']['radius']) < 3*M['u'] and np.linalg.norm(point[:2]-np.array(cir['center_xy_m'])) < cir['radius_m']-M['u']
        proposed = bool(stable and geometric and F['parameters']['relation'] == 'inside_supported' and F['parameters']['free'] == 'yes')
        log('final_actual_effect',{'assessment':F['parameters'],'assessment_source':F.get('assessment_source','Structured current visual review and metric checks'),'metric':F.get('metric'),'reference_frame':F['frame_id'],'current_frame':cl['frame_id'],'drift_p90_m':drift,'rgb_rms_normalized':color_change,'elapsed_steps':elapsed,'geometric_relation':bool(geometric),'stable':bool(stable)})
        D['phase'] = 'done' if proposed else 'verify'; D['proposal'] = proposed; store()
        return {'completion_proposed':proposed,'evidence':{'phase':C['phase'],'binding':D['binding'],'final':E[-1],'measurements':E,'limitations':'Local rigid-face and stationary-bowl hypotheses with heuristic uncertainty; no complete collision certificate or official success claim.'}}
    try:
        C.update(load('phase',{})); M.update(load('model',{})); H.update(load('hold',{}))
        if C['phase'] in ['retained','compact_route','compact_opening','compact_released','compact_verify','compact_done']: return resume_placement()
        if not M:
            fields = {'object':text,'destination':text,'model':['rigid_rectangular_package_on_table_and_round_open_bowl','unsupported','unknown'],'corner_camera':['agentview','robot0_eye_in_hand'],'corner_pixels':{'type':['array','null'],'items':pixel,'minItems':4,'maxItems':4},'corner_definitions':{'type':'array','items':text,'minItems':4,'maxItems':4},'mark_definitions':defs3}
            for attempt in range(2):
                try:
                    r = review('Resolve the runtime instruction. Identify object and destination. model may approve only a rigid rectangular package resting flat on the table and an unobstructed round open bowl. Request regions top (tight interior textured package face) and table (unoccluded support beside it), explicit camera/box/stride=6. Supply four genuinely visible top corner_pixels cyclically in corner_camera, with persistent physical corner_definitions c0..c3 tied to printing, not screen directions. Request named points f0,f1,f2 at three identifiable printed physical marks with mark_definitions; these are optional if tracking works. Request six widely spaced INNER bowl-rim points b0..b5 and one visible interior low point floor. Do not confuse background depths or a surface with a hidden underside. On a retry replace failed measurements using the other view or cleaner interior regions.',fields,{'previous_failures':E[-2:]})
                    z = r['parameters']; require(z['model'] == 'rigid_rectangular_package_on_table_and_round_open_bowl' and z['corner_pixels'] is not None,'Unsupported or unknown measured object/receptacle model.')
                    require('top' in r['regions'] and 'table' in r['regions'],'Missing top or support depth region.')
                    top = geo.plane(r['regions']['top']['world_m']); table = geo.plane(r['regions']['table']['world_m']); n = np.array(top['coefficients'][:3]); sn = np.array(table['coefficients'][:3])
                    require(n[2] > 0.98 and sn[2] > 0.98 and np.linalg.norm(n-sn) < 0.03,'Top/support are not consistent nearly horizontal planes.')
                    corners = np.array([api.plane_point(z['corner_camera'],p,top['coefficients'])['world_m'] for p in z['corner_pixels']])
                    rim = points(r,['b'+str(i) for i in range(6)]); require(len(rim) == 6 and 'floor' in r['points'],'Missing bowl opening or interior measurement.')
                    circ = geo.circle_xy(rim); rp = geo.plane(rim); u = max(0.0015,3*top['rms_m'],3*table['rms_m'],circ['max_radial_error_m']+0.0008)
                    center = corners.mean(axis=0); height = float((sn@center+table['coefficients'][3])/(sn@n)); e0 = corners[1]-corners[0]; e1 = corners[3]-corners[0]; lengths = [float(np.linalg.norm(e0)),float(np.linalg.norm(e1))]
                    require(circ['largest_angular_gap_rad'] < 2.4 and rp['coefficients'][2] > 0.98 and rp['rms_m'] < 2*u,'Bowl opening lacks adequate horizontal circular evidence.')
                    require(min(lengths) > 6*u and height > 2*u and np.linalg.norm(corners[0]+corners[2]-corners[1]-corners[3]) < 5*u and abs(float(e0@e1))/max(lengths) < 4*u,'Rectangular model fails extent or residual check: '+str({'edges':lengths,'height':height,'u':u}))
                    require(r['points']['floor']['world_m'][2] < float(rim[:,2].mean())-u,'Bowl interior depth is not observed.')
                    s = api.state(); R0 = geo.rotation(s['tcp_quaternion_xyzw']); short = e0 if lengths[0] < lengths[1] else e1; short = short/np.linalg.norm(short)
                    if float(short@R0[:,1]) < 0: short = -short
                    require(R0[2,2] < -0.95,'Current tool is not sufficiently downward; unsupported orientation change.')
                    yaw = math.atan2(float(R0[0,1]*short[1]-R0[1,1]*short[0]),float(R0[0,1]*short[0]+R0[1,1]*short[1])); q = api.compose(s['tcp_quaternion_xyzw'],[0,0,yaw]); R = geo.rotation(q)
                    own = s['own_geometry']; off = np.array(own['pad_center_in_tool_m']); low = own['finger_low_offset_tool_m']; high = own['finger_high_offset_tool_m']; pe = np.array(own['pad_extent_in_tool_m'])
                    fc = np.array([[x,y,zv] for x in [low[0],high[0]] for y in [low[1],high[1]] for zv in [low[2],high[2]]]); fmin = float(np.min(((fc-off)@R.T)[:,2])); band = float(np.abs(R[2,:])@pe/2)
                    bottom = corners-height*n; floorz = float(bottom[:,2].max()); topz = float(corners[:,2].min()); overlap = min(topz-floorz,2*band)*0.35
                    lo = max(floorz-band+overlap,floorz-fmin+u+0.001); hi = topz+band-overlap
                    log('contact_intervals',{'lower_pad_z':lo,'upper_pad_z':hi,'overlap_m':overlap,'width_m':min(lengths),'outer_pad_span_m':float(pe[1]),'uncertainty_m':u})
                    require(overlap > u and lo <= hi and min(lengths)+2*u < pe[1],'Measured contact band/support-clearance constraints are infeasible. Outer pad span alone does not prove an inner jaw gap.')
                    grasp = center.copy(); grasp[2] = min(hi,max(lo,topz-0.3*(topz-floorz))); env = np.concatenate([corners,bottom]); radius = float(np.max(np.linalg.norm(env[:,:2]-center[:2],axis=1)))
                    require(radius+3*u+0.002 < circ['radius_m'],'Package envelope cannot fit measured bowl opening with the current uncertainty margin.')
                    bank = [{'name':'c'+str(i),'definition':z['corner_definitions'][i],'world':corners[i].tolist()} for i in range(4)]
                    for i in range(3):
                        name = 'f'+str(i)
                        if name in r['points'] and abs(float(n@np.array(r['points'][name]['world_m'])+top['coefficients'][3])) < 2*u: bank.append({'name':name,'definition':z['mark_definitions'][i],'world':r['points'][name]['world_m']})
                    reg = r['regions']['top']; box = reg['box']; poly = [[box[0],box[1]],[box[2],box[1]],[box[2],box[3]],[box[0],box[3]]]
                    M.update({'object':z['object'],'destination':z['destination'],'frame_id':r['frame_id'],'bank':bank,'envelope':env.tolist(),'u':u,'tol':max(0.0005,min(0.002,u)),'radius':radius,'height':height,'quaternion':q,'opening_axis':R[:,1].tolist(),'finger_min_z':fmin,'grasp':grasp.tolist(),'hover_z':topz-fmin+max(0.012,3*u),'overlap':overlap,'open_span':float(pe[1]),'bowl':{'center':circ['center_xy_m'],'radius':circ['radius_m'],'rim_z':float(rim[:,2].mean()),'floor':r['points']['floor']['world_m']},'patch':patch(reg['camera'],poly,z['object'])})
                    api.checkpoint('model',M); C['phase'] = 'approach'; save(); break
                except Exception as ex:
                    log('survey_retry',str(ex))
                    if attempt == 1: raise ValueError('Current geometric model unavailable: '+str(ex))
        if C['phase'] in ['new','approach']:
            resume_effect = C.get('intent',{}).get('purpose') == 'visually bracketed open-finger descent'
            if resume_effect:
                log('resume_achieved_descent',{'last_motion':C.get('last_motion'),'policy':'No repeated descent or high approach. Measure achieved local effect first.'})
            else:
                prepare_approach()
                p = np.array(geo.pad_position(api.state())); high = max(float(p[2]),M['hover_z'],M['bowl']['rim_z']-M['finger_min_z']+0.03)
                travel([float(p[0]),float(p[1]),high],'noncontact raise')
                travel([M['grasp'][0],M['grasp'][1],high],'high noncontact alignment')
                travel([M['grasp'][0],M['grasp'][1],M['hover_z']],'open-finger hover')
                grasp_check(False); travel(M['grasp'],'visually bracketed open-finger descent')
            grasp_check(); C.update({'phase':'closing','jaw_calls':0,'approach_effect_pending':False}); save()
        if C['phase'] == 'closing' or (C['phase'] == 'closed' and C['jaw_calls'] < 3): jaw('close')
        if C['phase'] in ['closed','test']:
            for attempt in range(2):
                if C['phase'] != 'test':
                    require(C['trials'] < 2,'Retention trial bound exhausted.')
                    L = reference(); goal = np.array(geo.pad_position(api.state()))+np.array([0,0,max(0.03,8*L['u'])]); L['goal'] = goal.tolist(); api.checkpoint('local',L)
                    C['trials'] += 1; C['phase'] = 'test'; save()
                else: L = load('local',{})
                travel(L['goal'],'small upward observation-producing retention trial')
                try:
                    a,b,u = compare(L); s = api.state(); hand = np.array(s['tcp_position_world_m'])-np.array(L['before']['tcp_position_world_m']); motion = np.mean(b-a,axis=0); error = geo.attachment_error(a.tolist(),b.tolist(),L['before'],s)
                    log('retention_test',{'hand_motion_m':hand.tolist(),'object_motion_m':motion.tolist(),'attachment_error_m':error,'uncertainty_m':u+L['u']})
                    retained = hand[2] > max(0.012,4*(u+L['u'])) and motion[2] > 0.65*hand[2] and error < u+L['u']+0.004
                except Exception as ex: log('retention_unknown',str(ex)); retained = False
                if retained: C['phase'] = 'retained'; C['stage'] = 0; save(); break
                C['phase'] = 'closed'; save()
                require(C['trials'] < 2,'Retention not established; do not reopen or transfer.')
                log('recovery','Next trial uses a fresh identified local reference, not a predicted object transform.')
            require(C['phase'] == 'retained','Retention evidence unavailable.')
        if C['phase'] == 'retained': return resume_placement()
        if C['phase'] in ['retained','transfer']:
            env,u = refresh_hold(); C['phase'] = 'transfer'; save()
            for stage in range(C['stage'],3):
                env,u = refresh_hold(); p = np.array(geo.pad_position(api.state())); center = env[:4].mean(axis=0); radial = float(np.max(np.linalg.norm(env[:,:2]-center[:2],axis=1)))
                require(radial+u+M['u']+0.0005 < M['bowl']['radius'],'Current transported envelope has no positive measured containment slack: '+str({'radius':radial,'envelope_uncertainty':u,'bowl_uncertainty':M['u'],'guard':0.0005,'opening':M['bowl']['radius']}))
                target = p.copy()
                if stage == 0: target[2] += max(0,M['bowl']['rim_z']+0.025-float(env[:,2].min()),M['bowl']['rim_z']+0.025-(float(p[2])+M['finger_min_z']))
                if stage == 1: target[:2] += np.array(M['bowl']['center'])-center[:2]
                if stage == 2: target[2] += max(M['bowl']['rim_z']+u+0.003-float(env[:,2].min()),M['bowl']['rim_z']+u+0.005-(float(p[2])+M['finger_min_z']))
                travel(target,'retained transfer stage '+str(stage),held=True); C['stage'] = stage+1; save()
            env,u = refresh_hold(); p = np.array(geo.pad_position(api.state()))
            require(float(env[:,2].min()) > M['bowl']['rim_z']+u and float(p[2])+M['finger_min_z'] > M['bowl']['rim_z']+M['u'],'Actual item/finger height does not support a noncontact release.')
            r = review('Before release, request at least two separated CURRENT visible inner bowl-rim samples named b0,b1,b2; these are new samples, not old landmark correspondences. relation is centered_over_opening only if this package is over the open bowl interior, not another object or blocked bowl; otherwise blocked or unknown. prior is consistent only if the same bowl remains stationary with unchanged orientation and no rim contact or displacement contradicts the retained model, otherwise changed or unknown. Hidden rim pixels are not evidence of motion and a full circumference certificate is not requested.',{'relation':['centered_over_opening','blocked','unknown'],'prior':['consistent','changed','unknown']},{'bowl_prior':M['bowl'],'object':M['object'],'envelope':env.tolist(),'envelope_uncertainty_m':u,'finger_lowest_z':float(p[2])+M['finger_min_z']})
            rim = points(r,['b0','b1','b2']); require(len(rim) >= 2,'No current partial bowl-opening witness.')
            radial_error = float(np.max(np.abs(np.linalg.norm(rim[:,:2]-np.array(M['bowl']['center']),axis=1)-M['bowl']['radius'])))
            height_error = float(np.max(np.abs(rim[:,2]-M['bowl']['rim_z']))); log('release_bowl_prior',{'radial_error_m':radial_error,'height_error_m':height_error,'u_m':M['u'],'samples':len(rim)})
            require(r['parameters']['relation'] == 'centered_over_opening' and r['parameters']['prior'] == 'consistent' and radial_error < 3*M['u'] and height_error < 3*M['u'],'Stationary bowl prior contradicted or release relation unresolved.')
            cir = {'center_xy_m':M['bowl']['center'],'radius_m':M['bowl']['radius']}
            for correction in range(2):
                env,u = refresh_hold(); center = env[:4].mean(axis=0); radius = float(np.max(np.linalg.norm(env[:,:2]-np.array(cir['center_xy_m']),axis=1)))
                contained = radius+u+M['u']+0.0005 < cir['radius_m']
                log('release_containment',{'radius_about_bowl_m':radius,'envelope_u_m':u,'bowl_u_m':M['u'],'guard_m':0.0005,'opening_m':cir['radius_m']})
                if contained: break
                localradius = float(np.max(np.linalg.norm(env[:,:2]-center[:2],axis=1)))
                delta = np.array(cir['center_xy_m'])-center[:2]
                require(correction == 0 and localradius+u+M['u']+0.0005 < cir['radius_m'] and np.linalg.norm(delta) <= 0.012, 'Release gap is not resolvable by one small centering correction.')
                target = np.array(geo.pad_position(api.state())); target[:2] += delta
                travel(target,'fine measured containment correction',held=True)
            require(contained,'Measured release envelope remains outside the uncertainty margin.')
            C.update({'phase':'opening','jaw_calls':0}); save()
        if C['phase'] == 'opening' or (C['phase'] == 'released' and C['jaw_calls'] < 3): jaw('open')
        require(C['phase'] in ['released','verifying','done'],'Unknown persisted phase; no motion inferred.')
        if C['phase'] == 'released':
            travel(np.array(geo.pad_position(api.state()))+np.array([0,0,0.05]),'post-release withdrawal for a new view',final=True); C['phase'] = 'verifying'; save()
        stable = False
        for attempt in range(2):
            L = reference(); api.checkpoint('verification_reference',L)
            for j in range(2):
                s = api.state(); receipt = api.control(np.array(geo.pad_position(s)).tolist(),s['tcp_quaternion_xyzw'],'keep',Q,features={'purpose':'Six-step post-release observation interval; do not contact the object.'},tool_point='pad_center',translation_limit=0.001,rotation_limit=0.01,steps=3,position_tolerance=M['tol'],rotation_tolerance=0.025)
                require(receipt['status'] in ['reached','moved'],'Post-release hold failed.')
            a,b,u = compare(L); drift = float(np.max(np.linalg.norm(b-a,axis=1))); elapsed = api.state()['native_steps']-L['before']['native_steps']; stable = elapsed >= 6 and drift < max(0.003,L['u']+u)
            log('post_release_stability',{'drift_m':drift,'allowance_m':max(0.003,L['u']+u),'native_steps':elapsed})
            if stable: break
        r = review('Assess the actual runtime goal after release, not the commanded placement. relation is inside_supported only when the identified package is visibly resting in the bowl interior, not balanced across its rim, above it, outside it, or held by the robot. Other values are bridged, outside, still_held, unknown. free is yes only for visible separation from both fingers; otherwise no or unknown. Request current package_surface and three widely separated current inner rim points b0,b1,b2. These measurements must be fresh because release may move the bowl.',{'relation':['inside_supported','bridged','outside','still_held','unknown'],'free':['yes','no','unknown']},{'object':M['object'],'destination':M['destination'],'stability':E[-1]})
        rim = points(r,['b0','b1','b2']); require(len(rim) == 3 and 'package_surface' in r['points'],'Final geometric relation lacks obtainable measurements.'); cir = geo.circle_xy(rim); plane = geo.plane(rim); point = np.array(r['points']['package_surface']['world_m'])
        geometric = cir['largest_angular_gap_rad'] < 3.6 and plane['coefficients'][2] > 0.98 and abs(cir['radius_m']-M['bowl']['radius']) < 3*M['u'] and np.linalg.norm(point[:2]-np.array(cir['center_xy_m'])) < cir['radius_m']-M['u']
        proposed = bool(stable and geometric and r['parameters']['relation'] == 'inside_supported' and r['parameters']['free'] == 'yes')
        C['phase'] = 'done' if proposed else 'verifying'; C['proposal'] = proposed; save()
        return {'completion_proposed':proposed,'evidence':{'phase':C['phase'],'final_review':r['parameters'],'final_frame_id':r['frame_id'],'stable':stable,'geometric_relation':bool(geometric),'measurements':E,'limitations':'Finite visual/metric evidence and heuristic uncertainty, not a collision certificate or official evaluator success.'}}
    except Exception as ex:
        log('stopped',str(ex))
        return {'completion_proposed':False,'evidence':{'phase':C['phase'],'gap':str(ex),'last_acknowledged_motion':C.get('last_motion'),'jaw_calls':C['jaw_calls'],'retention_trials':C['trials'],'measurements':E,'recovery_policy':'Physical state persists. Do not reopen a possibly held object or disturb a released object merely because a measurement failed.'}}

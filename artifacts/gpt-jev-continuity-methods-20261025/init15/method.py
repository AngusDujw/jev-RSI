def main(api):
    evidence = []
    try:
        return execute(api, evidence)
    except Exception as exc:
        evidence.append({'stopped': str(exc)})
        return {'completion_proposed': False, 'evidence': evidence}

def execute(api, E):
    Q = {}
    for axis in ['x', 'y', 'z', 'rx', 'ry', 'rz']:
        Q[axis] = {'type': 'choice', 'instructions': 'Control world axis '+axis+'. Read state.processed_features.axes.'+axis+'.goal_relation. Select positive for increase, negative for decrease, hold for within_tolerance. Do not infer object effects.', 'criteria': {'negative': 'This axis says decrease.', 'hold': 'This axis says within_tolerance.', 'positive': 'This axis says increase.'}}
    Q['gripper'] = {'type': 'choice', 'instructions': 'Read state.processed_features.objective.gripper. Select exactly that requested jaw action; do not change it because of an imagined grasp.', 'criteria': {'open': 'Objective requests open.', 'close': 'Objective requests close.', 'keep': 'Objective requests keep.'}}
    keys = [x['key'] for x in api.recall()]
    C = api.recall('package_vessel')['value'] if 'package_vessel' in keys else {}
    pixel = {'type': 'array', 'items': {'type': 'integer', 'minimum': 0, 'maximum': 767}, 'minItems': 2, 'maxItems': 2}
    definitions = {'type': ['array', 'null'], 'items': {'type': 'string', 'maxLength': 500}, 'minItems': 3, 'maxItems': 3}
    def save():
        C['recent_evidence'] = E[-6:]
        api.checkpoint('package_vessel', C)
    def need(ok, message):
        if not ok:
            raise RuntimeError(message)
    def xyz(receipt):
        return np.array(receipt['world_m'], dtype=float)
    def note_review(r):
        if r['measurement_errors']:
            E.append({'frame': r['frame_id'], 'measurement_errors': r['measurement_errors']})
        need(r['status'] != 'stop', 'Visual review requested stop: '+r['explanation'])
    def fit_top(r):
        if 'top' not in r['regions']:
            return None
        a = xyz(r['regions']['top'])
        need(len(a) >= 12, 'Insufficient measured top-face samples')
        p = geo.plane(a); co = np.array(p['coefficients'])
        a = a[np.abs(a @ co[:3] + co[3]) < 0.004]
        need(len(a) >= 12, 'Top region does not supply a coherent plane')
        return geo.plane(a)
    if not C:
        A = api.recall('acquisition')['value'] if 'acquisition' in keys else None
        if A is None or A['frame'] != api.state()['frame_id']:
            fields = {'source_name': 'string', 'vessel_name': 'string', 'kind': ['rigid_rectangular_package', 'unsupported', 'unknown'], 'supported': ['on_visible_table', 'no', 'unknown'], 'identity': ['unique', 'ambiguous', 'unknown'], 'camera': ['agentview', 'robot0_eye_in_hand'], 'corners': {'type': ['array', 'null'], 'items': pixel, 'minItems': 4, 'maxItems': 4}, 'patch': {'type': ['array', 'null'], 'items': pixel, 'minItems': 3, 'maxItems': 12}, 'definitions': definitions}
            r = api.review('Interpret the user request and identify source_name and vessel_name. kind must describe the observed source, not an assumed hidden shape. supported means the package visibly rests on the measured table with upright sides. identity must be unique. Choose camera for its flat top. Return corners as four genuinely visible top-face corner pixels in cyclic order, or null; patch as a textured interior polygon in that same camera, or null. Request region top tightly inside the top face using explicit camera, box, stride=4. Request f0,f1,f2 at three spread, noncollinear, distinctive physical marks on that top; definitions must describe the persistent physical marks, never screen-relative corners. Request a0,a1,a2 on the nearby supporting tabletop, base on the visible lowest package side next to that support, b0 through b5 spread around the bowl INNER opening rim, and well on its visible interior bottom. Use whichever camera measures each point best. Do not mark hidden boundaries. Return unknown/null rather than guessing.', context={'user_request': 'could you put the cream cheese into the bowl'}, fields=fields)
            note_review(r)
            A = {'frame': r['frame_id'], 'p': r['parameters'], 'points': r['points'], 'top': None}
            api.checkpoint('acquisition', A)
            A['top'] = fit_top(r); api.checkpoint('acquisition', A)
        p = A['p']; need(p['identity'] == 'unique' and p['kind'] == 'rigid_rectangular_package' and p['supported'] == 'on_visible_table', 'Source identity, rectangular geometry, or visible support is unresolved')
        names = ['f0', 'f1', 'f2', 'a0', 'a1', 'a2', 'base', 'well']
        missing = [n for n in names if n not in A['points']]
        if missing or A['top'] is None or sum(n in A['points'] for n in ['b0','b1','b2','b3','b4','b5']) < 5:
            r = api.review('Replace failed measurements, using different usable interior samples where appropriate. Request these missing named points: '+str(missing)+'. Also request b0 through b5 on the inner rim if fewer than five were measured. If top_plane_missing, request region top tightly inside the flat face, with explicit camera, box, stride=4. Keep all supplied physical landmark definitions and object identities. identity means the same uniquely identified source and vessel.', context={'acquisition': A, 'top_plane_missing': A['top'] is None}, fields={'identity': ['unique','ambiguous','unknown']})
            note_review(r); need(r['parameters']['identity'] == 'unique', 'Replacement identity ambiguous')
            A['points'].update(r['points'])
            if A['top'] is None:
                A['top'] = fit_top(r)
            api.checkpoint('acquisition', A)
        P = A['points']; need(all(n in P for n in names) and A['top'] is not None and p['corners'] is not None and p['definitions'] is not None, 'Missing essential measured source/support geometry')
        top = A['top']; table = geo.plane([P[n]['world_m'] for n in ['a0','a1','a2']])
        rim = [P[n]['world_m'] for n in ['b0','b1','b2','b3','b4','b5'] if n in P]
        need(len(rim) >= 5, 'Insufficient distributed inner-rim samples')
        bp = geo.plane(rim); circle = geo.circle_xy(rim)
        E.append({'top_fit': top, 'support_fit': table, 'rim_fit': bp, 'opening_fit': circle})
        need(top['rms_m'] <= 0.0025 and table['rms_m'] <= 0.003 and bp['rms_m'] <= 0.004 and min(top['in_plane_spread_m']) > 0.003, 'Surface fits inadequate; see numerical fit evidence')
        need(min(top['coefficients'][2], table['coefficients'][2], bp['coefficients'][2]) > 0.97 and circle['max_radial_error_m'] < 0.006 and circle['largest_angular_gap_rad'] < 2.0, 'Nonhorizontal or insufficiently constrained opening/support')
        V = np.array([api.plane_point(p['camera'], px, top['coefficients'])['world_m'] for px in p['corners']]); center = V.mean(axis=0)
        e0 = V[1]-V[0]; e1 = V[3]-V[0]; l0 = float(np.linalg.norm(e0)); l1 = float(np.linalg.norm(e1))
        need(min(l0,l1) > 0 and abs(float(np.dot(e0,e1)))/(l0*l1) < 0.12 and np.linalg.norm(V[2]-V[1]-V[3]+V[0]) < 0.005, 'Visible top is not a consistent rectangle')
        co = np.array(table['coefficients']); support_z = float(-(co[0]*center[0]+co[1]*center[1]+co[3])/co[2]); h = float(center[2]-support_z)
        F = np.array([P[n]['world_m'] for n in ['f0','f1','f2']]); tc = np.array(top['coefficients'])
        need(np.max(np.abs(F @ tc[:3]+tc[3])) < 0.004 and np.linalg.svd(F-F.mean(axis=0), compute_uv=False)[1] > 0.004, 'Reference marks are off the measured face or poorly distributed')
        bc = np.array(circle['center_xy_m']); rim_z = float(np.mean(np.array(rim)[:,2])); u = max(0.002, top['rms_m'], table['rms_m'], bp['rms_m'], circle['rms_m'])
        safe_radius = float(circle['radius_m']-circle['max_radial_error_m']-2*u)
        need(abs(float(np.dot(co[:3], xyz(P['base']))+co[3])) < 0.009 and h > 0 and xyz(P['well'])[2] < rim_z-0.012 and np.linalg.norm(xyz(P['well'])[:2]-bc) < circle['radius_m']*0.7, 'Visible support/base or receiving cavity is not established')
        s = api.state(); q = s['tcp_quaternion_xyzw']; R = geo.rotation(q); own = s['own_geometry']
        need(R[2,2] < -0.95 and s['last_gripper_command'] == 'open', 'Acquisition requires a downward, currently open, unladen gripper')
        short = e0/l0 if l0 < l1 else e1/l1
        if np.dot(short, R[:,1]) < 0:
            short = -short
        yaw = math.atan2(R[0,1]*short[1]-R[1,1]*short[0], R[0,1]*short[0]+R[1,1]*short[1])
        if abs(yaw) > 0.12:
            q = api.compose(q, [0.0,0.0,yaw]); R = geo.rotation(q)
        width = float(np.ptp(V @ R[:,1])); aperture = float(sum(abs(v) for v in s['gripper_qpos_m'])); margin = u+0.003
        lo = own['finger_low_offset_tool_m']; hi = own['finger_high_offset_tool_m']; off = np.array(own['pad_center_in_tool_m'])
        envelope = np.array([[x,y,z] for x in [lo[0],hi[0]] for y in [lo[1],hi[1]] for z in [lo[2],hi[2]]])
        low = float(np.min(((envelope-off) @ R.T)[:,2])); ph = float(np.sum(np.abs(R[2,:])*np.array(own['pad_extent_in_tool_m']))/2)
        side_top = float(np.min(V[:,2])); minimum_overlap = min(ph,h/3)
        # [gz-ph,gz+ph] overlaps [support_z,side_top] by minimum_overlap.
        height_lower = float(max(support_z+minimum_overlap-ph, support_z+margin-low))
        height_upper = float(side_top+ph-minimum_overlap)
        gz = float(max(height_lower,min(float(center[2]-0.65*ph),height_upper)))
        inset = float(center[2]-gz)
        overlap = float(min(gz+ph,side_top)-max(gz-ph,support_z)); radius = float(np.max(np.linalg.norm(V[:,:2]-center[:2],axis=1)))
        E.append({'width_m': width, 'joint_aperture_estimate_m': aperture, 'height_m': h, 'finger_low_relative_pad_m': low, 'grasp_inset_m': inset, 'pad_band_half_height_m': ph, 'minimum_planned_overlap_m': minimum_overlap, 'feasible_pad_height_interval_m': [height_lower,height_upper], 'chosen_pad_height_m': gz, 'contact_band_overlap_m': overlap, 'planned_finger_support_clearance_m': float(gz+low-support_z), 'support_margin_m': margin, 'package_radius_m': radius, 'usable_opening_radius_m': safe_radius, 'uncertainty_heuristic_m': u})
        need(width+2*margin < aperture and 0 < minimum_overlap <= min(2*ph,side_top-support_z) and height_lower <= height_upper and overlap+1e-9 >= minimum_overlap and radius+u < safe_radius, 'Measured grasp interval, support clearance, or opening constraints infeasible; see numerical evidence')
        C.update({'phase':'approach', 'identity':{'source':p['source_name'],'vessel':p['vessel_name']}, 'definitions':p['definitions'], 'fiducials':{n:P[n] for n in ['f0','f1','f2']}, 'F':F.tolist(), 'V':V.tolist(), 'bottom':(V-np.array([0,0,h])).tolist(), 'center':center.tolist(), 'grasp':[float(center[0]),float(center[1]),gz], 'height':h, 'support_plane':table['coefficients'], 'minimum_planned_overlap_m':minimum_overlap, 'grasp_pad_height_interval_m':[height_lower,height_upper], 'bowl_xy':bc.tolist(), 'rim_z':rim_z, 'radius':float(circle['radius_m']), 'safe_radius':safe_radius, 'u':u, 'quaternion':q, 'geometry_frame':A['frame'], 'geometry_evidence':E[-2:], 'tracker':None, 'view_trials':0})
        save()
        if p['patch'] is not None:
            try:
                t = api.track_init(p['camera'], p['patch']); C['tracker'] = {'receipt':t,'camera':p['camera'],'polygon':p['patch'],'surface':p['source_name']+' flat printed top','reference_frame':t['frame_id']}; save()
            except Exception as exc:
                E.append({'optional_tracker_init_failed':str(exc)}); save()
    else:
        E.append({'restored_phase':C['phase'], 'historical_geometry':C['geometry_evidence']})
    def lease(target, phase, position_tolerance=0.003):
        s = api.state(); b = s['budgets']; calls = min(18, b['jev_remaining']-6, (b['native_steps_remaining']-18)//3)
        need(calls >= 1, 'Insufficient control reserve')
        C['intent'] = {'phase':phase,'pad_target':target,'frame':s['frame_id']}; save()
        a = api.drive(target, C['quaternion'], 'keep', Q, features={'phase':phase,'identity':C['identity'],'point_convention':'target is pad_center; not TCP','holding_claim': 'hold' in C}, max_calls=int(calls), tool_point='pad_center', translation_limit=0.02, rotation_limit=0.08, steps=3, position_tolerance=position_tolerance, rotation_tolerance=0.04)
        now = api.state(); progress = float(np.linalg.norm(geo.pad_position(now)-geo.pad_position(s)))
        C['last_ack'] = {'frame':a['frame_id'],'status':a['status'],'phase':phase,'position_error_m':a['position_error_m'],'rotation_error_rad':a['rotation_error_rad'],'lease_calls':a['lease_calls'],'actual_pad_progress_m':progress}; E.append(C['last_ack']); save()
        need(a['status'] != 'stalled', 'Stalled lease; no repeated contact push')
        need(a['status'] == 'reached' or progress > 0.002 or a['rotation_error_rad'] < 0.04, 'Lease exhausted without useful progress')
        return a
    def observe():
        for attempt in range(2):
            T = None; uncertainty = None
            if C['tracker'] is not None:
                t = api.track_update(C['tracker']['receipt']['handle'])
                if t['status'] == 'tracked':
                    uncertainty = max(0.0015, float(t['uncertainty_floor_m']), 2*float(t['rms_m']))
                    spread = sorted([float(v) for v in t['inlier_spread_m']], reverse=True)
                    required = [3*uncertainty, 2*uncertainty]
                    coverage = len(spread) >= 2 and spread[0] >= required[0] and spread[1] >= required[1]
                    accepted = bool(t['reference_frame_id'] == C['tracker']['reference_frame'] and t['inliers'] >= 12 and t['inliers']/max(1,t['matches']) >= 0.55 and coverage and uncertainty <= 0.004)
                    E.append({'registration_frame':t['frame_id'],'reference_frame':t['reference_frame_id'],'inliers':t['inliers'],'matches':t['matches'],'rms_m':t['rms_m'],'uncertainty_m':uncertainty,'spread_descending_m':spread,'required_two_spreads_m':required,'accepted':accepted,'meaning':'Resolved planar patch registration; heuristic uncertainty, not grasp evidence.'})
                    if accepted:
                        T = np.array(t['transform_initial_world_to_current_world'])
                else:
                    E.append({'registration_unknown':t['reason'],'frame':t['frame_id']})
                save()
            if T is None:
                r = api.review('Recover CURRENT registration of the same source surface. Request f0,f1,f2 at the exact physical marks in definitions, using the saved observations only as reference identity, not current detections. identity=unique only for unambiguous correspondence. quality=usable requires visible depth-valid, spread, rigid same-surface marks. Do not predict their positions from hand motion. If correspondence is unavailable, view_up=justified only if raising the current hand 0.025 m with unchanged jaws is locally unobstructed and likely to reveal these marks in a different view; otherwise blocked or unknown. Do not require the whole package perimeter.', context={'identity':C['identity'],'definitions':C['definitions'],'reference_measurements':C['fiducials'],'phase':C['phase'],'last_observation':C.get('last_observation')}, fields={'identity':['unique','ambiguous','unknown'],'quality':['usable','poor','unknown'],'view_up':['justified','blocked','unknown']})
                note_review(r); p = r['parameters']
                if p['identity'] == 'unique' and p['quality'] == 'usable' and all(n in r['points'] for n in ['f0','f1','f2']):
                    A = np.array(C['F']); B = np.array([r['points'][n]['world_m'] for n in ['f0','f1','f2']]); ac = A.mean(axis=0); bc = B.mean(axis=0)
                    U,S,Vt = np.linalg.svd((A-ac).T @ (B-bc)); D = np.eye(3); D[2,2] = np.linalg.det(Vt.T @ U.T); R = Vt.T @ D @ U.T
                    T = np.eye(4); T[:3,:3] = R; T[:3,3] = bc-R @ ac
                    residual = float(np.max(np.linalg.norm(geo.transform(A,T)-B,axis=1))); uncertainty = 0.003+residual
                    E.append({'landmark_registration_residual_m':residual,'frame':r['frame_id'],'uncertainty_m':uncertainty})
                    if residual > 0.003 or np.linalg.svd(B-bc,compute_uv=False)[1] < 0.004:
                        T = None
                if T is None:
                    need(attempt == 0 and p['view_up'] == 'justified' and C['view_trials'] < 3, 'Registration unknown: no unambiguous current correspondences or justified remaining view action')
                    C['view_trials'] += 1; save(); lease((geo.pad_position(api.state())+np.array([0,0,0.025])).tolist(), 'registration_view'); continue
            o = {'points':geo.transform(C['F'],T).tolist(),'center':geo.transform([C['center']],T)[0].tolist(),'vertices':geo.transform(C['V'],T).tolist(),'bottom':geo.transform(C['bottom'],T).tolist(),'transform':T.tolist(),'u':float(uncertainty),'frame':api.state()['frame_id']}
            C['last_observation'] = o; save(); return o
        raise RuntimeError('Registration recovery exhausted')
    def retention(o):
        if 'hold' in C:
            h = C['hold']; error = float(geo.attachment_error(h['points'],o['points'],h['state'],api.state())); limit = 0.005+h['u']+o['u']
            E.append({'attachment_discrepancy_m':error,'limit_m':limit,'frame':o['frame']}); need(error <= limit, 'Current independent object motion no longer supports retained attachment')
    def move(target, phase, position_tolerance=0.003, assess_effect=False):
        target = np.array(target); viewed = False
        for leg in range(12):
            s = api.state(); pad = geo.pad_position(s); d = target-pad; distance = float(np.linalg.norm(d)); angle = 2*math.acos(min(1.0,abs(float(np.dot(s['tcp_quaternion_xyzw'],C['quaternion'])))))
            if distance <= position_tolerance and angle <= 0.04:
                return
            need(distance < 0.59, 'Motion objective exceeds local episode range')
            b = s['budgets']; need(b['gpt_remaining'] >= (3 if C['phase'] in ['released','done'] else 5) and b['jev_remaining'] >= 9, 'Verification/control reserve reached')
            end = pad+d*min(1.0,0.10/max(distance,0.000001))
            fields = {'obstruction':['observed_external','none_observed','unknown'],'visibility':['adequate_local','self_occlusion','unobserved'],'action':['advance','view_up','stop']}
            extra = ''
            if phase == 'grasp_entry':
                fields['entry'] = ['straddles','blocked','unknown']; extra = ' Also return entry: straddles means the open fingers visibly align outside opposite measured sides with locally plausible entry, not proven contact; otherwise blocked or unknown.'
            r = api.review('Assess ONLY the next local pad-center leg, not the entire later route. obstruction=observed_external means an actual external obstacle intersects this proposed local action; none_observed means no such obstacle is seen, NOT certified clearance; unknown means even that assessment is unavailable. visibility distinguishes adequate local evidence, occlusion by our robot/held package, and genuinely unobserved space. action=advance requires justified local progress from current visible geometry and our measured envelope, allowing self-occlusion alone; never advance through an observed obstacle or unexplained unobserved region. action=view_up requires that a 0.025 m upward hand move is itself locally justified and likely to improve the view. Otherwise stop. Preserve the held package; no jaw change.'+extra, context={'phase':phase,'from_pad':pad.tolist(),'to_pad':end.tolist(),'desired_quaternion':C['quaternion'],'own_geometry':s['own_geometry'],'object_geometry':C['geometry_evidence'],'identity':C['identity'],'last_object_observation':C.get('last_observation')}, fields=fields)
            note_review(r); p = r['parameters']
            if p['action'] == 'view_up':
                need(not viewed and C['view_trials'] < 3, 'Local view action exhausted'); viewed = True; C['view_trials'] += 1; save(); lease((pad+np.array([0,0,0.025])).tolist(),'local_view')
            else:
                need(p['action'] == 'advance' and p['obstruction'] == 'none_observed' and p['visibility'] != 'unobserved' and (phase != 'grasp_entry' or p['entry'] == 'straddles'), 'No justified local action: '+str(p))
                lease(end.tolist(),phase,position_tolerance)
            if assess_effect:
                return
            if 'hold' in C and C['phase'] not in ['released','done']:
                retention(observe())
        raise RuntimeError('Bounded route incomplete; actual progress receipts retained')
    def jaw(command, phase):
        for k in range(2):
            s = api.state(); C['jaw_intent'] = {'command':command,'phase':phase,'frame':s['frame_id']}; save()
            a = api.control(geo.pad_position(s).tolist(),s['tcp_quaternion_xyzw'],command,Q,features={'phase':phase,'purpose':'Jaw delivery or settling only; no object effect inferred'},tool_point='pad_center',translation_limit=0.005,rotation_limit=0.04,steps=3,position_tolerance=0.003,rotation_tolerance=0.04)
            C['jaw_ack'] = {'choices':a['choices'],'frame':a['frame_id'],'status':a['status'],'acknowledged_steps':a['acknowledged_steps']}
            if a['choices']['gripper'] == command:
                C['phase'] = phase
            save(); E.append(C['jaw_ack']); need(a['status'] in ['reached','moved'] and a['choices']['gripper'] == command, 'Jaw action not acknowledged as requested; physical state must be reobserved')
    if C['phase'] == 'approach':
        o = observe(); need(np.max(np.linalg.norm(np.array(o['points'])-np.array(C['F']),axis=1)) < 0.006, 'Source moved: saved grasp geometry needs new acquisition')
        g = geo.transform([C['grasp']],o['transform'])[0]; s = api.state(); pad = geo.pad_position(s)
        need(s['last_gripper_command'] == 'open', 'Approach recovery requires acknowledged open jaws; do not reopen a possible load')
        angle = 2*math.acos(min(1.0,abs(float(np.dot(s['tcp_quaternion_xyzw'],C['quaternion'])))))
        lateral = float(np.linalg.norm(pad[:2]-g[:2]))
        nearby = bool(lateral <= 0.004 and g[2]-0.003 <= pad[2] <= g[2]+0.048 and angle <= 0.04)
        E.append({'entry_resume_frame':s['frame_id'],'resume_local_entry':nearby,'lateral_residual_m':lateral,'orientation_residual_rad':angle,'pad_height_m':float(pad[2]),'registered_grasp_height_m':float(g[2])}); save()
        if not nearby:
            move([float(g[0]),float(g[1]),max(float(pad[2]),float(g[2]+0.08))],'above_source')
            move((g+np.array([0,0,0.045])).tolist(),'source_standoff'); o = observe()
        before = np.array(o['points'])
        for entry_attempt in range(2):
            g = geo.transform([C['grasp']],o['transform'])[0]
            move(g.tolist(),'grasp_entry'); entry_frame = api.state()['frame_id']; o = observe()
            need(np.max(np.linalg.norm(np.array(o['points'])-before,axis=1)) < 0.008, 'Package displaced during entry; closure not justified')
            if o['frame'] == entry_frame:
                break
            E.append({'entry_observation_changed_hand_pose':True,'entry_frame':entry_frame,'observation_frame':o['frame']}); save()
            need(entry_attempt == 0, 'Registration still requires leaving entry after one re-entry; jaws remain open and closure is not justified')
        # Revalidate actual entry geometry, including any view motion inside observe().
        s = api.state(); R = geo.rotation(s['tcp_quaternion_xyzw']); own = s['own_geometry']; pad = geo.pad_position(s)
        lo = own['finger_low_offset_tool_m']; hi = own['finger_high_offset_tool_m']
        envelope = np.array([[x,y,z] for x in [lo[0],hi[0]] for y in [lo[1],hi[1]] for z in [lo[2],hi[2]]])
        world_envelope = (envelope-np.array(own['pad_center_in_tool_m'])) @ R.T + pad
        support = np.array(C['support_plane']); clearance = float(np.min(world_envelope @ support[:3]+support[3]))
        ph = float(np.sum(np.abs(R[2,:])*np.array(own['pad_extent_in_tool_m']))/2)
        side_top = float(np.min(np.array(o['vertices'])[:,2])); side_bottom = float(np.max(np.array(o['bottom'])[:,2]))
        overlap = float(min(pad[2]+ph,side_top)-max(pad[2]-ph,side_bottom)); overlap_uncertainty = float(C['u']+o['u'])
        E.append({'entry_geometry_frame':s['frame_id'], 'actual_pad_height_m':float(pad[2]), 'observed_side_height_interval_m':[side_bottom,side_top], 'actual_band_overlap_m':overlap, 'overlap_uncertainty_heuristic_m':overlap_uncertainty, 'actual_finger_support_clearance_m':clearance, 'support_uncertainty_heuristic_m':C['u'], 'meaning':'Geometry for closure only, not measured contact or retention.'}); save()
        need(clearance >= C['u'] and overlap > overlap_uncertainty, 'Current entry geometry does not establish support clearance and usable side-band overlap; see measured values')
        C['test_reference'] = {'points':o['points'],'u':o['u'],'state':s}; C['lift_target'] = (pad+np.array([0,0,0.05])).tolist(); C['phase'] = 'closing'; save()
    if C['phase'] in ['closing','possible_holding']:
        jaw('close','possible_holding'); C['phase'] = 'testing'; save()
        o = observe(); s = api.state()
        C['closure_observation'] = {'frame':o['frame'],'uncertainty_m':o['u'],'gripper_qpos_m':s['gripper_qpos_m'],'meaning':'Fresh package registration after acknowledged closure; retention remains unproven.'}
        E.append(C['closure_observation']); save()
    if C['phase'] == 'testing':
        move(C['lift_target'],'retention_probe'); o = observe(); h = C['test_reference']; s = api.state()
        hand_rise = float(geo.pad_position(s)[2]-geo.pad_position(h['state'])[2]); object_rise = float(np.mean(np.array(o['points'])[:,2]-np.array(h['points'])[:,2])); error = float(geo.attachment_error(h['points'],o['points'],h['state'],s)); limit = 0.005+h['u']+o['u']
        E.append({'retention_probe':{'hand_rise_m':hand_rise,'object_rise_m':object_rise,'attachment_error_m':error,'limit_m':limit}})
        need(hand_rise >= 0.03 and object_rise >= max(0.025,2*(h['u']+o['u'])) and error <= limit, 'Lift did not establish retention; unknown is not a grasp or a proven loss')
        C['hold'] = {'points':o['points'],'u':o['u'],'state':s}; C['phase'] = 'retained'; save()
    if C['phase'] in ['retained','transferring']:
        C['phase'] = 'transferring'; save(); o = observe(); retention(o); pad = geo.pad_position(api.state())
        pad[2] += max(0.0,C['rim_z']+0.06-float(np.min(np.array(o['bottom'])[:,2]))); move(pad.tolist(),'lift_for_transfer')
        o = observe(); retention(o); pad = geo.pad_position(api.state()); pad[:2] += np.array(C['bowl_xy'])-np.array(o['center'])[:2]; move(pad.tolist(),'transfer_above_opening'); C['phase'] = 'at_release'; save()
    if C['phase'] == 'at_release':
        r = api.review('Revalidate the receiving vessel, not the package outline. vessel=same_stationary means the same bowl has not visibly shifted from the historical measured opening. Request v0,v1 on two separated currently visible inner-rim locations, not necessarily old rim landmarks. A partly occluded rim is acceptable; unknown is not confirmation.', context={'identity':C['identity'],'historical_opening_center_xy':C['bowl_xy'],'historical_rim_z':C['rim_z'],'radius':C['radius']}, fields={'vessel':['same_stationary','changed','unknown']})
        note_review(r); need(r['parameters']['vessel'] == 'same_stationary' and all(n in r['points'] for n in ['v0','v1']), 'Destination stationarity/rim evidence missing')
        rr = np.array([r['points'][n]['world_m'] for n in ['v0','v1']]); er = float(np.max(np.abs(np.linalg.norm(rr[:,:2]-np.array(C['bowl_xy']),axis=1)-C['radius']))); ez = float(np.max(np.abs(rr[:,2]-C['rim_z'])))
        E.append({'current_rim_radial_error_m':er,'current_rim_height_error_m':ez}); need(er < 0.007 and ez < 0.007 and np.linalg.norm(rr[0]-rr[1]) > C['radius']*0.4, 'Current rim inconsistent with saved opening')
        C['rim_revalidated_frame'] = r['frame_id']; save()
        o = observe(); retention(o)
        for correction in range(4):
            points = np.array(o['vertices']+o['bottom']); center = np.array(o['center'])
            radial = float(np.max(np.linalg.norm(points[:,:2]-np.array(C['bowl_xy']),axis=1)))
            centered = float(np.max(np.linalg.norm(points[:,:2]-center[:2],axis=1)))
            gap = float(np.min(np.array(o['bottom'])[:,2])-C['rim_z'])
            headroom = float(C['safe_radius']-o['u']-centered)
            release_ok = bool(radial+o['u'] < C['safe_radius'] and -0.001 <= gap <= 0.022)
            E.append({'release_frame':o['frame'],'release_radial_extent_m':radial,'available_radius_m':C['safe_radius'],'actual_bottom_gap_m':gap,'effect_uncertainty_m':o['u'],'centered_radial_extent_m':centered,'radial_headroom_after_recentering_m':headroom,'actual_radial_margin_m':float(C['safe_radius']-radial-o['u']),'release_geometry_accepted':release_ok}); save()
            if release_ok:
                break
            need(correction < 3, 'Release geometry still fails after three bounded corrections; see measured margins')
            need(headroom > 0, 'Recentering cannot satisfy the measured footprint and uncertainty constraint; no release authorized')
            s = api.state(); pad = geo.pad_position(s)
            pad[:2] += np.array(C['bowl_xy'])-center[:2]
            if not -0.001 <= gap <= 0.022:
                pad[2] += C['rim_z']+o['u']+0.004-float(np.min(np.array(o['bottom'])[:,2]))
            tolerance = float(max(0.0005,min(0.003,headroom/2)))
            E.append({'release_correction':correction+1,'pad_target_m':pad.tolist(),'position_tolerance_m':tolerance,'controller_minimum_tolerance_m':0.0005,'meaning':'Tolerance schedules a bounded correction; only the next independent object observation can authorize release.'}); save()
            move(pad.tolist(),'low_release_alignment',position_tolerance=tolerance,assess_effect=True)
            need(api.state()['frame_id'] > s['frame_id'], 'Release gate fails but the requested correction is within the controller deadband; no new motion evidence, jaws kept unchanged')
            o = observe(); retention(o)
        need(release_ok, 'Actual measured object pose is not a suitable low release')
        C['phase'] = 'releasing'; save()
    if C['phase'] == 'releasing':
        jaw('open','released')
    need(C['phase'] in ['released','done'], 'Unrecognized recovery phase: '+C['phase'])
    if 'retreat_target' not in C:
        C['retreat_target'] = (geo.pad_position(api.state())+np.array([0,0,0.08])).tolist(); save()
    if not C.get('retreated',False):
        move(C['retreat_target'],'post_release_view'); C['retreated'] = True; save()
    for trial in range(3):
        previous = C.get('final_reference')
        r = api.review('Assess the ACTUAL released source relation to the bowl. relation=inside_resting means supported in the bowl interior, not merely overlapping in projection, bridging the rim, or held by fingers; on_rim, outside, held, and unknown have those literal meanings. identity=unique requires the same requested package. Request s0,s1,s2 at three currently visible, noncollinear physical package landmarks. On the first observation define them in definitions; on later observations use and repeat the supplied exact physical definitions, never redefine IDs by screen position. These may be a new reference gauge unrelated to the pregrasp patch. view_up=justified only if a 0.025 m upward hand move is locally unobstructed and would reveal missing final evidence. Do not infer stability from commanded release.', context={'identity':C['identity'],'previous_stability_reference':previous,'released_jaw_receipt':C.get('jaw_ack')}, fields={'relation':['inside_resting','on_rim','outside','held','unknown'],'identity':['unique','ambiguous','unknown'],'definitions':definitions,'view_up':['justified','blocked','unknown']})
        note_review(r); p = r['parameters']; valid = p['identity'] == 'unique' and p['definitions'] is not None and all(n in r['points'] for n in ['s0','s1','s2'])
        if not valid or p['relation'] == 'unknown':
            need(trial < 2 and p['view_up'] == 'justified' and not C.get('final_viewed',False), 'Released object left undisturbed: final identity/relation/stability evidence unavailable')
            C['final_viewed'] = True; save(); lease((geo.pad_position(api.state())+np.array([0,0,0.025])).tolist(),'final_evidence_view'); continue
        points = [r['points'][n]['world_m'] for n in ['s0','s1','s2']]; s = api.state()
        if previous is not None and previous['definitions'] == p['definitions'] and s['native_steps']-previous['native_steps'] >= 6:
            change = float(np.max(np.linalg.norm(np.array(points)-np.array(previous['points']),axis=1)))
            E.append({'final_relation':p['relation'],'stability_max_displacement_m':change,'elapsed_native_steps':s['native_steps']-previous['native_steps'],'frame':r['frame_id']})
            if p['relation'] == 'inside_resting' and previous['relation'] == 'inside_resting' and change <= 0.006:
                C['phase'] = 'done'; C['completion_proposed'] = True; save(); return {'completion_proposed':True,'evidence':E,'limitations':['Visual and RGB-D bounded-episode evidence, not certified clearance or official task success; uncertainty thresholds are heuristic.']}
        C['final_reference'] = {'points':points,'definitions':p['definitions'],'relation':p['relation'],'native_steps':s['native_steps'],'frame':r['frame_id']}; save()
        if trial < 2:
            jaw('keep','released')
    return {'completion_proposed':False,'evidence':E+[{'gap':'Released object did not establish both interior placement and measured stability within the observation bound.'}]}

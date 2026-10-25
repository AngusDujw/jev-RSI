def main(api):
    task = {'instruction': 'could you put the cream cheese into the bowl'}
    mem, tracker, trace = {}, {}, []
    cameras = ['agentview', 'robot0_eye_in_hand']
    pixel = {'type': 'array', 'items': {'type': 'number', 'minimum': 0, 'maximum': 767}, 'minItems': 2, 'maxItems': 2}
    polygon = {'type': ['array', 'null'], 'items': pixel, 'minItems': 3, 'maxItems': 16}
    patch_fields = {'identity': ['exact', 'ambiguous', 'unknown'], 'patch_camera': cameras, 'patch': polygon}
    questions = {}
    for axis in ['x', 'y', 'z', 'rx', 'ry', 'rz']:
        questions[axis] = {'type': 'choice', 'instructions': 'Control world axis ' + axis + '. Read state.processed_features.axes.' + axis + '.goal_relation. Follow increase, decrease or within_tolerance; rotation signs are world rotation-vector signs.', 'criteria': {'negative': 'decrease: use the negative direction on this axis', 'hold': 'within_tolerance: no update on this axis', 'positive': 'increase: use the positive direction on this axis'}}
    questions['gripper'] = {'type': 'choice', 'instructions': 'Read state.processed_features.objective.gripper and deliver exactly that requested gripper action. This is not a grasp judgment.', 'criteria': {'open': 'objective is open', 'close': 'objective is close', 'keep': 'objective is keep'}}
    def require(ok, gap, values=None):
        if not ok:
            trace.append({'gap': gap, 'values': values})
            raise RuntimeError(gap)
    def review(question, fields, context=None):
        require(api.state()['budgets']['gpt_remaining'] > 0, 'No observation-review budget')
        r = api.review(question, context=context, fields=fields)
        trace.append({'review_frame': r['frame_id'], 'parameters': r['parameters'], 'explanation': r['explanation'], 'measurement_errors': r['measurement_errors']})
        require(r['status'] != 'stop', 'Observation review requested stop', r['explanation'])
        return r
    def samples(r, names):
        bad = [e['name'] for e in r['measurement_errors']]
        return {n: r['points'][n] for n in names if n in r['points'] and n not in bad}
    def surface(r, name):
        require(name in r['regions'] and name not in [e['name'] for e in r['measurement_errors']], 'Missing measured region: ' + name, r['measurement_errors'])
        p = geo.plane(np.asarray(r['regions'][name]['world_m'], dtype=float))
        values = {'name': name, 'coefficients': np.asarray(p['coefficients']).tolist(), 'rms_m': float(p['rms_m']), 'spread_m': np.asarray(p['in_plane_spread_m']).tolist()}
        trace.append(values)
        require(p['rms_m'] < 0.0025 and p['coefficients'][2] > 0.97, 'Measured surface is not a sufficiently horizontal plane', values)
        return p
    def rim_measure(r):
        pts = samples(r, ['k' + str(i) for i in range(6)])
        require(len(pts) >= 4, 'Fewer than four usable inner-lip samples', r['measurement_errors'])
        p = np.asarray([v['world_m'] for v in pts.values()]); plane = geo.plane(p); c = geo.circle_xy(p)
        out = {'xy': np.asarray(c['center_xy_m']).tolist(), 'z': float(plane['center_world_m'][2]), 'radius': float(c['radius_m']), 'rms': float(c['rms_m']), 'max_error': float(c['max_radial_error_m']), 'gap_rad': float(c['largest_angular_gap_rad']), 'frame': r['frame_id']}
        trace.append({'rim_fit': out, 'plane_rms': float(plane['rms_m'])})
        require(plane['coefficients'][2] > 0.97 and plane['rms_m'] < 0.003 and c['max_radial_error_m'] < 0.005 and c['largest_angular_gap_rad'] < math.pi, 'Inner rim fit is inadequately supported', out)
        return out
    def point_uncertainty(pts):
        u = 0.0015
        for v in pts.values():
            k = np.asarray(api.camera(v['camera'])['K'])
            u = max(u, 1.5 * v['depth_m'] / min(k[0, 0], k[1, 1]))
        return float(u)
    def save():
        api.checkpoint('progress', {'phase': mem.get('phase', 'initializing'), 'held': mem.get('held', False), 'intent': mem.get('intent'), 'snapshot': mem.get('snapshot'), 'transition': mem.get('transition'), 'views': mem.get('views', 0)})
    def start_patch(camera, poly, base, bounds=None, witness=None):
        if poly is None: return
        try:
            t = api.track_init(camera, poly)
        except (RuntimeError, ValueError) as e:
            trace.append({'patch_initialization_error': str(e), 'camera': camera}); return
        base = np.asarray(base).tolist()
        if bounds is None: bounds = np.full((8,3), mem['u'])
        if witness is None: witness = {'ids': [0,1,2,3], 'points': base, 'u': mem['u']}
        tracker.clear()
        tracker.update({'handle': t['handle'], 'base': base, 'bounds': np.asarray(bounds).tolist(), 'witness': witness, 'identity': mem['reference']['identity'], 'camera': camera, 'polygon': poly, 'reference_frame_id': t['frame_id']})
        api.checkpoint('tracking_reference', tracker)
        trace.append({'patch_reference_frame': t['frame_id'], 'features': t['reference_features'], 'camera': camera})
    def finger_offsets(s, q):
        g = s['own_geometry']; lo = g['finger_low_offset_tool_m']; hi = g['finger_high_offset_tool_m']
        box = np.asarray([[x,y,z] for x in [lo[0],hi[0]] for y in [lo[1],hi[1]] for z in [lo[2],hi[2]]])
        return (box - np.asarray(g['pad_center_in_tool_m'])) @ geo.rotation(q).T
    def grasp_plans(B, u, s):
        ref = mem['reference']; R = geo.rotation(ref['q']); opening = R[:, ref['opening_axis']]
        along = np.cross([0,0,1], opening); along /= np.linalg.norm(along)
        center = B.mean(axis=0); extent = s['own_geometry']['pad_extent_in_tool_m']
        half = float(np.dot(np.abs(R.T @ along), extent) / 2)
        projected = (B - center) @ along; a, b = float(min(projected)), float(max(projected))
        overlap = min(1.6 * half, 0.4 * (b - a))
        low, high = a + overlap - half, b - overlap + half
        require(overlap > u and low <= high, 'Unresolved longitudinal pad overlap', {'half_band': half, 'side_interval': [a,b], 'overlap': overlap, 'u': u})
        env = finger_offsets(s, ref['q']); plans = []
        for shift in np.linspace(low, high, 9):
            offset = float(shift) * along; box = center + offset + env
            nearest = np.clip(np.asarray(ref['rim']['xy']), box[:, :2].min(axis=0), box[:, :2].max(axis=0))
            score = float(np.linalg.norm(nearest - ref['rim']['xy']) - ref['rim']['radius'])
            actual_overlap = min(float(shift) + half, b) - max(float(shift) - half, a)
            plans.append({'offset': offset.tolist(), 'side_overlap_m': float(actual_overlap), 'inner_lip_box_gap_m': score})
        plans = sorted(plans, key=lambda p: p['inner_lip_box_gap_m'], reverse=True)
        trace.append({'grasp_candidates': plans, 'meaning': 'Finite pad overlap and conservative box/INNER lip ranking only; not observed clearance. Outer bowl material needs local review.'})
        return plans
    def observe_once(reason):
        def require(ok, gap, values=None):
            if not ok:
                trace.append({'observation_gap': gap, 'values': values})
                raise RuntimeError('OBSERVATION_GAP: ' + gap)
        B, u, method = None, mem['u'], 'landmark_registration'
        bounds, witness = None, None
        if 'handle' in tracker:
            t = api.track_update(tracker['handle'])
            trace.append({'tracking_status': t['status'], 'frame': t['frame_id'], 'reference_frame': t['reference_frame_id'], 'reason': t.get('reason')})
            if t['status'] == 'tracked':
                x = np.asarray(t['reference_inlier_world_m']); spread = np.linalg.svd(x - x.mean(axis=0), compute_uv=False) / math.sqrt(len(x))
                u = max(mem['u'], float(t['uncertainty_floor_m']), float(t['rms_m']))
                trace.append({'inliers': t['inliers'], 'matches': t['matches'], 'rms_m': t['rms_m'], 'uncertainty_m': u, 'spatial_support_m': spread.tolist()})
                if t['inliers'] >= 8 and t['inliers'] / max(1, t['matches']) >= 0.55 and t['rms_m'] <= 0.0025 and u <= 0.004 and spread[1] > 1.2 * u:
                    T = np.asarray(t['transform_initial_world_to_current_world'])
                    B = geo.transform(np.asarray(tracker['base']), T); method = 'RGBD_registration'
                    noise = max(float(t['rms_m']), float(t['uncertainty_floor_m']))
                    bounds = np.asarray(tracker.get('bounds', np.full((8,3), mem['u']).tolist())) @ np.abs(T[:3,:3]).T + noise
                    w = tracker.get('witness', {'ids': [0,1,2,3], 'points': tracker['base'], 'u': mem['u']})
                    witness = {'ids': w['ids'], 'points': geo.transform(w['points'], T).tolist(), 'u': float(w['u'] + noise)}
        if B is None:
            fields = dict(patch_fields)
            fields.update({'boundary_camera': cameras, 'boundary': {'type': ['array','null'], 'items': pixel, 'minItems': 4, 'maxItems': 4}, 'face': ['top','side_upright','unknown'], 'edge': {'type': ['array','null'], 'items': pixel, 'minItems': 2, 'maxItems': 2}, 'edge_ids': {'type': ['array','null'], 'items': {'type': 'integer','minimum': 0,'maximum': 3}, 'minItems': 2,'maxItems': 2}})
            r = review('Recover the current envelope only for the next geometry action. Request CURRENT l0,l1,l2 at saved physical definitions where visible. Alternative boundary: four visible top corners in reference P order and region top strictly inside that face. A PARTIAL alternative is sufficient: edge gives two visible adjacent TOP-edge endpoints, edge_ids their physical indices in reference P, in boundary_camera. Request region face strictly inside the adjoining planar face, same camera, explicit box and stride=4. face=top identifies the upward broad top; side_upright identifies a vertical side with an observed distinction between its upper and lower edges and an approximately upright package. Never substitute lower side corners for top corners. A visible short end face is usable even when the broad top is hidden. Resolve endpoint identities from printing and saved references, not screen order; reject symmetric/ambiguous correspondences. No hidden endpoints may be inferred. Use null for unavailable boundary, edge or edge_ids and unknown for an unidentified face. identity=exact means the body AND the selected measurement correspondences are unambiguous, not that every corner is visible. Choose patch_camera and a textured interior patch on ANY exposed rigid face, excluding fingers/background, or patch=null. A new patch alone is not a full-envelope pose.', fields, {'reason': reason, 'reference': mem['reference'], 'last_snapshot': mem.get('snapshot'), 'diagnostics': trace[-3:]})
            p = r['parameters']; cur = samples(r, ['l0','l1','l2']); u = max(mem['u'], point_uncertainty(cur))
            require(p['identity'] == 'exact', 'Ambiguous current rigid-body identity/correspondence', p)
            if len(cur) == 3:
                X = np.asarray(mem['reference']['L']); Y = np.asarray([cur['l'+str(i)]['world_m'] for i in range(3)])
                A = X - X.mean(axis=0); C = Y - Y.mean(axis=0); U, singular, V = np.linalg.svd(A.T @ C)
                if np.linalg.det(V.T @ U.T) < 0: V[2,:] *= -1
                T = np.eye(4); T[:3,:3] = V.T @ U.T; T[:3,3] = Y.mean(axis=0) - T[:3,:3] @ X.mean(axis=0)
                err = float(np.max(np.linalg.norm(geo.transform(X,T)-Y, axis=1)))
                spread = min(float(np.linalg.svd(A,compute_uv=False)[1]),float(np.linalg.svd(C,compute_uv=False)[1])) / math.sqrt(3)
                trace.append({'landmark_fit_error_m': err, 'landmark_spread_m': spread, 'uncertainty_m': u})
                require(u <= 0.004 and spread > 1.2*u and err <= 3*u, 'Landmark registration is unresolved', trace[-1])
                B = geo.transform(np.asarray(mem['reference']['P']),T)
            elif p['boundary'] is None and p['edge'] is not None and p['edge_ids'] is not None and p['face'] != 'unknown':
                require('face' in r['regions'] and 'face' not in [e['name'] for e in r['measurement_errors']], 'Missing partial-face measurement', r['measurement_errors'])
                fit = geo.plane(np.asarray(r['regions']['face']['world_m'])); coeff = np.asarray(fit['coefficients']); spread = min(fit['in_plane_spread_m'])
                require(fit['rms_m'] <= 0.0025 and spread > max(2*fit['rms_m'],0.00015), 'Partial face plane is poorly observed', {'rms_m': float(fit['rms_m']), 'spread_m': float(spread)})
                ids = p['edge_ids']; require((ids[1]-ids[0]) % 4 in [1,3], 'Endpoints do not identify adjacent physical top corners', ids)
                E = np.asarray([api.plane_point(p['boundary_camera'],uv,coeff.tolist())['world_m'] for uv in p['edge']]); X = np.asarray(mem['reference']['P'])
                a = X[ids[1]]-X[ids[0]]; b = E[1]-E[0]; la = float(np.linalg.norm(a)); lb = float(np.linalg.norm(b))
                require(lb > 0, 'Degenerate measured edge'); a /= la; b /= lb
                n = coeff[:3] if p['face'] == 'top' else np.cross(b,coeff[:3])
                if n[2] < 0: n = -n
                n = n - np.dot(n,b)*b; n /= np.linalg.norm(n); n0 = normal(X)
                require(n[2] > 0.85 and (p['face'] != 'side_upright' or abs(coeff[2]) < 0.35), 'Partial face does not support the observed upright model', n.tolist())
                A = np.column_stack((a,np.cross(n0,a),n0)); C = np.column_stack((b,np.cross(n,b),n))
                T = np.eye(4); T[:3,:3] = C @ A.T; anchor = (X[ids[0]]+X[ids[1]])/2
                T[:3,3] = E.mean(axis=0)-T[:3,:3]@anchor; B = geo.transform(X,T)
                cam = api.camera(p['boundary_camera']); K = np.asarray(cam['K']); depth = geo.transform(E,np.linalg.inv(np.asarray(cam['camera_to_world_opencv'])))[:,2]
                pixel_u = float(1.5*max(depth)/min(K[0,0],K[1,1]))
                angular_u = math.atan(max(float(fit['rms_m'])/float(spread), pixel_u/lb))
                u = max(mem['u'], pixel_u, float(fit['rms_m']), abs(lb-la)/2)
                Q = np.concatenate([B, B-mem['reference']['height']*normal(B)])
                V = Q-E.mean(axis=0); perpendicular = V-(V@b)[:,None]*b
                anchor_edge = u + pixel_u*np.linalg.norm(V,axis=1)/lb
                bounds = anchor_edge[:,None] + np.abs(np.cross(b,V))*math.sin(angular_u) + np.abs(perpendicular)*(1-math.cos(angular_u))
                bounds[4:] += mem['u']*np.abs(normal(B))
                witness = {'ids': ids, 'points': E.tolist(), 'u': float(u)}
                err = max([abs(lb-la)] + [float(np.linalg.norm(geo.transform(np.asarray([mem['reference']['L'][int(k[1:])]]),T)[0]-v['world_m'])) for k,v in cur.items()])
                values = {'edge_ids': ids, 'edge_length_m': lb, 'reference_length_m': la, 'correspondence_error_m': err, 'plane_rms_m': float(fit['rms_m']), 'plane_spread_m': float(spread), 'angular_uncertainty_rad': angular_u, 'local_u_m': float(u), 'max_xyz_bound_m': bounds.max(axis=0).tolist(), 'model': p['face']}; trace.append(values)
                require(bool(np.all(np.isfinite(bounds))) and err <= 3*u, 'Partial-face correspondence or model is unresolved', values)
                api.checkpoint('envelope_witness', {'frame_id': r['frame_id'], 'identity': mem['reference']['identity'], 'camera': p['boundary_camera'], 'edge_pixels': p['edge'], 'edge_ids': ids, 'edge_world_m': E.tolist(), 'plane': coeff.tolist(), 'bounds': bounds.tolist(), 'quality': values})
                method = 'identified_partial_face_and_top_edge'
            else:
                require(p['boundary'] is not None and 'top' in r['regions'] and 'top' not in [e['name'] for e in r['measurement_errors']], 'Neither corresponding landmarks nor a current identified face envelope is obtainable', r['measurement_errors'])
                plane = geo.plane(np.asarray(r['regions']['top']['world_m'])); coeff = np.asarray(plane['coefficients'])
                require(plane['rms_m'] <= 0.0025, 'Current face region is not planar', {'rms_m': float(plane['rms_m'])})
                B = np.asarray([api.plane_point(p['boundary_camera'], uv, coeff.tolist())['world_m'] for uv in p['boundary']])
                cam = api.camera(p['boundary_camera']); K = np.asarray(cam['K'])
                depth = geo.transform(B,np.linalg.inv(np.asarray(cam['camera_to_world_opencv'])))[:,2]
                u = max(u,float(plane['rms_m']),float(2*max(depth)/min(K[0,0],K[1,1])))
                X = np.asarray(mem['reference']['P'])
                err = max(abs(float(np.linalg.norm(B[i]-B[j])-np.linalg.norm(X[i]-X[j]))) for i in range(4) for j in range(i))
                trace.append({'current_envelope_shape_error_m': err, 'u': u, 'frame': r['frame_id']})
                require(u <= 0.004 and err <= 4*u and mem['reference']['normal_sign']*np.dot(np.cross(B[1]-B[0],B[3]-B[0]),coeff[:3]) > 0, 'Current face does not resolve the saved envelope', trace[-1])
                method = 'current_identified_face_envelope'
            if bounds is None:
                bounds = np.full((8,3), u); bounds[4:] += mem['u']*np.abs(normal(B))
            if witness is None: witness = {'ids': [0,1,2,3], 'points': B.tolist(), 'u': float(np.max(bounds[:4]))}
            start_patch(p['patch_camera'], p['patch'], B, bounds, witness)
        s = api.state(); observation = {'B': B.tolist(), 'u': float(u), 'bounds': bounds.tolist(), 'witness': witness, 'state': s, 'method': method, 'reason': reason}
        api.checkpoint('observation', observation)
        old = mem.get('snapshot')
        if mem.get('held', False) and old is not None:
            ids = witness['ids']; ow = old.get('witness')
            if ow is not None and all(i in ow['ids'] for i in ids):
                Xw = [ow['points'][ow['ids'].index(i)] for i in ids]; ou = ow['u']
            else:
                Xw = np.asarray(old['B'])[ids]; ou = float(np.max(np.asarray(old.get('bounds', np.full((8,3),old['u']).tolist()))[ids]))
            err = float(geo.attachment_error(Xw, witness['points'], old['state'], s)); tol = ou + witness['u'] + 0.002
            trace.append({'continuation_attachment_error_m': err, 'tolerance_m': tol, 'physical_corner_ids': ids, 'reason': reason})
            if err > tol: raise RuntimeError('Measured object/hand motion contradiction; preserve jaws and stop')
        mem['snapshot'] = observation; save()
        return B, float(u), s
    def observe(reason):
        for attempt in range(2):
            detail = reason if attempt == 0 else reason + '. Alternate measurement: do not repeat the failed ROI. Use a larger clean region of the identified face, another visible adjoining face/top strip with identified edge, or corresponding printed landmarks. Resolve only the reported component gap; never infer hidden endpoints.'
            try:
                return observe_once(detail)
            except RuntimeError as e:
                if not str(e).startswith('OBSERVATION_GAP:'): raise
                trace.append({'measurement_recovery': str(e), 'attempt': attempt})
                if attempt == 1: raise
            except ValueError as e:
                trace.append({'rejected_geometry_fit': str(e), 'attempt': attempt})
                if attempt == 1: raise RuntimeError('OBSERVATION_GAP: alternate geometry fit also failed: ' + str(e))
        raise RuntimeError('OBSERVATION_GAP: bounded current measurement recovery exhausted')
    def move(target, quaternion, gripper, label, reserve=24, tolerance=0.0025):
        target = np.asarray(target, dtype=float); mem['intent'] = {'label': label, 'pad_target': target.tolist()}; save()
        for cap in [26, 12]:
            before = api.state(); budget = before['budgets']; n = min(cap, budget['jev_remaining'] - reserve, budget['native_steps_remaining'] // 3 - reserve)
            require(n > 0, 'Insufficient control reserve for ' + label, budget)
            old = float(np.linalg.norm(target - geo.pad_position(before)))
            r = api.drive(target.tolist(), quaternion, gripper, questions, features={'phase': mem['phase'], 'label': label, 'held_evidence': mem.get('held', False), 'historical_object_observation': mem.get('snapshot')}, max_calls=int(n), tool_point='pad_center', translation_limit=0.02, rotation_limit=0.08, steps=3, position_tolerance=tolerance, rotation_tolerance=0.035)
            now = float(np.linalg.norm(target - geo.pad_position(api.state())))
            trace.append({'motion': label, 'status': r['status'], 'position_error_m': r['position_error_m'], 'rotation_error_rad': r['rotation_error_rad'], 'lease_calls': r['lease_calls'], 'whole_lease_progress_m': old - now}); save()
            if r['status'] == 'reached': return
            require(r['status'] == 'lease_exhausted' and old - now > 0.001, 'Stalled or nonprogressing motion; no repeated contact push', trace[-1])
        require(False, 'Bounded feedback exhausted for ' + label, trace[-1])
    def pulse(gripper, count, reserve=0):
        s = api.state(); target = np.asarray(geo.pad_position(s)); q = s['tcp_quaternion_xyzw']
        require(s['budgets']['jev_remaining'] >= count + reserve and s['budgets']['native_steps_remaining'] >= 3 * (count + reserve), 'Insufficient transition/verification reserve')
        for i in range(count):
            r = api.control(target.tolist(), q, gripper, questions, features={'phase': mem['phase'], 'purpose': 'gripper transition or physical settling; not object-effect evidence'}, tool_point='pad_center', steps=3, position_tolerance=0.003, rotation_tolerance=0.035)
            mem['transition'] = {'requested': gripper, 'choice': r['choices']['gripper'], 'frame': r['frame_id'], 'acknowledged_steps': r['acknowledged_steps']}
            if r['acknowledged_steps'] > 0:
                if r['choices']['gripper'] == 'open' and mem['phase'] == 'release_pending': mem['phase'] = 'released'
                if r['choices']['gripper'] == 'close' and mem['phase'] == 'closing': mem['phase'] = 'candidate_between_fingers'
            save()
            require(r['status'] in ['reached', 'moved'] and r['choices']['gripper'] == gripper, 'Transition control failed or Jev did not deliver requested gripper choice', r)
            require(float(np.linalg.norm(np.asarray(geo.pad_position(api.state())) - target)) < 0.008, 'Unexpected hand displacement at a contact transition')
        trace.append({'transition': gripper, 'frame': api.state()['frame_id'], 'actual_gripper_qpos_m': api.state()['gripper_qpos_m']}); save()
    def guard(label, target, gripper, allow_reject=False):
        fields = {'external': ['observed_obstacle','none_observed','unknown'], 'visibility': ['observed','partial_unobserved','self_occluded'], 'action': ['local_supported','view_up_supported','unsupported']}
        for attempt in range(2):
            envelope = np.asarray(target) + finger_offsets(api.state(), mem['reference']['q'])
            r = review('Assess only this proposed local action, not a complete later corridor. external=observed_obstacle means observed external MATERIAL obstructs this action; a conservative bounding box overlapping a fitted INNER lip is only a proxy, not by itself observed collision. none_observed is not certified clearance; unknown means obstruction cannot be distinguished. visibility separately distinguishes observed space, partial_unobserved space and self_occluded space. Own occlusion is not an external obstacle. action=local_supported needs positive local justification from current surfaces, own geometry and task geometry. For descent check actual finger lanes and finite pad/side overlap; an end-biased pinch need not be centered on the package. Reject observed target displacement or inconsistent identity. Saved bowl/support geometry is only a short-horizon prior: invalidate it if current partial observations disagree or a possible interaction may have disturbed it. view_up_supported means a 0.035 m upward view action is itself supported AND likely to expose specifically missing evidence; otherwise unsupported. Never require retention before a designated measurement lift.', fields, {'label': label, 'pad_target': np.asarray(target).tolist(), 'gripper': gripper, 'reference': mem['reference'], 'snapshot': mem.get('snapshot'), 'candidate': mem.get('grasp_plan'), 'finger_envelope_world': envelope.tolist(), 'envelope_meaning': 'Own bounding envelope, not all occupied material and not a collision certificate.'})
            p = r['parameters']
            if p['external'] == 'none_observed' and p['action'] == 'local_supported': return True
            if p['action'] == 'view_up_supported' and attempt == 0 and mem.get('views',0) < 2 and label != 'resume_retention_test':
                mem['views'] = mem.get('views',0) + 1; s = api.state()
                move(np.asarray(geo.pad_position(s)) + [0,0,0.035], s['tcp_quaternion_xyzw'], 'keep', 'observation_view_change')
                observe('independent observation after view change')
            elif allow_reject:
                trace.append({'rejected_candidate': mem.get('grasp_plan'), 'local_action': label, 'assessment': p}); return False
            else: require(False, 'No justified local action: ' + label, p)
        if allow_reject: return False
        require(False, 'View change did not resolve the local evidence gap')
    def normal(B):
        n = mem['reference']['normal_sign'] * np.cross(B[1] - B[0], B[3] - B[0])
        return n / np.linalg.norm(n)
    try:
        if any(x['key'] == 'reference' for x in api.recall()):
            ref = api.recall('reference')['value']; old = api.recall('progress')['value']
            mem.update({'reference': ref, 'u': ref['u'], 'phase': old['phase'], 'held': False, 'snapshot': old['snapshot'], 'views': old.get('views',0), 'transition': old.get('transition'), 'intent': old.get('intent')})
            keys = [x['key'] for x in api.recall()]
            if 'tracking_reference' in keys:
                saved = api.recall('tracking_reference')['value']
                if saved['identity'] == ref['identity']: tracker.update(saved)
            if 'local_probe' in keys and old['phase'] in ['retention_test','retained_envelope_pending']:
                mem['probe'] = api.recall('local_probe')['value']
            r = review('Resume this physical episode without replaying actions. reference_valid=yes means physical identity and rigid dimensions remain applicable and current partial bowl/support evidence is consistent with their saved short-horizon geometry, with no potentially disturbing interaction. This is not full source-pose registration. mode=at_grasp_unheld means the actual OPEN fingers already bracket opposite source sides at contact height; prefer this over on_source_unheld when observed, even though the package still rests on the table. A previous descent target alone is insufficient. on_source_unheld means a flat supported source NOT yet in that grasp-ready configuration. candidate_between_fingers means a possibly held/closed-hand candidate, not proven retention. released_in_destination means an already released object there. unknown means these cases cannot be distinguished. Missing old landmarks or hidden far corners alone do not make a visible local grasp configuration unknown. Do not reopen a candidate held object.', {'reference_valid': ['yes', 'no', 'unknown'], 'mode': ['on_source_unheld', 'at_grasp_unheld', 'candidate_between_fingers', 'released_in_destination', 'unknown']}, {'reference': ref, 'historical_progress': old})
            require(r['parameters']['reference_valid'] == 'yes', 'Historical geometry dependencies could not be revalidated', r['parameters'])
            mode = r['parameters']['mode']; require(mode != 'unknown', 'Repair cannot distinguish held, unheld and released states')
        else:
            fields = {'eligible': ['yes', 'no', 'unknown'], 'identity': 'string', 'camera': cameras, 'corners': {'type': ['array', 'null'], 'items': pixel, 'minItems': 4, 'maxItems': 4}, 'landmark_definitions': {'type': 'array', 'items': {'type': 'string', 'maxLength': 500}, 'minItems': 3, 'maxItems': 3}, 'patch_camera': cameras, 'patch': polygon}
            r = review('Interpret the runtime task and identify source and destination. eligible=yes only for a rigid rectangular package with a visible planar top, visible side evidence that it rests flat on one support, and an accessible open approximately circular bowl. Do not infer an unseen underside from a top point. identity describes the actual objects. In camera, return four CURRENT visible top-face boundary corners cyclically; depth will be derived from a measured top plane, not sampled at boundaries. Request named regions top (strictly inside that top face, same camera) and support (exposed same supporting plane), each with explicit camera, box and stride=4. Request named points l0,l1,l2 at well-separated NONCOLLINEAR identifiable printed marks on that rigid top. landmark_definitions must describe these persistent physical identities, not camera-relative corners. Request k0..k5 on the actual INNER lip of the bowl, distributed around its rim, favoring valid narrow-surface depth samples, and floor on the visible cavity bottom. Choose patch_camera and a textured interior polygon for this object, excluding background/fingers, or null. Do not mark hidden boundaries.', fields, task)
            p = r['parameters']; api.checkpoint('initial_samples', {'parameters': p, 'points': r['points'], 'measurement_errors': r['measurement_errors'], 'frame': r['frame_id']})
            require(p['eligible'] == 'yes' and p['corners'] is not None, 'Current geometry does not support this measured grasp-and-place policy', p)
            top = surface(r, 'top'); table = surface(r, 'support'); rim = rim_measure(r)
            P = np.asarray([api.plane_point(p['camera'], uv, np.asarray(top['coefficients']).tolist())['world_m'] for uv in p['corners']])
            landmarks = samples(r, ['l0', 'l1', 'l2']); floor = samples(r, ['floor'])
            require(len(landmarks) == 3 and len(floor) == 1, 'Missing source identity landmarks or cavity measurement', r['measurement_errors'])
            L = np.asarray([landmarks['l' + str(i)]['world_m'] for i in range(3)]); u = max(point_uncertainty(landmarks), float(top['rms_m']), float(table['rms_m']), rim['rms'])
            center = P.mean(axis=0); coeff = np.asarray(table['coefficients']); table_z = -(coeff[3] + np.dot(coeff[:2], center[:2])) / coeff[2]; height = float(center[2] - table_z)
            e0, e1 = P[1] - P[0], P[3] - P[0]; lengths = [float(np.linalg.norm(e0)), float(np.linalg.norm(e1))]; half_diagonal = float(np.max(np.linalg.norm(P[:, :2] - center[:2], axis=1)))
            values = {'height_m': height, 'edge_lengths_m': lengths, 'half_diagonal_m': half_diagonal, 'rim_radius_m': rim['radius'], 'uncertainty_m': u}
            trace.append(values)
            require(height > 2 * u and min(lengths) > 4 * u and np.linalg.norm(P[2] - P[1] - P[3] + P[0]) < 4 * u and abs(np.dot(e0, e1)) / max(lengths) < 4 * u, 'Package extent geometry is inconsistent', values)
            require(np.max(np.abs(L @ np.asarray(top['coefficients'])[:3] + top['coefficients'][3])) < 3 * u and np.linalg.svd(L - L.mean(axis=0), compute_uv=False)[1] / math.sqrt(3) > 1.2 * u, 'Landmark surface or spatial support is insufficient', {'L': L.tolist(), 'u': u})
            floor_z = floor['floor']['world_m'][2]
            require(half_diagonal + 3 * u < rim['radius'] and floor_z < rim['z'] - 2 * u, 'Measured package does not fit the observed open cavity', values)
            s = api.state(); g = s['own_geometry']; R = geo.rotation(s['tcp_quaternion_xyzw']); opening_axis = int(np.argmax(g['pad_extent_in_tool_m'])); short = e0 if lengths[0] < lengths[1] else e1; a = R[:, opening_axis]
            if np.dot(a, short) < 0: short = -short
            require(abs(a[2]) < 0.15 and abs(R[2, 2]) > 0.95, 'Current hand orientation is not a supported top-down approach')
            yaw = math.atan2(a[0] * short[1] - a[1] * short[0], np.dot(a[:2], short[:2])); q = api.compose(s['tcp_quaternion_xyzw'], [0, 0, yaw]); R = geo.rotation(q)
            lo, hi, offset = np.asarray(g['finger_low_offset_tool_m']), np.asarray(g['finger_high_offset_tool_m']), np.asarray(g['pad_center_in_tool_m'])
            envelope = np.asarray([[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]]); fmin = float(np.min(((envelope - offset) @ R.T)[:, 2])); pad_half_z = float(np.dot(np.abs(R[2]), g['pad_extent_in_tool_m']) / 2)
            ref = {'task': task, 'identity': p['identity'], 'P': P.tolist(), 'L': L.tolist(), 'landmark_definitions': p['landmark_definitions'], 'landmark_measurements': landmarks, 'top_plane': np.asarray(top['coefficients']).tolist(), 'table_plane': coeff.tolist(), 'height': height, 'u': float(u), 'rim': rim, 'floor_z': floor_z, 'q': q, 'fmin': fmin, 'pad_half_z': pad_half_z, 'opening_axis': opening_axis, 'outer_pad_span': float(g['pad_extent_in_tool_m'][opening_axis]), 'normal_sign': 1 if np.cross(e0, e1)[2] > 0 else -1, 'frame': r['frame_id'], 'boundary_camera': p['camera'], 'boundary_pixels': p['corners']}
            api.checkpoint('reference', ref); mem.update({'reference': ref, 'u': float(u), 'phase': 'approach', 'held': False}); save(); start_patch(p['patch_camera'], p['patch'], P); mode = 'on_source_unheld'
        ref = mem['reference']; q, rim = ref['q'], ref['rim']
        if mode == 'on_source_unheld':
            mem.pop('probe',None); B, u, s = observe('current envelope needed for a new approach')
        else:
            s = api.state(); u = mem['u']
            if mode == 'at_grasp_unheld': mem['phase'] = 'grasp_ready'; save()
        if mode != 'released_in_destination':
            if mode == 'on_source_unheld':
                mem['phase'] = 'approach'; plans = grasp_plans(B,u,s); approached = False
                for trial in range(3):
                    mem['grasp_plan'] = plans[trial]; offset = np.asarray(plans[trial]['offset'])
                    for stage in ['high_alignment','source_hover','grasp_descent']:
                        center = B.mean(axis=0); pad = np.asarray(geo.pad_position(s))
                        z = max(pad[2],center[2]+0.08) if stage == 'high_alignment' else center[2]+0.05
                        if stage == 'grasp_descent':
                            c = np.asarray(ref['table_plane']); table_z = -(c[3]+np.dot(c[:2],center[:2]+offset[:2]))/c[2]
                            z = max(center[2]-ref['height']/2,table_z-ref['fmin']+2*u)
                            axis = geo.rotation(q)[:,ref['opening_axis']]; width = float(np.max(B@axis)-np.min(B@axis))
                            values = {'grasp_pad_z': float(z), 'table_z': float(table_z), 'top_z': float(center[2]), 'projected_width': width, 'outer_pad_span': ref['outer_pad_span'], 'u': u, 'candidate': plans[trial]}; trace.append(values)
                            require(abs(center[2]-table_z-ref['height']) < 4*u and z-ref['pad_half_z'] < center[2]-u and width+4*u < ref['outer_pad_span'], 'Unresolved vertical overlap or opening geometry', values)
                        target = [float(center[0]+offset[0]),float(center[1]+offset[1]),float(z)]
                        if not guard(stage,target,'open',stage == 'grasp_descent'): break
                        move(target,q,'open',stage)
                        if stage == 'grasp_descent':
                            approached = True; s = api.state(); mem['phase'] = 'grasp_ready'; save()
                        else:
                            s = api.state(); finger_low = float(geo.pad_position(s)[2]+np.min(finger_offsets(s,s['tcp_quaternion_xyzw'])[:,2]))
                            require(finger_low > float(np.max(B[:,2]))+2*u, 'Possible source interaction invalidates the noncontact prior', {'finger_low_z':finger_low,'source_top_z':float(np.max(B[:,2])),'u':u})
                            mem['snapshot']['scope'] = 'Historical source pose retained only across this noncontact open-hand approach. The next local_supported review must find current partial source surfaces consistent and no possible disturbing interaction; otherwise request new evidence or reject. Camera motion is not source motion.'
                            save()
                    if approached: break
                require(approached, 'Three distinct measured grasp configurations lacked a supported descent', plans[:3])
            r = review('Before closure, are the actual open or partially closed fingers beside opposite source sides, with no observed table/neighbor intrusion? bracketing=observed is a visual fact, not inferred from the target pose or outer pad span. For a repaired already closed hand, accept observed fingers around this same item. Otherwise unknown/not_bracketed. Only observation is requested.', {'bracketing': ['observed', 'not_bracketed', 'unknown']}, {'reference': ref, 'current': mem['snapshot']})
            require(r['parameters']['bracketing'] == 'observed', 'Actual finger bracketing was not observed')
            restored_probe = 'probe' in mem
            if not restored_probe:
                mem['phase'] = 'closing'; save(); pulse('close',5,24)
                fields = dict(patch_fields)
                fields.update({'candidate': ['present','absent','unknown'], 'probe': ['supported','unsupported','unknown'], 'definitions': {'type': 'array','items': {'type': 'string','maxLength': 400},'minItems': 3,'maxItems': 3}})
                good = False
                for attempt in range(2):
                    r = review('After closure, candidate=present means the same package is visibly between fingers, NOT retained. probe=supported authorizes only a locally justified upward measurement lift of at most 0.035 m. Reject observed obstruction, not self-occlusion. Initialize a NEW LOCAL reference on ANY exposed rigid face, including the printed short end face. Request up to three uniquely identifiable physical marks p0,p1,p2; ONE reliably corresponding mark suffices for this orientation-preserving translation test. Prefer well-spread marks when available, but do not invent or require hidden marks or old landmarks. definitions has three entries describing the physical p0,p1,p2 identities, using unavailable for omitted marks. identity=exact concerns the obtained marks and body, not its complete perimeter. Choose patch_camera and an optional textured interior polygon excluding fingers/background, or patch=null. On retry select different measurable marks to resolve omissions. Neither a full shape registration nor already proven retention is required to begin this bounded measurement trial.', fields, {'identity': ref['identity'], 'attempt': attempt, 'diagnostics': trace[-2:]})
                    p = r['parameters']; cur = samples(r,['p0','p1','p2'])
                    if p['candidate'] == 'absent' or p['probe'] == 'unsupported': break
                    if p['identity'] == 'exact' and p['candidate'] == 'present' and p['probe'] == 'supported' and len(cur) >= 1:
                        names = [n for n in ['p0','p1','p2'] if n in cur]
                        X0 = np.asarray([cur[n]['world_m'] for n in names]); u0 = max(mem['u'],point_uncertainty(cur))
                        trace.append({'local_reference_names': names,'u': u0,'scope': 'Small-rotation translation retention only; full envelope measured separately.'})
                        if u0 <= 0.004: good = True; break
                require(good,'No obtainable identified local motion reference or supported probe',trace[-1])
                probe = {'points': X0.tolist(),'names': names,'measurements': cur,'definitions': p['definitions'],'identity': ref['identity'],'state': api.state(),'u': u0,'reference_frame_id': r['frame_id']}
                if p['patch'] is not None:
                    try:
                        t = api.track_init(p['patch_camera'],p['patch'])
                        probe.update({'handle': t['handle'],'camera': p['patch_camera'],'polygon': p['patch'],'tracker_reference_frame_id': t['frame_id']})
                    except Exception as e: trace.append({'local_patch_initialization_error': str(e)})
                api.checkpoint('local_probe',probe); mem['probe'] = probe
            probe = mem['probe']; X0 = np.asarray(probe['points']); u0 = probe['u']; s0 = probe['state']
            require(probe['identity'] == ref['identity'],'Saved probe belongs to another surface')
            lift = max(0.022,8*u0); require(lift <= 0.035,'Local uncertainty exceeds bounded probe capability',{'u': u0,'lift': lift})
            mem['phase'] = 'retention_test'; save()
            if float(np.linalg.norm(np.asarray(geo.pad_position(api.state()))-geo.pad_position(s0))) <= 4*u0+0.006:
                target = np.asarray(geo.pad_position(s0))+[0,0,lift]
                if restored_probe: guard('resume_retention_test',target,'keep')
                move(target,q,'keep','retention_measurement_lift')
            Y = None; u = u0
            if 'handle' in probe:
                t = api.track_update(probe['handle']); trace.append({'local_tracking_status': t['status'],'frame': t['frame_id'],'reference_frame': t['reference_frame_id'],'reason': t.get('reason')})
                if t['status'] == 'tracked':
                    x = np.asarray(t['reference_inlier_world_m']); spread = np.linalg.svd(x-x.mean(axis=0),compute_uv=False)/math.sqrt(len(x))
                    u = max(u0,float(t['rms_m']),float(t['uncertainty_floor_m']))
                    trace.append({'local_inliers': t['inliers'],'local_matches': t['matches'],'local_rms_m': t['rms_m'],'local_uncertainty_m': u,'local_spread_m': spread.tolist()})
                    if t['inliers'] >= 8 and t['inliers']/max(1,t['matches']) >= 0.55 and t['rms_m'] <= 0.0025 and u <= 0.004 and spread[1] > 1.2*u:
                        Y = geo.transform(X0,t['transform_initial_world_to_current_world'])
            if Y is None:
                names = probe.get('names',['p0','p1','p2'])
                r = review('Unknown local tracking is not proof of loss. Request CURRENT points named in required_names at their exact saved physical definitions, in either camera. identity=exact requires those correspondences unambiguous on the same package. Do not substitute stationary projections, robot motion, unrelated new marks or a full outline. Report ambiguous/unknown honestly.', {'identity': ['exact','ambiguous','unknown']}, {'reference': probe, 'required_names': names})
                cur = samples(r,names)
                require(r['parameters']['identity'] == 'exact' and len(cur) >= 1,'Neither tracked nor corresponding local motion is obtainable; keep jaws unchanged',r['measurement_errors'])
                kept = [n for n in names if n in cur]; X0 = X0[[names.index(n) for n in kept]]
                Y = np.asarray([cur[n]['world_m'] for n in kept]); u = max(u0,point_uncertainty(cur))
                probe = dict(probe); probe['names'] = kept; probe['points'] = X0.tolist(); probe['measurements'] = {n:probe['measurements'][n] for n in kept}
                mem['probe'] = probe; api.checkpoint('local_probe',probe)
            s = api.state(); hand = float(np.linalg.norm(np.asarray(geo.pad_position(s))-geo.pad_position(s0)))
            obj = float(np.linalg.norm(Y.mean(axis=0)-X0.mean(axis=0))); err = float(geo.attachment_error(X0,Y,s0,s)); tol = 3*max(u0,u)+0.001
            rotation_change = float(np.linalg.norm(geo.rotation(s['tcp_quaternion_xyzw'])-geo.rotation(s0['tcp_quaternion_xyzw'])))
            values = {'actual_hand_motion_m': hand,'observed_object_motion_m': obj,'attachment_error_m': err,'tolerance_m': tol,'observed_object_rise_m': float(Y.mean(axis=0)[2]-X0.mean(axis=0)[2]),'reference_frame': probe['reference_frame_id'],'current_frame': s['frame_id'],'local_witness_count': len(X0),'hand_rotation_frobenius': rotation_change}; trace.append(values)
            api.checkpoint('retention_measurement',values)
            require(u <= 0.004 and rotation_change <= 0.08 and hand > 4*max(u0,u)+0.006 and obj > hand-tol and err <= tol and values['observed_object_rise_m'] > 0.5*hand,'Measured small-rotation local motion did not establish retention; no transfer or reopening',values)
            mem['phase'] = 'retained_envelope_pending'; save()
            for attempt in range(2):
                try:
                    B,u,s = observe('transport envelope after measured local retention; partial identified face/edge is sufficient')
                    break
                except RuntimeError as e:
                    if not str(e).startswith('OBSERVATION_GAP:'): raise
                    require(attempt == 0, 'Envelope recovery exhausted; preserve jaws', str(e))
                    target = np.asarray(geo.pad_position(api.state()))+[0,0,0.035]
                    r = review('The envelope is unresolved, not proof of loss. Assess ONLY a 0.035 m upward observation action with unchanged jaws/orientation. external distinguishes observed obstruction, none observed and unknown. view=informative_up_supported requires positive local support AND an explanation of which missing face/edge this exposes in agentview. The wrist view of a held item stays nearly fixed; repeating that occlusion is not informative. Do not require a later transfer corridor certificate. Otherwise unsupported/unknown; no action follows.', {'external': ['observed_obstacle','none_observed','unknown'], 'view': ['informative_up_supported','unsupported','unknown']}, {'reference': ref, 'local_retention': values, 'pad_target': target.tolist(), 'gap': str(e)})
                    require(r['parameters']['external'] == 'none_observed' and r['parameters']['view'] == 'informative_up_supported', 'No justified informative envelope observation action', r['parameters'])
                    move(target,q,'keep','bounded_envelope_observation_up',40)
                    names = probe.get('names',['p0','p1','p2'])
                    r = review('After the view action, request CURRENT points in required_names at their saved physical definitions. identity=exact requires unambiguous correspondence on the same package; unknown tracking or camera motion alone proves neither retention nor loss. Do not replace measurements with hand predictions.', {'identity': ['exact','ambiguous','unknown']}, {'reference': probe, 'required_names': names})
                    cur = samples(r,names)
                    require(r['parameters']['identity'] == 'exact' and len(cur) == len(names), 'View recovery lacks independent motion evidence; preserve jaws', r['measurement_errors'])
                    V = np.asarray([cur[n]['world_m'] for n in names]); sv = api.state(); uv = max(u0,point_uncertainty(cur))
                    ev = float(geo.attachment_error(X0,V,s0,sv)); rise = float(V.mean(axis=0)[2]-X0.mean(axis=0)[2])
                    check = {'view_attachment_error_m': ev, 'u': uv, 'observed_rise_m': rise, 'frame_id': sv['frame_id']}; trace.append(check)
                    require(uv <= 0.004 and ev <= 3*uv+0.001 and rise > 0.5*float(np.linalg.norm(np.asarray(geo.pad_position(sv))-geo.pad_position(s0))), 'View action did not preserve measured retention', check)
            mem['held'] = True; mem['phase'] = 'retained'; save()
            ru = max(ref['u'], rim['rms'], rim['max_error'])
            for stage in ['lift_clear', 'transfer', 'lower_to_release']:
                pad = np.asarray(geo.pad_position(s)); bottom = B-ref['height']*normal(B)
                U = np.asarray(mem['snapshot']['bounds']); fmin = float(np.min(finger_offsets(s,q)[:,2]))
                down = max(float(pad[2]-np.min(bottom[:,2]-U[4:,2])), -fmin)
                z = rim['z']+down+ru+0.003 if stage == 'lower_to_release' else max(float(pad[2]),rim['z']+down+0.07)
                center = np.concatenate([B,bottom]).mean(axis=0)
                xy = pad[:2] if stage == 'lift_clear' else np.asarray(rim['xy'])-(center[:2]-pad[:2]); target = [float(xy[0]),float(xy[1]),float(z)]
                mem['phase'] = stage; guard(stage,target,'keep'); move(target,q,'keep',stage); B,u,s = observe(stage+' actual retained-object outcome')
            release_ok = False
            for refinement in range(2):
                bottom = B-ref['height']*normal(B); Q = np.concatenate([B,bottom]); U = np.asarray(mem['snapshot']['bounds']); pad = np.asarray(geo.pad_position(s))
                nominal = float(np.max(np.linalg.norm(Q[:,:2]-rim['xy'],axis=1)))
                radial = float(np.max(np.linalg.norm(Q[:,:2]-rim['xy'],axis=1)+np.linalg.norm(U[:,:2],axis=1)))
                low = float(np.min(bottom[:,2]-U[4:,2])); finger_low = float(pad[2]+np.min(finger_offsets(s,q)[:,2]))
                drop = float(np.max(bottom[:,2]+U[4:,2])-ref['floor_z'])
                values = {'nominal_radial_margin_m': rim['radius']-nominal, 'bounded_radial_margin_m': rim['radius']-ru-radial, 'bounded_bottom_margin_m': low-rim['z']-ru, 'finger_margin_m': finger_low-rim['z']-ru, 'upper_drop_m': drop, 'max_xyz_bound_m': U.max(axis=0).tolist(), 'refinement': refinement}; trace.append(values)
                release_ok = min(values['bounded_radial_margin_m'],values['bounded_bottom_margin_m'],values['finger_margin_m']) >= 0 and drop < 0.12
                if release_ok: break
                if refinement == 0:
                    delta = np.zeros(3); delta[:2] = np.asarray(rim['xy'])-Q.mean(axis=0)[:2]
                    delta[2] = max(0.0,rim['z']+ru+0.003-low,rim['z']+ru+0.003-finger_low)
                    if np.linalg.norm(delta) > 0.0008:
                        target = pad+delta; guard('release_geometry_refinement',target,'keep'); move(target,q,'keep','release_geometry_refinement',24,0.0008)
                    B,u,s = observe('Release margin refinement: measure a different clean face region or independent fiducial to constrain the reported XYZ uncertainty; maintain physical edge identities')
            require(release_ok, 'Release effect margin remains inconclusive after bounded centering/measurement refinement; no opening', values)
            mem['phase'] = 'release_pending'; mem['held'] = False; save(); pulse('open', 5, 12); mem['phase'] = 'released'; save()
            s = api.state(); move(np.asarray(geo.pad_position(s)) + [0, 0, 0.07], s['tcp_quaternion_xyzw'], 'keep', 'post_release_view_and_separation_on_reverse_vertical_path', 4)
        if mode == 'released_in_destination':
            s = api.state()
            if geo.pad_position(s)[2]+ref['fmin'] < rim['z']+0.04:
                target = np.asarray(geo.pad_position(s))+[0,0,0.07]
                guard('released_object_view_withdrawal',target,'keep'); move(target,s['tcp_quaternion_xyzw'],'keep','released_object_view_withdrawal',4)
        mem['held'] = False; mem['phase'] = 'verification'; save()
        vf = {'identity': ['same','ambiguous','unknown'], 'correspondence': ['exact','ambiguous','unknown'], 'relation': ['inside','on_rim','outside','held','unknown'], 'separation': ['observed','contact','unknown'], 'comparison': ['unchanged','changed','unknown'], 'definitions': {'type':'array','items':{'type':'string','maxLength':400},'minItems':2,'maxItems':2}, 'external': ['observed_obstacle','none_observed','unknown'], 'visibility': ['observed','partial_unobserved','self_occluded'], 'view': ['informative_up_supported','unsupported','not_needed']}
        base, stable, view_used = None, False, False
        for attempt in range(4):
            r = review('Assess actual released support in the CURRENT scene. identity=same means the intended item. relation=inside requires visible support in the bowl cavity, not projection over it or balancing on its rim; separation=observed requires no hand contact. Request current v0,v1 at one or two visible identifiable physical marks on any rigid face. With no reference, definitions names these marks; use unavailable for an omitted mark. With a reference, keep those exact physical definitions; correspondence=exact means obtained marks match them unambiguously, never stationary projections or replacement marks. comparison=unchanged requires visible unchanged object orientation AND support relative to the saved observation, not just a fixed hand. Otherwise changed/unknown. No full outline or old shape registration is needed. external concerns only a possible 0.035 m upward hand withdrawal; distinguish observed external material, none observed, and unknown. visibility separately reports unobserved space or self-occlusion. view=informative_up_supported only if that local action has positive geometric support and exposes specifically missing object/support evidence; self-occlusion alone is not an obstacle. Unknown evidence is not clearance.', vf, {'task':task,'identity':ref['identity'],'released_reference':base,'attempt':attempt})
            p = r['parameters']; cur = samples(r,['v0','v1'])
            require(p['relation'] not in ['on_rim','outside','held'] and p['separation'] != 'contact', 'Observed final relation is not released interior support; do not disturb automatically', p)
            names = [n for n in ['v0','v1'] if n in cur and (base is None or n in base['points'])]
            good = p['identity'] == 'same' and p['correspondence'] == 'exact' and p['relation'] == 'inside' and p['separation'] == 'observed' and len(names) > 0
            if good:
                uv = point_uncertainty(cur)
                if base is not None:
                    displacement = max(float(np.linalg.norm(np.asarray(cur[n]['world_m'])-base['points'][n]['world_m'])) for n in names)
                    tolerance = max(0.003,2*max(uv,base['u']))
                    trace.append({'released_mark_motion_m':displacement,'tolerance_m':tolerance,'reference_frame':base['frame'],'current_frame':r['frame_id'],'visible_orientation_and_support':p['comparison']})
                    if displacement <= tolerance and p['comparison'] == 'unchanged': stable = True; break
                base = {'points':{n:cur[n] for n in names},'definitions':p['definitions'],'u':uv,'frame':r['frame_id'],'identity':ref['identity']}
                api.checkpoint('released_reference',base)
                if attempt < 3: pulse('keep',3)
            elif not view_used and attempt < 2 and p['external'] == 'none_observed' and p['view'] == 'informative_up_supported':
                sv = api.state(); move(np.asarray(geo.pad_position(sv))+[0,0,0.035],sv['tcp_quaternion_xyzw'],'keep','informative_released_view',4); view_used = True
            else:
                require(False,'Released support or current corresponding marks remain unobservable; leave object undisturbed',{'parameters':p,'measurement_errors':r['measurement_errors']})
        require(stable,'Bounded released-object stability verification exhausted; no regrasp',trace[-1])
        mem['phase'] = 'completion_proposed'; save()
        return {'completion_proposed': True, 'evidence': trace, 'limitations': ['Uncertainty is heuristic, not a calibrated confidence bound.', 'Observed local feasibility is not a swept-volume certificate.', 'This proposal is not the isolated native evaluator result.']}
    except Exception as e:
        trace.append({'stopped': str(e), 'phase': mem.get('phase', 'initializing'), 'held_evidence': mem.get('held', False)})
        return {'completion_proposed': False, 'evidence': trace}

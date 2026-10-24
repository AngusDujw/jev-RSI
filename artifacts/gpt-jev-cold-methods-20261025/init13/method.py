def main(api):
    task = 'could you put the cream cheese into the bowl'
    log, D, H = [], {}, {'fallbacks': 0}
    cameras = ['agentview', 'robot0_eye_in_hand']
    pixel = {'type': 'array', 'items': {'type': 'integer', 'minimum': 0, 'maximum': 767}, 'minItems': 2, 'maxItems': 2}
    polygon = {'type': ['array', 'null'], 'items': pixel, 'minItems': 3, 'maxItems': 16}
    rim_fields = {'inner_camera': cameras, 'inner_pixels': {'type': ['array', 'null'], 'items': pixel, 'minItems': 4, 'maxItems': 8}}
    Q = {}
    for axis in ['x', 'y', 'z', 'rx', 'ry', 'rz']:
        Q[axis] = {'type': 'choice', 'instructions': 'For world axis '+axis+', read state.processed_features.axes.'+axis+'.goal_relation. Follow that relation only; do not infer a different object goal.', 'criteria': {'negative': 'decrease: use the negative world component', 'hold': 'within_tolerance: no component motion', 'positive': 'increase: use the positive world component'}}
    Q['gripper'] = {'type': 'choice', 'instructions': 'Read state.processed_features.objective.gripper and select exactly that requested jaw action.', 'criteria': {'open': 'objective is open', 'close': 'objective is close', 'keep': 'objective is keep'}}
    def record(kind, values):
        log.append({'kind': kind, 'values': values}); api.note(str(log[-1]))
    def fail(reason, values=None):
        record(reason, values); raise RuntimeError(reason)
    def save(phase=None):
        if phase is not None: D['phase'] = phase
        D['recent_evidence'] = log[-8:]; api.checkpoint('manipulation', D)
    def review(question, fields, context=None, final=False):
        if api.state()['budgets']['gpt_remaining'] < (1 if final else 2): fail('No review resource for the required current identity, correspondence, or local-action evidence', {'remaining_reviews': api.state()['budgets']['gpt_remaining'], 'phase': D.get('phase'), 'requested_evidence': question[:450]})
        r = api.review(question, context=context, fields=fields)
        if r['measurement_errors']: record('measurement_errors', r['measurement_errors'])
        if r['status'] == 'stop': fail('Review stopped', r['explanation'])
        return r
    def valid(r, name, group='points'):
        return name in r[group] and not any(e['name'] == name for e in r['measurement_errors'])
    def plane_region(r, name):
        if not valid(r, name, 'regions'): fail('Missing measured region', name)
        p = geo.plane(r['regions'][name]['world_m'])
        if p['rms_m'] > 0.003 or min(p['in_plane_spread_m']) < 0.004 or p['coefficients'][2] < 0.98: fail('Unusable horizontal surface fit', {'name': name, 'fit': p})
        return p
    def outer_geometry(r):
        names = ['b'+str(i) for i in range(6) if valid(r, 'b'+str(i))]
        X = np.array([r['points'][k]['world_m'] for k in names]); best = None
        if len(X) < 4: fail('Need four depth-valid outer-lip samples', {'names': names})
        tolerance = max(0.0015, D['u'])
        for i in range(len(X)-2):
            for j in range(i+1, len(X)-1):
                for k in range(j+1, len(X)):
                    try: p = geo.plane(X[[i, j, k]])
                    except Exception: continue
                    if p['coefficients'][2] < 0.98: continue
                    residual = np.abs(X@np.array(p['coefficients'][:3])+p['coefficients'][3])
                    ids = [n for n in range(len(X)) if residual[n] <= tolerance]
                    score = (len(ids), -float(np.sum(residual[ids])))
                    if best is None or score > best[0]: best = (score, ids)
        if best is None or len(best[1]) < 4: fail('No consistent measured outer-lip plane', {'points': X.tolist(), 'tolerance_m': tolerance})
        ids = best[1]; Y = X[ids]; p, c = geo.plane(Y), geo.circle_xy(Y)
        evidence = {'plane': p, 'circle': c, 'used': [names[n] for n in ids], 'rejected': [names[n] for n in range(len(X)) if n not in ids], 'frame_id': r['frame_id']}
        record('outer_lip_fit', evidence)
        if p['coefficients'][2] < 0.98 or p['rms_m'] > tolerance or min(p['in_plane_spread_m']) < 2*D['u'] or c['max_radial_error_m'] > max(0.003, 1.5*D['u']) or c['largest_angular_gap_rad'] > 3.7: fail('Outer-lip geometry unresolved', evidence)
        return {'xy': c['center_xy_m'], 'radius': c['radius_m'], 'rim_z': float(np.max(Y[:, 2])), 'error': p['rms_m']+c['max_radial_error_m']+0.001, 'plane': p, 'frame_id': r['frame_id']}
    def bowl_geometry(r):
        outer = outer_geometry(r); v = r['parameters']; pixels = v['inner_pixels']; points = []; pixel_error = 0.0
        if pixels is None: fail('Visible inner-lip correspondence unavailable; outer lip is not the aperture')
        calibration = api.camera(v['inner_camera']); K = np.array(calibration['K']); origin = np.array(calibration['camera_to_world_opencv'])[:3, 3]
        for px in pixels:
            try: point = api.plane_point(v['inner_camera'], px, outer['plane']['coefficients'])
            except Exception as e:
                record('inner_lip_ray_unavailable', {'pixel': px, 'error': str(e)}); continue
            points.append(point['world_m'])
            pixel_error = max(pixel_error, 1.5*float(np.linalg.norm(np.array(point['world_m'])-origin))/min(float(K[0, 0]), float(K[1, 1])))
        if len(points) < 4 or not valid(r, 'floor'): fail('Insufficient current aperture evidence', {'inner_ray_count': len(points), 'floor_measured': valid(r, 'floor')})
        c = geo.circle_xy(points); shift = float(np.linalg.norm(np.array(c['center_xy_m'])-np.array(outer['xy'])))
        floor = r['points']['floor']['world_m']; error = outer['plane']['rms_m']+c['max_radial_error_m']+pixel_error
        evidence = {'inner_circle': c, 'outer': outer, 'center_difference_m': shift, 'ray_sampling_allowance_m': pixel_error, 'error_m': error, 'floor': floor, 'frame_id': r['frame_id']}
        record('current_aperture_fit', evidence)
        if c['max_radial_error_m'] > max(0.0025, D['u']) or c['largest_angular_gap_rad'] > 3.7 or shift > 3*D['u']+outer['plane']['rms_m'] or c['radius_m'] > outer['radius']+D['u'] or outer['rim_z']-floor[2] < 2*D['u']: fail('Inner aperture model unresolved', evidence)
        D['approach_obstacle'] = outer
        return {'xy': c['center_xy_m'], 'radius': c['radius_m'], 'rim_z': outer['rim_z'], 'floor': floor, 'error': error, 'frame_id': r['frame_id']}
    def init_track(camera, poly, T):
        if poly is None: return
        try:
            t = api.track_init(camera, poly)
            H['handle'], H['anchor'] = t['handle'], np.array(T)
            H.setdefault('tracks', []).append({'handle': t['handle'], 'T': np.array(T).tolist(), 'u': H.get('registration_uncertainty', D['u'])})
            record('patch_reference', {'frame_id': t['frame_id'], 'features': t['reference_features'], 'camera': camera})
        except Exception as e:
            record('patch_initialization_unavailable', str(e))
    placement_fields = dict(rim_fields, rim_identity=['same_inner_rim', 'ambiguous', 'unknown'], external_obstruction=['present', 'none_seen', 'unknown'], visibility=['observed', 'self_or_item_occluded', 'unobserved'], transfer_action=['supported', 'defer'])
    placement_question = ' Also measure the correct receiving bowl: rim_identity=same_inner_rim identifies its INNER upper-lip boundary, not the plate or a lower decorative ring. Request b0..b5 distributed depth-valid TOP OUTER lip points and floor on the visible low interior. Return inner_camera and 4..8 visible inner_pixels at that same lip height, or null. Do not invent hidden arcs. Separately assess only the adjacent source-to-bowl neighborhood: external_obstruction=present means a visible external obstacle impedes a vertical rise or above-rim lateral transfer; none_seen is not certified clearance; unknown is unclassified. visibility distinguishes observed space, robot/item occlusion, and other unobserved space. transfer_action=supported means local evidence supports a rise of at most 0.12 m, followed by at most 0.16 m lateral motion toward this bowl, ONLY after measured retention and with both item and fingers numerically above the measured rim. Self-occlusion alone is not an external obstacle. Defer if this local action lacks support. This does not authorize descent into the bowl, or require visibility of a later route. Missing bowl/transfer evidence does not prohibit the separate reverse-approach retention lift.'
    end_question = ' For an alternative registration when old printed landmarks are hidden, request current_face: an uncontaminated interior RGB-D region of the visible printed planar face, explicit camera, box, stride=4. end_identity=same_defined_short_end means the actual short physical end nearest the capital C beginning Cream, opposite the end nearest the capital C beginning Cheese. Return end_camera and two end_pixels at the visible intersections of THIS face plane with that end and its long sides: first the side toward the dark oval sublabel (historical vertex 0), then the opposite side (vertex 1). These are physical identities, not image-left/right. Select the actual face boundary, not a raised trim edge. Return ambiguous/unknown and null if not identifiable. Only two visible corners are requested, not a complete perimeter. The code checks their measured length, face normal, and the independently observed printed landmark(s).'
    def end_registration(r, ids):
        v = r['parameters']
        if v['end_identity'] != 'same_defined_short_end' or v['end_pixels'] is None or not valid(r, 'current_face', 'regions') or len(ids) < 1: fail('No usable patch registration or identifiable face/end correspondence', {'ids': ids, 'end_identity': v['end_identity']})
        plane = geo.plane(r['regions']['current_face']['world_m'])
        if plane['rms_m'] > 0.0015 or min(plane['in_plane_spread_m']) < 0.002 or plane['coefficients'][2] < 0.98: fail('Current visible face plane unresolved', plane)
        C = np.array([api.plane_point(v['end_camera'], px, plane['coefficients'])['world_m'] for px in v['end_pixels']]); V = np.array(D['vertices'])
        cal = api.camera(v['end_camera']); K = np.array(cal['K']); origin = np.array(cal['camera_to_world_opencv'])[:3, 3]
        pixel_u = 1.5*float(np.max(np.linalg.norm(C-origin, axis=1)))/min(float(K[0, 0]), float(K[1, 1]))+2*plane['rms_m']
        old_edge, edge = V[1]-V[0], C[1]-C[0]; old_len, length = float(np.linalg.norm(old_edge)), float(np.linalg.norm(edge))
        if length < 4*pixel_u or abs(length-old_len) > 2*D['u']+2*pixel_u: fail('Identified short end has inconsistent measured length', {'reference_m': old_len, 'current_m': length, 'pixel_allowance_m': pixel_u})
        n0 = np.array(D['top']['coefficients'][:3]); n0 /= np.linalg.norm(n0); n = np.array(plane['coefficients'][:3]); n /= np.linalg.norm(n)
        e0, e = old_edge/old_len, edge/length
        R = np.column_stack([e, np.cross(n, e), n]) @ np.column_stack([e0, np.cross(n0, e0), n0]).T
        T = np.eye(4); T[:3, :3] = R; T[:3, 3] = C[0]-R@V[0]
        a = np.array([D['refs'][k] for k in ids]); b = np.array([r['points'][k]['world_m'] for k in ids])
        residual = float(np.max(np.linalg.norm(geo.transform(a, T)-b, axis=1)))
        pose_u = pixel_u*(1+2*float(np.max(np.linalg.norm(V[:4]-V[0], axis=1)))/length)
        uncertainty = D['u']+max(pose_u, residual)
        evidence = {'frame_id': r['frame_id'], 'reference_frame_id': D['reference_frame_id'], 'plane': plane, 'end_world_m': C.tolist(), 'end_camera': v['end_camera'], 'end_pixels': v['end_pixels'], 'ids': ids, 'current_landmarks': b.tolist(), 'residual_m': residual, 'pose_allowance_m': pose_u, 'uncertainty_m': uncertainty, 'T': T.tolist()}
        record('partial_outline_registration', evidence)
        if residual > D['u']+pose_u+0.001: fail('End/printed-landmark correspondence disagrees', evidence)
        D['end_reference'] = evidence; save()
        return T, uncertainty
    def tracked_pose():
        for ref in reversed(H.get('tracks', [])):
            t = api.track_update(ref['handle'])
            if t['status'] != 'tracked': continue
            a = np.array(t['reference_inlier_world_m']); spread = np.linalg.svd(a-a.mean(axis=0), compute_uv=False)/math.sqrt(max(1, len(a)))
            if t['inliers'] < 12 or t['inliers']/max(1, t['matches']) < 0.6 or t['rms_m'] > 0.0025 or t['uncertainty_floor_m'] > 0.004 or len(spread) < 2 or spread[1] < 0.004: continue
            T = np.array(t['transform_initial_world_to_current_world']) @ np.array(ref['T'])
            u = ref['u']+max(t['rms_m'], t['uncertainty_floor_m'])
            record('registration', {'inliers': t['inliers'], 'matches': t['matches'], 'rms_m': t['rms_m'], 'uncertainty_floor_m': t['uncertainty_floor_m'], 'frame_id': t['frame_id'], 'reference_frame_id': t['reference_frame_id']})
            return {'T': T.tolist(), 'points': geo.transform([D['refs'][k] for k in D['ids']], T).tolist(), 'uncertainty': u, 'frame_id': t['frame_id'], 'source': 'RGBD_patch'}
        return None
    def observed():
        if H.get('observation', {}).get('frame_id') == api.state()['frame_id']: return H['observation']
        o = tracked_pose()
        if o is not None: H['observation'] = o; return o
        record('registration_unresolved', {'frame_id': api.state()['frame_id'], 'available_reviews': api.state()['budgets']['gpt_remaining']})
        A = np.array([D['refs'][k] for k in D['ids']]); T = None; uncertainty = H.get('registration_uncertainty', D['u']); source = 'landmarks'
        if T is None:
            if H['fallbacks'] >= 4: fail('Landmark recovery bound reached')
            H['fallbacks'] += 1
            refresh = D['phase'] in ['ready', 'approach'] and not H.get('scene_refreshed', False)
            uncertainty = D['u']
            fields = {'identity': ['unambiguous', 'ambiguous', 'unknown'], 'patch_camera': cameras, 'patch_polygon': polygon, 'end_identity': ['same_defined_short_end', 'ambiguous', 'unknown'], 'end_camera': cameras, 'end_pixels': dict(polygon, minItems=2, maxItems=2)}
            extra = end_question
            placement_request = D['phase'] in ['closing', 'lifting', 'held'] and not H.get('placement_ready', False)
            if placement_request: fields.update(placement_fields); extra += placement_question
            if refresh:
                fields.update({'rim_identity': ['same_bowl_outer_lip', 'ambiguous', 'unknown'], 'upward_observation': ['supported', 'unknown'], 'above_source_action': ['supported', 'observed_obstacle', 'unknown']})
                extra += ' For this approach only, refresh the receiving bowl OUTER lip as a nearby obstacle. rim_identity=same_bowl_outer_lip identifies its exposed top outer lip, not the sloping interior or table. Request b0..b5 distributed over the exposed outer lip at its top height, using reliable surface depth and either view. Omit occluded or mixed-depth samples; four consistent distributed samples suffice. Do not request an inner contour or floor yet: those are placement evidence, not prerequisites to approaching the source. upward_observation=supported supports only a 0.02 m vertical rise preserving orientation and jaw state. Separately, above_source_action=supported means local visible evidence supports, after that rise, a source-centered lateral adjustment of at most 0.03 m and yaw adjustment of at most 0.35 rad, with the entire measured finger envelope at least 0.01 m above this rim. The bowl is modeled separately in code; report observed_obstacle for another visible obstacle in that small above-source neighborhood, or unknown if no justified local action can be identified. This is not certified clearance and does not authorize descent. The next descent will have its own current alignment review.'
            r = review('Recover current registration of the source item. Request named points '+str(D['ids'])+' at the SAME physical printed landmarks defined in context. Use visible interior markings, not perimeter corners or stationary projections. Return identity=unambiguous only for defensible individual correspondences; omit hidden or ambiguous points. Optionally select a current textured patch wholly on this same rigid face with patch_camera and patch_polygon; this patch is not a substitute for correspondence to the saved reference.'+extra, fields, {'task': task, 'definitions': D['labels'], 'reference_points': D['refs'], 'reference_frame_id': D['reference_frame_id'], 'phase': D['phase'], 'historical_bowl': D['bowl']})
            if refresh:
                names = D['ids']+['b'+str(i) for i in range(6)]
                D['approach_measurements'] = {'frame_id': r['frame_id'], 'parameters': r['parameters'], 'points': {k: r['points'][k] for k in names if valid(r, k)}, 'measurement_errors': r['measurement_errors']}; save()
                if r['parameters']['rim_identity'] != 'same_bowl_outer_lip': fail('Current outer-lip identity unresolved')
                D['approach_obstacle'] = outer_geometry(r)
                H['scene_refreshed'] = True; H['up_supported'] = r['parameters']['upward_observation'] == 'supported'
                H['above_source_supported'] = r['parameters']['above_source_action'] == 'supported'
                if r['parameters']['above_source_action'] == 'observed_obstacle': fail('Observed obstruction in revised above-source neighborhood', r['explanation'])
                record('current_approach_obstacle', D['approach_obstacle']); save()
            ids = [k for k in D['ids'] if valid(r, k)]
            D['registration_observation'] = {'frame_id': r['frame_id'], 'parameters': r['parameters'], 'points': {k: r['points'][k] for k in ids}, 'measurement_errors': r['measurement_errors']}
            if D['phase'] not in ['ready', 'approach']: D.pop('approach_measurements', None)
            save()
            if placement_request:
                H['local_transfer'] = r['parameters']['transfer_action'] == 'supported' and r['parameters']['external_obstruction'] != 'present'
                if r['parameters']['rim_identity'] == 'same_inner_rim':
                    try:
                        D['bowl'] = bowl_geometry(r); H['placement_ready'] = True
                        D['placement_basis'] = {'frame_id': r['frame_id'], 'parameters': r['parameters']}; save()
                    except Exception as e: record('placement_measurement_deferred_not_a_lift_precondition', str(e))
            if r['parameters']['identity'] != 'unambiguous': fail('Ambiguous printed-landmark identity', {'valid_ids': ids, 'identity': r['parameters']['identity']})
            if len(ids) < 3:
                T, uncertainty = end_registration(r, ids); H['registration_uncertainty'] = uncertainty
                init_track(r['parameters']['patch_camera'], r['parameters']['patch_polygon'], T)
                H['observation'] = {'T': T.tolist(), 'points': geo.transform(A, T).tolist(), 'uncertainty': uncertainty, 'frame_id': r['frame_id'], 'source': 'measured_face_end_and_printed_landmark'}
                return H['observation']
            a = np.array([D['refs'][k] for k in ids]); b = np.array([r['points'][k]['world_m'] for k in ids]); ac, bc = a.mean(axis=0), b.mean(axis=0)
            spread = np.linalg.svd(a-ac, compute_uv=False)/math.sqrt(len(a))
            if spread[1] < max(0.003, 2*D['u']): fail('Ambiguous landmark spatial support', spread.tolist())
            U, S, V = np.linalg.svd((a-ac).T @ (b-bc)); R = V.T @ U.T
            if np.linalg.det(R) < 0: V[-1, :] *= -1; R = V.T @ U.T
            T = np.eye(4); T[:3, :3] = R; T[:3, 3] = bc-R@ac
            residual = float(np.max(np.linalg.norm(geo.transform(a, T)-b, axis=1)))
            if residual > max(0.004, 2*D['u']): fail('Nonrigid or incorrect landmark correspondence', {'residual_m': residual, 'ids': ids})
            uncertainty += residual+0.0015; frame = r['frame_id']; H['registration_uncertainty'] = uncertainty
            init_track(r['parameters']['patch_camera'], r['parameters']['patch_polygon'], T)
            record('landmark_recovery', {'ids': ids, 'residual_m': residual, 'uncertainty_m': uncertainty, 'frame_id': frame})
        H['observation'] = {'T': T.tolist(), 'points': geo.transform(A, T).tolist(), 'uncertainty': uncertainty, 'frame_id': frame, 'source': source}
        return H['observation']
    def plan_approach():
        s = api.state(); own = s['own_geometry']; top = np.array(D['vertices'])[:4]
        edges = np.roll(top, -1, axis=0)-top; lengths = np.linalg.norm(edges[:, :2], axis=1)
        long = edges[int(np.argmax(lengths))].copy(); long[2] = 0.0; long /= np.linalg.norm(long)
        short = np.array([-long[1], long[0], 0.0]); center = top.mean(axis=0)
        lo, hi, offset = np.array(own['finger_low_offset_tool_m']), np.array(own['finger_high_offset_tool_m']), np.array(own['pad_center_in_tool_m'])
        envelope = np.array([[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]])
        obstacle = D['approach_obstacle']; bc = np.array(obstacle['xy']); tested = []; selected = None
        for yaw in [0.0, 0.20, -0.20, 0.35, -0.35]:
            q = api.compose(D['q'], [0.0, 0.0, yaw]); R = geo.rotation(q); opening = R[:, 1]
            alignment = abs(float(np.dot(short, opening)))
            if alignment < 0.90: continue
            padhalf = 0.5*(abs(float(np.dot(long, R[:, 0])))*own['pad_extent_in_tool_m'][0]+abs(float(np.dot(long, R[:, 2])))*own['pad_extent_in_tool_m'][2])
            skew = 0.5*float(min(lengths))*abs(float(np.dot(long, opening)))/alignment
            allowance = D['u']+0.0025+0.04*float(min(lengths))/2
            reach = float(max(lengths))/2-padhalf-skew-allowance
            if reach <= 0: continue
            W = (envelope-offset)@R.T
            margin = D['u']+obstacle['error']+0.0025+0.04*float(np.max(np.linalg.norm(W[:, :2], axis=1)))
            for fraction in [0.0, 0.5, -0.5, 1.0, -1.0]:
                c = center+long*(fraction*reach); xy = W[:, :2]+c[:2]; mid = xy.mean(axis=0)
                distance = 0.0
                if np.linalg.norm(mid-bc) > np.max(np.linalg.norm(xy-mid, axis=1)):
                    distance = 10.0
                    for i in range(len(xy)):
                        for j in range(i+1, len(xy)):
                            e = xy[j]-xy[i]; t = max(0.0, min(1.0, float(np.dot(bc-xy[i], e))/max(1e-12, float(np.dot(e, e)))))
                            distance = min(distance, float(np.linalg.norm(xy[i]+t*e-bc)))
                gap = distance-obstacle['radius']
                tested.append({'yaw_delta_rad': yaw, 'long_offset_m': fraction*reach, 'finger_to_outer_lip_m': gap, 'required_margin_m': margin})
                if gap > margin:
                    selected = {'q': q, 'center_xy': c[:2].tolist(), 'low': float(np.min(W[:, 2])), 'evidence': tested[-1], 'contact_longitudinal_allowance_m': allowance}
                    break
            if selected is not None: break
        record('bounded_approach_candidates', tested)
        if selected is None: fail('No supported local grasp avoids current outer rim', {'obstacle': obstacle, 'candidates': tested})
        D['q'] = selected['q']; D['grasp']['center_xy'] = selected['center_xy']; D['grasp']['finger_low_relative_pad_z'] = selected['low']
        D['grasp']['approach_clearance'] = selected['evidence']; D['grasp']['contact_longitudinal_allowance_m'] = selected['contact_longitudinal_allowance_m']
        record('revised_approach', selected); save()
    def attachment(a, sa, b, sb, proof=False):
        err = float(geo.attachment_error(a['points'], b['points'], sa, sb)); u = max(a['uncertainty'], b['uncertainty'])
        hand = np.array(geo.pad_position(sb))-np.array(geo.pad_position(sa)); item = np.mean(np.array(b['points'])-np.array(a['points']), axis=0)
        evidence = {'attachment_error_m': err, 'hand_motion_m': hand.tolist(), 'item_motion_m': item.tolist(), 'uncertainty_m': u, 'lift_test': proof}
        record('retention_comparison', evidence)
        if err > max(0.006, 2*u+0.002): fail('Retention unresolved: object and hand motion disagree', evidence)
        if proof and (hand[2] < 0.022 or item[2] < max(3*u, 0.65*hand[2])): fail('No measured retention lift', evidence)
    def raw(grip):
        s = api.state()
        if s['budgets']['jev_remaining'] < 1 or s['budgets']['native_steps_remaining'] < 3: fail('Physical budget exhausted')
        r = api.control(np.array(geo.pad_position(s)).tolist(), s['tcp_quaternion_xyzw'], grip, Q, features={'phase': D['phase'], 'purpose': 'jaw transition or settling at measured current pose'}, tool_point='pad_center', steps=3, position_tolerance=0.004, rotation_tolerance=0.04)
        if r['status'] == 'stalled' or (grip != 'keep' and r['choices']['gripper'] != grip): fail('Jaw transition not delivered', r)
        record('jaw_or_settle_receipt', {'status': r['status'], 'choices': r['choices'], 'frame_id': r['frame_id']}); return r
    def move(target, q, grip, label, final=False, inspect=True):
        target = np.array(target); viewed = False
        for leg in range(32):
            s = api.state(); p = np.array(geo.pad_position(s)); delta = target-p; distance = float(np.linalg.norm(delta))
            angle = 2*math.acos(min(1.0, abs(float(np.dot(q, s['tcp_quaternion_xyzw'])))))
            tolerance = 0.0015 if D['phase'] == 'held' else 0.004
            if distance <= tolerance and angle <= 0.04 and grip == 'keep': return
            reserve = 2 if final else 18
            if s['budgets']['jev_remaining'] <= reserve or s['budgets']['native_steps_remaining'] <= 3*reserve: fail('Motion reserve reached', {'phase': label, 'remaining_m': distance})
            step = p + delta*min(1.0, 0.12/max(distance, 0.000001)); action = 'advance'
            if inspect:
                fields = {'external_obstruction': ['present', 'none_seen', 'unknown'], 'visibility': ['observed', 'self_or_item_occluded', 'unobserved'], 'action': ['advance', 'probe', 'view_up', 'stop']}
                if label == 'finger approach': fields['alignment'] = ['pads_straddle_short_sides', 'misaligned', 'unknown']
                r = review('Assess only the NEXT proposed bounded motion in context. external_obstruction=present means a visible external obstacle impedes it; none_seen means none observed, NOT certified clearance; unknown means no classification. visibility distinguishes observed neighborhood, robot/item occlusion, and other unobserved space. action=advance permits this at-most-0.12m leg from local evidence; probe permits at most 0.02m of justified observation-producing progress in the locally supported direction; view_up permits a 0.02m upward observation move ONLY if the local upward space supports it; stop means no justified action. Do not require visibility of the later route. Self-occlusion alone is not an external obstacle. For finger approach additionally report alignment: both pads must straddle the measured short sides with lateral clearance; a pose target alone does not prove that. Use measured own finger envelope plus visible object evidence, without demanding every outline corner.', fields, {'task': task, 'phase': label, 'next_pad_target': step.tolist(), 'gripper': grip, 'geometry': D.get('grasp'), 'bowl': D.get('bowl'), 'uncertainty_m': D['u']}, final)
                v = r['parameters']; action = v['action']
                if v['external_obstruction'] == 'present' or action == 'stop': fail('No justified local motion', v)
                if label == 'finger approach' and v['alignment'] != 'pads_straddle_short_sides' and action != 'view_up': fail('Finger-side clearance unresolved', v)
                if action == 'probe': step = p+delta*min(1.0, 0.02/max(distance, 0.000001))
                if action == 'view_up':
                    if viewed: fail('Repeated view does not resolve the local gap', v)
                    viewed = True; step = p+np.array([0.0, 0.0, 0.02])
            r = api.drive(step.tolist(), q, 'keep' if action == 'view_up' else grip, Q, features={'phase': label, 'authorized_local_action': action, 'uncertainty_m': D['u'], 'goal_pad_world_m': step.tolist()}, tool_point='pad_center', max_calls=min(20, s['budgets']['jev_remaining']-reserve), translation_limit=0.02, rotation_limit=0.10, steps=3, position_tolerance=0.0025 if label == 'finger approach' else tolerance, rotation_tolerance=0.04)
            D['last_motion'] = {'phase': label, 'status': r['status'], 'frame_id': r['frame_id'], 'position_error_m': r['position_error_m']}; save()
            progress = float(np.linalg.norm(np.array(geo.pad_position(api.state()))-p))
            if r['status'] == 'stalled' or (r['status'] == 'lease_exhausted' and progress < 0.003): fail('Motion stopped without useful progress', D['last_motion'])
            if action != 'view_up' and r['status'] == 'reached' and float(np.linalg.norm(step-target)) < 0.0001: return
        fail('Local motion bound reached', {'phase': label, 'target': target.tolist()})
    def bowl_cloud():
        b = D['bowl']; radius = D['approach_obstacle']['radius']+0.012
        corners = [[b['xy'][0]+x, b['xy'][1]+y, z] for x in [-radius, radius] for y in [-radius, radius] for z in [b['floor'][2]-0.008, b['rim_z']+0.065]]
        c = api.camera('agentview'); P = geo.transform(corners, np.linalg.inv(np.array(c['camera_to_world_opencv'])))
        if np.min(P[:, 2]) <= 0: fail('Bowl observation is behind the camera')
        uv = P@np.array(c['K']).T; uv = uv[:, :2]/uv[:, 2:3]
        lo = np.maximum(0, np.floor(uv.min(axis=0)-4)).astype(int); hi = np.minimum(767, np.ceil(uv.max(axis=0)+4)).astype(int)
        if np.any(hi-lo < 8): fail('Bowl crop is outside the current image')
        return api.cloud('agentview', [int(lo[0]), int(lo[1]), int(hi[0]), int(hi[1])], stride=4)
    def blue(rgb):
        C = np.array(rgb, dtype=float)
        return (C[:, 2]-C[:, 0])/np.maximum(C.sum(axis=1), 1e-6)
    def color_reference():
        try:
            r = D['registration_observation']; v = r['parameters']; poly = np.array(v['patch_polygon']); lo, hi = poly.min(axis=0), poly.max(axis=0)
            c = api.cloud(v['patch_camera'], [int(lo[0]), int(lo[1]), int(hi[0]), int(hi[1])], stride=4)
            X, px = np.array(c['world_m']), np.array(c['pixels']); crosses = []
            for i in range(len(poly)):
                e = poly[(i+1)%len(poly)]-poly[i]; d = px-poly[i]; crosses.append(e[0]*d[:, 1]-e[1]*d[:, 0])
            cross = np.array(crosses); inside = np.all(cross >= 0, axis=0) | np.all(cross <= 0, axis=0)
            plane = D['end_reference']['plane']['coefficients']; inside &= np.abs(X@np.array(plane[:3])+plane[3]) < 0.0015
            if int(np.sum(inside)) < 12: raise RuntimeError('Insufficient identified face color samples')
            bg = bowl_cloud(); Y = np.array(bg['world_m']); b = D['bowl']
            mask = (np.linalg.norm(Y[:, :2]-np.array(b['xy']), axis=1) < D['approach_obstacle']['radius']+0.002) & (Y[:, 2] < b['rim_z']+0.003)
            if int(np.sum(mask)) < 20: raise RuntimeError('Insufficient bowl appearance samples')
            source = float(np.percentile(blue(c['rgb'])[inside], 25)); background = float(np.percentile(blue(bg['rgb'])[mask], 99))
            if source-background <= 0.005: raise RuntimeError('Source and bowl colors are not discriminative')
            D['color_basis'] = {'threshold': (source+background)/2, 'source_quartile': source, 'background_99_percentile': background, 'frame_id': c['frame_id'], 'camera': v['patch_camera'], 'polygon': v['patch_polygon'], 'meaning': 'Appearance of the identified carton face versus the visible bowl; not a segmentation oracle'}
            record('appearance_reference', D['color_basis']); save()
        except Exception as e: record('optional_appearance_reference_unavailable', str(e))
    def numeric_result_view():
        c = bowl_cloud(); X = np.array(c['world_m']); b = D['bowl']; outer = D['approach_obstacle']
        if len(X) < 30: fail('Insufficient current bowl depth samples')
        radial = np.linalg.norm(X[:, :2]-np.array(outer['xy']), axis=1)
        mask = (np.abs(X[:, 2]-b['rim_z']) < 0.0025) & (radial > b['radius']-0.001) & (radial < outer['radius']+0.005)
        rim = X[mask]
        if len(rim) < 12: fail('Current lip cannot revalidate receiving-bowl geometry', {'samples': len(rim)})
        plane, circle = geo.plane(rim), geo.circle_xy(rim)
        shift = np.array(circle['center_xy_m'])-np.array(outer['xy'])
        if plane['coefficients'][2] < 0.98 or plane['rms_m'] > 0.0015 or circle['rms_m'] > 0.0025 or circle['largest_angular_gap_rad'] > 3.7 or np.linalg.norm(shift) > 0.006 or abs(circle['radius_m']-outer['radius']) > 0.004: fail('Current rim correspondence is ambiguous', {'plane': plane, 'circle': circle, 'shift_m': shift.tolist()})
        center = np.array(b['xy'])+shift; rimz = b['rim_z']+plane['center_world_m'][2]-outer['plane']['center_world_m'][2]
        o = tracked_pose(); fit = None
        if o is not None:
            V = geo.transform(D['vertices'], o['T']); uncertainty = o['uncertainty']; source = 'independent_RGBD_registration'
        else:
            if 'color_basis' not in D: fail('No post-release registration, discriminative appearance reference, or remaining visual review')
            m = (blue(c['rgb']) > D['color_basis']['threshold']) & (np.linalg.norm(X[:, :2]-center, axis=1) < b['radius']+0.005) & (X[:, 2] > b['floor'][2]+0.004) & (X[:, 2] < rimz+0.04)
            Y = X[m]
            if len(Y) < 20: fail('No sufficiently visible carton-color face', {'samples': len(Y)})
            for iteration in range(2):
                fit = geo.plane(Y); n = np.array(fit['coefficients'][:3]); residual = np.abs(Y@n+fit['coefficients'][3]); Y = Y[residual < 0.002]
                if len(Y) < 20: fail('Appearance candidate lacks a coherent measured face')
            fit = geo.plane(Y); n = np.array(fit['coefficients'][:3]); origin = np.array(fit['center_world_m'])
            if fit['rms_m'] > 0.0015 or n[2] < 0.8 or min(fit['in_plane_spread_m']) < 0.004: fail('Appearance candidate is not the supported planar carton face', fit)
            e = np.array([1.0, 0.0, 0.0]); e -= n*float(np.dot(e, n)); e /= np.linalg.norm(e); f = np.cross(n, e); best = None
            for i in range(36):
                angle = i*math.pi/72; a = math.cos(angle)*e+math.sin(angle)*f; d = np.cross(n, a)
                uv = (Y-origin)@np.column_stack([a, d]); lo, hi = uv.min(axis=0), uv.max(axis=0); dims = hi-lo; area = float(np.prod(dims))
                if best is None or area < best[0]: best = (area, a, d, lo, hi, dims)
            area, a, d, lo, hi, dims = best; old = np.array(D['vertices'])[:4]; edges = np.linalg.norm(np.roll(old, -1, axis=0)-old, axis=1)
            expected = np.array([max(edges), min(edges)]) if dims[0] >= dims[1] else np.array([min(edges), max(edges)])
            spacing = math.sqrt(max(area, 1e-8)/len(Y)); deficit = np.maximum(0.0, expected-dims)
            if np.any(dims > expected+2*D['u']) or np.any(deficit > 4*spacing+2*D['u']): fail('Face coverage cannot identify the carton extent', {'measured_dimensions_m': dims.tolist(), 'reference_dimensions_m': expected.tolist(), 'sampling_m': spacing})
            mid = origin+a*(lo[0]+hi[0])/2+d*(lo[1]+hi[1])/2
            top = np.array([mid+a*x*expected[0]/2+d*y*expected[1]/2 for x in [-1, 1] for y in [-1, 1]])
            V = np.vstack([top, top-n*D['height']]); uncertainty = D['u']+float(max(deficit))/2+spacing; source = 'current_color_plane_and_extent_hypothesis'
            record('postrelease_face_extent', {'samples': len(Y), 'dimensions_m': dims.tolist(), 'reference_dimensions_m': expected.tolist(), 'unobserved_extent_m': deficit.tolist(), 'rms_m': fit['rms_m'], 'uncertainty_m': uncertainty})
        top = V[:4]; radius = float(np.max(np.linalg.norm(top[:, :2]-center, axis=1))); p = np.array(geo.pad_position(api.state()))
        contained = radius+b['error']+circle['rms_m'] < b['radius'] and float(np.max(top[:, 2])) < rimz-D['u'] and float(np.min(top[:, 2])) > b['floor'][2]+0.5*D['height']
        separated = float(np.linalg.norm(p-top.mean(axis=0))) > float(np.linalg.norm(api.state()['own_geometry']['pad_extent_in_tool_m']))+D['height']
        result = {'frame_id': c['frame_id'], 'source': source, 'vertices': V.tolist(), 'uncertainty_m': uncertainty, 'radial_extent_m': radius, 'opening_radius_m': b['radius'], 'rim_z_m': rimz, 'source_top_z_m': [float(np.min(top[:, 2])), float(np.max(top[:, 2]))], 'contained': bool(contained), 'separated_from_hand': bool(separated), 'rim_shift_m': shift.tolist()}
        record('current_postrelease_geometry', result); return result
    def finish_without_review():
        p = np.array(geo.pad_position(api.state())); target = p.copy(); target[:2] = D['grasp']['center_xy']
        if np.linalg.norm(target[:2]-p[:2]) > 0.16 or p[2]+D['grasp']['finger_low_relative_pad_z'] <= D['bowl']['rim_z']+0.025: fail('No justified view-changing retreat within the traversed above-rim neighborhood')
        move(target.tolist(), api.state()['tcp_quaternion_xyzw'], 'keep', 'higher reverse-transfer view change after release', True, False)
        first = numeric_result_view(); D['postrelease_numeric'] = first; save('verifying')
        for i in range(3): raw('keep')
        second = numeric_result_view(); A, B = np.array(first['vertices'])[:4], np.array(second['vertices'])[:4]
        motion = max(float(np.min(np.linalg.norm(B-a, axis=1))) for a in A)
        complete = first['contained'] and second['contained'] and first['separated_from_hand'] and second['separated_from_hand'] and motion <= max(0.004, 2*D['u'])
        record('postrelease_assessment', {'first_frame_id': first['frame_id'], 'second_frame_id': second['frame_id'], 'measured_corner_motion_m': motion, 'completion_proposed': bool(complete), 'basis': second['source'], 'limitation': 'Appearance, finite sampling, and fitted extents are uncertain; containment is an assessment, not a certified solid model or native success.'})
        D['final_assessment'] = log[-1]; save('complete' if complete else 'verifying')
        return {'completion_proposed': bool(complete), 'evidence': log, 'limitations': ['No GPT review budget remains. Current calibrated geometry and a separated settling interval were used instead.', 'A one-shot above-rim placement trial was not a collision or fit certificate. Completion remains a proposal.']}
    try:
        manifest = api.recall(); restored = any(m['key'] == 'manipulation' for m in manifest)
        if restored:
            D.update(api.recall('manipulation')['value']); record('resume_historical_checkpoint', {'phase': D['phase'], 'reference_frame_id': D['reference_frame_id']})
            s = api.state()
            if D['phase'] == 'held' and s['frame_id'] == D['anchor']['frame_id']:
                previous = D['anchor_state']
                if np.linalg.norm(np.array(s['tcp_position_world_m'])-np.array(previous['tcp_position_world_m'])) > 1e-6 or abs(float(np.dot(s['tcp_quaternion_xyzw'], previous['tcp_quaternion_xyzw']))) < 0.999999 or s['last_gripper_command'] != 'close' or not D.get('retention_proved', False): fail('Unchanged-frame retention dependencies do not match')
                H['observation'] = D['anchor']; H['registration_uncertainty'] = D['anchor']['uncertainty']; D['q'] = s['tcp_quaternion_xyzw']
                r = D['registration_observation']; v = r['parameters']
                if r['frame_id'] != s['frame_id']: fail('No current identified patch to reinitialize after repair')
                init_track(v['patch_camera'], v['patch_polygon'], D['anchor']['T'])
                basis = D['placement_basis']['parameters']; H['placement_ready'] = True
                H['local_transfer'] = basis['transfer_action'] == 'supported' and basis['external_obstruction'] == 'none_seen'
                record('same_frame_evidence_reuse', {'frame_id': s['frame_id'], 'retention': 'saved independent lift comparison, not a new measurement', 'bowl': 'stationary receiving bowl; only the separated vertical source lift intervened'})
                color_reference()
        else:
            fields = {'interpretation': 'string', 'model': ['rigid_box_on_table_into_open_bowl', 'unsupported', 'unknown'], 'labels': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 4, 'maxItems': 4}, 'camera': cameras, 'corners': {'type': 'array', 'items': pixel, 'minItems': 4, 'maxItems': 4}, 'patch_camera': cameras, 'patch_polygon': polygon}
            fields.update(rim_fields)
            r = review('Interpret the runtime instruction in context. Return interpretation and model. The supported model requires a rigid rectangular source carton resting flat on a visible supporting table and an open approximately circular receiving bowl. Do not guess hidden undersides: confirm the support relation and flat-box model visually, else unknown. Request two named RGB-D regions src_top and supporting_table, each an interior uncontaminated planar patch, with explicit camera, box, stride=4. Return camera and four cyclic visible source top-corner pixels, not depth points on mixed edges. Request named points m0..m3 at four distinctive noncollinear interior printed features on the source top, and give their persistent physical definitions in labels in that order; camera-relative corner names are forbidden. Request b0..b5 distributed on the exposed TOP OUTER lip of the receiving bowl, choosing depth-valid surface locations, and floor on its visible low interior. Distinguish this from the plate. Return inner_camera and inner_pixels with four to eight distributed visible INNER upper-lip boundary pixels in that camera, or inner_pixels=null if this contour cannot be identified. These must be the inner boundary at the same top-lip height as the outer samples, not a decorative ring or points down the sloping interior. The code will intersect their calibrated rays with the measured lip plane instead of sampling mixed boundary depth. Do not invent a hidden arc. Choose patch_camera and patch_polygon for a textured visible patch wholly on the source face, or null if unusable. These observations identify geometry, not a grasp or task success.', fields, {'instruction': task})
            v = r['parameters']
            if v['model'] != 'rigid_box_on_table_into_open_bowl': fail('Unsupported or unobserved source/support model', v['model'])
            top, table = plane_region(r, 'src_top'), plane_region(r, 'supporting_table'); D['u'] = 0.002+2*max(top['rms_m'], table['rms_m'])
            corners = np.array([api.plane_point(v['camera'], px, top['coefficients'])['world_m'] for px in v['corners']]); edges = np.roll(corners, -1, axis=0)-corners; lengths = np.linalg.norm(edges, axis=1)
            if min(lengths) <= 4*D['u'] or abs(float(np.dot(edges[0], edges[1])))/(lengths[0]*lengths[1]) > 0.15 or max(abs(lengths[0]-lengths[2]), abs(lengths[1]-lengths[3])) > 4*D['u']+0.1*min(lengths): fail('Measured rectangle model inconsistent', {'edge_lengths_m': lengths.tolist(), 'corners': corners.tolist()})
            bottom = corners.copy(); coeff = table['coefficients']; bottom[:, 2] = -(bottom[:, 0]*coeff[0]+bottom[:, 1]*coeff[1]+coeff[3])/coeff[2]; heights = corners[:, 2]-bottom[:, 2]
            if min(heights) <= D['u'] or float(np.ptp(heights)) > 4*D['u']: fail('Box height/support inference unresolved', {'heights_m': heights.tolist(), 'uncertainty_m': D['u']})
            ids = ['m'+str(i) for i in range(4) if valid(r, 'm'+str(i))]
            if len(ids) < 3: fail('Need three usable persistent printed landmarks', ids)
            refs = {k: r['points'][k]['world_m'] for k in ids}
            for k in ids:
                if abs(float(np.dot(top['coefficients'][:3], refs[k])+top['coefficients'][3])) > 2*D['u']: fail('Landmark not consistent with source face', k)
            D.update({'task': task, 'phase': 'ready', 'labels': {'m'+str(i): v['labels'][i] for i in range(4)}, 'ids': ids, 'refs': refs, 'reference_frame_id': r['frame_id'], 'vertices': np.vstack([corners, bottom]).tolist(), 'table': table, 'top': top, 'height': float(np.mean(heights)), 'interpretation': v['interpretation']})
            D['bowl'] = bowl_geometry(r); s = api.state(); R = geo.rotation(s['tcp_quaternion_xyzw']); short = edges[int(np.argmin(lengths))]; opening = R[:, 1]
            yaw = (math.atan2(short[1], short[0])-math.atan2(opening[1], opening[0])+math.pi/2)%math.pi-math.pi/2
            D['q'] = api.compose(s['tcp_quaternion_xyzw'], [0.0, 0.0, float(yaw)])
            g = s['own_geometry']; R = geo.rotation(D['q']); lo, hi, offset = np.array(g['finger_low_offset_tool_m']), np.array(g['finger_high_offset_tool_m']), np.array(g['pad_center_in_tool_m'])
            envelope = np.array([[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]]); low = float(np.min(((envelope-offset)@R.T)[:, 2])); half = float(np.dot(np.abs(R[2, :]), np.array(g['pad_extent_in_tool_m']))/2)
            topz, tablez = float(np.mean(corners[:, 2])), float(np.mean(bottom[:, 2])); graspz = max(topz-min(D['height']/2, 0.7*half), tablez-low+D['u']+0.001)
            overlap = min(topz, graspz+half)-max(tablez, graspz-half); span = g['pad_extent_in_tool_m'][1]
            D['grasp'] = {'center_xy': corners.mean(axis=0)[:2].tolist(), 'pad_z': graspz, 'finger_low_relative_pad_z': low, 'pad_half_height_m': half, 'short_width_m': float(min(lengths)), 'combined_pad_open_span_m': span, 'qpos_m': s['gripper_qpos_m'], 'vertical_overlap_m': overlap, 'table_z': tablez, 'top_z': topz}
            record('derived_geometry', {'grasp': D['grasp'], 'bowl': D['bowl'], 'height_m': D['height'], 'uncertainty_m': D['u']})
            if min(lengths)+2*D['u'] >= span or overlap <= 2*D['u']: fail('No feasible grasp under measured geometry', D['grasp'])
            save(); init_track(v['patch_camera'], v['patch_polygon'], np.eye(4))
        q = D['q']
        if D['phase'] in ['ready', 'approach']:
            if restored:
                o = observed(); displacement = float(np.max(np.linalg.norm(np.array(o['points'])-np.array([D['refs'][k] for k in D['ids']]), axis=1)))
                if displacement > 2*o['uncertainty'] or api.state()['last_gripper_command'] == 'close': fail('Pregrasp checkpoint dependencies changed', {'source_motion_m': displacement})
                plan_approach(); q = D['q']
                if not H.get('up_supported', False): fail('No supported upward observation move before revised approach')
                s = api.state(); p = np.array(geo.pad_position(s))
                move((p+np.array([0.0, 0.0, 0.02])).tolist(), s['tcp_quaternion_xyzw'], 'keep', 'one freshly supported upward observation move', inspect=False)
            save('approach'); g = D['grasp']; p = np.array(geo.pad_position(api.state()))
            rim = D.get('approach_obstacle', D['bowl'])
            high = max(float(p[2]), g['top_z']+0.05-g['finger_low_relative_pad_z'], rim['rim_z']+0.025-g['finger_low_relative_pad_z'])
            D['approach_high'] = high; save()
            adjustment = float(np.linalg.norm(np.array(g['center_xy'])-p[:2])); turn = 2*math.acos(min(1.0, abs(float(np.dot(q, api.state()['tcp_quaternion_xyzw'])))))
            local_basis = H.get('above_source_supported', False) and adjustment <= 0.03 and turn <= 0.35 and high+g['finger_low_relative_pad_z'] > rim['rim_z']+D['u']+0.01
            record('above_source_local_basis', {'review_supported': H.get('above_source_supported', False), 'adjustment_m': adjustment, 'turn_rad': turn, 'lowest_finger_z_m': high+g['finger_low_relative_pad_z'], 'rim_z_m': rim['rim_z'], 'fresh_review_required': not local_basis})
            move(g['center_xy']+[high], q, 'open', 'revised above-source translation and alignment', inspect=not local_basis)
            move(g['center_xy']+[g['pad_z']], q, 'open', 'finger approach'); save('closing')
        if D['phase'] == 'closing':
            if api.state()['last_gripper_command'] != 'close':
                for i in range(3): raw('close')
            D['anchor'] = observed(); D['anchor_state'] = api.state(); D['lift_target'] = (np.array(geo.pad_position(D['anchor_state']))+np.array([0.0, 0.0, max(0.04, 7*D['anchor']['uncertainty'])])).tolist(); save('lifting')
        if D['phase'] == 'lifting':
            record('lift_local_basis', {'basis': 'reverse of just-traversed source approach, retaining the closed jaw state', 'target': D['lift_target']})
            move(D['lift_target'], q, 'keep', 'bounded retention-measurement lift; perimeter occlusion is not a failure', inspect= D['lift_target'][2] > D.get('approach_high', 0.0)+0.004)
            o, s = observed(), api.state(); attachment(D['anchor'], D['anchor_state'], o, s, True)
            D['anchor'], D['anchor_state'] = o, s; D['retention_proved'] = True; save('held')
        if D['phase'] == 'held':
            o, s = observed(), api.state(); attachment(D['anchor'], D['anchor_state'], o, s)
            if not H.get('placement_ready', False) or not H.get('local_transfer', False):
                r = review(placement_question, placement_fields, {'instruction': task, 'historical_bowl': D['bowl'], 'retention_proved': D.get('retention_proved', False)})
                if r['parameters']['rim_identity'] != 'same_inner_rim': fail('Receiving bowl identity unresolved')
                D['bowl'] = bowl_geometry(r); H['placement_ready'] = True
                H['local_transfer'] = r['parameters']['transfer_action'] == 'supported' and r['parameters']['external_obstruction'] != 'present'
                D['placement_basis'] = {'frame_id': r['frame_id'], 'parameters': r['parameters']}
            if not H.get('local_transfer', False): fail('Adjacent above-rim transfer lacks local observational support', D.get('placement_basis'))
            D['anchor'], D['anchor_state'] = o, s; save()
            record('bowl_measurement_reuse', {'frame_id': D['bowl']['frame_id'], 'basis': 'current-episode measurement; intervening vertical source motion retraced the separated approach; lateral motion will keep both envelopes above the rim'})
            for stage in range(3):
                p = np.array(geo.pad_position(api.state())); vertices = geo.transform(D['vertices'], D['anchor']['T']); center = vertices[:4].mean(axis=0); bowl = D['bowl']; u = max(D['u'], D['anchor']['uncertainty'])+bowl['error']; radius = float(np.max(np.linalg.norm(vertices[:, :2]-center[:2], axis=1)))
                margin = u+0.0015
                record('fit_evidence_not_a_corridor_precondition', {'stage': stage, 'source_radius_m': radius, 'opening_radius_m': bowl['radius'], 'nominal_clearance_m': bowl['radius']-radius, 'summed_allowance_m': margin, 'robust_clearance_m': bowl['radius']-radius-margin, 'interpretation': 'A negative robust clearance is unresolved fit uncertainty, not an observed obstruction. Rise and above-rim centering can produce current evidence before deciding on a single release trial.'})
                if stage == 2 and radius+D['u']+bowl['error'] >= bowl['radius']: fail('Nominal carton dimensions do not support an above-rim release trial', {'radius_m': radius, 'dimension_allowance_m': D['u'], 'aperture_allowance_m': bowl['error'], 'opening_radius_m': bowl['radius']})
                low = min(float(np.min(vertices[:, 2])-p[2]), D['grasp']['finger_low_relative_pad_z']); target = p.copy()
                if stage == 0: target[2] = max(float(p[2]), bowl['rim_z']+0.025-low); label = 'raise retained item above measured receiving rim'
                if stage == 1: target[:2] += np.array(bowl['xy'])-center[:2]; label = 'bounded adjacent transfer above measured rim'
                if stage == 2:
                    gap = max(0.006+u, float(np.min(vertices[:, 2])-p[2])-D['grasp']['finger_low_relative_pad_z']+u)
                    if gap > 0.025+u: fail('Finger geometry requires excessive release height', {'gap_m': gap})
                    target[:2] += np.array(bowl['xy'])-center[:2]; target[2] += bowl['rim_z']+gap-float(np.min(vertices[:, 2])); label = 'low centered release approach above lip'
                lateral = float(np.linalg.norm(target[:2]-p[:2])); rise = float(target[2]-p[2])
                supported = (stage == 0 and lateral < 0.001 and 0 <= rise <= 0.12) or (stage == 1 and lateral <= 0.16 and min(p[2], target[2])+low > bowl['rim_z']+u) or (stage == 2 and lateral <= 0.01 and target[2]+low > bowl['rim_z']+u)
                record('transfer_local_basis', {'stage': stage, 'supported': bool(supported), 'target_pad_m': target.tolist(), 'lowest_envelope_at_target_m': float(target[2]+low), 'rim_z_m': bowl['rim_z'], 'uncertainty_m': u})
                if not supported: fail('Motion exceeds reviewed local neighborhood or measured rim allowance')
                move(target.tolist(), q, 'keep', label, inspect=False); o, s = observed(), api.state(); attachment(D['anchor'], D['anchor_state'], o, s); D['anchor'], D['anchor_state'] = o, s; save()
            vertices = geo.transform(D['vertices'], D['anchor']['T']); radial = float(np.max(np.linalg.norm(vertices[:, :2]-np.array(D['bowl']['xy']), axis=1))); margin = D['anchor']['uncertainty']+D['bowl']['error']+0.0015
            center_error = float(np.linalg.norm(vertices[:4].mean(axis=0)[:2]-np.array(D['bowl']['xy'])))
            trial = {'frame_id': D['anchor']['frame_id'], 'radial_extent_m': radial, 'nominal_clearance_m': D['bowl']['radius']-radial, 'summed_allowance_m': margin, 'robust_clearance_m': D['bowl']['radius']-radial-margin, 'center_error_m': center_error, 'meaning': 'One bounded release from above the lip; uncertain fit is assessed after release, not certified beforehand.'}
            record('above_rim_release_trial', trial)
            if radial+D['u']+D['bowl']['error'] >= D['bowl']['radius'] or center_error > 0.0015+D['u']: fail('Current centering or nominal extent does not support the release trial', trial)
            if D.get('release_trial') is not None: fail('The one-shot release trial has already been used')
            D['release_trial'] = trial; save('releasing')
            for i in range(3): raw('open'); save('released')
        if D['phase'] not in ['released', 'releasing', 'verifying', 'complete']: fail('Unrecognized or unresolved episode phase', D['phase'])
        if D['phase'] in ['released', 'releasing']:
            p = np.array(geo.pad_position(api.state())); move((p+np.array([0.0, 0.0, 0.06])).tolist(), api.state()['tcp_quaternion_xyzw'], 'keep', 'post-release upward retreat through just-traversed space', True, False); save('verifying')
        if api.state()['budgets']['gpt_remaining'] == 0: return finish_without_review()
        checks = []; observations = []; motion = None; stable = False
        for i in range(2): raw('keep')
        for index in range(2):
            fields = {'identity': ['correct_source_and_bowl', 'unknown'], 'relation': ['contained_in_cavity', 'bridging_rim', 'outside', 'still_held', 'unknown'], 'support': ['settled_supported', 'moving', 'unknown']}
            if index == 0: fields.update({'patch_camera': cameras, 'patch_polygon': polygon})
            else: fields['same_pose'] = ['yes', 'no', 'unknown']
            r = review('Assess the ACTUAL post-release result. identity identifies the correct carton and bowl. relation=contained_in_cavity requires supported inside, not bridging the rim, outside, or still held. support=settled_supported means visible supported rest, otherwise moving or unknown. Request currently identifiable printed landmarks using the saved physical definitions, never stationary projections. On the first observation select patch_camera and patch_polygon wholly on the visible printed carton face for a subsequent independent stability measurement, or null if unusable. On the second, same_pose=yes requires visible agreement with the first post-release observation after the additional physical steps, not agreement with a command.', fields, {'instruction': task, 'definitions': D['labels'], 'previous_postrelease': checks[-1] if checks else None}, True)
            checks.append({'frame_id': r['frame_id'], 'parameters': r['parameters'], 'points': {k: r['points'][k]['world_m'] for k in D['ids'] if valid(r, k)}}); observations.append(r['parameters'])
            if index == 1:
                shared = [k for k in checks[0]['points'] if k in checks[1]['points']]
                if len(shared) >= 2: motion = max(float(np.linalg.norm(np.array(checks[1]['points'][k])-np.array(checks[0]['points'][k]))) for k in shared)
                stable = motion <= max(0.004, 2*D['u']) if motion is not None else r['parameters']['same_pose'] == 'yes'
                break
            handle = None
            if r['parameters']['patch_polygon'] is not None:
                try: handle = api.track_init(r['parameters']['patch_camera'], r['parameters']['patch_polygon'])['handle']
                except Exception as e: record('postrelease_patch_unavailable', str(e))
            D['postrelease_observation'] = checks[-1]; save()
            for i in range(2): raw('keep')
            if handle is not None:
                t = api.track_update(handle)
                if t['status'] == 'tracked' and t['inliers'] >= 12 and t['inliers']/max(1, t['matches']) >= 0.6 and t['rms_m'] <= 0.0025 and t['uncertainty_floor_m'] <= D['u']:
                    a, b = np.array(t['reference_inlier_world_m']), np.array(t['current_inlier_world_m'])
                    spread = np.linalg.svd(a-a.mean(axis=0), compute_uv=False)/math.sqrt(len(a))
                    if len(spread) >= 2 and spread[1] >= 0.003:
                        motion = float(np.max(np.linalg.norm(b-a, axis=1))); stable = motion <= max(0.004, 2*D['u'])
                    record('postrelease_motion_measurement', {'reference_frame_id': t['reference_frame_id'], 'frame_id': t['frame_id'], 'inliers': t['inliers'], 'rms_m': t['rms_m'], 'uncertainty_floor_m': t['uncertainty_floor_m'], 'motion_m': motion})
                else: record('postrelease_registration_unresolved', {'status': t['status'], 'frame_id': t['frame_id']})
            if stable: break
            if api.state()['budgets']['gpt_remaining'] < 1:
                record('stability_gap', 'No adequate post-release registration and no remaining independent visual comparison'); break
        complete = stable and all(v['identity'] == 'correct_source_and_bowl' and v['relation'] == 'contained_in_cavity' and v['support'] == 'settled_supported' for v in observations)
        record('postrelease_assessment', {'observations': checks, 'measured_stability_motion_m': motion, 'stability_basis': 'corresponding_RGBD_points' if motion is not None else 'two_view_review', 'completion_proposed': bool(complete)})
        D['final_assessment'] = log[-1]; save('complete' if complete else 'verifying')
        return {'completion_proposed': bool(complete), 'evidence': log, 'limitations': ['Visual and RGB-D evidence is uncertain; no full collision certificate or hidden success predicate was available.', 'Completion is a proposal, not official native evaluation.']}
    except Exception as e:
        record('incomplete', str(e))
        if 'reference_frame_id' in D: save()
        return {'completion_proposed': False, 'evidence': log, 'phase': D.get('phase', 'initial_measurement'), 'limitation': str(e)}

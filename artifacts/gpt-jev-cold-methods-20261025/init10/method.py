def main(api):
    R = {'phase': 'new'}; history = []; tracker = {'handle': None}
    task = 'Put the cream cheese into the bowl.'
    Q = {}
    for axis in ['x', 'y', 'z', 'rx', 'ry', 'rz']:
        Q[axis] = {'type': 'choice', 'instructions': 'Control world axis ' + axis + '. Read state.processed_features.axes.' + axis + '.goal_relation. Select positive for increase, negative for decrease, and hold for within_tolerance. Do not infer directions from images or another axis.', 'criteria': {'negative': 'This axis requires decrease.', 'hold': 'This axis is within tolerance.', 'positive': 'This axis requires increase.'}}
    Q['gripper'] = {'type': 'choice', 'instructions': 'Read state.processed_features.objective.gripper and select that literal command. Keep means preserve the current grasp, not open.', 'criteria': {'open': 'The objective requests open.', 'close': 'The objective requests close.', 'keep': 'The objective requests keep.'}}
    pixel = {'type': 'array', 'items': {'type': 'integer', 'minimum': 0, 'maximum': 767}, 'minItems': 2, 'maxItems': 2}
    def fail(text):
        raise RuntimeError(text)
    def note(value):
        history.append(value); R['recent'] = history[-10:]; api.note(str(value))
    def save():
        api.checkpoint('carton_bowl_method', R)
    def review(question, fields, context=None, reserve=2):
        if api.state()['budgets']['gpt_remaining'] <= reserve:
            fail('Insufficient review budget; reserved final observations were not spent.')
        ans = api.review(question, context=context, fields=fields)
        if ans['measurement_errors']:
            note({'measurement_errors': ans['measurement_errors'], 'frame_id': ans['frame_id']})
        if ans['status'] == 'stop':
            fail('Observation review stopped: ' + ans['explanation'])
        return ans
    def valid(ans, name, kind='points'):
        return name in ans[kind] and not any(e['name'] == name for e in ans['measurement_errors'])
    def command(target, quaternion, grip, lease=True, contact=False):
        reserve = 3 if R['phase'] in ['released', 'done'] else 14
        available = int(api.state()['budgets']['jev_remaining']) - reserve
        if available < 1 or api.state()['budgets']['native_steps_remaining'] < 3 * (reserve + 1):
            fail('Insufficient physical-action budget; stopping with current gripper state.')
        features = {'phase': R['phase'], 'intent': R.get('intent', ''), 'target_pad_world_m': list(target), 'geometry_uncertainty_m': R.get('u'), 'last_object_observation': R.get('last_obs')}
        if lease:
            out = api.drive(list(target), list(quaternion), grip, Q, features=features, max_calls=min(22, available), tool_point='pad_center', translation_limit=0.006 if contact else 0.02, rotation_limit=0.10, steps=3, position_tolerance=0.003, rotation_tolerance=0.04)
        else:
            out = api.control(list(target), list(quaternion), grip, Q, features=features, tool_point='pad_center', translation_limit=0.006 if contact else 0.02, rotation_limit=0.10, steps=3, position_tolerance=0.003, rotation_tolerance=0.04)
        note({'action_status': out['status'], 'frame_id': out['frame_id'], 'position_error_m': out['position_error_m'], 'rotation_error_rad': out['rotation_error_rad'], 'gripper_choice': out['choices']['gripper']})
        if out['status'] == 'stalled':
            fail('Stalled motion: no further pushing. Intent: ' + R.get('intent', ''))
        if out['choices']['gripper'] != grip:
            fail('Jev delivered an unexpected gripper choice; object state needs reobservation.')
        return out
    def body(obs):
        return geo.transform(np.array(R['vertices']), np.array(obs['T']))
    def registration_review(mode, reserve=2):
        fields = {'identity': ['same_unambiguous', 'ambiguous', 'unknown'], 'patch_camera': ['agentview', 'robot0_eye_in_hand'], 'patch_polygon': {'type': 'array', 'items': pixel, 'minItems': 0, 'maxItems': 16}, 'view': ['up_supported', 'none']}
        question = 'Request current L0,L1,L2 only where their SAME physical printed identities in context are unambiguous. Two identifiable landmarks suffice when combined with a measured top-face normal; do not demand hidden L1. identity=same_unambiguous means every supplied correspondence is unambiguous and top belongs to the same rigid printed carton face; otherwise ambiguous or unknown. Request top as a carton-only INTERIOR top-face cloud, explicit camera, box and stride 4, excluding fingers/background. Choose a CURRENT textured carton-only patch_polygon in patch_camera, empty if unusable. Historical projections are not detections. view=up_supported only if a 0.015 m world-up move with unchanged gripper is locally justified without an observed external obstruction AND would expose useful new texture; otherwise none. '
        if mode == 'resume':
            fields.update({'stationary_bowl_support': ['yes', 'no', 'unknown'], 'object': ['supported_flat', 'held', 'released', 'unknown']})
            question += 'Revalidate the saved bowl/table invariants: stationary_bowl_support=yes only with evidence they remain unchanged; no for observed change, unknown otherwise. object identifies actual supported_flat carton, visibly enclosed held candidate, released separate item, or unknown. '
        if mode == 'approach':
            fields['arrangement'] = ['straddled', 'blocked', 'unknown']
            question += 'Also assess actual OPEN-pad arrangement: straddled requires the carton between opposing pads with side clearance and no displaced carton or trapped neighbor; blocked for an observed conflict, unknown otherwise. A full perimeter is not required. '
        return review(question, fields, {'definitions': R['definitions'], 'reference_observations': R['landmark_observations'], 'phase': R['phase'], 'bowl_xy': R['bowl_xy'], 'rim_z': R['rim_z'], 'table_plane': R['table_plane'], 'plan': R.get('plan')}, reserve=reserve)
    def observe(force_landmarks=False, sample=None):
        if not force_landmarks and sample is None and tracker.get('current', {}).get('frame_id') == api.state()['frame_id']:
            return tracker['current']
        if tracker['handle'] is not None and not force_landmarks:
            try:
                t = api.track_update(tracker['handle'])
                if t['status'] == 'tracked':
                    a = np.array(t['reference_inlier_world_m']); spread = float(np.linalg.svd(a - a.mean(axis=0), compute_uv=False)[1] / math.sqrt(len(a)))
                    base = tracker.get('base', R['initial_obs']); lever = float(np.max(np.linalg.norm(body(base) - np.array(t['reference_patch_centroid_world_m']), axis=1)))
                    u = math.sqrt(base['u'] ** 2 + max(0.001, t['uncertainty_floor_m']) ** 2 + (lever * max(0.0003, t['rms_m']) / max(spread, 0.001)) ** 2)
                    note({'track_frame': t['frame_id'], 'reference_frame': t['reference_frame_id'], 'inliers': t['inliers'], 'matches': t['matches'], 'spread_m': spread, 'rms_m': t['rms_m'], 'derived_uncertainty_m': u, 'uncertainty_model': 'Heuristic RSS: measured anchor, tracking floor, and residual/spread angular extrapolation; not calibrated confidence.'})
                    if t['reference_frame_id'] == tracker['frame'] and t['inliers'] >= 12 and t['inliers'] / max(1, t['matches']) >= 0.6 and t['rms_m'] <= 0.0025 and spread > 0.0025 and u < R['probe_distance'] / 4:
                        T = np.array(t['transform_initial_world_to_current_world']) @ np.array(base['T'])
                        obs = {'T': T.tolist(), 'u': u, 'frame_id': t['frame_id'], 'source': 'patch'}; tracker['current'] = obs; return obs
                else:
                    note({'registration': 'unknown', 'reason': t['reason'], 'frame_id': t['frame_id']})
            except Exception as exc:
                note({'tracker_error': str(exc)})
        for attempt in range(2):
            ans = sample if attempt == 0 and sample is not None else registration_review('recover')
            p = ans['parameters']; ids = [i for i in range(3) if valid(ans, 'L' + str(i))]
            if p['identity'] == 'same_unambiguous' and len(ids) >= 2 and valid(ans, 'top', 'regions'):
                try:
                    fit = geo.plane(np.array(ans['regions']['top']['world_m'])); a = np.array([R['landmarks'][i] for i in ids]); b = np.array([ans['points']['L' + str(i)]['world_m'] for i in ids])
                    n0 = np.array(R['top_plane'][:3]); n1 = np.array(fit['coefficients'][:3]); spread = min(fit['in_plane_spread_m'])
                    pairs = [(i, j) for i in range(len(ids)) for j in range(i + 1, len(ids))]; pair = max(pairs, key=lambda ij: float(np.linalg.norm(a[ij[1]] - a[ij[0]])))
                    i, j = pair; d0 = a[j] - a[i]; d1 = b[j] - b[i]; d0 -= n0 * np.dot(n0, d0); d1 -= n1 * np.dot(n1, d1)
                    length = min(float(np.linalg.norm(d0)), float(np.linalg.norm(d1)))
                    if length <= 0.012 or spread <= 0.003 or fit['rms_m'] > 0.0025 or n1[2] < 0.94:
                        fail('Inadequate corresponding top geometry: ' + str({'baseline_m': length, 'fit': fit}))
                    d0 /= np.linalg.norm(d0); d1 /= np.linalg.norm(d1)
                    rot = np.column_stack([d1, np.cross(n1, d1), n1]) @ np.column_stack([d0, np.cross(n0, d0), n0]).T
                    T = np.eye(4); T[:3, :3] = rot; T[:3, 3] = b.mean(axis=0) - rot @ a.mean(axis=0)
                    residual = float(np.max(np.linalg.norm(geo.transform(a, T) - b, axis=1))); plane_error = float(np.max(np.abs(b @ n1 + fit['coefficients'][3])))
                    u = math.sqrt(max(0.0015, residual, plane_error) ** 2 + (R['radius'] * 0.002 / length) ** 2 + (R['radius'] * 2 * fit['rms_m'] / spread) ** 2)
                    note({'correspondence_ids': ids, 'baseline_m': length, 'landmark_residual_m': residual, 'plane_error_m': plane_error, 'derived_uncertainty_m': u, 'frame_id': ans['frame_id']})
                    if residual <= 0.003 and plane_error <= 0.003 and u < R['probe_distance'] / 4:
                        obs = {'T': T.tolist(), 'u': u, 'frame_id': ans['frame_id'], 'source': 'independent_landmarks_and_plane'}
                        R['registration_reference'] = {'observation': obs, 'definitions': R['definitions'], 'points': {('L' + str(i)): ans['points']['L' + str(i)] for i in ids}, 'plane_fit': fit, 'patch_camera': p['patch_camera'], 'patch_polygon': p['patch_polygon']}; save()
                        tracker['handle'] = None; tracker['current'] = obs
                        if len(p['patch_polygon']) >= 3:
                            try:
                                t = api.track_init(p['patch_camera'], p['patch_polygon']); tracker.update({'handle': t['handle'], 'frame': t['frame_id'], 'base': obs}); note({'current_patch_frame': t['frame_id'], 'reference_features': t['reference_features']})
                            except Exception as exc:
                                note({'patch_initialization_failed': str(exc)})
                        return obs
                except Exception as exc:
                    note({'correspondence_rejected': str(exc)})
            if attempt == 0 and p['view'] == 'up_supported':
                s = api.state(); R['intent'] = 'One justified correspondence-producing view change'; save(); command((np.array(geo.pad_position(s)) + [0, 0, 0.015]).tolist(), s['tcp_quaternion_xyzw'], 'keep')
            else:
                break
        fail('Unknown registration: insufficient identifiable corresponding landmarks with a measured top normal, and no reliable anchored patch. No attachment or transform was assumed.')
    def check_hold(probe=False):
        old = R['last_obs']; before = R['last_state']
        for attempt in range(2):
            obs = observe(force_landmarks=(attempt == 1)); after = api.state()
            p0 = body(old); p1 = body(obs); err = float(geo.attachment_error(p0, p1, before, after))
            hand = np.array(geo.pad_position(after)) - np.array(geo.pad_position(before)); obj = p1.mean(axis=0) - p0.mean(axis=0)
            tolerance = 0.003 + old['u'] + obs['u']; enough = not probe or (hand[2] >= max(0.025, 3 * (old['u'] + obs['u'])) and obj[2] >= max(0.012, 0.6 * hand[2]))
            note({'retention_test': probe, 'attachment_error_m': err, 'tolerance_m': tolerance, 'actual_hand_delta_m': hand.tolist(), 'observed_object_delta_m': obj.tolist(), 'source': obs['source']})
            if err <= tolerance and enough:
                R['last_obs'] = obs; R['last_state'] = after; save(); return obs
            if obs['source'] != 'patch':
                break
        fail('Measured object motion did not establish retention. The gripper will not be reopened during an uncertain transfer.')
    def move(target, quaternion, grip, held=False, contact=False):
        target = np.array(target); quaternion = list(quaternion); views = 0; scope = None
        start = np.array(geo.pad_position(api.state()))
        if np.linalg.norm(target - start) > 0.6:
            fail('Proposed route exceeds the bounded local workspace.')
        if held and R.get('route_scope'):
            candidate_scope = R['route_scope'].pop(0)
            if candidate_scope['permission'] in ['supported', 'self_occluded_supported'] and np.linalg.norm(target - np.array(candidate_scope['target'])) <= 0.006 and np.linalg.norm(start - np.array(candidate_scope['start'])) <= 0.006:
                scope = candidate_scope
        for leg_index in range(52):
            s = api.state(); p = np.array(geo.pad_position(s)); d = target - p; distance = float(np.linalg.norm(d))
            angle = 2 * math.acos(min(1.0, abs(float(np.dot(quaternion, s['tcp_quaternion_xyzw'])))))
            if distance <= 0.003 and angle <= 0.04:
                return
            leg_limit = 0.025 if contact else 0.16; candidate = p + d * min(1.0, leg_limit / max(distance, 0.00001)); qleg = quaternion
            if scope is None:
                ans = review('Assess only this next bounded leg. external=observed means a conflicting external obstacle; none_observed is absence of an observed obstacle, NOT certified clearance; unknown means unresolved external evidence. visibility distinguishes observed, partial unobserved space, and robot/payload self_occluded. local=candidate_supported justifies the displayed leg using local geometry; short_supported justifies only its first 0.025 m; unknown neither. For descent assess open-pad side clearance using the measured plan. Do not require complete corridor or object-perimeter visibility. view=up_supported only if an independently justified 0.025 m upward move would resolve the view gap.', {'external': ['observed', 'none_observed', 'unknown'], 'visibility': ['observed', 'partial', 'self_occluded'], 'local': ['candidate_supported', 'short_supported', 'unknown'], 'view': ['up_supported', 'none']}, {'phase': R['phase'], 'intent': R.get('intent'), 'current_pad_world_m': p.tolist(), 'candidate_pad_world_m': candidate.tolist(), 'goal_quaternion_xyzw': quaternion, 'held': held, 'contact_approach': contact, 'plan': R.get('plan'), 'last_object_observation': R.get('last_obs')}, reserve=1 if R['phase'] == 'released' else 3)
                a = ans['parameters']
                if a['external'] != 'none_observed' or a['local'] == 'unknown':
                    if a['view'] != 'up_supported' or views >= 1:
                        fail('No justified next local action: ' + str(a))
                    views += 1; candidate = p + [0, 0, 0.025]; qleg = s['tcp_quaternion_xyzw']
                elif a['local'] == 'short_supported':
                    candidate = p + d * min(1.0, 0.025 / max(distance, 0.00001))
            R['pending_target_pad'] = candidate.tolist(); save(); out = command(candidate.tolist(), qleg, grip, contact=contact)
            if held:
                check_hold()
            if scope is not None and (leg_index >= 2 or angle > 0.04):
                fail('Scoped transfer did not converge within its bounded feedback allowance.')
        fail('Bounded route trials exhausted before convergence.')
    def finger_bottom(state, quaternion):
        own = state['own_geometry']; lo = own['finger_low_offset_tool_m']; hi = own['finger_high_offset_tool_m']; offset = np.array(own['pad_center_in_tool_m'])
        corners = np.array([[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]])
        return float(np.min(((corners - offset) @ geo.rotation(quaternion).T)[:, 2]))
    def acquire():
        fields = {'shape': ['supported_flat_rectangular_carton', 'unknown'], 'rim_identity': ['inner_horizontal_opening', 'unknown'], 'corner_camera': ['agentview', 'robot0_eye_in_hand'], 'corners': {'type': 'array', 'items': pixel, 'minItems': 4, 'maxItems': 4}, 'definitions': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 3, 'maxItems': 3}, 'patch_camera': ['agentview', 'robot0_eye_in_hand'], 'patch_polygon': {'type': 'array', 'items': pixel, 'minItems': 0, 'maxItems': 16}}
        question = 'Goal: ' + task + ' Identify the cream-cheese carton and bowl, not the plate. shape requires visible top/side evidence of a flat rectangular carton resting on the measured tabletop. Request named regions top and table, each an explicit camera, interior box and stride 4 cloud; top must exclude its boundary/background and table must be adjacent supporting tabletop. Return four clockwise genuinely visible top-face corner pixels in corner_camera; these will be intersected with the measured top plane, not treated as raw boundary depth. Request L0,L1,L2 as three well-spaced noncollinear, identifiable printed INTERIOR texture landmarks on this carton top. definitions must specify their persistent physical printed identities, not screen-relative corners. Request side as a visible carton side-face point. Request r0 through r5 spaced around the bowl INNER lip and floor on the visible interior bottom near its center. rim_identity must distinguish the inner aperture from the outer silhouette. Choose a textured carton-only interior patch_polygon and its own patch_camera, preferably the most detailed view; use an empty polygon if unusable. Do not supply geometry numbers by visual estimation.'
        ans = review(question, fields, {'instruction': task})
        p = ans['parameters']; required = ['L0', 'L1', 'L2', 'side', 'floor'] + ['r' + str(i) for i in range(6)]
        missing = [n for n in required if not valid(ans, n)] + [n for n in ['top', 'table'] if not valid(ans, n, 'regions')]
        if missing:
            replacement = review('Replace only failed named measurements listed in context using the original definitions. Use depth-valid interior samples; do not change landmark physical identities or select an outer bowl boundary. Request the missing points/regions explicitly. No new parameters are requested.', {}, {'missing': missing, 'original_question': question, 'definitions_and_pixels': p, 'errors': ans['measurement_errors']})
            for kind in ['points', 'regions']:
                ans[kind].update(replacement[kind])
            ans['measurement_errors'] = [e for e in ans['measurement_errors'] if not valid(replacement, e['name'], 'regions' if e['name'] in ['top', 'table'] else 'points')]
        if p['shape'] != 'supported_flat_rectangular_carton' or p['rim_identity'] != 'inner_horizontal_opening' or not all(valid(ans, n) for n in required) or not all(valid(ans, n, 'regions') for n in ['top', 'table']):
            fail('Required initial shape, support, aperture, or depth measurements are unavailable: ' + str(ans['measurement_errors']))
        fits = {}
        for name in ['top', 'table']:
            cloud = np.array(ans['regions'][name]['world_m'])
            if len(cloud) < 8:
                fail('Insufficient interior cloud: ' + name)
            fits[name] = geo.plane(cloud)
            if fits[name]['rms_m'] > 0.0025 or min(fits[name]['in_plane_spread_m']) <= 0.003 or fits[name]['coefficients'][2] < 0.98:
                fail('Invalid near-horizontal surface fit: ' + str(fits[name]))
        top = np.array(fits['top']['coefficients']); table = np.array(fits['table']['coefficients'])
        corners = np.array([api.plane_point(p['corner_camera'], px, top.tolist())['world_m'] for px in p['corners']])
        rim = np.array([ans['points']['r' + str(i)]['world_m'] for i in range(6)]); plane = geo.plane(rim); circle = geo.circle_xy(rim)
        u = max(0.0015, 2 * fits['top']['rms_m'], 2 * fits['table']['rms_m'], 2 * plane['rms_m'], circle['max_radial_error_m'])
        note({'top_fit': fits['top'], 'support_fit': fits['table'], 'rim_fit': plane, 'aperture_fit': circle, 'geometry_uncertainty_m': u})
        if plane['coefficients'][2] < 0.98 or circle['largest_angular_gap_rad'] >= math.pi or circle['max_radial_error_m'] > 0.07 * circle['radius_m'] or plane['rms_m'] > 0.003:
            fail('Inner-opening fit is not adequate; see numerical fit evidence.')
        e0 = corners[1] - corners[0]; e1 = corners[2] - corners[1]; l0 = float(np.linalg.norm(e0)); l1 = float(np.linalg.norm(e1))
        if min(l0, l1) <= 4 * u or abs(float(np.dot(e0, e1))) > 0.12 * l0 * l1 or np.linalg.norm(corners[3] - corners[0] - e1) > 3 * u:
            fail('Footprint does not support a rectangular carton model: ' + str({'edges_m': [l0, l1], 'u_m': u}))
        bottom = corners.copy(); bottom[:, 2] = -(bottom[:, :2] @ table[:2] + table[3]) / table[2]; height = float(np.mean(corners[:, 2] - bottom[:, 2]))
        landmarks = np.array([ans['points']['L' + str(i)]['world_m'] for i in range(3)]); side = np.array(ans['points']['side']['world_m']); floor = np.array(ans['points']['floor']['world_m'])
        center = circle['center_xy_m']; pc = plane['coefficients']; rim_z = -(pc[0] * center[0] + pc[1] * center[1] + pc[3]) / pc[2]
        if height <= 2 * u or np.max(np.abs(landmarks @ top[:3] + top[3])) > 2 * u or not (float(np.min(bottom[:, 2])) - u <= side[2] <= float(np.max(corners[:, 2])) + u) or np.linalg.norm(floor[:2] - center) > 0.5 * circle['radius_m'] or floor[2] >= rim_z - u:
            fail('Top/side/support or visible bowl-interior measurements disagree: ' + str({'height_m': height, 'u_m': u, 'floor_m': floor.tolist(), 'rim_z_m': rim_z}))
        radius = float(np.max(np.linalg.norm(corners[:, :2] - corners[:, :2].mean(axis=0), axis=1)))
        if radius + 2 * u + 0.002 >= circle['radius_m']:
            fail('Measured horizontal carton footprint does not have sufficient aperture margin: ' + str({'carton_radius_m': radius, 'aperture_radius_m': circle['radius_m'], 'u_m': u}))
        R.update({'phase': 'ready', 'reference_frame': ans['frame_id'], 'definitions': p['definitions'], 'landmark_observations': [ans['points']['L' + str(i)] for i in range(3)], 'landmarks': landmarks.tolist(), 'vertices': np.concatenate([corners, bottom]).tolist(), 'table_plane': table.tolist(), 'top_plane': top.tolist(), 'bowl_xy': center, 'rim_z': float(rim_z), 'bowl_radius': float(circle['radius_m']), 'floor_world_m': floor.tolist(), 'height': height, 'radius': radius, 'u': float(u), 'probe_distance': 0.05, 'model_limit': 'Bottom footprint is derived from observed flat support and carton side/top evidence, not a measured hidden underside.'})
        R['initial_obs'] = {'T': np.eye(4).tolist(), 'u': float(u), 'frame_id': ans['frame_id'], 'source': 'initial_RGBD'}; save()
        if len(p['patch_polygon']) >= 3:
            try:
                t = api.track_init(p['patch_camera'], p['patch_polygon']); tracker.update({'handle': t['handle'], 'frame': t['frame_id']}); note({'patch_reference_frame': t['frame_id'], 'reference_features': t['reference_features']})
            except Exception as exc:
                note({'patch_initialization_failed': str(exc), 'fallback': 'Semantic landmark measurements'})
    def finish_measured_release():
        s0 = api.state(); saved = R['last_obs']; compact = R.get('compact_reference', {})
        if s0['frame_id'] != 357 or saved['frame_id'] != 357 or R['last_state']['frame_id'] != 357:
            fail('Frame-357 image selections are not current; fresh identifiable image selections are required.')
        if s0['last_gripper_command'] != 'close' or np.linalg.norm(np.array(s0['tcp_position_world_m']) - np.array(R['last_state']['tcp_position_world_m'])) > 0.001:
            fail('Saved held-state dependencies do not match current proprioception.')
        permission = compact.get('permissions', {})
        if permission.get('external') != 'none_observed' or permission.get('descent') != 'supported' or permission.get('retreat') != 'supported' or not compact.get('prior_retention'):
            fail('Missing historical retention or applicable local centering/retreat evidence.')
        if s0['budgets']['jev_remaining'] < 35 or s0['budgets']['native_steps_remaining'] < 105:
            fail('Insufficient reserved budget for centering, release, retreat, and measured settling.')
        camera = 'robot0_eye_in_hand'; corners = [[276, 450], [489, 444]]
        cloud = api.cloud(camera, [296, 466, 473, 630], stride=4)
        if cloud['frame_id'] != 357 or len(cloud['world_m']) < 24:
            fail('Current selected printed-face interior lacks sufficient depth.')
        fit = geo.plane(np.array(cloud['world_m'])); normal = np.array(fit['coefficients'][:3]); spread = min(fit['in_plane_spread_m'])
        if fit['rms_m'] > 0.0015 or spread < 0.004 or normal[2] < 0.98:
            fail('Current selected carton face is not an adequate planar measurement: ' + str(fit))
        cc = np.array([api.plane_point(camera, px, fit['coefficients'])['world_m'] for px in corners]); step = 0.0
        for px, point in zip(corners, cc):
            for axis in range(2):
                near = list(px); near[axis] += 1
                step = max(step, float(np.linalg.norm(np.array(api.plane_point(camera, near, fit['coefficients'])['world_m']) - point)))
        ref = np.array(R['vertices']); dimensions = sorted([float(np.linalg.norm(ref[1] - ref[0])), float(np.linalg.norm(ref[2] - ref[1]))])
        edge = cc[1] - cc[0]; length = float(np.linalg.norm(edge)); boundary_u = 3 * step; plane_u = max(R['u'], 2 * fit['rms_m'])
        if length <= 0.01 or abs(length - dimensions[0]) > 2 * (plane_u + boundary_u + R['u']):
            fail('Current visible short edge disagrees with measured dimensions: ' + str({'length_m': length, 'reference_m': dimensions, 'boundary_u_m': boundary_u}))
        inward = np.cross(normal, edge / length); inward /= np.linalg.norm(inward)
        side = float(np.dot(np.array(fit['center_world_m']) - cc.mean(axis=0), inward))
        if abs(side) <= max(plane_u, 2 * boundary_u):
            fail('Current interior samples do not resolve the physical side of the visible edge.')
        inward *= 1 if side > 0 else -1
        cc = np.array([cc[0], cc[1], cc[1] + inward * dimensions[1], cc[0] + inward * dimensions[1]])
        v0 = np.concatenate([cc, cc - normal * R['height']])
        u0 = math.sqrt(plane_u ** 2 + boundary_u ** 2 + R['u'] ** 2 + (2 * boundary_u * dimensions[1] / length) ** 2 + (R['radius'] * 2 * fit['rms_m'] / spread) ** 2)
        discrepancy = float(np.linalg.norm(v0.mean(axis=0) - body(saved).mean(axis=0)))
        note({'fresh_edge_frame': 357, 'edge_m': length, 'reference_dimensions_m': dimensions, 'plane': fit, 'boundary_u_m': boundary_u, 'footprint_u_m': u0, 'saved_centroid_discrepancy_m': discrepancy, 'selection_source': 'Supplied current image: visible far short edge and printed interior; three-pixel boundary allowance.'})
        if discrepancy > u0 + saved['u']:
            fail('Independent current geometry disagrees with the acknowledged tracked carton location.')
        rim_refs = [([389, 375], [-0.0301459, 0.00963289, 0.949843]), ([170, 591], [-0.0852564, 0.0602633, 0.950236]), ([612, 590], [-0.0801787, -0.0476957, 0.948959])]
        rim_checks = []
        for px, world in rim_refs:
            try:
                measured = api.point(camera, px, radius=1); error = float(np.linalg.norm(np.array(measured['world_m']) - np.array(world)))
                rim_checks.append({'reference_frame': 336, 'current': measured, 'reference_world_m': world, 'discrepancy_m': error})
            except Exception as exc:
                note({'rim_sample_error': str(exc), 'pixel': px})
        good = [entry for entry in rim_checks if entry['discrepancy_m'] <= 2 * R['u']]
        note({'bowl_stationarity_samples': rim_checks, 'interpretation': 'Current visible rim selections compared with historical surface measurements, not projected points treated as detections.'})
        if len(good) < 2 or max(float(np.linalg.norm(np.array(a['reference_world_m']) - np.array(b['reference_world_m']))) for a in good for b in good) < R['bowl_radius']:
            fail('Current visible rim samples do not support reuse of the saved stationary opening.')
        bowl_u = max(R['u'], max(entry['discrepancy_m'] for entry in good))
        handles = []
        for cam, polygon in [(camera, [[295, 465], [474, 460], [474, 629], [295, 629]]), ('agentview', [[379, 406], [407, 406], [408, 443], [379, 443]])]:
            try:
                init = api.track_init(cam, polygon); handles.append({'handle': init['handle'], 'frame': init['frame_id']})
                note({'new_patch_camera': cam, 'reference_frame': init['frame_id'], 'reference_features': init['reference_features']})
            except Exception as exc:
                note({'patch_init_error': str(exc), 'camera': cam})
        if not handles:
            fail('No usable current printed-face reference patch and no review budget for new correspondence selections.')
        R['repair_release_reference'] = {'frame_id': 357, 'vertices': v0.tolist(), 'u_m': u0, 'plane': fit, 'corners': corners, 'camera': camera, 'definitions': R['definitions'], 'global_anchor': saved, 'selection_source': 'User-supplied current images; invalid after this frame unless independently registered.'}; save()
        def locate():
            for item in handles:
                try:
                    t = api.track_update(item['handle'])
                    if t['status'] != 'tracked':
                        note({'registration': 'unknown', 'frame_id': t['frame_id'], 'reason': t['reason']}); continue
                    points = np.array(t['reference_inlier_world_m']); sp = float(np.linalg.svd(points - points.mean(axis=0), compute_uv=False)[1] / math.sqrt(len(points)))
                    lever = float(np.max(np.linalg.norm(v0 - np.array(t['reference_patch_centroid_world_m']), axis=1)))
                    u = math.sqrt(u0 ** 2 + max(0.001, t['uncertainty_floor_m']) ** 2 + (lever * max(0.0001, t['rms_m']) / max(sp, 0.001)) ** 2)
                    note({'registration_frame': t['frame_id'], 'inliers': t['inliers'], 'matches': t['matches'], 'rms_m': t['rms_m'], 'spread_m': sp, 'footprint_u_m': u})
                    if t['frame_id'] == api.state()['frame_id'] and t['reference_frame_id'] == item['frame'] and t['inliers'] >= 12 and t['inliers'] / max(1, t['matches']) >= 0.65 and t['rms_m'] <= 0.002 and sp > 0.0025:
                        delta = np.array(t['transform_initial_world_to_current_world'])
                        return {'vertices': geo.transform(v0, delta), 'u': u, 'frame': t['frame_id'], 'source': 'fresh_edge_and_independent_RGBD_registration'}
                except Exception as exc:
                    note({'registration_error': str(exc)})
            if api.state()['budgets']['gpt_remaining'] > 2:
                ans = registration_review('recover', reserve=0); obs = observe(force_landmarks=True, sample=ans)
                delta = np.array(obs['T']) @ np.linalg.inv(np.array(saved['T']))
                return {'vertices': geo.transform(v0, delta), 'u': math.sqrt(u0 ** 2 + saved['u'] ** 2 + obs['u'] ** 2), 'frame': obs['frame_id'], 'source': 'independently_identified_semantic_landmarks'}
            return None
        def snapshot(observation):
            v = observation['vertices'][:4]; center = v.mean(axis=0); cal = api.camera('agentview')
            cam = geo.transform(center + 0.7 * (v - center), np.linalg.inv(np.array(cal['camera_to_world_opencv'])))
            if np.min(cam[:, 2]) <= 0:
                return None
            homogeneous = cam @ np.array(cal['K']).T; pixels = homogeneous[:, :2] / homogeneous[:, 2:3]
            box = [max(0, int(math.floor(np.min(pixels[:, 0])))), max(0, int(math.floor(np.min(pixels[:, 1])))), min(767, int(math.ceil(np.max(pixels[:, 0])))), min(767, int(math.ceil(np.max(pixels[:, 1]))))]
            if box[2] - box[0] < 8 or box[3] - box[1] < 8:
                return None
            c = api.cloud('agentview', box, stride=4); w = np.array(c['world_m'])
            if len(w) < 12:
                return None
            plane = geo.plane(v); d = w - v[0]; e = v[1] - v[0]; f = v[3] - v[0]
            x = d @ e / np.dot(e, e); y = d @ f / np.dot(f, f)
            ids = np.where((x > 0.1) & (x < 0.9) & (y > 0.1) & (y < 0.9) & (np.abs(w @ np.array(plane['coefficients'][:3]) + plane['coefficients'][3]) < max(0.0025, observation['u'])))[0]
            if len(ids) < 12:
                return None
            rgb = np.array(c['rgb'], dtype=float)[ids]; scale = 255.0 if np.max(rgb) > 1.0 else 1.0
            if float(np.mean(np.std(rgb / scale, axis=0))) <= 0.02 or min(geo.plane(w[ids])['in_plane_spread_m']) < 0.002:
                return None
            return {'world': w[ids], 'rgb': rgb, 'pixels': np.array(c['pixels'])[ids].tolist(), 'box': box, 'scale': scale, 'frame': c['frame_id'], 'cal': cal['camera_to_world_opencv']}
        def unchanged(snap):
            if snap is None:
                return False, {'gap': 'No sufficiently textured, depth-valid current carton patch in the fixed view.'}
            c = api.cloud('agentview', snap['box'], stride=4); lookup = {tuple(px): i for i, px in enumerate(c['pixels'])}
            pairs = [(i, lookup[tuple(px)]) for i, px in enumerate(snap['pixels']) if tuple(px) in lookup]
            if len(pairs) < 12 or len(pairs) < 0.85 * len(snap['pixels']):
                return False, {'gap': 'Too few matching fixed-view depth samples.', 'samples': len(pairs)}
            i = [p[0] for p in pairs]; j = [p[1] for p in pairs]
            depth = float(np.quantile(np.linalg.norm(np.array(c['world_m'])[j] - snap['world'][i], axis=1), 0.95))
            color = float(np.quantile(np.max(np.abs(np.array(c['rgb'], dtype=float)[j] - snap['rgb'][i]), axis=1) / snap['scale'], 0.95))
            camera_error = float(np.max(np.abs(np.array(api.camera('agentview')['camera_to_world_opencv']) - np.array(snap['cal']))))
            evidence = {'frames': [snap['frame'], c['frame_id']], 'samples': len(pairs), 'depth_change_95_m': depth, 'color_change_95_fraction': color, 'camera_change': camera_error}
            return bool(c['frame_id'] > snap['frame'] and depth <= 2 * R['u'] + 0.001 and color <= 0.04 and camera_error < 0.000001), evidence
        pad = np.array(geo.pad_position(s0)); q = s0['tcp_quaternion_xyzw']; target = pad.copy(); target[:2] += np.array(R['bowl_xy']) - cc[:, :2].mean(axis=0)
        if np.linalg.norm(target - pad) > 0.006:
            fail('Current centering correction is outside the previously reviewed local envelope.')
        current = {'vertices': v0, 'u': u0, 'frame': 357, 'source': 'current_edge_plane_and_measured_dimensions'}
        if np.linalg.norm(target - pad) > 0.0006:
            R['intent'] = 'One measured in-plane centering correction above the bowl; preserve grasp and orientation'; R['pending_target_pad'] = target.tolist(); save()
            out = api.drive(target.tolist(), q, 'keep', Q, features={'phase': 'held', 'intent': R['intent'], 'correction_world_m': (target - pad).tolist(), 'geometry_uncertainty_m': u0}, max_calls=8, tool_point='pad_center', translation_limit=0.003, rotation_limit=0.10, steps=3, position_tolerance=0.0008, rotation_tolerance=0.04)
            note({'centering_status': out['status'], 'position_error_m': out['position_error_m'], 'rotation_error_rad': out['rotation_error_rad'], 'frame_id': out['frame_id']})
            if out['status'] == 'stalled' or out['choices']['gripper'] != 'keep' or out['position_error_m'] > 0.0013 or out['rotation_error_rad'] > 0.04:
                fail('Bounded centering failed; no repeated contact pushing or opening.')
            current = locate()
            if current is None:
                fail('Centering registration is unknown; no review budget for new identifiable correspondences. Preserving grasp.')
            err = float(geo.attachment_error(v0, current['vertices'], s0, api.state()))
            note({'centering_attachment_error_m': err, 'tolerance_m': 0.003 + u0 + current['u'], 'hand_delta_m': (np.array(geo.pad_position(api.state())) - pad).tolist(), 'object_delta_m': (current['vertices'].mean(axis=0) - v0.mean(axis=0)).tolist(), 'interpretation': 'Consistency with earlier measured retention, not a new lift test.'})
            if err > 0.003 + u0 + current['u']:
                fail('Observed object and hand motion disagree after centering.')
        v = current['vertices']; now = api.state(); available = R['bowl_radius'] - float(np.max(np.linalg.norm(v[:, :2] - np.array(R['bowl_xy']), axis=1)))
        needed = bowl_u + current['u'] + 0.001; low_z = float(np.min(v[:, 2])); finger_z = float(geo.pad_position(now)[2] + finger_bottom(now, q))
        note({'release_aperture_margin_m': available, 'required_margin_m': needed, 'object_low_z_m': low_z, 'finger_low_z_m': finger_z, 'rim_z_m': R['rim_z'], 'bowl_u_m': bowl_u, 'object_u_m': current['u']})
        if available <= needed or min(low_z, finger_z) <= R['rim_z'] + bowl_u + current['u'] or low_z - R['rim_z'] > 0.5 * R['bowl_radius']:
            fail('Fresh measured release margin remains inadequate; preserving the grasp.')
        R['release_footprint'] = {'frame_id': now['frame_id'], 'vertices': v.tolist(), 'u_m': current['u'], 'source': current['source']}; R['phase'] = 'releasing'; R['intent'] = 'Release from independently measured above-opening placement'; save()
        for opening in range(3):
            s = api.state(); command(np.array(geo.pad_position(s)).tolist(), q, 'open', lease=False)
        R['phase'] = 'released'; save(); effect = locate(); pre_view = snapshot(effect) if effect is not None else None
        note({'post_open_registered': effect is not None, 'interpretation': 'Contact-transition observation; stable release still unproven.'})
        before_retreat = api.state(); retreat_target = np.array(geo.pad_position(before_retreat)) + [0, 0, 0.06]
        R['intent'] = 'Previously reviewed upward open-hand observation retreat'; save(); out = command(retreat_target.tolist(), q, 'open')
        if out['position_error_m'] > 0.0035 or out['rotation_error_rad'] > 0.04:
            fail('Open-hand retreat did not converge; current separation requires new evidence.')
        final = locate()
        if final is None and effect is not None:
            still, detail = unchanged(pre_view); note({'registration_recovery_fixed_view': detail, 'unchanged': still})
            if still:
                final = {'vertices': effect['vertices'], 'u': effect['u'] + detail['depth_change_95_m'], 'frame': api.state()['frame_id'], 'source': 'post_open_registration_revalidated_by_current_fixed_view_RGBD'}
        if final is None:
            fail('Registration remains unknown after a justified new-view retreat; zero review budget prevents new identifiable landmark selection.')
        stable = False; stability = {}
        for trial in range(2):
            snap = snapshot(final)
            if snap is None:
                fail('Released-object identity was registered, but no current textured external patch supports an independent stability measurement.')
            for settling in range(3):
                s = api.state(); command(np.array(geo.pad_position(s)).tolist(), q, 'open', lease=False)
            stable, stability = unchanged(snap); note({'stability': stability, 'stable': stable})
            if stable:
                final['frame'] = api.state()['frame_id']; break
            final = locate()
            if final is None:
                fail('Object patch changed during settling and current registration is unknown; containment cannot be refreshed.')
        if not stable:
            fail('Released carton did not establish short-episode stability within bounded observations.')
        v = final['vertices']; s = api.state(); uncertainty = final['u'] + stability['depth_change_95_m']
        radial_margin = R['bowl_radius'] - float(np.max(np.linalg.norm(v[:, :2] - np.array(R['bowl_xy']), axis=1)))
        bottom_high = float(np.max(v[4:, 2])); bottom_low = float(np.min(v[4:, 2])); separation = float(geo.pad_position(s)[2] + finger_bottom(s, s['tcp_quaternion_xyzw']) - np.max(v[:, 2]))
        drop = float(current['vertices'].mean(axis=0)[2] - v.mean(axis=0)[2]); retreat = float(geo.pad_position(s)[2] - geo.pad_position(before_retreat)[2])
        inside = radial_margin > bowl_u + uncertainty and bottom_high < R['rim_z'] - bowl_u - uncertainty and bottom_low >= R['floor_world_m'][2] - bowl_u - uncertainty
        detached = separation > uncertainty + 0.003 and retreat > 0.04 and drop > max(0.006, current['u'] + uncertainty)
        evidence = {'frame_id': s['frame_id'], 'source': final['source'], 'radial_margin_m': radial_margin, 'required_radial_margin_m': bowl_u + uncertainty, 'bottom_z_range_m': [bottom_low, bottom_high], 'rim_z_m': R['rim_z'], 'interior_floor_z_m': R['floor_world_m'][2], 'finger_object_separation_m': separation, 'observed_object_drop_m': drop, 'actual_hand_retreat_m': retreat, 'uncertainty_m': uncertainty, 'containment_observed': bool(inside), 'detachment_observed': bool(detached), 'stability': stability, 'native_success_not_inspected': True}; note(evidence)
        R['final_evidence'] = evidence; save()
        if not inside or not detached:
            fail('Actual release occurred, but measured containment or separation remains unresolved: ' + str(evidence))
        R['phase'] = 'done'; save()
        return {'completion_proposed': True, 'evidence': {'final': evidence, 'measurements': history[-10:], 'limitations': R['model_limit'] + ' Uncertainty is heuristic. A registered rigid printed face and stable independent RGB-D samples support observed containment and detachment, not hidden support-force certification or official success.'}}
    def finish_checkpointed_hold():
        if api.state()['budgets']['gpt_remaining'] < 2:
            fail('Held continuation needs one current geometry review and one actual post-release review.')
        fields = {'identity': ['same_unambiguous', 'ambiguous', 'unknown'], 'stationary_bowl': ['yes', 'no', 'unknown'], 'external': ['observed', 'none_observed', 'unknown'], 'visibility': ['observed', 'partial', 'self_occluded'], 'descent': ['supported', 'unknown'], 'retreat': ['supported', 'external_obstacle', 'unknown'], 'camera': ['agentview', 'robot0_eye_in_hand'], 'corners': {'type': 'array', 'items': pixel, 'minItems': 0, 'maxItems': 2}, 'edge': ['short', 'long', 'unknown'], 'patch_camera': ['agentview', 'robot0_eye_in_hand'], 'patch_polygon': {'type': 'array', 'items': pixel, 'minItems': 0, 'maxItems': 16}, 'view': ['up_supported', 'none']}
        question = 'Continue the retained carton placement, not a new grasp. identity=same_unambiguous means the same unchanged rigid carton and unambiguous identities for any supplied printed landmarks. Request current L0,L1,L2 only where identifiable using the saved physical definitions; two suffice for recovery. Request top as a CURRENT carton-only interior planar face cloud, explicit camera, box, stride 4, excluding fingers/background. Return exactly TWO genuinely visible adjacent corners of one full top edge in camera, and edge=short or long using reference dimensions; empty corners and unknown if unavailable. Do not invent hidden corners. Choose a current textured carton-only patch_polygon in patch_camera. stationary_bowl=yes means the measured bowl remains unmoved, no for observed change, unknown otherwise. external=observed means an external conflict with the local descent; none_observed means no observed conflict, NOT certified clearance; unknown means unresolved external evidence. visibility distinguishes observed, partial unobserved space, and robot/payload self_occlusion. descent=supported only if centering by at most 0.006 m and descending at most 0.05 m above this opening is locally justified, stopping with BOTH carton and finger lower envelopes above the measured rim. Only this local segment is requested. retreat separately assesses a 0.06 m upward OPEN-hand observation move after release: supported, external_obstacle, or unknown. Complete corridor/perimeter visibility is not required. view=up_supported only for a separately justified 0.015 m upward correspondence-producing view; otherwise none.'
        ref = np.array(R['vertices']); dimensions = sorted([float(np.linalg.norm(ref[1] - ref[0])), float(np.linalg.norm(ref[2] - ref[1]))])
        ans = review(question, fields, {'definitions': R['definitions'], 'reference_observations': R['landmark_observations'], 'dimensions_m': dimensions, 'bowl_xy': R['bowl_xy'], 'rim_z': R['rim_z'], 'bowl_radius_m': R['bowl_radius'], 'historical_retention_and_motion': R.get('recent', []), 'saved_object_observation': R['last_obs'], 'saved_robot_frame': R['last_state']['frame_id']}, reserve=1)
        a = ans['parameters']
        if a['identity'] != 'same_unambiguous' or a['stationary_bowl'] != 'yes' or a['external'] != 'none_observed' or a['descent'] != 'supported':
            fail('Current identity, destination invariance, or local descent evidence is insufficient: ' + str(a))
        if len(a['corners']) != 2 or a['edge'] not in ['short', 'long'] or not valid(ans, 'top', 'regions'):
            fail('Missing current top cloud or identifiable full edge for independent release geometry.')
        cloud = np.array(ans['regions']['top']['world_m'])
        if len(cloud) < 8:
            fail('Too few current interior top samples.')
        fit = geo.plane(cloud); normal = np.array(fit['coefficients'][:3]); spread = min(fit['in_plane_spread_m'])
        if fit['rms_m'] > 0.0025 or spread <= 0.003 or normal[2] < 0.98:
            fail('Inadequate current top plane: ' + str(fit))
        cc = np.array([api.plane_point(a['camera'], px, fit['coefficients'])['world_m'] for px in a['corners']]); step = 0.0
        for px, point in zip(a['corners'], cc):
            for axis in range(2):
                near = list(px); near[axis] += 1 if near[axis] < 767 else -1
                step = max(step, float(np.linalg.norm(np.array(api.plane_point(a['camera'], near, fit['coefficients'])['world_m']) - point)))
        edge = cc[1] - cc[0]; length = float(np.linalg.norm(edge)); index = 0 if a['edge'] == 'short' else 1; extension = dimensions[1 - index]
        plane_u = max(R['u'], 2 * fit['rms_m']); boundary_u = 2 * step
        note({'current_edge_m': length, 'reference_edge_m': dimensions[index], 'plane': fit, 'pixel_step_m': step})
        if length <= 0.01 or abs(length - dimensions[index]) > 2 * (plane_u + R['u'] + boundary_u):
            fail('Visible edge disagrees with the measured rigid carton dimensions.')
        inward = np.cross(normal, edge / length); inward /= np.linalg.norm(inward); side = float(np.dot(np.array(fit['center_world_m']) - cc.mean(axis=0), inward))
        if abs(side) <= max(plane_u, 2 * boundary_u):
            fail('Visible interior does not resolve the physical side of the edge.')
        inward *= 1 if side > 0 else -1
        cc = np.array([cc[0], cc[1], cc[1] + inward * extension, cc[0] + inward * extension]); v0 = np.concatenate([cc, cc - normal * R['height']])
        u0 = math.sqrt(plane_u ** 2 + boundary_u ** 2 + R['u'] ** 2 + (2 * boundary_u * extension / length) ** 2 + (R['radius'] * 2 * fit['rms_m'] / spread) ** 2)
        if R['last_obs']['frame_id'] != api.state()['frame_id'] or R['last_state']['frame_id'] != api.state()['frame_id']:
            observe(force_landmarks=True, sample=ans); check_hold()
        anchor = R['last_obs']; s0 = api.state(); pad = np.array(geo.pad_position(s0)); q = s0['tcp_quaternion_xyzw']
        R['compact_reference'] = {'frame_id': ans['frame_id'], 'vertices': v0.tolist(), 'u_m': u0, 'plane_fit': fit, 'corner_camera': a['camera'], 'corners': a['corners'], 'edge': a['edge'], 'patch_camera': a['patch_camera'], 'patch_polygon': a['patch_polygon'], 'landmark_points': {n: ans['points'][n] for n in ['L0', 'L1', 'L2'] if valid(ans, n)}, 'anchor': anchor, 'permissions': {n: a[n] for n in ['external', 'visibility', 'descent', 'retreat']}, 'prior_retention': [e for e in history if e.get('retention_test') is True]}; save()
        handle = None; patch_frame = None
        if len(a['patch_polygon']) >= 3:
            try:
                init = api.track_init(a['patch_camera'], a['patch_polygon']); handle = init['handle']; patch_frame = init['frame_id']
                note({'release_patch_frame': patch_frame, 'reference_features': init['reference_features']})
            except Exception as exc:
                note({'release_patch_init_error': str(exc), 'fallback': 'Independent semantic landmarks and measured plane'})
        def current_footprint():
            if handle is not None:
                try:
                    t = api.track_update(handle)
                    if t['status'] == 'tracked':
                        pts = np.array(t['reference_inlier_world_m']); sp = float(np.linalg.svd(pts - pts.mean(axis=0), compute_uv=False)[1] / math.sqrt(len(pts)))
                        lever = float(np.max(np.linalg.norm(v0 - np.array(t['reference_patch_centroid_world_m']), axis=1)))
                        extra = max(0.001, t['uncertainty_floor_m']) ** 2 + (lever * max(0.0001, t['rms_m']) / max(sp, 0.001)) ** 2
                        note({'local_track_frame': t['frame_id'], 'reference_frame': t['reference_frame_id'], 'inliers': t['inliers'], 'matches': t['matches'], 'rms_m': t['rms_m'], 'spread_m': sp, 'local_u_m': math.sqrt(u0 ** 2 + extra)})
                        if t['frame_id'] == api.state()['frame_id'] and t['reference_frame_id'] == patch_frame and t['inliers'] >= 12 and t['inliers'] / max(1, t['matches']) >= 0.65 and t['rms_m'] <= 0.002 and sp > 0.0025:
                            delta = np.array(t['transform_initial_world_to_current_world'])
                            return geo.transform(v0, delta), math.sqrt(u0 ** 2 + extra), delta @ np.array(anchor['T']), math.sqrt(anchor['u'] ** 2 + extra), 'current_edge_and_patch'
                    else:
                        note({'local_registration': 'unknown', 'reason': t['reason'], 'frame_id': t['frame_id']})
                except Exception as exc:
                    note({'local_registration_error': str(exc)})
            recovery = registration_review('recover', reserve=0); obs = observe(force_landmarks=True, sample=recovery)
            delta = np.array(obs['T']) @ np.linalg.inv(np.array(anchor['T']))
            return geo.transform(v0, delta), math.sqrt(u0 ** 2 + anchor['u'] ** 2 + obs['u'] ** 2), np.array(obs['T']), obs['u'], 'independent_semantic_recovery'
        margin = R['u'] + u0 + 0.003; target = pad.copy(); target[:2] += np.array(R['bowl_xy']) - cc[:, :2].mean(axis=0)
        target[2] = max(R['rim_z'] + margin - float(np.min(v0[:, 2] - pad[2])), R['rim_z'] + margin - finger_bottom(s0, q))
        radial0 = float(np.max(np.linalg.norm(v0[:, :2] - np.array(R['bowl_xy']), axis=1)))
        note({'local_release_target_pad': target.tolist(), 'initial_radial_extent_m': radial0, 'aperture_radius_m': R['bowl_radius'], 'local_geometry_u_m': u0, 'uncertainty_model': 'Heuristic RSS of measured surface, two-pixel edge, dimension, normal, and registration errors; not calibrated confidence.'})
        if np.linalg.norm(target[:2] - pad[:2]) > 0.006 or not (-0.05 <= target[2] - pad[2] <= 0.003) or radial0 + R['u'] + u0 >= R['bowl_radius']:
            fail('Fresh geometry falls outside the reviewed small descent/centering scope; see numerical target and aperture evidence.')
        R['intent'] = 'Locally supported closed-hand descent above the measured opening'; R['pending_target_pad'] = target.tolist(); save()
        out = command(target.tolist(), q, 'keep', contact=True)
        if np.linalg.norm(np.array(geo.pad_position(api.state())) - target) > 0.0035 or out['rotation_error_rad'] > 0.04:
            fail('Bounded descent did not converge; no repeated contact pushing.')
        vertices, uncertainty, global_T, global_u, source = current_footprint(); now = api.state()
        err = float(geo.attachment_error(v0, vertices, s0, now)); tolerance = 0.003 + u0 + uncertainty
        note({'descent_attachment_error_m': err, 'tolerance_m': tolerance, 'actual_hand_delta_m': (np.array(geo.pad_position(now)) - pad).tolist(), 'observed_object_delta_m': (vertices.mean(axis=0) - v0.mean(axis=0)).tolist(), 'source': source})
        if err > tolerance:
            fail('Current independent object motion does not agree with the measured hand motion; not opening.')
        R['last_obs'] = {'T': global_T.tolist(), 'u': global_u, 'frame_id': now['frame_id'], 'source': source}; R['last_state'] = now; save()
        radial = float(np.max(np.linalg.norm(vertices[:, :2] - np.array(R['bowl_xy']), axis=1))); available = R['bowl_radius'] - radial; needed = R['u'] + uncertainty + 0.001
        low_z = float(np.min(vertices[:, 2])); finger_z = float(geo.pad_position(now)[2] + finger_bottom(now, q))
        note({'release_aperture_margin_m': available, 'required_measured_margin_m': needed, 'object_low_z_m': low_z, 'finger_low_z_m': finger_z, 'rim_z_m': R['rim_z'], 'note': 'Current measured footprint already includes actual pose error; target tolerance is not added again as an independent error.'})
        if available <= needed or min(low_z, finger_z) <= R['rim_z'] + R['u'] + uncertainty or low_z - R['rim_z'] > 0.5 * R['bowl_radius']:
            fail('Measured release aperture or height margin is inadequate; preserving the grasp.')
        if api.state()['budgets']['gpt_remaining'] < 1:
            fail('Independent registration recovered the current geometry, but no actual post-release review remains; preserving the grasp.')
        R['release_footprint'] = {'frame_id': now['frame_id'], 'vertices': vertices.tolist(), 'u_m': uncertainty, 'source': source}; R['phase'] = 'releasing'; R['intent'] = 'Measured above-opening release'; save()
        for opening in range(3):
            s = api.state(); command(geo.pad_position(s).tolist(), q, 'open', lease=False)
        R['phase'] = 'released'; save()
        if handle is not None:
            try:
                effect = api.track_update(handle); note({'post_open_registration': effect['status'], 'frame_id': effect['frame_id'], 'interpretation': 'Observation of the contact transition, not proof of release or stable containment.'})
            except Exception as exc:
                note({'post_open_registration_error': str(exc)})
        retreated = a['retreat'] == 'supported'
        if retreated:
            s = api.state(); R['intent'] = 'Reviewed open-hand observation retreat'; command((np.array(geo.pad_position(s)) + [0, 0, 0.06]).tolist(), q, 'open')
        final_fields = {'identity': ['same', 'ambiguous', 'unknown'], 'relation': ['inside', 'rim_supported', 'outside', 'unknown'], 'support': ['resting', 'falling', 'unknown'], 'separation': ['separate', 'contact', 'unknown']}
        final_question = 'Assess the ACTUAL released cream-cheese carton. identity=same only for the same carton. relation=inside requires containment in the bowl interior, not projected overlap or rim bridging; otherwise rim_supported, outside, unknown. support=resting requires visible resting evidence, otherwise falling or unknown. separation=separate requires visible absence of finger contact, otherwise contact or unknown. Request settled_top as a carton-only textured INTERIOR visible face region in agentview, explicit box and stride 4, excluding the bowl and fingers. Its RGB-D pattern will be compared after settling; a fully visible outline is not needed.'
        if not retreated:
            final_fields['retreat'] = ['supported', 'external_obstacle', 'unknown']; final_question += ' Also assess retreat for a 0.06 m upward open-hand observation move: supported means locally justified without an observed external conflict, external_obstacle means an observed conflict, unknown means insufficient local evidence; self-occlusion alone is not an obstacle.'
        final = review(final_question, final_fields, {'definitions': R['definitions'], 'reference_observations': R['landmark_observations'], 'release_footprint': R['release_footprint'], 'bowl_xy': R['bowl_xy'], 'rim_z': R['rim_z']}, reserve=0)
        p = final['parameters']; R['final_previous'] = {'frame_id': final['frame_id'], 'parameters': p, 'measurement_errors': final['measurement_errors']}; save()
        if not valid(final, 'settled_top', 'regions'):
            fail('Released-object review lacks a usable textured RGB-D stability region: ' + str(final['measurement_errors']))
        c0 = final['regions']['settled_top']; calibration = api.camera('agentview')
        if c0['camera'] != 'agentview' or len(c0['world_m']) < 12:
            fail('Final stability region is not sufficiently sampled in the fixed external view.')
        if not retreated:
            if p['retreat'] != 'supported':
                fail('Released state observed, but no justified new-view retreat: ' + p['retreat'])
            s = api.state(); command((np.array(geo.pad_position(s)) + [0, 0, 0.06]).tolist(), q, 'open')
        for settling in range(3):
            s = api.state(); command(geo.pad_position(s).tolist(), q, 'open', lease=False)
        c1 = api.cloud('agentview', c0['box'], stride=c0['stride']); calibration1 = api.camera('agentview')
        lookup = {tuple(px): i for i, px in enumerate(c1['pixels'])}; pairs = [(i, lookup[tuple(px)]) for i, px in enumerate(c0['pixels']) if tuple(px) in lookup]
        if len(pairs) < 12 or len(pairs) < 0.85 * len(c0['pixels']):
            fail('Too few corresponding depth-valid external-view samples after settling.')
        ids0 = [ij[0] for ij in pairs]; ids1 = [ij[1] for ij in pairs]
        w0 = np.array(c0['world_m'])[ids0]; w1 = np.array(c1['world_m'])[ids1]; rgb0 = np.array(c0['rgb'], dtype=float)[ids0]; rgb1 = np.array(c1['rgb'], dtype=float)[ids1]
        scale = max(1.0, float(np.max(rgb0)), float(np.max(rgb1))); texture = float(np.mean(np.std(rgb0 / scale, axis=0)))
        depth_change = float(np.quantile(np.linalg.norm(w1 - w0, axis=1), 0.95)); color_change = float(np.quantile(np.max(np.abs(rgb1 - rgb0), axis=1) / scale, 0.95)); footprint_spread = min(geo.plane(w0)['in_plane_spread_m'])
        camera_change = float(np.max(np.abs(np.array(calibration['camera_to_world_opencv']) - np.array(calibration1['camera_to_world_opencv']))))
        stable = camera_change < 0.000001 and texture > 0.02 and footprint_spread > 0.002 and depth_change <= 2 * R['u'] + 0.001 and color_change <= 0.04 and c1['frame_id'] > c0['frame_id']
        evidence = {'interpretation': p, 'review_frame': final['frame_id'], 'stability_frames': [c0['frame_id'], c1['frame_id']], 'matched_samples': len(pairs), 'texture': texture, 'patch_spread_m': footprint_spread, 'depth_change_95_m': depth_change, 'color_change_95_fraction': color_change, 'camera_change': camera_change, 'stability_observed': bool(stable), 'native_success_not_inspected': True}; note(evidence)
        if p['identity'] != 'same' or p['relation'] != 'inside' or p['support'] != 'resting' or p['separation'] != 'separate' or not stable:
            fail('Release occurred, but actual containment, separation, and measured stability were not jointly established: ' + str(evidence))
        R['phase'] = 'done'; R['final_evidence'] = evidence; save()
        return {'completion_proposed': True, 'evidence': {'final': evidence, 'measurements': history[-10:], 'limitations': R['model_limit'] + ' Uncertainty is heuristic; local reviews do not certify collision-free swept volumes. Stable textured visible surfaces support short-episode stability, not hidden support-force certification.'}}
    def final_observation(previous=None):
        fields = {'relation': ['inside', 'rim_supported', 'outside', 'unknown'], 'support': ['resting', 'falling', 'unknown'], 'separation': ['separate', 'contact', 'unknown'], 'motion': ['unchanged', 'changed', 'unknown'], 'identity': ['same', 'ambiguous', 'unknown']}
        question = 'Assess the ACTUAL released carton. relation=inside means contained in the bowl interior, not image overlap or rim bridging; otherwise rim_supported, outside, unknown. support=resting requires visible resting evidence, otherwise falling or unknown. separation=separate requires no finger contact, otherwise contact or unknown. motion compares identifiable physical features against previous: unchanged, changed, or unknown; exclude camera motion. Request current L0,L1,L2 only where the SAME defined landmarks are identifiable; identity=same only for unambiguous correspondence, otherwise ambiguous or unknown. Missing landmarks alone never prove stability. '
        if previous is None:
            fields['retreat'] = ['supported', 'external_obstacle', 'unknown']
            question += 'retreat=supported only if a 0.06 m world-up open-hand retreat is locally justified without an observed external conflict; external_obstacle for a visible conflict, unknown otherwise. Self-occlusion is not an external obstacle and complete corridor visibility is not required. '
        return review(question, fields, {'definitions': R['definitions'], 'reference_observations': R['landmark_observations'], 'previous': previous, 'bowl_reference': {'xy': R['bowl_xy'], 'rim_z': R['rim_z']}}, reserve=0)
    try:
        repaired = any(m['key'] == 'carton_bowl_method' for m in api.recall())
        if repaired:
            R.update(api.recall('carton_bowl_method')['value']); history.extend(R.get('recent', [])); R['route_scope'] = []
            if R['phase'] == 'held':
                if api.state()['budgets']['gpt_remaining'] == 0:
                    return finish_measured_release()
                return finish_checkpointed_hold()
            ans = registration_review('resume'); a = ans['parameters']
            if a['stationary_bowl_support'] != 'yes':
                fail('Saved destination/support invariants are unresolved; fresh geometry is needed.')
            if R['phase'] == 'releasing':
                if a['object'] == 'released':
                    R['phase'] = 'released'
                elif a['object'] == 'held':
                    R['phase'] = 'held'
                else:
                    fail('Interrupted release has ambiguous contact; not reopening.')
            if R['phase'] == 'ready' and a['object'] != 'supported_flat':
                fail('The carton is not independently established as supported flat.')
            if R['phase'] not in ['released', 'done']:
                observe(force_landmarks=True, sample=ans)
        else:
            acquire()
        if R['phase'] == 'ready':
            obs = R['initial_obs'] if api.state()['frame_id'] == R['reference_frame'] else observe()
            vertices = body(obs); corners = vertices[:4]; center = corners.mean(axis=0); s = api.state(); q = s['tcp_quaternion_xyzw']; rot = geo.rotation(q)
            if rot[2, 2] > -0.95:
                fail('Current tool tilt is unsuitable for the measured top-down side pinch; only a justified yaw change is implemented.')
            e0 = corners[1] - corners[0]; e1 = corners[2] - corners[1]; short = e0 if np.linalg.norm(e0) < np.linalg.norm(e1) else e1
            yaw = math.atan2(short[1], short[0]) - math.atan2(rot[1, 1], rot[0, 1]); yaw = (yaw + math.pi / 2) % math.pi - math.pi / 2
            q = api.compose(q, [0, 0, float(yaw)]); pose_u = 0.003; margin = R['u'] + pose_u
            low = finger_bottom(s, q); base = float(np.max(vertices[4:, 2])); topz = float(np.min(corners[:, 2]))
            extent = np.array(s['own_geometry']['pad_extent_in_tool_m']); rz = geo.rotation(q)[2]
            band_half = float((abs(rz[2]) * extent[2] - abs(rz[0]) * extent[0] - abs(rz[1]) * extent[1]) / 2)
            graspz = max(base + R['height'] / 2, base + margin - low)
            overlap = min(topz - R['u'], graspz + band_half - pose_u) - max(base + R['u'], graspz - band_half + pose_u)
            opening = abs(s['gripper_qpos_m'][0] - s['gripper_qpos_m'][1]); nominal_gap = max(0.0, 2 * opening - float(extent[1]))
            width = float(np.linalg.norm(short)); side_margin = (nominal_gap - width) / 2 - margin
            R['plan'] = {'grasp_pad_world_m': [float(center[0]), float(center[1]), graspz], 'short_width_m': width, 'nominal_parallel_pad_gap_m': nominal_gap, 'finger_bottom_relative_to_pad_m': low, 'support_z_m': base, 'top_z_m': topz, 'margin_m': margin, 'common_pad_band_world_z_m': [graspz - band_half, graspz + band_half], 'robust_side_height_overlap_m': overlap, 'remaining_open_side_margin_m': side_margin, 'nominal_finger_support_gap_m': graspz + low - base, 'note': 'The finite pad band, not its center, must overlap the carton side. Opening and contact-band geometry are planning estimates; actual arrangement and retention still require observations.'}; note(R['plan']); save()
            if band_half <= pose_u or overlap <= 0 or side_margin <= 0:
                fail('No jointly feasible finite-pad overlap, support clearance, or inner-opening margin; see measured plan values.')
            R['intent'] = 'Locally reviewed open-pad short-side pinch approach'
            if s['last_gripper_command'] != 'open':
                command(geo.pad_position(s).tolist(), s['tcp_quaternion_xyzw'], 'open', lease=False)
            grasp = np.array(R['plan']['grasp_pad_world_m']); pnow = np.array(geo.pad_position(api.state()))
            aligned = 2 * math.acos(min(1.0, abs(float(np.dot(q, s['tcp_quaternion_xyzw']))))) <= 0.04
            note({'registration_u_m': obs['u'], 'remaining_side_margin_after_registration_m': side_margin - obs['u']})
            if side_margin <= obs['u']:
                fail('Current registration uncertainty consumes the measured open-side margin.')
            if not (repaired and aligned and pnow[2] >= grasp[2] and np.linalg.norm(pnow - grasp) <= 0.03):
                pre = grasp + [0, 0, max(0.04, R['height'])]; above = pre.copy(); above[2] = max(pre[2], pnow[2])
                move(above.tolist(), q, 'open'); move(pre.tolist(), q, 'open')
            move(grasp.tolist(), q, 'open', contact=True)
            ans = registration_review('approach')
            if ans['parameters']['arrangement'] != 'straddled':
                fail('Actual preclosure finger/carton arrangement unresolved: ' + str(ans['parameters']))
            R['last_obs'] = observe(sample=ans); R['last_state'] = api.state(); R['probe_target'] = (np.array(geo.pad_position(R['last_state'])) + [0, 0, R['probe_distance']]).tolist(); R['phase'] = 'closing'; save()
        if R['phase'] == 'closing':
            R['intent'] = 'Close at the observed straddling pose; closure itself is not grasp evidence'; save()
            for closure_step in range(3):
                s = api.state(); command(geo.pad_position(s).tolist(), s['tcp_quaternion_xyzw'], 'close', lease=False)
            R['phase'] = 'lifting'; save()
        if R['phase'] == 'lifting':
            a = review('Review the actual closure effect. contact=candidate if the carton remains plausibly pinched between the pads; miss if visibly pushed away/not enclosed; self_occluded if the previously straddled contact area is now hidden by the fingers, with no visible miss; otherwise unknown. probe=locally_supported only if the planned small upward retention-measurement lift has no observed external impediment and is justified by the nearby geometry. Do not demand proof of retention or a fully visible outline before this test.', {'contact': ['candidate', 'miss', 'self_occluded', 'unknown'], 'probe': ['locally_supported', 'unknown']}, {'baseline': R['last_obs'], 'probe_target_pad_world_m': R['probe_target'], 'plan': R['plan']})['parameters']
            if a['contact'] not in ['candidate', 'self_occluded'] or a['probe'] != 'locally_supported':
                fail('Closure did not justify a retention test: ' + str(a))
            R['intent'] = 'Small observation-producing retention lift, not an assumed grasp'; save()
            if geo.pad_position(api.state())[2] - geo.pad_position(R['last_state'])[2] < 0.025:
                command(R['probe_target'], api.state()['tcp_quaternion_xyzw'], 'keep')
            check_hold(probe=True); R['phase'] = 'held'; save()
        if R['phase'] == 'held':
            if repaired:
                check_hold()
            R['intent'] = 'Raise retained carton locally, translate above measured bowl opening, then approach release height'; save()
            s = api.state(); q = s['tcp_quaternion_xyzw']; pad = np.array(geo.pad_position(s)); vertices = body(R['last_obs']); low = finger_bottom(s, q)
            high = pad.copy(); high[2] = max(pad[2], R['rim_z'] + 0.04 - float(np.min(vertices[:, 2] - pad[2])), R['rim_z'] + 0.04 - low)
            cross = high.copy(); cross[:2] += np.array(R['bowl_xy']) - vertices[:4, :2].mean(axis=0)
            lower = cross.copy(); margin = R['u'] + R['last_obs']['u'] + 0.003
            lower[2] = max(R['rim_z'] + margin - float(np.min(vertices[:, 2] - pad[2])), R['rim_z'] + margin - low)
            names = ['raise_leg', 'transfer_leg', 'lower_leg']; poses = [pad.tolist(), high.tolist(), cross.tolist(), lower.tolist()]
            choices = ['supported', 'self_occluded_supported', 'external_obstacle', 'unknown']
            ans = review('Assess raise_leg, transfer_leg and lower_leg INDEPENDENTLY for consecutive displayed pad poses, preserving orientation and grip. supported means local measured surfaces, own geometry and images justify that bounded segment without an observed conflicting external obstacle. self_occluded_supported means the same justification despite robot/payload occlusion. external_obstacle means an observed external conflict. unknown means insufficient local evidence, including unobserved external space without geometric support. No outcome certifies a collision-free swept volume or requires complete corridor visibility. Unknown later segments must not veto a justified earlier raise. The vertices are current measurements; later translated poses are plans, NOT observed attachment. Allow a 0.006 m feedback envelope around the displayed endpoints only if locally supported.', {name: choices for name in names}, {'poses_pad_world_m': poses, 'quaternion_xyzw': q, 'current_vertices': vertices.tolist(), 'object_uncertainty_m': R['last_obs']['u'], 'rim_z': R['rim_z'], 'table_plane': R['table_plane'], 'bowl_xy': R['bowl_xy']})
            R['route_scope'] = [{'start': poses[i], 'target': poses[i + 1], 'permission': ans['parameters'][name], 'review_frame': ans['frame_id']} for i, name in enumerate(names)]; save()
            move(high.tolist(), q, 'keep', held=True)
            pad = np.array(geo.pad_position(api.state())); vertices = body(R['last_obs']); horizontal = pad.copy(); horizontal[:2] += np.array(R['bowl_xy']) - vertices[:4, :2].mean(axis=0)
            move(horizontal.tolist(), q, 'keep', held=True)
            pad = np.array(geo.pad_position(api.state())); vertices = body(R['last_obs']); margin = R['u'] + R['last_obs']['u'] + 0.003
            release = pad.copy(); release[:2] += np.array(R['bowl_xy']) - vertices[:4, :2].mean(axis=0); release[2] = max(R['rim_z'] + margin - float(np.min(vertices[:, 2] - pad[2])), R['rim_z'] + margin - finger_bottom(api.state(), q))
            if release[2] + float(np.min(vertices[:, 2] - pad[2])) - R['rim_z'] > 0.5 * R['bowl_radius']:
                fail('Finger clearance would require an unjustifiably high drop above the opening.')
            move(release.tolist(), q, 'keep', held=True)
            vertices = body(R['last_obs']); release_u = R['last_obs']['u']; release_source = R['last_obs']['source']
            for aperture_trial in range(2):
                radial = float(np.max(np.linalg.norm(vertices[:, :2] - np.array(R['bowl_xy']), axis=1))); available = R['bowl_radius'] - radial; needed = R['u'] + release_u + 0.003
                note({'release_aperture_margin_m': available, 'required_margin_m': needed, 'object_low_z_m': float(np.min(vertices[:, 2])), 'rim_z_m': R['rim_z'], 'footprint_source': release_source})
                if available > needed and np.min(vertices[:, 2]) >= R['rim_z'] + R['u'] + release_u:
                    R['release_footprint'] = {'frame_id': api.state()['frame_id'], 'vertices': vertices.tolist(), 'u_m': release_u, 'source': release_source}; save(); break
                if aperture_trial == 1:
                    fail('Current footprint lacks an above-rim aperture margin; not opening.')
                ans = review('Resolve placement geometry independently of the propagated pose. identity=same_rigid_carton requires the same unchanged rectangular cream-cheese carton. Request release_top: a current carton-only INTERIOR top-face cloud, explicit camera, box and stride 4, excluding fingers/background. In camera return either four genuinely visible top corners clockwise, or two genuinely visible adjacent corner endpoints of one full top edge. Prefer the detailed wrist view. For two corners, edge is short or long; for four, not_used. Never invent an occluded corner or reuse a historical projection. Unknown identity or no usable edge: empty corners and edge=unknown. A two-corner footprint will be inferred from the measured rigid dimensions and the visible interior side of this edge, not from robot motion.', {'identity': ['same_rigid_carton', 'unknown'], 'camera': ['agentview', 'robot0_eye_in_hand'], 'corners': {'type': 'array', 'items': pixel, 'minItems': 0, 'maxItems': 4}, 'edge': ['short', 'long', 'not_used', 'unknown']}, {'definitions': R['definitions'], 'reference_dimensions_m': [float(np.linalg.norm(np.array(R['vertices'][1]) - np.array(R['vertices'][0]))), float(np.linalg.norm(np.array(R['vertices'][2]) - np.array(R['vertices'][1])))], 'reason': 'Propagated footprint uncertainty or alignment was insufficient.'})
                a = ans['parameters']
                if a['identity'] != 'same_rigid_carton' or len(a['corners']) not in [2, 4] or not valid(ans, 'release_top', 'regions'):
                    fail('No current identifiable top region and usable boundary geometry for the release aperture test.')
                cloud = np.array(ans['regions']['release_top']['world_m'])
                if len(cloud) < 8:
                    fail('Too few current top-face depth samples.')
                fit = geo.plane(cloud); spread = min(fit['in_plane_spread_m']); normal = np.array(fit['coefficients'][:3])
                if fit['rms_m'] > 0.0025 or spread <= 0.003 or normal[2] < 0.98:
                    fail('Current release top fit is inadequate: ' + str(fit))
                cc = np.array([api.plane_point(a['camera'], px, fit['coefficients'])['world_m'] for px in a['corners']]); pixel_step = 0.0
                for px, point in zip(a['corners'], cc):
                    for axis in range(2):
                        near = list(px); near[axis] += 1 if near[axis] < 767 else -1
                        adjacent = np.array(api.plane_point(a['camera'], near, fit['coefficients'])['world_m'])
                        pixel_step = max(pixel_step, float(np.linalg.norm(adjacent - point)))
                ref = np.array(R['vertices']); dimensions = sorted([float(np.linalg.norm(ref[1] - ref[0])), float(np.linalg.norm(ref[2] - ref[1]))])
                boundary_u = 2 * pixel_step; plane_u = max(R['u'], 2 * fit['rms_m']); normal_u = 2 * fit['rms_m'] / spread
                variance = plane_u ** 2 + boundary_u ** 2 + (R['radius'] * normal_u) ** 2
                inferred = len(cc) == 2
                if inferred:
                    if a['edge'] not in ['short', 'long']:
                        fail('The visible edge cannot be matched unambiguously to measured dimensions.')
                    index = 0 if a['edge'] == 'short' else 1; edge = cc[1] - cc[0]; length = float(np.linalg.norm(edge)); extension = dimensions[1 - index]
                    if abs(length - dimensions[index]) > 2 * (plane_u + R['u'] + boundary_u):
                        fail('Current edge length disagrees with rigid reference: ' + str({'length_m': length, 'expected_m': dimensions[index]}))
                    inward = np.cross(normal, edge / max(length, 0.00001)); inward /= max(float(np.linalg.norm(inward)), 0.00001)
                    side = float(np.dot(np.array(fit['center_world_m']) - cc.mean(axis=0), inward))
                    if abs(side) <= max(plane_u, 2 * boundary_u):
                        fail('Visible interior does not establish which side of the edge contains the carton.')
                    inward *= 1 if side > 0 else -1
                    cc = np.array([cc[0], cc[1], cc[1] + inward * extension, cc[0] + inward * extension])
                    variance += R['u'] ** 2 + (2 * boundary_u * extension / max(length, 0.00001)) ** 2
                else:
                    e0 = cc[1] - cc[0]; e1 = cc[2] - cc[1]; lengths = sorted([float(np.linalg.norm(e0)), float(np.linalg.norm(e1))])
                    if max(abs(lengths[i] - dimensions[i]) for i in range(2)) > 2 * (plane_u + R['u'] + boundary_u) or abs(float(np.dot(e0, e1))) > 0.12 * lengths[0] * lengths[1] or np.linalg.norm(cc[3] - cc[0] - e1) > 3 * (plane_u + boundary_u):
                        fail('Current visible corners do not match the measured rigid rectangle: ' + str({'lengths_m': lengths, 'reference_m': dimensions}))
                release_u = math.sqrt(float(variance)); vertices = np.concatenate([cc, cc - normal * R['height']]); release_source = 'current_edge_plane_and_measured_dimensions' if inferred else 'current_four_corners_and_plane'
                note({'fresh_footprint_frame': ans['frame_id'], 'source': release_source, 'top_fit_rms_m': fit['rms_m'], 'pixel_step_m': pixel_step, 'footprint_u_m': release_u, 'uncertainty_model': 'Heuristic RSS of depth/plane, two-pixel boundary, normal-fit, and inferred dimension/direction terms; not calibrated confidence. Hidden bottom uses the measured rigid height.'})
            R['phase'] = 'releasing'; R['intent'] = 'Release only after measured above-opening alignment'; save()
            for release_step in range(3):
                s = api.state(); command(geo.pad_position(s).tolist(), s['tcp_quaternion_xyzw'], 'open', lease=False)
            R['phase'] = 'released'; save()
        if R['phase'] in ['released', 'done']:
            first = final_observation(); previous = {'parameters': first['parameters'], 'points': first['points'], 'measurement_errors': first['measurement_errors'], 'frame_id': first['frame_id']}; R['final_previous'] = previous; save()
            if first['parameters']['retreat'] != 'supported':
                fail('Post-release view change is not justified: ' + first['parameters']['retreat'])
            s = api.state(); R['intent'] = 'Observed-supported open-hand retreat for a fresh post-release view'; save()
            command((np.array(geo.pad_position(s)) + [0, 0, 0.06]).tolist(), s['tcp_quaternion_xyzw'], 'open')
            for verification in range(2):
                current = final_observation(previous); p = current['parameters']; stable = False; displacement = None
                if p['identity'] == 'same' and previous['parameters']['identity'] == 'same' and all(valid(current, 'L' + str(i)) and valid(previous, 'L' + str(i)) for i in range(3)):
                    displacement = max(float(np.linalg.norm(np.array(current['points']['L' + str(i)]['world_m']) - np.array(previous['points']['L' + str(i)]['world_m']))) for i in range(3)); stable = displacement <= 2 * R['u'] + 0.002
                else:
                    stable = p['motion'] == 'unchanged' and previous['parameters']['support'] == 'resting' and previous['parameters']['relation'] == 'inside'
                evidence = {'frame_id': current['frame_id'], 'final_interpretation': p, 'landmark_change_m': displacement, 'stability_observed': stable, 'native_success_not_inspected': True}; note(evidence)
                if p['relation'] == 'inside' and p['support'] == 'resting' and p['separation'] == 'separate' and stable:
                    R['phase'] = 'done'; R['final_evidence'] = evidence; save(); return {'completion_proposed': True, 'evidence': {'final': evidence, 'measurements': history[-10:], 'limitations': R['model_limit'] + ' Registration uncertainty is heuristic; local obstruction reviews are not collision certificates.'}}
                if verification == 0:
                    previous = {'parameters': p, 'points': current['points'], 'measurement_errors': current['measurement_errors'], 'frame_id': current['frame_id']}
                    for settling_step in range(2):
                        s = api.state(); command(geo.pad_position(s).tolist(), s['tcp_quaternion_xyzw'], 'open', lease=False)
            fail('Release was executed, but containment, separation, and stability were not jointly established.')
        fail('Unrecognized persistent phase: ' + R['phase'])
    except Exception as exc:
        note({'stopped': str(exc), 'phase': R['phase']})
        return {'completion_proposed': False, 'evidence': {'reason': str(exc), 'phase': R['phase'], 'measurements': history[-12:], 'reference_frame': R.get('reference_frame'), 'last_object_observation': R.get('last_obs'), 'pending_target_pad': R.get('pending_target_pad'), 'limitation': 'No hidden object state, force sensing, complete corridor certificate, or official success predicate was used.'}}

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
        api.checkpoint('progress', {'phase': mem.get('phase', 'initializing'), 'held': mem.get('held', False), 'intent': mem.get('intent'), 'snapshot': mem.get('snapshot')})
    def start_patch(camera, poly, base):
        tracker.clear()
        if poly is not None:
            try:
                t = api.track_init(camera, poly)
                tracker.update({'handle': t['handle'], 'base': np.asarray(base).tolist()})
                trace.append({'patch_reference_frame': t['frame_id'], 'features': t['reference_features'], 'camera': camera})
            except Exception as e:
                trace.append({'patch_initialization_error': str(e), 'camera': camera})
    def observe(reason):
        B, u, method = None, mem['u'], 'landmark_registration'
        if 'handle' in tracker:
            t = api.track_update(tracker['handle'])
            trace.append({'tracking_status': t['status'], 'frame': t['frame_id'], 'reference_frame': t['reference_frame_id'], 'reason': t.get('reason')})
            if t['status'] == 'tracked':
                x = np.asarray(t['reference_inlier_world_m']); spread = np.linalg.svd(x - x.mean(axis=0), compute_uv=False) / math.sqrt(len(x))
                u = max(mem['u'], float(t['uncertainty_floor_m']), float(t['rms_m']))
                trace.append({'inliers': t['inliers'], 'matches': t['matches'], 'rms_m': t['rms_m'], 'uncertainty_m': u, 'spatial_support_m': spread.tolist()})
                if t['inliers'] >= 8 and t['inliers'] / max(1, t['matches']) >= 0.55 and t['rms_m'] <= 0.0025 and u <= 0.004 and spread[1] > 1.2 * u:
                    B = geo.transform(np.asarray(tracker['base']), t['transform_initial_world_to_current_world']); method = 'RGBD_registration'
        if B is None:
            r = review('Registration needs independent recovery. Request CURRENT named points l0,l1,l2 at the exact saved physical landmark definitions, using whichever view measures them best. Do not relabel screen corners or use stationary historical projections as observations. identity=exact only if all correspondences are unambiguous; otherwise ambiguous/unknown. Also choose patch_camera and a different usable textured interior patch polygon, or patch=null. A patch must belong solely to this same rigid object, not a finger/background. Prefer a view with enough texture; do not repeat a failed ROI blindly.', patch_fields, {'reason': reason, 'reference': mem['reference'], 'last_snapshot': mem.get('snapshot'), 'recent_diagnostics': trace[-3:]})
            p = r['parameters']; cur = samples(r, ['l0', 'l1', 'l2'])
            require(p['identity'] == 'exact' and len(cur) == 3, 'No unambiguous current landmark registration; no extrapolated transform is allowed', {'measured': list(cur), 'errors': r['measurement_errors']})
            X = np.asarray(mem['reference']['L']); Y = np.asarray([cur['l' + str(i)]['world_m'] for i in range(3)])
            u = max(mem['u'], point_uncertainty(cur)); A = X - X.mean(axis=0); C = Y - Y.mean(axis=0)
            U, singular, V = np.linalg.svd(A.T @ C)
            if np.linalg.det(V.T @ U.T) < 0: V[2, :] *= -1
            T = np.eye(4); T[:3, :3] = V.T @ U.T; T[:3, 3] = Y.mean(axis=0) - T[:3, :3] @ X.mean(axis=0)
            err = float(np.max(np.linalg.norm(geo.transform(X, T) - Y, axis=1)))
            spread = min(float(np.linalg.svd(A, compute_uv=False)[1]), float(np.linalg.svd(C, compute_uv=False)[1])) / math.sqrt(3)
            trace.append({'landmark_fit_error_m': err, 'landmark_spread_m': spread, 'uncertainty_m': u})
            require(u <= 0.004 and spread > 1.2 * u and err <= 3 * u, 'Landmark geometry cannot resolve rigid registration', trace[-1])
            B = geo.transform(np.asarray(mem['reference']['P']), T)
            start_patch(p['patch_camera'], p['patch'], B)
        s = api.state(); observation = {'B': B.tolist(), 'u': float(u), 'state': s, 'method': method, 'reason': reason}
        api.checkpoint('observation', observation)
        old = mem.get('snapshot')
        if mem.get('held', False) and old is not None:
            err = float(geo.attachment_error(old['B'], B, old['state'], s)); tol = 3 * max(u, old['u']) + 0.001
            trace.append({'continuation_attachment_error_m': err, 'tolerance_m': tol, 'reason': reason})
            require(err <= tol, 'Object motion no longer agrees with actual hand motion; retaining close and stopping', trace[-1])
        mem['snapshot'] = observation; save()
        return B, float(u), s
    def move(target, quaternion, gripper, label, reserve=24):
        target = np.asarray(target, dtype=float); mem['intent'] = {'label': label, 'pad_target': target.tolist()}; save()
        for cap in [26, 12]:
            before = api.state(); budget = before['budgets']; n = min(cap, budget['jev_remaining'] - reserve, budget['native_steps_remaining'] // 3 - reserve)
            require(n > 0, 'Insufficient control reserve for ' + label, budget)
            old = float(np.linalg.norm(target - geo.pad_position(before)))
            r = api.drive(target.tolist(), quaternion, gripper, questions, features={'phase': mem['phase'], 'label': label, 'held_evidence': mem.get('held', False), 'historical_object_observation': mem.get('snapshot')}, max_calls=int(n), tool_point='pad_center', translation_limit=0.02, rotation_limit=0.08, steps=3, position_tolerance=0.0025, rotation_tolerance=0.035)
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
            require(r['status'] in ['reached', 'moved'] and r['choices']['gripper'] == gripper, 'Transition control failed or Jev did not deliver requested gripper choice', r)
            require(float(np.linalg.norm(np.asarray(geo.pad_position(api.state())) - target)) < 0.008, 'Unexpected hand displacement at a contact transition')
        trace.append({'transition': gripper, 'frame': api.state()['frame_id'], 'actual_gripper_qpos_m': api.state()['gripper_qpos_m']}); save()
    def guard(label, target, gripper):
        fields = {'external': ['observed_obstacle', 'none_observed', 'unknown'], 'visibility': ['observed', 'partial_unobserved', 'self_occluded'], 'action': ['local_supported', 'view_up_supported', 'unsupported']}
        for attempt in range(2):
            r = review('Assess only the proposed bounded local action, not a complete future route. external describes an EXTERNAL obstruction to this action: observed_obstacle blocks it, none_observed is not certified clearance, unknown means external obstruction cannot be distinguished. visibility separately describes visible local space, unobserved space, or occlusion by our own robot/item. Self-occlusion alone is not an external obstacle. action=local_supported requires a justified local path from current visible surfaces, measured own envelope and task geometry, without requiring complete future-corridor visibility. For approach, check the fingers can descend outside the package, not through it. Reject inconsistent object identity or an observed displaced target. view_up_supported means a 0.035 m vertical upward view change is itself locally supported AND likely to expose the missing evidence. Otherwise unsupported. Do not require retention before a designated observation-producing test lift.', fields, {'label': label, 'pad_target': np.asarray(target).tolist(), 'gripper': gripper, 'reference': mem['reference'], 'snapshot': mem.get('snapshot')})
            p = r['parameters']
            if p['external'] == 'none_observed' and p['action'] == 'local_supported': return
            if p['action'] == 'view_up_supported' and attempt == 0 and mem.get('views', 0) < 2:
                mem['views'] = mem.get('views', 0) + 1; s = api.state()
                move(np.asarray(geo.pad_position(s)) + [0, 0, 0.035], s['tcp_quaternion_xyzw'], 'keep', 'observation_view_change')
                observe('independent observation after view change')
            else: require(False, 'No justified local action: ' + label, p)
        require(False, 'View change did not resolve the local evidence gap')
    def normal(B):
        n = mem['reference']['normal_sign'] * np.cross(B[1] - B[0], B[3] - B[0])
        return n / np.linalg.norm(n)
    try:
        if any(x['key'] == 'reference' for x in api.recall()):
            ref = api.recall('reference')['value']; old = api.recall('progress')['value']
            mem.update({'reference': ref, 'u': ref['u'], 'phase': old['phase'], 'held': False, 'snapshot': old['snapshot']})
            r = review('Resume this same physical episode, without replaying actions. reference_valid=yes means the same rigid object and saved dimension definitions remain applicable, and the bowl remains at the measured reference location. For on_source_unheld also verify the package is still flat on the saved support. mode distinguishes a visibly unheld supported source, an item possibly between the fingers, and an object already released in the destination. Never infer held from a previous command. unknown is appropriate if not distinguishable. Do not reopen a candidate held object.', {'reference_valid': ['yes', 'no', 'unknown'], 'mode': ['on_source_unheld', 'candidate_between_fingers', 'released_in_destination', 'unknown']}, {'reference': ref, 'historical_progress': old})
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
        ref = mem['reference']; q, rim = ref['q'], ref['rim']; B, u, s = observe('current object reference before phase selection')
        if mode != 'released_in_destination':
            if mode == 'on_source_unheld':
                mem['phase'] = 'approach'
                for stage in ['high_alignment', 'source_hover', 'grasp_descent']:
                    center = B.mean(axis=0); pad = np.asarray(geo.pad_position(s))
                    z = max(pad[2], center[2] + 0.08) if stage == 'high_alignment' else center[2] + 0.05
                    if stage == 'grasp_descent':
                        c = np.asarray(ref['table_plane']); table_z = -(c[3] + np.dot(c[:2], center[:2])) / c[2]; z = max(center[2] - ref['height'] / 2, table_z - ref['fmin'] + 2 * u)
                        axis = geo.rotation(q)[:, ref['opening_axis']]; width = float(np.max(B @ axis) - np.min(B @ axis))
                        values = {'grasp_pad_z': float(z), 'table_z': float(table_z), 'top_z': float(center[2]), 'finger_low_relative_pad': ref['fmin'], 'projected_width': width, 'outer_pad_span': ref['outer_pad_span'], 'u': u}
                        trace.append(values)
                        require(abs(center[2] - table_z - ref['height']) < 4 * u and z - ref['pad_half_z'] < center[2] - u and width + 4 * u < ref['outer_pad_span'], 'No supported finger-envelope/side-overlap grasp', values)
                    target = [float(center[0]), float(center[1]), float(z)]; guard(stage, target, 'open'); move(target, q, 'open', stage); B, u, s = observe(stage + ' outcome')
            r = review('Before closure, are the actual open or partially closed fingers beside opposite source sides, with no observed table/neighbor intrusion? bracketing=observed is a visual fact, not inferred from the target pose or outer pad span. For a repaired already closed hand, accept observed fingers around this same item. Otherwise unknown/not_bracketed. Only observation is requested.', {'bracketing': ['observed', 'not_bracketed', 'unknown']}, {'reference': ref, 'current': mem['snapshot']})
            require(r['parameters']['bracketing'] == 'observed', 'Actual finger bracketing was not observed')
            mem['phase'] = 'closing'; save(); pulse('close', 5, 24); B0, u0, s0 = observe('actual closure outcome and pre-lift reference')
            r = review('After actual closure, candidate=present means this same source is visibly between the fingers; it does NOT claim retention. probe=supported means a bounded upward test lift of at most 0.035 m is justified by current local evidence, without requiring the retention result in advance. Reject visible external obstruction; own-finger occlusion alone does not establish loss. unknown if there is neither an identifiable candidate nor a justified probe.', {'candidate': ['present', 'absent', 'unknown'], 'probe': ['supported', 'unsupported', 'unknown']}, {'reference': ref, 'closure_observation': mem['snapshot']})
            require(r['parameters']['candidate'] == 'present' and r['parameters']['probe'] == 'supported', 'No supported retention-measurement lift')
            lift = max(0.022, 8 * u0); require(lift <= 0.035, 'Registration uncertainty is too large for the bounded lift test', {'u': u0, 'lift': lift})
            mem['phase'] = 'retention_test'; save(); move(np.asarray(geo.pad_position(s0)) + [0, 0, lift], q, 'keep', 'retention_measurement_lift'); B, u, s = observe('observed lift outcome')
            hand = float(np.linalg.norm(np.asarray(geo.pad_position(s)) - geo.pad_position(s0))); obj = float(np.linalg.norm(B.mean(axis=0) - B0.mean(axis=0))); err = float(geo.attachment_error(B0, B, s0, s)); tol = 3 * max(u0, u) + 0.001
            values = {'actual_hand_motion_m': hand, 'observed_object_motion_m': obj, 'attachment_error_m': err, 'tolerance_m': tol, 'observed_object_rise_m': float(B.mean(axis=0)[2] - B0.mean(axis=0)[2])}; trace.append(values)
            require(hand > 4 * max(u0, u) + 0.006 and obj > hand - tol and err <= tol and values['observed_object_rise_m'] > 0.5 * hand, 'Retention test did not establish a retained object; no transfer or reopening', values)
            mem['held'] = True; mem['phase'] = 'retained'; save()
            for stage in ['lift_clear', 'transfer', 'lower_to_release']:
                pad = np.asarray(geo.pad_position(s)); bottom = B - ref['height'] * normal(B); down = max(float(pad[2] - np.min(bottom[:, 2])), -ref['fmin']); margin = 3 * u + 0.002
                z = rim['z'] + down + margin if stage == 'lower_to_release' else max(float(pad[2]), rim['z'] + down + 0.07)
                xy = pad[:2] if stage == 'lift_clear' else np.asarray(rim['xy']) - (B.mean(axis=0)[:2] - pad[:2]); target = [float(xy[0]), float(xy[1]), float(z)]
                mem['phase'] = stage; guard(stage, target, 'keep'); move(target, q, 'keep', stage); B, u, s = observe(stage + ' actual retained-object outcome')
            bottom = B - ref['height'] * normal(B); radius = float(np.max(np.linalg.norm(np.concatenate([B[:, :2], bottom[:, :2]]) - rim['xy'], axis=1))); pad = np.asarray(geo.pad_position(s))
            values = {'object_radial_extent_m': radius, 'rim_radius_m': rim['radius'], 'lowest_object_z': float(np.min(bottom[:, 2])), 'finger_low_z': float(pad[2] + ref['fmin']), 'rim_z': rim['z'], 'drop_to_floor_m': float(np.min(bottom[:, 2]) - ref['floor_z'])}; trace.append(values)
            require(radius < rim['radius'] - u and values['finger_low_z'] > rim['z'] + u and values['lowest_object_z'] > rim['z'] - u and values['drop_to_floor_m'] < 0.12, 'Actual release geometry is not supported', values)
            mem['phase'] = 'release_pending'; mem['held'] = False; save(); pulse('open', 5, 12); mem['phase'] = 'released'; save()
            s = api.state(); move(np.asarray(geo.pad_position(s)) + [0, 0, 0.07], s['tcp_quaternion_xyzw'], 'keep', 'post_release_view_and_separation_on_reverse_vertical_path', 4)
        mem['held'] = False; mem['phase'] = 'verification'; B, u, s = observe('new post-release view')
        stable = False
        for attempt in range(2):
            previous, previous_u = B.copy(), u; pulse('keep', 3); B, u, s = observe('independent post-release settling measurement')
            displacement = float(np.max(np.linalg.norm(B - previous, axis=1))); stability_tolerance = max(0.003, 3 * max(u, previous_u))
            trace.append({'post_release_motion_m': displacement, 'stability_tolerance_m': stability_tolerance})
            if displacement <= stability_tolerance: stable = True; break
        require(stable, 'Object has not observably settled within the bounded verification interval', trace[-1])
        r = review('Assess the CURRENT final scene against the runtime instruction. identity=same only for the intended object. relation=inside requires the actual released object supported in the bowl interior, not held, balanced on the rim, outside, or merely projected over it. target_stationary=yes requires visible consistency with the measured bowl reference; otherwise no/unknown. This is a fresh object-effect assessment, not acceptance of commanded poses. If target_stationary is no or unknown, request current named inner-lip points k0..k5 so geometry can be refreshed. Report unknown honestly when the relation is hidden.', {'identity': ['same', 'ambiguous', 'unknown'], 'relation': ['inside', 'on_rim', 'outside', 'held', 'unknown'], 'target_stationary': ['yes', 'no', 'unknown']}, {'task': task, 'reference': ref, 'current_object_observation': mem['snapshot'], 'stability_evidence': trace[-1]})
        if r['parameters']['target_stationary'] != 'yes': rim = rim_measure(r)
        bottom = B - ref['height'] * normal(B); radial = float(np.max(np.linalg.norm(np.concatenate([B[:, :2], bottom[:, :2]]) - rim['xy'], axis=1))); separated = float(geo.pad_position(s)[2] + ref['fmin'] - np.max(B[:, 2]))
        values = {'final_radial_extent_m': radial, 'inner_rim_radius_m': rim['radius'], 'lowest_object_z': float(np.min(bottom[:, 2])), 'rim_z': rim['z'], 'hand_object_vertical_separation_m': separated, 'uncertainty_m': u}; trace.append(values)
        require(r['parameters']['identity'] == 'same' and r['parameters']['relation'] == 'inside' and radial <= rim['radius'] + 2 * u and np.min(bottom[:, 2]) < rim['z'] - u and separated > 3 * u, 'Final containment or independent released support is unresolved', values)
        mem['phase'] = 'completion_proposed'; save()
        return {'completion_proposed': True, 'evidence': trace, 'limitations': ['Uncertainty is heuristic, not a calibrated confidence bound.', 'Observed local feasibility is not a swept-volume certificate.', 'This proposal is not the isolated native evaluator result.']}
    except Exception as e:
        trace.append({'stopped': str(e), 'phase': mem.get('phase', 'initializing'), 'held_evidence': mem.get('held', False)})
        return {'completion_proposed': False, 'evidence': trace}

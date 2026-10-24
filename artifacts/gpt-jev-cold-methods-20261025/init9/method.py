def main(api):
    task = 'could you put the cream cheese into the bowl'
    E, P, D, tracker = [], {}, {}, {'handle': None, 'basis': np.eye(4)}
    pixel = {'type': 'array', 'items': {'type': 'number', 'minimum': 0, 'maximum': 767}, 'minItems': 2, 'maxItems': 2}
    polygon = {'type': ['array', 'null'], 'items': pixel, 'minItems': 3, 'maxItems': 16}
    camera = ['agentview', 'robot0_eye_in_hand']
    Q = {}
    for axis in ['x', 'y', 'z', 'rx', 'ry', 'rz']:
        Q[axis] = {'type': 'choice', 'instructions': 'For the ' + axis + ' world pose component, read state.processed_features.axes.' + axis + '.goal_relation. Follow increase, decrease, or within_tolerance; do not infer object contact from the target.', 'criteria': {'negative': 'decrease: negative world component', 'hold': 'within_tolerance: no update', 'positive': 'increase: positive world component'}}
    Q['gripper'] = {'type': 'choice', 'instructions': 'Read state.processed_features.objective.gripper and deliver that exact requested gripper operation.', 'criteria': {'open': 'objective is open', 'close': 'objective is close', 'keep': 'objective is keep; preserve the current gripper command'}}
    gate_fields = {'external': ['present', 'not_observed', 'unknown'], 'visibility': ['visible', 'self_occluded', 'unobserved'], 'local': ['supported', 'unsupported', 'unknown'], 'up_view': ['supported', 'unsupported', 'unknown']}
    def log(x):
        E.append(x)
        api.note(str(x))
    def save():
        api.checkpoint('processing_progress', D)
    def review(question, context, fields, reserve=2):
        if api.state()['budgets']['gpt_remaining'] <= reserve:
            raise RuntimeError('Review reserve reached; stopping before an unverified action')
        r = api.review(question, context=context, fields=fields)
        log({'review_frame': r['frame_id'], 'measurement_errors': r['measurement_errors'], 'explanation': r['explanation']})
        if r['status'] == 'stop':
            raise RuntimeError('Observation review requested stop')
        return r
    def valid(r, name, kind='points'):
        return name in r[kind] and not any(e['name'] == name for e in r['measurement_errors'])
    def measured(r, name, kind='points'):
        if not valid(r, name, kind):
            raise RuntimeError('Missing current ' + kind + ' measurement: ' + name)
        return r[kind][name]
    def move(target, quat, grip, label, calls=18, reserve=24, tolerance=0.005):
        start = np.array(api.state()['tcp_position_world_m'])
        D['pending'] = {'label': label, 'target_pad_world_m': list(target), 'gripper': grip, 'frame_id': api.state()['frame_id']}
        save()
        for attempt in range(2):
            count = min(calls if attempt == 0 else 8, int(api.state()['budgets']['jev_remaining']) - reserve)
            if count < 1 or api.state()['budgets']['native_steps_remaining'] < 3 * count + 6:
                raise RuntimeError('Insufficient reserved control resources for ' + label)
            receipt = api.drive(list(target), list(quat), grip, Q, features={'phase': label, 'measurements': D.get('metrics', {})}, tool_point='pad_center', max_calls=count, translation_limit=0.02, rotation_limit=0.08, steps=3, position_tolerance=tolerance, rotation_tolerance=0.04)
            log({'motion': label, 'status': receipt['status'], 'position_error_m': receipt['position_error_m'], 'rotation_error_rad': receipt['rotation_error_rad'], 'lease_calls': receipt['lease_calls']})
            if receipt['status'] == 'reached':
                D['pending'] = None
                save()
                return
            if receipt['status'] == 'stalled':
                raise RuntimeError('Stalled at ' + label + '; no repeated contact push')
            if receipt['status'] != 'lease_exhausted' or np.linalg.norm(np.array(api.state()['tcp_position_world_m']) - start) < 0.004:
                raise RuntimeError('No useful pose progress at ' + label)
        raise RuntimeError('Bounded pose lease exhausted at ' + label)
    def hold(grip, label):
        s = api.state()
        if s['budgets']['jev_remaining'] < 1 or s['budgets']['native_steps_remaining'] < 3:
            raise RuntimeError('No resources for ' + label)
        r = api.control(geo.pad_position(s).tolist(), s['tcp_quaternion_xyzw'], grip, Q, features={'phase': label}, tool_point='pad_center', translation_limit=0.005, rotation_limit=0.04, steps=3, position_tolerance=0.003, rotation_tolerance=0.04)
        log({'contact_or_wait': label, 'status': r['status'], 'choices': r['choices'], 'frame_id': r['frame_id']})
        if r['status'] not in ['reached', 'moved']:
            raise RuntimeError('Explicit control failure during ' + label)
    def rim(r):
        pts = [r['points']['r' + str(i)]['world_m'] for i in range(6) if valid(r, 'r' + str(i))]
        if len(pts) < 5:
            raise RuntimeError('Fewer than five usable distributed inner-rim measurements')
        f, c = geo.plane(pts), geo.circle_xy(pts)
        log({'rim_plane': f, 'rim_circle': c})
        if f['coefficients'][2] < 0.97 or f['rms_m'] > 0.003 or c['max_radial_error_m'] > 0.004 or c['largest_angular_gap_rad'] > 2.5:
            raise RuntimeError('Round horizontal opening model not supported by rim measurements')
        return {'xy': c['center_xy_m'], 'radius': c['radius_m'], 'z': float(np.mean(np.array(pts)[:, 2])), 'u': max(0.003, 3 * f['rms_m'], c['max_radial_error_m']), 'points': pts, 'frame_id': r['frame_id']}
    def patch(cam, poly, basis, basis_u=0.0):
        if poly is None:
            return
        try:
            r = api.track_init(cam, poly)
            tracker.update({'handle': r['handle'], 'basis': np.array(basis), 'basis_u': float(basis_u)})
            log({'patch_reference_frame': r['frame_id'], 'reference_features': r['reference_features'], 'camera': cam})
        except Exception as exc:
            log({'patch_initialization_failed': str(exc)})
    def observe(label):
        names = ['a0', 'a1', 'a2']
        reference, definitions = list(P['landmarks']), list(P['definitions'])
        if 'recovery_landmarks' in P:
            names += ['b0', 'b1', 'b2']
            reference += P['recovery_landmarks']
            definitions += P['recovery_definitions']
        A = np.array(reference)
        for attempt in range(2):
            if tracker['handle'] is not None:
                t = api.track_update(tracker['handle'])
                if t['status'] == 'tracked':
                    relative_u = max(0.0015, 3 * t['rms_m'], t['uncertainty_floor_m'])
                    u = math.sqrt(relative_u ** 2 + tracker.get('basis_u', 0.0) ** 2)
                    log({'registration_uncertainty': 'RSS propagation of heuristic reference and relative errors, not a certified bound', 'reference_m': tracker.get('basis_u', 0.0), 'relative_m': relative_u, 'combined_m': u})
                    log({'tracking': label, 'frame_id': t['frame_id'], 'reference_frame_id': t['reference_frame_id'], 'inliers': t['inliers'], 'matches': t['matches'], 'uncertainty_m': u})
                    if t['inliers'] >= 8 and t['inliers'] / max(1, t['matches']) >= 0.6 and u <= 0.004 and float(np.max(np.array(t['inlier_spread_m']))) > 3 * u:
                        return np.array(t['transform_initial_world_to_current_world']) @ tracker['basis'], u
                else:
                    log({'registration_unknown': label, 'reason': t['reason'], 'frame_id': t['frame_id']})
            if api.state()['frame_id'] == P['frame_id']:
                cached = P.get('patch_selection')
                if tracker['handle'] is None and cached is not None and cached['frame_id'] == P['frame_id']:
                    patch(cached['camera'], cached['polygon'], np.eye(4))
                if tracker['handle'] is None:
                    fields = {'identity': ['confirmed', 'ambiguous', 'unknown'], 'patch_camera': camera, 'patch_polygon': polygon, 'definitions': {'type': 'array', 'items': {'type': 'string', 'maxLength': 350}, 'minItems': 3, 'maxItems': 3}}
                    r = review('Recreate the lost tracker reference before motion. The physical frame still equals the saved reference frame, so its measured geometry remains valid. identity confirmed means the selected patch and requested features belong unambiguously to the same item. patch_camera and patch_polygon select a textured interior RGB-D patch on that item, not background; null polygon if unavailable. Also request b0,b1,b2 at three distinct, widely distributed, noncollinear PRINTED features away from the perimeter, to provide an independent correspondence fallback if fingers hide the corners. definitions gives their concise persistent physical identities in that order, naming specific print marks rather than screen positions. If existing_recovery_definitions are supplied, retain exactly those identities. Missing or ambiguous features must be reported, not guessed; use unavailable in their definitions. This is not a grasp assessment.', {'item': P['item'], 'reference_frame_id': P['frame_id'], 'existing_recovery_definitions': P.get('recovery_definitions'), 'existing_recovery_points': P.get('recovery_landmarks')}, fields)
                    p = r['parameters']
                    if p['identity'] == 'confirmed':
                        P['patch_selection'] = {'camera': p['patch_camera'], 'polygon': p['patch_polygon'], 'frame_id': r['frame_id']}
                        if all(valid(r, 'b' + str(i)) for i in range(3)):
                            B = np.array([r['points']['b' + str(i)]['world_m'] for i in range(3)])
                            f = geo.plane(P['corners'])
                            error = float(np.max(np.abs(B @ np.array(f['coefficients'][:3]) + f['coefficients'][3])))
                            spread = float(np.linalg.svd(B - np.mean(B, axis=0), compute_uv=False)[1])
                            log({'printed_reference_plane_error_m': error, 'second_spread_m': spread, 'frame_id': r['frame_id']})
                            if error <= 3 * P['u'] and spread > 3 * P['u']:
                                P['recovery_landmarks'], P['recovery_definitions'] = B.tolist(), p['definitions']
                                P['recovery_reference_frame_id'] = r['frame_id']
                        api.checkpoint('processing_plan', P)
                        patch(p['patch_camera'], p['patch_polygon'], np.eye(4))
                return np.eye(4), P['u']
            fields = {'identity': ['confirmed', 'ambiguous', 'unknown'], 'patch_camera': camera, 'patch_polygon': polygon, 'up_view': ['supported', 'unsupported', 'unknown']}
            r = review('Recover CURRENT source registration for ' + label + '. Request whichever of the saved named landmarks are genuinely identifiable now; hidden landmarks must be omitted, not guessed. identity confirmed means every returned landmark has exactly its saved physical identity, with at least two usable correspondences. definitions and reference_points correspond to names in order. Do not redefine camera-relative corners, treat stationary projections as detections, or infer item motion from hand motion. Also request region current_top as a spatially broad, two-dimensional rectangle wholly on the visible INTERIOR of the same planar package top, with explicit camera, box, stride=4; exclude fingers, edges and background. Geometric homogeneity means the same physical plane, NOT uniform color: include printed texture rather than selecting only a narrow blank strip. Choose the largest usable interior rectangle in either current view without requiring hidden corners. This supplies independent surface-orientation evidence to complement the saved landmark correspondences; do not guess a missing region. patch_camera and patch_polygon select a textured interior patch on this same item, or null polygon. The program anchors it only after independent registration. up_view supported means a 0.015 m upward kept-grip motion is locally justified and would genuinely reveal missing correspondences, not merely preserve the same self-occlusion. It is not a clearance certificate.', {'item': P['item'], 'names': names, 'definitions': definitions, 'reference_points': A.tolist(), 'reference_frame_id': P['frame_id'], 'phase': label}, fields, reserve=1)
            p = r['parameters']
            ids = [i for i, name in enumerate(names) if valid(r, name)]
            if p['identity'] == 'confirmed' and len(ids) >= 2:
                X = A[ids]
                B = np.array([r['points'][names[i]]['world_m'] for i in ids])
                ac, bc = np.mean(X, axis=0), np.mean(B, axis=0)
                R, plane_rotation, plane_evidence, f = None, None, None, None
                u = max(P['u'], 0.002)
                pairs = [(i, j) for i in range(len(ids)) for j in range(i)]
                pair_error = max(abs(float(np.linalg.norm(X[i] - X[j]) - np.linalg.norm(B[i] - B[j]))) for i, j in pairs)
                reference_spread = float(np.linalg.svd(X - ac, compute_uv=False)[1])
                current_spread = float(np.linalg.svd(B - bc, compute_uv=False)[1])
                spread = min(reference_spread, current_spread)
                D['registration_samples'] = {'frame_id': r['frame_id'], 'reference_frame_id': P['frame_id'], 'names': [names[i] for i in ids], 'definitions': [definitions[i] for i in ids], 'reference_points': X.tolist(), 'current_points': B.tolist(), 'identity': p['identity'], 'pair_distance_error_m': pair_error, 'reference_second_spread_m': reference_spread, 'current_second_spread_m': current_spread, 'source': 'Current named RGB-D measurements; historical after subsequent motion.'}
                save()
                if valid(r, 'current_top', 'regions'):
                    try:
                        f = geo.plane(r['regions']['current_top']['world_m'])
                    except Exception as exc:
                        log({'current_plane_fit_rejected': str(exc), 'frame_id': r['frame_id']})
                if f is not None:
                    n0 = np.array(geo.plane(P['corners'])['coefficients'][:3])
                    n1 = np.array(f['coefficients'][:3])
                    plane_error = float(np.max(np.abs(B @ n1 + f['coefficients'][3])))
                    pair = max(pairs, key=lambda ij: float(np.linalg.norm(X[ij[0]] - X[ij[1]])))
                    v0, v1 = X[pair[0]] - X[pair[1]], B[pair[0]] - B[pair[1]]
                    v0, v1 = v0 - n0 * np.dot(v0, n0), v1 - n1 * np.dot(v1, n1)
                    lengths = [float(np.linalg.norm(v0)), float(np.linalg.norm(v1))]
                    plane_evidence = {'fit': f, 'landmark_plane_error_m': plane_error, 'ordered_baselines_m': lengths}
                    if 3 * f['rms_m'] <= u and plane_error <= 2 * u and pair_error <= 2 * u and min(lengths) > 8 * u and min(f['in_plane_spread_m']) > 2 * u:
                        e0, e1 = v0 / lengths[0], v1 / lengths[1]
                        plane_rotation = np.column_stack([e1, np.cross(n1, e1), n1]) @ np.column_stack([e0, np.cross(n0, e0), n0]).T
                if len(ids) >= 3 and spread > 2 * u and pair_error <= 2 * u:
                    U, singular, V = np.linalg.svd((X - ac).T @ (B - bc))
                    J = np.eye(3)
                    J[2, 2] = np.linalg.det(V.T @ U.T)
                    candidate = V.T @ J @ U.T
                    corroborated = False
                    if f is not None:
                        reach = float(np.max(np.linalg.norm(np.array(P['corners']) - ac, axis=1)))
                        surface_spread = float(min(f['in_plane_spread_m']))
                        normal_effect = reach * float(np.linalg.norm(candidate @ n0 - n1))
                        fit_effect = 3 * f['rms_m'] * max(1.0, reach / max(0.000001, surface_spread))
                        corroborated = bool(surface_spread > u and 3 * f['rms_m'] <= u and plane_error <= u and fit_effect <= u and normal_effect <= 2 * u + fit_effect)
                        plane_evidence.update({'reference_extent_from_observed_centroid_m': reach, 'normal_disagreement_over_extent_m': normal_effect, 'residual_extrapolation_over_extent_m': fit_effect, 'corroborates_landmark_orientation': corroborated, 'interpretation': 'Independent surface/landmark consistency; residual extrapolation is heuristic, not a calibrated uncertainty bound.'})
                    if spread > 3 * u or corroborated:
                        R = candidate
                if R is None:
                    R = plane_rotation
                D['registration_samples']['plane_evidence'] = plane_evidence
                save()
                log({'registration_support': {'pair_distance_error_m': pair_error, 'reference_second_spread_m': reference_spread, 'current_second_spread_m': current_spread, 'measurement_floor_m': u, 'plane_evidence': plane_evidence}, 'frame_id': r['frame_id']})
                if R is not None:
                    T = np.eye(4)
                    T[:3, :3], T[:3, 3] = R, bc - R @ ac
                    error = float(np.max(np.linalg.norm(geo.transform(X, T) - B, axis=1)))
                    u = max(u, error)
                    log({'registration_landmarks': [names[i] for i in ids], 'landmark_registration_error_m': error, 'second_spread_m': spread, 'plane_evidence': plane_evidence, 'uncertainty_m': u, 'uncertainty_kind': 'RGB-D and correspondence heuristic, not a certified pose bound', 'frame_id': r['frame_id']})
                    if error <= 0.004 and u <= 0.004:
                        D['last_registration'] = {'T': T.tolist(), 'u': u, 'frame_id': r['frame_id'], 'names': [names[i] for i in ids], 'current_points': B.tolist()}
                        save()
                        patch(p['patch_camera'], p['patch_polygon'], T, u)
                        return T, u
                else:
                    log({'registration_rejected': 'Insufficient independent orientation evidence', 'landmark_names': [names[i] for i in ids], 'second_spread_m': spread, 'plane_evidence': plane_evidence})
            if attempt == 0 and p['up_view'] == 'supported':
                s = api.state()
                move((geo.pad_position(s) + [0, 0, 0.015]).tolist(), s['tcp_quaternion_xyzw'], 'keep', 'registration view recovery', 8)
            else:
                raise RuntimeError('Unknown registration: no unambiguous current correspondences or justified new view')
        raise RuntimeError('Registration recovery bound reached')
    def geometry(T):
        top = geo.transform(P['corners'], T)
        bottom = geo.transform(np.array(P['corners']) - [0, 0, P['height']], T)
        return top, bottom, np.mean(np.concatenate([top, bottom]), axis=0)
    def pinch_geometry(top, bottom, quat, u, s, require=True):
        own, R = s['own_geometry'], geo.rotation(quat)
        bounds = np.array([[x, y, z] for x in [own['finger_low_offset_tool_m'][0], own['finger_high_offset_tool_m'][0]] for y in [own['finger_low_offset_tool_m'][1], own['finger_high_offset_tool_m'][1]] for z in [own['finger_low_offset_tool_m'][2], own['finger_high_offset_tool_m'][2]]])
        offsets = (bounds - np.array(own['pad_center_in_tool_m'])) @ R.T
        low = float(np.min(offsets[:, 2]))
        extent = np.array(own['pad_extent_in_tool_m'])
        half = float(0.5 * (abs(R[2, 2]) * extent[2] - abs(R[2, 0]) * extent[0] - abs(R[2, 1]) * extent[1]))
        coeff = np.array(P['support_plane'])
        xy = np.mean(top[:, :2], axis=0) + offsets[:, :2]
        support_z = -(xy @ coeff[:2] + coeff[3]) / coeff[2]
        bottom_support_z = -(bottom[:, :2] @ coeff[:2] + coeff[3]) / coeff[2]
        support_error = float(np.max(np.abs(bottom[:, 2] - bottom_support_z)))
        tolerance, clearance = 0.002, 0.5 * P['u']
        overlap = 0.1 * min(P['height'], max(0.0, 2 * half))
        lower = max(float(np.max(support_z - offsets[:, 2])) + P['u'] + tolerance + clearance, float(np.max(bottom[:, 2])) - half + u + tolerance + overlap)
        upper = float(np.min(top[:, 2])) + half - u - tolerance - overlap
        inset = float(np.mean(top[:, 2])) - 0.5 * (lower + upper)
        feasible = bool(half > 0 and upper >= lower and support_error <= u + P['u'] + tolerance)
        D['metrics'] = {'item_width_along_tool_y_m': float(np.ptp(top @ R[:, 1])), 'pad_extent_in_tool_m': own['pad_extent_in_tool_m'], 'gripper_qpos_m': s['gripper_qpos_m'], 'grasp_inset_m': inset, 'lowest_finger_relative_pad_z_m': low, 'uncertainty_m': u, 'pad_common_vertical_half_m': half, 'admissible_pad_center_z_m': [lower, upper], 'minimum_side_overlap_m': overlap, 'support_clearance_m': clearance, 'engagement_tolerance_m': tolerance, 'inferred_bottom_support_residual_m': support_error, 'side_overlap_feasible': feasible, 'aperture_note': 'Finite pads may overlap the sides with pad_center above the top. Opening geometry is not contact evidence; actual visible side slots and a measured retention lift are required.'}
        D['quat'], D['finger_low'] = quat, low
        save()
        log({'finite_pad_geometry': D['metrics'], 'frame_id': s['frame_id'], 'contact_gate_enforced': require})
        if require and not feasible:
            raise RuntimeError('No supported finite-pad side-contact interval: ' + str(D['metrics']))
        return inset, low
    def engage(T, u):
        fields = {'external': ['present', 'not_observed', 'unknown'], 'visibility': ['visible', 'self_occluded', 'unobserved'], 'close_trial': ['supported', 'unsupported', 'unknown'], 'adjust_trial': ['supported', 'unsupported', 'unknown']}
        permission, stalled = None, False
        for trial in range(4):
            if trial > 0:
                T, u = observe('current item after bounded open-pad engagement adjustment')
            top, bottom, center = geometry(T)
            s = api.state()
            quat = s['tcp_quaternion_xyzw']
            pinch_geometry(top, bottom, quat, u, s, require=False)
            m, pad = D['metrics'], geo.pad_position(s)
            lo, hi = m['admissible_pad_center_z_m']
            tol = m['engagement_tolerance_m']
            lo, hi = lo - tol + 0.0005, hi + tol - 0.0005
            edge = np.linalg.norm(np.roll(top, -1, axis=0) - top, axis=1)
            allowance = 0.5 * float(np.min(edge)) - u - 0.5 * s['own_geometry']['pad_extent_in_tool_m'][0]
            offset = float(np.linalg.norm(pad[:2] - np.mean(top[:, :2], axis=0)))
            support_ok = m['inferred_bottom_support_residual_m'] <= u + P['u'] + tol
            actual = bool(lo <= pad[2] <= hi and offset <= allowance and support_ok and m['pad_common_vertical_half_m'] > 0)
            target = np.mean(top, axis=0)
            target[2] = 0.5 * (lo + hi)
            info = {'actual_pad_world_m': pad.tolist(), 'actual_contact_height_interval_m': [lo, hi], 'centering_error_m': offset, 'centering_allowance_m': allowance, 'actual_geometry_supports_trial': actual, 'adjustment_target_pad_world_m': target.tolist(), 'finite_pad_geometry': m}
            log({'engagement_observation': info, 'frame_id': s['frame_id']})
            if hi < lo or allowance <= 0 or not support_ok:
                raise RuntimeError('No supported actual finite-pad engagement interval: ' + str(info))
            if trial == 0 or actual:
                r = review('Assess CURRENT engagement of the intended item. external present means an observed external obstruction to the proposed local closure or adjustment; not_observed means none seen, not certified clearance; unknown means unresolved evidence. visibility distinguishes visible surroundings, robot/item self_occlusion, and unobserved external space. close_trial supported means current visible item/jaw placement together with the supplied actual finite-pad geometry justifies closing in place as a retention experiment. It does not mean grasp or contact is established. Do not require hidden perimeter corners or the later transfer corridor. Reject observed wrong-side, top-face-only, table, or neighboring-object engagement. adjust_trial supported means a bounded open-jaw adjustment to the supplied target is locally supported by the current side slots and support geometry. Self-occlusion alone is not an external obstruction. Return unknown when the missing evidence actually prevents this local experiment.', {'item': P['item'], 'phase': 'engagement', 'measurements': info}, fields)
                permission = r['parameters']
            if permission['external'] == 'present':
                raise RuntimeError('Observed obstruction during engagement')
            if actual and permission['close_trial'] == 'supported':
                D['pending'] = None
                D['engagement'] = {'frame_id': s['frame_id'], 'measurements': info, 'visual_trial_support': permission}
                save()
                return
            if stalled:
                raise RuntimeError('Engagement stalled without sufficient actual contact geometry; no repeated push')
            if trial == 3 or permission['adjust_trial'] != 'supported':
                raise RuntimeError('Actual engagement evidence incomplete: ' + str(info))
            count = min(12, int(s['budgets']['jev_remaining']) - 72)
            if count < 1 or s['budgets']['native_steps_remaining'] < 3 * count + 72:
                raise RuntimeError('Engagement stopped to preserve retention, transfer and release resources')
            D['pending'] = {'label': 'guarded finite-pad side engagement', 'target_pad_world_m': target.tolist(), 'gripper': 'keep', 'frame_id': s['frame_id']}
            save()
            receipt = api.drive(target.tolist(), quat, 'keep', Q, features={'phase': 'actual finite-pad engagement', 'measurements': info}, tool_point='pad_center', max_calls=count, translation_limit=0.02, rotation_limit=0.04, steps=3, position_tolerance=0.002, rotation_tolerance=0.04)
            log({'engagement_motion_status': receipt['status'], 'position_error_m': receipt['position_error_m'], 'rotation_error_rad': receipt['rotation_error_rad'], 'lease_calls': receipt['lease_calls']})
            if receipt['status'] not in ['reached', 'lease_exhausted', 'stalled']:
                raise RuntimeError('Explicit engagement controller failure')
            stalled = receipt['status'] == 'stalled'
        raise RuntimeError('Engagement observation/action bound exhausted')
    def remember(T, u):
        D['attachment'] = {'T': T.tolist(), 'u': u, 'state': api.state()}
        save()
    def check_hold(label):
        old = D['attachment']
        current = api.state()
        if current['frame_id'] == old['state']['frame_id']:
            log({'attachment_reference_reuse': label, 'measurement_frame_id': old['state']['frame_id'], 'current_frame_id': current['frame_id'], 'uncertainty_m': old['u'], 'new_retention_test': False, 'reason': 'No physical step since the saved measured attachment; restart alone does not invalidate it.'})
            return np.array(old['T']), old['u']
        T, u = observe(label)
        err = geo.attachment_error(geo.transform(P['landmarks'], old['T']), geo.transform(P['landmarks'], T), old['state'], api.state())
        tolerance = max(0.006, old['u'] + u + 0.002)
        log({'attachment_check': label, 'error_m': err, 'tolerance_m': tolerance})
        if err > tolerance or float(T[2, 2]) < 0.96:
            raise RuntimeError('Observed item no longer agrees with retained upright attachment')
        remember(T, u)
        return T, u
    def guard(target, label):
        for attempt in range(2):
            r = review('Assess the proposed local motion: ' + label + '. external is present only for an observed external object intersecting the proposed robot/held-item motion, not_observed means none observed, and unknown means evidence cannot decide. visibility distinguishes visible, self_occluded by robot/item, and unobserved external space. local supported means current nearby geometry supports a bounded trial of this motion; it does NOT certify the whole later route. Self-occlusion alone is not an external obstacle. up_view supported means a 0.015 m upward kept-grip view change is independently locally justified and could reveal the missing evidence. Return exactly these four fields.', {'target_pad_world_m': list(target), 'current_pad_world_m': geo.pad_position(api.state()).tolist(), 'item': P['item'], 'destination': P['destination'], 'phase': D['phase'], 'measured_geometry': D.get('metrics', {})}, gate_fields)
            p = r['parameters']
            if p['external'] == 'present':
                raise RuntimeError('Observed external obstruction at ' + label)
            if p['local'] == 'supported':
                return p['visibility']
            if attempt == 0 and p['up_view'] == 'supported':
                s = api.state()
                move((geo.pad_position(s) + [0, 0, 0.015]).tolist(), s['tcp_quaternion_xyzw'], 'keep', 'local view recovery', 8)
                if 'attachment' in D:
                    check_hold('after local view recovery')
            else:
                raise RuntimeError('No justified local action: ' + label + ', visibility=' + p['visibility'] + ', external=' + p['external'])
        raise RuntimeError('Local observation recovery exhausted')
    try:
        keys = [m['key'] for m in api.recall()]
        if 'processing_plan' in keys:
            P.update(api.recall('processing_plan')['value'])
            if 'processing_progress' in keys:
                D.update(api.recall('processing_progress')['value'])
            log({'resumed_historical_reference_frame': P['frame_id'], 'phase': D.get('phase', 'approach'), 'warning': 'Tracker handles are not restored; current registration is reacquired.'})
        else:
            fields = {'item': 'string', 'destination': 'string', 'model': ['flat_package_round_open_container', 'unsupported', 'unknown'], 'supported': ['yes', 'no', 'unknown'], 'top_camera': camera, 'top_pixels': {'type': ['array', 'null'], 'items': pixel, 'minItems': 4, 'maxItems': 4}, 'definitions': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 3, 'maxItems': 3}, 'patch_camera': camera, 'patch_polygon': polygon}
            r = review('Interpret instruction in context. item and destination name its intended movable item and receiver. model selects flat_package_round_open_container only for a rigid flat-sided package with a visible approximately horizontal rectangular top and a round open receiver. supported yes requires visible evidence that the package rests flush on the nearby support, not a guessed hidden underside. Request named regions top and support, each an interior homogeneous planar RGB-D patch with explicit camera, box, stride=6. top_camera/top_pixels give four visible top corners in cyclic order; pixels will be intersected with the fitted top plane, not treated as reliable boundary depth. Request a0,a1,a2 on three noncollinear identifiable printed or geometric features of the item, and definitions giving persistent physical identities in that order. Request base on its visible lower side, floor on the receiver interior bottom, and r0..r5 distributed around the INNER upper rim at a common height. patch_camera/patch_polygon select a textured visible interior item patch, possibly in the other camera; null if unavailable. Do not substitute a bowl surface point for its center.', {'instruction': task}, fields)
            p = r['parameters']
            if p['model'] != 'flat_package_round_open_container' or p['supported'] != 'yes' or p['top_pixels'] is None:
                raise RuntimeError('Requested relation lacks the observable package/support/opening model used by this method')
            f = geo.plane(measured(r, 'top', 'regions')['world_m'])
            support = geo.plane(measured(r, 'support', 'regions')['world_m'])
            u = max(0.0015, 3 * f['rms_m'], 3 * support['rms_m'])
            log({'top_plane': f, 'support_plane': support, 'uncertainty_m': u})
            if u > 0.004 or f['coefficients'][2] < 0.98 or support['coefficients'][2] < 0.98:
                raise RuntimeError('Visible planar surface geometry is too uncertain or tilted')
            corners = np.array([api.plane_point(p['top_camera'], pix, f['coefficients'])['world_m'] for pix in p['top_pixels']])
            center = np.mean(corners, axis=0)
            coeff = support['coefficients']
            base_z = -(coeff[0] * center[0] + coeff[1] * center[1] + coeff[3]) / coeff[2]
            h = float(center[2] - base_z)
            base = measured(r, 'base')['world_m']
            A = np.array([measured(r, 'a' + str(i))['world_m'] for i in range(3)])
            edges = np.roll(corners, -1, axis=0) - corners
            lengths = np.linalg.norm(edges, axis=1)
            rectangular = abs(float(np.dot(edges[0], edges[1]))) < 0.2 * lengths[0] * lengths[1] and abs(lengths[0] - lengths[2]) < 0.2 * lengths[0] and abs(lengths[1] - lengths[3]) < 0.2 * lengths[1]
            log({'package_height_inferred_from_supported_top_m': h, 'visible_base_z_m': base[2], 'support_z_m': base_z, 'edge_lengths_m': lengths.tolist()})
            if h <= 3 * u or abs(base[2] - base_z) > max(0.008, 0.25 * h) or not rectangular or float(np.linalg.svd(A - np.mean(A, axis=0), compute_uv=False)[1]) < 3 * u:
                raise RuntimeError('Package extent, support contact, or persistent-landmark spread is inadequate')
            if float(np.max(np.abs(A @ np.array(f['coefficients'][:3]) + f['coefficients'][3]))) > 3 * u:
                raise RuntimeError('Landmark depths are inconsistent with the visible package top')
            bowl = rim(r)
            floor = measured(r, 'floor')['world_m']
            if floor[2] >= bowl['z'] - bowl['u']:
                raise RuntimeError('No measured open interior below rim')
            P.update({'item': p['item'], 'destination': p['destination'], 'corners': corners.tolist(), 'landmarks': A.tolist(), 'definitions': p['definitions'], 'height': h, 'base_z': base_z, 'support_plane': coeff, 'u': u, 'bowl': bowl, 'floor': floor, 'frame_id': r['frame_id'], 'initial_robot': api.state(), 'assumption': 'Height uses visually confirmed flush support; hidden underside is not measured.'})
            api.checkpoint('processing_plan', P)
            patch(p['patch_camera'], p['patch_polygon'], np.eye(4))
        if 'phase' not in D:
            D['phase'] = 'approach'
            save()
        if D['phase'] == 'done':
            D['phase'] = 'released'
        pending = D.get('pending')
        if D['phase'] == 'approach' and pending is not None and pending['label'] == 'guarded finite-pad side engagement':
            D['phase'] = 'engagement'
            save()
            log({'resume': 'Reobserve actual engagement; do not replay overhead approach', 'historical_pending': pending})
        if D['phase'] == 'approach':
            T, u = observe('current pregrasp geometry')
            top, bottom, center = geometry(T)
            s = api.state()
            R = geo.rotation(s['tcp_quaternion_xyzw'])
            edges = np.roll(top, -1, axis=0) - top
            short = edges[int(np.argmin(np.linalg.norm(edges, axis=1)))]
            yaw = math.atan2(short[1], short[0]) - math.atan2(R[1, 1], R[0, 1])
            yaw = math.atan2(math.sin(yaw), math.cos(yaw))
            if abs(yaw) > math.pi / 2:
                yaw -= math.pi if yaw > 0 else -math.pi
            quat = s['tcp_quaternion_xyzw'] if abs(yaw) < 0.12 else api.compose(s['tcp_quaternion_xyzw'], [0, 0, yaw])
            inset, low = pinch_geometry(top, bottom, quat, u, s, require=False)
            high = [float(center[0]), float(center[1]), max(float(geo.pad_position(s)[2]), float(np.mean(top[:, 2]) + 0.06))]
            guard(high, 'noncontact overhead approach; preserve orientation except the measured short-side alignment')
            move(high, quat, 'open', 'overhead approach', 30)
            above = [float(center[0]), float(center[1]), float(np.mean(top[:, 2]) + 0.04)]
            guard(above, 'vertical approach ending above the visible item, with fingers still above its top')
            move(above, quat, 'open', 'approach source', 32)
            grasp_fields = {'fit': ['yes', 'no', 'unknown'], 'closer_view': ['supported', 'unsupported', 'unknown']}
            for trial in range(2):
                r = review('Inspect the actual OPEN fingers and item. fit yes means two visible side slots allow the opposing pads to descend and pinch the intended item along tool y; the interior opening must visibly accommodate it, with no external obstruction. A pose target or joint opening alone is not proof. fit no means observed incompatibility; unknown means missing evidence. closer_view supported means lowering only until the lowest finger remains 0.006 m above the top is a justified noncontact view-producing action.', {'item': P['item'], 'geometry': D['metrics']}, grasp_fields)
                if r['parameters']['fit'] == 'yes':
                    break
                if trial == 0 and r['parameters']['fit'] == 'unknown' and r['parameters']['closer_view'] == 'supported':
                    move([above[0], above[1], float(np.mean(top[:, 2]) - low + 0.006)], quat, 'open', 'closer noncontact grasp view', 8)
                else:
                    raise RuntimeError('Current finger side-slot evidence does not support this pinch')
            T, u = observe('refresh source after approach')
            top, bottom, center = geometry(T)
            s = api.state()
            quat = s['tcp_quaternion_xyzw']
            pinch_geometry(top, bottom, quat, u, s, require=False)
            D['phase'] = 'engagement'
            save()
        if D['phase'] == 'engagement':
            T, u = observe('actual preclosure engagement, including repair revalidation')
            engage(T, u)
            D['phase'] = 'closing'
            save()
        if D['phase'] == 'closing':
            previous_opening = np.array(api.state()['gripper_qpos_m'])
            for settling in range(4):
                hold('close', 'bounded pinch contact transition')
                current_opening = np.array(api.state()['gripper_qpos_m'])
                change = float(np.max(np.abs(current_opening - previous_opening)))
                log({'closure_settling_sample': settling, 'gripper_qpos_m': current_opening.tolist(), 'joint_change_m': change, 'interpretation': 'Actuator settling only, not retention evidence'})
                previous_opening = current_opening
                if settling >= 2 and change < 0.001:
                    break
            T, u = observe('actual item after closure, before diagnostic lift')
            top, bottom, center = geometry(T)
            pad = geo.pad_position(api.state())
            if np.linalg.norm((center - pad)[:2]) > float(np.max(np.linalg.norm(top[:, :2] - center[:2], axis=1))) + u:
                raise RuntimeError('Item is no longer between the intended side contacts')
            D['baseline'] = {'T': T.tolist(), 'u': u, 'state': api.state()}
            D['phase'] = 'closed'
            save()
        if D['phase'] == 'closed':
            b = D['baseline']
            s = api.state()
            dz = float(geo.pad_position(s)[2] - geo.pad_position(b['state'])[2])
            if dz < 0.03:
                move((geo.pad_position(s) + [0, 0, 0.035 - dz]).tolist(), D['quat'], 'keep', 'diagnostic retention lift', 12)
            T, u = observe('diagnostic lift outcome')
            s = api.state()
            A0, A1 = geo.transform(P['landmarks'], b['T']), geo.transform(P['landmarks'], T)
            hand = float(geo.pad_position(s)[2] - geo.pad_position(b['state'])[2])
            object_lift = float(np.mean(A1[:, 2] - A0[:, 2]))
            error = geo.attachment_error(A0, A1, b['state'], s)
            tolerance = max(0.006, b['u'] + u + 0.002)
            log({'retention_hand_lift_m': hand, 'retention_item_lift_m': object_lift, 'attachment_error_m': error, 'tolerance_m': tolerance})
            if hand < 0.02 or object_lift < 0.65 * hand or error > tolerance or float(np.min(geometry(T)[1][:, 2])) < P['base_z'] + 0.01:
                raise RuntimeError('Retention is not established; no transfer or blind regrasp')
            D['phase'] = 'retained'
            remember(T, u)
        if D['phase'] == 'retained':
            T, u = check_hold('current retained item, including repair revalidation')
            arrived = False
            for leg in range(24):
                top, bottom, center = geometry(T)
                pad = geo.pad_position(api.state())
                dz = max(0.0, P['bowl']['z'] + 0.04 - float(np.min(bottom[:, 2])))
                xy = np.array(P['bowl']['xy']) - center[:2]
                distance = float(np.linalg.norm(xy))
                if dz <= 0.006 and distance <= 0.007:
                    arrived = True
                    break
                delta = np.array([0.0, 0.0, min(dz, 0.06)]) if dz > 0.006 else np.array([xy[0], xy[1], 0.0]) * min(1.0, 0.06 / max(0.0001, distance))
                target = pad + delta
                visibility = guard(target.tolist(), 'raise retained item above receiver, then translate toward its opening')
                current = geo.pad_position(api.state())
                difference = target - current
                if visibility != 'visible':
                    target = current + difference * min(1.0, 0.03 / max(0.0001, float(np.linalg.norm(difference))))
                move(target.tolist(), D['quat'], 'keep', 'bounded retained transfer', 14)
                T, u = check_hold('after transfer leg')
            if not arrived:
                raise RuntimeError('Transfer leg bound exhausted; remaining displacement is not certified progress')
            D['phase'] = 'lowering'
            save()
        if D['phase'] == 'lowering':
            T, u = check_hold('before receiver alignment')
            historical = dict(P['bowl'])
            top, bottom, center = geometry(T)
            pad = geo.pad_position(api.state())
            clearance = max(0.006, historical['u'] + 0.0035)
            dz = max(historical['z'] + clearance - float(np.min(bottom[:, 2])), historical['z'] + clearance - float(pad[2]) - D['finger_low'])
            proposal = pad + [historical['xy'][0] - center[0], historical['xy'][1] - center[1], dz]
            fields = {'rim_identity': ['confirmed', 'ambiguous', 'unknown'], 'item_identity': ['confirmed', 'ambiguous', 'unknown'], 'patch_camera': camera, 'patch_polygon': polygon, 'external': ['present', 'not_observed', 'unknown'], 'visibility': ['visible', 'self_occluded', 'unobserved'], 'local': ['supported', 'unsupported', 'unknown']}
            cached = D.get('receiver_refresh')
            alignment_frame = api.state()['frame_id']
            reusable = cached is not None and cached['review_frame_id'] == alignment_frame and cached['bowl']['frame_id'] == alignment_frame
            if reusable:
                bowl, p = cached['bowl'], cached['local_evidence']
                log({'receiver_evidence_reused_frame': alignment_frame, 'reason': 'No physical step since measured rim, identity, patch selection and bounded local-action review; no new review or measurement claimed.'})
            else:
                r = review('Refresh the receiver and held item for bounded local centering above its opening. Request r0..r5 at six distributed, currently visible INNER upper lip surfaces at common height, across both views if useful; omit hidden or mixed-depth points. These are new unordered samples, not historical correspondences. rim_identity confirmed means all samples identify the intended bowl lip, not outer wall, interior floor or plate. item_identity confirmed identifies the intended package and patch unambiguously. patch_camera and patch_polygon select textured package interior excluding fingers/background; null polygon if unavailable. external present means an observed external obstruction intersecting this local correction; not_observed means none seen, not certified clearance; unknown means unresolved external evidence. visibility distinguishes visible surroundings, robot/item self_occluded, and unobserved external space. local supported means the current nearby evidence justifies kept-grip alignment within 0.03 m lateral and 0.06 m vertical displacement, with orientation preserved and package bottom and open fingers ending above the measured rim, conditional on numerical fit checks. unsupported means visible incompatibility; unknown means essential evidence is absent. Do not require an unseen later corridor or full package perimeter.', {'item': P['item'], 'destination': P['destination'], 'historical_rim': historical, 'item_top_world_m': top.tolist(), 'inferred_item_bottom_world_m': bottom.tolist(), 'item_geometry_uncertainty_m': u + P['u'], 'current_pad_world_m': pad.tolist(), 'provisional_target_pad_world_m': proposal.tolist(), 'lowest_open_finger_relative_pad_z_m': D['finger_low']}, fields, reserve=1)
                p, bowl = r['parameters'], rim(r)
                alignment_frame = r['frame_id']
                radius_change = abs(bowl['radius'] - historical['radius'])
                radius_tolerance = bowl['u'] + historical['u'] + 0.002
                log({'current_opening_refit': bowl, 'radius_change_m': radius_change, 'radius_consistency_tolerance_m': radius_tolerance})
                if radius_change > radius_tolerance:
                    raise RuntimeError('Current rim shape conflicts with saved receiver: ' + str([radius_change, radius_tolerance]))
                D['receiver_refresh'] = {'bowl': bowl, 'previous_bowl': historical, 'review_frame_id': alignment_frame, 'local_evidence': p, 'source': 'Named RGB-D lip measurements and typed local review; historical after motion.'}
            if p['rim_identity'] != 'confirmed' or p['item_identity'] != 'confirmed':
                raise RuntimeError('Receiver or held-item identity unresolved')
            if p['external'] == 'present' or p['local'] != 'supported':
                raise RuntimeError('No justified local alignment: ' + str(p))
            P['bowl'] = bowl
            api.checkpoint('processing_plan', P)
            save()
            patch(p['patch_camera'], p['patch_polygon'], T, u)
            top, bottom, center = geometry(T)
            footprint = np.concatenate([top, bottom])
            radius = float(np.max(np.linalg.norm(footprint[:, :2] - center[:2], axis=1)))
            margin = bowl['radius'] - radius - bowl['u'] - u - P['u']
            log({'opening_radius_m': bowl['radius'], 'item_footprint_radius_m': radius, 'opening_uncertainty_m': bowl['u'], 'registration_uncertainty_m': u, 'package_reference_uncertainty_m': P['u'], 'centered_alignment_budget_m': margin, 'interpretation': 'Positive budget permits an observed alignment trial, not release. Actual centering error will be measured, not charged as a fixed 0.003 m before motion.'})
            if margin <= 0:
                raise RuntimeError('No positive measured centered-fit budget: ' + str(margin))
            pad = geo.pad_position(api.state())
            clearance = max(0.006, bowl['u'] + u + P['u'] + 0.002)
            dz = max(bowl['z'] + clearance - float(np.min(bottom[:, 2])), bowl['z'] + clearance - float(pad[2]) - D['finger_low'])
            target = pad + [bowl['xy'][0] - center[0], bowl['xy'][1] - center[1], dz]
            lateral = float(np.linalg.norm(target[:2] - pad[:2]))
            origin = pad.copy()
            log({'alignment_target_pad_world_m': target.tolist(), 'lateral_correction_m': lateral, 'vertical_correction_m': float(dz), 'above_rim_clearance_m': clearance, 'local_review_frame_id': alignment_frame, 'visibility': p['visibility']})
            if lateral > 0.03 or abs(dz) > 0.06:
                raise RuntimeError('Alignment exceeds reviewed local bounds: ' + str([lateral, float(dz)]))
            if api.state()['frame_id'] != alignment_frame:
                raise RuntimeError('Motion invalidated local review before first alignment')
            aligned = False
            for alignment_trial in range(3):
                if float(np.linalg.norm(target[:2] - origin[:2])) > 0.03 or abs(float(target[2] - origin[2])) > 0.06:
                    raise RuntimeError('Refinement would exceed reviewed local envelope')
                move(target.tolist(), D['quat'], 'keep', 'measured receiver alignment ' + str(alignment_trial), 18, 16, tolerance=max(0.0005, 0.0015 / (2 ** alignment_trial)))
                T, u = check_hold('actual prerelease placement')
                top, bottom, center = geometry(T)
                pad = geo.pad_position(api.state())
                radial = float(np.max(np.linalg.norm(np.concatenate([top, bottom])[:, :2] - np.array(bowl['xy']), axis=1)))
                bottom_z = float(np.min(bottom[:, 2]))
                measured_margin = bowl['radius'] - radial - u - bowl['u'] - P['u']
                finger_z = float(pad[2] + D['finger_low'])
                log({'alignment_trial': alignment_trial, 'prerelease_item_radius_about_receiver_m': radial, 'observed_remaining_radial_margin_m': measured_margin, 'registration_uncertainty_m': u, 'package_reference_uncertainty_m': P['u'], 'opening_uncertainty_m': bowl['u'], 'item_bottom_z_estimate_m': bottom_z, 'lowest_open_finger_z_estimate_m': finger_z, 'rim_z_m': bowl['z']})
                if bottom_z < bowl['z'] + bowl['u'] or bottom_z > bowl['z'] + 0.025 or finger_z < bowl['z'] + bowl['u']:
                    raise RuntimeError('Measured above-rim release height or finger clearance is inadequate')
                if measured_margin > 0:
                    aligned = True
                    break
                current_radius = float(np.max(np.linalg.norm(np.concatenate([top, bottom])[:, :2] - center[:2], axis=1)))
                centered_budget = bowl['radius'] - current_radius - u - bowl['u'] - P['u']
                correction = np.array(bowl['xy']) - center[:2]
                log({'centered_refinement_budget_m': centered_budget, 'measured_center_correction_m': correction.tolist()})
                if centered_budget <= 0 or float(np.linalg.norm(correction)) > 0.006:
                    raise RuntimeError('Fresh geometry cannot justify a small centering refinement')
                target = pad + [float(correction[0]), float(correction[1]), 0.0]
            if not aligned:
                raise RuntimeError('Measured alignment budget not achieved within three trials; no release')
            D['release'] = {'T': T.tolist(), 'bowl': bowl, 'state': api.state(), 'uncertainty_m': u}
            D['phase'] = 'opening'
            save()
        if D['phase'] == 'opening':
            for repeat in range(2):
                hold('open', 'release at measured opening')
            D['phase'] = 'released'
            save()
        if D['phase'] == 'released':
            s = api.state()
            move((geo.pad_position(s) + [0, 0, 0.04]).tolist(), s['tcp_quaternion_xyzw'], 'keep', 'postrelease retreat and new view', 14, 4)
            final_fields = {'relation': ['inside_supported', 'on_rim', 'outside', 'still_held', 'occluded', 'unknown'], 'stability': ['unchanged_supported', 'changing', 'unknown'], 'stable_id': 'string', 'patch_camera': camera, 'patch_polygon': polygon}
            question = 'Assess the actual released item and intended receiver. relation inside_supported means visibly within the inner rim and supported inside, not perched on the rim or constrained by fingers. Use on_rim/outside/still_held/occluded/unknown otherwise. Request point s on an identifiable visible item feature; stable_id defines its persistent physical identity. In a comparison, measure that exact feature and retain stable_id verbatim; omit s if ambiguous. stability unchanged_supported requires agreement of visible pose and support with the supplied earlier observation; otherwise changing or unknown. patch_camera and patch_polygon select a textured visible INTERIOR patch belonging unambiguously to this intended item, excluding bowl, fingers and background; null polygon if unavailable. This patch measures subsequent motion, not support or grasp. No full outline is required.'
            first = review(question, {'item': P['item'], 'destination': P['destination'], 'release_evidence': D['release']}, final_fields, 0)
            if first['parameters']['relation'] == 'still_held':
                if api.state()['budgets']['gpt_remaining'] < 1:
                    raise RuntimeError('Still held after release; no review remains to verify another release trial')
                hold('open', 'single release recovery above receiver')
                s = api.state()
                move((geo.pad_position(s) + [0, 0, 0.015]).tolist(), s['tcp_quaternion_xyzw'], 'keep', 'release recovery observation', 6, 2)
                first = review(question, {'item': P['item'], 'destination': P['destination'], 'release_retry': True}, final_fields, 0)
            fp = first['parameters']
            stable_handle = None
            if fp['relation'] == 'inside_supported' and fp['patch_polygon'] is not None:
                try:
                    ref = api.track_init(fp['patch_camera'], fp['patch_polygon'])
                    stable_handle = ref['handle']
                    log({'postrelease_patch_frame': ref['frame_id'], 'reference_features': ref['reference_features']})
                except Exception as exc:
                    log({'postrelease_patch_unavailable': str(exc)})
            D['postrelease_reference'] = {'frame_id': first['frame_id'], 'parameters': fp, 'point': first['points'].get('s'), 'source': 'Postretreat image review and optional named RGB-D point; historical after waiting.'}
            save()
            for wait in range(3):
                hold('keep', 'postrelease stability interval')
            displacement, second, stable = None, None, False
            if stable_handle is not None:
                t = api.track_update(stable_handle)
                if t['status'] == 'tracked':
                    uncertainty = max(0.0015, 3 * t['rms_m'], t['uncertainty_floor_m'])
                    M = np.array(t['transform_initial_world_to_current_world'])
                    X = np.array(t['reference_inlier_world_m'])
                    displacement = float(np.max(np.linalg.norm(geo.transform(X, M) - X, axis=1)))
                    angle = float(np.arccos(np.clip((np.trace(M[:3, :3]) - 1) / 2, -1, 1)))
                    stable = bool(t['inliers'] >= 8 and t['inliers'] / max(1, t['matches']) >= 0.6 and uncertainty <= 0.003 and float(np.max(np.array(t['inlier_spread_m']))) > 3 * uncertainty and displacement <= 0.003 and angle <= 0.03)
                    log({'postrelease_tracking': {'frame_id': t['frame_id'], 'reference_frame_id': t['reference_frame_id'], 'inliers': t['inliers'], 'matches': t['matches'], 'uncertainty_m': uncertainty, 'maximum_patch_motion_m': displacement, 'rotation_rad': angle, 'short_interval_stable': stable}})
                else:
                    log({'postrelease_tracking_unknown': t['reason'], 'frame_id': t['frame_id']})
            if not stable and api.state()['budgets']['gpt_remaining'] > 0:
                context = {'item': P['item'], 'destination': P['destination'], 'earlier_frame_id': first['frame_id'], 'stable_id': fp['stable_id'], 'earlier_point': first['points'].get('s'), 'earlier_relation': fp['relation']}
                second = review(question, context, final_fields, 0)
                displacement = None
                if valid(first, 's') and valid(second, 's') and second['parameters']['stable_id'] == fp['stable_id']:
                    displacement = float(np.linalg.norm(np.array(first['points']['s']['world_m']) - np.array(second['points']['s']['world_m'])))
                stable = bool(second['parameters']['relation'] == 'inside_supported' and second['parameters']['stability'] == 'unchanged_supported' and displacement is not None and displacement <= 0.005)
            ok = bool(fp['relation'] == 'inside_supported' and stable)
            log({'postrelease_first': fp, 'postrelease_second': None if second is None else second['parameters'], 'observed_motion_m': displacement, 'completion_proposed': ok, 'limitation': 'Image-observed interior support and independently observed short-interval stability only; unknown tracking is not motion or loss evidence. Not certified physics or official success.'})
            D['phase'] = 'done' if ok else 'released'
            D['final_observation'] = E[-1]
            save()
            return {'completion_proposed': bool(ok), 'evidence': E}
        raise RuntimeError('Unrecognized persisted processing phase: ' + str(D.get('phase')))
    except Exception as exc:
        log({'stopped': str(exc), 'phase': D.get('phase', 'initial_observation'), 'pending': D.get('pending'), 'policy': 'Physical state persists; no rollback or unverified success is claimed.'})
        return {'completion_proposed': False, 'evidence': E}

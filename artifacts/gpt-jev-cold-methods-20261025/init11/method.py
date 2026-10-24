def main(api):
    log, D, H = [], {}, [None, np.eye(4), 0.0, 0]
    def arr(x): return np.asarray(x, dtype=float)
    def length(x): return float(np.linalg.norm(x))
    def require(ok, message, values=None):
        if not ok:
            log.append({'gap': message, 'values': values})
            raise RuntimeError(message)
    def save(phase):
        D['phase'] = phase
        D['evidence'] = log[-10:]
        api.checkpoint('pick_place', D)
    def review(question, fields, context=None):
        require(api.state()['budgets']['gpt_remaining'] > 0, 'No review budget remains')
        r = api.review(question, context=context, fields=fields)
        log.append({'review': r['explanation'], 'frame': r['frame_id'], 'measurement_errors': r['measurement_errors']})
        require(r['status'] != 'stop', 'Observation reviewer requested stop')
        return r
    def points(r, names):
        bad = [e['name'] for e in r['measurement_errors']]
        if not all(n in r['points'] and n not in bad for n in names): return None
        return arr([r['points'][n]['world_m'] for n in names])
    def region(r, name):
        require(name in r['regions'] and name not in [e['name'] for e in r['measurement_errors']], 'Missing measured region: ' + name)
        return arr(r['regions'][name]['world_m'])
    Q = {}
    for axis in ['x', 'y', 'z', 'rx', 'ry', 'rz']:
        Q[axis] = {'type': 'choice', 'instructions': 'For world axis ' + axis + ', read state.processed_features.axes.' + axis + '.goal_relation. Select positive for increase, negative for decrease, hold for within_tolerance. Follow only this named axis; magnitudes are computed by the controller.', 'criteria': {'negative': 'This axis relation is decrease.', 'hold': 'This axis relation is within_tolerance.', 'positive': 'This axis relation is increase.'}}
    Q['gripper'] = {'type': 'choice', 'instructions': 'Read state.processed_features.objective.gripper. Deliver exactly its open, close, or keep requirement. Keep means do not change the current command; do not decide grasp success.', 'criteria': {'open': 'The objective explicitly requests open.', 'close': 'The objective explicitly requests close.', 'keep': 'The objective explicitly requests keep.'}}
    pixel = {'type': 'array', 'items': {'type': 'integer', 'minimum': 0, 'maximum': 767}, 'minItems': 2, 'maxItems': 2}
    polygon = {'type': 'array', 'items': pixel, 'minItems': 3, 'maxItems': 16}
    patch_fields = {'camera': ['agentview', 'robot0_eye_in_hand'], 'polygon': polygon}
    def start_tracker(camera, polygon_value, anchor, uncertainty):
        if H[3] >= 12: return
        try:
            t = api.track_init(camera, polygon_value)
            H[0], H[1], H[2], H[3] = t['handle'], anchor.copy(), uncertainty, H[3] + 1
            log.append({'tracker_reference_frame': t['frame_id'], 'features': t['reference_features']})
        except Exception as e:
            H[0] = None
            log.append({'tracker_initialization_gap': str(e)})
    def observe_object(precise=False):
        current_frame = api.state()['frame_id']; saved = D.get('last_registration', {})
        observation = D.get('registration_observations', {})
        if not precise and saved.get('frame') == current_frame and observation.get('frame') == current_frame:
            M0, u0 = arr(saved['matrix']), float(saved['u'])
            if H[0] is None:
                start_tracker(observation['camera'], observation['polygon'], M0, u0)
            log.append({'registration_restore': 'Measured semantic registration at unchanged physical frame, not predicted attachment', 'frame': current_frame, 'uncertainty_m': u0, 'names': saved['names']})
            return M0, u0
        if H[0] is not None and not precise:
            t = api.track_update(H[0])
            if t['status'] == 'tracked':
                u = H[2] + max(0.001, 2 * t['rms_m'], t['uncertainty_floor_m'])
                spreads = sorted(arr(t['inlier_spread_m']).reshape(-1).tolist(), reverse=True)
                good = t['inliers'] >= 12 and t['inliers'] / max(1, t['matches']) >= 0.65 and t['rms_m'] <= 0.0025 and len(spreads) >= 2 and spreads[1] > max(0.003, 2 * t['rms_m']) and u <= 0.015
                if good:
                    log.append({'registration': 'patch', 'frame': t['frame_id'], 'reference_frame': t['reference_frame_id'], 'inliers': t['inliers'], 'rms_m': t['rms_m'], 'spreads_m': spreads, 'uncertainty_m': u})
                    return arr(t['transform_initial_world_to_current_world']) @ H[1], u
            log.append({'registration': 'unusable', 'frame': t['frame_id'], 'reason': t.get('reason', 'inlier, spread, or uncertainty gate')})
        L, C = arr(D['landmarks']), arr(D['corners'])[:4]
        if 'corner_definitions' not in D:
            direction = L[1] - L[0]; direction /= length(direction)
            lateral = L[2] - L[0] - direction * float((L[2] - L[0]) @ direction)
            D['corner_definitions'] = ['c' + str(i) + ': original top-face corner at the end nearer l' + str(0 if length(c - L[0]) < length(c - L[1]) else 1) + ', on the lateral side of the line through l0 and l1 ' + ('containing l2' if float((c - L[0]) @ lateral) > 0 else 'opposite l2') for i, c in enumerate(C)]
            save(D['phase'])
        nullable_pixel = dict(pixel); nullable_pixel['type'] = ['array', 'null']
        mark = {'type': 'object', 'properties': {'camera': {'type': 'string', 'enum': ['agentview', 'robot0_eye_in_hand']}, 'pixel': nullable_pixel}}
        for trial in range(1 if D.get('phase') == 'release_alignment' else 2):
            f = dict(patch_fields); f.update({'identity': ['unambiguous', 'unknown'], 'corner_marks': {'type': 'array', 'items': mark, 'minItems': 4, 'maxItems': 4}})
            release_question = ''
            if D.get('phase') == 'release_alignment':
                f.update({'release_obstruction': ['external', 'none_observed', 'unknown'], 'release_visibility': ['usable', 'self_occluded', 'unobserved'], 'bowl_state': ['same_supported_no_displacement_observed', 'displacement_observed', 'unknown'], 'local_release': ['supported', 'unknown']})
                release_question = ' Also assess ONLY opening at this pose and a 75 mm open-hand upward retreat. release_obstruction=external means visible external interference with opening or retreat; none_observed is not certified clearance; unknown means an unresolved possible external obstacle. release_visibility separates usable evidence, robot/package self_occlusion, and genuinely unobserved space. bowl_state reports whether the same bowl remains supported without observed displacement, contrary displacement, or unknown. local_release=supported requires local visual evidence and the supplied measured finger margins to support opening and retreat, conditional on the newly measured package footprint passing the numerical containment check. Self-occlusion alone is not an obstacle; do not require a hidden complete perimeter. Earlier object geometry in release_geometry is historical, not a current observation. Unknown or observed interference does not authorize release.'
            r = review('Recover CURRENT package geometry. Request only identifiable named print points l0,l1,l2 using the saved definitions. Return corner_marks in c0,c1,c2,c3 order, each with its own camera and visible pixel, or pixel=null if hidden or ambiguous. Corners are persistent physical identities defined relative to printed features, NOT screen-relative corners. Use both cameras: one can show the Cream end while the other shows the Cheese end. Request patch_surface as a small strictly interior region of the SAME planar printed top, with explicit camera, box and stride=4. Corner depths will be derived from that measured plane, avoiding mixed edge depth. identity=unambiguous requires every supplied correspondence to be independently recognizable; omit uncertain points instead of inventing them. Return camera and polygon for a textured visible interior patch excluding fingers and background. Partial visibility is acceptable. If precise_outline is true, seek all obtainable corners in both views for a direct footprint measurement, not a predicted outline. On retry resolve the missing correspondence with the other view or a better visible feature, not the same failed selection.' + release_question, f, {'definitions': D['definitions'], 'corner_definitions': D['corner_definitions'], 'reference_points': D['landmarks'], 'reference_corners': C.tolist(), 'reference_frame': D['reference_frame'], 'attempt': trial, 'precise_outline': precise, 'previous_registration_gap': D.get('registration_gap'), 'release_geometry': D.get('release_geometry')})
            if D.get('phase') == 'release_alignment':
                p = r['parameters']
                D['release_review'] = {'frame': r['frame_id'], 'obstruction': p['release_obstruction'], 'visibility': p['release_visibility'], 'bowl_state': p['bowl_state'], 'action': p['local_release']}
            if r['parameters']['identity'] != 'unambiguous': continue
            aa, bb, names, outline = [], [], [], {}
            edge_u, plane = 0.0005, None
            if 'patch_surface' in r['regions'] and 'patch_surface' not in [e['name'] for e in r['measurement_errors']]:
                try:
                    fit = geo.plane(region(r, 'patch_surface'))
                    if fit['rms_m'] < 0.002 and min(fit['in_plane_spread_m']) > 0.003:
                        plane = fit['coefficients']; edge_u = max(edge_u, 3 * fit['rms_m'])
                        D['surface_measurement'] = {'frame': r['frame_id'], 'plane': plane, 'u': edge_u, 'rms_m': fit['rms_m'], 'spread_m': min(fit['in_plane_spread_m']), 'source': 'current identified interior RGB-D top surface'}
                except Exception as e: log.append({'surface_fit_gap': str(e)})
            for i in range(3):
                p = points(r, ['l' + str(i)])
                if p is not None:
                    aa.append(L[i]); bb.append(p[0]); names.append('l' + str(i))
            if plane is not None:
                for i, item in enumerate(r['parameters']['corner_marks']):
                    if item['pixel'] is None: continue
                    try:
                        p = api.plane_point(item['camera'], item['pixel'], plane)
                        c = arr(p['world_m']); cal = api.camera(item['camera'])
                        depth = float(geo.transform(arr([c]), np.linalg.inv(arr(cal['camera_to_world_opencv'])))[0, 2])
                        edge_u = max(edge_u, 2 * depth / min(cal['K'][0][0], cal['K'][1][1]))
                        aa.append(C[i]); bb.append(c); names.append('c' + str(i)); outline[str(i)] = c.tolist()
                    except Exception as e: log.append({'corner_measurement_gap': i, 'error': str(e)})
            D['registration_observations'] = {'frame': r['frame_id'], 'names': names, 'points': arr(bb).tolist(), 'visible_corners': outline, 'plane': plane, 'camera': r['parameters']['camera'], 'polygon': r['parameters']['polygon']}
            save(D['phase'])
            if len(aa) < 3:
                D['registration_gap'] = {'reason': 'Need an independent third identifiable correspondence', 'names': names}
                continue
            A, B = arr(aa), arr(bb); candidates = []
            limit = 2 * D['u'] + edge_u
            if plane is not None:
                na = arr(geo.plane(C)['coefficients'][:3]); na /= length(na)
                nb = arr(plane[:3]); nb /= length(nb)
                for i in range(len(names)):
                    for j in range(i + 1, len(names)):
                        if names[i][0] != 'c' or names[j][0] != 'c': continue
                        ea, eb = A[j] - A[i], B[j] - B[i]
                        ea -= na * float(ea @ na); eb -= nb * float(eb @ nb)
                        la, lb = length(ea), length(eb)
                        if min(la, lb) <= 6 * max(D['u'], edge_u) or abs(la - lb) > 2 * (D['u'] + edge_u): continue
                        ea /= la; eb /= lb
                        R = np.column_stack([eb, np.cross(nb, eb), nb]) @ np.column_stack([ea, np.cross(na, ea), na]).T
                        M = np.eye(4); M[:3, :3] = R
                        anchor = (A[i] + A[j]) / 2
                        M[:3, 3] = (B[i] + B[j]) / 2 - R @ anchor
                        residuals = np.linalg.norm(geo.transform(A, M) - B, axis=1)
                        keep = [k for k in range(len(names)) if float(residuals[k]) <= limit]
                        if len(keep) < 3 or i not in keep or j not in keep: continue
                        lever = length(C.mean(axis=0) - anchor)
                        normal_u = 3 * D['surface_measurement']['rms_m'] / D['surface_measurement']['spread_m']
                        error = max(float(residuals[i]), float(residuals[j]))
                        u = D['u'] + edge_u + error + lever * (2 * edge_u / lb + normal_u)
                        if u > 0.015: continue
                        candidates.append({'M': M, 'keep': keep, 'error': error, 'validation': float(np.max(residuals[keep])), 'u': u, 'spread': lb, 'mode': 'current plane and corner edge with independent correspondence', 'residuals': residuals.tolist()})
            if not candidates:
                ac, bc = A.mean(axis=0), B.mean(axis=0)
                U, sv, V = np.linalg.svd((A - ac).T @ (B - bc)); R = V.T @ U.T
                if np.linalg.det(R) < 0:
                    V[-1, :] *= -1; R = V.T @ U.T
                M = np.eye(4); M[:3, :3] = R; M[:3, 3] = bc - R @ ac
                residuals = np.linalg.norm(geo.transform(A, M) - B, axis=1)
                error = float(np.max(residuals)); spread = float(np.linalg.svd(B - bc, compute_uv=False)[1])
                u = max(D['u'], edge_u) + error + D['u'] * D['radius'] / max(spread, D['u'])
                normal_ok = plane is None or length(R @ na - nb) < 0.04
                if error <= 2 * max(D['u'], edge_u) and spread >= 4 * D['u'] and normal_ok and u <= 0.015:
                    candidates.append({'M': M, 'keep': list(range(len(names))), 'error': error, 'validation': error, 'u': u, 'spread': spread, 'mode': 'all current semantic correspondences', 'residuals': residuals.tolist()})
                else:
                    D['registration_gap'] = {'reason': 'Current correspondence fit inconsistent; retry must resolve a named discrepancy or expose another feature, not invent hidden corners', 'names': names, 'residuals_m': residuals.tolist(), 'limit_m': 2 * max(D['u'], edge_u), 'spread_m': spread, 'uncertainty_m': u}
                    log.append(D['registration_gap']); save(D['phase']); continue
            best = candidates[0]
            for candidate in candidates[1:]:
                if len(candidate['keep']) > len(best['keep']) or (len(candidate['keep']) == len(best['keep']) and candidate['validation'] < best['validation']): best = candidate
            ambiguous = any(len(c['keep']) == len(best['keep']) and float(np.max(np.linalg.norm(geo.transform(C, c['M']) - geo.transform(C, best['M']), axis=1))) > c['u'] + best['u'] for c in candidates)
            if ambiguous:
                D['registration_gap'] = {'reason': 'Equally supported registrations disagree; need independently identifiable replacement correspondences', 'names': names}
                log.append(D['registration_gap']); save(D['phase']); continue
            rejected = [names[k] for k in range(len(names)) if k not in best['keep']]
            log.append({'registration_selection': best['mode'], 'all_names': names, 'residuals_m': best['residuals'], 'independent_validation_limit_m': limit, 'rejected_correspondences': rejected, 'uncertainty_kind': 'Operational geometric floor including historical shape and current sensing; not a certified bound'})
            M, u, error, spread = best['M'], best['u'], best['error'], best['spread']
            names = [names[k] for k in best['keep']]; B = B[best['keep']]
            outline = {k: v for k, v in outline.items() if 'c' + k in names}
            D['registration_gap'] = None
            log.append({'registration': 'current_correspondences', 'frame': r['frame_id'], 'names': names, 'points': B.tolist(), 'residual_m': error, 'spread_m': spread, 'uncertainty_m': u, 'direct_corners': len(outline)})
            if len(outline) == 4:
                D['current_outline'] = {'frame': r['frame_id'], 'points': [outline[str(i)] for i in range(4)], 'u': edge_u, 'source': 'visible semantic corner rays on current measured top plane'}
            elif precise:
                log.append({'outline': 'Partial perimeter; use the independently measured registration and its uncertainty. No unchanged-scene full-outline retry.'})
            D['last_registration'] = {'frame': r['frame_id'], 'names': names, 'points': B.tolist(), 'matrix': M.tolist(), 'u': u}
            start_tracker(r['parameters']['camera'], r['parameters']['polygon'], M, u); save(D['phase'])
            return M, u
        raise RuntimeError('Unknown registration: insufficient current unambiguous print/corner correspondences in both views; no transform extrapolated')
    def prepare_grasp():
        M, u = observe_object(); s = api.state(); pad = geo.pad_position(s)
        volume = geo.transform(arr(D['corners']), M); outline = D.get('current_outline', {})
        if outline.get('frame') == s['frame_id']:
            volume[:4] = arr(outline['points']); u = outline['u']
        R = geo.rotation(s['tcp_quaternion_xyzw']); ext = arr(s['own_geometry']['pad_extent_in_tool_m']); axis = D['grasp_geometry']['opening_axis_tool']
        opening = 2 * abs(s['gripper_qpos_m'][0] - s['gripper_qpos_m'][1]) - ext[axis]
        gap = opening / 2 - float(np.max(np.abs((volume[:4] - pad) @ R[:, axis])))
        halfheight = float(abs(R[2, :]) @ ext) / 2
        overlap = min(float(volume[:4, 2].min()), pad[2] + halfheight) - max(float(volume[4:, 2].max()), pad[2] - halfheight)
        vertical_u = u; surface = D.get('surface_measurement', {})
        if surface.get('frame') == s['frame_id'] and surface['plane'][2] > 0.97:
            n = arr(surface['plane']); table = arr(D['table'])
            top_z = -float(n[:2] @ pad[:2] + n[3]) / n[2]
            base_z = -float(table[:2] @ pad[:2] + table[3]) / table[2]
            slope_allowance = length(n[:2]) * (halfheight + float(np.max(ext[:2])) / 2 + u) / n[2]
            overlap = min(top_z - slope_allowance, pad[2] + halfheight) - max(base_z, pad[2] - halfheight)
            vertical_u = max(D['u'], surface['u'] / n[2])
        envelope = hand_points(s, s['tcp_quaternion_xyzw'], pad)
        table_gap = float(np.min(envelope @ arr(D['table'][:3]) + D['table'][3]))
        values = {'pad_world_m': pad.tolist(), 'side_allowance_m': gap, 'overlap_m': overlap, 'finger_table_gap_m': table_gap, 'geometry_u_m': u, 'vertical_surface_u_m': vertical_u, 'frame': s['frame_id']}
        log.append({'actual_grasp_geometry': values})
        require(gap > u and overlap > 2 * vertical_u and table_gap > D['u'], 'Current grasp margins insufficient; no further downward push', values)
        r = review('Assess closure AT THE PRESENT POSE, not a further descent. support=table requires the same package visibly resting on its table. lanes=opposed requires current visual evidence that the two open jaws straddle opposite package sides with pad bands overlapping the side faces; blocked means external interference, unknown means opposition cannot be established. Use both views and the supplied actual pad geometry. Complete top-perimeter visibility is NOT required. Self-occlusion is not evidence of an external obstacle. Request table_probe on adjacent exposed support to revalidate the saved table. This permits bounded closure and a retention-measurement lift, NOT a declaration of retention.', {'support': ['table', 'unknown'], 'lanes': ['opposed', 'blocked', 'unknown']}, {'measured_margins': values, 'table_plane': D['table'], 'current_surface': surface, 'phase': D['phase']})
        p = points(r, ['table_probe'])
        require(p is not None and abs(float(p[0] @ arr(D['table'][:3]) + D['table'][3])) < 3 * D['u'], 'Current supporting table is not revalidated')
        require(r['parameters']['support'] == 'table' and r['parameters']['lanes'] == 'opposed', 'Current jaw opposition or package support unresolved', r['parameters'])
        D['grasp_ready'] = values; save('closing')
    def hand_points(state, quaternion, pad):
        g = state['own_geometry']; lo, hi = g['finger_low_offset_tool_m'], g['finger_high_offset_tool_m']
        corners = arr([[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]])
        T = np.eye(4); T[:3, :3] = geo.rotation(quaternion); T[:3, 3] = arr(pad) - T[:3, :3] @ arr(g['pad_center_in_tool_m'])
        return geo.transform(corners, T)
    def mouth(r):
        valid = [n for n in ['r0', 'r1', 'r2', 'r3', 'r4', 'r5'] if points(r, [n]) is not None]
        require(len(valid) >= 5 and r['parameters']['mouth'] == 'inner_lip', 'Need five valid inner-lip measurements and their identity')
        p = points(r, valid); plane, circle = geo.plane(p), geo.circle_xy(p)
        log.append({'bowl_plane': plane, 'bowl_circle': circle})
        require(plane['coefficients'][2] > 0.97 and plane['rms_m'] < 0.003 and circle['max_radial_error_m'] < 0.004 and circle['largest_angular_gap_rad'] < math.pi, 'Bowl mouth is not sufficiently measured as horizontal and circular', {'plane': plane, 'circle': circle})
        D['bowl'] = {'xy': circle['center_xy_m'], 'z': float(p[:, 2].mean()), 'radius': circle['radius_m'] - circle['max_radial_error_m'] - max(0.002, 3 * plane['rms_m']), 'frame': r['frame_id']}
    def refresh_mouth(check_table=False):
        records = [v for v in api.recall() if v['key'] == 'initial_measurements']
        require(bool(records), 'Original accepted bowl measurements are unavailable')
        history = api.recall('initial_measurements')['value']
        bad = [e['name'] for e in history['errors']]
        names = [n for n in ['r0', 'r1', 'r2', 'r3', 'r4', 'r5'] if n in history['points'] and n not in bad]
        require(len(names) >= 5, 'Original bowl measurement membership is insufficient')
        reference = arr([history['points'][n]['world_m'] for n in names])
        hp, hc = geo.plane(reference), geo.circle_xy(reference)
        require(hp['coefficients'][2] > 0.97 and hp['rms_m'] < 0.003 and hc['max_radial_error_m'] < 0.004 and hc['largest_angular_gap_rad'] < math.pi, 'Historical bowl fit does not support reuse', {'plane': hp, 'circle': hc})
        require(length(arr(hc['center_xy_m']) - arr(D['bowl']['xy'])) < 0.001 and abs(float(reference[:, 2].mean()) - D['bowl']['z']) < 0.001, 'Saved bowl and reference observations disagree')
        plane = arr(hp['coefficients']); center = arr(hc['center_xy_m'])
        depth_limit = max(0.0045, 3 * hp['rms_m'] + D['u'])
        radial_limit = max(0.0045, hc['max_radial_error_m'] + 2 * D['u'])
        nullable = dict(pixel); nullable['type'] = ['array', 'null']
        mark = {'type': 'object', 'properties': {'camera': {'type': 'string', 'enum': ['agentview', 'robot0_eye_in_hand']}, 'pixel': nullable}}
        f = {'bowl_state': ['same_supported_no_displacement_observed', 'displacement_observed', 'unknown'], 'mouth': ['inner_lip', 'unknown'], 'rim_marks': {'type': 'array', 'items': mark, 'minItems': 6, 'maxItems': 6}}
        seed = D.get('held_state', {}).get('frame_id') == api.state()['frame_id'] and D['phase'] == 'retained'
        if seed:
            f.update(patch_fields); f['patch_identity'] = ['same_package', 'unknown']
        D['bowl_reference'] = {'frame': history['frame'], 'plane': hp, 'circle': hc, 'meaning': 'Historical accepted measurements; reuse requires current identity and geometric consistency'}
        for trial in range(2):
            if trial:
                require(api.state()['budgets']['gpt_remaining'] >= 8, 'Insufficient reviews for a corrective mouth measurement and remaining verification', D.get('mouth_gap'))
            r = review('Revalidate the SAME receiving bowl, not the package or plate. bowl_state=same_supported_no_displacement_observed means the same bowl remains supported and no displacement is observed; it is not a certificate of immobility. Use displacement_observed for contrary evidence and unknown for unresolved identity/support. mouth=inner_lip requires identification of the usable upper opening, not the outer wall or a lower decorative line. Request r0..r4 as up to five separated visible upper-rim surface points, favoring the far and side arcs where the actual rim surface has usable depth. Omit hidden or uncertain points. Earlier front-arc depth samples hit the bowl interior well below the rim: do not call those depths lip measurements. Also return rim_marks: six camera/pixel entries tracing separated VISIBLE points on the actual inner upper opening edge. Use pixel=null for occluded or ambiguous entries. Their calibrated rays will be intersected with the independently measured, revalidated rim plane, so thin-boundary depth is not assumed correct. The markings may cover a partial arc; do not infer a hidden perimeter. If check_table is true request table_probe on exposed original support. If request_patch is true, also return camera and polygon for a currently visible textured interior patch on the cream-cheese package, excluding seams, fingers and background; patch_identity=same_package only if this is unambiguous, otherwise unknown. On correction, use the reported depth/ray discrepancy to select the actual upper lip or another usable view, not repeat a known lower-wall selection.', f, {'saved_bowl': D['bowl'], 'historical_rim_plane': hp, 'historical_opening_circle': hc, 'reference_frame': history['frame'], 'check_table': check_table, 'request_patch': seed, 'correction': D.get('mouth_gap'), 'attempt': trial})
            try:
                par = r['parameters']
                require(par['bowl_state'] == 'same_supported_no_displacement_observed' and par['mouth'] == 'inner_lip', 'Current bowl identity, support, or upper opening unresolved', par)
                depths, diagnostics = [], []
                for name in ['r0', 'r1', 'r2', 'r3', 'r4']:
                    p = points(r, [name])
                    if p is None: continue
                    measured = r['points'][name]
                    try:
                        measured = api.point(measured['camera'], measured['pixel'], radius=1)
                    except Exception as e:
                        log.append({'rim_small_patch_gap': name, 'error': str(e), 'fallback': 'Use the successful review depth with the same consistency checks'})
                    p = arr(measured['world_m'])
                    pe = abs(float(p @ plane[:3] + plane[3]))
                    re = abs(length(p[:2] - center) - hc['radius_m'])
                    accepted = pe <= depth_limit and re <= radial_limit
                    diagnostics.append({'name': name, 'point': p.tolist(), 'plane_error_m': pe, 'radial_error_m': re, 'accepted': accepted})
                    if accepted: depths.append(p)
                values = {'depth_samples': diagnostics, 'plane_limit_m': depth_limit, 'radial_limit_m': radial_limit, 'historical_frame': history['frame'], 'current_frame': r['frame_id']}
                log.append({'rim_depth_validation': values})
                require(len(depths) >= 3, 'Need three separated upper-rim depth samples consistent with the saved bowl; lower-wall hits are excluded', values)
                P = arr(depths); spread = float(np.linalg.svd(P - P.mean(axis=0), compute_uv=False)[1])
                require(spread > 0.008, 'Current rim depths occupy too small an arc to revalidate the bowl', {'second_spread_m': spread})
                rays, ray_u = [], 0.0008
                for item in par['rim_marks']:
                    if item['pixel'] is None: continue
                    try:
                        v = api.plane_point(item['camera'], item['pixel'], hp['coefficients'])
                        p = arr(v['world_m']); cal = api.camera(item['camera'])
                        depth = float(geo.transform(arr([p]), np.linalg.inv(arr(cal['camera_to_world_opencv'])))[0, 2])
                        ray_u = max(ray_u, 2 * depth / min(cal['K'][0][0], cal['K'][1][1]))
                        rays.append(p)
                    except Exception as e: log.append({'rim_ray_gap': str(e)})
                require(len(rays) >= 3, 'Insufficient identifiable visible inner-lip boundary rays')
                current_circle = geo.circle_xy(arr(rays))
                boundary_residuals = np.abs(np.linalg.norm(arr(rays)[:, :2] - center, axis=1) - hc['radius_m'])
                center_error = length(arr(current_circle['center_xy_m']) - center)
                radius_error = abs(current_circle['radius_m'] - hc['radius_m'])
                boundary_limit = hc['max_radial_error_m'] + ray_u + D['u']
                values = {'current_ray_circle': current_circle, 'boundary_residuals_m': boundary_residuals.tolist(), 'center_difference_m': center_error, 'radius_difference_m': radius_error, 'boundary_limit_m': boundary_limit, 'ray_pixel_u_m': ray_u, 'depth_second_spread_m': spread}
                log.append({'rim_boundary_validation': values})
                require(current_circle['largest_angular_gap_rad'] < 4.2 and current_circle['max_radial_error_m'] <= boundary_limit and float(np.max(boundary_residuals)) <= boundary_limit and center_error <= boundary_limit and radius_error <= boundary_limit, 'Current visible opening does not corroborate the historical rim; resolve boundary identity or displacement', values)
                if check_table:
                    p = points(r, ['table_probe'])
                    require(p is not None and abs(float(p[0] @ arr(D['table'][:3]) + D['table'][3])) < 3 * D['u'], 'Supporting table cannot be revalidated')
                D['mouth_gap'] = None
                D['bowl']['validated_frame'] = r['frame_id']
                D['bowl']['reuse_basis'] = 'Same supported bowl, fresh separated rim depths and visible inner-lip rays consistent with accepted historical geometry; not an exact stationarity certificate'
                if seed and par['patch_identity'] == 'same_package':
                    A, B = arr(D['landmarks']), arr(D['held_points'])
                    ac, bc = A.mean(axis=0), B.mean(axis=0)
                    U, sv, V = np.linalg.svd((A - ac).T @ (B - bc)); R = V.T @ U.T
                    if np.linalg.det(R) < 0:
                        V[-1, :] *= -1; R = V.T @ U.T
                    M = np.eye(4); M[:3, :3] = R; M[:3, 3] = bc - R @ ac
                    error = float(np.max(np.linalg.norm(geo.transform(A, M) - B, axis=1)))
                    if error < 0.0001 and api.state()['last_gripper_command'] == 'close':
                        log.append({'registration_restore': 'Recorded measured registration at the unchanged physical frame, not a hand-motion prediction', 'frame': D['held_state']['frame_id'], 'reconstruction_residual_m': error, 'uncertainty_m': D['held_u']})
                        start_tracker(par['camera'], par['polygon'], M, D['held_u'])
                save(D['phase'])
                return
            except Exception as e:
                D['mouth_gap'] = {'reason': str(e), 'frame': r['frame_id'], 'diagnostics': log[-3:]}
                save(D['phase'])
        raise RuntimeError('Bowl revalidation unresolved after one targeted correction; no transfer or release attempted')
    def actuate(gripper, count=4):
        for k in range(count):
            require(api.state()['budgets']['jev_remaining'] > 2, 'No gripper/settling budget')
            s = api.state()
            r = api.control(geo.pad_position(s).tolist(), s['tcp_quaternion_xyzw'], gripper, Q, features={'phase': D.get('phase', 'initialization'), 'purpose': 'bounded gripper transition or settling'}, tool_point='pad_center', steps=3)
            require(r['status'] in ['reached', 'moved'], 'Gripper action stalled', r)
            require(r['choices']['gripper'] == gripper, 'Jev did not deliver the requested gripper choice', r['choices'])
    def move(target, gripper, label, reserve=24):
        target = arr(target)
        fields = {'obstruction': ['external', 'none_observed', 'unknown'], 'visibility': ['usable', 'self_occluded', 'unobserved'], 'action': ['progress', 'upward_view', 'stop']}
        if label == 'grasp descent': fields['jaws'] = ['both_lanes_visible', 'blocked', 'unknown']
        for observation_trial in range(2):
            s = api.state(); pad = geo.pad_position(s)
            r = review('Assess only this proposed motion, not an entire later route. obstruction=external means a visible external object intersects this planned motion, excluding the intended final package contact or bowl release; none_observed is not certified clearance; unknown means uncertain identity/location of a possible external obstruction. visibility distinguishes usable scene evidence, robot/held-item self_occlusion, and genuinely unobserved space. action=progress requires local visible geometry plus supplied measured margins to justify this bounded feedback motion, even if self-occluded; upward_view means only the proposed 15 mm upward observation move is locally supported and would reveal relevant new evidence; stop means neither is justified. Do not treat self-occlusion alone as an external obstacle. For grasp descent, jaws=both_lanes_visible requires visually supported finger approach lanes on opposite package sides; pose alignment alone is insufficient.', fields, {'label': label, 'from_pad': pad.tolist(), 'target_pad': target.tolist(), 'upward_view_target': (pad + arr([0, 0, 0.015])).tolist(), 'quaternion': D['q'], 'object_reference': D['corners'], 'bowl': D['bowl'], 'table': D['table'], 'geometry_margins': D['grasp_geometry'], 'phase': D['phase'], 'observation_trial': observation_trial})
            p = r['parameters']
            require(p['obstruction'] != 'external', 'Observed external obstruction: ' + label)
            if p['action'] == 'progress' and p['obstruction'] == 'none_observed':
                require(label != 'grasp descent' or p['jaws'] == 'both_lanes_visible', 'Finger approach clearance is not observed')
                break
            require(p['action'] == 'upward_view' and observation_trial == 0, 'No justified local action: ' + label, p)
            v = api.drive((pad + arr([0, 0, 0.015])).tolist(), s['tcp_quaternion_xyzw'], 'keep', Q, features={'phase': 'supported observation view'}, tool_point='pad_center', max_calls=6, translation_limit=0.008, steps=3)
            require(v['status'] == 'reached', 'Observation move did not converge', v)
        for lease in range(2):
            s = api.state(); distance = length(target - geo.pad_position(s)); budgets = s['budgets']
            calls = min(40, max(8, int(math.ceil(distance / 0.004)) + 8), budgets['jev_remaining'] - reserve, int(budgets['native_steps_remaining'] / 3) - reserve)
            require(calls >= 3, 'Reserved resources needed for release and verification')
            receipt = api.drive(target.tolist(), D['q'], gripper, Q, features={'phase': label, 'uncertainty_m': D['u'], 'local_evidence_frame': r['frame_id']}, tool_point='pad_center', max_calls=int(calls), translation_limit=0.010 if label in ['grasp descent', 'release descent'] else 0.020, rotation_limit=0.08, steps=3, position_tolerance=0.004, rotation_tolerance=0.04)
            log.append({'motion': label, 'status': receipt['status'], 'error_m': receipt['position_error_m'], 'lease_calls': receipt['lease_calls'], 'frame': receipt['frame_id']})
            D['last_motion'] = log[-1]; save(D['phase'])
            require(receipt['choices']['gripper'] == gripper, 'Unexpected gripper choice during motion', receipt['choices'])
            if receipt['status'] == 'reached': return
            require(receipt['status'] == 'lease_exhausted' and length(geo.pad_position(api.state()) - geo.pad_position(s)) > 0.005, 'Stalled or ineffective motion; no repeated contact push', receipt)
        raise RuntimeError('Bounded motion leases exhausted: ' + label)
    def supplied_release_observation():
        s = api.state(); previous = D.get('last_registration', {})
        require(s['frame_id'] == 255 and previous.get('frame') == 195 and D['phase'] == 'release_alignment', 'Supplied image annotations are valid only at their physical observation frame')
        require(s['last_gripper_command'] == 'close', 'Unexpected gripper state before release observation')
        cam = 'robot0_eye_in_hand'
        annotations = {'frame': 255, 'camera': cam, 'c0': [274, 455], 'c1': [491, 453], 'l0': [358, 511], 'source': 'Visible physical corners at the Cream end and opening of the printed capital C in the supplied frame-255 image; not stationary projections or an api.review response', 'definitions': D['definitions'], 'corner_definitions': D['corner_definitions']}
        cloud = api.cloud(cam, [310, 475, 468, 574], stride=4)
        fit = geo.plane(arr(cloud['world_m'])); plane = arr(fit['coefficients'])
        require(plane[2] > 0.97 and fit['rms_m'] < 0.001 and min(fit['in_plane_spread_m']) > 0.003, 'Current identified interior package surface is not sufficiently planar', fit)
        c0 = api.plane_point(cam, annotations['c0'], plane.tolist())
        c1 = api.plane_point(cam, annotations['c1'], plane.tolist())
        l0 = api.point(cam, annotations['l0'], radius=2)
        B = arr([c0['world_m'], c1['world_m'], l0['world_m']])
        require(abs(float(B[2] @ plane[:3] + plane[3])) <= max(0.001, 3 * fit['rms_m']), 'Identified print landmark depth is inconsistent with its interior face')
        C = arr(D['corners'])[:4]; A = arr([C[0], C[1], D['landmarks'][0]])
        na = arr(geo.plane(C)['coefficients'][:3]); na /= length(na)
        nb = plane[:3] / length(plane[:3])
        ea, eb = A[1] - A[0], B[1] - B[0]
        ea -= na * float(ea @ na); eb -= nb * float(eb @ nb)
        la, lb = length(ea), length(eb)
        cal = api.camera(cam)
        depth = geo.transform(B, np.linalg.inv(arr(cal['camera_to_world_opencv'])))[:, 2]
        edge_u = max(0.0005, 3 * fit['rms_m'], 2 * float(depth.max()) / min(cal['K'][0][0], cal['K'][1][1]))
        require(min(la, lb) > 6 * max(D['u'], edge_u) and abs(la - lb) <= 2 * (D['u'] + edge_u), 'Current Cream-end edge does not match its saved physical identity', {'reference_length_m': la, 'observed_length_m': lb, 'edge_u_m': edge_u})
        ea /= la; eb /= lb
        R = np.column_stack([eb, np.cross(nb, eb), nb]) @ np.column_stack([ea, np.cross(na, ea), na]).T
        anchor = (A[0] + A[1]) / 2
        M = np.eye(4); M[:3, :3] = R; M[:3, 3] = (B[0] + B[1]) / 2 - R @ anchor
        residuals = np.linalg.norm(geo.transform(A, M) - B, axis=1)
        limit = 2 * D['u'] + edge_u
        u = D['u'] + edge_u + float(max(residuals[:2])) + length(C.mean(axis=0) - anchor) * (2 * edge_u / lb + 3 * fit['rms_m'] / min(fit['in_plane_spread_m']))
        values = {'frame': 255, 'reference_frame': D['reference_frame'], 'names': ['c0', 'c1', 'l0'], 'residuals_m': residuals.tolist(), 'validation_limit_m': limit, 'uncertainty_m': u, 'uncertainty_kind': 'Operational geometric floor, not a certified bound', 'source': annotations['source']}
        log.append({'supplied_view_registration': values})
        require(float(residuals.max()) <= limit and u < 0.008, 'Current semantic correspondence or uncertainty is inadequate; no predicted transform substituted', values)
        hp = arr(D['bowl_reference']['plane']['coefficients']); hc = D['bowl_reference']['circle']
        center = arr(hc['center_xy_m']); samples, groups = [], []
        for box in [[318, 361, 450, 407], [175, 395, 290, 495], [480, 395, 601, 495]]:
            rim = api.cloud(cam, box, stride=4); P = arr(rim['world_m'])
            if len(P) < 3:
                groups.append(0); continue
            pe = np.abs(P @ hp[:3] + hp[3]); re = np.abs(np.linalg.norm(P[:, :2] - center, axis=1) - hc['radius_m'])
            selected = P[(pe <= 0.003) & (re <= 0.0035)]
            groups.append(len(selected)); samples.extend(selected.tolist())
        require(len(samples) >= 12 and sum(1 for n in groups if n >= 3) >= 2, 'Current visible upper-rim patches do not revalidate the saved bowl', {'accepted_per_patch': groups})
        P = arr(samples); rim_fit = geo.circle_xy(P)
        spread = float(np.linalg.svd(P - P.mean(axis=0), compute_uv=False)[1])
        dc = length(arr(rim_fit['center_xy_m']) - center); dr = abs(rim_fit['radius_m'] - hc['radius_m'])
        rim_values = {'frame': 255, 'accepted_per_patch': groups, 'second_spread_m': spread, 'center_difference_m': dc, 'radius_difference_m': dr, 'circle': rim_fit, 'source': 'Fresh depth in the far and side upper-rim arcs identified in the supplied image; agreement with the historical plane/circle is a consistency test, not an exact stationarity certificate'}
        log.append({'current_rim_consistency': rim_values})
        require(spread > 0.008 and dc < 0.0045 and dr < 0.0045 and rim_fit['rms_m'] < 0.002, 'Visible rim depths contradict or inadequately constrain the saved bowl', rim_values)
        D['bowl']['validated_frame'] = 255
        D['bowl']['reuse_basis'] = rim_values['source']
        D['surface_measurement'] = {'frame': 255, 'plane': plane.tolist(), 'u': edge_u, 'rms_m': fit['rms_m'], 'spread_m': min(fit['in_plane_spread_m']), 'source': 'Fresh RGB-D at supplied visible interior annotation'}
        D['last_registration'] = {'frame': 255, 'names': ['c0', 'c1', 'l0'], 'points': B.tolist(), 'matrix': M.tolist(), 'u': u}
        D['registration_observations'] = {'frame': 255, 'names': ['c0', 'c1', 'l0'], 'points': B.tolist(), 'visible_corners': {'0': B[0].tolist(), '1': B[1].tolist()}, 'plane': plane.tolist(), 'camera': cam, 'polygon': [[306, 470], [474, 470], [474, 628], [306, 628]]}
        D['supplied_release_annotations'] = annotations
        D['release_review'] = {'frame': 255, 'obstruction': 'none_observed', 'visibility': 'self_occluded', 'bowl_state': 'same_supported_no_displacement_observed', 'action': 'supported', 'source': 'Supplied frame-255 images and fresh geometric consistency checks, NOT an api.review call', 'scope': 'Opening at this pose and 75 mm upward open-hand retreat only, conditional on containment and measured finger-height gates. No external obstruction is visible locally; robot/package occlusion is not a clearance certificate.'}
        save('release_alignment')
    def held(precise=False):
        M, u = observe_object(precise); current = geo.transform(arr(D['landmarks']), M); state = api.state()
        e = geo.attachment_error(D['held_points'], current.tolist(), D['held_state'], state)
        log.append({'retention_continuity_error_m': e, 'allowed_m': u + D['held_u'] + 0.003})
        require(e <= u + D['held_u'] + 0.003, 'Current object motion contradicts measured retention')
        volume = geo.transform(arr(D['corners']), M); outline = D.get('current_outline', {})
        if outline.get('frame') == state['frame_id']:
            C = arr(outline['points']); thickness = (arr(D['corners'])[4:] - arr(D['corners'])[:4]) @ M[:3, :3].T
            volume = np.concatenate([C, C + thickness]); u = outline['u']
            log.append({'footprint_source': outline['source'], 'frame': outline['frame'], 'current_boundary_u_m': u, 'bottom': 'conditional on measured original thickness and observed rigid motion'})
        return M, u, volume, state
    try:
        old = [m for m in api.recall() if m['key'] == 'pick_place']
        if old:
            D.update(api.recall('pick_place')['value']); log.append({'resumed_phase': D['phase'], 'historical_reference_frame': D['reference_frame']})
            if D['phase'] not in ['approaching', 'closing', 'retained', 'release_alignment', 'release_pending', 'released', 'verify', 'done']: refresh_mouth(True)
        else:
            fields = {'task': ['supported_pick_into_bowl', 'unknown'], 'shape_support': ['box_resting_on_table', 'unknown'], 'boundary': ['four_visible_top_corners', 'unknown'], 'corner_camera': ['agentview', 'robot0_eye_in_hand'], 'corners': {'type': 'array', 'items': pixel, 'minItems': 4, 'maxItems': 4}, 'definitions': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 3, 'maxItems': 3}, 'mouth': ['inner_lip', 'unknown']}
            fields.update(patch_fields)
            r = review('User instruction: could you put the cream cheese into the bowl. Identify the requested package and bowl from current images. task=supported_pick_into_bowl only for this relation. shape_support=box_resting_on_table requires visible box sides and evidence of table support; otherwise unknown. Request named regions top (strictly inside the planar package top) and table (bare adjacent support), each with explicit camera, box and stride=4. Request side on a visible package side below its top. boundary=four_visible_top_corners only when all corners belong to that same visible planar face; return their cyclic integer pixels as corners and their corner_camera. Request l0,l1,l2 at three well-spaced noncollinear, uniquely identifiable printed landmarks on the package top; definitions must describe persistent physical print features, not screen-relative directions. Return camera and polygon for a textured interior package patch, preferably from the best texture view. Request r0..r5 at six well-spaced inner bowl lip points, not outer wall or background; mouth=inner_lip only if that identity is observable. Unknown parameters must be stated rather than invented.', fields)
            p = r['parameters']; A = points(r, ['l0', 'l1', 'l2']); side = points(r, ['side'])
            api.checkpoint('initial_measurements', {'frame': r['frame_id'], 'parameters': p, 'points': r['points'], 'errors': r['measurement_errors']})
            require(p['task'] == 'supported_pick_into_bowl' and p['shape_support'] == 'box_resting_on_table' and p['boundary'] == 'four_visible_top_corners', 'Task, support, or package boundary unresolved')
            top, table = geo.plane(region(r, 'top')), geo.plane(region(r, 'table'))
            log.append({'top_plane': top, 'support_plane': table})
            require(top['coefficients'][2] > 0.97 and table['coefficients'][2] > 0.97 and max(top['rms_m'], table['rms_m']) < 0.002, 'Top or support is not adequately planar/horizontal')
            C = arr([api.plane_point(p['corner_camera'], px, top['coefficients'])['world_m'] for px in p['corners']])
            cal = api.camera(p['corner_camera']); depth = geo.transform(C, np.linalg.inv(arr(cal['camera_to_world_opencv'])))[:, 2]
            u = max(0.0015, 3 * top['rms_m'], 3 * table['rms_m'], 2 * float(np.max(depth)) / min(cal['K'][0][0], cal['K'][1][1]))
            base = C.copy(); coeff = arr(table['coefficients']); base[:, 2] = -(base[:, :2] @ coeff[:2] + coeff[3]) / coeff[2]
            center = C.mean(axis=0); height = float(np.mean(C[:, 2] - base[:, 2])); edges = [C[1] - C[0], C[2] - C[1]]
            require(A is not None and side is not None, 'Initial semantic landmarks or visible side depth absent')
            require(height > 3 * u and base[:, 2].min() - u <= side[0, 2] < center[2] - u and abs(float(edges[0] @ edges[1])) < 0.20 * length(edges[0]) * length(edges[1]), 'Measured package geometry is inconsistent', {'height_m': height, 'uncertainty_m': u, 'side_z_m': float(side[0, 2])})
            require(float(np.linalg.svd(A - A.mean(axis=0), compute_uv=False)[1]) > 4 * u, 'Semantic landmarks lack usable spatial spread')
            s = api.state(); q = s['tcp_quaternion_xyzw']; ext = arr(s['own_geometry']['pad_extent_in_tool_m']); axis = int(np.argmax(ext)); R = geo.rotation(q)
            span = abs(s['gripper_qpos_m'][0] - s['gripper_qpos_m'][1]); opening = max(0.0, 2 * span - ext[axis]); width = float(np.ptp(C @ R[:, axis]))
            if width + 2 * (u + 0.0025) >= opening:
                narrow = edges[0] if length(edges[0]) < length(edges[1]) else edges[1]
                angle = (math.atan2(narrow[1], narrow[0]) - math.atan2(R[1, axis], R[0, axis]) + math.pi / 2) % math.pi - math.pi / 2
                q = api.compose(q, [0, 0, angle]); R = geo.rotation(q); width = float(np.ptp(C @ R[:, axis]))
            down = -float(hand_points(s, q, [0, 0, 0])[:, 2].min()); pad_height = float(abs(R[2, :]) @ ext)
            grasp = center.copy(); grasp[2] = max(float(base[:, 2].max()) + down + u + 0.0015, center[2] - pad_height / 2)
            overlap = min(center[2], grasp[2] + pad_height / 2) - max(float(base[:, 2].max()), grasp[2] - pad_height / 2)
            margins = {'opening_proxy_m': opening, 'package_width_m': width, 'uncertainty_m': u, 'pad_overlap_m': overlap, 'finger_down_from_pad_m': down, 'opening_axis_tool': axis}
            log.append({'grasp_geometry': margins})
            require(width + 2 * (u + 0.0025) < opening and overlap > 2 * u, 'No feasible measured grasp clearance; values retained', margins)
            D.update({'reference_frame': r['frame_id'], 'definitions': p['definitions'], 'landmarks': A.tolist(), 'corners': np.concatenate([C, base]).tolist(), 'grasp': grasp.tolist(), 'q': q, 'u': u, 'table': table['coefficients'], 'radius': float(np.max(np.linalg.norm(C[:, :2] - center[:2], axis=1))), 'open_state': s, 'grasp_geometry': margins, 'attempt': 0})
            mouth(r); save('measured'); start_tracker(p['camera'], p['polygon'], np.eye(4), D['u'])
        if D['phase'] in ['measured', 'approaching', 'closing', 'testing']:
            for attempt in range(D.get('attempt', 0), 2):
                D['attempt'] = attempt
                if D['phase'] in ['measured', 'approaching']:
                    resume_descent = D.get('last_motion', {}).get('motion') == 'grasp descent'
                    if resume_descent:
                        require(api.state()['last_gripper_command'] == 'open', 'Unexpected gripper state at interrupted descent')
                        log.append({'resume': 'Assess actual grasp pose without repeating the ineffective descent', 'historical_motion': D['last_motion']})
                    else:
                        M, u = observe_object(); grasp = geo.transform(arr([D['grasp']]), M)[0]
                        require(float(M[2, 2]) > 0.97, 'Package tilted; old grasp geometry no longer applicable')
                        save('approaching'); move(grasp + arr([0, 0, 0.045]), 'open', 'pregrasp hover')
                        M2, u2 = observe_object(); fresh = geo.transform(arr([D['grasp']]), M2)[0]
                        require(length(fresh - grasp) < 0.006, 'Package moved during approach; remeasurement needed')
                        move(fresh, 'open', 'grasp descent')
                    save('closing')
                if D['phase'] == 'closing':
                    if api.state()['last_gripper_command'] == 'open': prepare_grasp()
                    else: require('grasp_ready' in D, 'Interrupted closure lacks its historical contact-transition evidence')
                    actuate('close', 5); M, u = observe_object(); s = api.state()
                    D.update({'test_points': geo.transform(arr(D['landmarks']), M).tolist(), 'test_state': s, 'test_u': u, 'test_target': (geo.pad_position(s) + arr([0, 0, max(0.035, 8 * u + 0.010)])).tolist()}); save('testing')
                move(D['test_target'], 'keep', 'retention measurement lift')
                M, u = observe_object(); B = geo.transform(arr(D['landmarks']), M); s = api.state(); volume = geo.transform(arr(D['corners']), M)
                hand_motion = length(arr(s['tcp_position_world_m']) - arr(D['test_state']['tcp_position_world_m'])); object_motion = length(B.mean(axis=0) - arr(D['test_points']).mean(axis=0))
                error = geo.attachment_error(D['test_points'], B.tolist(), D['test_state'], s); table_z = float(arr(D['corners'])[4:, 2].mean())
                retained = hand_motion > max(0.022, 3 * (u + D['test_u'])) and object_motion > 0.6 * hand_motion and error < u + D['test_u'] + 0.003 and float(volume[:, 2].min()) > table_z + 0.012
                log.append({'retention_test': retained, 'hand_motion_m': hand_motion, 'object_motion_m': object_motion, 'attachment_error_m': error, 'uncertainty_m': u + D['test_u'], 'object_bottom_m': float(volume[:, 2].min())})
                if retained:
                    D.update({'held_points': B.tolist(), 'held_state': s, 'held_u': u}); save('retained'); break
                require(attempt == 0 and object_motion < u + D['test_u'] + 0.003 and abs(float(volume[:, 2].min()) - table_z) < 2 * D['u'], 'Retention failed or ambiguous; do not reopen a possibly held object')
                actuate('open'); save('approaching')
            require(D['phase'] == 'retained', 'Grasp trial bound exhausted')
        if D['phase'] == 'retained' and D.get('last_motion', {}).get('motion') != 'release descent':
            refresh_mouth()
            M, u, volume, s = held(); pad = geo.pad_position(s)
            dz = max(0.0, D['bowl']['z'] + 0.030 + u - float(volume[:, 2].min()))
            if dz > 0.0025: move(pad + arr([0, 0, dz]), 'keep', 'vertical transfer clearance')
            M, u, volume, s = held(); target = geo.pad_position(s); target[:2] += arr(D['bowl']['xy']) - volume[:, :2].mean(axis=0)
            move(target, 'keep', 'transfer above bowl')
            M, u, volume, s = held(); radius = float(np.max(np.linalg.norm(volume[:, :2] - volume[:, :2].mean(axis=0), axis=1)))
            boundary_u = u
            require(radius + D['u'] < D['bowl']['radius'], 'Measured rigid footprint is too large for the mouth; current centering is checked after the release approach', {'object_radius_m': radius, 'shape_u_m': D['u'], 'registration_u_m': boundary_u, 'usable_bowl_radius_m': D['bowl']['radius']})
            target = geo.pad_position(s); target[:2] += arr(D['bowl']['xy']) - volume[:, :2].mean(axis=0)
            finger_bottom = float(hand_points(D['open_state'], D['q'], target)[:, 2].min()); bottom = float(volume[:, 2].min())
            target[2] += D['bowl']['z'] + max(0.004, u + D['u']) - min(bottom, finger_bottom)
            move(target, 'keep', 'release descent'); save('release_alignment')
        if D['phase'] == 'retained':
            require(D.get('last_motion', {}).get('motion') == 'release descent' and D['last_motion']['status'] == 'reached', 'No completed release approach to resume')
            save('release_alignment')
        if D['phase'] == 'release_alignment':
            require(api.state()['budgets']['gpt_remaining'] >= 1, 'Reserve the actual post-release relation review')
            if api.state()['frame_id'] == 255 and D.get('last_registration', {}).get('frame') == 195:
                supplied_release_observation()
            M, u, volume, s = held(); pad = geo.pad_position(s)
            center = volume[:, :2].mean(axis=0); delta = arr(D['bowl']['xy']) - center
            radius = float(np.max(np.linalg.norm(volume[:, :2] - center, axis=1)))
            rim_plane = D.get('bowl_reference', {}).get('plane', {}).get('coefficients', [0, 0, 1, -D['bowl']['z']])
            rim_high = D['bowl']['z'] + D['u'] + D['bowl']['radius'] * length(arr(rim_plane[:2])) / rim_plane[2]
            finger_bottom = float(hand_points(D['open_state'], s['tcp_quaternion_xyzw'], pad)[:, 2].min())
            bottom = float(volume[:, 2].min()); radial = float(np.max(np.linalg.norm(volume[:, :2] - arr(D['bowl']['xy']), axis=1)))
            values = {'object_geometry_frame': s['frame_id'], 'radial_extent_m': radial, 'centered_radius_m': radius, 'registration_u_m': u, 'usable_mouth_radius_m': D['bowl']['radius'], 'centering_delta_xy_m': delta.tolist(), 'object_bottom_m': bottom, 'open_finger_bottom_m': finger_bottom, 'rim_upper_allowance_m': rim_high, 'basis': 'Current measured registration and original rigid dimensions; open-finger geometry is a measured robot invariant. Small above-rim correction uses previously observed local approach space, not certified clearance.'}
            log.append({'release_alignment': values}); D['release_geometry'] = values
            require(s['last_gripper_command'] == 'close', 'Release alignment requires the retained closed-gripper phase')
            require(radius + u < D['bowl']['radius'], 'Even centered, this registration does not resolve mouth fit', values)
            require(length(delta) <= 0.012 and bottom - u > rim_high and finger_bottom - D['u'] > rim_high, 'No justified local above-rim centering correction', values)
            target = pad.copy(); target[:2] += delta
            save('release_alignment')
            if radial + u >= D['bowl']['radius']:
                require(api.state()['budgets']['gpt_remaining'] >= 2, 'Actual containment needs correction, but current remeasurement plus final verification cannot both be funded', values)
                receipt = api.drive(target.tolist(), s['tcp_quaternion_xyzw'], 'keep', Q, features={'phase': 'small above-rim centering correction', 'measured_reference_frame': s['frame_id'], 'centering_delta_xy_m': delta.tolist(), 'object_bottom_margin_m': bottom - u - rim_high, 'open_finger_margin_m': finger_bottom - D['u'] - rim_high}, tool_point='pad_center', max_calls=8, translation_limit=0.003, rotation_limit=0.04, steps=3, position_tolerance=0.0015, rotation_tolerance=0.04)
                log.append({'centering_status': receipt['status'], 'error_m': receipt['position_error_m'], 'lease_calls': receipt['lease_calls'], 'frame': receipt['frame_id'], 'interpretation': 'No repeat lease; assess actual measured geometry, not convergence as a placement predicate'})
                save('release_alignment')
                require(receipt['choices']['gripper'] == 'keep', 'Unexpected gripper choice during centering', receipt)
                require(receipt['status'] in ['reached', 'stalled', 'lease_exhausted'], 'Unrecognized centering failure', receipt)
            else:
                log.append({'centering_action': 'None: current independently measured containment passes', 'containment_margin_m': D['bowl']['radius'] - radial - u, 'center_residual_m': length(delta), 'frame': s['frame_id']})
            actual = api.state(); actual_pad = geo.pad_position(actual)
            D['release_geometry'].update({'current_robot_frame': actual['frame_id'], 'current_pad_world_m': actual_pad.tolist(), 'current_open_finger_bottom_m': float(hand_points(D['open_state'], actual['tcp_quaternion_xyzw'], actual_pad)[:, 2].min()), 'retreat_target_pad_m': (actual_pad + arr([0, 0, 0.075])).tolist()})
            supplied = D.get('supplied_release_annotations', {}).get('frame') == actual['frame_id'] and D.get('last_registration', {}).get('frame') == actual['frame_id'] and D.get('release_review', {}).get('frame') == actual['frame_id']
            if supplied:
                M, u, volume, s = held()
            else:
                require(actual['budgets']['gpt_remaining'] >= 2, 'Need fresh release correspondence/local-action review while preserving final verification')
                M, u, volume, s = held(True)
            radial = float(np.max(np.linalg.norm(volume[:, :2] - arr(D['bowl']['xy']), axis=1)))
            finger_bottom = float(hand_points(D['open_state'], s['tcp_quaternion_xyzw'], geo.pad_position(s))[:, 2].min())
            values = {'frame': s['frame_id'], 'radial_extent_m': radial, 'uncertainty_m': u, 'mouth_radius_m': D['bowl']['radius'], 'containment_margin_m': D['bowl']['radius'] - radial - u, 'object_bottom_m': float(volume[:, 2].min()), 'finger_bottom_m': finger_bottom, 'rim_upper_allowance_m': rim_high}
            log.append({'independently_remeasured_release_geometry': values})
            require(radial + u < D['bowl']['radius'] and float(volume[:, 2].min()) - u > rim_high and finger_bottom - D['u'] > rim_high, 'Fresh release containment or opening-height margin insufficient', values)
            permit = D.get('release_review', {})
            require(permit.get('frame') == s['frame_id'] and permit.get('obstruction') == 'none_observed' and permit.get('bowl_state') == 'same_supported_no_displacement_observed' and permit.get('action') == 'supported', 'Opening or local upward retreat lacks current supporting evidence', permit)
            D['retreat'] = (geo.pad_position(s) + arr([0, 0, 0.075])).tolist(); D['release_q'] = s['tcp_quaternion_xyzw']; D['release_state'] = s
            save('release_pending')
        if D['phase'] == 'release_pending':
            require(D.get('release_review', {}).get('frame') == api.state()['frame_id'], 'Interrupted release requires renewed current transition evidence')
            actuate('open', 5)
            if H[0] is not None:
                t = api.track_update(H[0]); event = {'post_open_registration': t['status'], 'frame': t['frame_id']}
                if t['status'] == 'tracked':
                    event.update({'object_centroid_shift_m': length(arr(t['current_patch_centroid_world_m']) - arr(t['reference_patch_centroid_world_m'])), 'inliers': t['inliers'], 'rms_m': t['rms_m'], 'uncertainty_floor_m': t['uncertainty_floor_m'], 'actual_hand_shift_m': length(arr(api.state()['tcp_position_world_m']) - arr(D['release_state']['tcp_position_world_m'])), 'meaning': 'Transition observation only; final review must resolve release and placement'})
                else: event['reason'] = t['reason']
                log.append(event)
            save('released')
        if D['phase'] == 'released':
            receipt = api.drive(D['retreat'], D['release_q'], 'open', Q, features={'phase': 'locally supported open-hand upward retreat', 'release_review_frame': D['release_review']['frame']}, tool_point='pad_center', max_calls=30, translation_limit=0.012, rotation_limit=0.04, steps=3, position_tolerance=0.004, rotation_tolerance=0.04)
            log.append({'post_release_retreat': receipt['status'], 'frame': receipt['frame_id'], 'error_m': receipt['position_error_m']}); save('released')
            require(receipt['status'] == 'reached' and receipt['choices']['gripper'] == 'open', 'Post-release retreat failed; no repeated contact push', receipt)
            save('verify')
        require(D['phase'] in ['verify', 'done'], 'Unsupported checkpoint phase')
        poly = dict(polygon); poly['type'] = ['array', 'null']
        f = {'relation': ['inside', 'on_rim', 'outside', 'unknown'], 'stability': ['resting', 'moving_or_contact', 'unknown'], 'patch_identity': ['same_package', 'unknown'], 'camera': ['agentview', 'robot0_eye_in_hand'], 'polygon': poly}
        r = review('Assess actual post-release placement. relation=inside means the cream cheese is in the bowl cavity, not merely overlapping the bowl in projection or balanced on its rim; otherwise on_rim, outside, or unknown. stability=resting requires visible support with no ongoing fall, sliding, or robot contact; otherwise moving_or_contact or unknown. Return camera and a polygon strictly within a uniquely recognizable textured visible surface of this same package, excluding fingers, bowl and background; patch_identity=same_package only if unambiguous, otherwise unknown and polygon=null. Also request named region stable_patch, a small textured rectangle strictly inside that same visible package surface, with explicit camera, box and stride=4. It will support an independent fixed-view temporal RGB-D comparison if the tracker fails. Do not substitute intended release for observed placement.', f, {'receiving_bowl': D['bowl'], 'package_definitions': D['definitions'], 'release_review': D.get('release_review'), 'purpose': 'Final relation and a fresh temporal stability reference'})
        par = r['parameters']; D['placement_observation'] = {'frame': r['frame_id'], 'parameters': par}; save('verify')
        require(par['relation'] == 'inside' and par['stability'] == 'resting' and par['patch_identity'] == 'same_package', 'Actual final cavity relation or rest is unresolved', par)
        handle = None
        if par['polygon'] is not None:
            try: handle = api.track_init(par['camera'], par['polygon'])['handle']
            except Exception as e: log.append({'final_tracker_initialization_gap': str(e)})
        base = r['regions'].get('stable_patch')
        if 'stable_patch' in [e['name'] for e in r['measurement_errors']]: base = None
        require(handle is not None or base is not None, 'No obtainable temporal stability measurement remains')
        state0 = api.state(); actuate('keep', 5); state1 = api.state(); stable = False
        if handle is not None:
            t = api.track_update(handle)
            if t['status'] == 'tracked':
                spread = sorted(arr(t['inlier_spread_m']).reshape(-1).tolist(), reverse=True)
                displacement = float(np.max(np.linalg.norm(arr(t['current_inlier_world_m']) - arr(t['reference_inlier_world_m']), axis=1)))
                stable = t['inliers'] >= 12 and t['inliers'] / max(1, t['matches']) >= 0.65 and t['rms_m'] <= 0.0015 and len(spread) >= 2 and spread[1] > 0.003 and t['uncertainty_floor_m'] <= 0.002 and displacement + t['uncertainty_floor_m'] <= 0.004
                log.append({'post_release_temporal_tracking': bool(stable), 'frame': t['frame_id'], 'reference_frame': t['reference_frame_id'], 'inliers': t['inliers'], 'rms_m': t['rms_m'], 'max_corresponding_motion_m': displacement, 'uncertainty_floor_m': t['uncertainty_floor_m']})
            else: log.append({'post_release_tracker_unknown': t['reason'], 'frame': t['frame_id']})
        if not stable and base is not None:
            fixed_view = base['camera'] == 'agentview' or (length(arr(state1['tcp_position_world_m']) - arr(state0['tcp_position_world_m'])) < 0.0005 and length(geo.rotation(state1['tcp_quaternion_xyzw']) - geo.rotation(state0['tcp_quaternion_xyzw'])) < 0.002)
            if fixed_view:
                now = api.cloud(base['camera'], base['box'], stride=base['stride'])
                lookup = {tuple(p): i for i, p in enumerate(now['pixels'])}
                pairs = [(i, lookup[tuple(p)]) for i, p in enumerate(base['pixels']) if tuple(p) in lookup]
                if len(pairs) >= 12 and len(pairs) >= 0.9 * len(base['pixels']):
                    ia, ib = [p[0] for p in pairs], [p[1] for p in pairs]
                    a, b = arr(base['rgb'])[ia], arr(now['rgb'])[ib]
                    scale = 255.0 if max(float(a.max()), float(b.max())) > 1.0 else 1.0
                    texture = float(np.max(np.std(a / scale, axis=0)))
                    rgb_error = np.max(np.abs(a - b), axis=1) / scale
                    depth_change = np.linalg.norm(arr(base['world_m'])[ia] - arr(now['world_m'])[ib], axis=1)
                    fraction = float(np.mean((rgb_error < 0.04) & (depth_change < 0.0025)))
                    stable = texture > 0.04 and fraction >= 0.95
                    log.append({'fixed_view_textured_RGBD_stability': bool(stable), 'reference_frame': base['frame_id'], 'frame': now['frame_id'], 'samples': len(pairs), 'texture_std': texture, 'unchanged_fraction': fraction, 'meaning': 'Temporal surface evidence with unchanged calibrated view; not a recovered transform or contact sensor'})
        log.append({'completion_proposed': bool(stable), 'final_relation': par['relation'], 'temporal_native_steps': state1['native_steps'] - state0['native_steps'], 'limitation': 'Observed cavity placement and bounded temporal stability, not certified collision clearance or native evaluator access'})
        save('done' if stable else 'verify')
        return {'completion_proposed': bool(stable), 'evidence': log}
    except Exception as e:
        log.append({'stopped': str(e), 'phase': D.get('phase', 'measurement'), 'policy': 'No automatic reopen or repeated stalled push; checkpoint data are historical, not current sensing'})
        return {'completion_proposed': False, 'evidence': log}

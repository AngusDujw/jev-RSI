def main(api):
    key = 'measured_transfer_v1'
    M = {'phase': 'new', 'evidence': [], 'request': 'could you put the cream cheese into the bowl'}
    for record in api.recall():
        if record['key'] == key: M = api.recall(key)['value']
    for name in M.pop('saved_components', []):
        M[name] = api.recall(key + '.' + name)['value']
    G = M.get('geometry')
    pixel = {'type': 'array', 'items': {'type': 'integer', 'minimum': 0, 'maximum': 767}, 'minItems': 2, 'maxItems': 2}
    nullable_pixel = dict(pixel); nullable_pixel['type'] = ['array', 'null']
    uv3 = {'type': 'array', 'items': nullable_pixel, 'minItems': 3, 'maxItems': 3}
    labels3 = {'type': 'array', 'items': 'string', 'minItems': 3, 'maxItems': 3}
    cameras = ['agentview', 'robot0_eye_in_hand']
    Q = {}
    for axis in ['x', 'y', 'z', 'rx', 'ry', 'rz']:
        Q[axis] = {'type': 'choice', 'instructions': 'For world axis ' + axis + ', use state.processed_features.axes.' + axis + '.goal_relation. Select positive for increase, negative for decrease, hold for within_tolerance. Rotation signs are world rotation-vector signs. Do not calculate geometry or infer object contact.', 'criteria': {'negative': 'The selected axis relation is decrease.', 'hold': 'The selected axis relation is within_tolerance.', 'positive': 'The selected axis relation is increase.'}}
    Q['gripper'] = {'type': 'choice', 'instructions': 'Use state.processed_features.objective.gripper exactly. This is a requested jaw action, not a claim of grasp success.', 'criteria': {'open': 'The objective requests open.', 'close': 'The objective requests close.', 'keep': 'The objective requests keep; do not reopen a carried item.'}}
    written = {}
    def storage_bound(value):
        if isinstance(value, str):
            return 2 + sum(2 if c in ['"', '\\'] else (1 if ' ' <= c <= '~' else 12) for c in value)
        if isinstance(value, dict):
            return 2 + sum(storage_bound(k) + storage_bound(v) + 4 for k, v in value.items())
        if isinstance(value, (list, tuple)):
            return 2 + sum(storage_bound(v) + 2 for v in value)
        return len(str(value)) + 8
    def save(event=None):
        events = M.get('evidence', []) + ([] if event is None else [event]); kept = []
        for item in events[-8:]:
            if storage_bound(item) > 6000:
                item = {'diagnostic_excerpt': str(item)[:360], 'diagnostic_truncated': True}
            kept.append(item)
        for j in range(8):
            if storage_bound(kept) <= 6000: break
            kept = kept[1:]
        M['evidence'] = kept
        names = [name for name in ['geometry', 'grasp_geometry', 'preclosure', 'retention_test', 'last_retention'] if name in M]
        core = {name: value for name, value in M.items() if name not in names}
        core['saved_components'] = names
        writes = [(key + '.' + name, M[name]) for name in names] + [(key, core)]
        for address, value in writes:
            size = storage_bound(value)
            if size > 14000: raise ValueError('Essential checkpoint component exceeds conservative byte bound: ' + address + ' estimated_bytes=' + str(size))
        for address, value in writes:
            signature = str(value)
            if written.get(address) != signature:
                api.checkpoint(address, value); written[address] = signature
    def review(question, fields, context=None):
        if api.state()['budgets']['gpt_remaining'] < 1: raise ValueError('No observation-review budget remains')
        r = api.review(question, context={'instruction': M['request'], 'phase': M['phase'], 'reference': context}, fields=fields)
        if r['measurement_errors']: save({'measurement_errors': r['measurement_errors'], 'frame_id': r['frame_id']})
        if r['status'] == 'stop': raise ValueError('Observation review stopped: ' + r['explanation'])
        return r
    def fitted(r, name):
        if name not in r['regions']: raise ValueError('Missing measured region ' + name + ': ' + str(r['measurement_errors']))
        p = np.asarray(r['regions'][name]['world_m'], dtype=float)
        if len(p) < 9: raise ValueError('Too few surface samples in ' + name)
        for j in range(2):
            f = geo.plane(p); c = np.asarray(f['coefficients']); d = np.abs(p @ c[:3] + c[3])
            keep = d <= max(0.002, 2.5 * float(f['rms_m']))
            if int(np.sum(keep)) >= 9: p = p[keep]
        f = geo.plane(p)
        if f['rms_m'] > 0.0025 or min(f['in_plane_spread_m']) < 0.0015: raise ValueError('Unusable ' + name + ' plane: ' + str(f))
        return f
    def destination(r):
        pts = [r['points']['r' + str(i)]['world_m'] for i in range(6) if 'r' + str(i) in r['points']]
        if len(pts) < 4 or 'floor' not in r['points']: raise ValueError('Need four valid distributed rim points and a separate interior measurement: ' + str(r['measurement_errors']))
        a = np.asarray(pts); pl = geo.plane(a); cir = geo.circle_xy(a); u = max(0.001, 2 * pl['rms_m'], 2 * cir['rms_m'])
        interior = np.asarray(r['points']['floor']['world_m']); center = np.asarray(cir['center_xy_m'])
        if pl['coefficients'][2] < 0.97 or u > 0.005 or cir['max_radial_error_m'] > 0.006 or cir['largest_angular_gap_rad'] > 3.8: raise ValueError('Rim fit inadequate: ' + str({'plane': pl, 'circle': cir}))
        if interior[2] >= float(np.mean(a[:, 2])) - 3 * u or np.linalg.norm(interior[:2] - center) >= cir['radius_m']: raise ValueError('Interior depth does not establish an open receptacle')
        return {'xy': center.tolist(), 'z': float(np.max(a[:, 2])), 'radius': float(cir['radius_m']), 'u': float(u), 'frame_id': r['frame_id'], 'rim': pts, 'floor': interior.tolist()}
    def bind_patch(camera, polygon, transform):
        if M.get('patch_trials', 0) >= 5: return
        M['patch_trials'] = M.get('patch_trials', 0) + 1
        try:
            t = api.track_init(camera, polygon)
            G['patch'] = {'receipt': t, 'surface': G['source'], 'polygon': polygon, 'reference_transform': np.asarray(transform).tolist()}
            save({'patch_created': t, 'surface': G['source']})
        except Exception as e: save({'patch_initialization_failed': str(e)})
    def observed(T, u, via, quality):
        return {'c': geo.transform(G['corners'], T).tolist(), 'v': geo.transform(G['vertices'], T).tolist(), 'f': geo.transform(G['fiducials'], T).tolist(), 'u': float(u), 'via': via, 'quality': quality, 'frame_id': api.state()['frame_id']}
    def run(target, quaternion, gripper, calls=14, tolerance=0.002):
        b = api.state()['budgets']; count = min(calls, b['jev_remaining'], b['native_steps_remaining'] // 3)
        if count < 1: raise ValueError('No physical control budget remains')
        M['intent'] = {'target_pad': np.asarray(target).tolist(), 'quaternion': np.asarray(quaternion).tolist(), 'gripper': gripper, 'frame_id': api.state()['frame_id']}; save()
        r = api.drive(target=np.asarray(target).tolist(), quaternion=np.asarray(quaternion).tolist(), gripper=gripper, questions=Q, features={'phase': M['phase'], 'intent': M['intent'], 'measurement_evidence': M['evidence'][-1:]}, tool_point='pad_center', translation_limit=0.02, rotation_limit=0.10, steps=3, position_tolerance=tolerance, rotation_tolerance=0.035, max_calls=int(count))
        save({'control_status': r['status'], 'position_error_m': r['position_error_m'], 'rotation_error_rad': r['rotation_error_rad'], 'lease_calls': r['lease_calls'], 'choices': r['choices'], 'frame_id': r['frame_id']})
        if r['status'] == 'stalled' or r['choices']['gripper'] != gripper: raise ValueError('Stopped after stall or unexpected jaw decision')
        if r['status'] not in ['reached', 'lease_exhausted']: raise ValueError('Unexpected drive status ' + r['status'])
        return r
    def observe(purpose='registration'):
        why = 'No registered patch'
        for attempt in range(2):
            candidate = None; patch = G.get('patch')
            if patch is not None:
                t = api.track_update(patch['receipt']['handle'])
                if t['status'] == 'tracked':
                    pts = np.asarray(t['reference_inlier_world_m']); spread = np.linalg.svd(pts - np.mean(pts, axis=0), compute_uv=False)[1] / math.sqrt(len(pts)); u = max(G['u'], t['uncertainty_floor_m'], 2 * t['rms_m'])
                    if t['inliers'] >= 10 and t['inliers'] / max(1, t['matches']) >= 0.55 and t['rms_m'] <= 0.0025 and u <= 0.004 and spread >= 2 * u:
                        T = np.asarray(t['transform_initial_world_to_current_world']) @ np.asarray(patch['reference_transform'])
                        candidate = observed(T, u, 'rgbd_registration', {k: t[k] for k in ['inliers', 'matches', 'rms_m', 'uncertainty_floor_m', 'reference_frame_id', 'frame_id']})
                        if purpose == 'registration': return candidate
                    why = 'Registration quality: ' + str({'inliers': t['inliers'], 'rms_m': t['rms_m'], 'u': u, 'spread': float(spread)})
                else: why = 'Unknown registration: ' + t['reason']
            if 'recovery_edge' not in G:
                C = np.asarray(G['corners']); mark = np.asarray(G['fiducials'][0]); short_ids = sorted(range(4), key=lambda i: float(np.linalg.norm(C[(i + 1) % 4] - C[i])))[:2]
                ranked = sorted([(float(np.linalg.norm((C[i] + C[(i + 1) % 4]) / 2 - mark)), i) for i in short_ids])
                if ranked[1][0] - ranked[0][0] <= 4 * G['u']: raise ValueError('Reference mark does not distinguish a short end: ' + str(ranked))
                i = ranked[0][1]; G['recovery_edge'] = {'definition': 'Short end boundary of the SAME broad printed face nearest saved print landmark 0: ' + G['labels'][0], 'world': [G['corners'][i], G['corners'][(i + 1) % 4]], 'reference_frame_id': G['frame_id']}; save()
            fields = {'camera': cameras, 'landmarks': uv3, 'identity': ['unambiguous', 'ambiguous', 'unknown'], 'edge': {'type': 'array', 'items': nullable_pixel, 'minItems': 2, 'maxItems': 2}, 'edge_identity': ['identified', 'unknown'], 'patch_polygon': {'type': ['array', 'null'], 'items': pixel, 'minItems': 3, 'maxItems': 16}, 'patch_surface': 'string', 'view': ['up', 'none']}
            extra = ''
            if purpose == 'approach':
                fields.update({'obstruction': ['observed', 'none_observed', 'undetermined'], 'visibility': ['adequate', 'self_occlusion', 'unobserved_other'], 'action': ['advance', 'model_check', 'stop'], 'bowl_profile': ['round_tapered', 'other', 'unknown'], 'support': ['same_contact', 'same_surface_occluded', 'different', 'unknown']})
                extra = ' Assess ONLY approach_plan.waypoints and its quaternion. obstruction=observed requires positively observed external interference; none_observed means none seen, NOT certified clearance; undetermined means unresolved. visibility distinguishes adequate local evidence, hand/item self_occlusion, and unobserved_other. advance requires positive local evidence for these open-finger segments, not visibility of a later corridor. NEW resolvable question: if the sole missing local fact is the bowl boundary hidden by the hand, action=model_check permits code to test a circular exterior envelope, NOT to assume clearance. It requires bowl_profile=round_tapered: the identified bowl has a visibly approximately horizontal circular outer upper lip, with visible exterior narrowing below it and no handle, bulge or other interfering object. For model_check request named points o0 through o5 distributed on clean visible OUTER upper lip samples, not inner lip, floor or silhouette-mixed depth. Omit hidden samples. Code will fit and compare this model with the actual finger sweep; no full outline is required. other means contrary shape evidence; unknown means inadequate evidence. model_check is forbidden when any OTHER external space or obstacle remains unresolved. stop otherwise; an absent plan forbids motion. Request region table on the same visible tabletop beside the source, explicit camera, box and stride 4. support=same_contact requires a visible source/table junction; same_surface_occluded requires identifiable placement on the same stationary table with consistent visible side/surroundings, only hand-hidden junction and no lifting, tipping or intervening support. different means contrary support; unknown means insufficient evidence. Code independently checks the registered base against this measured table, not a newly observed hidden underside.'
            if purpose == 'preclosure':
                fields['enclosure'] = ['visible_straddle', 'consistent_self_occlusion', 'blocked', 'unknown']
                extra = ' Also inspect actual open pads: enclosure=visible_straddle means visible clearance outside opposing narrow sides; consistent_self_occlusion means measured geometry and visible portions support that enclosure with only hand occlusion. blocked means top/support/obstacle interference; unknown means unresolved. This permits closure, not a grasp claim.'
            if purpose == 'contact':
                fields.update({'contact': ['opposing_contacts', 'occluded_plausible', 'not_enclosed', 'unknown'], 'probe': ['advance', 'stop']})
                extra = ' Also inspect the actual closure effect. contact=opposing_contacts means visible opposing pad/item contacts; occluded_plausible means the item remains enclosed and only the hand hides contacts; not_enclosed and unknown forbid lifting. probe=advance additionally requires positive local overhead evidence for a bounded vertical retention test of at most 40mm, keeping orientation and closed jaws. This is not retention evidence.'
            r = review('Recover the SAME broad artwork-bearing face containing the saved print marks, NOT an adjacent narrow end face. camera selects the measurement view. landmarks are current pixels for the saved physical definitions, null if hidden. identity=unambiguous means every supplied nonnull mark is genuinely identified; ONE mark can qualify. Request named region top strictly inside that broad face, same camera, explicit box, stride 4. edge gives two separated currently visible pixels ON the saved short-end boundary, not necessarily its corners; edge_identity=identified only for that physical boundary. Hidden ends need not be invented. One mark, that face plane and an identified edge segment can resolve pose; two separated marks are another option. patch_polygon may select a larger visible textured object-only patch in the same camera, including adjacent rigid printed faces but excluding hand/background; patch_surface describes its physical identity, or use null polygon and explain absence. Historical projections are not detections. view=up permits only a locally justified 15mm upward observation move with overhead evidence; otherwise none. When supplied current tracker quality is valid, recovery landmarks, edge pixels and the top region may be omitted; use null pixels and unknown visual identity where appropriate. Their absence alone is not an action veto. The separate phase-specific evidence still must be assessed.' + extra, fields, {'source': G['source'], 'labels': G['labels'], 'fiducials_world_reference': G['fiducials'], 'reference_camera': G['reference_camera'], 'reference_pixels': G['landmark_pixels'], 'edge_reference': G['recovery_edge'], 'failure': why, 'current_track': candidate, 'grasp_geometry': M.get('grasp_geometry'), 'approach_plan': M.get('approach_plan')})
            p = r['parameters']; s = api.state()
            if purpose == 'approach':
                M.pop('approach_permission', None)
                if p['obstruction'] == 'observed' or p['visibility'] == 'unobserved_other' or p['action'] == 'stop': raise ValueError('Local approach not justified: ' + r['explanation'])
                if p['action'] == 'model_check':
                    if p['bowl_profile'] != 'round_tapered': raise ValueError('No supported circular exterior model')
                    outer = [r['points']['o' + str(i)]['world_m'] for i in range(6) if 'o' + str(i) in r['points']]
                    if len(outer) < 4: raise ValueError('Need four valid outer-lip samples for the self-occluded local bowl boundary: ' + str(r['measurement_errors']))
                    a = np.asarray(outer); pl = geo.plane(a); cir = geo.circle_xy(a); D = G['destination']; u = max(0.0015, 2 * pl['rms_m'], 2 * cir['rms_m']); bc = np.asarray(cir['center_xy_m']); radius = float(cir['radius_m'])
                    span = float(np.max(np.linalg.norm(a[:, None, :2] - a[None, :, :2], axis=2))); minor = float(np.linalg.svd(a[:, :2] - np.mean(a[:, :2], axis=0), compute_uv=False)[1] / math.sqrt(len(a)))
                    center_error = float(np.linalg.norm(bc - np.asarray(D['xy']))); height_error = abs(float(np.mean(a[:, 2])) - D['z']); plan = M['approach_plan']; own = s['own_geometry']; offset = np.asarray(own['pad_center_in_tool_m']); lo = np.asarray(own['finger_low_offset_tool_m']) - offset; hi = np.asarray(own['finger_high_offset_tool_m']) - offset
                    box = np.asarray([[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]]); R0 = geo.rotation(s['tcp_quaternion_xyzw']); R1 = geo.rotation(plan['quaternion']); angle = math.acos(float(np.clip((np.trace(R1 @ R0.T) - 1) / 2, -1, 1)))
                    envelope = np.vstack([box @ R0.T, box @ R1.T]); low = np.min(envelope[:, :2], axis=0); high = np.max(envelope[:, :2], axis=0); gaps = []
                    for start, end in zip(plan['waypoints'][:-1], plan['waypoints'][1:]):
                        pair = np.asarray([start, end]); lower = np.min(pair[:, :2], axis=0) + low; upper = np.max(pair[:, :2], axis=0) + high; separation = np.maximum(np.maximum(lower - bc, bc - upper), 0)
                        gaps.append(float(np.linalg.norm(separation)) - radius)
                    margin = 2 * u + 0.003
                    diagnostic = {'outer_radius_m': radius, 'rms_m': float(cir['rms_m']), 'max_radial_error_m': float(cir['max_radial_error_m']), 'angular_gap_rad': float(cir['largest_angular_gap_rad']), 'span_m': span, 'minor_m': minor, 'center_difference_m': center_error, 'height_difference_m': height_error, 'segment_separations_m': gaps, 'required_separation_m': margin, 'orientation_change_rad': angle, 'frame_id': r['frame_id'], 'limitation': 'Current visible circular/tapered exterior model plus measured own envelope; not a collision certificate.'}
                    save({'local_bowl_model': diagnostic})
                    if pl['coefficients'][2] < 0.97 or u > 0.004 or cir['max_radial_error_m'] > 2 * u or cir['largest_angular_gap_rad'] > 4.4 or span < radius or minor < 2 * u or center_error > 3 * (u + D['u']) or height_error > 3 * (u + D['u']) or radius < D['radius'] - u or angle > 0.04 or not gaps or min(gaps) <= margin: raise ValueError('Local exterior model cannot justify this approach: ' + str(diagnostic))
                elif p['action'] != 'advance' or p['obstruction'] != 'none_observed': raise ValueError('Unresolved local approach evidence: ' + r['explanation'])
                if p['support'] not in ['same_contact', 'same_surface_occluded']: raise ValueError('Current source support unresolved: ' + r['explanation'])
                sf = fitted(r, 'table'); su = max(0.001, 2 * sf['rms_m']); previous_plane = np.asarray(G['support_plane'])
                difference = abs(float(np.dot(previous_plane[:3], sf['center_world_m']) + previous_plane[3]))
                save({'support_plane_refresh': {'fit': sf, 'reference_plane_difference_m': difference, 'u_m': su, 'visual_support': p['support'], 'frame_id': r['frame_id']}})
                if sf['coefficients'][2] < 0.97 or difference > 3 * (G['u'] + su): raise ValueError('Measured tabletop disagrees with stationary support reference: ' + str({'difference_m': difference, 'u_m': su, 'plane': sf['coefficients']}))
                G['support_plane'] = sf['coefficients']; G['support_validation'] = {'u': su, 'frame_id': r['frame_id'], 'camera': r['regions']['table']['camera'], 'visual_support': p['support'], 'rms_m': sf['rms_m']}
                plan = M['approach_plan']
                M['approach_permission'] = {'waypoints': plan['waypoints'], 'next': 0, 'tube': 0.003, 'quaternion': plan['quaternion'], 'frame_id': r['frame_id']}; save()
            if purpose == 'preclosure' and p['enclosure'] not in ['visible_straddle', 'consistent_self_occlusion']: raise ValueError('No justified closure: ' + r['explanation'])
            if purpose == 'contact':
                M['contact_observation'] = {'contact': p['contact'], 'probe': p['probe'], 'frame_id': r['frame_id']}; save()
                if p['contact'] not in ['opposing_contacts', 'occluded_plausible'] or p['probe'] != 'advance': raise ValueError('No justified retention probe: ' + r['explanation'])
            if candidate is not None: return candidate
            try:
                if p['identity'] != 'unambiguous': raise ValueError('Ambiguous physical correspondence')
                f = fitted(r, 'top'); n1 = np.asarray(f['coefficients'][:3]); n0 = np.asarray(G['normal']); ids = [i for i in range(3) if p['landmarks'][i] is not None]; u = max(G['u'], 2 * f['rms_m'], 0.001)
                if not ids or n1[2] < 0.7 or r['regions']['top']['camera'] != p['camera']: raise ValueError('Insufficient face/landmark evidence')
                current = np.asarray([api.plane_point(p['camera'], p['landmarks'][i], f['coefficients'])['world_m'] for i in ids]); reference = np.asarray(G['fiducials'])[ids]; trials = []
                if len(ids) >= 2:
                    length, i, j = max([(float(np.linalg.norm(reference[j] - reference[i])), i, j) for i in range(len(ids)) for j in range(i + 1, len(ids))])
                    a = reference[j] - reference[i]; b = current[j] - current[i]
                    if length < 6 * u or abs(np.linalg.norm(b) - length) > 3 * u: raise ValueError('Landmark spacing inconsistent: ' + str([length, float(np.linalg.norm(b)), u]))
                    trials = [(a, b, None)]
                elif p['edge_identity'] == 'identified' and all(v is not None for v in p['edge']):
                    A = np.asarray(G['recovery_edge']['world']); E = np.asarray([api.plane_point(p['camera'], v, f['coefficients'])['world_m'] for v in p['edge']]); span = float(np.linalg.norm(E[1] - E[0])); length = float(np.linalg.norm(A[1] - A[0]))
                    if span < 6 * u or span > length + 3 * u: raise ValueError('Edge sample span inadequate: ' + str({'span': span, 'reference_length': length, 'u': u}))
                    trials = [(A[1] - A[0], E[1] - E[0], E), (A[1] - A[0], E[0] - E[1], E[::-1])]
                else: raise ValueError('Need another identified mark OR a visible identified boundary segment')
                accepted = []; residuals = []
                for a, b, edge in trials:
                    a = a - n0 * np.dot(a, n0); b = b - n1 * np.dot(b, n1); a /= np.linalg.norm(a); b /= np.linalg.norm(b)
                    R = np.column_stack([b, np.cross(n1, b), n1]) @ np.column_stack([a, np.cross(n0, a), n0]).T; T = np.eye(4); T[:3, :3] = R; T[:3, 3] = np.mean(current - reference @ R.T, axis=0)
                    residual = float(np.max(np.linalg.norm(geo.transform(reference, T) - current, axis=1)))
                    if edge is not None:
                        predicted = geo.transform(A, T); along = (edge - predicted[0]) @ b
                        residual = max(residual, float(np.max(np.linalg.norm(np.cross(predicted - edge[0], b), axis=1))), float(max(0, -np.min(along), np.max(along) - length)))
                    residuals.append(residual)
                    if residual <= 3 * u: accepted.append(T)
                save({'registration_hypothesis_residuals_m': residuals, 'u_m': u, 'ids': ids, 'plane_rms_m': f['rms_m'], 'frame_id': r['frame_id']})
                if len(accepted) != 1: raise ValueError('Ambiguous/inconsistent registration hypotheses: ' + str(residuals))
                T = accepted[0]
                if p['patch_polygon'] is not None:
                    bind_patch(p['camera'], p['patch_polygon'], T)
                    if G.get('patch') is not None and G['patch']['receipt']['frame_id'] == r['frame_id']:
                        G['patch']['surface_definition'] = p['patch_surface']; save()
                return observed(T, u, 'identified_face_marks_or_edge', {'residuals_m': residuals, 'ids': ids, 'frame_id': r['frame_id'], 'uncertainty': 'Heuristic measurement allowance, not calibrated confidence'})
            except Exception as e: why = str(e); save({'registration_recovery_gap': why})
            if attempt == 0 and purpose == 'registration' and p['view'] == 'up' and api.state()['budgets']['jev_remaining'] > 18:
                s = api.state(); run(np.asarray(geo.pad_position(s)) + [0, 0, 0.015], s['tcp_quaternion_xyzw'], 'keep', 6)
            else: break
        raise ValueError('No justified current object registration: ' + why)
    def attached(old, new, s0, s1, test=False):
        error = float(geo.attachment_error(old['f'], new['f'], s0, s1)); tol = max(0.004, 2 * (old['u'] + new['u']) + 0.001)
        hand = np.asarray(s1['tcp_position_world_m']) - np.asarray(s0['tcp_position_world_m']); item = np.mean(np.asarray(new['f']) - np.asarray(old['f']), axis=0); distance = float(np.linalg.norm(hand))
        save({'attachment_error_m': error, 'tolerance_m': tol, 'actual_hand_translation_m': hand.tolist(), 'observed_object_translation_m': item.tolist(), 'observation': new['quality']})
        if tol > 0.012 or error > tol: raise ValueError('Retention unresolved or relative slip exceeds measured tolerance')
        if test and (distance < 0.018 or hand[2] < 0.018 or float(np.dot(item, hand)) < 0.65 * distance * distance): raise ValueError('Lift did not independently demonstrate retained object motion')
    def approve_transfer(o, s):
        D = G['destination']; pad = np.asarray(geo.pad_position(s)); q = s['tcp_quaternion_xyzw']; R = geo.rotation(q); own = s['own_geometry']; offset = np.asarray(own['pad_center_in_tool_m']); lo = np.asarray(own['finger_low_offset_tool_m']) - offset; hi = np.asarray(own['finger_high_offset_tool_m']) - offset
        finger_z = float(np.min((np.asarray([[x, y, z] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z in [lo[2], hi[2]]]) @ R.T)[:, 2])); bottom = float(np.min(np.asarray(o['v'])[:, 2]) - pad[2]); center = np.mean(np.asarray(o['c']), axis=0); xy = np.asarray(D['xy']) - (center - pad)[:2]
        safe_z = max(float(pad[2]), D['z'] + 0.03 - min(finger_z, bottom)); margin = max(0.006, 2 * (o['u'] + D['u']) + 0.002); low_z = D['z'] + margin - min(finger_z, bottom); tube = 2 * (o['u'] + D['u']) + 0.003
        path = [pad.tolist(), [float(pad[0]), float(pad[1]), safe_z], [float(xy[0]), float(xy[1]), safe_z], [float(xy[0]), float(xy[1]), low_z]]
        if M.get('transfer_review_reusable', False):
            permit = M['route_permission']; prior = np.asarray(permit['waypoints']); allowance = permit['tube']; angle = math.acos(float(np.clip((np.trace(R @ geo.rotation(permit['quaternion']).T) - 1) / 2, -1, 1)))
            residual = float(np.max(np.linalg.norm(np.asarray(path)[1:] - prior[1:], axis=1)))
            on_first = np.linalg.norm(pad[:2] - prior[0, :2]) <= allowance and prior[0, 2] - allowance <= pad[2] <= prior[1, 2] + allowance
            save({'conditional_transfer_revalidation': {'remaining_waypoint_error_m': residual, 'allowance_m': allowance, 'on_first_vertical_segment': bool(on_first), 'orientation_error_rad': angle, 'retention_frame': M['last_retention']['observation']['frame_id']}})
            if permit['next'] != 0 or not on_first or residual > allowance or angle > 0.04: raise ValueError('Measured retained pose no longer fits the conditionally reviewed transfer')
            permit['waypoints'][0] = pad.tolist(); M['transfer_review_reusable'] = False; save(); return finger_z
        contact_fields = {}; contact_question = ''
        if M['phase'] == 'possible_holding':
            contact_fields = {'contact': ['opposing_contacts', 'occluded_plausible', 'not_enclosed', 'unknown'], 'probe': ['advance', 'stop']}
            contact_question = 'First inspect the ACTUAL closure effect. contact=opposing_contacts means visible opposing pad/item contacts; occluded_plausible means the item remains enclosed and only the hand hides contacts; not_enclosed means failed enclosure; unknown means unresolved. probe=advance requires plausible/visible contacts and positive local overhead evidence for at most 40mm vertical testing with closed jaws. Otherwise stop. Also assess the supplied transfer CONDITIONALLY: it will execute only after independently observed object motion agrees with actual hand motion during that test. The probe is part of the first vertical segment, not proof of retention. Do not require retention to approve this conditional plan. '
        r = review(contact_question + 'Validate the same stationary destination, not a new hidden reconstruction. same_target=yes identifies the requested bowl; reference_state=consistent requires no visible displacement relative to saved geometry and surroundings, changed means displacement, unknown means unresolved. Request r0 through r5 only where clean samples of the INNER UPPER lip are visible, distributed across the visible arc; omit hidden points and do not sample interior floor or outer wall as lip. Assess the supplied three finite elevated transfer segments with the supplied uncertainty allowance. obstruction=observed means external interference; none_observed is not certified clearance; undetermined means unresolved. visibility distinguishes adequate local evidence, hand/item self_occlusion, and unobserved_other. action=advance requires positive local support for these short segments from visible surfaces and the measured hand/item envelope. Complete visibility of a later corridor is NOT required, but wholly unknown external space is not clearance. The final segment ends ABOVE the rim; it does not insert fingers into hidden space. Otherwise stop. This authorization says nothing about retention or the later released outcome. Also return release: bounded_drop permits ONE short vertical placement trial after fresh measurements put the complete nominal object footprint inside the identified opening and the object bottom within 20mm above its rim, with fingers and object above the rim. Require visible evidence of an open receiving cavity and no interfering item. This is not certified containment: a positive nominal fit can justify a measured trial even when the uncertainty allowance exceeds its small edge margin. Actual containment and stability must be observed after opening. release=obstructed means contrary receiving-cavity evidence; unknown means no justified release trial.', dict({'release': ['bounded_drop', 'obstructed', 'unknown'], 'same_target': ['yes', 'no', 'unknown'], 'reference_state': ['consistent', 'changed', 'unknown'], 'obstruction': ['observed', 'none_observed', 'undetermined'], 'visibility': ['adequate', 'self_occlusion', 'unobserved_other'], 'action': ['advance', 'stop']}, **contact_fields), {'goal': G['goal'], 'historical_destination': D, 'current_object': o, 'pad_waypoints': path, 'quaternion': q, 'allowance_m': tube, 'finger_low_relative_pad_m': finger_z, 'object_low_relative_pad_m': bottom, 'actual_open_enclosure': M.get('enclosure_measurement'), 'joint_contraction_m': M.get('closure_contraction_m')})
        p = r['parameters']; good = []; residuals = []
        if contact_fields:
            M['contact_observation'] = {'contact': p['contact'], 'probe': p['probe'], 'frame_id': r['frame_id']}; save()
            if p['contact'] not in ['opposing_contacts', 'occluded_plausible'] or p['probe'] != 'advance': raise ValueError('Actual closure does not justify the retention probe: ' + r['explanation'])
        for i in range(6):
            name = 'r' + str(i)
            if name in r['points']:
                v = np.asarray(r['points'][name]['world_m']); radial = abs(float(np.linalg.norm(v[:2] - np.asarray(D['xy']))) - D['radius']); vertical = abs(float(v[2]) - D['z']); residuals.append([name, radial, vertical])
                if max(radial, vertical) <= max(0.006, 3 * D['u']): good.append(v[:2])
        span = 0.0; minor = 0.0
        if len(good) >= 3:
            a = np.asarray(good); span = float(np.max(np.linalg.norm(a[:, None, :] - a[None, :, :], axis=2))); minor = float(np.linalg.svd(a - np.mean(a, axis=0), compute_uv=False)[1] / math.sqrt(len(a)))
        save({'transfer_review': p, 'rim_residuals_m': residuals, 'span_m': span, 'minor_spread_m': minor, 'required_span_m': max(D['radius'], 6 * D['u']), 'required_minor_m': 2 * D['u'], 'frame_id': r['frame_id']})
        if p['same_target'] != 'yes' or p['reference_state'] != 'consistent' or len(good) < 3 or span < max(D['radius'], 6 * D['u']) or minor < 2 * D['u']: raise ValueError('Stationary bowl reference not supported by current measurements')
        if p['action'] != 'advance' or p['obstruction'] != 'none_observed' or p['visibility'] == 'unobserved_other': raise ValueError('Elevated local transfer lacks positive evidence: ' + r['explanation'])
        if p['release'] != 'bounded_drop': raise ValueError('No justified receiving-cavity placement trial: ' + r['explanation'])
        M['release_permission'] = {'frame_id': r['frame_id'], 'destination_reference_frame': D['frame_id'], 'maximum_bottom_height_above_rim_m': 0.020, 'meaning': 'Bounded placement trial only; actual supported containment and settling remain unmeasured.'}
        M['destination_validation_frame'] = r['frame_id']; M['route_permission'] = {'waypoints': path, 'next': 0, 'tube': tube, 'quaternion': q, 'frame_id': r['frame_id']}; save(); return finger_z
    def travel(target, quaternion, gripper='keep', final=False):
        target = np.asarray(target); views = 0
        carrying = M['phase'] in ['held', 'over_goal']; permit = M.get('route_permission') if carrying else M.get('approach_permission') if M['phase'] == 'approach' else None
        if permit is not None and permit['next'] + 1 < len(permit['waypoints']):
            i = permit['next']; s0 = api.state(); here = np.asarray(geo.pad_position(s0)); qerror = math.acos(float(np.clip((np.trace(geo.rotation(quaternion) @ geo.rotation(permit['quaternion']).T) - 1) / 2, -1, 1)))
            fits = np.linalg.norm(target - np.asarray(permit['waypoints'][i + 1])) <= permit['tube'] and np.linalg.norm(here - np.asarray(permit['waypoints'][i])) <= permit['tube'] and qerror <= 0.04
            if fits:
                if np.linalg.norm(target - here) > 0.0025:
                    old = observe() if carrying else None; s0 = api.state()
                    if np.linalg.norm(np.asarray(geo.pad_position(s0)) - here) > 0.002: raise ValueError('Observation move changed the permitted segment start; a new local plan is needed')
                    if carrying:
                        last = M['last_retention']; attached(last['observation'], old, last['state'], s0)
                    b = s0['budgets']; calls = min(30, b['jev_remaining'] - 8, b['native_steps_remaining'] // 3 - 8)
                    if calls < 1: raise ValueError('Physical verification reserve reached')
                    receipt = run(target, quaternion, gripper, calls)
                    if carrying:
                        new = observe(); s1 = api.state(); attached(old, new, s0, s1); M['last_retention'] = {'observation': new, 'state': s1}; save()
                    if np.linalg.norm(target - np.asarray(geo.pad_position(api.state()))) > 0.003: raise ValueError('Bounded approved segment exhausted before convergence')
                permit['next'] = i + 1; save({'approved_segment_completed': i, 'permission_frame': permit['frame_id']}); return
            if carrying: raise ValueError('Measured transfer changed beyond its reviewed allowance; no stale route permission used')
        if np.linalg.norm(target - np.asarray(geo.pad_position(api.state()))) > 0.6: raise ValueError('Requested route exceeds bounded local workspace')
        for leg in range(34):
            carrying = M['phase'] in ['held', 'over_goal']; old = observe() if carrying else None; s0 = api.state(); here = np.asarray(geo.pad_position(s0)); delta = target - here; distance = float(np.linalg.norm(delta))
            angle = math.acos(float(np.clip((np.trace(geo.rotation(quaternion) @ geo.rotation(s0['tcp_quaternion_xyzw']).T) - 1) / 2, -1, 1)))
            if distance <= 0.0025 and angle <= 0.04: return
            b = s0['budgets']
            if b['gpt_remaining'] <= (3 if final else 4) or b['jev_remaining'] < (8 if final else 22): raise ValueError('Reserved verification/recovery budget reached')
            end = here + delta * min(1, (0.075 if final else 0.06) / max(distance, 0.000001))
            r = review('Assess only this proposed bounded local segment and orientation change, not an entire future corridor. obstruction=observed means an external obstacle intersects the proposed local sweep; none_observed means none is seen, NOT certified clearance; undetermined means that question cannot be resolved. visibility distinguishes adequate local evidence, self_occlusion by hand/item, and unobserved_other. action=advance requires a justified bounded local action from current visible geometry, own envelope and historical stationary surfaces; self-occlusion alone is not an external obstacle. With unobserved_other, advance authorizes only the first 20mm with positive local evidence, not entry into wholly unknown space. action=raise_view authorizes only 15mm upward when overhead local evidence supports it. Otherwise stop. During approach the open fingers must pass outside the source, not through its top. Never approve motion through an observed obstacle.', {'obstruction': ['observed', 'none_observed', 'undetermined'], 'visibility': ['adequate', 'self_occlusion', 'unobserved_other'], 'action': ['advance', 'raise_view', 'stop']}, {'start_pad': here.tolist(), 'end_pad': end.tolist(), 'quaternion': np.asarray(quaternion).tolist(), 'source': G['source'], 'destination': G['goal'], 'object_observation': old, 'geometry': M.get('grasp_geometry'), 'destination_reference': G['destination'], 'approach_plan': M.get('approach_plan'), 'view_moves_used': views})
            p = r['parameters']; save({'local_observation': p, 'explanation': r['explanation'], 'frame_id': r['frame_id']})
            if p['obstruction'] == 'observed' or p['action'] == 'stop': raise ValueError('Local motion not justified: ' + str(p))
            if p['action'] == 'raise_view':
                if views >= 2: raise ValueError('View-change allowance exhausted')
                views += 1; end = here + [0, 0, 0.015]; q = s0['tcp_quaternion_xyzw']
            else:
                if p['visibility'] == 'unobserved_other': end = here + delta * min(1, 0.02 / max(distance, 0.000001))
                q = quaternion
            receipt = run(end, q, gripper)
            if carrying:
                new = observe(); s1 = api.state(); attached(old, new, s0, s1); M['last_retention'] = {'observation': new, 'state': s1}; save()
            if receipt['status'] == 'lease_exhausted':
                s1 = api.state(); shift = np.linalg.norm(np.asarray(s1['tcp_position_world_m']) - np.asarray(s0['tcp_position_world_m'])); rotation = np.linalg.norm(geo.rotation(s1['tcp_quaternion_xyzw']) - geo.rotation(s0['tcp_quaternion_xyzw']))
                if max(float(shift), float(rotation)) < 0.0005: raise ValueError('Feedback lease exhausted without observable progress')
        raise ValueError('Finite local-route bound exhausted')
    def pulse(command, repeats):
        for j in range(repeats):
            s = api.state(); M['jaw_intent'] = {'command': command, 'frame_id': s['frame_id']}; save()
            r = api.control(target=np.asarray(geo.pad_position(s)).tolist(), quaternion=s['tcp_quaternion_xyzw'], gripper=command, questions=Q, features={'phase': M['phase'], 'purpose': 'jaw transition or settling observation interval'}, tool_point='pad_center', translation_limit=0.006, rotation_limit=0.04, steps=3, position_tolerance=0.003, rotation_tolerance=0.04)
            if r['choices']['gripper'] == 'open': M['phase'] = 'released'; M['opened_ack'] = True
            if r['choices']['gripper'] == 'close': M['closed_ack'] = True
            save({'jaw_receipt': {'requested': command, 'choices': r['choices'], 'status': r['status'], 'acknowledged_steps': r['acknowledged_steps'], 'frame_id': r['frame_id']}})
            if r['status'] not in ['reached', 'moved'] or r['choices']['gripper'] != command: raise ValueError('Unexpected transition result; physical effects have not been undone')
    rim_question = 'Identify the requested destination. Request measured points r0 through r5 distributed on the visible INNER upper lip of the bowl opening, avoiding depth-mixed silhouettes and any held item; use small clean depth neighborhoods. Request floor on a separately visible interior bottom surface. Missing/occluded samples may be omitted, never invented. same_target=yes only for the requested receptacle and this inner opening, otherwise no or unknown.'
    try:
        save()
        if G is None:
            fields = {'source': 'string', 'goal': 'string', 'compatible': ['yes', 'no', 'unknown'], 'camera': cameras, 'corners': {'type': 'array', 'items': pixel, 'minItems': 4, 'maxItems': 4}, 'landmark_labels': labels3, 'landmarks': uv3, 'support_contact': ['observed', 'unknown']}
            r = review('Interpret the user request. compatible=yes only for a rigid rectangular planar-top item to be put inside an open approximately horizontal round bowl, with visible side/support evidence. Return source and goal identities. Return camera and corners: four currently visible top-face vertices in cyclic order, as pixels, not guessed hidden geometry. Request named region top strictly inside that face in that camera, and region table on its adjacent support, each with explicit camera, box and stride 4. Return three well-separated interior print landmark pixels and persistent physical landmark_labels tied to artwork, not camera-relative corners. support_contact=observed requires visible lower-side/table junction evidence. Request s0 and s1 on visible source side surfaces near the bottom junction. Also request r0 through r5 on the destination INNER upper rim and floor on a separately visible interior bottom surface. These are current measured surfaces; do not substitute centers or hidden undersides.', fields)
            p = r['parameters']
            if p['compatible'] != 'yes' or p['support_contact'] != 'observed' or any(v is None for v in p['landmarks']): raise ValueError('Task/shape/support identity is not sufficiently observed')
            top = fitted(r, 'top'); table = fitted(r, 'table')
            if top['coefficients'][2] < 0.97 or table['coefficients'][2] < 0.97 or r['regions']['top']['camera'] != p['camera']: raise ValueError('Need a currently observed near-horizontal top and support')
            C = np.asarray([api.plane_point(p['camera'], v, top['coefficients'])['world_m'] for v in p['corners']]); F = np.asarray([api.plane_point(p['camera'], v, top['coefficients'])['world_m'] for v in p['landmarks']]); B = C.copy(); plane = np.asarray(table['coefficients']); B[:, 2] = -(B[:, :2] @ plane[:2] + plane[3]) / plane[2]
            a = C[1] - C[0]; b = C[3] - C[0]; u = max(0.001, 2 * top['rms_m'], 2 * table['rms_m']); width = min(np.linalg.norm(a), np.linalg.norm(b)); height = float(np.min(C[:, 2] - B[:, 2]))
            shape_error = float(np.linalg.norm(C[0] + C[2] - C[1] - C[3]))
            if shape_error > 4 * u or abs(np.dot(a, b)) > 0.18 * np.linalg.norm(a) * np.linalg.norm(b) or height <= 2 * u: raise ValueError('Measured box geometry inconsistent: ' + str({'rectangle_error': shape_error, 'height': height, 'u': u}))
            sides = [np.asarray(r['points'][name]['world_m']) for name in ['s0', 's1'] if name in r['points']]
            if not any(abs(float(np.dot(plane[:3], v) + plane[3])) <= height + 3 * u for v in sides): raise ValueError('Missing consistent visible source side/support measurement')
            for f in F:
                if any(abs(float(np.dot(f - np.mean(C, axis=0), e / np.linalg.norm(e)))) > np.linalg.norm(e) / 2 + u for e in [a, b]): raise ValueError('Print landmark lies outside measured top face')
            D = destination(r)
            if float(np.max(np.linalg.norm(C[:, :2] - np.mean(C[:, :2], axis=0), axis=1))) + 3 * u + D['u'] >= D['radius']: raise ValueError('Measured source footprint does not fit the observed opening with uncertainty margin')
            G = {'source': p['source'], 'goal': p['goal'], 'corners': C.tolist(), 'vertices': np.vstack([C, B]).tolist(), 'fiducials': F.tolist(), 'labels': p['landmark_labels'], 'landmark_pixels': p['landmarks'], 'reference_camera': api.camera(p['camera']), 'normal': top['coefficients'][:3], 'support_plane': table['coefficients'], 'u': float(u), 'destination': D, 'frame_id': r['frame_id']}; M['geometry'] = G; M['phase'] = 'approach'; save({'initial_geometry': {'height_m': height, 'width_m': float(width), 'u_m': float(u), 'destination': D}})
            polygon = np.asarray(p['corners']); polygon = np.rint(np.mean(polygon, axis=0) + 0.78 * (polygon - np.mean(polygon, axis=0))).astype(int).tolist(); bind_patch(p['camera'], polygon, np.eye(4))
        if M['phase'] == 'releasing':
            M['phase'] = 'released' if api.state()['last_gripper_command'] == 'open' or M.get('opened_ack', False) else 'over_goal'; save()
        if M['phase'] == 'approach':
            o = observe(); C = np.asarray(o['c']); s = api.state(); own = s['own_geometry']; center = np.mean(C, axis=0)
            save({'approach_reference_change_m': float(np.max(np.linalg.norm(C - np.asarray(G['corners']), axis=1))), 'reference_policy': 'Rigid dimensions remain historical measured invariants. Current registration is independent; support will be revalidated before motion, not rejected solely for lateral displacement.', 'observation': o['quality']})
            a = C[1] - C[0]; b = C[3] - C[0]; short = a if np.linalg.norm(a) < np.linalg.norm(b) else b; y = geo.rotation(s['tcp_quaternion_xyzw'])[:, 1]; angle = math.atan2(y[0] * short[1] - y[1] * short[0], float(np.dot(y[:2], short[:2])))
            if angle > math.pi / 2: angle -= math.pi
            if angle < -math.pi / 2: angle += math.pi
            q = api.compose(s['tcp_quaternion_xyzw'], [0, 0, angle]); R = geo.rotation(q); offset = np.asarray(own['pad_center_in_tool_m']); lo = np.asarray(own['finger_low_offset_tool_m']) - offset; hi = np.asarray(own['finger_high_offset_tool_m']) - offset; extent = np.asarray(own['pad_extent_in_tool_m']) / 2
            fingers = np.asarray([[x, y0, z] for x in [lo[0], hi[0]] for y0 in [lo[1], hi[1]] for z in [lo[2], hi[2]]]) @ R.T; pads = np.asarray([[x, y0, z] for x in [-extent[0], extent[0]] for y0 in [-extent[1], extent[1]] for z in [-extent[2], extent[2]]]) @ R.T
            plane = np.asarray(G['support_plane']); support = float(-(np.dot(plane[:2], center[:2]) + plane[3]) / plane[2]); side_low = support + o['u']; side_high = float(np.min(C[:, 2])) - o['u']; band_low = float(np.min(pads[:, 2])); band_high = float(np.max(pads[:, 2])); overlap = 0.35 * min(side_high - side_low, band_high - band_low); clearance = o['u'] + 0.002
            lower = max(support + clearance - float(np.min(fingers[:, 2])), side_low + overlap - band_high); upper = side_high - overlap - band_low; gap = abs(float(s['gripper_qpos_m'][0] - s['gripper_qpos_m'][1])); source_width = float(np.ptp(C @ R[:, 1]))
            M['grasp_geometry'] = {'pad_height_interval': [float(lower), float(upper)], 'required_overlap_m': float(overlap), 'source_width_m': source_width, 'joint_opening_span_m': gap, 'support_z': support, 'finger_min_relative_pad_z': float(np.min(fingers[:, 2])), 'uncertainty_m': o['u']}; save({'grasp_geometry': M['grasp_geometry']})
            if lower > upper or overlap <= 0 or source_width + 2 * o['u'] >= gap: raise ValueError('Measured grasp interval/aperture infeasible: ' + str(M['grasp_geometry']))
            zg = float((lower + upper) / 2); D = G['destination']
            longitudinal = R[:, 0].copy(); longitudinal[2] = 0; longitudinal /= np.linalg.norm(longitudinal)
            side_interval = (C - center) @ longitudinal; pad_interval = pads @ longitudinal
            side_a, side_b = float(np.min(side_interval)), float(np.max(side_interval)); pad_a, pad_b = float(np.min(pad_interval)), float(np.max(pad_interval))
            contact_length = 0.60 * min(side_b - side_a, pad_b - pad_a); allowance = o['u'] + 0.002
            shift_low = side_a + contact_length - pad_b + allowance; shift_high = side_b - contact_length - pad_a - allowance
            if contact_length <= 0 or shift_low > shift_high: raise ValueError('No longitudinal pad overlap interval: ' + str({'side': [side_a, side_b], 'pad': [pad_a, pad_b], 'required_overlap': contact_length, 'shift_interval': [shift_low, shift_high]}))
            candidates = []
            for shift in [float(np.clip(0, shift_low, shift_high)), shift_low, shift_high]:
                xy = center[:2] + shift * longitudinal[:2]; xy_low = xy + np.min(fingers[:, :2], axis=0); xy_high = xy + np.max(fingers[:, :2], axis=0)
                separation = np.maximum(np.maximum(xy_low - np.asarray(D['xy']), np.asarray(D['xy']) - xy_high), 0)
                candidates.append({'shift_m': float(shift), 'target_pad_xy': xy.tolist(), 'finger_xy_low': xy_low.tolist(), 'finger_xy_high': xy_high.tolist(), 'inner_rim_screen_gap_m': float(np.linalg.norm(separation)) - D['radius']})
            selected = candidates[0]
            if selected['inner_rim_screen_gap_m'] < 2 * (o['u'] + D['u']) + 0.003:
                for candidate in candidates[1:]:
                    if candidate['inner_rim_screen_gap_m'] > selected['inner_rim_screen_gap_m']: selected = candidate
            M['grasp_geometry'].update({'longitudinal_side_interval_m': [side_a, side_b], 'longitudinal_pad_interval_m': [pad_a, pad_b], 'required_longitudinal_overlap_m': contact_length, 'allowed_shift_interval_m': [shift_low, shift_high], 'candidates': candidates, 'selected': selected, 'screen_limitation': 'Inner opening is not the external bowl boundary. This selects a candidate only; image review must assess the actual external obstacle and local sweep.', 'source_observation_frame': o['frame_id'], 'destination_reference_frame': D['frame_id']}); save({'approach_replan': selected})
            if selected['inner_rim_screen_gap_m'] <= 2 * (o['u'] + D['u']): raise ValueError('No adequately separated end-grasp candidate: ' + str(M['grasp_geometry']))
            gx, gy = selected['target_pad_xy']; here = np.asarray(geo.pad_position(s)); finger_low = float(np.min(fingers[:, 2]))
            lateral_error = float(np.linalg.norm(here[:2] - np.asarray([gx, gy]))); aligned = lateral_error <= 0.0025 and abs(angle) <= 0.035
            near = lateral_error <= 0.012 and abs(angle) <= 0.035
            safe_z = max(float(here[2]), float(np.max(C[:, 2])) + 2 * o['u'] + 0.004 - finger_low) if near else max(float(here[2]), zg + 0.04, side_high + 0.025 - finger_low, D['z'] + 0.020 - finger_low)
            withdraw = [float(here[0]), float(here[1]), safe_z]; lateral = [gx, gy, safe_z]; grasp = [gx, gy, zg]
            path = [here.tolist(), grasp] if aligned else [here.tolist(), withdraw, lateral, grasp]
            M['approach_plan'] = {'withdraw_pad': withdraw, 'lateral_pad': lateral, 'grasp_pad': grasp, 'waypoints': path, 'quaternion': q, 'reason': 'A short local correction may use a source-top-clearing lift; the current image review must assess the actual external bowl and finger sweep. Larger corrections retain the elevated withdrawal.', 'lateral_error_m': lateral_error, 'frame_id': s['frame_id']}; save()
            fresh = observe('approach'); drift = float(np.max(np.linalg.norm(np.asarray(fresh['c']) - C, axis=1)))
            plane = np.asarray(G['support_plane']); base = np.asarray(fresh['v'])[4:]; residuals = base @ plane[:3] + plane[3]; allowance = 3 * (fresh['u'] + G['support_validation']['u'])
            current_support = float(-(np.dot(plane[:2], center[:2]) + plane[3]) / plane[2]); clearance_now = zg + finger_low - current_support
            support_check = {'registered_base_plane_residuals_m': residuals.tolist(), 'allowance_m': allowance, 'planned_finger_support_separation_m': clearance_now, 'same_frame_registration_change_m': drift, 'frame_id': fresh['frame_id'], 'limitation': 'Base inferred from preserved rigid dimensions under independently observed registration; not a current hidden-underside measurement or calibrated confidence bound.'}
            save({'support_revalidation': support_check})
            if drift > max(4 * G['u'], 2 * (o['u'] + fresh['u'])) or float(np.max(np.abs(residuals))) > allowance or clearance_now < fresh['u'] + 0.001: raise ValueError('Current support/approach model inconsistent: ' + str(support_check))
            M['grasp_geometry']['support_z'] = current_support; M['grasp_geometry']['support_validation_frame'] = fresh['frame_id']; save()
            if api.state()['budgets']['gpt_remaining'] < 3: raise ValueError('Need three remaining reviews: actual closure plus conditional transfer, then two released-outcome observations; no contact started')
            if not aligned:
                travel(withdraw, s['tcp_quaternion_xyzw'], 'open')
                travel(lateral, q, 'open')
            travel(grasp, q, 'open')
            ready = observe(); actual = api.state(); own = actual['own_geometry']; Rn = geo.rotation(actual['tcp_quaternion_xyzw']); pad = np.asarray(geo.pad_position(actual)); local = (np.asarray(ready['v']) - pad) @ Rn; half = np.asarray(own['pad_extent_in_tool_m']) / 2
            gap = abs(float(actual['gripper_qpos_m'][0] - actual['gripper_qpos_m'][1])); side_slack = min(gap / 2 - float(np.max(local[:, 1])), float(np.min(local[:, 1])) + gap / 2)
            overlap_x = min(float(np.max(local[:, 0])), half[0]) - max(float(np.min(local[:, 0])), -half[0]); overlap_z = min(float(np.max(local[:, 2])), half[2]) - max(float(np.min(local[:, 2])), -half[2])
            offset = np.asarray(own['pad_center_in_tool_m']); lo = np.asarray(own['finger_low_offset_tool_m']) - offset; hi = np.asarray(own['finger_high_offset_tool_m']) - offset
            actual_fingers = np.asarray([[x, y, z0] for x in [lo[0], hi[0]] for y in [lo[1], hi[1]] for z0 in [lo[2], hi[2]]]) @ Rn.T + pad; plane = np.asarray(G['support_plane']); separation = float(np.min(actual_fingers @ plane[:3] + plane[3]))
            M['enclosure_measurement'] = {'side_clearance_m': float(side_slack), 'longitudinal_overlap_m': float(overlap_x), 'height_overlap_m': float(overlap_z), 'finger_support_separation_m': separation, 'opening_span_m': gap, 'u_m': ready['u'], 'required_longitudinal_overlap_m': contact_length, 'required_height_overlap_m': float(overlap), 'frame_id': actual['frame_id'], 'basis': 'Fresh independent object registration and actual pad/finger pose, not commanded target or proof of contact.'}; save({'actual_enclosure': M['enclosure_measurement']})
            if side_slack <= ready['u'] + 0.001 or overlap_x < contact_length or overlap_z < overlap or separation <= ready['u'] + 0.001: raise ValueError('Actual pad enclosure/support geometry does not justify closure: ' + str(M['enclosure_measurement']))
            if actual['budgets']['gpt_remaining'] < 3: raise ValueError('Registration recovery used the required closure/final-observation reserve; no contact started')
            M['preclosure'] = {'observation': ready, 'state': actual}; M['open_gap'] = gap; M['phase'] = 'possible_holding'; save()
        if M['phase'] == 'possible_holding':
            if not M.get('closed_ack', False): pulse('close', 3)
            before = observe(); s0 = api.state(); contraction = M['open_gap'] - abs(float(s0['gripper_qpos_m'][0] - s0['gripper_qpos_m'][1])); M['closure_contraction_m'] = contraction; save({'joint_contraction_m': contraction, 'closure_frame': s0['frame_id']})
            if s0['budgets']['gpt_remaining'] < 3: raise ValueError('Need actual closure/conditional-transfer review and two released-outcome observations; keep jaws unchanged')
            approve_transfer(before, s0); contact = M['contact_observation']['contact']; save({'closure_contact': contact, 'joint_contraction_m': contraction})
            if contraction < 0.001 and contact != 'opposing_contacts': raise ValueError('Closure did not justify a retention test')
            M['retention_test'] = {'observation': before, 'state': s0}; save()
            lift = 0.028 + 2 * before['u']
            if lift > 0.04: raise ValueError('Retention uncertainty exceeds the reviewed probe allowance')
            target = np.asarray(geo.pad_position(s0)) + [0, 0, lift]; run(target, s0['tcp_quaternion_xyzw'], 'keep', 12); after = observe(); s1 = api.state(); attached(before, after, s0, s1, True)
            if np.min(np.asarray(after['v'])[:, 2]) <= M['grasp_geometry']['support_z'] + 2 * after['u']: raise ValueError('Observed item has not cleared its original support')
            M['phase'] = 'held'; M['last_retention'] = {'observation': after, 'state': s1}; M['transfer_review_reusable'] = True; save({'retention_measured': True, 'conditional_transfer_requires_route_revalidation': True})
        if M['phase'] in ['held', 'over_goal']:
            o = observe(); s = api.state(); last = M['last_retention']; attached(last['observation'], o, last['state'], s)
            finger_z = approve_transfer(o, s); D = G['destination']; q = s['tcp_quaternion_xyzw']
            pad = np.asarray(geo.pad_position(s)); bottom = float(np.min(np.asarray(o['v'])[:, 2]) - pad[2]); safe_z = max(float(pad[2]), D['z'] + 0.03 - min(finger_z, bottom)); travel([pad[0], pad[1], safe_z], q)
            o = observe(); pad = np.asarray(geo.pad_position(api.state())); center = np.mean(np.asarray(o['c']), axis=0); xy = np.asarray(D['xy']) - (center - pad)[:2]; travel([xy[0], xy[1], safe_z], q)
            o = observe(); pad = np.asarray(geo.pad_position(api.state())); center = np.mean(np.asarray(o['c']), axis=0); xy = np.asarray(D['xy']) - (center - pad)[:2]; bottom = float(np.min(np.asarray(o['v'])[:, 2]) - pad[2]); margin = max(0.006, 2 * (o['u'] + D['u']) + 0.002); z = D['z'] + margin - min(finger_z, bottom); travel([xy[0], xy[1], z], q)
            o = observe(); pad = np.asarray(geo.pad_position(api.state())); radial = float(np.max(np.linalg.norm(np.asarray(o['v'])[:, :2] - np.asarray(D['xy']), axis=1))); low_object = float(np.min(np.asarray(o['v'])[:, 2])); save({'release_geometry': {'radial_extent_m': radial, 'opening_radius_m': D['radius'], 'object_low_z': low_object, 'finger_low_z': float(pad[2] + finger_z), 'rim_z': D['z'], 'object_uncertainty_m': o['u'], 'rim_uncertainty_m': D['u']}})
            fit_margin = D['radius'] - radial; fit_allowance = 2 * o['u'] + D['u']; permission = M.get('release_permission')
            fit = {'nominal_radial_margin_m': fit_margin, 'heuristic_uncertainty_allowance_m': fit_allowance, 'bottom_height_above_rim_m': low_object - D['z'], 'fit_certified': False, 'uncertainty_resolved_by': 'Bounded release followed by actual relation and settling observations, not a pose-success inference.'}; save({'placement_trial_geometry': fit})
            permitted = permission is not None and permission['destination_reference_frame'] == D['frame_id'] and low_object - D['z'] <= permission['maximum_bottom_height_above_rim_m']
            if fit_margin <= 0 or min(low_object, pad[2] + finger_z) < D['z'] + 0.002 or not permitted: raise ValueError('No justified bounded release relation: ' + str(fit))
            M['phase'] = 'over_goal'; save(); M['phase'] = 'releasing'; save(); pulse('open', 3)
        if M['phase'] in ['released', 'done']:
            if not M.get('retreated', False):
                s = api.state(); save({'release_withdrawal': 'Bounded upward separation at unchanged XY and orientation along the prior approach axis; an observation-producing move, not evidence that the item was released successfully.'})
                retreat = run(np.asarray(geo.pad_position(s)) + [0, 0, 0.07], s['tcp_quaternion_xyzw'], 'keep', 18)
                if retreat['position_error_m'] > 0.003: raise ValueError('Post-release view withdrawal did not converge; do not disturb the object')
                M['retreated'] = True; save()
            previous = None
            for trial in range(3):
                if trial: pulse('keep', 2)
                r = review('Assess the actual final relation after release, not the intended pose. relation=inside_supported means the identified item is within and supported by the bowl interior, not held or balanced on its rim; rim, outside, and unknown have their literal meanings. separated=yes requires visible hand/item separation. Request named points s0,s1,s2 on separated visible physical marks on the item, avoiding depth boundaries. First choose persistent physical definitions in labels; subsequently use exactly the previous definitions and current detections, never historical projections. identity=unambiguous only when those correspondences are identifiable. These samples will be compared across actual settling steps.', {'relation': ['inside_supported', 'rim', 'outside', 'unknown'], 'separated': ['yes', 'no', 'unknown'], 'labels': labels3, 'identity': ['unambiguous', 'unknown']}, {'source': G['source'], 'goal': G['goal'], 'previous_observation': previous})
                now = {'parameters': r['parameters'], 'points': {name: r['points'][name] for name in ['s0', 's1', 's2'] if name in r['points']}, 'frame_id': r['frame_id'], 'native_steps': api.state()['native_steps']}; save({'final_observation': now})
                if previous is not None:
                    names = [name for name in now['points'] if name in previous['points']]; displacement = max([float(np.linalg.norm(np.asarray(now['points'][name]['world_m']) - np.asarray(previous['points'][name]['world_m']))) for name in names] + [0.0]); stable = len(names) >= 2 and displacement <= 0.0035 and now['native_steps'] - previous['native_steps'] >= 6
                    identity = now['parameters']['identity'] == 'unambiguous' and previous['parameters']['identity'] == 'unambiguous' and now['parameters']['labels'] == previous['parameters']['labels']; save({'settling_displacement_m': displacement, 'common_landmarks': names, 'stable_observed': stable, 'identity_consistent': identity})
                    if stable and identity and now['parameters']['relation'] == 'inside_supported' and now['parameters']['separated'] == 'yes':
                        M['phase'] = 'done'; save({'completion_proposal': True, 'limitation': 'Visual relation and short settling interval, not certified long-term stability or native success'}); return {'completion_proposed': True, 'evidence': M['evidence']}
                previous = now
            raise ValueError('Release occurred, but final containment/separation/stability is unresolved; no blind regrasp')
        raise ValueError('Unsupported persisted phase: ' + M['phase'])
    except Exception as e:
        failure = {'stopped_in_phase': M['phase'], 'gap': str(e), 'physical_state_preserved': True}
        try:
            save(failure)
        except Exception as checkpoint_error:
            M['evidence'] = M.get('evidence', [])[-4:] + [failure, {'checkpoint_gap': str(checkpoint_error)[:600]}]
        return {'completion_proposed': False, 'evidence': M['evidence']}

"""Visible geometry, own-pad fit and Jev-owned recovery graph.
No hidden object poses, contact IDs, reward or task predicates enter decisions.
"""
import hashlib
import json
import os
import time
import cv2
import numpy as np
from scipy.spatial.transform import Rotation
from run_position_pilot import Jev, dump, append, serial, direction_metrics
from libero_generic_vision import GenericVision
from libero_robot_geometry import gripper_geometry, envelope
from libero_goal_rack_geometry import fit_visible_rack

PHASES = ['select', 'approach', 'align', 'descend', 'grasp', 'test_lift', 'lift', 'carry', 'lower', 'release', 'retreat']
NATIVE_BUDGET = 580  # Env horizon is 600; initial gripper opening uses 10 ticks.


def fit_candidates(src, own, position, quaternion, level, points, cfg, failed_candidates):
    extent = src['high']-src['low']
    # Horizontal observed bounding range, no hidden object shape/PCA metadata.
    major = np.array([1.,0.,0.]) if extent[0] >= extent[1] else np.array([0.,1.,0.])
    minor = np.array([-major[1],major[0],0.])
    R = np.column_stack([major, -minor, [0.,0.,-1.]])
    current = Rotation.from_quat(quaternion).as_matrix()
    alternate = R @ Rotation.from_euler('z',np.pi).as_matrix()
    if np.linalg.norm(Rotation.from_matrix(alternate@current.T).as_rotvec()) < np.linalg.norm(Rotation.from_matrix(R@current.T).as_rotvec()):
        R = alternate
    angle = cfg['contact_angle_deg']*np.pi/180
    near = 1 if position[:2]@major[:2] > src['center'][:2]@major[:2] else -1
    R = Rotation.from_rotvec(minor*angle*near).as_matrix() @ R
    ee = envelope(own, R)
    c = []
    for i, extra in enumerate([0., .003, -.003]):
        overlap = cfg['pad_overlap_mm']/1000+extra
        if cfg['grasp_algorithm'] == 'legacy_clearance':
            z = src['high'][2]+.023
        else:
            z = src['high'][2]-overlap-ee['pad_low_offset'][2]
            z = max(z, level-ee['finger_low_z_offset']+cfg['table_margin_mm']/1000)
        tall_slender = extent[2] > .09 and max(extent[:2]) < .07
        if tall_slender and cfg['grasp_algorithm'] == 'pad_fit':
            # A top-edge fit pinches a bottle cap; use visible mid-body height.
            mid = src['low'][2]+.55*extent[2]-ee['pad_center_offset'][2]
            z = max(mid, level-ee['finger_low_z_offset']+cfg['table_margin_mm']/1000)
        target = np.r_[src['center'][:2]-ee['pad_center_offset'][:2], z]
        target[:2] += major[:2] * ([0.,-.012,.012][i])
        pad_low, pad_high = z+ee['pad_low_offset'][2],z+ee['pad_high_offset'][2]
        width = float(abs(minor[:2])@extent[:2])
        c.append(dict(id=f'candidate_{i}', target=target, orientation=R, visible_width_mm=width*1000,
                      estimated_pad_overlap_mm=max(0., min(pad_high,src['high'][2])-max(pad_low,src['low'][2]))*1000,
                      estimated_finger_table_clearance_mm=(z+ee['finger_low_z_offset']-level)*1000,
                      pad_z_interval_m=[pad_low,pad_high],support_z_m=level, support_pixels=points,
                      grasp_height_source='visible tall-slender mid-body' if tall_slender else 'visible top pad-overlap',
                      prior_failed=i in failed_candidates, source='Visible RGB-D bounds/support plane + own robot mesh; geometric estimate only'))
    return c


class RecoveryModel(Jev):
    def decide(self, state):
        self.rec.check_budget()
        i = len(self.rec.decisions)
        if i >= self.rec.cfg['max_jev_decisions']:
            raise RuntimeError('Jev decision budget')
        folder = self.rec.folder / f'decision-{i:04d}'
        folder.mkdir()
        questions = {a: dict(type='choice', instructions=f'Read ONLY translation_axes[{a}]. Compare that axis goal coordinate with its current coordinate: larger goal needs positive, smaller goal needs negative. If relation is within_tolerance choose hold. Do not use another axis. In select/grasp/release/recover_open choose hold.', criteria=dict(negative='Decrease coordinate', hold='No displacement', positive='Increase coordinate')) for a in 'xyz'}
        for a in ['rx', 'ry', 'rz']:
            if abs(state['required_rotation_world_rad'][a]) < .03:
                continue
            questions[a] = dict(type='choice', instructions=f'Read required_rotation_world_rad[{a}], TARGET relative to CURRENT. Do not negate. Hold within 0.03 radians.', criteria=dict(negative='Negative world rotation', hold='No rotation', positive='Positive world rotation'))
        questions['gripper'] = dict(type='choice', instructions='Choose the gripper from the CURRENT operation contract and measured aperture. Opening/closure alone does not prove holding. keep preserves your previous motor command. Hold closed during a carrying operation. Open when explicitly releasing or preparing an unheld source.', criteria=dict(open='Command open', close='Command close', keep='Preserve prior motor command'))
        transitions = dict(stop='End incomplete attempt')
        if state['allowed_transitions']['continue_phase']:
            transitions['continue_phase'] = 'Execute and remain'
        if state['allowed_transitions']['advance']:
            transitions['advance'] = 'Enter supplied next operation'
        if state['allowed_transitions']['retry']:
            transitions['retry'] = 'Withdraw and select another visible-geometry candidate'
        if state['allowed_transitions'].get('finish_if_visible'):
            transitions['finish_if_visible'] = 'End because fresh public RGB-D shows the source resting on the requested support'
        questions['transition'] = dict(type='choice', instructions='Decide the operation edge from completion_evidence and allowed_transitions. advance only when the current contract is satisfied. If fresh visible_goal_evidence passed at select and the gripper is open, choose finish_if_visible; this is sensor evidence, not native task success. A pending test is unknown, not failed. At descend, a blocked motion with measured open-pad overlap may allow one bounded closure trial; advance then and let the short lift test decide holding. At lower, a fresh visible held-source/rack contact candidate after arrival or blocked motion may allow release; it is not native task success. On a failed or unavailable lift/contact check, or blocked motion without contact-trial evidence, choose retry if available. Do not keep repeating a blocked command. stop if a failure cannot be recovered. The selected actions execute before the edge.', criteria=transitions)
        if state['operation'] == 'select' and not state['allowed_transitions'].get('finish_if_visible'):
            choices={c['id']: 'Visible-geometry candidate '+c['id'] for c in state['candidates'] if not c['prior_failed']}
            questions['candidate'] = dict(type='choice', instructions='Select one of the available visible-geometry candidates now. Prefer adequate pad overlap and positive table clearance. This selection and your advance choice apply together. The previously displayed candidate is only a default, not a completed selection. These are geometric estimates, not tested success predictions.', criteria=choices)
        payload = dict(model=self.api.cfg['model'], state=state, questions=questions)
        dump(folder/'request.json', payload)
        row = dict(decision_id=f'decision-{i:04d}', stage=state['operation'], observation=state, prompt_version='recovery-'+self.rec.cfg['input_organization'], request_sha256=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest())
        self.rec.decisions.append(row)
        started = time.monotonic()
        try:
            raw = self.api.post('/systemone', payload)
            dump(folder/'response.json', raw)
            answers = raw['answers']
            if set(answers)!=set(questions):raise ValueError('Unexpected or missing Jev question answer')
            for name, q in questions.items():
                a = answers[name]
                p = a['probabilities']
                if a['choice'] not in q['criteria'] or set(p) != set(q['criteria']) or not all(np.isfinite(x) and 0 <= x <= 1 for x in [a['confidence'], *p.values()]) or abs(sum(p.values())-1) > .02:
                    raise ValueError('Invalid Jev decision')
            mapping = dict(negative=-1, hold=0, positive=1)
            signs = [mapping[answers[a]['choice']] for a in 'xyz']
            row.update(answers=answers, signs=signs, rotation_signs=[mapping[answers[a]['choice']] if a in answers else 0 for a in ['rx', 'ry', 'rz']], model=raw.get('model'), gripper=answers['gripper']['choice'], transition=answers['transition']['choice'], candidate=answers['candidate']['choice'] if 'candidate' in answers else 'not_requested', metrics=direction_metrics([state['translation_axes'][a]['current_coordinate_m'] for a in 'xyz'], [state['translation_axes'][a]['goal_coordinate_m'] for a in 'xyz'], signs, state['axis_hold_tolerance_mm']/1000))
        except Exception as exc:
            row['error'] = str(exc).replace(self.api.credential, '[redacted]') if self.api.credential else str(exc)
            self.rec.errors.append(dict(type=type(exc).__name__))
            raise
        finally:
            row['request_seconds'] = time.monotonic()-started
            dump(folder/'decision.json', row)
            append(self.rec.folder/'decisions.jsonl', row)
        return row


def run_recovery(env, obs, rec, task, depth_fn, k_fn, t_fn):
    vision = GenericVision(rec)
    model = RecoveryModel(rec)
    phases = list(PHASES)
    rack_task = rec.cfg.get('suite') == 'libero_goal' and rec.cfg.get('task_id') == 1458
    if rack_task:
        phases.insert(phases.index('lower'), 'orient_receiver')
    lateral_first = rec.cfg.get('carry_route') == 'lateral_first'
    if lateral_first:
        phases.insert(phases.index('carry'), 'carry_lateral')
    own = gripper_geometry(env, obs)
    dump(rec.folder/'own-gripper.json', own)
    ticks = stage_ticks = stage_decisions = grip_ticks = 0
    gripper = -1
    stage = 'select'
    selected = 0
    grasp_tries = 0
    failed_candidates = []
    history = []
    stalls = 0
    holding = dict(status='not_checked_yet', valid=None)
    offset = None
    tcp_grasp = source_grasp = test_target = recovery_target = None
    error_message = None
    finished = False
    initial_src = src = dst = identity = None
    cached_external = None
    initial_source_points_world = None
    dark_source = False
    lift_verified = False
    carry_verified_stage = None
    grasp_orientation = grasp_offset = rack_geometry = None
    rack_verified = False
    rack_release_tcp = None
    rack_contact_checked = False
    rack_contact_evidence = dict(status='not_checked')
    visible_goal_evidence = dict(status='not_checked')

    def views():
        return {c: dict(rgb=np.ascontiguousarray(obs[c+'_image'][::-1]), depth=depth_fn(env.sim, obs[c+'_depth'])[::-1].squeeze(), K=k_fn(env.sim,c,obs[c+'_image'].shape[0],obs[c+'_image'].shape[1]), T=t_fn(env.sim,c)) for c in ['agentview','robot0_eye_in_hand']}

    def cloud(v):
        vv, uu = np.indices(v['depth'].shape)
        d, K, T = v['depth'], v['K'], v['T']
        return np.stack([(uu-K[0,2])*d/K[0,0], (vv-K[1,2])*d/K[1,1], d], -1) @ T[:3,:3].T + T[:3,3]

    def locate(reason):
        nonlocal identity, cached_external, initial_source_points_world, dark_source, rack_geometry
        vv = views()
        identity = vision.recognize(vv, task.language, reason)
        result = {}
        for role in ['source','destination']:
            ob = identity[role]
            v = vv[ob['camera']]
            result[role] = vision.measure(v, ob['bbox'], ob['label'], reason+'-'+role)
            if role == 'destination' and rack_task and reason == 'initial':
                mask = np.load(result[role]['visible_mask_path']).astype(bool)
                depth = v['depth']
                good = mask & np.isfinite(depth) & (depth > .02) & (depth < 3.)
                rack_geometry = fit_visible_rack(cloud(v)[good], result['source'])
                dump(rec.folder/'visible-rack-fit.json', rack_geometry)
            if role == 'source' and reason == 'initial':
                mask = np.load(result[role]['visible_mask_path'])
                valid = (mask & np.isfinite(v['depth']) &
                         (v['depth'] > .02) & (v['depth'] < 3.))
                initial_source_points_world = cloud(v)[valid]
                if len(initial_source_points_world) < 80:
                    raise RuntimeError('Insufficient initial visible source points')
                np.save(rec.folder/'initial-visible-source-cloud.npy',
                        initial_source_points_world)
                hsv = cv2.cvtColor(v['rgb'], cv2.COLOR_RGB2HSV)
                dark_source = bool(np.mean((hsv[:, :, 2][valid] < 100) &
                                           (hsv[:, :, 1][valid] > 50)) > .8)
                dump(rec.folder/'source-appearance.json', dict(
                    dark_saturated_fraction=float(np.mean(
                        (hsv[:, :, 2][valid] < 100) &
                        (hsv[:, :, 1][valid] > 50))),
                    use_dark_foreground_filter=dark_source,
                    source='Initial public RGB and SAM mask'))
            if role == 'source' and ob['camera'] == 'agentview':
                cached_external = dict(ob)
            if role == 'destination' and ob.get('receiver_kind') == 'open_container':
                uv = (np.asarray(ob['bbox'][:2])+ob['bbox'][2:])/2
                ray = v['T'][:3,:3] @ np.linalg.solve(v['K'], np.r_[uv,1.])
                distance = (result[role]['high'][2]-v['T'][2,3])/ray[2]
                if not 0 < distance < 3:
                    raise RuntimeError('Invalid visible receiver plane')
                result[role]['center'] = v['T'][:3,3] + distance*ray
        dump(rec.folder/(reason+'-geometry.json'), result)
        return result['source'], result['destination']

    def fuse(observed):
        if not rec.cfg['preserve_source']:
            return observed
        old_extent = initial_src['high']-initial_src['low']
        new_extent = observed['high']-observed['low']
        if np.any(new_extent[:2] < .7*old_extent[:2]) or new_extent[2] < .5*old_extent[2]:
            merged = dict(initial_src, partial_view=observed, source='Initial full visible bounds retained when fresh view is partial; no hidden dimensions')
            return merged
        return observed

    def support_level():
        v = views()['agentview']
        xyz = cloud(v)
        local = np.linalg.norm(xyz[:,:,:2]-src['center'][:2], axis=2) < .16
        outside = np.any((xyz[:,:,:2] < src['low'][:2]-.01) | (xyz[:,:,:2] > src['high'][:2]+.01), axis=2)
        good = local & outside & np.isfinite(v['depth']) & (abs(xyz[:,:,2]-src['low'][2]) < .06)
        z = xyz[:,:,2][good]
        if len(z) < 100:
            raise RuntimeError('Visible support unavailable')
        hist, edges = np.histogram(z, bins=120, range=(src['low'][2]-.06,src['low'][2]+.06))
        center = (edges[np.argmax(hist)]+edges[np.argmax(hist)+1])/2
        near = z[abs(z-center)<.003]
        return float(np.median(near)), int(len(near))

    def candidates():
        level, points = support_level()
        c = fit_candidates(src, own, obs['robot0_eef_pos'], obs['robot0_eef_quat'], level, points, rec.cfg, failed_candidates)
        dump(rec.folder/f'candidates-{grasp_tries:02d}.json',c)
        return c

    def check_hold(use_projection=False, rotation_aware=False):
        nonlocal holding, offset, src
        vv = views()
        if rotation_aware:
            if grasp_orientation is None or grasp_offset is None:
                raise RuntimeError('No measured grasp pose for rotated hold check')
            current_orientation = Rotation.from_quat(obs['robot0_eef_quat']).as_matrix()
            relative_rotation = current_orientation @ grasp_orientation.T
            expected = obs['robot0_eef_pos'] + relative_rotation @ grasp_offset
        else:
            relative_rotation = np.eye(3)
            expected = source_grasp+(obs['robot0_eef_pos']-tcp_grasp)
        projection = vision.static_mode or use_projection
        if projection:
            # Reproject the actually segmented visible RGB-D points. Corners
            # of an axis-aligned 3-D box create an overly wide projected box
            # for a tall, thin object and contaminate the SAM hold check.
            v = vv['agentview']
            if initial_source_points_world is None:
                raise RuntimeError('Initial visible source cloud unavailable')
            moved = ((initial_source_points_world-source_grasp) @
                     relative_rotation.T + expected)
            camera = (moved-v['T'][:3,3]) @ v['T'][:3,:3]
            if np.any(camera[:,2] <= .02):
                raise RuntimeError('Expected lifted source behind camera')
            projected = camera @ v['K'].T
            uv = projected[:,:2]/projected[:,2,None]
            low_uv, high_uv = np.quantile(uv, [.01, .99], axis=0)
            box = np.r_[low_uv-8,high_uv+8].clip(0,767).tolist()
            if box[2]-box[0] < 12 or box[3]-box[1] < 12:
                raise RuntimeError('Projected visible source box too small')
            ob = dict(camera='agentview',bbox=box,label=identity['source']['label'])
            dump(rec.folder/f'hold-projection-{ticks:04d}.json',dict(
                expected=expected,bbox=box,visible_source_points=len(moved),
                projection_quantiles=[.01,.99],
                source='Initial visible SAM/RGB-D source points transformed by own TCP pose'))
        elif 'lift_check' not in vision.reasons and vision.calls < 3:
            ids = vision.recognize(vv, task.language, 'lift_check')
            ob = ids['source']
        else:
            ob = cached_external
        if ob is None:
            holding = dict(valid=None,status='unavailable',reason='No cached external source identity')
            return
        try:
            h = vision.measure(vv[ob['camera']],ob['bbox'],ob['label'],'test-lift-hold')
        except RuntimeError as exc:
            if not projection:
                raise
            try:
                still = vision.measure(vv['agentview'],identity['source']['bbox'],
                                       identity['source']['label'],'test-lift-original-site')
                unmoved = bool(np.linalg.norm(still['center']-source_grasp)<.025)
            except RuntimeError:
                still = None
                unmoved = False
            holding = dict(valid=False if unmoved else None,
                           status='failed' if unmoved else 'unavailable',
                           reason='Lifted-source mask unavailable: '+str(exc),
                           original_site=still, observed_tick=ticks)
            dump(rec.folder/f'holding-{ticks:04d}.json',holding)
            return
        appearance_filtered = False
        if dark_source:
            v = vv[ob['camera']]
            mask = np.load(h['visible_mask_path']).astype(bool)
            hsv = cv2.cvtColor(v['rgb'], cv2.COLOR_RGB2HSV)
            selected = (mask & (hsv[:, :, 2] < 100) &
                        (hsv[:, :, 1] > 50) & np.isfinite(v['depth']) &
                        (v['depth'] > .02) & (v['depth'] < 3.))
            # Only replace a visibly contaminated SAM extent; a clean mask
            # remains on its original geometric validation path.
            raw_ratio = float(np.linalg.norm(h['high']-h['low']) /
                              max(np.linalg.norm(initial_src['high']-initial_src['low']),1e-6))
            raw_mismatch = float(np.linalg.norm(h['center']-expected))
            if raw_ratio > 1.5 or raw_mismatch > .05:
                if selected.sum() < 400 or selected.sum() < .25*mask.sum():
                    holding = dict(valid=None,status='unavailable',
                                   reason='Visible appearance insufficient to separate held source from gripper',
                                   observed_tick=ticks)
                    dump(rec.folder/f'holding-{ticks:04d}.json', holding)
                    return
                data = cloud(v)[selected]
                low, high = np.quantile(data,[.05,.95],axis=0)
                h = dict(h, low=low, high=high, center=(low+high)/2,
                         points=len(data),
                         source='SAM/RGB-D with initial visible dark-foreground appearance gate')
                appearance_filtered = True
                dump(rec.folder/f'holding-appearance-{ticks:04d}.json',h)
        rise = float(h['center'][2]-source_grasp[2])
        mismatch = float(np.linalg.norm(h['center']-expected))
        size_ratio = float(np.linalg.norm(h['high']-h['low']) /
                           max(np.linalg.norm(initial_src['high']-initial_src['low']),1e-6))
        min_rise = .03 if use_projection else .01 if appearance_filtered else .015
        valid = rise > min_rise and mismatch < .065 and .4 < size_ratio < 1.7
        holding = dict(valid=bool(valid),status='passed' if valid else 'failed',
                       source='Visible RGB-D co-motion proxy',
                       source_rise_mm=rise*1000,co_motion_error_mm=mismatch*1000,
                       visible_span_ratio=size_ratio,appearance_filtered=appearance_filtered,
                       second_lift_check=use_projection,measured=h,expected=expected,
                       observed_tick=ticks)
        if valid:
            offset = h['center']-obs['robot0_eef_pos']
        elif rise < .015:
            src = fuse(h)
        dump(rec.folder/f'holding-{ticks:04d}.json',holding)

    def check_visible_support_goal():
        nonlocal visible_goal_evidence
        if vision.calls >= 3:
            visible_goal_evidence = dict(status='unavailable', reason='Semantic visual budget exhausted')
            dump(rec.folder/f'visible-goal-{ticks:04d}.json',visible_goal_evidence)
            return
        try:
            vv = views()
            found = vision.recognize(vv, task.language, 'stalled')
            ob = found['source']
            measured = vision.measure(vv[ob['camera']], ob['bbox'], ob['label'],
                                      'visible-goal-source')
            if rack_task:
                v = vv[ob['camera']]
                mask = np.load(measured['visible_mask_path']).astype(bool)
                good = (mask & np.isfinite(v['depth']) &
                        (v['depth'] > .02) & (v['depth'] < 3.))
                source_points = cloud(v)[good]
                if len(source_points) < 300:
                    raise RuntimeError('Insufficient released source pixels for rack check')
                rack_center = np.asarray(rack_geometry['center_world_m'], float)
                slope = rack_geometry['support_slope_dz_dy']
                surface_z = (rack_geometry['visible_surface_z_m'] +
                             slope*(source_points[:,1]-rack_center[1]))
                normal_gap = ((source_points[:,2]-surface_z)/
                              np.sqrt(1+slope*slope))
                y_low, y_high = rack_geometry['y_visible_quantile_range_m']
                near_support = (np.abs(source_points[:,0]-rack_center[0]) < .075
                    ) & (source_points[:,1] > y_low-.03) & (
                    source_points[:,1] < y_high+.03) & (
                    normal_gap > -.06) & (normal_gap < .08)
                supported_fraction = float(np.mean(near_support))
                center_rise = float(measured['center'][2]-initial_src['center'][2])
                passed = bool(supported_fraction > .12 and center_rise > .08 and
                    abs(measured['center'][0]-rack_center[0]) < .085)
                visible_goal_evidence = dict(
                    status='passed' if passed else 'failed',
                    released_source_near_visible_rack_fraction=supported_fraction,
                    center_rise_from_initial_m=center_rise,
                    source_center_world_m=measured['center'],
                    source_pixels=len(source_points),
                    observed_tick=ticks,
                    source='Fresh public RGB-D/SAM released source vs initial visible rack support; no native success input')
                dump(rec.folder/f'visible-goal-{ticks:04d}.json',visible_goal_evidence)
                return
            low, high = measured['low'], measured['high']
            width = np.maximum(high[:2]-low[:2], 1e-6)
            overlap = np.maximum(0., np.minimum(high[:2],dst['high'][:2])-
                                 np.maximum(low[:2],dst['low'][:2]))
            footprint_overlap = float(np.prod(overlap/width))
            bottom_gap = float(low[2]-dst['high'][2])
            center_rise = float(measured['center'][2]-initial_src['center'][2])
            passed = bool(footprint_overlap>.2 and -.02<bottom_gap<.06 and
                          center_rise>.08)
            visible_goal_evidence = dict(status='passed' if passed else 'failed',
                footprint_overlap=footprint_overlap,bottom_gap_m=bottom_gap,
                center_rise_from_initial_m=center_rise,
                measured_source=measured,
                receiver=dst,
                source='Fresh public RGB-D/SAM source vs previously visible receiver surface')
        except Exception as exc:
            visible_goal_evidence = dict(status='unavailable',reason=str(exc))
        dump(rec.folder/f'visible-goal-{ticks:04d}.json',visible_goal_evidence)

    try:
        initial_src, dst = locate('initial')
        src = initial_src
        cs = candidates()
        hover = max(src['high'][2],dst['high'][2])+(.17 if rack_task else .12)
        while True:
            rec.check_budget()
            if ticks >= NATIVE_BUDGET or stage_decisions >= 45:
                raise RuntimeError('Stage/native budget: '+stage)
            if (rec.cfg.get('visible_goal_check') and stage == 'select' and grasp_tries and
                    visible_goal_evidence['status']=='not_checked'):
                check_visible_support_goal()
            c = cs[selected]
            Rgoal = c['orientation']
            if rack_task and stage in ('orient_receiver','lower','release','retreat'):
                Rgoal = (Rotation.from_rotvec(
                    np.array([rack_geometry['x_rotation_world_rad'],0.,0.])).as_matrix()
                    @ c['orientation'])
            position = obs['robot0_eef_pos'].copy()
            if stage in ['select','grasp','release','recover_open']:
                target = position.copy()
            elif stage in ['approach','align']:
                target = c['target'].copy();target[2]=hover
            elif stage == 'descend':
                target = c['target'].copy()
            elif stage == 'test_lift':
                target = test_target
            elif stage == 'lift':
                target = np.r_[tcp_grasp[:2],hover]
            elif stage == 'carry_lateral':
                # Public source/receiver geometry gives a two-leg path. The
                # object crosses sideways at the source-side Y before moving
                # toward the receiver, clearing a visible rear obstacle.
                target = np.r_[dst['center'][0]-offset[0],tcp_grasp[1],hover]
            elif stage in ['carry','orient_receiver']:
                target = np.r_[dst['center'][:2]-(offset[:2] if offset is not None else 0),hover]
            elif stage == 'retreat' and rack_task:
                target = np.r_[rack_release_tcp[:2],hover]
            elif stage == 'retreat':
                target = np.r_[dst['center'][:2]-(offset[:2] if offset is not None else 0),hover]
            elif stage == 'lower':
                if rack_task:
                    # Rotation and contact can shift the source inside the
                    # fingers. Use the fresh post-rotation visible offset.
                    target = np.asarray(rack_geometry['center_world_m'])-offset
                else:
                    target = np.r_[dst['center'][:2]-offset[:2],dst['high'][2]+(initial_src['high'][2]-initial_src['low'][2])/2+.012-offset[2]]
            elif stage == 'recover_up':
                target = recovery_target
            else:
                raise ValueError(stage)
            error = target-position
            tol = .003 if stage == 'descend' else .006
            arrived = bool(np.max(abs(error)) < tol)
            rot = Rotation.from_matrix(Rgoal@Rotation.from_quat(obs['robot0_eef_quat']).as_matrix().T).as_rotvec()
            oriented = bool(np.max(abs(rot)) < .03)
            aperture = float(np.sum(abs(obs['robot0_gripper_qpos']))*1000)
            if stage == 'test_lift' and arrived and holding['status']=='not_checked_yet':
                check_hold()
                cs = cs  # candidate stays frozen through a grasp attempt
            if (stage == 'lift' and arrived and
                    holding.get('appearance_filtered') and not lift_verified):
                check_hold(use_projection=True)
                lift_verified = True
            if (stage in ('carry_lateral', 'carry') and arrived and dark_source and
                    carry_verified_stage != stage):
                check_hold(use_projection=True)
                carry_verified_stage = stage
            if stage == 'orient_receiver' and arrived and oriented and not rack_verified:
                check_hold(use_projection=True, rotation_aware=True)
                rack_verified = True
            if stage == 'lower' and rack_task and (arrived or stalls >= 2) and not rack_contact_checked:
                check_hold(use_projection=True, rotation_aware=True)
                rack_contact_checked = True
                if holding['status'] == 'passed':
                    measured_center = np.asarray(holding['measured']['center'], float)
                    rack_center = np.asarray(rack_geometry['center_world_m'], float)
                    slope = rack_geometry['support_slope_dz_dy']
                    surface_z = (rack_geometry['visible_surface_z_m'] +
                                 slope*(measured_center[1]-rack_center[1]))
                    normal_gap = float((measured_center[2]-surface_z)/
                                       np.sqrt(1+slope*slope))
                    y_low, y_high = rack_geometry['y_visible_quantile_range_m']
                    in_footprint = bool(abs(measured_center[0]-rack_center[0]) < .055
                        and y_low-.015 < measured_center[1] < y_high+.015)
                    radius = rack_geometry['source_visible_radius_m']
                    candidate = bool(in_footprint and
                        -.01 < normal_gap < radius+.025)
                    rack_contact_evidence = dict(
                        status='visible_contact_candidate' if candidate else 'not_near_visible_support',
                        source_center_world_m=measured_center.tolist(),
                        normal_gap_m=normal_gap, visible_source_radius_m=radius,
                        in_visible_rack_footprint=in_footprint, observed_tick=ticks,
                        source='Fresh public RGB-D held-source mask vs visible rack slope')
                else:
                    rack_contact_evidence = dict(status='unavailable',
                        holding_status=holding['status'],observed_tick=ticks)
                dump(rec.folder/f'rack-contact-{ticks:04d}.json',rack_contact_evidence)
            required_open = stage in ['approach','align','descend','release','retreat','recover_open']
            required_close = stage in ['grasp','test_lift','lift','carry_lateral','carry','orient_receiver','lower']
            contracts = dict(select='Choose an unfailed candidate, then advance. Hold XYZ. Gripper open. If fresh visible support evidence passed, choose finish_if_visible instead of another grasp.',approach='Reach hover pose above candidate and align orientation with gripper open.',align='Reach refreshed hover pose/orientation with gripper open.',descend='Reach supplied pad-fit pose with gripper open; if motion stalls but own open pads overlap the latest visible source bounds in all axes, you may advance to one closure trial. This overlap is not grasp proof.',grasp=f'Hold TCP, close for at least {rec.cfg.get("grasp_hold_ticks", 18)} native ticks, then advance to a short lift test. Closure is not holding proof.',test_lift='Keep closed and reach short lift goal. Advance only if measured holding passed. Retry if failed and budget remains.',lift='Keep closed and reach clearance height with passed holding evidence.',carry='Keep closed and reach pose over receiver with passed holding evidence.',lower='Keep closed and reach supplied release pose.',release='Hold TCP and open for at least 24 native ticks AND aperture >=70mm.',retreat='Withdraw upward with gripper open, then advance to end attempt.',recover_up='Withdraw to supplied clearance pose. Keep current grip until clear.',recover_open='Hold TCP and open for >=24 ticks AND aperture >=70mm, then advance to select another candidate.')
            contracts['carry_lateral'] = 'Keep closed and move sideways at source-side Y to the visible receiver X corridor. Advance only after arrival and passed visual holding check.'
            contracts['orient_receiver'] = ('Keep closed at the high hover pose. Rotate the held bottle toward the slope measured from the visible rack RGB-D surface. '
                                            'Advance only after arrival and a fresh rotated visible holding check passes.')
            if rack_task:
                contracts['lower'] = ('Keep closed and approach the rack using the bottle offset measured after rotation. '
                                      'Advance to one release trial only when a fresh public RGB-D source/rack contact candidate passes after arrival or blocked motion. '
                                      'This geometric candidate is not native success.')
            if dark_source:
                contracts['carry'] += ' At arrival, require a fresh visible holding check before advance.'
            if stage == 'lift' and holding.get('appearance_filtered'):
                contracts['lift'] += ' At clearance, advance only after the second visible holding check passes.'
            complete = arrived and oriented
            pad_overlap_mm = None
            contact_trial = False
            if stage == 'descend':
                pad_vertices = (np.asarray(own['pad_vertices_tool']) @
                    Rotation.from_quat(obs['robot0_eef_quat']).as_matrix().T + position)
                pad_low, pad_high = np.quantile(pad_vertices, [.05, .95], axis=0)
                overlap = np.maximum(0., np.minimum(pad_high, src['high'])-
                                     np.maximum(pad_low, src['low']))
                pad_overlap_mm = np.round(overlap*1000, 2).tolist()
                contact_trial = bool(stalls >= 3 and oriented and
                    np.all(overlap >= .005) and
                    c['estimated_finger_table_clearance_mm'] > 1.)
                complete = bool(complete or contact_trial)
            if stage == 'select':complete=True
            if stage == 'grasp':complete=grip_ticks>=rec.cfg.get('grasp_hold_ticks', 18) and gripper==1
            if stage in ['release','recover_open']:complete=grip_ticks>=24 and aperture>=70 and gripper==-1
            if stage == 'test_lift':complete=complete and holding['status']=='passed'
            if stage == 'lift' and lift_verified:complete=complete and holding['status']=='passed'
            if stage == 'orient_receiver':complete=complete and rack_verified and holding['status']=='passed'
            if stage == 'lower' and rack_task:
                complete=bool(oriented and rack_contact_checked and
                    rack_contact_evidence['status']=='visible_contact_candidate' and
                    (arrived or stalls>=2))
            if stage in ('carry_lateral','carry') and dark_source:
                complete=complete and carry_verified_stage==stage and holding['status']=='passed'
            can_retry = rec.cfg['allow_retry'] and grasp_tries<3 and stage not in ['select','release','retreat','recover_up','recover_open'] and (stalls>=3 or holding['status'] in ('failed','unavailable') or (stage=='lower' and rack_contact_checked and rack_contact_evidence['status']!='visible_contact_candidate'))
            next_stage = 'select' if stage=='recover_open' else 'recover_open' if stage=='recover_up' else 'finish_attempt' if stage=='retreat' else phases[phases.index(stage)+1]
            finish_if_visible = bool(stage=='select' and visible_goal_evidence['status']=='passed')
            can_continue = not (rack_task and stage == 'lower' and stalls >= 3 and
                rack_contact_checked and
                rack_contact_evidence['status'] != 'visible_contact_candidate')
            state = dict(task=task.language,operation=stage,next_operation=next_stage,operation_contract=contracts[stage],position_m=position.tolist(),target_position_m=target.tolist(),target_minus_current_mm=np.round(error*1000,2).tolist(),axis_hold_tolerance_mm=2.,arrival_tolerance_mm=tol*1000,required_rotation_world_rad=dict(zip(['rx','ry','rz'],rot.tolist())),gripper=dict(aperture_mm=aperture,last_command='open' if gripper==-1 else 'close',executed_command_ticks=grip_ticks,required_state='open' if required_open else 'closed' if required_close else 'preserve',closure_nearly_empty=bool(aperture<3)),completion_evidence=dict(position_arrived=arrived,orientation_arrived=oriented,contract_satisfied=bool(complete),holding_status=holding['status'],gripper_command_ticks=grip_ticks,visible_pad_envelope_overlap_xyz_mm=pad_overlap_mm,blocked_visible_contact_trial=contact_trial),holding_evidence=holding,allowed_transitions=dict(continue_phase=can_continue,advance=bool(complete and not finish_if_visible),retry=bool(can_retry),stop=True,finish_if_visible=finish_if_visible),visible_goal_evidence=visible_goal_evidence if stage=='select' else dict(status='not_requested'),selected_candidate=c['id'],candidates=[{k:v for k,v in cc.items() if k not in ['orientation','target']} for cc in cs],failed_candidates=[f'candidate_{i}' for i in failed_candidates],grasp_attempts=grasp_tries,recent_actions=history[-3:],blocked_action_count=stalls,phase_decisions=stage_decisions,information_sources='Public task + rendered RGB-D/calibration + own robot proprioception/mesh. No scene truth/reward/success.')
            if rack_task and stage == 'lower':
                state['completion_evidence']['visible_rack_contact'] = rack_contact_evidence
            if rack_task and stage in ('orient_receiver','lower'):
                state['visible_receiver_geometry'] = {k:rack_geometry[k] for k in (
                    'center_world_m','visible_surface_z_m','x_rotation_world_rad',
                    'support_slope_dz_dy','line_residual_p90_m','source')}
            adaptive=rec.cfg.get('execution_profile','baseline')=='adaptive'
            block_ticks=6 if adaptive and (stage in ['grasp','release','recover_open'] or np.max(abs(error))>.06) else 3
            state['gripper']['next_action_block_native_ticks']=block_ticks
            state['translation_axes']={a:dict(current_coordinate_m=float(position[i]),goal_coordinate_m=float(target[i]),goal_minus_current_mm=round(float(error[i])*1000,2),relation='within_tolerance' if abs(error[i])<.002 else 'goal_coordinate_larger' if error[i]>0 else 'goal_coordinate_smaller') for i,a in enumerate('xyz')}
            state['rotation_questions']='Only axes outside 0.03rad tolerance are requested; unrequested rotations are zero, not fabricated model choices.'
            if rec.cfg['input_organization']=='local':
                state['local_decision_summary']=dict(operation=stage,xyz_error_mm=np.round(error*1000,2).tolist(),can_finish=bool(complete),holding=holding['status'],blocked=stalls>=3,can_retry=bool(can_retry),gripper_state_to_maintain=state['gripper']['required_state'])
            if rec.cfg['input_organization']=='evidence':
                state['evidence_interpretation']='contract_satisfied is a measured conjunction of the listed tests, not task success. failed holding means the source did not follow the robot; not_checked_yet means continue the pending test. Failed or blocked attempts may use retry. Pick candidates by physical overlap/clearance, never by index alone.'
            if rec.cfg['input_organization']=='focused':
                keep=['task','operation','next_operation','operation_contract','translation_axes','axis_hold_tolerance_mm','arrival_tolerance_mm','required_rotation_world_rad','gripper','completion_evidence','allowed_transitions','visible_goal_evidence','blocked_action_count','recent_actions','information_sources','grasp_attempts','failed_candidates','selected_candidate','phase_decisions']
                focused={k:state[k] for k in keep}
                focused['holding_evidence']={k:v for k,v in holding.items() if k in ['status','valid','source','source_rise_mm','co_motion_error_mm','observed_tick','reason']}
                if stage=='select' and not finish_if_visible:focused['candidates']=state['candidates']
                elif stage=='select':focused['candidate_selection']='not_requested_when_visible_goal_passed'
                else:focused['selected_candidate_geometry']={k:c[k] for k in ['visible_width_mm','estimated_pad_overlap_mm','estimated_finger_table_clearance_mm']}
                if 'visible_receiver_geometry' in state:
                    focused['visible_receiver_geometry']=state['visible_receiver_geometry']
                state=focused
            state = json.loads(json.dumps(state,default=serial,allow_nan=False))
            d = model.decide(state);stage_decisions+=1
            if d['transition']=='stop':raise RuntimeError('Jev elected stop')
            if d['transition']=='finish_if_visible' and not finish_if_visible:
                raise RuntimeError('Jev requested unavailable visual finish')
            if stage=='select':
                if d['candidate'].startswith('candidate_'):
                    selected=int(d['candidate'].split('_')[-1]);c=cs[selected]
                elif d['transition']=='advance':raise RuntimeError('Jev advanced without selecting candidate')
            newgrip=gripper if d['gripper']=='keep' else -1 if d['gripper']=='open' else 1
            if newgrip!=gripper:grip_ticks=0
            gripper=newgrip
            cap=(.02 if np.max(abs(error))>.05 else .006 if np.max(abs(error))>.015 else .003) if stage in ['descend','test_lift','lower'] else .02
            gain=.35 if block_ticks==6 else .5
            delta=np.asarray(d['signs'])*np.minimum(cap,gain*abs(error))
            rotation=np.asarray(d['rotation_signs'])*np.minimum(.10,gain*abs(rot))
            before=position.copy()
            if ticks+block_ticks>NATIVE_BUDGET:raise RuntimeError('Native block budget')
            for _ in range(block_ticks):
                obs,_,_,_=env.step(np.r_[delta/.05,rotation/.5,gripper]);ticks+=1;stage_ticks+=1;grip_ticks+=1
            after=obs['robot0_eef_pos'].copy()
            progress=float(np.linalg.norm(error)-np.linalg.norm(target-after))
            stalls=stalls+1 if np.linalg.norm(after-before)<.0008 and np.linalg.norm(error)>.008 else 0
            rec.branch(dict(stage=stage,decision_id=d['decision_id'],delta=delta,before=before,after=after,native_steps=ticks,selected_gripper=d['gripper'],executed_gripper=gripper,selected_transition=d['transition'],block_native_ticks=block_ticks,selected_candidate=c['id'],rotation_signs=d['rotation_signs'],rotation_error_rad=rot,progress_m=progress))
            history.append(dict(gripper=d['gripper'],transition=d['transition'],progress_mm=round(progress*1000,2),actual_displacement_mm=np.round((after-before)*1000,2).tolist()))
            for cam,v in views().items():cv2.imwrite(str(rec.folder/f'{ticks:04d}-{stage}-{cam}.png'),cv2.cvtColor(v['rgb'],cv2.COLOR_RGB2BGR))
            transition=d['transition']
            if transition=='finish_if_visible':
                if stage!='select' or gripper!=-1 or aperture<70:
                    raise RuntimeError('Visual finish requires select with opened gripper')
                to_stage='finish_attempt'
            elif transition=='retry':
                if not can_retry:raise RuntimeError('Jev requested unavailable retry')
                failed_candidates.append(selected)
                recovery_target=np.r_[after[:2],max(hover,after[2]+.06)]
                to_stage='recover_up'
                holding=dict(status='not_checked_yet',valid=None)
                offset=grasp_offset=grasp_orientation=None
                lift_verified=False
                carry_verified_stage=None
                rack_verified=False
                rack_contact_checked=False
                rack_contact_evidence=dict(status='not_checked')
            elif transition=='advance':
                to_stage=next_stage
                if stage=='select':
                    if selected in failed_candidates:raise RuntimeError('Jev repeated failed candidate')
                    grasp_tries+=1
                if stage=='approach' and 'pregrasp' not in vision.reasons:
                    fresh, dst=locate('pregrasp');src=fuse(fresh);cs=candidates()
                if stage=='grasp':
                    tcp_grasp=obs['robot0_eef_pos'].copy();source_grasp=src['center'].copy();test_target=tcp_grasp+np.array([0.,0.,.05]);holding=dict(status='not_checked_yet',valid=None)
                    grasp_orientation=Rotation.from_quat(obs['robot0_eef_quat']).as_matrix()
                    grasp_offset=None
                    lift_verified=False
                    carry_verified_stage=None
                    rack_verified=False
                    rack_contact_checked=False
                    rack_contact_evidence=dict(status='not_checked')
                if stage=='test_lift':
                    if offset is None:raise RuntimeError('Jev advanced without holding evidence')
                    grasp_offset=offset.copy()
                if stage=='release' and rack_task:
                    rack_release_tcp=obs['robot0_eef_pos'].copy()
                if stage=='recover_open':cs=candidates()
            else:
                continue
            rec.event(dict(kind='phase_transition',from_stage=stage,to_stage=to_stage,decision_id=d['decision_id'],selected_transition=transition))
            stage=to_stage;stage_decisions=stage_ticks=grip_ticks=stalls=0
            if stage=='finish_attempt':finished=True;break
    except Exception as exc:
        error_message=str(exc);rec.event(dict(kind='stop',reason=error_message))
    finally:
        success=bool(env.check_success())  # Terminal evaluation only.
        backend='gpt-6-sol/xhigh via ChatGPT Codex' if os.environ.get('JEV_RSI_MODEL_BACKEND')=='codex_pro' else 'Jev'
        dump(rec.folder/'result.json',dict(success=success,program_finished=finished,error=error_message,native_steps=ticks,jev_calls=len(rec.decisions),model_control_calls=len(rec.decisions),semantic_calls=vision.calls,deepseek_calls=0,stage=stage,grasp_attempts=grasp_tries,failed_candidates=failed_candidates,ownership=backend+' XYZ/rotation/gripper/candidate/phase/retry',input_organization=rec.cfg['input_organization'],model_backend=backend))
        rec.finish('success' if success else 'failed');model.close();vision.close()

"""Visible RGB-D contact-push primitive with model-owned decisions.

Only public language, rendered cameras, calibration and own robot state/mesh
enter the policy. The evaluator's success predicate is read once, at the end.
"""
import base64
import hashlib
import io
import json
import math
import os
import time

import cv2
import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation

from libero_generic_vision import GenericVision
from libero_robot_geometry import gripper_geometry, envelope
from run_position_pilot import Jev, append, direction_metrics, dump, serial


PHASES = ('prepare', 'approach', 'lower', 'push', 'retreat')


def world_cloud(view):
    vv, uu = np.indices(view['depth'].shape)
    d, k, t = view['depth'], view['K'], view['T']
    cam = np.stack(((uu-k[0, 2])*d/k[0, 0],
                    (vv-k[1, 2])*d/k[1, 1], d), axis=-1)
    return cam @ t[:3, :3].T + t[:3, 3]


def visible_rear_extent(view, mask, source, direction):
    """Robust trailing support of any segmented tabletop object along a push."""
    if mask.shape != view['depth'].shape:
        raise RuntimeError('Visible source mask/depth shape mismatch')
    good = mask & np.isfinite(view['depth']) & (view['depth'] > .02) & (view['depth'] < 3.)
    if int(good.sum()) < 80:
        raise RuntimeError('Insufficient visible source pixels for push extent')
    points = world_cloud(view)[good]
    projection = (points[:, :2]-source['center'][:2]) @ direction
    rear = -float(np.quantile(projection, .05))
    if not .005 < rear < .20:
        raise RuntimeError('Visible rear push extent outside supported range')
    return rear


def contact_push_plan(source, goal, own, current_orientation=None,
                      observed_rear_extent_m=None, rear_standoff_m=.010,
                      preserve_downward=True, lateral_contact_offset_m=0.,
                      contact_mode='rear_edge'):
    """Derive a pushing line only from RGB-D bounds and the robot's own mesh."""
    travel = goal[:2]-source['center'][:2]
    distance = float(np.linalg.norm(travel))
    if not .04 < distance < .55:
        raise RuntimeError('Visible push distance outside supported range')
    direction = travel/distance
    if abs(goal[2]-source['low'][2]) > .065:
        raise RuntimeError('Proposed goal not on visible source support level')
    xaxis = np.r_[direction, 0.]
    yaxis = np.r_[direction[::-1]*np.array([1., -1.]), 0.]
    proposed = np.column_stack((xaxis, yaxis, [0., 0., -1.]))
    if np.linalg.det(proposed) < 0:
        proposed[:, 1] *= -1
    # A downward pusher needs no yaw alignment to make side contact. Keep an
    # already-downward wrist pose to avoid sweeping the arm through obstacles.
    preserve = preserve_downward and current_orientation is not None and float(
        np.asarray(current_orientation)[2, 2]) < -.90
    orientation = np.asarray(current_orientation) if preserve else proposed
    own_box = envelope(own, orientation)
    fingers = own['finger_vertices_tool'] @ orientation.T
    leading = float(np.max(fingers @ xaxis))
    finger_high = float(fingers[:, 2].max())
    rear_extent = (float(observed_rear_extent_m) if observed_rear_extent_m is not None
        else float(np.dot(np.abs(direction), (source['high']-source['low'])[:2]/2)))
    if not -.020 <= rear_standoff_m <= .030:
        raise ValueError('Rear standoff outside declared contact range')
    if not -.045 <= lateral_contact_offset_m <= .045:
        raise ValueError('Lateral contact offset outside visible object support')
    lateral_axis = np.array([direction[1], -direction[0]])
    if contact_mode == 'rear_edge':
        contact_xy = (source['center'][:2] - direction*(rear_extent+leading+.004)
                      + lateral_axis*lateral_contact_offset_m)
        contact_z = goal[2]+.004-own_box['finger_low_z_offset']
    elif contact_mode == 'top_surface':
        if lateral_contact_offset_m:
            raise ValueError('Top contact must remain at observed source centre')
        contact_xy = np.asarray(source['center'][:2], float)
        # Four millimetres of commanded finger-pad contact accounts for the
        # OSC controller's residual tracking error; it is not scene truth.
        contact_z = source['high'][2]-.004-own_box['finger_low_z_offset']
    else:
        raise ValueError('Unknown visible contact mode')
    finger_low_world = contact_z+own_box['finger_low_z_offset']
    finger_high_world = contact_z+finger_high
    if (contact_mode == 'rear_edge' and
            (finger_low_world > source['high'][2]-.001 or
             finger_high_world < source['low'][2]+.001)):
        raise RuntimeError('Own finger envelope misses observed object height')
    hover_z = max(contact_z+.20, source['high'][2]+.20)
    standoff = rear_standoff_m if contact_mode == 'rear_edge' else 0.
    approach = np.r_[contact_xy-direction*standoff, hover_z]
    lower = np.r_[contact_xy-direction*standoff, contact_z]
    contact = np.r_[contact_xy, contact_z]
    push_end = np.r_[contact_xy+direction*(distance+.025), contact_z]
    retreat = push_end+np.array([0., 0., .10])
    return dict(orientation=orientation,
        orientation_source='preserved downward robot pose' if preserve else
            'downward pose derived from visible push direction',
        direction=direction,
        observed_rear_extent_m=rear_extent,
        rear_standoff_m=rear_standoff_m,
        contact_mode=contact_mode,
        lateral_contact_offset_m=lateral_contact_offset_m,
        lateral_contact_axis_xy=lateral_axis,
        rear_extent_source='visible SAM mask/RGB-D 5th percentile' if observed_rear_extent_m is not None else 'RGB-D axis bounds fallback',
        own_finger_leading_offset_m=leading,
        own_finger_high_offset_m=finger_high, own_envelope=own_box,
        finger_world_z_interval_m=[finger_low_world,finger_high_world],
        approach=approach, lower=lower, contact=contact, push_end=push_end,
        retreat=retreat)


class PushVision(GenericVision):
    def locate(self, views, public_task, reason, previous=None):
        if reason not in ('initial', 'reobserve', 'after_push') or self.calls >= 3:
            raise RuntimeError('Push semantic-vision trigger/budget')
        self.calls += 1
        folder = self.rec.folder / f'semantic-{self.calls}'
        folder.mkdir()
        instruction = (
            'For the public tabletop pushing instruction, identify the same visible '
            'object to push. Return JSON containing source and destination, each '
            'with {label, camera, bbox:[x1,y1,x2,y2], visible}, plus evidence. '
            'Labels and evidence must be English. The source box encloses only '
            'the visible object, without the robot. Destination is a small '
            'visible, empty tabletop patch in agentview where the object centre '
            'should end, satisfying the public spatial relation. Keep a straight '
            'route clear of visible objects. Do not use unseen regions or imagine '
            'simulator coordinates. At after_push report the moved source and '
            'the same destination patch, not a new target. At reobserve, '
            'find the SAME source and destination from previous, even if the '
            'robot partly occludes them; if ambiguous set visible=false. If source '
            'identity is ambiguous, visible=false. Prefer agentview when the '
            'wrist image crops the source. Return pixel coordinates for '
            'the supplied image size; do not propose motor actions or success claims.')
        content = [dict(type='input_text', text=json.dumps(dict(
            task=public_task, reason=reason, previous=previous)))]
        for name, view in views.items():
            buffer = io.BytesIO()
            Image.fromarray(view['rgb']).save(buffer, 'PNG')
            content += [dict(type='input_text', text=f'{name}: '
                f'{view["rgb"].shape[1]}x{view["rgb"].shape[0]} pixels'),
                dict(type='input_image', image_url='data:image/png;base64,'+
                     base64.b64encode(buffer.getvalue()).decode(), detail='high')]
        request = dict(model=self.api.cfg['model'], instructions=instruction,
            input=[dict(role='user', content=content)], max_output_tokens=2000,
            store=False, text=dict(format=dict(type='json_object')))
        dump(folder/'request.json', request)
        raw = self.api.post('/responses', request)
        dump(folder/'response.json', raw)
        if raw.get('status') != 'completed':
            raise RuntimeError('Incomplete push semantic response')
        answer = json.loads(''.join(c.get('text', '') for row in raw.get('output', [])
            for c in row.get('content', []) if c.get('type') == 'output_text'))
        source = answer['source']
        if not source['visible'] or source['camera'] not in views:
            raise RuntimeError('Visible source not identified')
        view = views[source['camera']]
        box = np.asarray(source['bbox'], float)
        if (box.shape != (4,) or not np.isfinite(box).all() or
                not (0 <= box[0] < box[2] <= view['rgb'].shape[1] and
                     0 <= box[1] < box[3] <= view['rgb'].shape[0])):
            raise RuntimeError('Invalid visible source box')
        if reason == 'initial':
            destination = answer['destination']
            v = views['agentview']
            db = np.asarray(destination['bbox'], float)
            if (not destination['visible'] or destination['camera'] != 'agentview'
                    or db.shape != (4,) or not np.isfinite(db).all() or
                    not (5 <= db[0] < db[2] <= v['rgb'].shape[1]-5 and
                         5 <= db[1] < db[3] <= v['rgb'].shape[0]-5)):
                raise RuntimeError('Invalid visible goal patch')
            answer['goal_uv'] = ((db[:2]+db[2:])/2).tolist()
        dump(folder/'objects.json', answer)
        return answer


class PushModel(Jev):
    def decide(self, state):
        self.rec.check_budget()
        i = len(self.rec.decisions)
        if i >= self.rec.cfg['max_jev_decisions']:
            raise RuntimeError('Model decision budget')
        folder = self.rec.folder / f'decision-{i:04d}'
        folder.mkdir()
        questions = {axis: dict(type='choice',
            instructions=f'Use only translation_axes[{axis}]. Choose direction '
                'from current toward goal; hold within axis tolerance. In prepare '
                'hold position. Program determines step distance.',
            criteria=dict(negative='Decrease world coordinate',
                          hold='No displacement', positive='Increase world coordinate'))
            for axis in 'xyz'}
        for axis in ('rx', 'ry', 'rz'):
            if abs(state['required_rotation_world_rad'][axis]) >= .03:
                questions[axis] = dict(type='choice', instructions=
                    f'Sign of required_rotation_world_rad[{axis}] toward target pose.',
                    criteria=dict(negative='Negative world rotation',
                                  hold='No rotation', positive='Positive world rotation'))
        questions['gripper'] = dict(type='choice', instructions=
            'Choose open, close or keep based on the current contact-push contract. '
            'The source remains supported by the table, so never claim a grasp. '
            'For an observation-only reobserve, the motor choice is not executed.',
            criteria=dict(open='Command open', close='Command close',
                          keep='Preserve previous command'))
        questions['transition'] = dict(type='choice', instructions=
            'Choose advance only when current contract_satisfied is true; '
            'otherwise continue or, when offered, reobserve. A correct direction '
            'does not imply the controller actually moved: compare commanded and '
            'observed displacement in tracking_axes and recent_actions. Commanded '
            'delta is per native step; observed displacement is over the whole '
            'block, so do not divide them as if they shared a time interval. '
            'If blocked, reobserve can '
            'refresh the visible source and contact waypoint once, without motor '
            'action or phase change. Stop if continued control is not sensible. '
            'When selecting reobserve or stop, no XYZ, rotation or gripper '
            'motor choice from this response is executed. '
            'For continue_phase or advance, your selected motor action executes '
            'before any phase edge.',
            criteria=dict(continue_phase='Remain in current operation',
                          **({'advance': 'Enter next operation'}
                              if state['allowed_transitions']['advance'] else {}),
                          **({'reobserve': 'Refresh visible geometry without moving or changing phase'}
                              if state['allowed_transitions']['reobserve'] else {}),
                          stop='End incomplete'))
        request = dict(model=self.api.cfg['model'], state=state, questions=questions)
        dump(folder/'request.json', request)
        row = dict(decision_id=f'decision-{i:04d}', stage=state['operation'],
                   observation=state, prompt_version='contact-push-v2',
                   request_sha256=hashlib.sha256(json.dumps(request,
                       sort_keys=True).encode()).hexdigest())
        self.rec.decisions.append(row)
        started = time.monotonic()
        try:
            raw = self.api.post('/systemone', request)
            dump(folder/'response.json', raw)
            answers = raw['answers']
            if set(answers) != set(questions):
                raise ValueError('Missing/unrequested push decision')
            for name, question in questions.items():
                answer = answers[name]
                probabilities = answer['probabilities']
                values = [answer['confidence'], *probabilities.values()]
                if (answer['choice'] not in question['criteria'] or
                        set(probabilities) != set(question['criteria']) or
                        not all(isinstance(x, (int, float)) and
                            math.isfinite(x) and 0 <= x <= 1 for x in values) or
                        abs(sum(probabilities.values())-1) > .02):
                    raise ValueError('Invalid model choice/probabilities')
            sign = dict(negative=-1, hold=0, positive=1)
            signs = [sign[answers[a]['choice']] for a in 'xyz']
            row.update(answers=answers, signs=signs,
                rotation_signs=[sign[answers[a]['choice']] if a in answers else 0
                    for a in ('rx', 'ry', 'rz')],
                gripper=answers['gripper']['choice'],
                transition=answers['transition']['choice'], model=raw.get('model'),
                metrics=direction_metrics(
                    [state['translation_axes'][a]['current_coordinate_m'] for a in 'xyz'],
                    [state['translation_axes'][a]['goal_coordinate_m'] for a in 'xyz'],
                    signs, state['axis_hold_tolerance_mm']/1000))
        except Exception as exc:
            row['error'] = str(exc)
            self.rec.errors.append(dict(type=type(exc).__name__))
            raise
        finally:
            row['request_seconds'] = time.monotonic()-started
            dump(folder/'decision.json', row)
            append(self.rec.folder/'decisions.jsonl', row)
        return row


def run_push(env, obs, rec, task, depth_fn, k_fn, t_fn):
    visible_goal_plate = bool(rec.cfg.get('goal_plate_push'))
    if visible_goal_plate:
        from libero_goal_plate_vision import GoalPlateVision
        vision = GoalPlateVision(rec)
    else:
        vision = PushVision(rec)
    model = PushModel(rec)
    own = gripper_geometry(env, obs)
    dump(rec.folder/'own-gripper.json', own)
    ticks = grip_ticks = stage_decisions = 0
    stage = 'prepare'
    gripper = -1
    finished = False
    error_message = None
    termination_reason = None
    observed_after = None
    goal = None
    stalls = 0
    reobservations = 0
    history = []

    def views():
        return {c: dict(rgb=np.ascontiguousarray(obs[c+'_image'][::-1]),
            depth=depth_fn(env.sim, obs[c+'_depth'])[::-1].squeeze(),
            K=k_fn(env.sim, c, rec.cfg['camera_size'], rec.cfg['camera_size']),
            T=t_fn(env.sim, c)) for c in ('agentview', 'robot0_eye_in_hand')}

    def build_plan(source, rear_extent, observed_views, own, standoff=.010):
        kwargs = dict(current_orientation=Rotation.from_quat(
            obs['robot0_eef_quat']).as_matrix(),
            observed_rear_extent_m=rear_extent, rear_standoff_m=standoff,
            preserve_downward=not visible_goal_plate,
            contact_mode='top_surface' if visible_goal_plate else 'rear_edge')
        candidate = contact_push_plan(source, goal, own, **kwargs)
        return candidate

    try:
        public_task = ' '.join(task.language.split()[:-2]) if task.language.split()[-2:-1] == ['light'] else task.language
        v = views()
        identity = vision.locate(v, public_task, 'initial')
        ob = identity['source']
        source = vision.measure(v[ob['camera']], ob['bbox'], ob['label'], 'initial-source')
        goal_uv = np.asarray(identity['goal_uv'], float)
        xyz = world_cloud(v['agentview'])
        u, w = np.round(goal_uv).astype(int)
        patch = xyz[w-4:w+5, u-4:u+5]
        if len(patch) == 0 or not np.isfinite(patch).all():
            raise RuntimeError('Goal tabletop RGB-D unavailable')
        goal = np.median(patch.reshape(-1, 3), axis=0)
        unit_push = goal[:2]-source['center'][:2]
        unit_push /= max(float(np.linalg.norm(unit_push)), 1e-9)
        rear_extent = visible_rear_extent(v[ob['camera']],
            np.load(source['visible_mask_path']), source, unit_push)
        plan = build_plan(source, rear_extent, v, own)
        direction = plan['direction']
        orientation = plan['orientation']
        approach, lower, contact = (plan[k] for k in ('approach','lower','contact'))
        push_end, retreat = plan['push_end'],plan['retreat']
        dump(rec.folder/'push-geometry.json', dict(public_task=public_task,
            source=source, target_uv=goal_uv, visible_goal_world_m=goal,
            **plan, provenance=(
                'Public language + visible red-rim plate/stove/table RGB-D + own gripper mesh'
                if visible_goal_plate else 'Public language + GPT-6 image point/box + '
                'visible RGB-D/SAM + own gripper mesh') +
                '; no BDDL geometry or predicate'))
        while True:
            rec.check_budget()
            if ticks >= 550 or stage_decisions >= 65:
                raise RuntimeError('Push native/stage decision budget')
            if visible_goal_plate and stalls >= 6 and reobservations >= 1:
                raise RuntimeError('Visible plate push halted after six blocked blocks following reobserve')
            current = obs['robot0_eef_pos'].copy()
            target = dict(prepare=current, approach=approach, lower=lower,
                          push=push_end, retreat=retreat)[stage]
            error = target-current
            tolerance = .008 if stage == 'push' else .006
            arrived = bool(np.max(np.abs(error)) < tolerance)
            rot = np.zeros(3) if stage in ('prepare', 'retreat') else Rotation.from_matrix(
                orientation @ Rotation.from_quat(obs['robot0_eef_quat']).as_matrix().T).as_rotvec()
            oriented = bool(np.max(np.abs(rot)) < .03)
            if stage == 'push' and arrived and observed_after is None:
                v = views()
                later = vision.locate(v, public_task, 'after_push',
                    previous=dict(source=ob, destination=identity['destination']))
                later_ob = later['source']
                observed_after = vision.measure(v[later_ob['camera']],
                    later_ob['bbox'], later_ob['label'], 'after-push-source')
                dump(rec.folder/'after-push-geometry.json', observed_after)
            visible_error = None if observed_after is None else float(np.linalg.norm(
                observed_after['center'][:2]-goal[:2]))
            if stage == 'push' and arrived and visible_error is not None and visible_error >= .045:
                raise RuntimeError(f'Observed push missed visible target by {visible_error*1000:.1f}mm')
            complete = (grip_ticks >= 18 and gripper == 1) if stage == 'prepare' else arrived and oriented
            if stage == 'push':
                complete = bool(complete and visible_error is not None and visible_error < .045)
            if stage == 'retreat':
                complete = arrived
            aperture = float(np.sum(abs(obs['robot0_gripper_qpos']))*1000)
            next_stage = 'finish_attempt' if stage == 'retreat' else PHASES[PHASES.index(stage)+1]
            contracts = dict(prepare='Stay still; close gripper for at least 18 native ticks to make a compact pusher.',
                approach=('Move to a high-clearance hover above the visible plate centre.'
                    if visible_goal_plate else
                    'Move to high-clearance hover behind visible source, keeping the selected downward pusher pose.'),
                lower=('Lower the own fingertip onto the visible plate top for a supported slide; keep the plate on the table.'
                    if visible_goal_plate else
                    'Lower behind object to own-finger tabletop clearance, without lifting source.'),
                push=('Translate the supported contact across the table toward the visible goal; advance only after fresh RGB-D confirms the plate centre within 45mm of goal.'
                    if visible_goal_plate else
                    'Move pusher along table toward the visible goal. Advance only after fresh RGB-D confirms object centre within 45mm of goal.'),
                retreat='Raise pusher after the observed push; advance to end attempt.')
            state = dict(task=public_task, operation=stage, next_operation=next_stage,
                operation_contract=contracts[stage],
                translation_axes={a: dict(current_coordinate_m=float(current[i]),
                    goal_coordinate_m=float(target[i]),
                    goal_minus_current_mm=round(float(error[i])*1000, 2),
                    relation='within_tolerance' if abs(error[i])<.002 else
                        'goal_coordinate_larger' if error[i]>0 else 'goal_coordinate_smaller')
                    for i, a in enumerate('xyz')},
                axis_hold_tolerance_mm=2., required_rotation_world_rad=dict(
                    zip(('rx','ry','rz'), rot.tolist())),
                gripper=dict(aperture_mm=aperture,
                    last_command='open' if gripper==-1 else 'close',
                    command_ticks=grip_ticks, needed_for_contract='close'),
                completion_evidence=dict(position_arrived=arrived,
                    orientation_arrived=oriented, visible_object_goal_error_mm=
                    None if visible_error is None else round(visible_error*1000, 2),
                    contract_satisfied=bool(complete)),
                allowed_transitions=dict(continue_phase=True, advance=bool(complete),
                    reobserve=bool(stalls >= 2 and reobservations == 0 and
                        stage in ('approach', 'lower') and vision.calls < 2),
                    stop=True),
                visible_geometry=dict(source_initial_xy_m=source['center'][:2],
                    goal_xy_m=goal[:2], push_direction_xy=direction,
                    contact_mode=plan['contact_mode'],
                    source_observed_after_xy_m=None if observed_after is None else observed_after['center'][:2]),
                blocked_action_count=stalls, reobserve_count=reobservations,
                tracking_axes={a: dict(
                    commanded_delta_mm_per_native_step=
                        history[-1]['commanded_delta_mm_per_native_step'][i],
                    observed_block_displacement_mm=
                        history[-1]['actual_block_displacement_mm'][i],
                    block_native_ticks=history[-1]['block_native_ticks'],
                    motion_detected=abs(history[-1]['actual_block_displacement_mm'][i]) >= .5)
                    for i, a in enumerate('xyz')} if history else None,
                recent_actions=history[-3:],
                phase_decisions=stage_decisions, information_sources=
                'Public instruction, rendered RGB-D/calibration, own robot pose/finger mesh, executed history only.')
            state = json.loads(json.dumps(state, default=serial, allow_nan=False))
            decision = model.decide(state)
            stage_decisions += 1
            if decision['transition'] == 'stop':
                termination_reason = 'model_stopped_unsatisfied'
                rec.event(dict(kind='model_stop', stage=stage,
                    decision_id=decision['decision_id'],
                    blocked_action_count=stalls))
                break
            if decision['transition'] == 'advance' and not complete:
                raise RuntimeError('Model advanced before visible contract satisfied')
            if decision['transition'] == 'reobserve':
                if not state['allowed_transitions']['reobserve']:
                    raise RuntimeError('Invalid model reobserve choice')
                v = views()
                refreshed = vision.locate(v, public_task, 'reobserve',
                    previous=dict(source=ob, destination=identity['destination']))
                ob = refreshed['source']
                source = vision.measure(v[ob['camera']], ob['bbox'], ob['label'],
                    'reobserve-source')
                unit_push = goal[:2]-source['center'][:2]
                unit_push /= max(float(np.linalg.norm(unit_push)), 1e-9)
                rear_extent = visible_rear_extent(v[ob['camera']],
                    np.load(source['visible_mask_path']), source, unit_push)
                own = gripper_geometry(env, obs)
                plan = build_plan(source, rear_extent, v, own)
                direction, orientation = plan['direction'], plan['orientation']
                approach, lower, contact = (plan[k] for k in ('approach','lower','contact'))
                push_end, retreat = plan['push_end'], plan['retreat']
                reobservations += 1
                stalls = 0
                rec.event(dict(kind='reobserve', decision_id=decision['decision_id'],
                    stage=stage, old_target=target,
                    new_target=approach if stage == 'approach' else lower,
                    semantic_calls=vision.calls))
                dump(rec.folder/'push-geometry-reobserve.json', dict(
                    public_task=public_task, source=source, target_uv=goal_uv,
                    visible_goal_world_m=goal, **plan,
                    provenance=('Fresh visible red-rim plate RGB-D and own robot geometry; '
                        if visible_goal_plate else
                        'Fresh visible RGB-D/SAM and own robot geometry; ') +
                        'original visible destination retained'))
                continue
            newgripper = gripper if decision['gripper']=='keep' else -1 if decision['gripper']=='open' else 1
            if newgripper != gripper:
                grip_ticks = 0
            gripper = newgripper
            cap = .012 if stage in ('lower','push') else .02
            delta = np.asarray(decision['signs'])*np.minimum(cap, .5*np.abs(error))
            rotations = np.asarray(decision['rotation_signs'])*np.minimum(.10, .5*np.abs(rot))
            block = 6 if stage == 'prepare' or np.max(np.abs(error))>.06 else 3
            if ticks+block > 550:
                raise RuntimeError('Native block budget')
            before = current.copy()
            for _ in range(block):
                obs, _, _, _ = env.step(np.r_[delta/.05, rotations/.5, gripper])
                ticks += 1
                grip_ticks += 1
            after = obs['robot0_eef_pos'].copy()
            progress = float(np.linalg.norm(error)-np.linalg.norm(target-after))
            stalls = stalls+1 if stage != 'prepare' and np.linalg.norm(error)>.015 and progress<.0003 else 0
            history.append(dict(stage=stage, progress_mm=round(progress*1000, 2),
                commanded_delta_mm_per_native_step=np.round(delta*1000, 2).tolist(),
                actual_block_displacement_mm=np.round((after-before)*1000, 2).tolist(),
                block_native_ticks=block))
            rec.branch(dict(stage=stage, decision_id=decision['decision_id'],
                before=before, after=after, delta=delta, rotation=rotations,
                selected_gripper=decision['gripper'], executed_gripper=gripper,
                selected_transition=decision['transition'], native_steps=ticks,
                block_native_ticks=block, progress_mm=progress*1000,
                blocked_action_count=stalls))
            for camera, view in views().items():
                cv2.imwrite(str(rec.folder/f'{ticks:04d}-{stage}-{camera}.png'),
                    cv2.cvtColor(view['rgb'], cv2.COLOR_RGB2BGR))
            if decision['transition'] == 'advance':
                rec.event(dict(kind='phase_transition', from_stage=stage,
                    to_stage=next_stage, decision_id=decision['decision_id'],
                    selected_transition='advance'))
                if stage == 'retreat':
                    finished = True
                    termination_reason = 'model_finished_attempt'
                    break
                if stage == 'prepare':
                    # The pusher geometry is recalculated from its *actual* closed
                    # finger mesh before setting the approach/contact line.
                    own = gripper_geometry(env, obs)
                    dump(rec.folder/'own-gripper-after-close.json', own)
                    plan = build_plan(source, rear_extent, v, own)
                    direction, orientation = plan['direction'], plan['orientation']
                    approach, lower, contact = (plan[k] for k in ('approach','lower','contact'))
                    push_end, retreat = plan['push_end'],plan['retreat']
                    dump(rec.folder/'push-geometry-after-close.json', dict(
                        public_task=public_task, source=source, target_uv=goal_uv,
                        visible_goal_world_m=goal, **plan,
                        provenance='Fresh own closed-finger geometry + initial visible SAM/RGB-D; no scene truth'))
                stage = next_stage
                stage_decisions = 0
                stalls = 0
    except Exception as exc:
        error_message = str(exc)
        termination_reason = 'execution_error'
        rec.event(dict(kind='stop', reason=error_message,
                       error_type=type(exc).__name__))
    finally:
        success = bool(env.check_success())
        dump(rec.folder/'result.json', dict(success=success,
            program_finished=finished, error=error_message,
            termination_reason=termination_reason,
            native_steps=ticks, jev_calls=len(rec.decisions),
            semantic_calls=vision.calls, stage=stage,
            visible_object_goal_error_m=None if observed_after is None or goal is None else
                float(np.linalg.norm(observed_after['center'][:2]-goal[:2])),
            ownership=('Jev: XYZ/rotation/gripper/phase; fixed visible Goal plate method'
                if visible_goal_plate else
                'gpt-6-sol/xhigh via ChatGPT Codex: XYZ/rotation/gripper/phase'),
            model_backend='jev-1.13' if visible_goal_plate else
                'gpt-6-sol/xhigh via ChatGPT Codex'))
        rec.finish('success' if success else 'failed')
        model.close()
        vision.close()

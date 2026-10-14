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


def visible_rim_slide_plan(source, goal, own, robot_reference, current_orientation):
    """Plan table-height rim contact from observed bounds and own geometry."""
    center = np.asarray(source['center'], float)
    extent = np.asarray(source['high'])-np.asarray(source['low'])
    toward_robot = np.asarray(robot_reference)[:2]-center[:2]
    axis = int(np.argmax(np.abs(toward_robot)))
    close_axis = np.eye(3)[axis]
    long_axis = np.array([close_axis[1], -close_axis[0], 0.])
    rotation = np.column_stack([long_axis, -close_axis, [0., 0., -1.]])
    if np.linalg.det(rotation) < 0:
        rotation[:, 1] *= -1
    other = rotation @ Rotation.from_euler('z', np.pi).as_matrix()
    rotation = min((rotation, other), key=lambda candidate: np.linalg.norm(
        Rotation.from_matrix(candidate@current_orientation.T).as_rotvec()))
    box = envelope(own, rotation)
    side = 1. if toward_robot[axis] >= 0 else -1.
    rim = center[:2]+side*close_axis[:2]*extent[axis]/2
    xy = rim-np.asarray(box['pad_center_offset'])[:2]
    z = max(float(source['high'][2])-.004-float(box['pad_low_offset'][2]),
            float(goal[2])+.002-float(box['finger_low_z_offset']))
    contact = np.r_[xy, z]
    direction = (goal[:2]-center[:2])/max(np.linalg.norm(goal[:2]-center[:2]), 1e-9)
    end = contact.copy()
    end[:2] += goal[:2]-center[:2]
    return dict(orientation=rotation, direction=direction,
        approach=contact+np.array([0., 0., .14]), lower=contact,
        contact=contact, push_end=end, retreat=end+np.array([0., 0., .12]),
        contact_mode='robot_near_visible_rim_slide', observed_rear_extent_m=0.,
        own_finger_table_clearance_mm=(z+box['finger_low_z_offset']-goal[2])*1000,
        rim_axis_world=close_axis, rim_side=side,
        rim_source='visible plate bounds and initial own TCP reference',
        own_envelope=box)


def visible_finger_plate_contact(own, tcp, quaternion, source, history,
                                 position_error, rotation_error, direction):
    """Offer a bounded push trial from public plate bounds and own finger motion.

    A close mesh/bounding-box distance alone is ambiguous. Require repeated
    commanded motion toward the planned contact with little actual movement;
    later RGB-D verification still decides whether the plate moved.
    """
    fingers = (np.asarray(own['finger_vertices_tool']) @
               Rotation.from_quat(quaternion).as_matrix().T + np.asarray(tcp))
    low, high = (np.asarray(source[k], float) for k in ('low', 'high'))
    gap = np.linalg.norm(np.maximum(np.maximum(low-fingers, fingers-high), 0.), axis=1)
    near = bool(np.any(gap < .005))
    height_overlap = bool(np.min(fingers[:, 2]) <= high[2]+.003 and
                          np.max(fingers[:, 2]) >= low[2]-.003)
    rearward = -np.asarray(direction[:2], float)
    recent = [row for row in history if row['stage'] == 'lower'][-3:]
    blocked_rearward = bool(len(recent) == 3 and all(
        np.dot(row['commanded_delta_mm_per_native_step'][:2], rearward) > .5 and
        abs(np.dot(row['actual_block_displacement_mm'][:2], rearward)) < .3
        for row in recent))
    lateral_residual = (rearward[0]*position_error[1] -
                        rearward[1]*position_error[0])
    bounded_pose = bool(.008 <= np.dot(position_error[:2], rearward) <= .016 and
                        abs(lateral_residual) < .010 and
                        abs(position_error[2]) < .005 and
                        np.max(np.abs(rotation_error)) < .12)
    return dict(visible_finger_to_plate_bbox_mm=round(float(np.min(gap))*1000, 2),
                finger_plate_height_overlap=height_overlap,
                commanded_rearward_blocked_three_times=blocked_rearward,
                bounded_own_pose=bounded_pose,
                contact_trial_available=bool(near and height_overlap and
                                             blocked_rearward and bounded_pose),
                source='public RGB-D plate bounds + own finger mesh/pose + executed action history')


def world_cloud(view):
    vv, uu = np.indices(view['depth'].shape)
    d, k, t = view['depth'], view['K'], view['T']
    cam = np.stack(((uu-k[0, 2])*d/k[0, 0],
                    (vv-k[1, 2])*d/k[1, 1], d), axis=-1)
    return cam @ t[:3, :3].T + t[:3, 3]


def visible_rear_extent(view, mask, source, direction, quantile=.05):
    """Robust trailing support of any segmented tabletop object along a push."""
    if mask.shape != view['depth'].shape:
        raise RuntimeError('Visible source mask/depth shape mismatch')
    good = mask & np.isfinite(view['depth']) & (view['depth'] > .02) & (view['depth'] < 3.)
    if int(good.sum()) < 80:
        raise RuntimeError('Insufficient visible source pixels for push extent')
    points = world_cloud(view)[good]
    projection = (points[:, :2]-source['center'][:2]) @ direction
    rear = -float(np.quantile(projection, quantile))
    if not .005 < rear < .20:
        raise RuntimeError('Visible rear push extent outside supported range')
    return rear


def contact_push_plan(source, goal, own, current_orientation=None,
                      observed_rear_extent_m=None, rear_standoff_m=.010,
                      preserve_downward=True, lateral_contact_offset_m=0.,
                      contact_mode='rear_edge', top_contact_rear_fraction=0.,
                      allow_short_push=False, overshoot_extra_m=0.,
                      hover_clearance_m=.20, yaw_flip=False):
    """Derive a pushing line only from RGB-D bounds and the robot's own mesh."""
    travel = goal[:2]-source['center'][:2]
    distance = float(np.linalg.norm(travel))
    if not (.008 if allow_short_push else .04) < distance < .55:
        raise RuntimeError('Visible push distance outside supported range')
    direction = travel/distance
    if abs(goal[2]-source['low'][2]) > .065:
        raise RuntimeError('Proposed goal not on visible source support level')
    xaxis = np.r_[direction, 0.]
    yaxis = np.r_[direction[::-1]*np.array([1., -1.]), 0.]
    proposed = np.column_stack((xaxis, yaxis, [0., 0., -1.]))
    if np.linalg.det(proposed) < 0:
        proposed[:, 1] *= -1
    if yaw_flip:
        proposed[:, :2] *= -1
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
    if not 0. <= top_contact_rear_fraction <= .8:
        raise ValueError('Top contact rear fraction outside visible support')
    if not 0. <= overshoot_extra_m <= .020:
        raise ValueError('Extra supported push outside bounded range')
    if not .12 <= hover_clearance_m <= .20:
        raise ValueError('Hover clearance outside bounded range')
    lateral_axis = np.array([direction[1], -direction[0]])
    if contact_mode == 'rear_edge':
        contact_xy = (source['center'][:2] - direction*(rear_extent+leading+.004)
                      + lateral_axis*lateral_contact_offset_m)
        contact_z = goal[2]+.004-own_box['finger_low_z_offset']
    elif contact_mode == 'top_surface':
        if lateral_contact_offset_m:
            raise ValueError('Top contact cannot use a lateral offset')
        contact_xy = (np.asarray(source['center'][:2], float) -
                      direction*rear_extent*top_contact_rear_fraction)
        surface_z = float(source['contact_surface_world_z_m'])
        if not source['low'][2]-.003 < surface_z < source['high'][2]+.003:
            raise RuntimeError('Visible inner surface inconsistent with plate bounds')
        # Use the inner surface actually contacted by the finger, not the
        # higher coloured rim. Three millimetres of commanded penetration
        # counters OSC residual tracking error; it is not hidden scene state.
        contact_z = surface_z-.003-own_box['finger_low_z_offset']
    else:
        raise ValueError('Unknown visible contact mode')
    finger_low_world = contact_z+own_box['finger_low_z_offset']
    finger_high_world = contact_z+finger_high
    if (contact_mode == 'rear_edge' and
            (finger_low_world > source['high'][2]-.001 or
             finger_high_world < source['low'][2]+.001)):
        raise RuntimeError('Own finger envelope misses observed object height')
    hover_z = max(contact_z+hover_clearance_m,
                  source['high'][2]+hover_clearance_m)
    standoff = rear_standoff_m if contact_mode == 'rear_edge' else 0.
    approach = np.r_[contact_xy-direction*standoff, hover_z]
    lower = np.r_[contact_xy-direction*standoff, contact_z]
    contact = np.r_[contact_xy, contact_z]
    # Top contact leaves the plate trailing the fingertip; keep the pusher
    # moving until the visible plate can approach the visible stove-front goal.
    # A short goal residual does not shorten the travel needed to reach the
    # plate from a rear top contact. Keep the same visible-extent sweep.
    overshoot = (.060 if contact_mode == 'top_surface' else .025) + overshoot_extra_m
    push_end = np.r_[contact_xy+direction*(distance+overshoot), contact_z]
    retreat = push_end+np.array([0., 0., .10])
    return dict(orientation=orientation,
        orientation_source='preserved downward robot pose' if preserve else
            'alternate downward yaw from visible push direction' if yaw_flip else
            'downward pose derived from visible push direction',
        direction=direction,
        observed_rear_extent_m=rear_extent,
        rear_standoff_m=rear_standoff_m,
        contact_mode=contact_mode,
        top_contact_rear_fraction=top_contact_rear_fraction,
        planned_overshoot_m=overshoot,
        hover_clearance_m=hover_clearance_m,
        short_visible_correction=bool(allow_short_push and distance < .04),
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
            'Follow gripper.needed_for_contract; closure is only a contact trial, not holding proof. Keep the source supported by the table. '
            'For an observation-only reobserve, the motor choice is not executed.',
            criteria=dict(open='Command open', close='Command close',
                          keep='Preserve previous command'))
        residual_correction = bool(state.get('residual_correction_available'))
        questions['transition'] = dict(type='choice', instructions=
            'Choose advance only when current contract_satisfied is true; '
            'otherwise continue or, when offered, reobserve. A correct direction '
            'does not imply the controller actually moved: compare commanded and '
            'observed displacement in tracking_axes and recent_actions. Commanded '
            'delta is per native step; observed displacement is over the whole '
            'block, so do not divide them as if they shared a time interval. '
            'Stop if continued control is not sensible. '
            'When selecting reobserve or stop, no XYZ, rotation or gripper '
            'motor choice from this response is executed. '
            'For continue_phase or advance, your selected motor action executes '
            'before any phase edge.' + (
                ' At retreat with a measured residual and '
                'residual_correction_available=true, choose reobserve to start '
                'one bounded correction segment using the fresh visible plate; '
                'this selection has no motor action.' if residual_correction else
                ' If blocked at approach/lower, reobserve can refresh the '
                'visible source and contact waypoint once without moving or '
                'changing phase.'),
            criteria=dict(continue_phase='Remain in current operation',
                          **({'advance': 'Enter next operation'}
                              if state['allowed_transitions']['advance'] else {}),
                          **({'reobserve': ('Start one visible residual correction segment'
                               if residual_correction else
                               'Refresh visible geometry without moving or changing phase')}
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
            raw = self.post_with_connect_retry('/systemone', request)
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
        from libero_goal_plate_vision import (GoalPlateVision,
            visible_plate_in_front_of_stove, visible_plate_rim_progress)
        vision = GoalPlateVision(rec)
    else:
        vision = PushVision(rec)
    model = PushModel(rec)
    own = gripper_geometry(env, obs)
    robot_reference = np.asarray(obs['robot0_eef_pos']).copy()
    dump(rec.folder/'own-gripper.json', own)
    ticks = grip_ticks = stage_decisions = 0
    stage = 'prepare'
    gripper = -1
    finished = False
    error_message = None
    termination_reason = None
    observed_after = None
    observed_after_identity = None
    goal = None
    ultimate_goal = None
    ultimate_goal_uv = None
    segment = 1
    coast_enabled = bool(visible_goal_plate and rec.cfg.get('plate_coast_gate'))
    coast_previous = None
    coast_gate_reached = False
    coast_evidence = None
    # The official episode horizon is 600 native steps.  The rollout already
    # spent 10 steps opening the gripper before entering this supervisor.
    # Leave a ten-step margin so a correction cannot overrun the simulator.
    max_native_ticks = 580 if visible_goal_plate else 550
    stalls = 0
    reobservations = 0
    history = []
    clearance_orientation_target = None

    def views():
        return {c: dict(rgb=np.ascontiguousarray(obs[c+'_image'][::-1]),
            depth=depth_fn(env.sim, obs[c+'_depth'])[::-1].squeeze(),
            K=k_fn(env.sim, c, rec.cfg['camera_size'], rec.cfg['camera_size']),
            T=t_fn(env.sim, c)) for c in ('agentview', 'robot0_eye_in_hand')}

    def build_plan(source, rear_extent, observed_views, own, standoff=.010):
        if visible_goal_plate and segment >= 2 and rec.cfg.get('plate_second_rim_slide'):
            return visible_rim_slide_plan(source, goal, own, robot_reference, Rotation.from_quat(obs['robot0_eef_quat']).as_matrix())
        rim_second = bool(visible_goal_plate and segment >= 2 and
                          rec.cfg.get('plate_second_rim_contact'))
        kwargs = dict(current_orientation=Rotation.from_quat(
            obs['robot0_eef_quat']).as_matrix(),
            yaw_flip=bool(rim_second and rec.cfg.get('plate_second_yaw_flip')),
            observed_rear_extent_m=rear_extent,
            rear_standoff_m=((.004 if rec.cfg.get('plate_rear_compact') else .015) if rim_second and rec.cfg.get('plate_second_rear_insert') else
                            0. if rim_second else standoff),
            hover_clearance_m=.14 if rim_second else .20,
            preserve_downward=(not visible_goal_plate or
                visible_goal_plate and segment == 1 and rec.cfg.get('plate_first_preserve_downward') or
                rim_second and rec.cfg.get('plate_second_preserve_downward')),
            # Both plate segments concern the same visible, broad support
            # surface.  Trailing top contact maintained the second segment
            # on init2; init3's centred first contact lost the plate early.
            # Use the same support-relative contact rule in both segments.
            # Crosswise top contact can slide over the plate. The optional
            # second contact starts behind the visible rim using own fingers.
            contact_mode=('rear_edge' if rim_second else
                          'top_surface' if visible_goal_plate else 'rear_edge'),
            allow_short_push=bool(visible_goal_plate and segment >= 2),
            overshoot_extra_m=(
                rec.cfg.get('plate_final_overshoot_mm', 0)/1000.
                if visible_goal_plate and segment >= 2 else 0.),
            # A visually blocked direct corridor needs a lateral first leg.
            # The second crosswise push in that route can slip from a far-rear
            # plate contact; use the same more central supported contact as
            # its first leg. Direct routes keep the previously successful .7.
            top_contact_rear_fraction=(
                .5 if visible_goal_plate and (
                    segment == 1 or vision.goal['elevated_corridor_pixels'] >= 80)
                else .7 if visible_goal_plate else 0.))
        candidate = contact_push_plan(source, goal, own, **kwargs)
        if rim_second and rec.cfg.get('plate_second_rear_insert'):
            candidate['rear_extent_source'] = 'visible SAM mask/RGB-D 1st percentile'
        return candidate

    try:
        public_task = ' '.join(task.language.split()[:-2]) if task.language.split()[-2:-1] == ['light'] else task.language
        v = views()
        identity = vision.locate(v, public_task, 'initial')
        initial_plate_u = float(vision.last_uv[0]) if coast_enabled else None
        ob = identity['source']
        source = vision.measure(v[ob['camera']], ob['bbox'], ob['label'], 'initial-source')
        goal_uv = np.asarray(identity['goal_uv'], float)
        xyz = world_cloud(v['agentview'])
        u, w = np.round(goal_uv).astype(int)
        patch = xyz[w-4:w+5, u-4:u+5]
        if len(patch) == 0 or not np.isfinite(patch).all():
            raise RuntimeError('Goal tabletop RGB-D unavailable')
        goal = np.median(patch.reshape(-1, 3), axis=0)
        ultimate_goal = goal.copy()
        ultimate_goal_uv = goal_uv.copy()
        if visible_goal_plate:
            goal_uv = np.asarray(vision.stage_goal['goal_uv'], float)
            goal = np.asarray(vision.stage_goal['goal_world_m'], float)
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
            if ticks >= max_native_ticks or stage_decisions >= 65:
                raise RuntimeError('Push native/stage decision budget')
            if visible_goal_plate and stalls >= 6 and reobservations >= 1:
                raise RuntimeError('Visible plate push halted after six blocked blocks following reobserve')
            current = obs['robot0_eef_pos'].copy()
            rear_insert = bool(visible_goal_plate and segment >= 2 and
                               rec.cfg.get('plate_second_rear_insert'))
            rim_slide = bool(visible_goal_plate and segment >= 2 and rec.cfg.get('plate_second_rim_slide'))
            slide_open = bool(rim_slide and stage in ('prepare','approach','lower','release','retreat'))
            orient_clearance = bool(rear_insert and rec.cfg.get('plate_second_orient_clearance'))
            if orient_clearance and stage == 'orient_clearance' and clearance_orientation_target is None:
                clearance_orientation_target = current.copy()
            target = dict(orient_clearance=(clearance_orientation_target if clearance_orientation_target is not None else current), prepare=current, grasp=current, release=current, approach=approach, lower=lower,
                          side_contact=contact, push=push_end, retreat=retreat)[stage]
            stage_orientation = orientation
            rear_path = None
            if rear_insert and stage in ('approach', 'lower', 'side_contact'):
                current_rotation = Rotation.from_quat(obs['robot0_eef_quat']).as_matrix()
                rear_fingers = np.asarray(own['finger_vertices_tool']) @ current_rotation.T + current
                rear_boundary = float(np.dot(source['center'][:2], direction)-plan['observed_rear_extent_m'])
                leading_projection = float(np.max(rear_fingers[:, :2] @ direction))
                rear_clearance = rear_boundary-leading_projection
                rear_low_z, rear_high_z = float(rear_fingers[:, 2].min()), float(rear_fingers[:, 2].max())
                low_ready = bool(max(float(goal[2])+.002, float(source['low'][2])-.004) <=
                                 rear_low_z <= float(source['high'][2])-.001)
                leg = 'rear_hover' if stage == 'approach' else 'lower_outside' if stage == 'lower' else 'insert_sideways'
                if stage == 'lower' and rear_clearance < .003:
                    target = lower.copy()
                    target[2] = max(float(current[2]), float(source['high'][2])+.03-(rear_low_z-current[2]))
                    leg = 'restore_rear_clearance'
                rear_path = dict(leg=leg, visible_rear_boundary_projection_m=rear_boundary,
                    own_leading_projection_m=leading_projection, rear_clearance_mm=round(rear_clearance*1000, 2),
                    own_finger_low_world_z_m=rear_low_z, own_finger_high_world_z_m=rear_high_z,
                    side_contact_height_ready=low_ready,
                    source='public RGB-D trailing support + own finger mesh/pose')
            planar_contact = None
            if (visible_goal_plate and segment == 2 and stage == 'push' and
                    rec.cfg.get('plate_second_planar_contact')):
                current_orientation = Rotation.from_quat(obs['robot0_eef_quat']).as_matrix()
                fingers = np.asarray(own['finger_vertices_tool']) @ current_orientation.T + current
                finger_low = float(np.min(fingers[:, 2]))
                finger_high = float(np.max(fingers[:, 2]))
                compatible = bool(float(goal[2])+.001 < finger_low <= float(source['high'][2])+.003 and
                    finger_high >= float(source['low'][2])-.003 and
                    abs(float(current[2]-lower[2])) < .025)
                planar_contact = dict(own_finger_low_world_z_m=finger_low,
                    own_finger_high_world_z_m=finger_high,
                    public_plate_z_interval_m=[float(source['low'][2]), float(source['high'][2])],
                    public_support_world_z_m=float(goal[2]),
                    relieved_own_pose=compatible,
                    source='public RGB-D plate/support heights + own finger mesh/pose')
                if compatible:
                    target = target.copy()
                    target[2] = current[2]
                    stage_orientation = current_orientation
            if coast_enabled and segment == 1 and stage == 'push':
                live_rgb = np.ascontiguousarray(obs['agentview_image'][::-1])
                measured = visible_plate_rim_progress(live_rgb)
                if measured is not None:
                    u = measured['u_px']
                    speed = (None if coast_previous is None or
                             ticks <= coast_previous[0] else
                             (u-coast_previous[1])/(ticks-coast_previous[0]))
                    coast_previous = (ticks, u)
                    direction_u = np.sign(float(ultimate_goal_uv[0])-initial_plate_u)
                    along_speed = (None if speed is None else
                                   float(np.clip(direction_u*speed, 0., 4.)))
                    predicted_u = (None if along_speed is None else
                                   u+direction_u*20.*along_speed)
                    span = abs(float(ultimate_goal_uv[0])-initial_plate_u)
                    if (not coast_gate_reached and predicted_u is not None and
                            direction_u*(u-initial_plate_u) >= .5*span and
                            direction_u*(predicted_u-initial_plate_u) >= span):
                        coast_gate_reached = True
                        rec.event(dict(kind='visible_plate_coast_gate',
                            native_tick=ticks, measured_u_px=u,
                            speed_px_per_native_step=along_speed,
                            predicted_settle_u_px=predicted_u,
                            final_public_goal_u_px=float(ultimate_goal_uv[0]),
                            source='public agentview red plate rim and executed tick history'))
                    coast_evidence = dict(**measured,
                        speed_toward_goal_px_per_native_step=along_speed,
                        predicted_settle_u_px=predicted_u,
                        final_public_goal_u_px=float(ultimate_goal_uv[0]),
                        lookahead_native_steps=20,
                        visual_stage_reached=coast_gate_reached)
                if coast_gate_reached:
                    # Stop commanding the old overshoot endpoint. Jev still
                    # chooses hold signs and whether to advance the phase.
                    target = current.copy()
            error = target-current
            second_lower = visible_goal_plate and segment == 2 and stage == 'lower'
            second_rim_hover = bool(visible_goal_plate and segment == 2 and
                stage == 'approach' and rec.cfg.get('plate_second_rim_hover_gate'))
            # The rear-edge staging pose is a clearance waypoint, not the
            # contact endpoint. At this pose the controller's near-contact
            # residual can persist for >100 ticks; the measured finger envelope
            # still overlaps the visible plate within these bounds.
            # Under supported contact, OSC can stall within the last 10–14 mm
            # of the planned TCP sweep.  The object itself is independently
            # checked from fresh RGB-D after lifting the pusher.
            tolerance = (.010 if second_rim_hover else
                         .014 if visible_goal_plate and stage == 'push' else
                         .009 if second_lower else .008 if stage == 'push' else .006)
            arrived = bool(np.max(np.abs(error)) < tolerance)
            rot = np.zeros(3) if stage in ('prepare', 'retreat') else Rotation.from_matrix(
                stage_orientation @ Rotation.from_quat(obs['robot0_eef_quat']).as_matrix().T).as_rotvec()
            oriented = bool(np.max(np.abs(rot)) <
                (.06 if second_rim_hover else .07 if second_lower else .03))
            contact_trial = (visible_finger_plate_contact(
                own, current, obs['robot0_eef_quat'], source, history,
                error, rot, direction)
                if second_lower and not rear_insert and rec.cfg.get('plate_second_visible_contact_gate')
                and plan['contact_mode'] == 'rear_edge' else None)
            verification_stage = ('retreat' if visible_goal_plate else 'push')
            if stage == verification_stage and arrived and observed_after is None:
                v = views()
                later = vision.locate(v, public_task, 'after_push',
                    previous=dict(source=ob, destination=identity['destination']),
                    expected_uv=goal_uv if visible_goal_plate else None)
                later_ob = later['source']
                observed_after_identity = later_ob
                observed_after = vision.measure(v[later_ob['camera']],
                    later_ob['bbox'], later_ob['label'], 'after-push-source')
                dump(rec.folder/(f'after-push-geometry-segment-{segment}.json'
                    if visible_goal_plate else 'after-push-geometry.json'),
                    observed_after)
            visible_error = None if observed_after is None else float(np.linalg.norm(
                observed_after['center'][:2]-goal[:2]))
            front_relation = (visible_plate_in_front_of_stove(
                observed_after_identity['bbox'], vision.stove['bbox'],
                observed_after['low'][2],
                vision.goal['visible_support_world_z_m'])
                if visible_goal_plate and segment >= 2 and
                   observed_after is not None else None)
            if front_relation is not None and rec.cfg.get('plate_front_margin_px', 0):
                margin = int(rec.cfg['plate_front_margin_px'])
                front_relation = dict(front_relation,
                    base_passed=front_relation['passed'],
                    required_front_margin_px=margin,
                    passed=bool(front_relation['passed'] and
                        front_relation['visible_front_gap_px'] <=
                        front_relation['allowed_front_gap_px'][1]-margin))
            front_relation_passed = bool(front_relation and front_relation['passed'])
            goal_tolerance = .020 if visible_goal_plate and segment >= 2 else .045
            residual_correction_available = bool(visible_goal_plate and
                stage == 'retreat' and arrived and segment == 2 and
                visible_error is not None and not front_relation_passed and
                goal_tolerance <= visible_error <= .12 and
                vision.calls < 5 and max_native_ticks-ticks >= 120)
            if (stage == verification_stage and arrived and
                    visible_error is not None and visible_error >= goal_tolerance and
                    not front_relation_passed and not residual_correction_available):
                raise RuntimeError(f'Observed push missed visible target by {visible_error*1000:.1f}mm')
            complete = (grip_ticks >= 18 and gripper == 1) if stage == 'prepare' else arrived and oriented
            slide_evidence = None
            if rim_slide:
                if stage == 'prepare': complete = bool(grip_ticks >= 18 and gripper == -1)
                if stage == 'grasp': complete = bool(grip_ticks >= 18 and gripper == 1)
                if stage == 'release': complete = bool(grip_ticks >= 18 and gripper == -1 and float(np.sum(abs(obs['robot0_gripper_qpos'])))*1000 >= 65)
                if stage == 'lower':
                    measured_rotation = Rotation.from_quat(obs['robot0_eef_quat']).as_matrix()
                    vertices = np.asarray(own['pad_vertices_tool']) @ measured_rotation.T + current
                    low_pad, high_pad = np.quantile(vertices, [.05,.95],axis=0)
                    overlap = np.maximum(0.,np.minimum(high_pad,source['high'])-np.maximum(low_pad,source['low']))
                    gap = float(max(low_pad[2]-source['high'][2],source['low'][2]-high_pad[2],0.))
                    finger_low = float((np.asarray(own['finger_vertices_tool']) @ measured_rotation.T + current)[:,2].min())
                    contact_ready = bool(gripper == -1 and np.all(overlap[:2] >= .003) and gap <= .002 and finger_low >= float(goal[2])+.001 and np.max(np.abs(error)) < .015 and np.max(np.abs(rot)) < .08)
                    complete = contact_ready
                    slide_evidence = dict(closure_trial_ready=contact_ready,visible_pad_overlap_mm=(overlap*1000).tolist(),vertical_gap_mm=gap*1000,own_finger_table_clearance_mm=(finger_low-goal[2])*1000,source='public plate RGB-D bounds and own open finger mesh; not holding proof')
            if orient_clearance and stage == 'orient_clearance':
                complete = bool(arrived and np.max(np.abs(rot)) < .06 and gripper == 1)
            if rear_insert and stage == 'approach':
                complete = bool(gripper == 1 and rear_clearance >= .003 and
                    rear_low_z >= float(source['high'][2])+.10 and
                    np.max(np.abs(error[:2])) < .025 and np.max(np.abs(rot)) < (.12 if rec.cfg.get('plate_rear_compact') else .06))
            if rear_insert and stage == 'lower':
                complete = bool(gripper == 1 and rear_clearance >= .003 and low_ready and
                    np.max(np.abs(error[:2])) < .025 and np.max(np.abs(rot)) < .12)
            if rear_insert and stage == 'side_contact':
                bounds_low, bounds_high = np.asarray(source['low']), np.asarray(source['high'])
                gap = np.linalg.norm(np.maximum(np.maximum(bounds_low-rear_fingers, rear_fingers-bounds_high), 0.), axis=1)
                recent = [row for row in history if row['stage'] == 'side_contact'][-3:]
                blocked_forward = bool(len(recent) == 3 and all(
                    np.dot(row['commanded_delta_mm_per_native_step'][:2], direction) > .5 and
                    abs(np.dot(row['actual_block_displacement_mm'][:2], direction)) < .3 for row in recent))
                trial = bool(float(np.min(gap)) < .005 and low_ready and blocked_forward and
                    np.max(np.abs(error)) < .015 and np.max(np.abs(rot)) < .12)
                rear_path.update(forward_blocked_three_times=blocked_forward,
                    own_finger_to_visible_bbox_mm=round(float(np.min(gap))*1000, 2), side_contact_trial=trial)
                complete = bool(gripper == 1 and ((arrived and oriented) or trial))
            if contact_trial is not None and contact_trial['contact_trial_available']:
                # This is a permitted trial of pushing, not proof of contact
                # or task success. Jev still chooses the phase edge and fresh
                # RGB-D after the push must verify plate movement.
                complete = True
            if stage == 'push' and not visible_goal_plate:
                complete = bool(complete and visible_error is not None and visible_error < goal_tolerance)
            if coast_enabled and segment == 1 and stage == 'push':
                complete = bool((coast_gate_reached or arrived) and oriented)
            if stage == 'retreat':
                complete = (bool(arrived and visible_error is not None and
                                 (visible_error < goal_tolerance or
                                  front_relation_passed)) if visible_goal_plate
                            else arrived)
            support_height_passed = (bool(float(goal[2])-.005 <= float(observed_after['low'][2]) <= float(goal[2])+.025) if rim_slide and observed_after is not None else None)
            if rim_slide and stage == 'retreat':
                complete = bool(complete and support_height_passed)
            aperture = float(np.sum(abs(obs['robot0_gripper_qpos']))*1000)
            phase_order = (('prepare', 'orient_clearance', 'approach', 'lower', 'side_contact', 'push', 'retreat') if orient_clearance else ('prepare', 'approach', 'lower', 'side_contact', 'push', 'retreat')) if rear_insert else PHASES
            if rim_slide:
                phase_order = ('prepare','approach','lower','grasp','push','release','retreat')
            next_stage = (('prepare' if rec.cfg.get('plate_second_rim_slide') else 'orient_clearance' if rec.cfg.get('plate_second_orient_clearance') else 'approach') if stage == 'retreat' and visible_goal_plate
                          and segment == 1 else 'finish_attempt' if stage == 'retreat'
                          else phase_order[phase_order.index(stage)+1])
            contracts = dict(prepare='Stay still; close gripper for at least 18 native ticks to make a compact pusher.',
                approach=('Move to a high-clearance hover above the visible plate centre.'
                    if visible_goal_plate else
                    'Move to high-clearance hover behind visible source, keeping the selected downward pusher pose.'),
                lower=('Lower the own fingertip onto the visible plate top for a supported slide; keep the plate on the table.'
                    if visible_goal_plate else
                    'Lower behind object to own-finger tabletop clearance, without lifting source.'),
                push=('Translate the supported contact laterally across the table to the visible staging waypoint; advance after reaching the sweep endpoint so the pusher can lift before RGB-D verification.'
                    if visible_goal_plate and segment == 1 else
                    'Keep supported top contact while pushing the observed plate toward the visible stove-front goal; advance after reaching the sweep endpoint so the pusher can lift before RGB-D verification.'
                    if visible_goal_plate else
                    'Move pusher along table toward the visible goal. Advance only after fresh RGB-D confirms object centre within 45mm of goal.'),
                retreat=('Raise the pusher to reveal the plate; advance only after fresh RGB-D measures its centre within the supplied visible goal tolerance (45 mm staging, 20 mm final).'
                    if visible_goal_plate else
                    'Raise pusher after the observed push; advance to end attempt.'))
            if visible_goal_plate and segment >= 2:
                contracts['retreat'] = (
                    'Raise the pusher to reveal the plate. Advance if fresh '
                    'public RGB-D confirms the plate centre near the target '
                    'patch or the plate visibly rests on the tabletop in '
                    'front of and horizontally aligned with the stove. '
                    'The latter uses visible bounding boxes and the plate '
                    'radius, not the evaluator.')
            if contact_trial is not None:
                contracts['lower'] = (
                    'Lower the own fingertip to the visible plate rim. '
                    'Advance when position and orientation arrive, or when '
                    'completion_evidence.visible_contact_trial.contact_trial_available '
                    'is true: own fingers overlap the public plate bounds, '
                    'three commanded rearward blocks barely move, and own '
                    'pose is bounded. This permits a push trial only; later '
                    'fresh RGB-D must show the plate moved.')
            if coast_enabled and segment == 1:
                contracts['push'] = (
                    'Move the supported pusher toward the visible staging lane. '
                    'When completion_evidence.plate_coast_prediction.'
                    'visual_stage_reached is true, the public red rim trajectory '
                    'predicts the plate will settle near the final stove-front '
                    'image column; choose advance now to lift the pusher. '
                    'The old fixed sweep endpoint remains a fallback if the '
                    'public rim is occluded. This is not official success.')
            if residual_correction_available:
                contracts['retreat'] = (
                    'Fresh public RGB-D measures a remaining plate-to-goal '
                    f'distance above {goal_tolerance*1000:.0f} mm. Reobserve is offered for one '
                    'additional correction push from the measured plate pose; '
                    'choose it now if correction is sensible. No motor action '
                    'executes for reobserve. This is not official success.')
            if planar_contact is not None:
                contracts['push'] += (
                    ' When completion_evidence.visible_planar_contact.relieved_own_pose '
                    'is true, the own finger height overlaps the public plate height '
                    'above visible support and within 25 mm of planned contact. '
                    'The supplied Z and wrist goals then preserve the current own pose; '
                    'select planar directions toward the supplied endpoint. This is a '
                    'contact-compatible trial only; later fresh RGB-D verifies object movement.')
            if rim_slide:
                contracts.update(prepare='Hold TCP and open for 18 native ticks before approaching the visible robot-near rim.',approach='Reach the clearance hover above the visible robot-near rim with open fingers; align the supplied downward pose.',lower='Lower open fingers toward the visible rim. Advance only on the supplied bounded pad-overlap and positive table-clearance closure-trial gate. This is not grasp proof.',grasp='Hold TCP and close for 18 native ticks for one rim-assisted slide trial. Closure does not prove holding. No source lifting goal is supplied.',push='Keep closed and translate the rim contact along the table toward the visible stove-front goal. Keep the supplied table-height Z; advance after the endpoint. Final fresh RGB-D after open withdrawal must verify the plate.',release='Hold TCP and open for 18 native ticks with aperture at least 65 mm, then advance to upward withdrawal.',retreat='Withdraw with open fingers to reveal the plate; advance only if fresh public RGB-D verifies the final visible stove-front relation or goal tolerance.')
            if orient_clearance:
                contracts['orient_clearance'] = 'Hold the measured clearance TCP location and align the downward pusher orientation before lateral approach. Advance only after own position arrival and rotation residual below 0.06 rad with closed fingers. No source contact is claimed.'
            if rear_insert:
                contracts['approach'] = 'Move to the rear hover. Advance only when own fingers are at least 3 mm behind the public trailing boundary and 100 mm above the visible plate, with bounded own pose.'
                contracts['lower'] = 'Lower outside the visible plate. If rear clearance is lost, follow the temporary raised goal to restore it. Advance only with rear clearance >=3 mm and own finger bottom inside the measured side-contact height band.'
                contracts['side_contact'] = 'Keep closed and insert horizontally from the verified rear staging pose toward the visible rim. Advance at supplied pose arrival or after a bounded forward-blocked side-contact trial; this is not task success.'
                contracts['push'] = 'Keep closed and push from the verified rear-side entry toward the supplied visible stove-front endpoint. The own contact height and wrist goal were latched at the verified rear staging pose. Later fresh RGB-D must verify plate movement.'
            state = dict(task=public_task, operation=stage, next_operation=next_stage,
                segment_index=segment, segment_count=(3 if segment == 3 else 2)
                    if visible_goal_plate else 1,
                residual_correction_available=residual_correction_available,
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
                    command_ticks=grip_ticks, needed_for_contract='open' if slide_open else 'close'),
                completion_evidence=dict(position_arrived=arrived,
                    orientation_arrived=oriented, visible_object_goal_error_mm=
                    None if visible_error is None else round(visible_error*1000, 2),
                    visible_goal_tolerance_mm=round(goal_tolerance*1000, 1),
                    visible_front_relation=front_relation,
                    plate_coast_prediction=(coast_evidence if coast_enabled and
                        segment == 1 and stage == 'push' else None),
                    visible_contact_trial=contact_trial,
                    contract_satisfied=bool(complete)),
                allowed_transitions=dict(continue_phase=True, advance=bool(complete),
                    reobserve=bool(residual_correction_available or
                        (stalls >= 2 and reobservations == 0 and
                         stage in ('approach', 'lower') and vision.calls < 2)),
                    stop=True),
                visible_geometry=dict(source_initial_xy_m=source['center'][:2],
                    goal_xy_m=goal[:2], push_direction_xy=direction,
                    contact_mode=plan['contact_mode'],
                    final_goal_xy_m=None if ultimate_goal is None else ultimate_goal[:2],
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
            if rim_slide:
                state['completion_evidence']['visible_source_on_support'] = support_height_passed
            if slide_evidence is not None:
                state['completion_evidence']['rim_slide_contact'] = slide_evidence
            if planar_contact is not None:
                state['completion_evidence']['visible_planar_contact'] = planar_contact
            if rear_path is not None:
                state['completion_evidence']['rear_insert_path'] = rear_path
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
                if residual_correction_available:
                    # Reuse the just-measured public RGB-D plate, so the
                    # correction costs no additional semantic/model call.
                    v = views()
                    ob = observed_after_identity
                    source = observed_after
                    goal, goal_uv = ultimate_goal.copy(), ultimate_goal_uv.copy()
                    unit_push = goal[:2]-source['center'][:2]
                    unit_push /= max(float(np.linalg.norm(unit_push)), 1e-9)
                    rear_extent = visible_rear_extent(v[ob['camera']],
                        np.load(source['visible_mask_path']), source, unit_push,
                        quantile=.01 if rec.cfg.get('plate_second_rear_insert') and segment >= 2 else .05)
                    own = gripper_geometry(env, obs)
                    segment = 3
                    plan = build_plan(source, rear_extent, v, own)
                    direction, orientation = plan['direction'], plan['orientation']
                    approach, lower, contact = (plan[k] for k in
                        ('approach', 'lower', 'contact'))
                    push_end, retreat = plan['push_end'], plan['retreat']
                    dump(rec.folder/'push-geometry-segment-3.json', dict(
                        public_task=public_task, source=source,
                        target_uv=goal_uv, visible_goal_world_m=goal, **plan,
                        provenance='Fresh visible plate RGB-D and own gripper; Jev chose correction'))
                    rec.event(dict(kind='visible_residual_correction',
                        decision_id=decision['decision_id'],
                        visible_error_mm=round(visible_error*1000, 2),
                        from_stage='retreat', to_stage='approach',
                        segment_index=segment))
                    observed_after = observed_after_identity = None
                    stage = 'approach'
                    stage_decisions = stalls = 0
                    reobservations += 1
                    continue
                v = views()
                refreshed = vision.locate(v, public_task, 'reobserve',
                    previous=dict(source=ob, destination=identity['destination']))
                ob = refreshed['source']
                source = vision.measure(v[ob['camera']], ob['bbox'], ob['label'],
                    'reobserve-source')
                unit_push = goal[:2]-source['center'][:2]
                unit_push /= max(float(np.linalg.norm(unit_push)), 1e-9)
                rear_extent = visible_rear_extent(v[ob['camera']],
                    np.load(source['visible_mask_path']), source, unit_push,
                    quantile=.01 if rec.cfg.get('plate_second_rear_insert') and segment >= 2 else .05)
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
            cap = .012 if stage in ('lower', 'side_contact', 'push') else .02
            delta = np.asarray(decision['signs'])*np.minimum(cap, .5*np.abs(error))
            if (stage == 'push' and segment >= 2 and visible_goal_plate and
                    rec.cfg.get('plate_second_line_step')):
                # Independent axis clipping turned a 15-degree push into a
                # 45-degree command. Share one planar gain, preserving every
                # Jev sign and hold while keeping each axis below the cap.
                planar_gain = min(.5, cap/max(float(np.max(np.abs(error[:2]))), 1e-9))
                delta[:2] = np.asarray(decision['signs'][:2])*planar_gain*np.abs(error[:2])
            rotations = np.asarray(decision['rotation_signs'])*np.minimum(.10, .5*np.abs(rot))
            block = 6 if stage in ('prepare','grasp','release') or np.max(np.abs(error))>.06 else 3
            if rear_insert and decision['transition'] == 'advance' and stage in ('approach', 'lower', 'side_contact'):
                block = 1
            if ticks+block > max_native_ticks:
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
                if rear_insert and stage == 'lower':
                    contact, push_end, retreat = contact.copy(), push_end.copy(), retreat.copy()
                    contact[2] = push_end[2] = float(obs['robot0_eef_pos'][2])
                    retreat[2] = contact[2]+.10
                    orientation = Rotation.from_quat(obs['robot0_eef_quat']).as_matrix()
                    rec.event(dict(kind='verified_rear_pose_latch', native_tick=ticks,
                        own_contact_z_m=float(contact[2]), own_orientation_world=orientation,
                        source='own pose after Jev advance from visible rear-clearance/height gate'))
                rec.event(dict(kind='phase_transition', from_stage=stage,
                    to_stage=next_stage, decision_id=decision['decision_id'],
                    selected_transition='advance', segment_index=segment))
                if stage == 'retreat':
                    if visible_goal_plate and segment == 1:
                        v = views()
                        refreshed = vision.locate(v, public_task, 'reobserve',
                            previous=dict(source=ob, destination=identity['destination']))
                        ob = refreshed['source']
                        source = vision.measure(v[ob['camera']], ob['bbox'],
                            ob['label'], 'second-segment-source')
                        goal, goal_uv = ultimate_goal.copy(), ultimate_goal_uv.copy()
                        unit_push = goal[:2]-source['center'][:2]
                        unit_push /= max(float(np.linalg.norm(unit_push)), 1e-9)
                        rear_extent = visible_rear_extent(v[ob['camera']],
                            np.load(source['visible_mask_path']), source, unit_push,
                            quantile=.01 if rec.cfg.get('plate_second_rear_insert') else .05)
                        own = gripper_geometry(env, obs)
                        segment = 2
                        plan = build_plan(source, rear_extent, v, own)
                        direction, orientation = plan['direction'], plan['orientation']
                        approach, lower, contact = (plan[k] for k in
                            ('approach', 'lower', 'contact'))
                        push_end, retreat = plan['push_end'], plan['retreat']
                        dump(rec.folder/'push-geometry-segment-2.json', dict(
                            public_task=public_task, source=source,
                            target_uv=goal_uv, visible_goal_world_m=goal, **plan,
                            provenance='Fresh visible plate RGB-D, fixed public front goal, own gripper mesh'))
                        rec.event(dict(kind='second_segment_visible_replan',
                            decision_id=decision['decision_id'],
                            goal_world_m=goal, semantic_calls=vision.calls))
                        observed_after = None
                        reobservations = 1
                        stage = next_stage
                        stage_decisions = stalls = 0
                        continue
                    finished = True
                    termination_reason = 'model_finished_attempt'
                    break
                if stage == 'prepare':
                    # The pusher geometry is recalculated from its *actual* closed
                    # finger mesh before setting the approach/contact line.
                    own = gripper_geometry(env, obs)
                    dump(rec.folder/('own-gripper-after-open.json' if rim_slide else 'own-gripper-after-close.json'), own)
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

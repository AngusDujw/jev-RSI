"""Bounded Jev drawer primitive from public RGB-D handle measurements.

No simulator object state or task predicate is read until terminal evaluation.
Goal 1202 can hand off its opened drawer to bowl placement in the same native
episode. Jev chooses motion signs, gripper commands and every phase edge.
"""
import hashlib
import json
import os
import time
from types import SimpleNamespace

import cv2
import numpy as np
from scipy.spatial.transform import Rotation

from libero_goal_drawer_vision import (visible_cabinet_front,
    visible_cabinet_near_side, visible_drawer_handles, select_public_handle,
    visible_drawer_extension)
from libero_robot_geometry import gripper_geometry, own_hand_vertices_tool
from libero_ten_task_workflows import decision_request, stages, validate_choice_set
from run_position_pilot import Jev, append, direction_metrics, dump, serial


def under_hook_waypoints(middle, lower, contact_tcp, pad_center_offset,
                         own_pad_half_height_m):
    """Enter a measured handle gap before rising to the requested rod."""
    middle_z = float(middle['center_world_m'][2])
    lower_z = float(lower['center_world_m'][2])
    separation = middle_z-lower_z
    if not .050 < separation < .110 or \
            separation/2 <= float(own_pad_half_height_m) + .005:
        raise RuntimeError('Visible middle/lower handle gap unavailable')
    pad_entry_z = (middle_z+lower_z)/2
    entry_tcp = np.asarray(contact_tcp, float).copy()
    entry_tcp[2] = pad_entry_z-float(pad_center_offset[2])
    return entry_tcp, pad_entry_z


class DrawerModel(Jev):
    def decide(self, request, stage):
        self.rec.check_budget()
        index = len(self.rec.decisions)
        if index >= self.rec.cfg['max_jev_decisions']:
            raise RuntimeError('Jev decision budget')
        folder = self.rec.folder / f'decision-{index:04d}'
        folder.mkdir()
        payload = dict(model=self.api.cfg['model'], state=request['state'],
                       questions=request['questions'])
        dump(folder/'request.json', payload)
        row = dict(decision_id=f'decision-{index:04d}', stage=stage,
                   observation=payload['state'], prompt_version=getattr(self,'prompt_version','goal-drawer-v1'),
                   request_sha256=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest())
        self.rec.decisions.append(row)
        started = time.monotonic()
        try:
            raw = self.post_with_connect_retry('/systemone', payload)
            dump(folder/'response.json', raw)
            answers = raw['answers']
            validate_choice_set(payload, answers)
            for name, answer in answers.items():
                probabilities = answer['probabilities']
                if (set(probabilities) != set(payload['questions'][name]['criteria']) or
                        not all(np.isfinite(value) and 0 <= value <= 1
                                for value in [answer['confidence'], *probabilities.values()]) or
                        abs(sum(probabilities.values())-1) > .02):
                    raise ValueError('Malformed Jev probabilities')
            signs = {'negative': -1, 'hold': 0, 'positive': 1}
            choice = [signs[answers[axis]['choice']] for axis in 'xyz']
            rotation_choice = [signs[answers[axis]['choice']] if axis in answers else 0
                               for axis in ('rx', 'ry', 'rz')]
            axes = payload['state']['translation_axes']
            row.update(answers=answers, signs=choice, rotation_signs=rotation_choice,
                       gripper=answers['gripper']['choice'],
                       transition=answers['transition']['choice'],
                       model=raw.get('model'),
                       metrics=direction_metrics(
                           [axes[axis]['current_coordinate_m'] for axis in 'xyz'],
                           [axes[axis]['goal_coordinate_m'] for axis in 'xyz'],
                           choice, .002))
        except Exception as exc:
            row['error'] = str(exc)
            self.rec.errors.append(dict(type=type(exc).__name__))
            raise
        finally:
            row['request_seconds'] = time.monotonic()-started
            dump(folder/'decision.json', row)
            append(self.rec.folder/'decisions.jsonl', row)
        return row


def run_drawer(env, obs, rec, task, depth_fn, k_fn, t_fn):
    task_id = rec.cfg['task_id']
    if rec.cfg['suite'] != 'libero_goal' or task_id not in (1098, 1202):
        raise ValueError('Drawer controller requires Goal 1098 or 1202')
    if os.environ.get('JEV_RSI_MODEL_BACKEND') == 'codex_pro':
        raise ValueError('Drawer trial requires Jev at runtime')
    model = DrawerModel(rec)
    ticks = stage_ticks = grip_ticks = 0
    gripper = -1
    history = []
    sequence = [stage for stage in stages(task_id)
                if stage['primitive'] == 'open_drawer']
    requested_level = 'top' if task_id == 1202 else 'middle'
    contact_clearance = .07 if requested_level == 'top' else .14
    phase = 0
    reobserved = False
    finished = False
    failure = None
    initial_handle = None
    image_template = None
    initial_extension_pixels = 0
    clear_target = None
    clear_start = None
    clear_source_x = None
    blocked_contact_blocks = 0
    expected = None
    side_plan_logged = False
    contact_mode = rec.cfg.get('drawer_contact_mode', 'pinch')
    high_entry = contact_mode == 'high_entry_down_hook'
    steep_entry = contact_mode == 'steep_tip_hook'
    yaw_side_entry = contact_mode == 'cabinet_side_yaw_hook'
    thin_side_entry = contact_mode == 'cabinet_side_thin_hook'
    cabinet_side_entry = contact_mode in ('cabinet_side_hook', 'cabinet_side_yaw_hook', 'cabinet_side_thin_hook')
    hook_mode = contact_mode in ('hook', 'top_hook', 'under_hook', 'side_hook', 'cabinet_side_hook', 'cabinet_side_yaw_hook', 'cabinet_side_thin_hook', 'tip_hook', 'down_hook', 'high_entry_down_hook', 'steep_tip_hook')
    initial_robot_x = float(obs['robot0_eef_pos'][0])
    initial_robot_position = np.asarray(obs['robot0_eef_pos'], float).copy()
    front_plane = None
    # The three visible handles protrude from the cabinet face toward +world Y.
    # Approach with tool Z toward -world Y to avoid a top-down collision.
    initial_orientation = Rotation.from_quat(obs['robot0_eef_quat']).as_matrix()
    side_orientation = ((Rotation.from_euler('z', 75, degrees=True).as_matrix()
                         @ Rotation.from_euler('x', -60, degrees=True).as_matrix()
                         @ initial_orientation)
                        if thin_side_entry else
                        (Rotation.from_euler('z', 90, degrees=True).as_matrix()
                         @ Rotation.from_euler('x', -30, degrees=True).as_matrix()
                         @ initial_orientation)
                        if yaw_side_entry else
                        (Rotation.from_euler('x', 105, degrees=True).as_matrix()
                         @ initial_orientation)
                        if steep_entry else
                        (Rotation.from_euler('x', 60, degrees=True).as_matrix()
                         @ initial_orientation)
                        if contact_mode in ('down_hook', 'high_entry_down_hook') else
                        (Rotation.from_euler('x', -30, degrees=True).as_matrix()
                         @ initial_orientation)
                        if contact_mode in ('under_hook', 'side_hook', 'cabinet_side_hook') else
                        initial_orientation if contact_mode == 'tip_hook' else
                        initial_orientation if contact_mode == 'top_hook' else
                        Rotation.from_euler('x', 210, degrees=True).as_matrix()
                        if hook_mode else np.array([[1., 0., 0.],
                                                    [0., 0., -1.],
                                                    [0., 1., 0.]]))
    own = gripper_geometry(env, obs)
    own_hand_tool = own_hand_vertices_tool(env, obs) if thin_side_entry else None
    if hook_mode:
        initial_rotation = Rotation.from_quat(obs['robot0_eef_quat']).as_matrix()
        finger_options = []
        for finger in ('left_fingerpad', 'right_fingerpad'):
            names = env.robots[0].gripper.important_geoms[finger]
            pad_world = np.mean([env.sim.data.geom_xpos[
                env.sim.model.geom_name2id(geom)] for geom in names], axis=0)
            pad_tool = (pad_world-np.asarray(obs['robot0_eef_pos'])) @ initial_rotation
            offset = pad_tool @ side_orientation.T
            finger_options.append((finger, names, offset, pad_tool))
        # The pad toward the cabinet (-world Y) leaves the TCP in front of the
        # visible cabinet face. Choose from measured own geometry, not a name.
        hook_finger, pad_names, pad_center_offset, chosen_pad_tool = min(
            finger_options, key=lambda item: item[2][1])
        other_pad_tool = next(row[3] for row in finger_options
                              if row[0] != hook_finger)
        own_pad_vertices = np.asarray(own['pad_vertices_tool'])
        selected_vertices = own_pad_vertices[
            np.linalg.norm(own_pad_vertices-chosen_pad_tool, axis=1) <
            np.linalg.norm(own_pad_vertices-other_pad_tool, axis=1)]
        if not len(selected_vertices):
            raise RuntimeError('Own selected fingerpad mesh unavailable')
        projected_pad = selected_vertices @ side_orientation.T
        pad_half_height = float(np.max(np.abs(
            projected_pad[:, 2]-pad_center_offset[2])))
        if contact_mode in ('top_hook', 'under_hook', 'side_hook', 'cabinet_side_hook', 'tip_hook', 'down_hook', 'high_entry_down_hook') and pad_center_offset[1] >= 0:
            raise RuntimeError('No rearward own fingerpad for hook')
        contact_offset = pad_center_offset
        tip_tool = None
        if contact_mode in ('tip_hook', 'down_hook', 'high_entry_down_hook', 'steep_tip_hook'):
            finger_vertices = np.asarray(own['finger_vertices_tool'])
            selected_finger = finger_vertices[
                np.linalg.norm(finger_vertices-chosen_pad_tool, axis=1) <
                np.linalg.norm(finger_vertices-other_pad_tool, axis=1)]
            if steep_entry:
                # At a steep wrist angle the rearward pad can switch sides.
                # Search both fingers before associating the chosen own tip
                # with its nearest own pad; no scene geometry is involved.
                selected_finger = finger_vertices
            if not len(selected_finger):
                raise RuntimeError('Own selected fingertip mesh unavailable')
            projected_finger = selected_finger @ side_orientation.T
            # The old tip mode stays within the pad-height corridor. The new
            # downward mode instead uses an own-mesh point below TCP so the
            # same visible rod/gap can be approached with a higher wrist.
            corridor = ((projected_finger[:, 2] <= -.060) &
                        (projected_finger[:, 2] >= -.090)
                        if steep_entry else
                        (projected_finger[:, 2] <= -.020) &
                        (projected_finger[:, 2] >= -.080)
                        if contact_mode in ('down_hook', 'high_entry_down_hook') else
                        (projected_finger[:, 2] >= 0) &
                        (projected_finger[:, 2] <= min(.030, 3*pad_half_height)))
            if not np.any(corridor):
                raise RuntimeError('No own fingertip in pad-height corridor')
            feasible = np.flatnonzero(corridor)
            tip_tool = selected_finger[feasible[
                np.argmin(projected_finger[feasible, 1])]]
            if steep_entry:
                hook_finger, pad_names, pad_center_offset, chosen_pad_tool = min(
                    finger_options,
                    key=lambda row: np.linalg.norm(row[3]-tip_tool))
                other_pad_tool = next(row[3] for row in finger_options
                                      if row[0] != hook_finger)
                selected_vertices = own_pad_vertices[
                    np.linalg.norm(own_pad_vertices-chosen_pad_tool, axis=1) <
                    np.linalg.norm(own_pad_vertices-other_pad_tool, axis=1)]
                projected_pad = selected_vertices @ side_orientation.T
                pad_half_height = float(np.max(np.abs(
                    projected_pad[:, 2]-pad_center_offset[2])))
            contact_offset = tip_tool @ side_orientation.T
            if contact_offset[1] >= pad_center_offset[1]-.015:
                raise RuntimeError('Own fingertip offers no deeper contact than pad')
            if contact_mode in ('down_hook', 'high_entry_down_hook', 'steep_tip_hook') and contact_offset[2] >= -.020:
                raise RuntimeError('Own fingertip does not extend below TCP')
            if steep_entry and contact_offset[1] >= -.015:
                raise RuntimeError('Own steep fingertip does not reach behind visible rod')
    else:
        pad_center_offset = np.median(
            np.asarray(own['pad_vertices_tool']) @ side_orientation.T, axis=0)
        pad_half_height = None
        contact_offset = pad_center_offset
        tip_tool = None
    dump(rec.folder/'own-pad-contact-offset.json', dict(
        side_orientation=side_orientation,
        pad_center_offset_world_m=pad_center_offset,
        contact_feature_offset_world_m=contact_offset,
        contact_feature='own fingertip mesh' if tip_tool is not None else 'own fingerpad',
        tip_vertex_tool_m=tip_tool,
        selected_pad_half_height_world_z_m=pad_half_height,
        hook_finger=hook_finger if hook_mode else None,
        source='own gripper collision pads and robot TCP only'))

    def frame():
        cam = 'agentview'
        image = np.ascontiguousarray(obs[cam+'_image'][::-1])
        depth = depth_fn(env.sim, obs[cam+'_depth'])[::-1].squeeze()
        return image, depth, k_fn(env.sim, cam, 768, 768), t_fn(env.sim, cam)

    def visible_source_x_for_clearance():
        """Locate the public source before drawer motion can occlude it."""
        from libero_generic_vision import GenericVision
        from libero_goal_local_vision import SOURCE_LABEL, pick_visible
        folder = rec.folder/'clear-source-vision'
        folder.mkdir()
        vision = GenericVision(SimpleNamespace(cfg=rec.cfg, folder=folder))
        try:
            rgb, depth, intrinsic, extrinsic = frame()
            image = folder/'agentview.png'
            cv2.imwrite(str(image), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
            label = SOURCE_LABEL[task_id]
            request = dict(image=str(image), instruction=label+' .',
                           output=str(folder/'grounding-source'))
            dump(folder/'grounding-source-request.json', request)
            vision.worker.stdin.write(json.dumps(request)+'\n')
            vision.worker.stdin.flush()
            detections = vision.receive()['objects']
            dump(folder/'grounding-source-response.json', detections)
            source = pick_visible(detections, label)
            measured = vision.measure(dict(rgb=rgb, depth=depth,
                K=intrinsic, T=extrinsic), source['bbox'], label,
                'public-source-clearance')
            dump(folder/'source-geometry.json', measured)
            return float(measured['center'][0])
        finally:
            vision.close()

    def measure_handle():
        image, depth, intrinsic, extrinsic = frame()
        measured = visible_drawer_handles(image, depth, intrinsic, extrinsic)
        chosen = select_public_handle(measured, requested_level)
        dump(rec.folder/f'handles-{ticks:04d}.json', measured)
        front = (visible_cabinet_front(image, depth, intrinsic, extrinsic,
                 chosen['center_world_m']) if hook_mode else None)
        lower = select_public_handle(measured, 'bottom')
        upper = select_public_handle(measured, 'top')
        return image, chosen, front, lower, upper

    def handle_shift():
        if image_template is None:
            return None
        image, _, _, _ = frame()
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        # The declared search window covers the visible drawer face after a
        # bounded pull. A weak or ambiguous match is unknown evidence.
        search = gray[330:620, 170:370]
        score = cv2.matchTemplate(search, image_template, cv2.TM_CCOEFF_NORMED)
        _, maximum, _, location = cv2.minMaxLoc(score)
        if maximum < .55:
            return None
        now = np.array([170+location[0], 330+location[1]], float)
        return dict(pixel_displacement=float(np.linalg.norm(now-initial_handle['template_origin'])),
                    match_score=float(maximum), current_origin=now.tolist())

    try:
        image, handle, front_plane, lower_handle, upper_handle = measure_handle()
        handle_position = np.asarray(handle['center_world_m'], float)
        x, y, width, height = handle['bbox_xywh']
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        image_template = gray[y:y+height, x:x+width].copy()
        initial_handle = dict(handle, template_origin=[x, y])
        initial_rgb, initial_depth, initial_k, initial_t = frame()
        initial_extension_pixels = visible_drawer_extension(
            initial_rgb, initial_depth, initial_k, initial_t, handle)['candidate_pixels']
        cabinet_side = (visible_cabinet_near_side(initial_rgb, initial_depth,
            initial_k, initial_t, front_plane, handle)
            if cabinet_side_entry else None)
        if cabinet_side is not None:
            dump(rec.folder/'visible-cabinet-near-side.json', cabinet_side)
        dump(rec.folder/'selected-handle.json', dict(
            initial_handle, public_requested_level=requested_level))
        if task_id == 1202 and rec.cfg.get('drawer_clear_to_source'):
            try:
                clear_source_x = visible_source_x_for_clearance()
                if not np.isfinite(clear_source_x) or \
                        abs(clear_source_x-initial_robot_x) > .35:
                    raise RuntimeError('Visible source X is outside own bounded reach')
                rec.event(dict(kind='initial_public_source_for_clearance',
                    visible_source_x_world_m=clear_source_x,
                    source='Initial unobstructed agentview RGB-D + public noun'))
            except (RuntimeError, OSError, ValueError) as exc:
                rec.event(dict(kind='clear_to_source_unavailable',
                    reason=str(exc)))
        while phase < len(sequence):
            rec.check_budget()
            if ticks >= 550 or stage_ticks >= 145:
                raise RuntimeError('Drawer native/stage budget')
            stage = sequence[phase]
            name = stage['name']
            position = np.asarray(obs['robot0_eef_pos'], float)
            contact_rod_position = handle_position.copy()
            if task_id == 1098 and contact_mode in ('top_hook', 'under_hook', 'side_hook', 'cabinet_side_hook', 'cabinet_side_yaw_hook', 'cabinet_side_thin_hook', 'tip_hook', 'down_hook', 'high_entry_down_hook', 'steep_tip_hook'):
                # The middle handle is visibly about 8 cm long. A near-side
                # contact may leave room for the arm beside the cabinet;
                # retain the same observed rod point for both hook paths.
                axis = np.asarray(handle['rod_axis_world'], float)
                toward_robot = 1. if (initial_robot_x-handle_position[0])*axis[0] >= 0 else -1.
                contact_rod_position += (toward_robot *
                    min(.024, .30*float(handle['visible_rod_length_m'])) * axis)
            if hook_mode:
                face_y = float(front_plane['point_world_m'][1])
                back_y = float(handle['rod_back_world_y_m'])
                hook_y = face_y + (.018 if thin_side_entry else .0165 if yaw_side_entry else .012)
                if not face_y + .008 < hook_y < back_y - .003:
                    raise RuntimeError('Visible finger-hook gap unavailable')
                hook_pad = np.array([contact_rod_position[0], hook_y,
                                     contact_rod_position[2]])
                contact_tcp = hook_pad - contact_offset
                if yaw_side_entry:
                    own_fingers = np.asarray(own['finger_vertices_tool']) @ side_orientation.T
                    if contact_tcp[1] + float(np.min(own_fingers[:, 1])) <= face_y + .002:
                        raise RuntimeError('Own yawed fingers do not clear visible cabinet front')
                if thin_side_entry:
                    own_envelope = np.concatenate((
                        np.asarray(own['finger_vertices_tool']), own_hand_tool)) @ side_orientation.T
                    if contact_tcp[1] + float(np.min(own_envelope[:, 1])) <= face_y + .002:
                        raise RuntimeError('Own entire hand does not clear visible cabinet front')
                pad_now = (position +
                    Rotation.from_quat(obs['robot0_eef_quat']).as_matrix() @ tip_tool
                    if tip_tool is not None else np.mean([env.sim.data.geom_xpos[
                    env.sim.model.geom_name2id(name)] for name in pad_names], axis=0))
                finger_behind = bool(face_y + .003 < pad_now[1] < back_y - .003
                    and abs(pad_now[0]-contact_rod_position[0]) < .018
                    and abs(pad_now[2]-contact_rod_position[2]) < .012)
            else:
                contact_tcp = handle_position - pad_center_offset
                finger_behind = False
                pad_now = None
            under_tcp = pad_entry_z = side_entry_tcp = None
            if contact_mode in ('under_hook', 'side_hook', 'cabinet_side_hook', 'cabinet_side_yaw_hook', 'cabinet_side_thin_hook', 'tip_hook', 'down_hook'):
                under_tcp, pad_entry_z = under_hook_waypoints(
                    handle, lower_handle, contact_tcp, contact_offset,
                    pad_half_height)
            if contact_mode == 'side_hook':
                # First pass the measured near end of the rod at the visible
                # middle/lower gap, then slide along its axis behind the rod.
                # This changes the collision path, not the final hook point.
                axis = np.asarray(handle['rod_axis_world'], float)
                toward_robot = 1. if (initial_robot_x-handle_position[0])*axis[0] >= 0 else -1.
                side_entry_tcp = under_tcp.copy()
                side_entry_tcp[:2] = (handle_position[:2] +
                    toward_robot*(.5*float(handle['visible_rod_length_m'])+.018)*axis[:2]
                    - pad_center_offset[:2])
                side_entry_tcp[1] = under_tcp[1]
            if cabinet_side_entry:
                # Bypass the measured cabinet body edge. For the thin option
                # include the own palm as well as both fingers; the prior
                # finger-only estimate missed a physical collision.
                own_side_mesh = (np.concatenate((
                    np.asarray(own['finger_vertices_tool']), own_hand_tool))
                    if thin_side_entry else np.asarray(own['finger_vertices_tool']))
                projected_fingers = own_side_mesh @ side_orientation.T
                side_entry_tcp = under_tcp.copy()
                side_entry_tcp[0] = (cabinet_side['near_side_world_x_m'] -
                    float(np.max(projected_fingers[:, 0])) - .020)
                if abs(side_entry_tcp[0]-initial_robot_x) > .35:
                    raise RuntimeError('Visible cabinet side outside bounded own reach')
                if thin_side_entry and not side_plan_logged:
                    clearance = (contact_tcp[1] +
                        float(np.min(projected_fingers[:, 1])) - face_y)
                    dump(rec.folder/'cabinet-side-plan.json', dict(
                        approach_tcp_world_m=(side_entry_tcp + [0., .14, 0.]).tolist(),
                        side_entry_tcp_world_m=side_entry_tcp,
                        under_rod_tcp_world_m=under_tcp,
                        contact_tcp_world_m=contact_tcp,
                        own_hand_and_fingers_to_visible_front_clearance_mm=round(clearance*1000,2),
                        visible_cabinet_near_side_world_x_m=cabinet_side['near_side_world_x_m'],
                        visible_front_world_y_m=face_y,
                        visible_rod_back_world_y_m=back_y,
                        source='Public camera RGB-D/links plus own gripper collision mesh and proprioception'))
                    side_plan_logged = True
            approach_tcp = side_entry_tcp if side_entry_tcp is not None else under_tcp
            if steep_entry:
                upper_z = float(upper_handle['center_world_m'][2])
                if abs(contact_tcp[2]-upper_z) > .025:
                    raise RuntimeError('Own steep-tip TCP is not in visible upper-height corridor')
                approach_tcp = contact_tcp
            high_entry_tcp = None
            high_entry_orientation = None
            if high_entry:
                # The already successful top-handle orientation supplies an
                # upper-height free-space corridor. Both heights come from
                # this episode's rendered handles, not scene object truth.
                upper_z = float(upper_handle['center_world_m'][2])
                if not .035 < upper_z-float(handle_position[2]) < .115:
                    raise RuntimeError('Visible upper/middle handle gap unavailable')
                high_entry_tcp = np.array([contact_tcp[0], contact_tcp[1], upper_z])
                high_entry_orientation = np.array([[1., 0., 0.],
                                                   [0., 0., -1.],
                                                   [0., 1., 0.]])
                approach_tcp = high_entry_tcp
            targets = {
                'approach': (approach_tcp if approach_tcp is not None else contact_tcp)
                            + [0., .14, 0. if approach_tcp is not None else contact_clearance],
                'align': (high_entry_tcp if high_entry else
                          (approach_tcp if approach_tcp is not None else contact_tcp)
                          + [0., .14, 0. if approach_tcp is not None else contact_clearance]),
                'contact': contact_tcp,
                'pull': contact_tcp + [0., .18, 0.],
            }
            target = np.asarray(targets.get(name, position), float)
            approach_leg = None
            if (thin_side_entry and rec.cfg.get('drawer_preorient') and
                    name == 'approach'):
                turn_error = Rotation.from_matrix(side_orientation @
                    Rotation.from_quat(obs['robot0_eef_quat']).as_matrix().T).as_rotvec()
                approach_leg = ('high_free_space_turn' if
                    np.max(np.abs(turn_error)) >= .06 else 'side_approach')
                if approach_leg == 'high_free_space_turn':
                    target = initial_robot_position.copy()
            if name == 'clear_opening':
                if clear_target is None:
                    clear_start = position.copy()
                    clear_target = position + np.array([0., .14, .15])
                    if clear_source_x is not None:
                        clear_target[0] = clear_source_x
                        rec.event(dict(kind='clear_to_public_source',
                            target_tcp_world_m=clear_target.tolist(),
                            source='initial public RGB-D source X + current own TCP'))
                target = clear_target.copy()
                if (rec.cfg.get('drawer_clear_to_source') and
                        (position[1] < clear_start[1]+.045 or
                         position[2] < clear_start[2]+.045)):
                    # Clear the observed drawer mouth before crossing toward
                    # the separately visible source. Both legs remain Jev XYZ.
                    target[0] = clear_start[0]
            contact_leg = 'final'
            if contact_mode == 'top_hook' and name == 'contact' and \
                    position[1] > contact_tcp[1] + .009:
                # Keep the finger above the selected visible handle while
                # moving into the cabinet/rod depth; descend after that Y leg.
                target = np.asarray(contact_tcp + [0., 0., contact_clearance], float)
                contact_leg = 'high_y_insert'
            if contact_mode == 'under_hook' and name == 'contact' and \
                    position[1] > contact_tcp[1] + .009:
                target = under_tcp.copy()
                contact_leg = 'under_y_insert'
            elif contact_mode == 'under_hook' and name == 'contact':
                contact_leg = 'under_rise'
            if contact_mode in ('tip_hook', 'down_hook') and name == 'contact' and \
                    position[1] > contact_tcp[1] + .009:
                target = under_tcp.copy()
                contact_leg = 'tip_y_insert'
            elif contact_mode in ('tip_hook', 'down_hook') and name == 'contact':
                contact_leg = 'tip_rise'
            if high_entry and name == 'contact':
                entry_turn = Rotation.from_matrix(side_orientation @
                    Rotation.from_quat(obs['robot0_eef_quat']).as_matrix().T).as_rotvec()
                if np.max(np.abs(entry_turn)) >= .06:
                    target = high_entry_tcp.copy()
                    contact_leg = 'high_entry_turn'
                else:
                    contact_leg = 'high_entry_descend'
            if contact_mode == 'side_hook' and name == 'contact':
                if position[1] > side_entry_tcp[1] + .009:
                    target = side_entry_tcp.copy()
                    contact_leg = 'side_y_insert'
                elif abs(position[0]-under_tcp[0]) > .007:
                    target = under_tcp.copy()
                    contact_leg = 'side_x_slide'
                else:
                    contact_leg = 'side_rise'
            if cabinet_side_entry and name == 'contact':
                if position[1] > side_entry_tcp[1] + .009:
                    target = side_entry_tcp.copy()
                    contact_leg = 'cabinet_side_y_insert'
                elif abs(position[0]-under_tcp[0]) > .007:
                    target = under_tcp.copy()
                    contact_leg = 'cabinet_side_x_slide'
                else:
                    contact_leg = 'cabinet_side_rise'
            orientation_goal = (high_entry_orientation if high_entry and
                name in ('approach', 'align') else side_orientation)
            rotation_error = (Rotation.from_matrix(orientation_goal @
                Rotation.from_quat(obs['robot0_eef_quat']).as_matrix().T).as_rotvec()
                if name in ('align', 'contact', 'grasp', 'pull', 'release') or
                   (name == 'approach' and (rec.cfg.get('drawer_preorient') or high_entry or steep_entry))
                else np.zeros(3))
            oriented = bool(np.max(np.abs(rotation_error)) < .06)
            aperture = float(np.sum(np.abs(obs['robot0_gripper_qpos']))*1000)
            shift = handle_shift() if name in ('pull', 'verify') else None
            extension = (visible_drawer_extension(*frame(), handle,
                baseline_pixels=initial_extension_pixels)
                if name in ('pull', 'verify') else None)
            arrived = bool(np.max(np.abs(target-position)) < .007)
            # An actual contact can block the final exact TCP pose. This only
            # offers a closure trial from permitted RGB-D and own pad geometry;
            # opening is still verified from fresh public images later.
            pad_bounds = (np.asarray(own['pad_vertices_tool']) @
                Rotation.from_quat(obs['robot0_eef_quat']).as_matrix().T + position)
            pad_low, pad_high = np.min(pad_bounds, axis=0), np.max(pad_bounds, axis=0)
            rod_gap = float(np.linalg.norm(np.maximum(
                np.maximum(pad_low-contact_rod_position,
                           contact_rod_position-pad_high), 0.)))
            blocked_contact_trial = bool(task_id == 1098 and name == 'contact' and
                contact_mode == 'pinch' and blocked_contact_blocks >= 3 and
                oriented and np.linalg.norm(target-position) < .030 and
                rod_gap < .025)
            exact_contact_pose = bool(name == 'contact' and arrived and oriented and
                contact_leg in ('final', 'under_rise', 'side_rise', 'cabinet_side_rise', 'tip_rise', 'high_entry_descend') and
                (finger_behind if hook_mode else True))
            gate = {
                'observe': True,
                'select_handle': True,
                'approach': (arrived and oriented and
                    approach_leg != 'high_free_space_turn') if
                    (high_entry or steep_entry or
                     (thin_side_entry and rec.cfg.get('drawer_preorient'))) else arrived,
                'align': arrived and oriented,
                'contact': exact_contact_pose or blocked_contact_trial,
                'grasp': (grip_ticks >= 18 and gripper == -1 and finger_behind
                          if hook_mode else grip_ticks >= 18 and gripper == 1),
                'pull': bool(extension and extension['passed']) or (
                    arrived and shift is not None and shift['pixel_displacement'] > 12),
                'release': grip_ticks >= 24 and gripper == -1 and aperture >= 65,
                'clear_opening': arrived and gripper == -1,
                'verify': bool(extension and extension['passed']) or (
                    shift is not None and shift['pixel_displacement'] > 12),
            }[name]
            evidence = dict(sources=['public_task', 'agentview_rgbd',
                                     'camera_calibration', 'robot_proprioception',
                                     'own_robot_mesh',
                                     'executed_action_history'],
                            observed_native_tick=ticks,
                            handle_world_m=handle_position.tolist(),
                            contact_rod_world_m=contact_rod_position.tolist(),
                            own_pad_center_offset_world_m=pad_center_offset.tolist(),
                            own_contact_feature_offset_world_m=contact_offset.tolist(),
                            own_contact_feature='fingertip' if tip_tool is not None else 'fingerpad',
                            hook_finger_behind_visible_rod=finger_behind if hook_mode else None,
                            hook_pad_current_world_m=pad_now.tolist() if hook_mode and tip_tool is None else None,
                            hook_tip_current_world_m=pad_now.tolist() if tip_tool is not None else None,
                            contact_path_leg=contact_leg if name == 'contact' else None,
                            approach_path_leg=approach_leg,
                            visible_cabinet_front_world_y_m=(face_y if hook_mode else None),
                            visible_rod_back_world_y_m=(back_y if hook_mode else None),
                            lower_neighbor_rod_world_z_m=(float(lower_handle['center_world_m'][2])
                                if contact_mode in ('under_hook', 'side_hook', 'cabinet_side_hook', 'cabinet_side_yaw_hook', 'cabinet_side_thin_hook', 'tip_hook', 'down_hook') else None),
                            visible_cabinet_near_side_world_x_m=(cabinet_side['near_side_world_x_m']
                                if cabinet_side is not None else None),
                            visible_upper_handle_world_z_m=(float(upper_handle['center_world_m'][2])
                                if high_entry or steep_entry else None),
                            high_entry_tcp_world_m=(high_entry_tcp.tolist() if high_entry else None),
                            under_entry_pad_world_z_m=pad_entry_z,
                            own_pad_half_height_world_z_m=pad_half_height,
                            current_tcp_world_m=position.tolist(),
                            own_pad_to_visible_rod_gap_mm=round(rod_gap*1000, 2),
                            blocked_contact_blocks=blocked_contact_blocks,
                            handle_contact_pose_reached=exact_contact_pose,
                            blocked_contact_closure_trial=blocked_contact_trial,
                            position_arrived=arrived,
                            orientation_arrived=oriented,
                            gripper_command_ticks=grip_ticks,
                            gripper_aperture_mm=aperture,
                            visible_handle_shift=shift,
                            visible_drawer_extension=extension,
                            **{stage['gate']: bool(gate)})
            request = decision_request(task_id, stage['id'], tcp_xyz_m=position,
                target_xyz_m=target, rotation_error_world_rad=rotation_error,
                gripper_aperture_mm=aperture,
                last_gripper_command='open' if gripper == -1 else 'close',
                observed_evidence=evidence, recent_actions=history,
                native_tick=ticks, public_language=task.language,
                reobserve_available=not reobserved and name in ('observe', 'select_handle', 'approach', 'align'),
                required_gripper_state=('close' if name in ('grasp', 'pull')
                    and not hook_mode else 'open'))
            request['questions']['transition']['instructions'] = (
                f'The current completion gate is completion_evidence.{stage["gate"]}. '
                'When it is true, choose advance now; the selected action '
                'executes before the stage edge. When false, choose '
                'continue_phase or stop. This is a local visible/proprioceptive '
                'stage gate, not official task success.')
            if name == 'approach' and rec.cfg.get('drawer_preorient'):
                request['state']['stage_contract'] += (
                    ' Rotate toward the supplied own-wrist target while '
                    'translating. Advance on TCP arrival; the next align '
                    'stage checks and completes any remaining orientation.')
            if thin_side_entry and rec.cfg.get('drawer_preorient') and name == 'approach':
                request['state']['stage_contract'] = (
                    'First turn the open own wrist at its high free-space pose, '
                    'then follow the supplied low cabinet-side TCP goal. '
                    'completion_evidence.approach_path_leg names the active leg. '
                    'Advance only after both low TCP arrival and own-wrist '
                    'orientation are measured; Jev decides every direction and edge.')
            if hook_mode and name == 'grasp':
                request['state']['stage_contract'] = (
                    'Keep the gripper open and place one own finger behind the '
                    f'visible {requested_level} handle rod, with RGB-D front-plane clearance. '
                    'Advance only after the measured finger hook and open-command '
                    'hold are confirmed.')
            if contact_mode == 'top_hook' and name == 'contact':
                request['state']['stage_contract'] = (
                    'First move the selected own finger to the measured '
                    'cabinet/rod depth while it remains above the selected '
                    f'visible {requested_level} handle, then lower it to that rod. '
                    'contact_path_leg names the current waypoint. Advance '
                    'only after the final pose and observed finger-behind-rod '
                    'gate are both true.')
            if contact_mode == 'under_hook' and name in ('approach', 'align'):
                request['state']['stage_contract'] = (
                    'Keep the hand outside the visible cabinet and align the '
                    'selected own finger with the measured gap between middle '
                    'and lower handle rods. The wrist is tilted toward the '
                    'open room. Advance only after own pose evidence is met.')
            if contact_mode == 'under_hook' and name == 'contact':
                request['state']['stage_contract'] = (
                    'First insert the own finger to the visible cabinet/rod '
                    'depth at the measured gap midpoint, then rise to the '
                    'middle handle rod. contact_path_leg names the current '
                    'waypoint. Advance only after the selected finger is '
                    'measured behind the middle rod at the final pose.')
            if contact_mode == 'side_hook' and name in ('approach', 'align'):
                request['state']['stage_contract'] = (
                    'Keep the hand outside the cabinet and align the own finger '
                    'with the measured middle/lower gap just beyond the near '
                    'end of the visible handle rod. Advance after own pose evidence.')
            if contact_mode == 'side_hook' and name == 'contact':
                request['state']['stage_contract'] = (
                    'Insert the selected own finger at the visible gap beside '
                    'the near rod end, slide sideways behind the rod to the '
                    'measured contact X, then rise to the middle rod. '
                    'contact_path_leg names the current waypoint. Advance only '
                    'when the finger is visibly measured behind the rod at '
                    'the final pose.')
            if cabinet_side_entry and name in ('approach', 'align'):
                request['state']['stage_contract'] = (
                    'Move the open own fingers beyond the camera-measured near '
                    'edge of the cabinet body, aligned with the visible gap '
                    'between middle and lower rods. The clearance includes '
                    'the own finger mesh; the thin option also checks the own '
                    'palm mesh. Yawed options place the own finger length '
                    'along the visible rod. Advance only on own-pose evidence.')
            if cabinet_side_entry and name == 'contact':
                request['state']['stage_contract'] = (
                    'At the cabinet body side, insert the own finger into the '
                    'camera-measured middle/lower rod gap, then slide along X '
                    'behind the middle rod, then rise to it. contact_path_leg '
                    'names the active waypoint. Advance only when the selected '
                    'own finger is behind the visible rod at the final pose.')
            if contact_mode in ('tip_hook', 'down_hook') and name in ('approach', 'align'):
                request['state']['stage_contract'] = (
                    'Keep the hand outside the cabinet and align the selected '
                    'own fingertip with the visible middle/lower handle gap. '
                    'The fingertip is from own mesh; the TCP remains in front '
                    'and, for a downward tip, above the visible rod.')
            if contact_mode in ('tip_hook', 'down_hook') and name == 'contact':
                request['state']['stage_contract'] = (
                    'Insert the selected own fingertip into the measured gap '
                    'from the front, then rise behind the middle visible rod. '
                    'Only advance after own fingertip coordinates are behind '
                    'the rod and the supplied final TCP pose is reached.')
            if high_entry and name in ('approach', 'align'):
                request['state']['stage_contract'] = (
                    'Reach the supplied open-gripper upper-handle-height '
                    'corridor. The upper and middle heights were measured '
                    'from this episode RGB-D. Align the own wrist to the '
                    'supplied orientation before the later fingertip turn. '
                    'Advance only on the supplied own-pose gate.')
            if high_entry and name == 'contact':
                request['state']['stage_contract'] = (
                    'At the measured upper-height corridor, first turn the '
                    'open own wrist so its fingertip hangs toward the middle '
                    'rod. Then follow the supplied downward TCP goal. '
                    'contact_path_leg identifies the active leg. Advance only '
                    'after the own fingertip is measured behind the visible '
                    'middle rod at the final pose.')
            if steep_entry and name in ('approach', 'align'):
                request['state']['stage_contract'] = (
                    'Outside the visible cabinet, orient the open own wrist '
                    'so its measured fingertip hangs below the TCP. Reach '
                    'the supplied upper-handle-height corridor. The pose '
                    'gate requires both translation and orientation before '
                    'the fingertip moves inward.')
            if steep_entry and name == 'contact':
                request['state']['stage_contract'] = (
                    'Keep the already oriented open wrist at the measured '
                    'upper-handle-height corridor and move the own fingertip '
                    'inward to the visible middle rod. Advance only after '
                    'the final own TCP pose and measured fingertip-behind-rod '
                    'gate are both true.')
            if task_id == 1098 and contact_mode == 'pinch' and name == 'contact':
                request['state']['stage_contract'] = (
                    'Move open fingers toward the visible rod. If the exact '
                    'pose is blocked but three executed blocks have stalled '
                    'within 30 mm of the RGB-D target and own pad envelope '
                    'is within 25 mm of the rod, you may advance to one '
                    'closure trial. This does not prove grasp; the later '
                    'visible drawer-motion gate must still pass.')
            if hook_mode and name == 'pull':
                request['state']['stage_contract'] = (
                    'Keep the gripper open; pull the measured finger hook outward '
                    'along the visible cabinet-front normal. Advance only when '
                    'fresh RGB-D shows a protruding drawer surface at the selected '
                    'handle height, or the handle visibly moves and TCP arrives.')
            if name in ('pull', 'verify'):
                request['questions']['transition']['instructions'] = (
                    'Advance when the fresh visible drawer-extension gate is true. '
                    'This is calibrated RGB-D evidence of an outward dark drawer '
                    'surface at the selected handle height, not native task success. '
                    'Otherwise use the allowed transitions from current evidence.')
            if name == 'clear_opening':
                request['state']['stage_contract'] = (
                    'Keep the gripper open and move to the supplied clearance '
                    'pose above and outward of the visibly open drawer. Advance '
                    'only after own TCP arrival; the next stage measures fresh '
                    'RGB-D with the hand out of the opening.')
                if rec.cfg.get('drawer_clear_to_source'):
                    request['state']['stage_contract'] += (
                        ' First leave the visible drawer mouth outward and up '
                        'by 45 mm while holding X; then move X toward the '
                        'initial publicly detected source during clearance.')
            decision = model.decide(request, stage['id'])
            edge = decision['transition']
            if edge == 'stop':
                raise RuntimeError('Jev elected stop')
            if edge == 'reobserve':
                image, handle, front_plane, lower_handle, upper_handle = measure_handle()
                handle_position = np.asarray(handle['center_world_m'], float)
                reobserved = True
                continue
            command = decision['gripper']
            selected_gripper = gripper if command == 'keep' else (-1 if command == 'open' else 1)
            if selected_gripper != gripper:
                grip_ticks = 0
            gripper = selected_gripper
            error = target-position
            fast_open = bool(rec.cfg.get('empty_hand_fast') and gripper == -1 and
                             name in ('approach', 'align', 'clear_opening'))
            far_open = fast_open and np.max(np.abs(error)) > .04
            fast_rotation = fast_open and np.max(np.abs(rotation_error)) > .15
            delta = np.asarray(decision['signs'])*np.minimum(
                .030 if far_open else .018,
                (.60 if far_open else .5)*np.abs(error))
            rotation_delta = np.asarray(decision['rotation_signs'])*np.minimum(
                .16 if fast_rotation else .10,
                (.60 if fast_rotation else .5)*np.abs(rotation_error))
            block = 6 if name in ('grasp', 'release') else 3
            before = position.copy()
            for _ in range(block):
                if ticks >= 550:
                    raise RuntimeError('Drawer native step budget')
                obs, _, _, _ = env.step(np.r_[delta/.05, rotation_delta/.5, gripper])
                ticks += 1
                stage_ticks += 1
                grip_ticks += 1
            after = np.asarray(obs['robot0_eef_pos'], float)
            if name == 'contact':
                blocked_contact_blocks = (blocked_contact_blocks+1 if
                    np.linalg.norm(after-before) < .0008 and
                    np.linalg.norm(target-before) > .007 else 0)
            motion = np.round((after-before)*1000, 2).tolist()
            rec.branch(dict(stage=stage['id'], decision_id=decision['decision_id'],
                            before=before, after=after, delta=delta,
                            rotation_delta=rotation_delta,
                            selected_gripper=command, executed_gripper=gripper,
                            selected_transition=edge, native_steps=ticks))
            history.append(dict(stage=name, actual_displacement_mm=motion,
                                commanded_delta_mm=np.round(delta*1000, 2).tolist(),
                                transition=edge))
            if edge == 'advance':
                current_image, _, _, _ = frame()
                cv2.imwrite(str(rec.folder/f'{ticks:04d}-{name}-agentview.jpg'),
                            cv2.cvtColor(current_image, cv2.COLOR_RGB2BGR))
                rec.event(dict(kind='phase_transition', from_stage=stage['id'],
                               to_stage=request['state']['next_stage'],
                               decision_id=decision['decision_id']))
                phase += 1
                stage_ticks = grip_ticks = 0
                blocked_contact_blocks = 0
        finished = True
    except Exception as exc:
        failure = str(exc)
        rec.event(dict(kind='stop', reason=failure))
    finally:
        handoff = bool(task_id == 1202 and finished and
                       rec.cfg.get('drawer_bowl_continuation'))
        current_image, agent_depth, agent_k, agent_t = frame()
        label = 'drawer-primitive' if handoff else 'terminal'
        cv2.imwrite(str(rec.folder/f'{ticks:04d}-{label}-agentview.jpg'),
                    cv2.cvtColor(current_image, cv2.COLOR_RGB2BGR))
        if task_id == 1202:
            np.save(rec.folder/'terminal-agentview-depth.npy', agent_depth)
            dump(rec.folder/'terminal-agentview-calibration.json',
                 dict(K=agent_k, T=agent_t))
            wrist = 'robot0_eye_in_hand'
            wrist_rgb = np.ascontiguousarray(obs[wrist+'_image'][::-1])
            wrist_depth = depth_fn(env.sim, obs[wrist+'_depth'])[::-1].squeeze()
            cv2.imwrite(str(rec.folder/f'{ticks:04d}-{label}-wrist.jpg'),
                        cv2.cvtColor(wrist_rgb, cv2.COLOR_RGB2BGR))
            np.save(rec.folder/'terminal-wrist-depth.npy', wrist_depth)
            dump(rec.folder/'terminal-wrist-calibration.json', dict(
                 K=k_fn(env.sim, wrist, 768, 768), T=t_fn(env.sim, wrist)))
        visible_shift = handle_shift()
        visible_extension = (visible_drawer_extension(
            current_image, agent_depth, agent_k, agent_t, handle,
            baseline_pixels=initial_extension_pixels)
            if initial_handle is not None else None)
        success = None if handoff else bool(env.check_success())
        result_file = ('drawer-primitive-result.json' if handoff else 'result.json')
        dump(rec.folder/result_file, dict(success=success,
            program_finished=finished and task_id == 1098,
            drawer_primitive_finished=finished,
            remaining_primitive='pick_place_bowl_in_open_drawer' if task_id == 1202 else None,
            terminal_dual_rgbd_saved=task_id == 1202,
            error=failure,
            native_steps=ticks, jev_calls=len(rec.decisions),
            stage=sequence[phase]['name'] if phase < len(sequence) else (
                'await_bowl_placement' if task_id == 1202 else 'finished'),
            visible_handle_shift=visible_shift,
            visible_drawer_extension=visible_extension,
            ownership='Jev XYZ/gripper/phase; fixed public RGB-D handle geometry'))
        if not handoff:
            rec.finish('success' if success and finished and task_id == 1098
                       else 'failed')
        model.close()
    if handoff:
        return obs, ticks

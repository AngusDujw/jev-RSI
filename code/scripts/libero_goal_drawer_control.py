"""Bounded Jev drawer attempt from public RGB-D handle measurements.

No simulator object state or task predicate is read until terminal evaluation.
The action path is a declared init0 development scaffold; Jev chooses motion
signs, gripper commands and every phase transition.
"""
import hashlib
import json
import os
import time

import cv2
import numpy as np
from scipy.spatial.transform import Rotation

from libero_goal_drawer_vision import (visible_cabinet_front,
    visible_drawer_handles, select_public_handle)
from libero_robot_geometry import gripper_geometry
from libero_ten_task_workflows import decision_request, stages, validate_choice_set
from run_position_pilot import Jev, append, direction_metrics, dump, serial


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
                   observation=payload['state'], prompt_version='goal-drawer-v1',
                   request_sha256=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest())
        self.rec.decisions.append(row)
        started = time.monotonic()
        try:
            raw = self.api.post('/systemone', payload)
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
    if rec.cfg['suite'] != 'libero_goal' or rec.cfg['task_id'] != 1098 or rec.cfg['init_index'] != 0:
        raise ValueError('Drawer controller is frozen only for Goal 1098 init0')
    if os.environ.get('JEV_RSI_MODEL_BACKEND') == 'codex_pro':
        raise ValueError('Drawer trial requires Jev at runtime')
    model = DrawerModel(rec)
    ticks = stage_ticks = grip_ticks = 0
    gripper = -1
    history = []
    sequence = stages(1098)
    phase = 0
    reobserved = False
    finished = False
    failure = None
    initial_handle = None
    image_template = None
    expected = None
    hook_mode = rec.cfg.get('drawer_contact_mode', 'pinch') == 'hook'
    front_plane = None
    # The three visible handles protrude from the cabinet face toward +world Y.
    # Approach with tool Z toward -world Y to avoid a top-down collision.
    side_orientation = (Rotation.from_euler('x', 210, degrees=True).as_matrix()
                        if hook_mode else np.array([[1., 0., 0.],
                                                    [0., 0., -1.],
                                                    [0., 1., 0.]]))
    own = gripper_geometry(env, obs)
    if hook_mode:
        pad_names = env.robots[0].gripper.important_geoms['left_fingerpad']
        pad_world = np.mean([env.sim.data.geom_xpos[
            env.sim.model.geom_name2id(name)] for name in pad_names], axis=0)
        initial_rotation = Rotation.from_quat(obs['robot0_eef_quat']).as_matrix()
        pad_tool = (pad_world-np.asarray(obs['robot0_eef_pos'])) @ initial_rotation
        pad_center_offset = pad_tool @ side_orientation.T
    else:
        pad_center_offset = np.median(
            np.asarray(own['pad_vertices_tool']) @ side_orientation.T, axis=0)
    dump(rec.folder/'own-pad-contact-offset.json', dict(
        side_orientation=side_orientation,
        pad_center_offset_world_m=pad_center_offset,
        source='own gripper collision pads and robot TCP only'))

    def frame():
        cam = 'agentview'
        image = np.ascontiguousarray(obs[cam+'_image'][::-1])
        depth = depth_fn(env.sim, obs[cam+'_depth'])[::-1].squeeze()
        return image, depth, k_fn(env.sim, cam, 768, 768), t_fn(env.sim, cam)

    def measure_handle():
        image, depth, intrinsic, extrinsic = frame()
        measured = visible_drawer_handles(image, depth, intrinsic, extrinsic)
        chosen = select_public_handle(measured, 'middle')
        dump(rec.folder/f'handles-{ticks:04d}.json', measured)
        front = (visible_cabinet_front(image, depth, intrinsic, extrinsic,
                 chosen['center_world_m']) if hook_mode else None)
        return image, chosen, front

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
        image, handle, front_plane = measure_handle()
        handle_position = np.asarray(handle['center_world_m'], float)
        x, y, width, height = handle['bbox_xywh']
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        image_template = gray[y:y+height, x:x+width].copy()
        initial_handle = dict(handle, template_origin=[x, y])
        dump(rec.folder/'selected-handle.json', initial_handle)
        while phase < len(sequence):
            rec.check_budget()
            if ticks >= 550 or stage_ticks >= 145:
                raise RuntimeError('Drawer native/stage budget')
            stage = sequence[phase]
            name = stage['name']
            position = np.asarray(obs['robot0_eef_pos'], float)
            if hook_mode:
                face_y = float(front_plane['point_world_m'][1])
                back_y = float(handle['rod_back_world_y_m'])
                hook_y = face_y + .012
                if not face_y + .008 < hook_y < back_y - .003:
                    raise RuntimeError('Visible finger-hook gap unavailable')
                hook_pad = np.array([handle_position[0], hook_y,
                                     handle_position[2]])
                contact_tcp = hook_pad - pad_center_offset
                pad_now = np.mean([env.sim.data.geom_xpos[
                    env.sim.model.geom_name2id(name)] for name in pad_names], axis=0)
                finger_behind = bool(face_y + .003 < pad_now[1] < back_y - .003
                    and abs(pad_now[0]-handle_position[0]) < .018
                    and abs(pad_now[2]-handle_position[2]) < .012)
            else:
                contact_tcp = handle_position - pad_center_offset
                finger_behind = False
                pad_now = None
            targets = {
                'approach': contact_tcp + [0., .14, .14],
                'align': contact_tcp + [0., .14, .14],
                'contact': contact_tcp,
                'pull': contact_tcp + [0., .18, 0.],
            }
            target = np.asarray(targets.get(name, position), float)
            rotation_error = (Rotation.from_matrix(side_orientation @
                Rotation.from_quat(obs['robot0_eef_quat']).as_matrix().T).as_rotvec()
                if name in ('align', 'contact', 'grasp', 'pull', 'release')
                else np.zeros(3))
            oriented = bool(np.max(np.abs(rotation_error)) < .06)
            aperture = float(np.sum(np.abs(obs['robot0_gripper_qpos']))*1000)
            shift = handle_shift() if name in ('pull', 'verify') else None
            arrived = bool(np.max(np.abs(target-position)) < .007)
            gate = {
                'observe': True,
                'select_handle': True,
                'approach': arrived,
                'align': arrived and oriented,
                'contact': arrived and oriented,
                'grasp': (grip_ticks >= 18 and gripper == -1 and finger_behind
                          if hook_mode else grip_ticks >= 18 and gripper == 1),
                'pull': arrived and shift is not None and shift['pixel_displacement'] > 12,
                'release': grip_ticks >= 24 and gripper == -1 and aperture >= 65,
                'verify': shift is not None and shift['pixel_displacement'] > 12,
            }[name]
            evidence = dict(sources=['public_task', 'agentview_rgbd',
                                     'camera_calibration', 'robot_proprioception',
                                     'own_robot_mesh',
                                     'executed_action_history'],
                            observed_native_tick=ticks,
                            handle_world_m=handle_position.tolist(),
                            own_pad_center_offset_world_m=pad_center_offset.tolist(),
                            hook_finger_behind_visible_rod=finger_behind if hook_mode else None,
                            hook_pad_current_world_m=pad_now.tolist() if hook_mode else None,
                            visible_cabinet_front_world_y_m=(face_y if hook_mode else None),
                            visible_rod_back_world_y_m=(back_y if hook_mode else None),
                            current_tcp_world_m=position.tolist(),
                            position_arrived=arrived,
                            orientation_arrived=oriented,
                            gripper_command_ticks=grip_ticks,
                            gripper_aperture_mm=aperture,
                            visible_handle_shift=shift,
                            **{stage['gate']: bool(gate)})
            request = decision_request(1098, stage['id'], tcp_xyz_m=position,
                target_xyz_m=target, rotation_error_world_rad=rotation_error,
                gripper_aperture_mm=aperture,
                last_gripper_command='open' if gripper == -1 else 'close',
                observed_evidence=evidence, recent_actions=history,
                native_tick=ticks, public_language=task.language,
                reobserve_available=not reobserved and name in ('observe', 'select_handle', 'approach', 'align'),
                required_gripper_state=('close' if name in ('grasp', 'pull')
                    and not hook_mode else 'open'))
            if hook_mode and name == 'grasp':
                request['state']['stage_contract'] = (
                    'Keep the gripper open and place one own finger behind the '
                    'visible middle handle rod, with RGB-D front-plane clearance. '
                    'Advance only after the measured finger hook and open-command '
                    'hold are confirmed.')
            if hook_mode and name == 'pull':
                request['state']['stage_contract'] = (
                    'Keep the gripper open; pull the measured finger hook outward '
                    'along the visible cabinet-front normal. Advance only when '
                    'the handle image actually moves and TCP reaches the target.')
            decision = model.decide(request, stage['id'])
            edge = decision['transition']
            if edge == 'stop':
                raise RuntimeError('Jev elected stop')
            if edge == 'reobserve':
                image, handle, front_plane = measure_handle()
                handle_position = np.asarray(handle['center_world_m'], float)
                reobserved = True
                continue
            command = decision['gripper']
            selected_gripper = gripper if command == 'keep' else (-1 if command == 'open' else 1)
            if selected_gripper != gripper:
                grip_ticks = 0
            gripper = selected_gripper
            error = target-position
            delta = np.asarray(decision['signs'])*np.minimum(.018, .5*np.abs(error))
            rotation_delta = np.asarray(decision['rotation_signs'])*np.minimum(.10, .5*np.abs(rotation_error))
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
        finished = True
    except Exception as exc:
        failure = str(exc)
        rec.event(dict(kind='stop', reason=failure))
    finally:
        current_image, _, _, _ = frame()
        cv2.imwrite(str(rec.folder/f'{ticks:04d}-terminal-agentview.jpg'),
                    cv2.cvtColor(current_image, cv2.COLOR_RGB2BGR))
        visible_shift = handle_shift()
        success = bool(env.check_success())
        dump(rec.folder/'result.json', dict(success=success,
            program_finished=finished, error=failure,
            native_steps=ticks, jev_calls=len(rec.decisions),
            stage=sequence[phase]['name'] if phase < len(sequence) else 'finished',
            visible_handle_shift=visible_shift,
            ownership='Jev XYZ/gripper/phase; fixed public RGB-D handle geometry'))
        rec.finish('success' if success else 'failed')
        model.close()

"""Stage-focused evidence for Jev; no action selection, thresholds or task truth."""
from copy import deepcopy
import json
import numpy as np


def evidence_view(evidence):
    return dict(source=evidence['source'], frame=evidence.get('frame'),
        objects=[{k: v for k, v in obj.items() if k in
                  ('id', 'category', 'position_m', 'quaternion_wxyz', 'geometry')}
                 for obj in evidence['objects']], robot=evidence['robot'])


def direction_text(vector):
    """Exact signed observed components, not a selected action or error deadband."""
    return {axis: f'{abs(float(value))*1000:.3f} mm toward world {"positive" if value > 0 else "negative" if value < 0 else "zero"} {axis}'
            for axis, value in zip('XYZ', vector)}


def focused_state(state, semantic=False):
    if state['observation_mode'] != 'oracle':
        raise ValueError('This representation ablation is explicitly oracle-only')
    stage = state['current_stage']
    evidence = evidence_view(state['evidence'])
    out = dict(task=state['task'], mode=state['mode'], observation_mode='oracle',
        current_stage=deepcopy(stage), stage_index=state['stage_index'],
        evidence=evidence, stage_observed_signals=deepcopy(state['stage_observed_signals']),
        stage_entry_evidence=evidence_view(state['stage_entry_evidence']),
        stage_decisions=state['stage_decisions'], stage_remaining_decisions=state['stage_remaining_decisions'],
        plan=dict(task=state['plan']['task'], stages=[{k: v for k, v in s.items() if k in
                  ('id', 'operation', 'arm', 'target_id', 'destination_id')} for s in state['plan']['stages']]),
        instructions='Select the next primitive for current_stage using CURRENT evidence and stage_observed_signals. '
          'Stage-entry data is only a historical baseline for effects, never the current position. '
          'World frame: Z up, X/Y horizontal. Every translation is the fixed catalog displacement, '
          'and every rotation acts around link6, so the nominal grasp point can move during rotation. '
          'Use nominal_grasp_points_m for grasp positioning. Each question is answered independently. '
          'Closing response does not prove capture: the lift stage must observe the block moving with the hand. '
          'Choose directions and stage completion yourself; no supplied field is a recommended action. '
          'Gripper opening is 0 closed / 1 open; an object may oppose complete closure.',
        input_representation='focused_semantic' if semantic else 'focused_numeric')
    # Recovery may refer to the failed stage's entry pose. Preserve that reference,
    # rather than copying an entire second plan or omitting needed recovery evidence.
    revision = state.get('plan_revision_context')
    if revision and revision.get('stage_entry_evidence'):
        out['plan_revision_context'] = dict(reason=revision['reason'], failed_stage=revision['failed_stage'],
            stage_entry_evidence=evidence_view(revision['stage_entry_evidence']))
    elif revision:
        out['plan_revision_context'] = dict(reason=revision['reason'])
    if semantic:
        signals = out['stage_observed_signals']
        relation = dict(target_relative_to_nominal_grasp=direction_text(signals['target_minus_nominal_grasp_m']),
            observed_target_motion_since_stage_entry=direction_text(signals['object_delta_since_entry_m']),
            observed_hand_motion_since_stage_entry=direction_text(signals['hand_delta_since_entry_m']))
        if 'destination_minus_object_m' in signals:
            relation['destination_relative_to_target'] = direction_text(signals['destination_minus_object_m'])
        if 'object_bottom_minus_destination_top_m' in signals:
            gap = signals['object_bottom_minus_destination_top_m']
            relation['target_bottom_relative_to_destination_top'] = (
                f'{abs(gap)*1000:.3f} mm {"above" if gap > 0 else "below" if gap < 0 else "at"} destination top; geometry only, not contact')
        axes = evidence['robot'].get('gripper_axes')
        if axes:
            arm = ('left', 'right').index(stage['arm'])
            approach = np.asarray(axes['approach_world'][arm])
            relation['gripper_approach_angle_from_world_down_degrees'] = float(np.rad2deg(np.arccos(np.clip(-approach[2], -1, 1))))
            relation['gripper_approach_direction_world'] = approach.tolist()
            relation['gripper_closing_direction_world'] = axes['closing_world'][arm]
        out['current_spatial_relations'] = relation
    return out


def focused_questions(questions):
    """Same options in literal language; all actions remain available to Jev."""
    out = deepcopy(questions)
    out['action']['instructions'] = (
        'Choose one fixed primitive that advances current_stage.completion_evidence using CURRENT '
        'stage_observed_signals and current_spatial_relations. Follow current_stage.arm and target_id. '
        'Do not repeat a past direction after the target is now on the opposite side. '
        'An approach requiring horizontal alignment and an above-object hand does not require closing '
        'the vertical gap to the object center: preserve that above-object relation while correcting '
        'horizontal alignment and any requested grasp orientation. Descent to the center belongs to '
        'the descend stage. Prioritize the explicit current objective in recovery stages. '
        'The plan outline is future work; do not execute a later operation before the current one completes.')
    for name, encoded in questions['action']['criteria'].items():
        primitive = json.loads(encoded)
        arm = primitive['arm']
        if arm is None:
            meaning = 'Hold both hands and current gripper openings.'
        elif primitive['gripper'] != 'hold':
            meaning = f'{primitive["gripper"].capitalize()} the {arm} gripper while keeping its pose.'
        else:
            rotation = any(primitive['rotation'])
            values = primitive['rotation'] if rotation else primitive['delta']
            axis = next(i for i, x in enumerate(values) if x)
            amount = values[axis]
            sign = 'positive' if amount > 0 else 'negative'
            if rotation:
                meaning = f'Rotate {arm} link6 {abs(amount)} radians about WORLD {sign} {"XYZ"[axis]} using the right-hand rule; nominal grasp center moves around link6.'
            else:
                meaning = f'Move the {arm} hand and nominal grasp center {abs(amount)*1000:g} mm toward WORLD {sign} {"XYZ"[axis]}, retaining orientation.'
            meaning += ' Retain the current gripper opening.'
        out['action']['criteria'][name] = meaning
    return out


def current_relations_state(state, full_plan=True):
    """Remove stale absolute poses; retain their effects as observed comparisons."""
    out = focused_state(state, semantic=True)
    out.pop('stage_entry_evidence')
    out.pop('plan_revision_context', None)
    out['input_representation'] = 'current_relations_full_plan' if full_plan else 'current_relations_outline'
    if full_plan:
        out['plan'] = deepcopy(state['plan'])
    stage = state['current_stage']
    arm = ('left', 'right').index(stage['arm'])
    entry = state['stage_entry_evidence']
    target_entry = next(o for o in entry['objects'] if o['id'] == stage['target_id'])
    entry_offset = np.asarray(target_entry['position_m'])-entry['robot']['nominal_grasp_points_m'][arm]
    out['stage_entry_comparisons'] = dict(horizontal_separation_at_entry_m=float(np.linalg.norm(entry_offset[:2])))
    if stage['operation'] in {'approach', 'descend'}:
        signals = out['stage_observed_signals']
        out['stage_entry_comparisons']['observed_target_motion_distance_m'] = float(np.linalg.norm(signals['object_delta_since_entry_m']))
        for key in ('hand_delta_since_entry_m', 'object_delta_since_entry_m', 'object_hand_displacement_residual_m'):
            signals.pop(key, None)
        relations = out['current_spatial_relations']
        relations.pop('observed_target_motion_since_stage_entry', None)
        relations.pop('observed_hand_motion_since_stage_entry', None)
    revision = state.get('plan_revision_context')
    if revision and revision.get('stage_entry_evidence'):
        old = revision['stage_entry_evidence']['robot']
        now = state['evidence']['robot']
        offset = np.asarray(old['nominal_grasp_points_m'][arm])-now['nominal_grasp_points_m'][arm]
        out['recovery_reference'] = dict(reason=revision['reason'], failed_stage=revision['failed_stage'],
            failed_entry_grasp_relative_to_current_grasp=direction_text(offset),
            failed_entry_quaternion_wxyz=old['eef_quaternions_wxyz'][arm],
            meaning='Historical reference only if the current recovery objective explicitly requests return to it; not the object position.')
    elif revision:
        out['recovery_reference'] = dict(reason=revision['reason'], historical_reference='not provided')
    return out


def collection_state(state):
    """Keep the current physical stage and temporal feedback, without duplicate plans."""
    out = current_relations_state(state, full_plan=False)
    out['input_representation'] = 'collection_current_stage_v1'
    if state.get('primitive_execution_contract'):
        out['primitive_execution_contract'] = deepcopy(state['primitive_execution_contract'])
    out['action_history'] = deepcopy(state.get('action_history', [])[-6:])
    from scipy.spatial.transform import Rotation
    def change(now, before):
        q, q0 = np.asarray(now['quaternion_wxyz']), np.asarray(before['quaternion_wxyz'])
        angle = (Rotation.from_quat(q[[1, 2, 3, 0]]) * Rotation.from_quat(q0[[1, 2, 3, 0]]).inv()).magnitude()
        return dict(displacement_m=(np.asarray(now['position_m'])-before['position_m']).round(6).tolist(), rotation_change_rad=float(angle))
    current = state['evidence']
    for label, reference in (('stage_entry', state['stage_entry_evidence']), ('episode_entry', state['initial_evidence'])):
        initial_objects = {o['id']: o for o in reference['objects']}
        out['object_changes_since_'+label] = {o['id']: change(o, initial_objects[o['id']]) for o in current['objects'] if o['id'] in initial_objects}
        out['robot_joint_changes_since_'+label] = (np.asarray(current['robot']['states'])-reference['robot']['states']).round(6).tolist()
    out['instructions'] += (' Only current_stage is active. The plan is a future outline. '
        'Read measured execution feedback before repeating a command: a requested displacement '
        'is not proof the hand moved. Use coarse increments while far from the endpoint, and fine '
        'increments near it; reserve decisions for completion checks. Completion is the observable '
        'endpoint, not elapsed decisions.')
    return out


def collection_task_card(state, questions):
    """A stage-bound action menu and directly named geometric observations."""
    out = collection_state(state)
    out['input_representation'] = 'collection_task_card_v2'
    stage = state['current_stage']
    arm = ('left', 'right').index(stage['arm'])
    robot = state['evidence']['robot']
    hand = np.asarray(robot['nominal_grasp_points_m'][arm])
    wrist = np.asarray(robot['eef_positions_m'][arm])
    radius = float(np.linalg.norm(hand-wrist))
    objects = {o['id']: o for o in state['evidence']['objects']}
    target = objects[stage['target_id']]
    relation = out['current_spatial_relations']
    geometry = target.get('geometry')
    if geometry:
        top = geometry['world_bbox_max_m'][2]
        relation['nominal_grasp_above_target_top_mm'] = float((hand[2]-top)*1000)
        relation['nominal_point_rotation_sweep_bottom_above_target_top_mm'] = float((wrist[2]-radius-top)*1000)
    relation['nominal_grasp_rotation_radius_mm'] = radius*1000
    relation['rotation_sweep_interpretation'] = ('Lowest possible height of the nominal grasp POINT when rotated around link6. '
        'This does not bound all robot collision geometry or prove clearance.')
    out['action_history'] = [{k:v for k,v in row.items() if k != 'ik_diagnostics'} for row in out['action_history']]
    primitives = [json.loads(v) for v in questions['action']['criteria'].values()]
    out['motion_resolution'] = dict(translation_m=min(float(np.linalg.norm(p['delta'])) for p in primitives if any(p['delta'])),
        rotation_rad=min(float(np.linalg.norm(p['rotation'])) for p in primitives if any(p['rotation'])),
        interpretation='Pose coincidence and axis alignment mean within the existing finest corresponding action resolution, not exact floating-point equality.')
    revised = focused_questions(questions)
    revised['action']['criteria'] = {k:v for k,v in revised['action']['criteria'].items()
        if k == 'hold' or k.startswith(stage['arm']+'_')}
    out['action_menu_scope'] = ('The high-level stage binds the active arm; all its original translation, '
        'rotation, gripper and hold options remain. No direction or magnitude is chosen by this filter.')
    return out, revised


def collection_explicit_questions(state, questions):
    """Restate the active criterion directly; never supply its truth value."""
    out, revised = collection_task_card(state, questions)
    out['input_representation'] = 'collection_explicit_questions_v3'
    stage = out['current_stage']
    revised['action']['instructions'] = (
        'CURRENT physical objective: '+stage['objective']+
        ' CURRENT completion criterion: '+stage['completion_evidence']+
        ' Use only this stage, not a later operation. Choose one of the listed primitives. '
        'Use measured effects in recent history; requested movement is not actual movement. '
        'Use coarse increments while far, fine increments near the endpoint. If this current '
        'criterion already holds, choose hold and advance; if blocked, request replanning.')
    revised['completion']['instructions'] = (
        'Evaluate ONLY this CURRENT stage criterion, not future stages: '+stage['completion_evidence']+
        ' Current measured geometric relations: '+json.dumps(out['current_spatial_relations'])+
        ' A criterion concerning nominal-point rotational sweep HEIGHT uses the measured sweep-bottom '
        'height relative to the target top. A positive value establishes that nominal-point height '
        'condition; it does not require executing a later orientation stage or prove full-arm collision '
        'clearance. Apply this interpretation only to a sweep-height criterion. For other criteria, '
        'evaluate their own named observations and temporal evidence. No requirement to complete the '
        'whole task or improve a relation that already satisfies the current endpoint.')
    return out, revised

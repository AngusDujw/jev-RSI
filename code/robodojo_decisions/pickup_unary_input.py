"""Single-program actor facts with explicit world effects; solver detail stays off-input."""
import os
import numpy as np
from scipy.spatial.transform import Rotation
from camera_geometry import eef_transform


def compact(data, observation):
    result = dict(data)
    program = dict(data['proposed_complete_program'])
    target = program['target']
    current = eef_transform(observation['current_eef']['right'])
    future = eef_transform(target['right'])
    delta = (future[:3,3]-current[:3,3])*1000
    rotation = Rotation.from_matrix(future[:3,:3] @ current[:3,:3].T).as_rotvec()
    program['complete_world_command_effect'] = {
        'right_LINK6_translation_xyz_mm':delta.round(3).tolist(),
        'world_rotation_vector_xyz_rad':rotation.round(6).tolist(),
        'right_gripper_command':'CLOSE' if target['right']['gripper_closed'] else 'OPEN',
        'left_arm':'held', 'physical_steps':5,
        'meaning':'All components form ONE simultaneous complete command. +X robot-right, +Y away from bases, +Z up; these are WORLD axes, not moving image axes. A close command is a grasp attempt, not holding evidence.'}
    score = program.get('stage_score') or {}
    result.pop('source_feature_after_each_complete_action',None)
    if os.environ.get('ROBODOJO_PICKUP_ACTOR_METRIC_ERRORS','1') != '0':
        result['source_feature_after_proposed_program'] = score.get('prediction')
    contact = result.get('contact_approach_evidence')
    if isinstance(contact,dict):
        result['contact_approach_evidence'] = {program['id']:contact[program['id']]} if program['id'] in contact else None
    evidence = program.get('public_five_step_evidence') or {}
    paths = evidence.get('five_step_retarget_previews') or []
    if paths:
        path = paths[-1]
        endpoint = path['predicted_joint_path'][-1]
        program['public_five_step_evidence'] = {
            'passed':path['public_path_gate'],
            'single_action_legal':path['native_eef_single_action_legal'],
            'predicted_terminal_position_error_mm':round(endpoint['predicted_link6_translation_residual_m']*1000,3),
            'predicted_terminal_rotation_error_rad':round(endpoint['predicted_link6_rotation_residual_rad'],6),
            'minimum_hand_gap_to_uncertain_RGB_reference_m':evidence.get('hand_reference_gap_m'),
            'scope':'Public robot-only five-step prediction. Scene/object collision is NOT certified; judge current RGB.'}
    else:
        program['public_five_step_evidence'] = {'passed_by_candidate_generator':True,
            'scope':'Public robot-only path/caps checked by generator; scene clearance still requires current RGB.'}
    validity = dict(result.get('current_geometry_validity') or {})
    table = validity.get('table_plane')
    if isinstance(table,dict):
        keep = ('source','reference_step_id','current_step_id','accepted_texture_match_count',
                'near_horizontal_plane_z_ax_by_c','plane_tilt_deg','plane_fit_abs_residual_p95_mm',
                'upper_height_for_robot_check_m','declared_systematic_allowance_mm','limitations')
        validity['table_plane'] = {k:table[k] for k in keep if k in table}
    if 'current_geometry_validity' in result:
        result['current_geometry_validity']=validity
    orientation = result.get('public_tool_orientation_evidence')
    if isinstance(orientation,dict):
        result['public_tool_orientation_evidence']={k:v for k,v in orientation.items() if k!='candidate_diagnostics'}
    result['proposed_complete_program']=program
    result['single_program_input_scope']='Only the CURRENT full program and its numerical effect are provided. Complete source/solver alternatives remain in saved diagnostics, not actor context. Preserve every stated uncertainty; short stage progress does not require completing the whole task in one action.'
    return result

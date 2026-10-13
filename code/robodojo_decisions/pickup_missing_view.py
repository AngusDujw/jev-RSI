"""Explicit unknown geometry -> Luna-reviewed open-hand observation recovery."""
import hashlib
import json
import numpy as np
from controller import choice
from pickup_rgb_axes import _targets
from robot_path_preview import preview


def recover(tools, obs, model, output, experience, turn, cause):
    record = {'turn':turn, 'step_id':obs['step_id'], 'stage':'missing_view_recovery',
              'geometry_error':str(cause), 'source_metric_geometry':'UNKNOWN'}
    if float(obs['current_eef']['right']['gripper_opening_command']) < .95:
        record['status'] = 'missing_view_closed_hand_not_recovered'
        return None, record
    target = _targets(obs,'z',1,.015)
    path = preview(obs,target['right'],None,steps=5)
    record['public_five_step_path'] = path
    if not (path['public_path_gate'] and path['native_eef_single_action_legal']):
        record['status'] = 'missing_view_public_path_rejected'
        return None, record
    snapshots = output / f"missing_view_experience_step_{obs['step_id']:03d}"
    snapshots.mkdir(exist_ok=False)
    hashes = {}
    for name, text in experience.items():
        (snapshots/name).write_text(text)
        hashes[name] = hashlib.sha256(text.encode()).hexdigest()
    evidence = {'task':obs['task'],'instruction':obs['instruction'],
        'step_id':obs['step_id'],'current_stage':'identity_and_view',
        'geometry_unknown_reason':str(cause),'object_pose_and_contact':'UNKNOWN',
        'measured_eef':obs['current_eef'],'measured_joints':obs['current_state'],
        'complete_robot_target':target,
        'complete_world_effect':{'right_LINK6_delta_xyz_mm':[0,0,15],
            'rotation':'held','right_gripper':'OPEN','left_arm':'held','physical_steps':5},
        'scope':'Runtime recovery hypothesis: lift the OPEN hand 15mm in WORLD +Z (up) to change occlusion. This is ONE complete action, not a planner recommendation. No object direction/distance, depth, contact, scene-clearance or guaranteed visibility gain is asserted. Public robot-only five-step path passed. Inspect all CURRENT RGB for the entire short hand/arm corridor; choose STOP if this exact increment is unsupported. Never descend, close, use a historical object pose or infer capture in this recovery.',
        'experience_original_text':experience,'experience_sha256':hashes}
    questions = [choice('source_identity','Is the mint-green scissors source currently identifiable in any of the THREE current RGB? Do not infer visibility from history.',
        {'visible_mint_green_scissors':'Current RGB supports the scissors identity.',
         'source_identity_unavailable':'Current source identity is ambiguous or hidden.'}),
        choice('full_program_decision','Judge only the exact OPEN +Z15mm five-step observation-recovery program. Unknown depth is not permission for contact. Execute only if current source identity and visible short corridor support it; otherwise STOP.',
        {'execute_open_up_recovery':'Execute this exact whole target once, then reobserve all cameras.',
         'stop_program_unsupported':'Do not execute this recovery.'})]
    try:
        answer = model.query(obs,questions,json.dumps(evidence,ensure_ascii=False),
                             f"pickup_active_{turn:02d}_step{obs['step_id']:03d}")
    except ValueError as error:
        record['status']='missing_view_decision_invalid_or_refused'
        record['decision_decode_error']=str(error)
        return None, record
    record['luna_choice']=answer['full_program_decision']
    record['luna_source_identity']=answer['source_identity']
    if (answer['source_identity']!='visible_mint_green_scissors' or
            answer['full_program_decision']!='execute_open_up_recovery'):
        record['status']='missing_view_luna_stopped'
        return None, record
    first = tools._rpc('eef_joint_target',targets=target)
    record['native_first_IK']=first
    if first.get('physical_steps')!=0 or len(first.get('action',[]))!=14:
        raise ValueError('Recovery native first IK must remain read-only')
    verified=preview(obs,target['right'],first['action'][7:13],steps=5)
    record['native_first_IK_public_path']=verified
    if not (verified['model_path_gate'] and verified['native_eef_single_action_legal']):
        record['status']='missing_view_native_path_rejected'
        return None, record
    import hybrid_rollout.robodojo.robodojo_server.gpt_only_client as native
    action={'request_id':obs['request_id'],'mode':'eef','steps':5,
            'reason':'du Luna current-RGB open-hand missing-view recovery','target':target}
    native.validate_action(action,tools.request)
    call=tools.next_call();call.pop('tool');call['response']=action
    after=tools.act(**call)
    error=float(np.linalg.norm(np.asarray(after['current_eef']['right']['position'])-
                               np.asarray(target['right']['position'])))
    record['post_action']={'action':action,'new_step_id':after['step_id'],
        'measured_right_LINK6_position_residual_m':error}
    record['status']='missing_view_reobserve' if error<=.002 else 'missing_view_tracking_incomplete'
    return after,record

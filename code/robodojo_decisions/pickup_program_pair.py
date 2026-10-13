"""Two already gated complete programs; no resampling or planner motion."""
import copy
import numpy as np
from pickup_unary_input import compact
from camera_geometry import eef_transform
from scipy.spatial.transform import Rotation


def build(data, obs, primary, targets, scores, diagnostics):
    current = eef_transform(obs['current_eef']['right'])
    first = eef_transform(targets[primary]['right'])
    candidates = []
    for name, score in scores.items():
        if name == primary or score['stage_progress_score'] <= 0 or name.startswith('open_empty_'):
            continue
        target = targets[name]
        if target['right']['gripper_closed'] != targets[primary]['right']['gripper_closed']:
            continue
        other = eef_transform(target['right'])
        distance = np.linalg.norm(other[:3,3]-first[:3,3])
        angle = Rotation.from_matrix(other[:3,:3] @ first[:3,:3].T).magnitude()
        if distance < .004 and angle < .025:
            continue
        # Targets are only the candidates admitted by the existing public gates.
        candidates.append(name)
    if not candidates:
        return None
    secondary = max(candidates, key=lambda k:scores[k]['stage_progress_score'])
    result = copy.deepcopy(data)
    programs = []
    for label, name in zip(('execute_program_a', 'execute_program_b'), (primary,secondary)):
        original = copy.deepcopy(data)
        original['proposed_complete_program'] = {'id':name, 'target':targets[name],
            'stage_score':scores[name], 'public_five_step_evidence':diagnostics.get(name)}
        item = compact(original,obs)
        program = item['proposed_complete_program']
        program.pop('stage_score',None)
        programs.append({'decision_value':label, **program,
            'phase_error_change':item.get('current_phase_error_change'),
            'source_feature_prediction':item.get('source_feature_after_proposed_program')})
    for key in ('proposed_complete_program','source_feature_after_proposed_program',
                'current_phase_error_change','single_program_input_scope'):
        result.pop(key,None)
    result['complete_program_alternatives'] = programs
    result['complete_robot_action_targets'] = {k:targets[k] for k in (primary,secondary)}
    result['program_comparison_scope'] = ('Choose exactly ONE full program or STOP from this one fresh observation. '
        'Each is an independent legal five-step robot target, not consecutive steps; never combine their components. '
        'Compare actual RGB corridor, uncertainty and incremental CURRENT stage progress. Neither program is certified scene clearance or grasp success. '
        'The planner supplies semantic stages/perception only; these programs are runtime public-robot/RGB algorithm outputs.')
    return result, {p['decision_value']:p['id'] for p in programs}

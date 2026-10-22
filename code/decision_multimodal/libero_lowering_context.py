"""Give the actor shared lateral context before its vertical seating choice."""
from copy import deepcopy
import math


def _number(value):
    return f'{value:g}' if type(value) in (int, float) and math.isfinite(value) else 'unavailable'


def revise_lowering(request, strategy):
    state = request['state']
    if (not strategy.get('lowering_xy_gate_enabled')
            or state.get('stage', {}).get('stage_key') != 'lower_to_place'
            or 'z' not in request['questions']):
        return request
    purpose = state.get('request_purpose')
    if purpose not in ('text_only_numeric_axis_classification', 'multimodal_policy',
                       'multimodal_rotation_gripper_transition'):
        return request
    revised = deepcopy(request)
    question = revised['questions']['z']
    rule = strategy['lowering_condition']
    if purpose == 'text_only_numeric_axis_classification':
        errors = state.get('current_minus_desired_error_mm', {})
        tolerances = state.get('current_position_tolerances_mm', {})
        facts = ' '.join(
            f'Current {axis.upper()} error={_number(errors.get(axis))} mm; '
            f'its alignment tolerance={_number(tolerances.get(axis))} mm.'
            for axis in ('x', 'y'))
        revised['state']['numeric_input'] = (
            'Position error is CURRENT minus DESIRED in millimetres. '
            'Answer X and Y independently. For Z use the ordered rules in its question. ' + facts)
        question['instructions'] = (
            'Choose Z using these ordered rules. '
            '1. If Z error is below its negative tolerance, choose positive. '
            '2. Otherwise, if Z error is above its positive tolerance AND both X/Y errors '
            'are available AND abs(X error)<=X tolerance AND abs(Y error)<=Y tolerance, choose negative. '
            '3. In every other case choose hold. Missing means unavailable, not zero. '
            + facts + ' ' + request['questions']['z']['instructions'])
        question['criteria'] = {
            'positive': 'Z error is below the negative Z tolerance.',
            'negative': 'Z error is above positive Z tolerance, both X/Y errors are available, and each is within its tolerance.',
            'hold': 'Z is within tolerance, OR Z is above tolerance but either lateral error is missing or outside tolerance.'}
    else:
        choices = state.get('numeric_axis_decisions', {})
        facts = ' '.join(f'Your SAME-observation numeric {axis.upper()} choice={choices.get(axis, "unavailable")}.'
                         for axis in ('x', 'y'))
        context = (rule + ' ' + facts +
            ' Negative Z descent requires BOTH numeric X/Y choices to be present and hold. '
            'Missing choices or visually uncertain holds do not establish measured alignment. '
            'Without that condition, hold Z unless current evidence independently calls for '
            'positive Z to restore clearance; missing XY alone is not such evidence.')
        question['instructions'] = context + ' ' + question['instructions']
        question['criteria']['positive'] += ' Current evidence must justify clearance restoration; unavailable XY alone does not.'
        question['criteria']['negative'] += ' Both same-observation numeric X and Y must already be present and hold.'
        question['criteria']['hold'] += ' Hold during unavailable or unfinished measured lateral alignment unless current evidence calls for restoring clearance.'
        revised['state']['lowering_sequence_context'] = context
    return revised

"""Stage-local templates compiled from the saved Pro high template proposal.

Clarity v1 remains a separate completed experiment, including its regressions.
The controller still executes the returned model choices without correcting them.
"""
from copy import deepcopy

from legacy_decisions import english
from libero_prompt_revision import RevisedAPI


def revise_local(original):
    request = deepcopy(original)
    state, questions = request['state'], request['questions']
    stage = state.get('stage', state.get('operation'))
    status = state.get('measurement_status', {})
    tolerance = state.get('axis_hold_tolerance_mm')
    if tolerance is None and 'hold_tolerance_m' in state:
        tolerance = state['hold_tolerance_m'] * 1000
    for axis, values in state.get('translation_axes', {}).items():
        error = values.get('goal_minus_current_mm')
        if axis not in questions or error is None or tolerance is None:
            continue
        questions[axis]['instructions'] = (
            f'For world {axis.upper()}, goal-minus-current error is {error} mm '
            f'and the original hold tolerance is {tolerance} mm. Independently '
            'choose positive if error > tolerance, negative if error < -tolerance, '
            'otherwise hold. Use only this axis. The supplied phase target already '
            'encodes stationary gripper-only stages as zero error. Holding-test '
            'status and a future phase do not change this signed scalar comparison.')
    transition = questions.get('transition')
    if transition is None:
        english(request)
        return request
    if 'measurement_status' in state:
        if status.get('holding_check') == 'not_checked_yet' and stage == 'lift':
            state['holding_evidence']['valid'] = None
            state['holding_evidence']['status'] = 'not_checked_yet'
            if status.get('target_arrival') is False:
                state['phase_contract'] = state['phase_contract'].replace(
                    'If evidence unavailable request reobserve or stop.',
                    'The co-motion test runs at lift-target arrival, not before it.')
        contract = state['phase_contract']
        if stage in ('grasp', 'release'):
            transition['instructions'] = (
                f'Current phase: {stage}. Original contract: {contract} '
                'Use only current target_arrival, gripper.phase_ticks and gripper.aperture_mm '
                'to decide whether this gripper trial has completed its stated duration and '
                'aperture requirements. Once they are satisfied, choose advance now; '
                'otherwise continue_phase. A holding check not yet performed does not delay '
                'closure-trial completion. It is tested in the prescribed lift stage. '
                'Do not require the current gripper state to match a future phase. '
                'Closure alone does not prove holding. Original failure/stop conditions remain.')
        elif stage == 'lift':
            transition['instructions'] = (
                f'Current phase: lift. Original contract: {contract} '
                'Before target_arrival, holding_check=not_checked_yet means the test is '
                'not due: continue the lift toward its supplied test point, unless an '
                'original failure or stop condition is established. After arrival, advance '
                'when holding_check=passed; an actual failed check requires available '
                'reobserve or stopping incomplete. Reobserve only if reobserve_available=true. '
                'An unperformed check is unknown, not failed. Required orientation still applies.')
        else:
            transition['instructions'] = (
                f'Current phase: {stage}. Original contract: {contract} '
                'Use current measurement_status.target_arrival and required orientation, '
                'plus any explicitly stated current contact-trial exception. Choose advance '
                'when this current contract is satisfied; otherwise continue positioning. '
                'For carry, its stated holding requirement must also pass. A future holding '
                'test is not a prerequisite for an earlier approach, insert or descend phase. '
                'Reobserve only for an actual failed current check or the original stall '
                'condition, and only if reobserve_available=true. If an actual failure is '
                'unrecoverable, stop. Zero commanded motion followed by zero displacement '
                'does not establish failure to track a nonzero command.')
    elif 'allowed_transitions' in state:
        # Complex drawer and plate contracts already expose their own exact gate.
        # Keep them and add only current positioning/permission clarification.
        transition['instructions'] += (
            ' Use current phase errors to complete prescribed positioning, including a '
            'reveal retreat, before requiring its later visual verification. Zero commanded '
            'motion followed by near-zero displacement is not evidence of failure to '
            'track a nonzero command. Do not classify a voluntary HOLD as physical blockage.')
        if (state['allowed_transitions'].get('advance') is True
                and state.get('completion_evidence', {}).get('contract_satisfied') is True):
            transition['instructions'] += (
                ' The current contract_satisfied and allowed_transitions.advance are both '
                'true: choose advance now, without waiting for a future-stage check.')
    # Remove no sensor fields or options. Explicit values stay in their original units.
    english(request)
    return request


class LocalAPI(RevisedAPI):
    profile = 'libero-clarity-v2'
    revise = staticmethod(revise_local)


def revise_recovery(original):
    request = revise_local(original)
    state = request['state']
    status = state.get('measurement_status', {})
    transition = request['questions'].get('transition')
    if transition is None or not status:
        return request
    current_trial = any(status.get(name) is True for name in (
        'visible_contact_candidate', 'support_stall_release_candidate',
        'carry_support_transfer_candidate'))
    if current_trial:
        # Preserve the exact original task-specific exception and its bounds.
        transition['instructions'] = original['questions']['transition']['instructions'] + (
            ' The supplied current trial-candidate flag is true. Evaluate this original '
            'bounded trial exception; do not reject it solely because target_arrival is '
            'false or a later holding/placement check is pending. It is not confirmed success.')
    elif state.get('stalls', 0) >= 3 and status.get('reobserve_available') is True:
        transition['instructions'] += (
            ' The measured consecutive stall count has reached the original recovery '
            'threshold of three and reobserve_available=true. Choose reobserve now to '
            'refresh permitted geometry instead of repeating this blocked phase command. '
            'This does not relax any contact or placement criterion.')
    english(request)
    return request


class RecoveryAPI(RevisedAPI):
    profile = 'libero-clarity-v3'
    revise = staticmethod(revise_recovery)

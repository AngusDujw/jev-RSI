"""Explicit request semantics for the separately declared LIBERO repair batch.

No vision, controller, target, tolerance, phase graph or motor answer is changed.
The original frozen request is saved alongside the revised model request.
"""
from copy import deepcopy
import json
import time
import urllib.error
import urllib.request

from legacy_decisions import LegacyAPI, ENDPOINT, MODEL, convert_request, convert_response, digest, english

PROFILE = 'libero-clarity-v1'


def revise_request(original):
    request = deepcopy(original)
    state = request['state']
    questions = request['questions']
    stage = state.get('stage', state.get('operation'))
    status = state.get('measurement_status', {})
    if status.get('holding_check') == 'not_checked_yet':
        state.setdefault('holding_evidence', {})['valid'] = None
        state['holding_evidence']['status'] = 'not_checked_yet'
        state['holding_evidence']['meaning'] = (
            'Not yet measured. The visual co-motion test runs on arrival at the lift target; '
            'this is neither a failed grasp nor evidence of holding.')
    # Focused supervisor reconstruction discarded its own pending-check protocol.
    pending_note = (
        ' At lift while still far from lift target, holding_check=not_checked_yet is normal: '
        'keep closed and move, not a failure. The co-motion test runs on arrival. '
        'Reobserve only after at least 3 stalled actions or an actual failed visual check; '
        'do not reobserve because a future check is pending. Never request reobserve '
        'when unavailable. These clarify the existing protocol; all task-specific '
        'phase gates and contact-trial exceptions still apply.')
    if 'measurement_status' in state:
        # This exact protocol existed before the historical focused reconstruction.
        # Append it rather than replacing task-specific gates or exceptions.
        if (stage == 'lift' and status.get('holding_check') == 'not_checked_yet'
                and status.get('target_arrival') is False):
            state['phase_contract'] = state['phase_contract'].replace(
                'If evidence unavailable request reobserve or stop.',
                'The holding test is pending until lift-target arrival; before that arrival '
                'continue the lift. Other failure and recovery rules are unchanged.')
        state['decision_protocol'] = (state.get('decision_protocol', '') + pending_note).strip()
    axes = state.get('translation_axes', {})
    tolerance = state.get('axis_hold_tolerance_mm')
    if tolerance is None and 'hold_tolerance_m' in state:
        tolerance = state['hold_tolerance_m'] * 1000
    for axis in 'xyz':
        if axis not in questions or axis not in axes:
            continue
        error = axes[axis].get('goal_minus_current_mm')
        if error is None or tolerance is None:
            continue
        questions[axis]['instructions'] += (
            f' Numeric definition for this question only: {axis.upper()} goal minus current '
            f'is {error} mm; this axis hold tolerance is {tolerance} mm. '
            'In a moving phase, positive error beyond tolerance needs positive, negative error '
            'beyond tolerance needs negative, and magnitude within tolerance needs hold. '
            'Do not reverse this sign because the phase is named lift, lower or retreat. '
            'Keep the original hold requirement in a gripper-only phase. '
            'A pending future visual check does not reverse a motion direction.')
    if 'transition' in questions:
        if 'measurement_status' in state:
            if (stage == 'lift' and status.get('holding_check') == 'not_checked_yet'
                    and status.get('target_arrival') is False):
                questions['transition']['instructions'] = questions['transition']['instructions'].replace(
                    'For stalled motion or missing visual holding evidence reobserve; if recovery budget unavailable stop.',
                    'This lift check is pending, not failed: continue toward its test point. '
                    'Reobserve for at least three stalled actions only if available; '
                    'stop if an actual failure is unrecoverable.')
            questions['transition']['instructions'] += pending_note
        else:
            questions['transition']['instructions'] += (
                ' Treat allowed_transitions as permissions, not outcomes. When advance is allowed '
                'and completion_evidence.contract_satisfied=true, choose advance now rather than '
                'holding indefinitely in the completed operation. A pending not_checked_yet visual '
                'test is not a failed test; follow the current operation_contract until its test point. '
                'Use retry/reobserve only when offered and justified by an actual failure or block. '
                'A final visible relation that is unknown remains unknown, not passed.')
    english(request)
    return request


def split_singletons(request):
    """One permissible value is a schema constant, not a sampled model answer."""
    sent = deepcopy(request)
    forced = {}
    for name, question in list(sent['questions'].items()):
        criteria = question['criteria']
        if len(criteria) == 1:
            value = next(iter(criteria))
            forced[name] = dict(type='choice', choice=value, confidence=1.,
                probabilities={value: 1.}, decision_source='schema_constant_not_model',
                confidence_meaning='Unique legal value; not model certainty or action correctness')
            del sent['questions'][name]
    return sent, forced


class RevisedAPI(LegacyAPI):
    def post(self, endpoint, original):
        if endpoint != '/systemone':
            raise ValueError('Unexpected legacy endpoint')
        revised = revise_request(original)
        sent, forced = split_singletons(revised)
        english(sent)
        payload = convert_request(sent) if sent['questions'] else None
        if payload is not None and (payload['model'] != MODEL or not isinstance(payload['input'], str)):
            raise ValueError('Expected named text-only Decision payload')
        while True:
            directory = self.folder / f'{self.calls:04d}'
            self.calls += 1
            try:
                directory.mkdir()
                break
            except FileExistsError:
                continue
        def save(name, value):
            (directory/name).write_text(json.dumps(value, indent=2, ensure_ascii=False,
                allow_nan=False) + '\n')
        save('legacy-request.json', original)
        save('revised-legacy-request.json', revised)
        save('schema-constants.json', forced)
        save('dispatch.json', dict(profile=PROFILE, key_origin='du', endpoint=ENDPOINT,
            image_count=0, experience_injection=False, state_sha256=digest(revised['state']),
            requested_model=MODEL, provider_called=payload is not None,
            original_request_sha256=digest(original), schema_constant_questions=list(forced),
            retry_policy='At most three HTTP attempts; only explicit 429/502/503/504 without a usable answer. No retries of received answers, refusals, timeouts or parsing errors. No simulation steps while retrying.'))
        started = time.monotonic()
        try:
            if payload is None:
                converted = dict(model=MODEL, answers={}, usage={},
                    probability_source='schema constants only; no provider call')
            else:
                save('request.json', payload)
                for attempt in range(3):
                    request = urllib.request.Request(ENDPOINT,
                        data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(),
                        headers={'Authorization': 'Bearer '+self.credential,
                                 'Content-Type': 'application/json'}, method='POST')
                    try:
                        with self.client.open(request, timeout=120) as handle:
                            raw = json.load(handle)
                        save('response.json', raw)
                        # Validate outside retry handling: never resample an answer.
                        break
                    except urllib.error.HTTPError as error:
                        body = error.read().decode('utf-8', errors='replace')
                        try:
                            decoded = json.loads(body)
                        except ValueError:
                            decoded = None
                        answer_present = isinstance(decoded, dict) and 'answers' in decoded
                        terminal_refusal = any(word in body.lower() for word in (
                            'refusal', 'refused', 'content_filter', 'content_policy_violation',
                            'safety_violation', 'insufficient_quota'))
                        save(f'http-attempt-{attempt+1}.json', dict(status=error.code,
                            error=str(error), body_utf8=body.replace(self.credential, '[redacted]'),
                            answer_field_present=answer_present, terminal_refusal=terminal_refusal))
                        if answer_present:
                            raw = decoded
                            save('response.json', raw)
                            break  # Validate once; never retry a supplied answer.
                        if terminal_refusal or error.code not in (429, 502, 503, 504) or attempt == 2:
                            raise
                        time.sleep(2 ** (attempt+1))
                converted = convert_response(raw, sent)
            converted['answers'].update(forced)
            converted['request_profile'] = PROFILE
            if forced:
                converted['schema_constant_questions'] = list(forced)
                converted['probability_source'] += '; singleton distributions are schema constants, not model probabilities'
            save('legacy-response.json', converted)
            self.log(dict(kind='decision_api_response', key_origin='du', model=MODEL,
                profile=PROFILE, image_count=0, seconds=time.monotonic()-started,
                request_sha256=digest(payload), audit_directory=str(directory),
                schema_constant_questions=list(forced), provider_called=payload is not None))
            return converted
        except Exception as error:
            save('failure.json', dict(error_type=type(error).__name__,
                error=str(error).replace(self.credential, '[redacted]')[:600],
                seconds=time.monotonic()-started))
            raise

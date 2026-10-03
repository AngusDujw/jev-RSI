"""English request contract and compact evidence from disclosed measurements only."""
import hashlib
import json
import re


def validate_english(value, path='$'):
    if isinstance(value, dict):
        for key, child in value.items():
            validate_english(str(key), path + '.<key>')
            validate_english(child, path + '.' + str(key))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            validate_english(child, path + '[' + str(index) + ']')
    elif isinstance(value, str) and not value.isascii():
        raise ValueError('Non-English/non-ASCII model input at ' + path)


def audit_request(state, questions, run_dir):
    from pathlib import Path
    payload = dict(state=state, questions=questions)
    validate_english(payload)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    with (Path(run_dir) / 'input_contract_audit.jsonl').open('a') as handle:
        handle.write(json.dumps(dict(stage=state.get('stage'), role=state.get('decision_role'),
                                    english_only=True, sha256=digest)) + '\n')


def evidence_status(stage, evidence, error):
    if error:
        return 'unobservable'
    if stage == 'verify_grasp':
        count = evidence.get('consecutive_supporting_observations', 0)
        if count >= 2:
            return 'supported'
        rows = [evidence] if 'robot_rise_m' in evidence else [v for v in evidence.values() if isinstance(v, dict)]
        if any(v.get('robot_rise_m', 0) > .02 and
               v.get('visible_rise_m', v.get('visible_bottom_rise_m', 1)) is not None and
               v.get('visible_rise_m', v.get('visible_bottom_rise_m', 1)) < .005 for v in rows):
            return 'contradicted'
        delta = evidence.get('visible_object_displacement_m')
        robot = evidence.get('robot_displacement_m')
        if delta and robot and robot[2] > .02 and delta[2] < .005:
            return 'contradicted'
        if evidence.get('reason') or any(v.get('visible_rise_m', 1) is None for v in rows):
            return 'unobservable'
        return 'inconclusive'
    if stage == 'verify_release':
        return 'inconclusive'  # Expose geometry and stability; do not invent success.
    return 'not_checked_yet'


def add_card(state, compact=False):
    evidence = state.get('phase_evidence', {})
    stage = state['stage']
    alignment = state.get('alignment_facts', {})
    state['decision_card'] = dict(
        current_objective=stage, next_candidate=state.get('next_stage_candidate'),
        evidence_status=evidence_status(stage, evidence, state.get('perception_error')),
        axes_outside_band={a: v['axes_outside_tracking_band'] for a, v in alignment.items()},
        orientation_outside_band={a: v.get('orientation_outside_tracking_band') for a, v in alignment.items()},
        grasp_history_is_not_current_attachment=True,
        future_verification_is_not_required_for_current_robot_waypoint=True,
        evidence_source='disclosed RGB-D estimates and robot feedback only')
    if compact:
        state['history'] = state.get('history', [])[-2:]
        state.pop('evidence_card', None)
        if isinstance(evidence.get('candidate_plan'), dict):
            plan = evidence['candidate_plan']
            state['phase_evidence'] = dict(evidence)
            state['phase_evidence']['candidate_plan'] = {
                k: plan[k] for k in ('source', 'destination', 'arms', 'rule', 'requested_lift_m',
                                    'fold_mode', 'count_entry') if k in plan}
            # Temporal evidence explains departure/return; keep it even in compact input.
        state['robot'] = {a: {k: r[k] for k in ('grasp', 'quaternion', 'opening') if k in r}
                          for a, r in state['robot'].items()}
    return state

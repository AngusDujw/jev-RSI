"""Audit public-input Jev ownership for Goal drawer episodes.

This checks saved model requests and actual branches. Perception source still
requires separate RGB-D/code review; this cannot prove an image estimate true.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


STATE_KEYS = {
    'task', 'public_entity_slots', 'stage', 'next_stage', 'stage_contract',
    'translation_axes', 'required_rotation_world_rad', 'gripper',
    'completion_evidence', 'recent_actions', 'allowed_transitions',
    'information_sources',
}
FORBIDDEN_KEYS = {
    'reward', 'success', 'object_poses', 'object_id', 'object_ids',
    'goal_predicates', 'true_state', 'scene_layout', 'bddl', 'task_id',
    'init_state', 'contact_forces', 'sim_object_state',
}
SIGNS = {'negative': -1, 'hold': 0, 'positive': 1}


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def inspect_keys(value):
    if isinstance(value, dict):
        assert not (set(value) & FORBIDDEN_KEYS), set(value) & FORBIDDEN_KEYS
        for child in value.values():
            inspect_keys(child)
    elif isinstance(value, list):
        for child in value:
            inspect_keys(child)


def audit(episode):
    protocol = json.loads((episode/'protocol.json').read_text())
    assert protocol['task_id'] in (1098, 1202) and protocol['suite'] == 'libero_goal'
    combined = bool(protocol.get('drawer_bowl_continuation'))
    drawer_stage = lambda stage: stage.startswith('0:open_drawer:')
    decisions = [d for d in rows(episode/'decisions.jsonl')
                 if not combined or drawer_stage(d['stage'])]
    branches = [b for b in rows(episode/'branches.jsonl')
                if not combined or drawer_stage(b['stage'])]
    events = rows(episode/'events.jsonl')
    drawer_result = episode/'drawer-primitive-result.json'
    result = json.loads((drawer_result if combined and drawer_result.exists()
                         else episode/'result.json').read_text())
    assert decisions and len({d['decision_id'] for d in decisions}) == len(decisions)
    by_id = {d['decision_id']: d for d in decisions}
    states = {}
    usage = Counter()
    answered = []
    unanswered = []
    for decision in decisions:
        ident = decision['decision_id']
        request = json.loads((episode/ident/'request.json').read_text())
        assert set(request) == {'model', 'state', 'questions'}
        assert json.dumps(request, ensure_ascii=False).isascii(), ident
        assert hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest() == decision['request_sha256'], ident
        inspect_keys(request)
        state = request['state']
        assert set(state) == STATE_KEYS, (ident, set(state) ^ STATE_KEYS)
        assert state['stage'] == decision['stage']
        states[ident] = state
        response_path = episode/ident/'response.json'
        if not response_path.exists():
            assert ident == decisions[-1]['decision_id'] and result.get('error'), ident
            assert 'answers' not in decision, ident
            unanswered.append(ident)
            continue
        response = json.loads(response_path.read_text())
        answered.append(decision)
        answers = response['answers']
        assert answers == decision['answers']
        assert set(answers) == set(request['questions']), ident
        assert [SIGNS[answers[axis]['choice']] for axis in 'xyz'] == decision['signs']
        for index, axis in enumerate(('rx', 'ry', 'rz')):
            expected = SIGNS[answers[axis]['choice']] if axis in answers else 0
            assert expected == decision['rotation_signs'][index]
        assert answers['gripper']['choice'] == decision['gripper']
        assert answers['transition']['choice'] == decision['transition']
        assert state['allowed_transitions'][decision['transition']]
        for key, value in response.get('usage', {}).items():
            if isinstance(value, int):
                usage[key] += value

    current_gripper = -1
    executed = set()
    for branch in branches:
        ident = branch['decision_id']
        assert ident in by_id and ident not in unanswered and ident not in executed
        executed.add(ident)
        decision = by_id[ident]
        assert branch['stage'] == decision['stage']
        assert branch['selected_gripper'] == decision['gripper']
        assert branch['selected_transition'] == decision['transition']
        current_gripper = (current_gripper if decision['gripper'] == 'keep'
                           else -1 if decision['gripper'] == 'open' else 1)
        assert branch['executed_gripper'] == current_gripper
        assert all(delta*sign >= -1e-12 for delta, sign in
                   zip(branch['delta'], decision['signs']))
        assert all(delta*sign >= -1e-12 for delta, sign in
                   zip(branch['rotation_delta'], decision['rotation_signs']))

    edges = [event for event in events if event.get('kind') == 'phase_transition'
             and (not combined or drawer_stage(event['from_stage']))]
    for edge in edges:
        ident = edge['decision_id']
        assert ident in executed
        assert by_id[ident]['transition'] == 'advance'
        assert edge['from_stage'] == states[ident]['stage']
        assert edge['to_stage'] == states[ident]['next_stage']
    assert len(edges) == sum(d['transition'] == 'advance' for d in answered)
    assert result['jev_calls'] == len(decisions)
    return dict(episode=str(episode), success=result['success'],
                program_finished=result['program_finished'],
                drawer_primitive_finished=result['drawer_primitive_finished'],
                decisions=len(decisions), answered=len(answered),
                unanswered_requests=len(unanswered), executed=len(branches),
                phase_edges=len(edges),
                gripper_choices=dict(Counter(d['gripper'] for d in answered)),
                transition_choices=dict(Counter(d['transition'] for d in answered)),
                usage=dict(usage), contract_violations=0,
                input_boundary='Request schema/forbidden keys checked; frozen RGB-D perception source reviewed separately')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('episode', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = audit(args.episode)
    output = json.dumps(report, indent=2)+'\n'
    if args.output:
        args.output.write_text(output)
    print(output, end='')


if __name__ == '__main__':
    main()

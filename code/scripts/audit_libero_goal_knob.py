"""Audit a recorded Goal1383 Jev episode against responses and executed actions.

This checks recorded inputs and ownership, not the provenance of the RGB-D
estimates; provenance still requires review of the frozen perception source.
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
    'init_state',
}
SOURCES = {
    'public_task', 'agentview_rgbd', 'wrist_rgbd', 'camera_calibration',
    'robot_proprioception', 'own_robot_mesh', 'executed_action_history',
}
SIGNS = {'negative': -1, 'hold': 0, 'positive': 1}


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def inspect_keys(value):
    if isinstance(value, dict):
        assert not (set(value) & FORBIDDEN_KEYS), set(value) & FORBIDDEN_KEYS
        for item in value.values():
            inspect_keys(item)
    elif isinstance(value, list):
        for item in value:
            inspect_keys(item)


def audit(episode):
    protocol = json.loads((episode/'protocol.json').read_text())
    assert protocol['task_id'] == 1383 and protocol['knob_supervisor']
    decisions = rows(episode/'decisions.jsonl')
    branches = rows(episode/'branches.jsonl')
    events = rows(episode/'events.jsonl')
    result = json.loads((episode/'result.json').read_text())
    assert decisions and len({d['decision_id'] for d in decisions}) == len(decisions)
    by_id = {d['decision_id']: d for d in decisions}
    states = {}
    tokens = Counter()
    for decision in decisions:
        ident = decision['decision_id']
        request = json.loads((episode/ident/'request.json').read_text())
        response = json.loads((episode/ident/'response.json').read_text())
        assert set(request) == {'model', 'state', 'questions'}
        assert json.dumps(request, ensure_ascii=False).isascii(), ident
        assert hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest() == decision['request_sha256'], ident
        inspect_keys(request)
        state = request['state']
        assert set(state) == STATE_KEYS, (ident, set(state) ^ STATE_KEYS)
        assert set(state['information_sources']) <= SOURCES
        assert set(state['completion_evidence']['sources']) <= SOURCES
        assert state['stage'] == decision['stage']
        states[ident] = state
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
                tokens[key] += value

    prior_gripper = -1
    executed = set()
    for branch in branches:
        ident = branch['decision_id']
        assert ident in by_id and ident not in executed
        executed.add(ident)
        decision = by_id[ident]
        assert branch['stage'] == decision['stage']
        assert branch['selected_gripper'] == decision['gripper']
        assert branch['selected_transition'] == decision['transition']
        prior_gripper = (prior_gripper if decision['gripper'] == 'keep' else
                         -1 if decision['gripper'] == 'open' else 1)
        assert branch['executed_gripper'] == prior_gripper
        assert all(delta*sign >= -1e-12 for delta, sign in
                   zip(branch['delta'], decision['signs']))
        assert all(delta*sign >= -1e-12 for delta, sign in
                   zip(branch['rotation_delta'], decision['rotation_signs']))

    edges = [event for event in events if event.get('kind') == 'phase_transition']
    for edge in edges:
        ident = edge['decision_id']
        assert ident in executed
        assert by_id[ident]['transition'] == 'advance'
        assert edge['from_stage'] == states[ident]['stage']
        assert edge['to_stage'] == states[ident]['next_stage']
    assert len(edges) == sum(d['transition'] == 'advance' for d in decisions)
    assert result['jev_calls'] == len(decisions)
    return {
        'episode': str(episode), 'success': result['success'],
        'program_finished': result['program_finished'],
        'decisions': len(decisions), 'executed': len(branches),
        'phase_edges': len(edges), 'gripper_choices': dict(Counter(
            d['gripper'] for d in decisions)),
        'transition_choices': dict(Counter(d['transition'] for d in decisions)),
        'usage': dict(tokens), 'contract_violations': 0,
        'input_boundary': 'request key allowlist and source labels checked; perception source review required',
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('episode', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = audit(args.episode)
    text = json.dumps(report, indent=2)+'\n'
    if args.output:
        args.output.write_text(text)
    print(text, end='')


if __name__ == '__main__':
    main()

"""Check saved push-model responses against every executed control and phase edge."""
import argparse
import json
from pathlib import Path


FORBIDDEN = {'reward', 'success', 'object_poses', 'object_ids', 'goal_predicates',
             'true_state', 'scene_layout', 'bddl', 'task_id', 'init_state'}
ALLOWED = {'task', 'operation', 'next_operation', 'operation_contract',
           'translation_axes', 'axis_hold_tolerance_mm',
           'required_rotation_world_rad', 'gripper', 'completion_evidence',
           'allowed_transitions', 'visible_geometry', 'phase_decisions',
           'information_sources'}


def scan(value):
    if isinstance(value, dict):
        assert not (set(value) & FORBIDDEN), set(value) & FORBIDDEN
        for child in value.values():
            scan(child)
    elif isinstance(value, list):
        for child in value:
            scan(child)


def audit(root):
    rows = [json.loads(s) for s in (root/'decisions.jsonl').read_text().splitlines()]
    branches = [json.loads(s) for s in (root/'branches.jsonl').read_text().splitlines()] if (root/'branches.jsonl').exists() else []
    events = [json.loads(s) for s in (root/'events.jsonl').read_text().splitlines()]
    decisions = {row['decision_id']: row for row in rows}
    states = {}
    sign = dict(negative=-1, hold=0, positive=1)
    for row in rows:
        directory = root/row['decision_id']
        request = json.loads((directory/'request.json').read_text())
        state = request['state']
        assert set(state) <= ALLOWED, set(state)-ALLOWED
        scan(state)
        assert json.dumps(request, ensure_ascii=False).isascii()
        states[row['decision_id']] = state
        if 'answers' not in row:
            continue
        answer = json.loads((directory/'response.json').read_text())['answers']
        assert answer == row['answers'] and set(answer) == set(request['questions'])
        assert [sign[answer[axis]['choice']] for axis in 'xyz'] == row['signs']
        for index, axis in enumerate(('rx', 'ry', 'rz')):
            assert (sign[answer[axis]['choice']] if axis in answer else 0) == row['rotation_signs'][index]
        assert answer['gripper']['choice'] == row['gripper']
        assert answer['transition']['choice'] == row['transition']
    previous_gripper = -1
    for branch in branches:
        decision = decisions[branch['decision_id']]
        assert branch['selected_gripper'] == decision['gripper']
        assert branch['selected_transition'] == decision['transition']
        expected = previous_gripper if decision['gripper'] == 'keep' else -1 if decision['gripper'] == 'open' else 1
        assert branch['executed_gripper'] == expected
        previous_gripper = expected
        assert all(d*s >= -1e-12 for d, s in zip(branch['delta'], decision['signs']))
    edges = [row for row in events if row.get('kind') == 'phase_transition']
    for edge in edges:
        decision = decisions[edge['decision_id']]
        state = states[edge['decision_id']]
        assert decision['transition'] == 'advance'
        assert state['allowed_transitions']['advance']
        assert edge['to_stage'] == state['next_operation']
    violations = [row['decision_id'] for row in rows if row.get('transition') == 'advance'
                  and not states[row['decision_id']]['allowed_transitions']['advance']]
    result = dict(episode=str(root), decisions=len(rows), actions=len(branches),
                  phase_edges=len(edges), contract_violations=violations,
                  result=json.loads((root/'result.json').read_text()),
                  note='Response/action/edge audit; source provenance requires code review')
    assert not violations
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    answer = audit(args.root)
    if args.output:
        args.output.write_text(json.dumps(answer, indent=2)+'\n')
    print(json.dumps(answer, indent=2))

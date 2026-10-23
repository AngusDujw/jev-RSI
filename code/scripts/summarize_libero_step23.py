"""Audit saved cabinet/knob translation-scale trials, including native clipping."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics

from summarize_libero_step_scale import check_input


def read(path):
    return json.loads(path.read_text())


def audit(run):
    manifest = read(run/'manifest.json')
    task = manifest['reservation']['task']
    assert task in (1252, 1383)
    scale = manifest['translation_step_multiplier']
    ep = run/'episode'
    result = read(ep/'result.json')
    limits = read(ep/'translation-controller-limits.json')
    branches = [json.loads(line) for line in (ep/'branches.jsonl').read_text().splitlines() if line]
    stages, clipped, reversals, models = Counter(), Counter(), Counter(), set()
    previous, motions, errors, per_stage_errors = {}, [], [], {}
    gripper = -1
    ticks = 0
    signs = {'negative': -1, 'hold': 0, 'positive': 1}
    for branch in branches:
        folder = ep/branch['decision_id']
        request, response = read(folder/'request.json'), read(folder/'response.json')
        assert json.dumps(request, ensure_ascii=False).isascii()
        check_input(request)
        answers = response['answers']
        assert set(answers) == set(request['questions'])
        assert all(v['choice'] in request['questions'][k]['criteria'] for k, v in answers.items())
        models.add(response['model'])
        assert response['model'].startswith('jev-1.13.')
        assert branch['translation_step_multiplier'] == scale
        stage = branch['stage']
        block = branch['block_native_ticks']
        assert block == (6 if task == 1383 and stage.split(':')[-1] in ('grasp', 'release') else 3)
        ticks += block
        assert ticks == branch['native_steps']
        stages[stage] += block
        axis_errors = []
        for index, axis in enumerate('xyz'):
            state_axis = request['state']['translation_axes'][axis]
            error = state_axis['goal_minus_current_mm']/1000
            axis_errors.append(error*1000)
            expected = signs[answers[axis]['choice']]*min(.020 if task == 1252 else .018, .5*abs(error))
            assert abs(expected-branch['base_delta'][index]) < 3e-6
            assert abs(branch['delta'][index]-scale*branch['base_delta'][index]) < 1e-12
            assert abs(branch['normalized_xyz'][index]-branch['delta'][index]/.05) < 1e-12
            native = min(limits['input_high'][index], max(limits['input_low'][index], branch['normalized_xyz'][index]))
            assert abs(native-branch['controller_clipped_xyz'][index]) < 1e-12
            assert branch['translation_clipped_axes'][index] == (abs(native-branch['normalized_xyz'][index]) > 1e-12)
            if branch['translation_clipped_axes'][index]:
                clipped[axis] += block
            key = (stage, axis)
            direction = signs[answers[axis]['choice']]
            if direction and previous.get(key, direction) != direction:
                reversals[stage+':'+axis] += 1
            if direction:
                previous[key] = direction
        errors.append(dict(decision_id=branch['decision_id'], stage=stage, errors_mm=axis_errors))
        per_stage_errors[stage] = axis_errors
        choice = answers['gripper']['choice']
        gripper = gripper if choice == 'keep' else -1 if choice == 'open' else 1
        assert branch['selected_gripper'] == choice and branch['executed_gripper'] == gripper
        assert branch['selected_transition'] == answers['transition']['choice']
        if any(abs(value) > 1e-12 for value in branch['delta']):
            motions.append(1000*sum((a-b)**2 for a, b in zip(branch['after'], branch['before']))**.5)
    assert ticks == result['native_steps']
    requests = sorted(ep.glob('decision-*/request.json'))
    return dict(task=task, init=manifest['reservation']['init'], scale=scale,
                success=result['success'], program_finished=result['program_finished'],
                error=result.get('error'), final_stage=result.get('stage'),
                native_steps=result['native_steps'], initial_open_steps_excluded=10,
                jev_calls=result['jev_calls'], executed_decisions=len(branches),
                models=sorted(models), controller_limits=limits,
                clipped_native_axis_commands=dict(clipped), stage_native_steps=dict(stages),
                direction_reversals=dict(reversals), last_stage_request_errors_mm=per_stage_errors,
                median_nonzero_block_motion_mm=statistics.median(motions) if motions else None,
                maximum_nonzero_block_motion_mm=max(motions, default=0),
                visible_control_angle_change_rad=result.get('visible_control_angle_change_rad'),
                first_request_sha256=hashlib.sha256(requests[0].read_bytes()).hexdigest() if requests else None,
                policy_source_sha256=manifest['policy_source_sha256'],
                seconds=read(run/'launcher-result.json')['seconds'], run=str(run))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = [audit(p) for p in sorted(args.root.glob('2026-10-23-goal*-init*-step-*'))]
    assert len(rows) == 4 and {(r['task'], r['scale']) for r in rows} == {(t, s) for t in (1252, 1383) for s in (2, 3)}
    for task in (1252, 1383):
        group = [r for r in rows if r['task'] == task]
        assert group[0]['policy_source_sha256'] == group[1]['policy_source_sha256']
        assert group[0]['first_request_sha256'] == group[1]['first_request_sha256']
    args.output.write_text(json.dumps(dict(rows=rows, audit='Exact XYZ scaling, real response ownership, native block counts, English and forbidden-field checks passed.'), indent=2)+'\n')
    print(json.dumps([{k:r[k] for k in ('task','scale','success','program_finished','native_steps','jev_calls','error','clipped_native_axis_commands')} for r in rows], indent=2))


if __name__ == '__main__':
    main()

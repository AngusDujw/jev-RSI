"""Audit paired translation-multiplier rollouts using only saved artifacts."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics

FORBIDDEN = {'reward', 'success', 'object_poses', 'object_id', 'object_ids',
             'goal_predicates', 'true_state', 'scene_layout', 'bddl', 'task_id', 'init_state'}


def check_input(value):
    if isinstance(value, dict):
        assert not FORBIDDEN.intersection(value), FORBIDDEN.intersection(value)
        for child in value.values():
            check_input(child)
    elif isinstance(value, list):
        for child in value:
            check_input(child)


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = []
    signs = {'negative': -1, 'hold': 0, 'positive': 1}
    for run in sorted(args.root.glob('2026-10-22-goal1144-init5-step-*')):
        ep = run/'episode'
        if not (ep/'result.json').exists():
            continue
        result, manifest = read(ep/'result.json'), read(run/'manifest.json')
        scale = manifest['translation_step_multiplier']
        branches = [json.loads(line) for line in (ep/'branches.jsonl').read_text().splitlines() if line]
        counts, motions, command_axes = Counter(), [], []
        gripper = -1
        models = set()
        for branch in branches:
            folder = ep/branch['decision_id']
            req, resp = read(folder/'request.json'), read(folder/'response.json')
            assert all(ord(c) < 128 for c in json.dumps(req, ensure_ascii=False))
            check_input(req)
            answers = resp['answers']
            models.add(resp['model'])
            assert set(answers) == set(req['questions'])
            for key, answer in answers.items():
                assert answer['choice'] in req['questions'][key]['criteria']
            assert branch['translation_step_multiplier'] == scale
            for i, axis in enumerate('xyz'):
                s = signs[answers[axis]['choice']]
                error = req['state']['translation_axes'][axis]['goal_minus_current_mm']/1000
                expected = s*min(.02, .5*abs(error))
                # The model sees errors rounded to 0.01 mm; execution uses full precision.
                assert abs(expected-branch['base_delta'][i]) < 3e-6
                assert abs(branch['delta'][i]-scale*branch['base_delta'][i]) < 1e-12
                command_axes.append(abs(branch['delta'][i])*1000)
            choice = answers['gripper']['choice']
            gripper = gripper if choice == 'keep' else -1 if choice == 'open' else 1
            assert branch['selected_gripper'] == choice
            assert branch['executed_gripper'] == gripper
            assert branch['selected_transition'] == answers['transition']['choice']
            counts[branch['stage']] += 3
            if any(abs(v) > 1e-12 for v in branch['delta']):
                motions.append(sum((a-b)**2 for a, b in zip(branch['after'], branch['before']))**.5*1000)
        assert len(branches)*3 == result['native_steps']
        requests = sorted(ep.glob('decision-*/request.json'))
        rows.append(dict(scale=scale, success=result['success'], program_finished=result['program_finished'],
                         native_steps=result['native_steps'], initial_open_steps_excluded=10,
                         steps_including_initial_open=result['native_steps']+10,
                         jev_calls=result['jev_calls'], executed_decisions=len(branches),
                         models=sorted(models), error=result.get('error'), stage=result.get('stage'),
                         stage_native_steps=dict(counts), maximum_command_axis_mm=max(command_axes, default=0),
                         actual_nonzero_block_median_mm=statistics.median(motions) if motions else None,
                         actual_nonzero_block_max_mm=max(motions, default=0),
                         first_request_sha256=hashlib.sha256(requests[0].read_bytes()).hexdigest() if requests else None,
                         source_sha256=manifest['policy_source_sha256'],
                         seconds=read(run/'launcher-result.json')['seconds'],
                         run=str(run), audit='all executed commands match real responses; XYZ scaled exactly; no forbidden input keys'))
    rows.sort(key=lambda row: row['scale'])
    baseline = next((row for row in rows if row['scale'] == 1), None)
    for row in rows:
        row['completed_step_reduction_percent'] = (round(100*(baseline['native_steps']-row['native_steps'])/baseline['native_steps'], 2)
            if baseline and baseline['success'] and baseline['program_finished'] and row['success'] and row['program_finished'] else None)
    if rows:
        assert all(row['source_sha256'] == rows[0]['source_sha256'] for row in rows)
    report = dict(rows=rows, same_initial_model_request=len({r['first_request_sha256'] for r in rows}) == 1,
                  interpretation='One shared task/init per scale; paired pilot, not a success-rate estimate. Native counts exclude ten initial open-gripper steps; physical displacement differs from commanded translation.')
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'rows'}, ensure_ascii=False))
    for row in rows:
        print(json.dumps({k:row[k] for k in ('scale','success','program_finished','native_steps','jev_calls','completed_step_reduction_percent','error')}, ensure_ascii=False))


if __name__ == '__main__':
    main()

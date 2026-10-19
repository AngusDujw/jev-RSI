"""Read-only audit of genuine RGB direction rollouts and actual provider bodies."""
import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
from legacy_decisions import english


def compact_audit(root):
    """Audit split Decisions calls against immutable request and execution evidence."""
    result=json.loads((root/'result.json').read_text()) if (root/'result.json').exists() else None
    manifest=json.loads((root/'manifest.json').read_text())
    # Snapshot executed rows before reading requests so a live episode cannot
    # append an action whose later request was absent from the initial scan.
    actions=[json.loads(s) for s in (root/'execution.jsonl').read_text().splitlines()] if (root/'execution.jsonl').exists() else []
    counts=Counter();purposes=Counter();answers_by_observation={}
    forbidden={'reward','success','contact','object_pose','target_pose','required_rotation_world_rad','goal_minus_current'}

    def inspect_text(value):
        if isinstance(value,dict):
            assert not (set(value)&forbidden),set(value)&forbidden
            for item in value.values():inspect_text(item)
        elif isinstance(value,list):
            for item in value:inspect_text(item)
        elif isinstance(value,str) and value.lstrip().startswith(('{','[')):
            try:decoded=json.loads(value)
            except ValueError:return
            inspect_text(decoded)

    axes=('x','y','z','rx','ry','rz')
    for path in sorted((root/'evidence').glob('*-request.json')):
        folder=root/'decision-api'/path.name[:4]
        request=json.loads(path.read_text());english(request)
        assert request['model']=='gpt-6-luna'
        summary=json.loads((folder/'request-summary.json').read_text())
        dispatch=json.loads((folder/'dispatch.json').read_text())
        assert dispatch['endpoint']=='https://api.openai.com/v1/decisions'
        assert dispatch['key_origin']=='du' and dispatch['experience_injection'] is False
        image_hashes=[]
        for message in request['input']:
            for part in message['content']:
                if part['type']=='input_text':inspect_text(part['text'])
                elif part['type']=='input_image':
                    image_file=part.pop('image_file')
                    assert Path(image_file).parent==Path('images')
                    raw=(root/'evidence'/image_file).read_bytes()
                    digest=hashlib.sha256(raw).hexdigest()
                    assert Path(image_file).name==digest+'.png'
                    image_hashes.append(digest)
                    part['image_url']='data:image/png;base64,'+base64.b64encode(raw).decode()
        assert image_hashes==summary['image_sha256']
        body=json.dumps(request,ensure_ascii=False).encode()
        assert hashlib.sha256(body).hexdigest()==summary['body_sha256'],str(path)
        questions={q['name']:q for q in request['questions']}
        for name,question in questions.items():
            if name in axes:
                assert {c['value'] for c in question['choices']}=={'positive','negative','hold'}
        counts['requests']+=1;counts['image_blocks']+=len(image_hashes)
        purposes[summary.get('request_purpose','unknown')]+=1
        if (folder/'failure.json').exists():counts['failures']+=1
        if not (folder/'response.json').exists():
            counts['unanswered_requests']+=1;continue
        response=json.loads((folder/'response.json').read_text())
        assert response['model']=='gpt-6-luna'
        assert {a['name'] for a in response['answers']}==set(questions)
        key=(summary['native_tick'],summary['stage']['name'])
        chosen=answers_by_observation.setdefault(key,{})
        for answer in response['answers']:
            assert answer['choice'] in {c['value'] for c in questions[answer['name']]['choices']}
            chosen[answer['name']]=answer['choice']
        counts['responses']+=1
    diagnostic=manifest.get('diagnostic_replay',False)
    for row in actions:
        if diagnostic:continue
        key=(row['native_steps']-manifest['execution_steps'],manifest['plan']['stages'][row['stage']]['name'])
        chosen=answers_by_observation[key]
        for channel,value in row['choices'].items():
            assert chosen[channel]==value,(key,channel,value,chosen.get(channel))
            counts['executed_channel_choices_checked']+=1
        command=row['commanded_translation_mm']+row['commanded_rotation_world_deg']
        for axis,value in zip(axes,command):
            sign='positive' if value>1e-10 else 'negative' if value< -1e-10 else 'hold'
            assert sign==row['choices'][axis],(key,axis,value,row['choices'][axis])
        counts['physical_action_turns']+=1
    return dict(directory=str(root),result=result,counts=dict(counts),request_purposes=dict(purposes),
        diagnostic_replay=diagnostic,actor_agency_checked=bool(actions) and not diagnostic,
        exact_request_bodies_and_image_assets_verified=bool(counts['requests']),
        all_executed_choices_and_command_signs_match_original_answers=bool(actions) and not diagnostic,
        limitation='This verifies recorded request integrity, English text, dispatch identity and actor agency. It does not certify perception accuracy, sensor-frame freshness, physical motion correctness or task completion. Native outcome and program completion remain separate.')


def audit(root):
    if (root/'evidence').is_dir():return compact_audit(root)
    result=json.loads((root/'result.json').read_text()) if (root/'result.json').exists() else None
    counts=Counter();axes={a:Counter() for a in ('x','y','z','rx','ry','rz')}
    stages=Counter();world_samples=0
    for folder in sorted((root/'decision-api').glob('[0-9]*')):
        if not (folder/'request.json').exists():continue
        request=json.loads((folder/'request.json').read_text());english(request)
        assert request['model']=='gpt-6-luna'
        dispatch=json.loads((folder/'dispatch.json').read_text())
        assert dispatch['endpoint']=='https://api.openai.com/v1/decisions'
        assert dispatch['key_origin']=='du' and dispatch['experience_injection'] is False
        state=json.loads((folder/'revised-legacy-request.json').read_text())['state']
        assert not set(state)&{'reward','success','contact','object_pose','target_pose','required_rotation_world_rad','axis_feedback'}
        for a in axes:
            q=next(q for q in request['questions'] if q['name']==a)
            assert {c['value'] for c in q['choices']}=={'positive','negative','hold'}
        counts['requests']+=1
        counts['image_blocks']+=sum(x['type']=='input_image' for x in request['input'][0]['content'])
        world_samples+=len(state.get('visible_surface_samples',[]))
        if (folder/'response.json').exists():counts['responses']+=1
        if (folder/'failure.json').exists():counts['failures']+=1
    path=root/'execution.jsonl'
    if path.exists():
        for line in path.read_text().splitlines():
            row=json.loads(line);stages[str(row['stage'])]+=1
            for a in axes:axes[a][row['choices'][a]]+=1
            counts['physical_action_turns']+=1
            counts['all_six_axes_hold']+=all(row['choices'][a]=='hold' for a in axes)
            counts['gripper_close_turns']+=row['choices']['gripper']=='close'
    interrupted=(root/'control-stop.json').exists()
    evaluated=bool(result and result.get('native_evaluated',not result.get('error') and not interrupted))
    return dict(directory=str(root),result=result,native_evaluated=evaluated,development_interrupted=interrupted,counts=dict(counts),axes=axes,
        stage_action_turns=stages,visible_surface_sample_entries=world_samples,
        limitation='Choice counts are not correctness scores. Program completion does not imply native task completion. No scene pose or target error is used for this audit.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directories',nargs='+',type=Path);p.add_argument('--output',type=Path)
    a=p.parse_args();report=[audit(root) for root in a.directories]
    raw=json.dumps(report,indent=2)+'\n'
    if a.output:a.output.write_text(raw)
    print(raw)

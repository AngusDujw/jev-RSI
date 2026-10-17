"""Export one existing decision per condition and build a static evidence page."""
import argparse
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def collect(runs, output):
    output.mkdir(parents=True, exist_ok=False)
    (output/'images').mkdir()
    records = []
    for label in ('full', 'waypoint', 'raw'):
        case = runs/f'2026-10-16-libero-rgb-{label}'/'task-1144-init-5'
        folder = case/'multimodal/decision-api/0000'
        request = read(folder/'request.json')
        revised = read(folder/'revised-legacy-request.json')
        dispatch = read(folder/'dispatch.json')
        original = read(folder/'legacy-request.json')
        assert set(request) == {'model', 'input', 'questions'}
        assert request['model'] == 'gpt-6-luna'
        content = request['input'][0]['content']
        assert json.loads(content[0]['text']) == revised['state']
        assert original['state']['stage'] == 'approach'
        images = [p for p in content if p['type'] == 'input_image']
        assert len(images) == len(dispatch['camera_views']) == 2
        views = []
        for image, view in zip(images, dispatch['camera_views']):
            raw = base64.b64decode(image['image_url'].split(',', 1)[1])
            assert sha(raw) == view['sha256']
            assert Path(view['rgb_path']).read_bytes() == raw
            relative = 'images/'+sha(raw)+'.png'
            (output/relative).write_bytes(raw)
            views.append(dict(camera=view['camera'], description=view['description'],
                src=relative, sha256=sha(raw), width=view['width'], height=view['height'],
                observation_counter=view['native_observation_counter']))
        sources = {}
        for name in ('request.json', 'response.json', 'legacy-request.json',
                     'revised-legacy-request.json', 'legacy-response.json'):
            raw = (folder/name).read_bytes()
            target = output/'records'/label/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            sources[name] = dict(file=f'records/{label}/{name}', sha256=sha(raw), original=str(folder/name))
        records.append(dict(id=label, source=str(case), state=revised['state'],
            original_state=original['state'], questions=request['questions'],
            response=read(folder/'response.json'), normalized=read(folder/'legacy-response.json'),
            text_parts=[dict(part=i, text=p['text']) for i,p in enumerate(content) if p['type']=='input_text'],
            views=views, sources=sources, result=read(case/'episode/result.json'),
            robot=dispatch['measured_robot'], init=5, stage='approach', decision='0000'))
    assert all(r['robot'] == records[0]['robot'] for r in records)
    assert all(r['original_state']['translation_axes'] == records[0]['original_state']['translation_axes'] for r in records)
    write(output/'collected.json', records)
    print('COLLECTED: 3 actual requests/responses; 6 exact image blocks; identical initial robot states')


def build(evidence, casebook, template, output):
    output.mkdir(parents=True, exist_ok=False)
    for p in evidence.iterdir():
        if p.is_dir():
            shutil.copytree(p, output/p.name)
        else:
            shutil.copyfile(p, output/p.name)
    source = casebook.read_text()
    cases = json.loads(source.removeprefix('window.CASES=').strip().removesuffix(';'))
    case = next(c for c in cases if c['id'] == 1144)
    assert case['init'] == 5
    first = case['decisions'][0]
    assert first['request']['model'] == 'jev-latest'
    assert first['response']['model'].startswith('jev-')
    records = read(evidence/'collected.json')
    assert first['request']['state']['translation_axes'] == records[0]['original_state']['translation_axes']
    assert first['execution'][0]['before'] == records[0]['robot']['robot0_eef_pos']
    jev = dict(id='jev', source=case['source_run'], state=first['request']['state'],
        questions=[dict(name=name, type=q['type'], instructions=q['instructions'],
            choices=[dict(value=k, description=v) for k,v in q['criteria'].items()])
            for name,q in first['request']['questions'].items()],
        response=first['response'], normalized=first['response'], text_parts=[], views=[],
        model=first['response']['model'], init=5, stage='approach', decision='0000',
        sources={}, result=case['result'], source_request_sha256=first['request_sha256'],
        source_response_sha256=first['response_sha256'])
    for name,value in [('request.json',first['request']),('response.json',first['response'])]:
        relative=f'records/jev/{name}'
        write(output/relative,value)
        jev['sources'][name]=dict(file=relative, sha256=sha((output/relative).read_bytes()),
            original=first['source']+name,
            note='JSON values copied from the archived Jev casebook; file formatting reserialized.')
    records.insert(0,jev)
    titles = {
        'jev': ('原Jev · 纯文本', '读已计算的误差，选择运动方向。'),
        'full': ('Luna · 误差＋图像', '保留结构化反馈，加两张命名RGB。'),
        'waypoint': ('Luna · 删XYZ＋标记图', '删除XYZ反馈，用白圈和黄叉表示控制点与目标。'),
        'raw': ('Luna · 删XYZ＋原图', '删除XYZ反馈，直接给原始双相机图像。')}
    base_questions={q['name']:q for q in jev['questions']}
    for r in records:
        r['title'],r['summary']=titles[r['id']]
        r['model']=r['response']['model']
        r['sent_state_keys']=list(r['state'])
        r['removed_keys']=sorted(set(jev['state'])-set(r['state']))
        r['added_keys']=sorted(set(r['state'])-set(jev['state']))
        r['changed_questions']=[q['name'] for q in r['questions'] if q['name'] in base_questions
            and q['instructions']!=base_questions[q['name']]['instructions']]
        r['question_names']=[q['name'] for q in r['questions']]
        r['answers']=r['normalized']['answers']
        assert all(r['sources'][name]['file'] for name in ('request.json','response.json'))
    data=dict(task=1144, init=5, decision='0000', stage='approach',
        public_task=jev['state']['task'], records=records,
        audit=dict(source_casebook_sha256=sha(casebook.read_bytes()), records=4,
            image_blocks_verified=6, unique_images=len(list((output/'images').glob('*.png'))),
            identical_start_position=True, identical_frontend_xyz=True,
            model_calls=0, simulation_steps=0,
            historical_only=True, draft_motion_prompt_sent=False,
            note='One actual first decision from each historical episode; not a new experiment or success-rate comparison.'))
    for p in template.iterdir():
        if p.suffix in ('.html','.css','.js'):
            shutil.copyfile(p,output/p.name)
    (output/'data.js').write_text('window.COMPARISON='+json.dumps(data,ensure_ascii=False).replace('</','<\\/')+';\n')
    write(output/'audit.json',data['audit'])
    print(json.dumps(data['audit'],ensure_ascii=False))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--collect',action='store_true')
    p.add_argument('--runs-root',type=Path,default=Path('code/runs'))
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--evidence',type=Path)
    p.add_argument('--casebook',type=Path,default=Path('code/reports/libero-ten-workflows/data.js'))
    p.add_argument('--template',type=Path,default=Path('code/reports/libero-input-comparison'))
    a=p.parse_args()
    if a.collect:
        collect(a.runs_root.resolve(),a.output.resolve())
    else:
        build(a.evidence.resolve(),a.casebook.resolve(),a.template.resolve(),a.output.resolve())


if __name__=='__main__':
    main()

"""Summarize frozen motion-description experiments; optionally audit actual requests."""
import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
from datetime import datetime, timezone

from legacy_decisions import english
from libero_motion_multimodal import assert_no_camera_matrices, MOTION_FILE


def read(path):
    return json.loads(path.read_text())


def audit_case(case):
    counts=Counter()
    agreement=Counter()
    for folder in sorted((case/'multimodal/decision-api').glob('[0-9]*')):
        path=folder/'request.json'
        if not path.exists():
            continue
        request=read(path)
        english(request)
        assert_no_camera_matrices(request)
        content=request['input'][0]['content']
        assert content[0]['text']==MOTION_FILE.read_text()
        dispatch=read(folder/'dispatch.json')
        revised=read(folder/'revised-legacy-request.json')
        original=read(folder/'legacy-request.json')
        assert json.loads(content[1]['text'])==revised['state']
        context=json.loads(content[2]['text'])
        assert set(context)=={'camera_views','measured_robot','units','timing'}
        assert all(set(v)=={'camera','description','native_observation_counter','width','height'}
                   for v in context['camera_views'])
        assert dispatch['camera_matrices_sent'] is False
        for contract in ('phase_contract','operation_contract','stage_contract'):
            # Latest stable clarification can change pending-check wording;
            # it is identical across conditions by construction and is audited separately.
            if contract in original['state']:
                assert contract in revised['state']
        parts=[p for p in content if p['type']=='input_image']
        assert len(parts)==2
        for part,view in zip(parts,dispatch['camera_views']):
            raw=base64.b64decode(part['image_url'].split(',',1)[1])
            assert hashlib.sha256(raw).hexdigest()==view['sha256']
            assert Path(view['rgb_path']).read_bytes()==raw
            assert (view['width'],view['height'])==(768,928)
            counts['exact_image_blocks']+=1
        counts['actual_requests']+=1
        if not (folder/'legacy-response.json').exists():
            continue
        response=read(folder/'legacy-response.json')
        provider=read(folder/'response.json')
        if provider.get('model')!='gpt-6-luna':
            raise ValueError('Unexpected model')
        for answer in provider['answers']:
            assert answer['choice']==response['answers'][answer['name']]['choice']
        counts['valid_responses']+=1
        state=original['state']
        tolerance=state.get('axis_hold_tolerance_mm',state.get('hold_tolerance_m',.002)*1000)
        for axis,row in state.get('translation_axes',{}).items():
            if axis not in 'xyz' or axis not in response['answers'] or 'goal_minus_current_mm' not in row:
                continue
            error=row['goal_minus_current_mm']
            expected='hold' if abs(error)<=tolerance else 'positive' if error>0 else 'negative'
            observed=response['answers'][axis]['choice']
            agreement['all_axes']+=1
            agreement['all_agree']+=int(expected==observed)
            if expected!='hold':
                agreement['nonzero_axes']+=1
                agreement['nonzero_agree']+=int(expected==observed)
    return dict(counts=counts,nominal_axis_agreement=agreement)


def export_sample(runs,output):
    output.mkdir(parents=True,exist_ok=True)
    records=[]
    for label in ('full','marker','axes'):
        folder=runs/f'2026-10-17-libero-rgb-motion-{label}-v1/task-1144-init-5/multimodal/decision-api/0000'
        if not (folder/'response.json').exists():
            continue
        request=read(folder/'request.json');assert_no_camera_matrices(request)
        content=request['input'][0]['content'];dispatch=read(folder/'dispatch.json')
        images=[]
        for part,view in zip([x for x in content if x['type']=='input_image'],dispatch['camera_views']):
            raw=base64.b64decode(part['image_url'].split(',',1)[1])
            assert hashlib.sha256(raw).hexdigest()==view['sha256']
            filename=label+'-'+view['camera']+'.png'
            (output/filename).write_bytes(raw)
            images.append(dict(camera=view['camera'],src=filename,sha256=view['sha256']))
        shutil.copyfile(folder/'request.json',output/(label+'-actual-request.json'))
        records.append(dict(condition=label,motion_description=content[0]['text'],
            state=json.loads(content[1]['text']),context=json.loads(content[2]['text']),
            questions=request['questions'],response=read(folder/'response.json'),
            images=images,source=str(folder),download=label+'-actual-request.json'))
    (output/'sample.json').write_text(json.dumps(dict(task=1144,init=5,decision='0000',records=records),indent=2)+'\n')


def summarize_rows(rows,expected):
    per_task={};categories=Counter();total_counts=Counter();total_axes=Counter()
    for item in rows:
        categories[item['category']]+=1
        audit=item.get('audit',{})
        total_counts.update(audit.get('counts',{}))
        total_axes.update(audit.get('nominal_axis_agreement',{}))
        task=per_task.setdefault(str(item['task']),dict(completed=0,native=0,joint=0,failures=[]))
        task['completed']+=1;task['native']+=int(item['native'] is True)
        task['joint']+=int(item['joint'] is True)
        if not item['joint']:
            task['failures'].append({k:item[k] for k in ('init','stage','error','category')})
    return dict(completed=len(rows),expected=expected,
        native=sum(r['native'] is True for r in rows),joint=sum(r['joint'] is True for r in rows),
        categories=categories,per_task=per_task,episodes=rows,
        input_audit_counts=total_counts,nominal_axis_agreement=total_axes)


def collect_root(root,audit_inputs):
    specification=read(root/'campaign.json')
    if audit_inputs:
        for name,expected in specification['adapter_source_sha256'].items():
            # An explicit replacement may update queue eligibility only. All
            # inference sources must still equal the original frozen manifest.
            if name!='run_libero_campaign.py':
                assert hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()==expected,name
    rows=[]
    for folder in sorted(root.glob('task-*-init-*')):
        if not (folder/'outcome.json').exists():
            continue
        row=read(folder/'outcome.json');result=row.get('native_result') or {}
        item=dict(task=row['task'],init=row['init'],category=row['category'],
            native=row['native_success'],joint=row['joint_success'],
            decisions=row['decision_answers'],steps=result.get('native_steps'),
            stage=result.get('stage'),error=result.get('error'),source=str(folder))
        if audit_inputs:
            item['audit']=audit_case(folder)
        rows.append(item)
    return summarize_rows(rows,specification['expected_episodes'])


def combine_transport_replacements(primary,root,replacement,audit_inputs):
    original_spec=read(root/'campaign.json');new_spec=read(replacement/'campaign.json')
    assert new_spec['request_profile']==original_spec['request_profile']
    for name,expected in original_spec['adapter_source_sha256'].items():
        if name!='run_libero_campaign.py':
            assert new_spec['adapter_source_sha256'][name]==expected,name
    authorized={}
    for source in new_spec['transport_replacements']:
        key=(source['task'],source['init']);assert key not in authorized
        case=root/f'task-{key[0]}-init-{key[1]}'
        assert Path(source['source']).resolve()==case.resolve()
        assert hashlib.sha256((case/'outcome.json').read_bytes()).hexdigest()==source['outcome_sha256']
        assert read(case/'outcome.json')['category']=='transport_or_schema_failure'
        authorized[key]=source
    added=collect_root(replacement,audit_inputs)
    replacement_rows={(r['task'],r['init']):r for r in added['episodes']}
    assert set(replacement_rows)<=set(authorized)
    selected=[]
    for row in primary['episodes']:
        key=(row['task'],row['init'])
        if key in replacement_rows:
            assert row['category']=='transport_or_schema_failure'
            row={**replacement_rows[key],'replaces_interrupted_source':row['source']}
        selected.append(row)
    primary['transport_replacements']=added
    primary['effective']=summarize_rows(selected,primary['expected'])
    primary['effective']['interpretation']='Original normal outcomes plus source-linked complete episodes for explicit gateway/connection interruptions only. Original attempts remain in the primary and replacement records.'
    primary['attempted_total']=primary['completed']+added['completed']


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--runs-root',type=Path,default=Path('code/runs'))
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--audit-inputs',action='store_true')
    p.add_argument('--sample-output',type=Path)
    p.add_argument('--include-transport-replacements',action='store_true',
        help='Include only separately recorded source-linked *-v1-transport campaigns; retain originals')
    a=p.parse_args()
    summary={}
    for label in ('full','marker','axes'):
        root=a.runs_root/f'2026-10-17-libero-rgb-motion-{label}-v1'
        if not (root/'campaign.json').exists():
            continue
        summary[label]=collect_root(root,a.audit_inputs)
        replacement=root.with_name(root.name+'-transport')
        if a.include_transport_replacements and (replacement/'campaign.json').exists():
            combine_transport_replacements(summary[label],root,replacement,a.audit_inputs)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(dict(updated_at=datetime.now(timezone.utc).isoformat(),conditions=summary),indent=2)+'\n')
    if a.sample_output:
        export_sample(a.runs_root,a.sample_output)
    print(json.dumps({k:{x:v[x] for x in ('completed','native','joint','categories','input_audit_counts','nominal_axis_agreement')}
                      for k,v in summary.items()}))


if __name__=='__main__':
    main()

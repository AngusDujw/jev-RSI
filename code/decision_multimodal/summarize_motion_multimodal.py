"""Summarize frozen motion-description experiments; optionally audit actual requests."""
import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path

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


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--runs-root',type=Path,default=Path('code/runs'))
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--audit-inputs',action='store_true')
    a=p.parse_args()
    summary={}
    for label in ('full','marker','axes'):
        root=a.runs_root/f'2026-10-17-libero-rgb-motion-{label}-v1'
        if not (root/'campaign.json').exists():
            continue
        rows=[]
        per_task={}
        categories=Counter()
        total_counts=Counter()
        total_axes=Counter()
        for folder in sorted(root.glob('task-*-init-*')):
            if not (folder/'outcome.json').exists():
                continue
            row=read(folder/'outcome.json')
            categories[row['category']]+=1
            result=row.get('native_result') or {}
            item=dict(task=row['task'],init=row['init'],category=row['category'],
                native=row['native_success'],joint=row['joint_success'],
                decisions=row['decision_answers'],steps=result.get('native_steps'),
                stage=result.get('stage'),error=result.get('error'),source=str(folder))
            if a.audit_inputs:
                audit=audit_case(folder)
                item['audit']=audit
                total_counts.update(audit['counts'])
                total_axes.update(audit['nominal_axis_agreement'])
            rows.append(item)
            task=per_task.setdefault(str(row['task']),dict(completed=0,native=0,joint=0,failures=[]))
            task['completed']+=1;task['native']+=int(row['native_success'] is True)
            task['joint']+=int(row['joint_success'] is True)
            if not row['joint_success']:
                task['failures'].append(dict(init=row['init'],stage=item['stage'],error=item['error'],category=item['category']))
        summary[label]=dict(completed=len(rows),expected=30,
            native=sum(r['native'] is True for r in rows),joint=sum(r['joint'] for r in rows),
            categories=categories,per_task=per_task,episodes=rows,
            input_audit_counts=total_counts,nominal_axis_agreement=total_axes)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:{x:v[x] for x in ('completed','native','joint','categories','input_audit_counts','nominal_axis_agreement')}
                      for k,v in summary.items()}))


if __name__=='__main__':
    main()

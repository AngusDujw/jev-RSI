"""Audit actual paired RGB requests and collect completed outcomes, without inference."""
import argparse
import base64
from collections import Counter
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path

from PIL import Image
from legacy_decisions import english
from libero_gripper_pair import PairedArrowsAPI, PairedRawAPI
from run_libero_campaign import connection_interruption


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def collect(root, kind):
    spec=json.loads((root/'campaign.json').read_text())
    api_type=PairedArrowsAPI if kind=='arrows' else PairedRawAPI
    api=api_type.__new__(api_type)
    # Collection runs after the campaign: verify the actual inference contract.
    for name, sha in spec['adapter_source_sha256'].items():
        if name=='run_libero_campaign.py':
            continue
        assert hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()==sha, name
    episodes=[]; inputs={}; calls=responses=images=0; phases=Counter(); directional=Counter(); coverage=Counter()
    for case in sorted(root.glob('task-*')):
        outcome=json.loads((case/'outcome.json').read_text()) if (case/'outcome.json').is_file() else None
        if outcome is None:
            continue
        task,init=int(case.name.split('-')[1]),int(case.name.split('-')[3])
        records=[]; case_direction=Counter()
        for folder in sorted((case/'multimodal/decision-api').glob('*')):
            if not (folder/'request.json').is_file():
                continue
            payload=json.loads((folder/'request.json').read_text())
            api.validate_payload(payload)
            english(payload)
            parts=payload['input'][0]['content']
            normalized=deepcopy(payload)
            for part in normalized['input'][0]['content']:
                if part['type']=='input_image':
                    part['image_url']='IMAGE-BYTES-ONLY-DIFFERENCE'
            dispatch=json.loads((folder/'dispatch.json').read_text())
            assert dispatch['key_origin']=='du' and dispatch['requested_model']=='gpt-6-luna'
            assert dispatch['experience_injection'] is False
            assert dispatch['camera_matrices_sent'] is False
            assert dispatch['eef_coordinates_sent'] is False
            assert dispatch['numeric_tolerances_sent'] is False
            assert dispatch['target_markers'] is False
            assert dispatch['arrows_drawn']==(kind=='arrows')
            image_parts=[p for p in parts if p['type']=='input_image']
            view_hashes=[]
            for part, view in zip(image_parts,dispatch['camera_views']):
                raw=base64.b64decode(part['image_url'].split(',',1)[1])
                sha=hashlib.sha256(raw).hexdigest()
                assert sha==view['sha256']
                assert Image.open(io.BytesIO(raw)).size==(768,768)
                # The actual sent bytes must match the recorded current-frame file.
                assert Path(view['rgb_path']).read_bytes()==raw
                if kind=='arrows':
                    expected=['Y','Z'] if view['camera']=='agentview' else ['X','Y']
                    assert view['overlay_audit']['shown_axes']==expected
                    assert view['overlay_audit']['uses_target_position'] is False
                    coverage['views']+=1
                    coverage['origin_in_frame']+=int(view['overlay_audit']['origin_visible'])
                    coverage['arrows_drawn']+=sum('end_pixel' in a for a in view['overlay_audit']['axes'])
                view_hashes.append(sha)
            assert len(image_parts)==2
            assert len({v['native_observation_counter'] for v in dispatch['camera_views']})==1
            original=json.loads((folder/'legacy-request.json').read_text())
            state=original['state']
            stage=state.get('stage',state.get('phase',state.get('operation')))
            phases[str(stage)]+=1
            answered=(folder/'legacy-response.json').is_file()
            choices={}
            if answered:
                answer=json.loads((folder/'legacy-response.json').read_text())
                axes=original['state'].get('translation_axes',{})
                for axis, feedback in axes.items():
                    error=feedback.get('goal_minus_current_mm')
                    row=answer.get('answers',{}).get(axis)
                    if error is None or row is None or abs(error)<1e-9:
                        continue
                    if feedback.get('relation','').replace('_',' ')=='within tolerance':
                        continue
                    # Diagnostic only. Contact/gripper-only motion is not evaluated.
                    if str(stage).split(':')[-1] in ('grasp','release'):
                        continue
                    choice=row.get('choice')
                    if choice not in ('negative','positive','hold'):
                        continue
                    directional['outside_original_deadband_axes']+=1
                    directional['correct_sign']+=int(choice==('positive' if error>0 else 'negative'))
                    case_direction['outside_original_deadband_axes']+=1
                    case_direction['correct_sign']+=int(choice==('positive' if error>0 else 'negative'))
                choices={axis:answer.get('answers',{}).get(axis,{}).get('choice') for axis in 'xyz'}
            records.append(dict(decision=folder.name,stage=stage,answered=answered,
                observation=dispatch['camera_views'][0]['native_observation_counter'],
                nonimage_sha256=digest(normalized),images_sha256=view_hashes,
                actual_xyz_choices=choices,
                diagnostic_only_not_sent_xyz_error_mm={axis:row.get('goal_minus_current_mm')
                    for axis,row in original['state'].get('translation_axes',{}).items()}))
            calls+=1;responses+=int(answered);images+=2
        if records:
            inputs[(task,init)]=records[0]
        result=outcome.get('native_result') or {}
        episodes.append(dict(task=task,init=init,native_success=outcome['native_success'],
            program_finished=outcome['program_finished'],joint_success=outcome['joint_success'],
            category=outcome['category'],decisions=outcome['decision_answers'],
            stage=result.get('stage'),native_steps=result.get('native_steps'),
            error=result.get('error'),nominal_direction_diagnostic=dict(case_direction),request_records=records))
    per_task={str(task):dict(n=sum(e['task']==task for e in episodes),
        native=sum(e['task']==task and e['native_success'] is True for e in episodes),
        joint=sum(e['task']==task and e['joint_success'] for e in episodes))
        for task in sorted({e['task'] for e in episodes})}
    return dict(root=str(root),completed=len(episodes),
        native_successes=sum(e['native_success'] is True for e in episodes),
        joint_successes=sum(e['joint_success'] for e in episodes),
        actual_requests=calls,valid_responses=responses,actual_images=images,
        stages=dict(phases),terminal_stages=dict(Counter(str(e['stage']) for e in episodes)),
        categories=dict(Counter(e['category'] for e in episodes)),
        nominal_direction_diagnostic=dict(directional),overlay_coverage=dict(coverage),per_task=per_task,episodes=episodes),inputs


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--arrows',type=Path,required=True)
    parser.add_argument('--raw',type=Path,required=True)
    parser.add_argument('--arrows-replacement',type=Path)
    parser.add_argument('--raw-replacement',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    groups={}; starts={}; replacements={}; effective={}
    for name in ('arrows','raw'):
        groups[name],starts[name]=collect(getattr(args,name),name)
        episodes={(e['task'],e['init']):e for e in groups[name]['episodes']}
        replacement=getattr(args,name+'_replacement')
        if replacement:
            replacements[name],_=collect(replacement,name)
            spec=json.loads((replacement/'campaign.json').read_text())
            provenance={(p['task'],p['init']):p for p in spec['transport_replacements']}
            assert len(provenance)==replacements[name]['completed']
            for row in replacements[name]['episodes']:
                key=(row['task'],row['init']); origin=provenance[key]
                case=getattr(args,name)/f'task-{key[0]}-init-{key[1]}'
                assert episodes[key]['category']=='transport_or_schema_failure'
                assert hashlib.sha256((case/'outcome.json').read_bytes()).hexdigest()==origin['outcome_sha256']
                failures=list((case/'multimodal/decision-api').glob('*/failure.json'))
                assert failures and all(connection_interruption(json.loads(p.read_text())) and
                    not (p.parent/'response.json').exists() and not (p.parent/'legacy-response.json').exists()
                    for p in failures)
                row['replaces_source']=origin['source']
                episodes[key]=row
        rows=list(episodes.values())
        per_task={str(t):dict(n=sum(e['task']==t for e in rows),
            native=sum(e['task']==t and e['native_success'] is True for e in rows),
            joint=sum(e['task']==t and e['joint_success'] for e in rows)) for t in sorted({e['task'] for e in rows})}
        direction=Counter()
        for row in rows:
            direction.update(row['nominal_direction_diagnostic'])
        effective[name]=dict(completed=len(rows),native_successes=sum(e['native_success'] is True for e in rows),
            joint_successes=sum(e['joint_success'] for e in rows),
            terminal_stages=dict(Counter(str(e['stage']) for e in rows)),
            categories=dict(Counter(e['category'] for e in rows)),
            nominal_direction_diagnostic=dict(direction),
            actual_requests=sum(len(e['request_records']) for e in rows),
            valid_responses=sum(sum(r['answered'] for r in e['request_records']) for e in rows),
            per_task=per_task,episodes=rows)
    keys=sorted(set(starts['arrows'])&set(starts['raw']))
    paired=[dict(task=t,init=i,
        initial_nonimage_input_identical=starts['arrows'][(t,i)]['nonimage_sha256']==starts['raw'][(t,i)]['nonimage_sha256']) for t,i in keys]
    result=dict(groups=groups,replacements=replacements,effective=effective,paired_initial_inputs=paired,
        experience_injection=False,interpretation='Actual recorded attempts; normal failures retained. Native and joint completion are separate. Not pure RGB.')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:{x:v for x,v in g.items() if x not in ('episodes','per_task')} for k,g in groups.items()}))


if __name__=='__main__':
    main()

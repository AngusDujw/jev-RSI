"""Read-only audit of actual rotation-role requests, choices and native outcomes."""
import argparse
import json
from pathlib import Path
import statistics

from legacy_decisions import english


def audit(root):
    rows=[]
    for folder in sorted(root.glob('task-*-init-*')):
        counts={'visual_requests':0,'motor_requests':0,'image_blocks':0,'responses':0,'api_failures':0}
        for directory in (folder/'episode/decision-api').glob('[0-9]*'):
            path=directory/'request.json'
            if not path.is_file():continue
            request=json.loads(path.read_text());english(request)
            dispatch=json.loads((directory/'dispatch.json').read_text())
            assert dispatch['key_origin']=='du' and dispatch['experience_injection'] is False
            assert request['model']=='gpt-6-luna'
            parts=request['input'][0]['content']
            images=[p for p in parts if p['type']=='input_image']
            if dispatch['profile'] in ('rotation_visual_candidates_v1','rotation_visual_dials_v2'):
                assert len(images)==3
                state=json.loads(parts[0]['text'])
                assert set(state)=={'task','stage','task_plan','goal','source'}
                if dispatch['profile']=='rotation_visual_candidates_v1':
                    assert len(request['questions'])==1 and request['questions'][0]['name']=='rotation_action'
                else:
                    assert {q['name'] for q in request['questions']}<=set(('rx','ry','rz'))
                    assert dispatch['algorithm_derived_signed_angular_residual_visualized'] is True
                counts['visual_requests']+=1
            else:
                assert dispatch['profile']=='rotation_numerical_motor_v1' and not images
                counts['motor_requests']+=1
            counts['image_blocks']+=len(images)
            counts['responses']+=(directory/'response.json').is_file()
            counts['api_failures']+=(directory/'failure.json').is_file()
        events_path=folder/'episode/events.jsonl'
        events=[json.loads(x) for x in events_path.read_text().splitlines()] if events_path.exists() else []
        merges=[x for x in events if x.get('kind')=='rotation_role_merge']
        visual=[x for x in merges if x['visual_call']]
        correct=wrong=hold=0
        for x in visual:
            if 'selected_visual_actions' in x:
                choices=x['selected_visual_actions'].items()
            else:
                choice=x['selected_visual_action']
                if choice=='hold':hold+=1;continue
                choices=[choice.split('_')]
            for axis,direction in choices:
                error=x['diagnostic_only_error_rad'][('rx','ry','rz').index(axis)]
                good=(error>0 and direction=='positive') or (error<0 and direction=='negative')
                correct+=good;wrong+=not good
        progress=[]
        for before,after in zip(merges,merges[1:]):
            if before['visual_call'] and before['stage']==after['stage']:
                norm=lambda x:sum(v*v for v in x['diagnostic_only_error_rad'])**.5
                progress.append(norm(before)-norm(after))
        result_path=folder/'outcome.json'
        result=json.loads(result_path.read_text()) if result_path.exists() else None
        setup_path=folder/'multimodal/rotation-setup.json'
        setup=json.loads(setup_path.read_text()) if setup_path.exists() else None
        rows.append(dict(case=folder.name,**counts,visual_choices=len(visual),
            residual_sign_consistent=correct,residual_sign_opposed=wrong,visual_hold=hold,
            same_stage_angular_progress_samples=len(progress),
            same_stage_positive_progress=sum(p>0 for p in progress),
            same_stage_net_angular_progress_rad=sum(progress),
            same_stage_median_angular_progress_rad=statistics.median(progress) if progress else None,
            setup=setup,result=result))
    return dict(campaign=str(root),episodes=rows,
        limitation='Angular diagnostics derive from permitted targets/robot state. Sign agreement is not optimality, native success or proof that camera RGB is necessary.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--output',type=Path)
    args=p.parse_args();report=audit(args.root);text=json.dumps(report,indent=2)+'\n'
    if args.output:args.output.write_text(text)
    print(text)

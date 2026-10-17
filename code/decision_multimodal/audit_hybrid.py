"""Audit archived hybrid role inputs and contribution, without model calls."""
import argparse
import json
from pathlib import Path

from legacy_decisions import english


def load(path):
    return json.loads(path.read_text())


def audit(root):
    rows=[]
    for case in sorted(root.glob('task-*-init-*')):
        episode=case/'episode'; counts={'visual':0,'motor':0,'images':0}
        for directory in sorted((episode/'decision-api').glob('[0-9]*')):
            path=directory/'request.json'
            if not path.exists():continue
            request=load(path);english(request)
            assert request['model']=='gpt-6-luna'
            dispatch=load(directory/'dispatch.json')
            assert dispatch['key_origin']=='du' and dispatch['experience_injection'] is False
            content=request['input'][0]['content']
            images=[p for p in content if p['type']=='input_image']
            state=json.loads(next(p['text'] for p in content if p['type']=='input_text' and p['text'].startswith('{')))
            names={q['name'] for q in request['questions']}
            if dispatch['profile']=='hybrid_visual_relation':
                assert names=={'bowl_location'} and len(images)==1
                assert set(state)=={'source','task','image'}
                assert (directory/'execution-map.json').is_file()
                assert images[0]['image_url'].startswith('data:image/png;base64,')
                counts['visual']+=1
            else:
                assert dispatch['profile']=='hybrid_text_motor' and not images
                axes=state['axis_feedback']
                assert set(axes)==(names & set('xyz'))
                if state['hybrid_substage']=='visual_coarse_x':assert 'x' not in axes and 'x' not in names
                assert not any(k in state for k in ('translation_axes','hold_tolerance_m','arrival_tolerance_m','eef'))
                counts['motor']+=1
            counts['images']+=len(images)
        events=[json.loads(line) for line in (episode/'events.jsonl').read_text().splitlines()]
        merges=[e for e in events if e.get('kind')=='hybrid_role_merge']
        coarse=[e for e in merges if e['x_source']=='visual_relation']
        fine=next((e for e in merges if e['x_source']=='numerical_feedback'),None)
        initial=coarse[0]['x_reference_diagnostic_only_mm'] if coarse else None
        at_fine=fine['x_reference_diagnostic_only_mm'] if fine else None
        correct=sum((e['returned_x']['choice']=='positive' and e['x_reference_diagnostic_only_mm']>0) or
                    (e['returned_x']['choice']=='negative' and e['x_reference_diagnostic_only_mm']<0) for e in coarse)
        row=dict(case=case.name,**counts,visual_actions=len(coarse),
            visual_sign_consistent=correct,initial_x_mm=initial,fine_entry_x_mm=at_fine,
            coarse_abs_x_reduction_mm=abs(initial)-abs(at_fine) if initial is not None and at_fine is not None else None,
            result=load(case/'outcome.json') if (case/'outcome.json').exists() else None)
        rows.append(row)
    return dict(campaign=str(root),episodes=rows,
        interpretation='Hybrid, not pure RGB. Residuals in this audit are evaluator diagnostics, never visual-role inputs.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args();report=audit(args.root)
    text=json.dumps(report,indent=2)+'\n'
    if args.output:args.output.write_text(text)
    print(text)

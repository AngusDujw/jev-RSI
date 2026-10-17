"""Read-only diagnosis of archived actor choices and measured robot branches."""
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics


def read(path):
    return json.loads(path.read_text())


def percentile(values, fraction):
    values=sorted(values)
    return values[round((len(values)-1)*fraction)] if values else None


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--audit',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    audit=read(args.audit); result={}
    for name,group in audit['effective'].items():
        primary=Path(audit['groups'][name]['root'])
        replacement=audit['replacements'].get(name)
        replacement_keys={(e['task'],e['init']) for e in replacement['episodes']} if replacement else set()
        counters=Counter(); probabilities=[]; margins=[]; confidences=[]; examples={}
        for episode in group['episodes']:
            key=(episode['task'],episode['init'])
            root=Path(replacement['root']) if key in replacement_keys else primary
            case=root/f'task-{key[0]}-init-{key[1]}'
            for record in episode['request_records']:
                folder=case/'multimodal/decision-api'/record['decision']
                original=read(folder/'legacy-request.json')
                response=read(folder/'legacy-response.json')
                state=original['state']
                stage=state.get('stage',state.get('phase',state.get('operation',''))).split(':')[-1]
                if stage in ('grasp','release'):
                    continue
                for axis,feedback in state.get('translation_axes',{}).items():
                    row=response.get('answers',{}).get(axis)
                    error=feedback.get('goal_minus_current_mm')
                    if row is None or error is None or abs(error)<1e-9 or feedback.get('relation','').replace('_',' ')=='within tolerance':
                        continue
                    choice=row['choice']; distribution=row['probabilities']
                    ordered=sorted(distribution.values(),reverse=True)
                    selected=distribution[choice];margin=ordered[0]-ordered[1]
                    correct=choice==('positive' if error>0 else 'negative')
                    counters['axes']+=1; counters['correct']+=correct
                    counters['selected_probability_below_half']+=selected<.5
                    counters['top_two_probability_gap_below_point_one']+=margin<.1
                    counters['choice_not_unique_argmax']+=selected<ordered[0]-1e-9
                    counters['hold_outside_original_deadband']+=choice=='hold'
                    probabilities.append(selected); margins.append(margin);confidences.append(row['confidence'])
            if key==(1144,5):
                branches=[json.loads(line) for line in (case/'episode/branches.jsonl').read_text().splitlines()]
                steps=[]; aligned=opposed=0
                for branch in branches:
                    if not all(k in branch for k in ('delta','before','after','decision_id')):
                        continue
                    index=int(branch['decision_id'].split('-')[-1])
                    folder=case/'multimodal/decision-api'/f'{index:04d}'
                    original=read(folder/'legacy-request.json');answer=read(folder/'legacy-response.json')
                    actual=[(a-b)*1000 for a,b in zip(branch['after'],branch['before'])]
                    delta=[x*1000 for x in branch['delta']]
                    for command,motion in zip(delta,actual):
                        if abs(command)>=2 and abs(motion)>=1:
                            aligned+=command*motion>0;opposed+=command*motion<0
                    error={a:v['goal_minus_current_mm'] for a,v in original['state']['translation_axes'].items()}
                    steps.append(dict(decision=index,stage=branch['stage'],
                        diagnostic_only_not_sent_error_mm=error,
                        choices={a:answer['answers'][a]['choice'] for a in 'xyz'},
                        confidence={a:answer['answers'][a]['confidence'] for a in 'xyz'},
                        selected_probabilities={a:answer['answers'][a]['probabilities'][answer['answers'][a]['choice']] for a in 'xyz'},
                        command_increment_mm=delta,measured_displacement_mm=actual,
                        progress_mm=branch['progress_m']*1000))
                state=read(case/'multimodal/decision-api'/f'{steps[-1]["decision"]:04d}'/'revised-legacy-request.json')['state']
                examples['1144-init5']=dict(decisions=len(steps),
                    command_motion_sign_same=aligned,command_motion_sign_opposed=opposed,
                    movement_sign_filter='abs commanded increment >=2mm; abs measured displacement >=1mm; not exact tracking proof',
                    retained_last_history=state.get('recent_actions'),
                    positive_progress=sum(s['progress_mm']>0 for s in steps),
                    negative_progress=sum(s['progress_mm']<0 for s in steps),steps=steps)
        result[name]=dict(axis_diagnostic=dict(counters),
            median_selected_probability=statistics.median(probabilities),
            median_reported_confidence=statistics.median(confidences),
            median_top_two_probability_gap=statistics.median(margins),
            selected_probability_p10=percentile(probabilities,.1),
            selected_probability_p90=percentile(probabilities,.9),examples=examples)
    output=dict(model_calls=0,native_steps=0,source_audit=str(args.audit),groups=result,
        interpretation='Existing camera-derived reference only, not privileged object truth. Probability descriptions are descriptive, not calibrated correctness guarantees. No inference or controller change.')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps({name:{k:v for k,v in group.items() if k!='examples'} for name,group in result.items()}))


if __name__=='__main__':
    main()

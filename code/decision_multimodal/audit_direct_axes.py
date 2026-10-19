"""Read-only audit of genuine RGB direction rollouts and actual provider bodies."""
import argparse
from collections import Counter
import json
from pathlib import Path
from legacy_decisions import english


def audit(root):
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

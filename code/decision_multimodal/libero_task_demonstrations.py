"""RoboDawn-style task examples from archived actual RGB and executed commands."""
import io
import json
from pathlib import Path
import re
from PIL import Image,ImageDraw


def build_task_examples(episode,output):
    from libero_direct_axes import image_part
    output.mkdir()
    branches=[json.loads(x) for x in (episode/'branches.jsonl').read_text().splitlines()]
    snapshots=[];pattern=re.compile(r'^(\d+)-(.+)-agentview\.png$')
    for path in episode.glob('*-agentview.png'):
        m=pattern.match(path.name)
        if m:snapshots.append((int(m[1]),m[2].split(':')[-1],path))
    snapshots.sort();parts=[];previous=episode/'agentview.png';provenance=[]
    names=('approach','contact','grasp','turn','release','verify') if any(s[1]=='turn' for s in snapshots) else ('approach','grasp','lift','orient_receiver','lower','release')
    for name in names:
        group=[s for s in snapshots if s[1]==name]
        if not group:continue
        last=group[-1];first=group[0]
        before=previous if previous.is_file() else first[2]
        after=last[2];previous=after
        card=Image.new('RGB',(1024,546),'#11212b');d=ImageDraw.Draw(card)
        d.text((12,10),'ARCHIVED TASK EXAMPLE: '+name+' | BEFORE (left), AFTER (right)',fill='white')
        card.paste(Image.open(before).convert('RGB').resize((512,512)),(0,34))
        card.paste(Image.open(after).convert('RGB').resize((512,512)),(512,34))
        b=io.BytesIO();card.save(b,format='PNG');path=output/(name+'.png');path.write_bytes(b.getvalue())
        rows=[r for r in branches if str(r['stage']).split(':')[-1]==name]
        runs=[]
        for row in rows:
            command=dict(xyz=['positive' if v>1e-8 else 'negative' if v< -1e-8 else 'hold' for v in row.get('delta',[0,0,0])],
                gripper='close' if row.get('executed_gripper')==1 else 'open')
            if 'rotation_delta' in row:
                command['roll_pitch_yaw']=['positive' if v>1e-8 else 'negative' if v< -1e-8 else 'hold' for v in row['rotation_delta']]
            elif 'rotation_signs' in row:
                command['roll_pitch_yaw']=['positive' if v>0 else 'negative' if v<0 else 'hold' for v in row['rotation_signs']]
            if runs and runs[-1]['command']==command:runs[-1]['repeat']+=1
            else:runs.append(dict(command=command,repeat=1))
        text=('Another recorded episode illustrates the physical relationship for phase '+name+'. '
            'Study how the actual fingers and object change; transfer the strategy, not a fixed coordinate or direction sequence. '
            'These are historical example images, never the CURRENT scene. Executed directions in temporal order: '+json.dumps(runs)+'. '
            'No target pose, residual, rendered angle answer, contact flag or evaluator label is included.')
        parts.extend([dict(type='input_text',text=text),image_part(b.getvalue())])
        provenance.append(dict(phase=name,before=str(before),after=str(after),commands=runs))
    (output/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    return parts

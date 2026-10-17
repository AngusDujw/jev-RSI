"""Export original model calls and complete policy snapshot replays, read-only."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


def load(path):return json.loads(path.read_text())


def export_call(directory,output,name):
    output.mkdir(exist_ok=True)
    request=load(directory/'request.json');response=load(directory/'response.json')
    shutil.copyfile(directory/'request.json',output/(name+'-request.raw.json'))
    shutil.copyfile(directory/'response.json',output/(name+'-response.raw.json'))
    displayed=deepcopy(request);images=[]
    for content in displayed['input']:
        for part in content['content']:
            if part['type']!='input_image':continue
            raw=base64.b64decode(part['image_url'].split(',',1)[1])
            file=name+'-image-'+str(len(images))+'.png';(output/file).write_bytes(raw)
            images.append(dict(file=file,sha256=hashlib.sha256(raw).hexdigest()))
            part['image_url']='[inline PNG base64 displayed as '+file+']'
    return dict(source_directory=str(directory),request=displayed,response=response,
        raw_request=name+'-request.raw.json',raw_response=name+'-response.raw.json',images=images)


def video(episode,output):
    from PIL import Image,ImageDraw,ImageFont
    pattern=re.compile(r'^(\d+)-(.+)-agentview\.png$')
    pairs=[]
    if (episode/'agentview.png').is_file():pairs.append((0,'initial after setup',episode/'agentview.png',episode/'robot0_eye_in_hand.png'))
    for p in episode.glob('*-agentview.png'):
        match=pattern.match(p.name)
        wrist=p.with_name(p.name.replace('-agentview.png','-robot0_eye_in_hand.png'))
        if match:pairs.append((int(match[1]),match[2],p,wrist if wrist.is_file() else None))
    pairs.sort(key=lambda row:row[0])
    assert len(pairs)>5
    branches={r['native_steps']:r for r in map(json.loads,(episode/'branches.jsonl').read_text().splitlines())}
    path=output/'policy-replay.mp4'
    command=['ffmpeg','-y','-f','rawvideo','-pixel_format','rgb24','-video_size','1280x720',
        '-framerate','8','-i','pipe:0','-an','-c:v','libx264','-threads','2','-preset','fast',
        '-crf','23','-pix_fmt','yuv420p','-movflags','+faststart',str(path)]
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',18)
    with (output/'video-encode.log').open('w') as log:
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log,stdout=log)
        try:
            for step,stage,external,wrist in pairs:
                frame=Image.new('RGB',(1280,720),'#13262d');draw=ImageDraw.Draw(frame)
                draw.text((15,7),episode.parent.name+' | policy step '+str(step)+' | '+stage,fill='white',font=font)
                row=branches.get(step,{})
                draw.text((15,34),'Rotation signs '+str(row.get('rotation_signs',row.get('rotation_delta','initial')))+
                    ' | edge '+str(row.get('selected_transition','initial')),fill='#75e3cd',font=font)
                draw.text((15,59),'EXTERNAL RGB                                      WRIST RGB | snapshot replay, not real-time video',fill='#b8ccca',font=font)
                frame.paste(Image.open(external).convert('RGB').resize((640,640)),(0,80))
                if wrist is not None:
                    frame.paste(Image.open(wrist).convert('RGB').resize((640,640)),(640,80))
                else:
                    draw.text((685,300),'No wrist snapshot recorded at this policy step.',fill='white',font=font)
                    draw.text((685,335),'Actual wrist inputs for visual calls are archived separately.',fill='#b8ccca',font=font)
                process.stdin.write(frame.tobytes())
        finally:process.stdin.close()
        if process.wait():raise RuntimeError('Video encoding failed; log preserved')
    return dict(file=path.name,frames=len(pairs),fps=8,
        external_only_frames=sum(wrist is None for _,_,_,wrist in pairs),
        scope='All saved policy snapshots after setup/settling; not every physics frame or wall-clock playback',
        sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def export_case(case,output):
    out=output/case.name;out.mkdir(exist_ok=True)
    episode=case/'episode';visual=[];motors=[]
    for directory in sorted((episode/'decision-api').glob('[0-9]*')):
        if not (directory/'response.json').is_file():continue
        dispatch=load(directory/'dispatch.json')
        if dispatch['profile']=='rotation_visual_dials_v2':visual.append(directory)
        elif dispatch['profile']=='rotation_numerical_motor_v1':motors.append(directory)
    assert visual and motors
    fine=next((p for p in motors if any(.03<abs(v['goal_minus_current_rad'])<.12 for v in
        load(p/'revised-legacy-request.json')['state']['rotation_feedback'].values())),motors[0])
    branches=[json.loads(x) for x in (episode/'branches.jsonl').read_text().splitlines()]
    stages=[]
    for branch in branches:
        if not stages or stages[-1]!=branch['stage']:stages.append(branch['stage'])
    examples=dict(visual=export_call(visual[0],out,'visual'),motor=export_call(fine,out,'motor'))
    receiver=next((p for p in visual if load(p/'legacy-request.json')['state']['stage']=='orient_receiver'),None)
    if receiver:examples['receiver']=export_call(receiver,out,'receiver')
    return dict(case=case.name,outcome=load(case/'outcome.json'),stages=stages,
        video=video(episode,out),examples=examples)


def main():
    p=argparse.ArgumentParser();p.add_argument('campaign',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(exist_ok=True,parents=True)
    selected=[]
    for task in (1383,1458,1335):
        cases=sorted(args.campaign.glob(f'task-{task}-init-*'))
        assert cases and all((c/'outcome.json').is_file() for c in cases)
        selected.append(cases[0])
    with ThreadPoolExecutor(max_workers=3) as pool:
        examples=list(pool.map(lambda case:export_case(case,args.output),selected))
    data=dict(audit=load(args.campaign/'rotation-audit-final.json'),examples=examples,
        source_commit=load(args.campaign/'campaign.json'),
        interpretation='Signed angular information is algorithm-derived and rendered. This is not raw-RGB orientation inference.')
    (args.output/'evidence.json').write_text(json.dumps(data,indent=2)+'\n')
    print(json.dumps(dict(output=str(args.output),examples=[x['case'] for x in examples])))


if __name__=='__main__':main()

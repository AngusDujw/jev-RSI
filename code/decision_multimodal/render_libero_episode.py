"""Render an existing LIBERO episode and exact actor images; no model/env calls."""
import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import textwrap

from PIL import Image, ImageDraw, ImageFont


def read(path):
    return json.loads(path.read_text())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def font(size):
    for path in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                 '/usr/share/fonts/truetype/freefont/FreeSans.ttf'):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise RuntimeError('An existing readable TrueType font is required')


def encode(path, frames, rate, height, log):
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'warning', '-nostdin',
        '-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', f'1536x{height}',
        '-framerate', rate, '-i', 'pipe:0', '-an', '-vf', 'fps=24',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-threads', '4',
        '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(path)]
    with log.open('w') as errors:
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors)
        try:
            for frame in frames:
                if frame.size != (1536, height):
                    raise ValueError('Wrong video frame dimensions')
                child.stdin.write(frame.convert('RGB').tobytes())
            child.stdin.close()
            if child.wait() != 0:
                raise RuntimeError('Video encoder failed; see '+str(log))
        except BaseException:
            if child.poll() is None:
                child.terminate()
                child.wait()
            raise
    return command


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    case, output = args.case.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    result = read(case/'episode/result.json')
    manifest = read(case/'manifest.json')
    branches = [json.loads(s) for s in (case/'episode/branches.jsonl').read_text().splitlines()]
    branches = {b['decision_id']: b for b in branches}
    items = []
    snapshots = []
    for directory in sorted((case/'multimodal/decision-api').glob('[0-9]*')):
        payload = read(directory/'request.json')
        dispatch = read(directory/'dispatch.json')
        revised = read(directory/'revised-legacy-request.json')
        original = read(directory/'legacy-request.json')
        response = read(directory/'response.json')
        normalized = read(directory/'legacy-response.json')
        content = payload['input'][0]['content']
        assert json.loads(content[0]['text']) == revised['state']
        assert 'translation_axes' not in revised['state']
        images = [p for p in content if p['type'] == 'input_image']
        assert len(images) == 2
        for part, view in zip(images, dispatch['camera_views']):
            raw = base64.b64decode(part['image_url'].split(',',1)[1])
            assert sha(raw) == view['sha256']
            assert Path(view['rgb_path']).read_bytes() == raw
            assert Image.open(Path(view['rgb_path'])).size == (768,768)
        for answer in response['answers']:
            assert answer['choice'] == normalized['answers'][answer['name']]['choice']
        item = dict(id=directory.name, payload=payload, dispatch=dispatch,
                    revised=revised, original=original, response=response,
                    normalized=normalized, source=str(directory))
        items.append(item)
        display_parts = []
        image_index = 0
        for part in content:
            if part['type'] == 'input_image':
                view = dispatch['camera_views'][image_index]
                display_parts.append(dict(type='input_image', detail=part.get('detail'),
                    exact_image_file=view['rgb_path'], sha256=view['sha256']))
                image_index += 1
            else:
                display_parts.append(part)
        snapshots.append(dict(decision=directory.name, source=str(directory),
            request_sha256=sha((directory/'request.json').read_bytes()),
            input_parts_exact_text_images_externalized=display_parts,
            questions=payload['questions'], actual_response=response,
            executed_branch_OFFLINE_NOT_ACTOR_INPUT=branches['decision-'+directory.name]))
    assert len(items) == result['jev_calls']
    first_counter = items[0]['dispatch']['camera_views'][0]['native_observation_counter']
    for i,item in enumerate(items):
        assert item['dispatch']['camera_views'][0]['native_observation_counter']-first_counter == i*3
    first = items[0]
    for view in first['dispatch']['camera_views']:
        shutil.copyfile(view['rgb_path'], output/('first_input_'+view['camera']+'.png'))
    text = ['ACTUAL REQUEST TEXT / IMAGE REFERENCES / QUESTIONS / RESPONSE',
            'Export only: headings below were not sent to the actor. Image bytes are in the attached PNGs.',
            'No separate system/developer message was present in this saved request.',
            'MODEL: '+first['payload']['model']]
    for i,part in enumerate(first['payload']['input'][0]['content']):
        if part['type'] == 'input_text':
            text += [f'\nINPUT TEXT PART {i} (exact string):', part['text']]
        else:
            text += [f'\nINPUT IMAGE PART {i}: exact PNG, not a reconstructed overlay.']
    text += ['\nQUESTION DEFINITIONS (JSON values unchanged):',
             json.dumps(first['payload']['questions'], indent=2),
             '\nACTUAL PROVIDER RESPONSE:', json.dumps(first['response'], indent=2)]
    (output/'first_actual_prompt_and_response.txt').write_text('\n'.join(text)+'\n')
    with (output/'all_45_actual_inputs_outputs.jsonl').open('w') as handle:
        for snapshot in snapshots:
            handle.write(json.dumps(snapshot)+'\n')
    f20, f24, f30 = font(20), font(24), font(30)

    def base_frame(item, raw=False, final=False):
        height = 864 if raw else 1200
        frame = Image.new('RGB',(1536,height),'#111827')
        draw = ImageDraw.Draw(frame)
        step = item['dispatch']['camera_views'][0]['native_observation_counter']-first_counter
        if final:
            title = f'FINAL RAW OBSERVATION | native step {result["native_steps"]} | no new actor call'
        else:
            title = f'Goal {manifest["task_id"]} / init {manifest["init_index"]} | decision {int(item["id"])+1}/{len(items)} | native step {step}'
        draw.text((18,8 if raw else 12),title,font=f24 if raw else f30,fill='white')
        draw.text((18,38 if raw else 54),'Unmodified saved RGB' if raw or final else
            'EXACT actor-input images | white circle = robot reference | yellow cross = active waypoint',font=f20 if raw else f24,fill='#facc15')
        for j,view in enumerate(item['dispatch']['camera_views']):
            draw.text((18+j*768,91 if not raw else 66),view['camera']+(' / fixed' if j==0 else ' / moving wrist'),font=f20,fill='white')
            if final:
                paths = sorted((case/'episode').glob(f'{result["native_steps"]:04d}-*-{view["camera"]}.png'))
                if len(paths) != 1:
                    raise ValueError('Final saved image missing or ambiguous')
                path = paths[0]
            else:
                path = Path(view['original_rgb_path'] if raw else view['rgb_path'])
            frame.paste(Image.open(path).convert('RGB'),(j*768,96 if raw else 120))
        if raw:
            return frame
        draw.rectangle((0,900,1536,1200),fill='#111827')
        if final:
            lines = [('Native success: '+str(result['success'])+' | program finished: '+str(result['program_finished']),'#f87171'),
                ('Termination: '+result['error'],'white'),
                ('All45 decisions are included. No frames were synthesized between recorded observations.','white'),
                ('Final panels are saved raw RGB, NOT images sent to another actor call.','#facc15')]
            for i,(line,color) in enumerate(lines):
                draw.text((18,918+i*52),line,font=f24,fill=color)
            return frame
        answers = item['normalized']['answers']
        signs = ' | '.join(a.upper()+': '+answers[a]['choice']+f' (conf {answers[a]["confidence"]:.2f})' for a in 'xyz')
        draw.text((18,912),'ACTUAL MODEL OUTPUT: '+signs,font=f24,fill='#93c5fd')
        draw.text((18,952),'Gripper: '+answers['gripper']['choice']+' | transition: '+answers['transition']['choice']+
                  ' | stage: '+item['revised']['state']['stage'],font=f24,fill='white')
        goal = item['revised']['state']['current_stage_semantic_goal']
        for i,line in enumerate(textwrap.wrap('ACTOR STAGE GOAL: '+goal,110)):
            draw.text((18,992+i*30),line,font=f24,fill='white')
        axes = item['original']['state']['translation_axes']
        errors = ' / '.join(a.upper()+f' {axes[a]["goal_minus_current_mm"]:+.2f}' for a in 'xyz')
        draw.text((18,1074),'OFFLINE AUDIT ONLY - NOT SENT: goal minus current (mm): '+errors,font=f24,fill='#fda4af')
        draw.text((18,1112),'Replay: 1.5 seconds per decision; API waiting time omitted. Original episode wall time: '
                  +f'{read(case/"outcome.json")["seconds"]:.1f}s.',font=f20,fill='#cbd5e1')
        flags = item['dispatch']['camera_views']
        draw.text((18,1154),'Target marker in image: fixed='+str(flags[0]['target_marker_visible'])+
                  ', wrist='+str(flags[1]['target_marker_visible'])+' | Missing markers were not clamped.',font=f20,fill='#cbd5e1')
        return frame

    preview = base_frame(first)
    preview.save(output/'first_decision_review.png')
    base_frame(items[-1]).save(output/'last_decision_review.png')

    def reviews():
        yield preview
        yield preview
        for item in items:
            yield base_frame(item)
        for _ in range(3):
            yield base_frame(items[-1],final=True)

    def raws():
        for item in items:
            yield base_frame(item,raw=True)
        yield base_frame(items[-1],raw=True,final=True)

    commands = [encode(output/'episode_with_actor_inputs.mp4',reviews(),'2/3',1200,output/'review-encode.log'),
                encode(output/'raw_episode.mp4',raws(),'6',864,output/'raw-encode.log')]
    counts = {a:dict(Counter(i['normalized']['answers'][a]['choice'] for i in items)) for a in 'xyz'}
    audit = dict(source_case=str(case), model=first['payload']['model'], decisions=len(items),
        native_result=result, image_blocks_byte_verified=len(items)*2, raw_answer_mapping_verified=True,
        source_request_files_sha256=[s['request_sha256'] for s in snapshots],
        stage_counts=dict(Counter(i['revised']['state']['stage'] for i in items)),
        axis_choices=counts, first_error_OFFLINE_ONLY=first['original']['state']['translation_axes'],
        last_error_OFFLINE_ONLY=items[-1]['original']['state']['translation_axes'],
        terminal_raw_native_step=result['native_steps'], snapshot_video_not_continuous_recording=True,
        no_new_robot_or_model_calls=True, encode_commands=commands)
    for path in output.glob('*.mp4'):
        probe = subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],text=True)
        audit[path.name] = json.loads(probe)
    (output/'audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    print(json.dumps(dict(output=str(output), decisions=len(items), verified_image_blocks=len(items)*2,
        axis_choices=counts, native_result=result)),flush=True)


if __name__ == '__main__':
    main()

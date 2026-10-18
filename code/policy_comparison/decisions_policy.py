"""OpenAI Decisions categorical outputs over official GPT-only observations."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time

import numpy as np
from scipy.spatial.transform import Rotation

from hybrid_rollout.robodojo.robodojo_server.gpt_only_client import GPTOnlyTools
from hybrid_rollout.robodojo.skill.run import SKILL_ROOT, content_items
from hybrid_rollout.robodojo.settings import DEFAULT_CODEX_IMAGE_MAX_EDGE

ENDPOINT = 'https://api.openai.com/v1/decisions'
MODEL = 'gpt-6-luna'
TCP_OFFSET = np.array([.15007, 0., 0.])


def questions():
    result = []
    for arm in ('left', 'right'):
        for axis in ('x', 'y', 'z', 'yaw', 'pitch', 'roll'):
            meaning = (f'World {axis.upper()} translation of the fingertip TCP by 0.02 meters'
                if axis in 'xyz' else
                f'World {dict(yaw="Z",pitch="X",roll="Y")[axis]} rotation by 0.10 radians about the fingertip TCP')
            result.append(dict(type='choice', name=f'{arm}_{axis}', instructions=(
                f'Select {arm} arm {axis} direction toward the original task goal. {meaning}. '
                'TCP is the center between the gripping faces. '
                'For this arm at most one of yaw, pitch and roll may be non-hold; translation may accompany it. '
                'Both arms may move simultaneously. Use the original observations and same-episode context.'),
                choices=[dict(value=v, description=d) for v,d in (
                    ('negative','Apply the negative increment'),('hold','Apply no increment'),
                    ('positive','Apply the positive increment'))]))
        result.append(dict(type='choice', name=f'{arm}_gripper',
            instructions=f'Select the {arm} gripper command for the original task goal.',
            choices=[dict(value=v,description=d) for v,d in (
                ('keep','Retain the last gripper command'),('open','Open the gripper'),
                ('close','Close the gripper'))]))
    return result


def action(answers, packet, last_gripper):
    targets = {}
    sign = dict(negative=-1., hold=0., positive=1.)
    for arm in ('left','right'):
        rotations = [axis for axis in ('yaw','pitch','roll') if answers[f'{arm}_{axis}'] != 'hold']
        if len(rotations) > 1:
            raise ValueError(f'{arm}: multiple rotations; reject unchanged output without resampling')
        current = packet['current_eef'][arm]
        old = Rotation.from_quat(np.roll(current['quaternion_wxyz'], -1))
        new = old
        if rotations:
            axis = rotations[0]
            vector = np.zeros(3)
            vector[dict(yaw=2,pitch=0,roll=1)[axis]] = .10 * sign[answers[f'{arm}_{axis}']]
            new = Rotation.from_rotvec(vector) * old
        tcp = np.array(current['position']) + old.apply(TCP_OFFSET)
        tcp += .02 * np.array([sign[answers[f'{arm}_{axis}']] for axis in 'xyz'])
        gripper = answers[f'{arm}_gripper']
        if gripper != 'keep':
            last_gripper[arm] = gripper == 'close'
        targets[arm] = dict(position=(tcp-new.apply(TCP_OFFSET)).tolist(),
            quaternion_wxyz=np.roll(new.as_quat(),1).tolist(),gripper_closed=last_gripper[arm])
    return dict(request_id=packet['request_id'], mode='eef', steps=5,
        reason='Execute the original task policy categorical choices from current RGB and same-episode observations.',
        target=targets)


def load_key():
    # This exact previously-authorized du key is used for Decisions only.
    remote = '/root/yekangjie/project/jev_rsi/.worktrees/robodojo-planner-advancer-20261018/.private/du-openai-direct.key'
    result = subprocess.run(['ssh','-o','BatchMode=yes','--','company-server-2',
        'cat '+remote],capture_output=True,check=True,timeout=30)
    key = result.stdout.decode().strip()
    if not key.startswith('sk-'):
        raise ValueError('Invalid authorized OpenAI key format')
    return key


def call(body, key, folder):
    folder.mkdir(parents=True,exist_ok=False)
    # Save reconstructible evidence without multiplying all prior image binaries.
    redacted = json.loads(json.dumps(body))
    for message in redacted['input']:
        for item in message.get('content',[]):
            if item.get('type') == 'input_image':
                raw = item['image_url']
                item['image_url'] = 'sha256:'+hashlib.sha256(raw.encode()).hexdigest()
    wire = json.dumps(body).encode()
    (folder/'request.json').write_text(json.dumps(dict(endpoint=ENDPOINT,
        wire_sha256=hashlib.sha256(wire).hexdigest(),body=redacted),indent=2))
    read_fd,write_fd = os.pipe()
    os.write(write_fd,('header = "Authorization: Bearer '+key+'"\n').encode())
    os.close(write_fd)
    started = time.monotonic()
    try:
        response = subprocess.run(['curl','--silent','--show-error','--http1.1',
            '--socks5-hostname','127.0.0.1:7897','--connect-timeout','20','--max-time','300',
            '--config',f'/proc/self/fd/{read_fd}','--header','Content-Type: application/json',
            '--data-binary','@-','--write-out','\n%{http_code}',ENDPOINT],
            input=wire,capture_output=True,pass_fds=(read_fd,),timeout=310)
        raw,_,status = response.stdout.rpartition(b'\n')
        (folder/'response.json').write_bytes(raw)
        (folder/'transport.json').write_text(json.dumps(dict(http_status=status.decode(),
            returncode=response.returncode,elapsed_s=time.monotonic()-started,endpoint=ENDPOINT)))
        if response.returncode or not status.startswith(b'2'):
            raise RuntimeError('Decisions transport/HTTP failure; do not resample: '+status.decode())
        data = json.loads(raw)
        if data.get('model') != MODEL:
            raise ValueError('Wrong Decisions response model')
        answers = {x['name']:x['choice'] for x in data['answers']}
        expected = {q['name']: {v['value'] for v in q['choices']} for q in body['questions']}
        if len(data['answers']) != len(expected) or set(answers) != set(expected):
            raise ValueError('Unexpected Decisions answer names')
        if any(answers[k] not in expected[k] for k in expected):
            raise ValueError('Invalid Decisions choice')
        return answers
    finally:
        os.close(read_fd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--task',required=True)
    parser.add_argument('--sim-port',type=int,required=True)
    parser.add_argument('--seed',type=int,required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    skill = SKILL_ROOT.parent/'robodojo-gpt-only-rollout'
    prompt = (skill/'SKILL.md').read_text()+'\n\n'+(skill/'context/teacher_context.md').read_text()
    (args.output/'PROMPT.md').write_text(prompt)
    q = questions()
    (args.output/'questions.json').write_text(json.dumps(q,indent=2))
    key = load_key()
    rollout = GPTOnlyTools(args.output,args.task,sim_port=args.sim_port,seed=args.seed,
        max_decisions=0,prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest())
    messages = [dict(role='developer',content=[dict(type='input_text',text=prompt)])]
    try:
        start = dict(rollout.next_call()); start.pop('tool')
        packet = rollout.start(**start)
        rollout.run.update(teacher_model_provider='openai-decisions',
            teacher_reasoning_effort=None, decision_endpoint=ENDPOINT,
            decision_question_count=14, decisions_API_has_no_reasoning_effort_parameter=True)
        (args.output/'run.json').write_text(json.dumps(rollout.run,indent=2))
        gripper = {arm:packet['current_eef'][arm]['gripper_opening_command'] < .5
                   for arm in ('left','right')}
        while not packet['rollout_finished']:
            official = content_items(packet,images=True,max_image_edge=DEFAULT_CODEX_IMAGE_MAX_EDGE)
            content = [dict(type='input_text',text=x['text']) if x['type']=='inputText' else
                       dict(type='input_image',image_url=x['imageUrl'],detail='auto') for x in official]
            messages.append(dict(role='user',content=content))
            index = len(rollout.history)
            choices = call(dict(model=MODEL,input=messages,questions=q),key,
                           args.output/'decisions'/f'{index:03d}')
            response = action(choices,packet,gripper)
            messages.append(dict(role='assistant',content=[dict(type='output_text',text=json.dumps(response))]))
            arguments = dict(rollout.next_call()); arguments.pop('tool'); arguments['response'] = response
            packet = rollout.act(**arguments)
    except BaseException as exc:
        (args.output/'failure.json').write_text(json.dumps(dict(error_type=type(exc).__name__,
            error=str(exc),step_id=rollout.tick,endpoint=ENDPOINT,no_response_repair=True)))
        if rollout.episode is not None and rollout.phase != 'done':
            rollout.finish('controller_error')
        raise
    finally:
        rollout.close()


if __name__ == '__main__':
    main()

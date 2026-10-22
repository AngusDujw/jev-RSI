"""Persistent, bounded-memory Decisions Playground worker with review barriers."""
import argparse
import base64
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import time
import uuid

from contract import decode, delivered_motion_feedback, motion_feedback, permitted_state, questions
from transport import MODEL, request, save

STOP = False


def rpc(port, op, **arguments):
    message = dict(op=op, request_id=uuid.uuid4().hex, **arguments)
    with socket.create_connection(('127.0.0.1', port), timeout=30) as connection:
        connection.settimeout(300)
        connection.sendall(json.dumps(message).encode()+b'\n')
        with connection.makefile('rb') as stream:
            value = json.loads(stream.readline())
    if value.get('request_id') != message['request_id']:
        raise RuntimeError('Mismatched native RPC response identity; do not replay')
    if not value.get('ok'):
        raise RuntimeError('Native RPC rejected: '+json.dumps(value))
    result = value['result']
    if 'images_png_base64' in result:
        result = dict(result, observation_id=result['episode_id']+':'+str(result['step']),
            native_success=result['success'], observation=dict(state=result['state'],
                instruction=result['instruction'], images=result['images_png_base64']))
    return result


def append(path, value):
    with path.open('a') as stream:
        stream.write(json.dumps(value)+'\n')


def images_content(images, prefix):
    result = []
    for name, encoded in images.items():
        result.extend([dict(type='input_text', text=prefix+' camera '+name),
            dict(type='input_image', image_url='data:image/png;base64,'+encoded, detail='high')])
    return result


def persist_images(folder, images):
    folder.mkdir(parents=True, exist_ok=True)
    refs = []
    for name, encoded in images.items():
        path = folder/(name+'.png')
        content = base64.b64decode(encoded)
        path.write_bytes(content)
        refs.append(dict(camera=name, path=str(path), sha256=hashlib.sha256(content).hexdigest()))
    return refs


def knowledge(path):
    data = json.loads(path.read_text())
    if not json.dumps(data, ensure_ascii=False).isascii():
        raise ValueError('Knowledge must be English ASCII')
    if set(data)-{'revision', 'guidance', 'visual_lessons', 'skills'}:
        raise ValueError('Unsupported model-readable knowledge fields')
    # Paths point only into the newly authored campaign, never an old experience bank.
    content = []
    for item in data.get('visual_lessons', []):
        image_path = Path(item['image_path']).resolve()
        if not image_path.is_relative_to(path.resolve().parent):
            raise ValueError('Visual lesson must belong to this campaign knowledge directory')
        content.extend([dict(type='input_text', text=item['description']),
            dict(type='input_image', image_url='data:image/png;base64,'+
                base64.b64encode(image_path.read_bytes()).decode(), detail='high')])
    return data, content


def main():
    global STOP
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sim-port', type=int, required=True)
    parser.add_argument('--knowledge', type=Path, required=True)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--visual-history', action='store_true')
    parser.add_argument('--retain-history', action='store_true')
    parser.add_argument('--segment-decisions', type=int, default=3)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    def stop(*unused):
        global STOP
        STOP = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    prompt = Path(__file__).with_name('prompt.md').read_text()
    recent = deque(maxlen=2)
    command_sequence = -1
    count = segment = 0
    snapshot = None
    retained_episode = None
    try:
        snapshot = rpc(args.sim_port, 'observe')
        retained_episode = snapshot['episode_id']
        while not STOP:
            data, lesson_images = knowledge(args.knowledge)
            revision = data['revision']
            for _ in range(args.segment_decisions):
                if STOP or snapshot['ended']:
                    break
                observation = snapshot['observation']
                state = permitted_state(observation['state'])
                model_state = dict(instruction=observation['instruction'],
                    current_robot=state, knowledge_revision=revision,
                    applicable_guidance=data.get('guidance', ''), skills=data.get('skills', []),
                    recent_interactions=[item['text'] for item in recent])
                if not json.dumps(model_state, ensure_ascii=False).isascii():
                    raise ValueError('Model state must contain English ASCII text before serialization')
                serialized = json.dumps(model_state)
                for forbidden in ('camera_calibration', 'intrinsics', 'extrinsics',
                                  'camera_to_world', 'reward', 'native_success'):
                    if forbidden in serialized:
                        raise ValueError('Forbidden model input field: '+forbidden)
                content = [dict(type='input_text', text=prompt+'\nCURRENT STATE\n'+serialized)]
                content += lesson_images
                if args.visual_history:
                    for item in recent:
                        content += images_content(item['images'], 'HISTORICAL '+item['text']['observation_id'])
                content += images_content(observation['images'], 'CURRENT')
                call_dir = args.output/'requests'/f'{count:04d}'
                if args.retain_history and snapshot['episode_id'] == retained_episode:
                    persist_images(args.output/'retained'/retained_episode/f'{snapshot["step"]:04d}', observation['images'])
                save(args.output/'status.json', dict(status='requesting', count=count,
                    step=snapshot['step'], episode_id=snapshot['episode_id'], revision=revision))
                answers = request(dict(model=MODEL, input=[dict(role='user', content=content)],
                    questions=questions()), call_dir, args.key_file)
                if STOP:
                    save(call_dir/'not_executed.json', dict(reason='stop_received_during_request',
                        answers=answers))
                    break
                native_action, audit = decode(answers, observation['state'])
                if STOP:
                    break
                before = snapshot
                snapshot = rpc(args.sim_port, 'step', episode_id=before['episode_id'],
                    expected_step=before['step'], action=native_action, steps=5)
                text = dict(observation_id=before['observation_id'], step=before['step'],
                    robot_before=state, selected_action=answers,
                    execution_feedback=motion_feedback(audit, snapshot['observation']['state']),
                    last_dispatched_target_feedback=delivered_motion_feedback(
                        audit, snapshot['last_dispatched_action'], snapshot['observation']['state']),
                    measured_robot_after=permitted_state(snapshot['observation']['state']))
                recent.append(dict(text=text, images=observation['images']))
                append(args.output/'interactions.jsonl', dict(count=count,
                    episode_id=before['episode_id'], revision=revision, **text,
                    decoded_action=native_action, audit=audit, step_after=snapshot['step'],
                    executed_steps=snapshot.get('executed_steps'),
                    requested_steps=snapshot.get('requested_steps'),
                    controller_event=snapshot.get('controller_event'),
                    review_required=snapshot.get('review_required', False)))
                if args.retain_history and before['episode_id'] == retained_episode:
                    persist_images(args.output/'retained'/before['episode_id']/f'{before["step"]:04d}', observation['images'])
                count += 1
                if snapshot.get('review_required', False):
                    # A delivered pre-dispatch refusal ends this short segment.
                    # Only explicit outer review may authorize another action.
                    break
            # Review does not advance physics. Persistent process/context stays alive.
            if args.retain_history and snapshot['episode_id'] == retained_episode:
                persist_images(args.output/'retained'/retained_episode/f'{snapshot["step"]:04d}', snapshot['observation']['images'])
            refs = persist_images(args.output/'review_current', snapshot['observation']['images'])
            save(args.output/'review.json', dict(status='awaiting_review', segment=segment,
                count=count, episode_id=snapshot['episode_id'], step=snapshot['step'],
                ended=snapshot['ended'], native_success=snapshot.get('native_success'),
                revision=revision, images=refs,
                controller_event=snapshot.get('controller_event'),
                executed_steps=snapshot.get('executed_steps'),
                requested_steps=snapshot.get('requested_steps'),
                review_required=snapshot.get('review_required', False),
                measured_robot=permitted_state(snapshot['observation']['state'])))
            save(args.output/'status.json', dict(status='awaiting_review', count=count,
                step=snapshot['step'], segment=segment, episode_id=snapshot['episode_id'], revision=revision))
            while not STOP:
                path = args.output/'command.json'
                if path.exists():
                    command = json.loads(path.read_text())
                    if command['sequence'] > command_sequence:
                        command_sequence = command['sequence']
                        if command['op'] == 'stop':
                            STOP = True
                        elif command['op'] == 'reset':
                            snapshot = rpc(args.sim_port, 'reset', reason=command['reason'],
                                episode_id=snapshot['episode_id'], expected_step=snapshot['step'])
                            recent.clear()
                        elif command['op'] != 'continue':
                            raise ValueError('Unknown review command')
                        if snapshot['ended'] and not STOP:
                            raise ValueError('Ended native attempt needs explicit reset or stop')
                        append(args.output/'review_commands.jsonl', command)
                        break
                time.sleep(1)
            segment += 1
    except BaseException as error:
        save(args.output/'failure.json', dict(error_type=type(error).__name__, error=str(error),
            count=count, no_retry=True))
        save(args.output/'status.json', dict(status='failed', count=count, error_type=type(error).__name__))
        raise
    finally:
        if snapshot is not None:
            try:
                rpc(args.sim_port, 'close', reason='explicit_stop' if STOP else 'worker_error')
            except Exception as error:
                save(args.output/'close_error.json', dict(error_type=type(error).__name__, error=str(error)))
        if STOP:
            save(args.output/'status.json', dict(status='stopped', count=count))
            for path in (args.output/'review_current').glob('*.png'):
                path.unlink()


if __name__ == '__main__':
    main()

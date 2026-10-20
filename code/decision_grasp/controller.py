"""Current-RGB-only Decisions policy; no stored images or privileged inputs."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import uuid

import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'policy_comparison'))
from decisions_policy import ENDPOINT, MODEL, TCP_OFFSET, action, call, load_key, questions
from hybrid_rollout.robodojo.robodojo_server.gpt_only_client import GPTOnlyTools
from hybrid_rollout.robodojo.io import write_json
from joint_rotation import questions_with_joint_rotation, expand_rotation_choices
from camera_overlay import annotate

CAMERAS = ('cam_high','cam_left_wrist','cam_right_wrist')


class MemoryRGBTools(GPTOnlyTools):
    def _observation(self, directory, *, result=None):
        directory.mkdir(parents=True)
        self.obs = self._rpc('teacher_observation')
        if getattr(self,'persist_images',False):
            for camera in CAMERAS:
                Image.fromarray(self.obs[camera]).save(directory/(camera+'.png'))
        self.observation_path = directory/'observation.json'
        packet = dict(task=self.task, instruction=self.meta['instruction'], step_id=self.tick,
            current_eef=self.current_eef(), rollout_finished=self.phase=='done',
            request_id=uuid.uuid4().hex, next_call=self.next_call())
        self.request = dict(packet)
        self.observation_packet = packet
        write_json(self.observation_path,packet)
        return packet


def permitted_state(rollout, packet):
    arms = {}
    for arm in ('left','right'):
        current = packet['current_eef'][arm]
        rotation = Rotation.from_quat(np.roll(current['quaternion_wxyz'],-1))
        matrix = rotation.as_matrix()
        arms[arm] = dict(tcp_position_world_m=(np.array(current['position'])+rotation.apply(TCP_OFFSET)).tolist(),
            tool_rotation_world_from_local=matrix.tolist(),
            finger_extension_axis_world=matrix[:,0].tolist(),
            jaw_sliding_axis_world=matrix[:,1].tolist(),
            gripper_opening_measured=current['gripper_opening_command'])
    # Explicit allowlist: do not forward packet result/history or native flags.
    return dict(instruction=packet['instruction'], control_step=packet['step_id'],
        robot=arms, measured_joint_state=rollout.obs['states'].tolist(),
        camera_order=list(CAMERAS), frame='environment_origin_world')


def image_items(obs, robot=None, output=None):
    result=[]
    for name in CAMERAS:
        buffer=io.BytesIO()
        image = (annotate(obs[name], obs['camera_calibration'][name], robot)
                 if robot is not None else Image.fromarray(obs[name]))
        image.save(buffer,format='PNG')
        if output is not None:
            (output/('model_'+name+'.png')).write_bytes(buffer.getvalue())
        result += [dict(type='input_text',text='Current camera: '+name),
            dict(type='input_image',image_url='data:image/png;base64,'+
                base64.b64encode(buffer.getvalue()).decode(),detail='high')]
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--task',default='general_pickup')
    parser.add_argument('--sim-port',type=int,required=True)
    parser.add_argument('--seed',type=int,required=True)
    parser.add_argument('--rotation-format',choices=('axes','joint'),default='axes')
    parser.add_argument('--save-images',action='store_true')
    parser.add_argument('--geometry-overlay',action='store_true')
    parser.add_argument('--alignment-guidance',action='store_true')
    args=parser.parse_args()
    if args.alignment_guidance and (not args.geometry_overlay or args.rotation_format!='joint'):
        parser.error('Alignment guidance requires geometry overlay and joint rotation')
    args.output.mkdir(parents=True,exist_ok=False)
    prompt=Path(__file__).with_name('advancer_alignment_v2.md' if args.alignment_guidance else 'advancer_v1.md').read_text()
    if args.geometry_overlay:
        prompt += ('\n\nImage overlays show measured robot TCP projections: cyan=left, orange=right. '
            'The cross is a geometric projection, not a visible object, contact point or evidence of holding. '
            'Red/green/blue segments show the projection of a +0.02 m world X/Y/Z displacement '
            'from that TCP. Use these segments to relate image motion to the world action axes. '
            'They may be hidden by real geometry or absent when outside the image. '
            'Camera K and camera-to-world transforms use X-right/Y-down/Z-forward camera coordinates. '
            'Do not treat a projected TCP overlap as an enclosed grasp. No target annotations are supplied.')
    if not prompt.isascii():raise ValueError('Model prompt must be English ASCII')
    (args.output/'PROMPT.md').write_text(prompt)
    q=questions()
    if args.rotation_format=='joint':q=questions_with_joint_rotation(q)
    for question in q:
        question['instructions']=question['instructions'].replace('Use the original observations and same-episode context.','Use only the current images and measured robot state.')
    write_json(args.output/'questions.json',q)
    key=load_key()
    rollout=MemoryRGBTools(args.output,args.task,sim_port=args.sim_port,seed=args.seed,
        max_decisions=0,prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest())
    rollout.persist_images=args.save_images
    try:
        start=dict(rollout.next_call());start.pop('tool')
        packet=rollout.start(**start)
        rollout.run.update(teacher_model=MODEL,teacher_model_provider='openai-decisions',
            teacher_reasoning_effort=None,decision_endpoint=ENDPOINT,
            condition=('generic-current-rgb-alignment-v4' if args.alignment_guidance else
                'generic-current-rgb-calibrated-v3' if args.geometry_overlay else
                'generic-current-rgb-joint-v2' if args.rotation_format=='joint' else 'generic-current-rgb-v1'),
            decision_question_count=len(q),rotation_format=args.rotation_format,
            history_supplied=False,images_persisted=args.save_images,
            camera_overlay=args.geometry_overlay,alignment_guidance=args.alignment_guidance,
            tcp_reference_link6_local_m=TCP_OFFSET.tolist())
        write_json(args.output/'run.json',rollout.run)
        gripper={a:packet['current_eef'][a]['gripper_opening_command']<.5 for a in ('left','right')}
        while not packet['rollout_finished']:
            state=permitted_state(rollout,packet)
            if args.geometry_overlay:
                state['camera_calibration']=rollout.obs['camera_calibration']
            index=len(rollout.history)
            content=[dict(type='input_text',text=prompt+'\n\nCURRENT OBSERVATION\n'+json.dumps(state))]+image_items(
                rollout.obs,state['robot'] if args.geometry_overlay else None,
                rollout.observation_path.parent if args.geometry_overlay and args.save_images else None)
            answers=call(dict(model=MODEL,input=[dict(role='user',content=content)],questions=q),key,
                         args.output/'decisions'/f'{index:03d}')
            if args.rotation_format=='joint':answers=expand_rotation_choices(answers)
            response=action(answers,packet,gripper)
            response['reason']='Execute the joint categorical choices selected from current RGB and measured robot state.'
            arguments=dict(rollout.next_call());arguments.pop('tool');arguments['response']=response
            packet=rollout.act(**arguments)
            print(json.dumps(dict(event='progress',step=rollout.tick,decisions=len(rollout.history))),flush=True)
    except BaseException as error:
        write_json(args.output/'failure.json',dict(error_type=type(error).__name__,error=str(error),
            step=rollout.tick,endpoint=ENDPOINT,no_repair_or_resample=True))
        if rollout.episode is not None and rollout.phase!='done':
            rollout.finish('controller_error')
        raise
    finally:
        rollout.close()


if __name__=='__main__':main()

"""Native one-axis image-centering with audited Decisions, never object truth."""
import argparse
import base64
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import sys

from legacy_decisions import convert_request, english
from libero_prompt_revision import RevisedAPI
from libero_multimodal import ObservationStream
from libero_inframe_axes import overlay_gripper_axes
from libero_motion_multimodal import assert_no_camera_matrices


def save(path,value):
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


class Recorder:
    def __init__(self,folder):
        self.folder=folder;folder.mkdir()

    def log(self,value):
        with (self.folder/'events.jsonl').open('a') as f:
            f.write(json.dumps(value)+'\n')


class VisualServoAPI(RevisedAPI):
    profile='libero-visible-center-v1'

    def build_payload(self,sent):
        payload=convert_request(sent)
        axis=next(iter(sent['questions']))
        direction=('left' if axis=='y' else 'up')
        scene=('right' if axis=='y' else 'down')
        relation=('left' if axis=='y' else 'above')
        opposite=('right' if axis=='y' else 'below')
        goal=('horizontally on the vertical center line' if axis=='y' else
              'vertically on the horizontal center line')
        description=(f'Control only world {axis.upper()}; other motion channels stay fixed and the gripper stays open. '
            'The target is the patterned gray bowl, not the flat red-rim plate. '
            f'In the wrist image, bring the center of that bowl {goal} of the image. '
            'This is camera centering, not a grasp or a hidden world waypoint. '
            'Use the image center, not an arrow tip, as the visual destination. '
            f'With the current fixed wrist orientation, positive world {axis.upper()} moves the hand {direction} '
            f'in the current view; because the camera moves with it, the bowl scene shifts {scene}. '
            f'Thus if the bowl is {relation} the image center, positive brings it toward center; '
            f'if it is {opposite}, negative brings it toward center. Hold when visually centered. '
            'The controller supplies a small fixed increment. '
            'World arrows start at the current gripper reference: external green +Y/blue +Z; '
            'wrist red +X/green +Y. No target point is drawn. '
            'Previous images, when present, show the observation before the last categorical action. '
            'Compare them with current images to check its effect. Return the requested category only.')
        content=[dict(type='input_text',text=description),dict(type='input_text',text=payload['input'])]
        records=[]
        frames=[]
        if self.temporal and self.previous is not None:
            frames.append(('PREVIOUS',self.previous))
        frames.append(('CURRENT',self.views))
        for label,views in frames:
            for view in views:
                content += [dict(type='input_text',text=label+' '+view['camera']+'. '+view['description']),
                    dict(type='input_image',detail='high',image_url='data:image/png;base64,'+base64.b64encode(view['raw']).decode())]
                records.append(dict(time_label=label,**{k:v for k,v in view.items() if k!='raw'}))
        payload['input']=[dict(role='user',content=content)]
        self.image_count=len(records)
        self.metadata=dict(camera_views=records,history_images=self.temporal and self.previous is not None,
            camera_matrices_sent=False,eef_coordinates_sent=False,numeric_residuals_sent=False,
            target_markers=False,visual_goal='image center',diagnostic_not_benchmark_completion=True)
        english(payload);assert_no_camera_matrices(payload)
        return payload

    def validate_payload(self,payload):
        assert sum(x['type']=='input_image' for x in payload['input'][0]['content'])==self.image_count
        english(payload);assert_no_camera_matrices(payload)

    def input_audit(self):
        return self.metadata


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--libero-root',required=True)
    parser.add_argument('--init',type=int,required=True)
    parser.add_argument('--axis',choices=['x','y'],required=True)
    parser.add_argument('--offset',type=float,required=True)
    parser.add_argument('--temporal',action='store_true')
    parser.add_argument('--budget',type=int,default=24)
    args=parser.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    cache=out/'cache';cache.mkdir()
    os.environ.update(LIBERO_CONFIG_PATH=args.libero_root+'/.libero-config',TMPDIR=str(cache),
        XDG_CACHE_HOME=str(cache),MUJOCO_GL='egl')
    sys.path.insert(0,args.libero_root)
    import cv2
    import numpy as np
    from PIL import Image
    from libero.libero import benchmark
    from libero.libero.envs.env_wrapper import ControlEnv
    suite=benchmark.get_benchmark_dict()['libero_goal'](0)
    env=ControlEnv(bddl_file_name=suite.get_task_bddl_file_path(1144),
        camera_names=['agentview','robot0_eye_in_hand'],camera_heights=768,camera_widths=768,
        camera_depths=False,control_freq=20,horizon=1000,controller='OSC_POSE',initialization_noise=None)
    stream=ObservationStream();steps=0
    axis_index='xyz'.index(args.axis);pixel_index=0 if args.axis=='y' else 1
    reference=np.asarray(Image.open(args.reference).convert('RGB'))[210:300,337:427]
    reference=cv2.cvtColor(reference,cv2.COLOR_RGB2GRAY)
    save(out/'manifest.json',dict(task=1144,init=args.init,axis=args.axis,offset_m=args.offset,
        temporal=args.temporal,model='gpt-6-luna',key_origin='du',experience_injection=False,
        source_sha256={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ('libero_visual_servo.py','libero_inframe_axes.py','libero_multimodal.py',
                         'libero_prompt_revision.py','legacy_decisions.py')},
        physical_egl_gpu=os.environ.get('MUJOCO_EGL_DEVICE_ID'),native_python=sys.executable,
        reference_image=str(args.reference),reference_sha256=hashlib.sha256(args.reference.read_bytes()).hexdigest(),
        reference_crop_xyxy=[337,210,427,300],reference_use='historical bowl appearance for evaluation only; never sent to model',
        goal_band_pixels=16,minimum_initial_error_pixels=28,budget=args.budget,
        observation_permissions='current RGB, own robot state and public camera calibration only',
        benchmark_completion_not_evaluated=True))

    def step(action):
        nonlocal steps,obs
        obs,_,_,_=env.step(np.asarray(action,float));steps+=1;stream.tick=steps;stream.record(env,obs)

    def locate():
        rgb=np.ascontiguousarray(obs['robot0_eye_in_hand_image'][::-1])
        gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
        best=None
        for scale in (.92,1.,1.08):
            template=cv2.resize(reference,None,fx=scale,fy=scale)
            scores=cv2.matchTemplate(gray,template,cv2.TM_CCOEFF_NORMED)
            _,score,_,point=cv2.minMaxLoc(scores)
            row=dict(score=float(score),pixel=[point[0]+template.shape[1]/2,point[1]+template.shape[0]/2])
            if best is None or row['score']>best['score']:best=row
        if best['score']<.65:raise RuntimeError('Visible bowl appearance lost; no guessed evaluation')
        return best

    def views_for_actor(api):
        views,robot=stream.capture(api.asset_root)
        for view in views:
            raw,_,audit=overlay_gripper_axes(view['raw'],view['camera_to_world'],view['K'],
                robot['robot0_eef_pos'],view['camera'])
            path=api.asset_root/f'{steps:04d}-{api.calls:04d}-{view["camera"]}.png';path.write_bytes(raw)
            view.update(raw=raw,rgb_path=str(path),sha256=hashlib.sha256(raw).hexdigest(),overlay_audit=audit)
        return views

    trace=[];result=dict(success=False,error=None)
    try:
        env.seed(0);env.reset();obs=env.set_init_state(np.asarray(suite.get_task_init_states(1144)[args.init],float))
        for _ in range(10):step([0,0,0,0,0,0,-1])
        # Evaluation/setup uses current RGB only. This is not an actor success.
        for _ in range(100):
            measured=locate();error=measured['pixel'][pixel_index]-384
            if abs(error)<8:break
            action=np.zeros(7);action[axis_index]=-.15 if error>0 else .15;action[6]=-1;step(action)
        else:raise RuntimeError('Could not initialize visible image-centered reference')
        center_pose=obs['robot0_eef_pos'].copy();goal=center_pose.copy();goal[axis_index]+=args.offset
        for _ in range(80):
            error=goal-obs['robot0_eef_pos']
            if abs(error[axis_index])<.002:break
            action=np.zeros(7);action[axis_index]=np.clip(error[axis_index]*.6,-.01,.01)/.05;action[6]=-1;step(action)
        else:raise RuntimeError('Own robot offset setup did not track')
        initial=locate();initial_error=initial['pixel'][pixel_index]-384
        if abs(initial_error)<28:raise RuntimeError('Setup did not create a meaningful visual offset')
        recorder=Recorder(out/'episode');api=VisualServoAPI({},recorder.log,'jev')
        api.asset_root=out/'inputs';api.asset_root.mkdir();api.temporal=args.temporal;api.previous=None
        previous_action=None
        for index in range(args.budget):
            measured=locate();api.views=views_for_actor(api)
            original=dict(model='gpt-6-luna',state=dict(task='Center the patterned gray bowl in the wrist view',
                stage='horizontal_image_centering' if args.axis=='y' else 'vertical_image_centering',
                previous_action=previous_action if args.temporal else None),
                questions={args.axis:dict(type='choice',instructions='Choose the direction that centers the bowl on the stated image center line. Hold when visually centered.',
                    criteria=dict(negative='Negative world-axis increment',hold='Zero increment',positive='Positive world-axis increment'))})
            answer=api.post('/systemone',original);choice=answer['answers'][args.axis]['choice']
            before=obs['robot0_eef_pos'].copy();api.previous=deepcopy(api.views)
            action=np.zeros(7);action[axis_index]={'positive':1,'negative':-1,'hold':0}[choice]*.01/.05;action[6]=-1
            step(action);after=locate()
            row=dict(index=index,choice=choice,before_pixel=measured['pixel'],after_pixel=after['pixel'],
                tracker_score=after['score'],evaluation_error_pixels=after['pixel'][pixel_index]-384,
                own_displacement_m=(obs['robot0_eef_pos']-before).tolist(),native_steps=steps,
                probabilities=answer['answers'][args.axis]['probabilities'])
            trace.append(row);save(out/'trace.json',trace)
            previous_action=dict(axis=args.axis,direction=choice)
            if choice=='hold' and abs(row['evaluation_error_pixels'])<=16 and abs(row['evaluation_error_pixels'])<=abs(initial_error)*.5:
                result['success']=True;break
        result.update(initial_error_pixels=initial_error,final_error_pixels=trace[-1]['evaluation_error_pixels'],
            model_calls=len(trace),native_steps_including_setup=steps,benchmark_completion_not_evaluated=True)
    except Exception as error:
        result.update(error=str(error),model_calls=len(trace),native_steps_including_setup=steps)
    finally:
        save(out/'result.json',result);env.close()
    print(json.dumps(result))


if __name__=='__main__':
    main()

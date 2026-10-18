"""Native RGB direction policy: no scene targets, residuals or motion oracle."""
import argparse
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

from legacy_decisions import english, convert_request
from libero_prompt_revision import RevisedAPI

MOTION = '''Control the centre between the gripper faces. World +X is forward,
away from the robot base, +Y is left, +Z is up when standing behind the robot
facing the table. Negative reverses the direction. X/Y/Z translate without
changing tool orientation. Roll rotates about fixed world X, pitch about fixed
world Y, yaw about fixed world Z, through the gripper reference. Positive
rotations follow the right-hand rule; positive yaw is counterclockwise viewed
from above. Simultaneous roll/pitch/yaw are ONE rotation vector, not sequential
Euler rotations. Hold means zero on that channel. World arrows are projected
from the current measured gripper: external image Y/Z, wrist image X/Y. The
wrist camera moves with the hand, so scene motion in that image can be opposite
to hand motion. Arrows identify axes, not desired motion. Previous actions and
their measured results are execution feedback, not recommended future actions.
Choose directions from the actual object and finger relationship in both views.
Decide a grasp posture yourself; no target pose or angle error is supplied.
Keep the gripper open until the source is between the fingers. When closed,
retain the close command during manipulation. Use fine scale near contact;
use coarse scale for clear free-space movement. Hold unused channels. A stage
label is a goal, never evidence that its exit condition is satisfied.'''


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


class Recorder:
    def __init__(self, folder):
        self.folder=folder
    def log(self, row):
        with (self.folder/'api-events.jsonl').open('a') as f:
            f.write(json.dumps(row)+'\n')


class DirectAPI(RevisedAPI):
    profile='genuine_rgb_direct_axes_v1'
    def revise(self, original):
        return original
    def build_payload(self, sent):
        p=convert_request(sent)
        p['input']=[dict(role='user',content=[dict(type='input_text',text=MOTION),
            *self.demonstrations,dict(type='input_text',text=p['input']),*self.previous,*self.current])]
        self.image_count=sum(x['type']=='input_image' for x in p['input'][0]['content'])
        return p
    def validate_payload(self,p):
        english(p)
        forbidden={'required_rotation_world_rad','goal_minus_current','target_pose','reward','success','contact','object_pose'}
        def audit(value):
            if isinstance(value,dict):
                assert not (set(value)&forbidden),set(value)&forbidden
                for v in value.values():audit(v)
            elif isinstance(value,list):
                for v in value:audit(v)
        # Check structured field names, not substrings in images or words like successive.
        audit(self.sent_state)
    def input_audit(self):
        return dict(no_target_geometry=True,no_error_feedback=True,examples='Measured own-robot primitive effects',
                    native_tick=self.tick,action_signs_chosen_by_model=True)


def image_part(raw):
    return dict(type='input_image',detail='high',image_url='data:image/png;base64,'+base64.b64encode(raw).decode())


def demonstrations(root, output):
    from PIL import Image,ImageDraw
    parts=[]
    for name in ('x','y','z','yaw','pitch','roll'):
        folder=root/name
        endpoints=output/name;endpoints.mkdir()
        for label,seek in (('start',[]),('end',['-sseof','-0.10'])):
            source=folder/(label+'.png')
            if not source.is_file():
                source=endpoints/(label+'.png')
                subprocess.run(['ffmpeg','-v','error',*seek,'-i',str(folder/(name+'.mp4')),
                    '-frames:v','1','-threads','1',str(source)],check=True)
            if label=='start':start=source
            else:end=source
        # These endpoints contain real RGB and own-axis overlays, not imagined future states.
        a=Image.open(start).convert('RGB').crop((0,65,1024,600))
        b=Image.open(end).convert('RGB').crop((0,65,1024,600))
        card=Image.new('RGB',(1024,575),'#101c25')
        card.paste(a.resize((512,268)),(0,34));card.paste(b.resize((512,268)),(512,34))
        d=ImageDraw.Draw(card);d.text((10,10),f'INDEPENDENT EXAMPLE +{name.upper()} | BEFORE (left) -> AFTER (right)',fill='white')
        metrics=json.loads((folder/'metrics.json').read_text())
        description=(f'Actual independently reset +{name} demonstration. '
            'Left half is BEFORE, right half AFTER; within each half external view is left and wrist view right. '
            'This is another scene, not a target for the current task. '
            f'Measured world translation mm {metrics["measured_displacement_mm"]}; '
            f'measured world rotation-vector degrees {metrics["measured_rotation_vector_deg"]}. '
            'Negative reverses this primitive; hold leaves it unchanged. Use the effect, not the endpoint coordinates.')
        # Remove unused black area to preserve readability at the API image size.
        card=card.crop((0,0,1024,304));buf=io.BytesIO();card.save(buf,format='PNG')
        raw=buf.getvalue();(output/f'{name}-example.png').write_bytes(raw)
        save(endpoints/'provenance.json',dict(source_video=str(folder/(name+'.mp4')),
            video_sha256=hashlib.sha256((folder/(name+'.mp4')).read_bytes()).hexdigest(),
            measured_effects=metrics,endpoint_source='existing PNG or decoded endpoint of original native video'))
        parts.extend([dict(type='input_text',text=description),image_part(raw)])
    return parts


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--task',type=int,required=True);p.add_argument('--init',type=int,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--demos',type=Path,required=True);p.add_argument('--libero-root',required=True)
    p.add_argument('--gpu',type=int,choices=[4,5,6,7],default=4)
    p.add_argument('--decisions',type=int,default=180);p.add_argument('--size',type=int,default=512)
    p.add_argument('--grounded',action='store_true',help='Pro RGB source description and fixed external source crop')
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    cache=out/'cache';cache.mkdir()
    os.environ.update(LIBERO_CONFIG_PATH=args.libero_root+'/.libero-config',
        TMPDIR=str(cache),XDG_CACHE_HOME=str(cache),MUJOCO_GL='egl',MUJOCO_EGL_DEVICE_ID=str(args.gpu))
    # One lightweight renderer per GPU, with at least 1.4GiB free before allocation.
    query=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free','--format=csv,noheader,nounits'],text=True)
    free={int(r.split(',')[0]):int(r.split(',')[1]) for r in query.strip().splitlines()}
    if free[args.gpu]<1400: raise RuntimeError('Insufficient free GPU memory for isolated renderer')
    sys.path.insert(0,args.libero_root)
    import numpy as np
    from scipy.spatial.transform import Rotation
    from PIL import Image
    from libero.libero import benchmark
    from libero.libero.envs.env_wrapper import ControlEnv
    from robosuite.utils.camera_utils import get_camera_intrinsic_matrix,get_camera_extrinsic_matrix
    from libero_inframe_axes import overlay_gripper_axes
    plan=json.loads(args.plan.read_text());english(plan)
    save(out/'manifest.json',dict(task=args.task,init=args.init,gpu=args.gpu,
        profile='grounded_rgb_axes_v2' if args.grounded else 'genuine_rgb_direct_axes_v1r2',
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        plan=plan,plan_sha256=hashlib.sha256(args.plan.read_bytes()).hexdigest(),
        scene_target_or_error_inputs=False,grasp_pose_decided_by_actor=True,experience_injection=False))
    stages=plan['stages'];stage=0;grip=-1.;tick=0;previous=[];history=[];env=None
    recorder=Recorder(out);api=DirectAPI({},recorder.log,'jev')
    examples=out/'examples';examples.mkdir();api.demonstrations=demonstrations(args.demos,examples)
    api.previous=[]
    started=time.monotonic();result=dict(task=args.task,init=args.init,success=False,program_finished=False)
    try:
        with contextlib.redirect_stdout(io.StringIO()):suite=benchmark.get_benchmark_dict()['libero_goal'](0)
        instruction=suite.get_task(args.task).language;english(instruction)
        env=ControlEnv(bddl_file_name=suite.get_task_bddl_file_path(args.task),
            camera_names=['agentview','robot0_eye_in_hand'],camera_heights=args.size,camera_widths=args.size,
            camera_depths=False,control_freq=20,horizon=600,controller='OSC_POSE',initialization_noise=None)
        env.seed(0);env.reset();obs=env.set_init_state(np.asarray(suite.get_task_init_states(args.task)[args.init],float))
        for _ in range(10):obs,_,_,_=env.step(np.r_[np.zeros(6),grip]);tick+=1
        native=env.env;site=native.robots[0].eef_site_id
        def own_pose():
            return native.sim.data.site_xpos[site].copy(),native.sim.data.site_xmat[site].reshape(3,3).copy()
        def capture():
            parts=[];p0,_=own_pose()
            for camera in ('agentview','robot0_eye_in_hand'):
                im=Image.fromarray(np.ascontiguousarray(obs[camera+'_image'][::-1]));b=io.BytesIO();im.save(b,format='PNG')
                raw=b.getvalue();(out/f'{tick:04d}-{camera}-raw.png').write_bytes(raw)
                K=get_camera_intrinsic_matrix(native.sim,camera,args.size,args.size)
                T=get_camera_extrinsic_matrix(native.sim,camera)
                raw,_,audit=overlay_gripper_axes(raw,T,K,p0,camera)
                (out/f'{tick:04d}-{camera}-input.png').write_bytes(raw)
                parts.extend([dict(type='input_text',text=f'CURRENT {camera}, observation {tick}. World axes at the current gripper.'),image_part(raw)])
                if args.grounded and camera=='agentview' and 'fixed_view_bbox_xyxy' in plan:
                    # Fixed-camera articulated knob base is stationary; this crop is identity/visibility only.
                    box=np.asarray(plan['fixed_view_bbox_xyxy'],float)*(args.size/512)
                    margin=.10*args.size
                    box=[max(0,int(box[0]-margin)),max(0,int(box[1]-margin)),
                         min(args.size,int(box[2]+margin)),min(args.size,int(box[3]+margin))]
                    crop=im.crop(box).resize((512,512));b=io.BytesIO();crop.save(b,format='PNG')
                    (out/f'{tick:04d}-source-crop.png').write_bytes(b.getvalue())
                    parts.extend([dict(type='input_text',text='CURRENT fixed-view source detail; same observation, zoom only. '+plan['source_description']),image_part(b.getvalue())])
            return parts
        for decision in range(args.decisions):
            if tick+4>600:break
            if time.monotonic()-started>1800:raise TimeoutError('Native episode wall budget')
            api.current=capture();api.previous=previous;api.tick=tick
            state=dict(task=instruction,stage=stages[stage],stage_order=stages,
                gripper_joints=obs['robot0_gripper_qpos'].tolist(),last_actions=history[-4:],
                next_stage=stages[min(stage+1,len(stages)-1)])
            if args.grounded:
                state['source_description']=plan.get('source_description','Identify the named object from current images.')
                state['visual_cues']=plan.get('relevant_visual_cues',[])
            api.sent_state=state
            questions={}
            for a,label in zip(('x','y','z','rx','ry','rz'),('X translation','Y translation','Z translation','roll about world X','pitch about world Y','yaw about world Z')):
                questions[a]=dict(type='choice',instructions=f'Which {label} direction helps achieve the CURRENT stage goal from the actual images? Use motion examples for the physical effect. Hold if this channel needs no change.',
                    criteria={'positive':'Positive direction on this channel.','negative':'Negative direction on this channel.','hold':'No increment on this channel.'})
            questions['gripper']=dict(type='choice',instructions='Choose the gripper command for the current manipulation.',criteria={'open':'Open the fingers.','close':'Close or retain the grasp.','hold':'Retain the preceding gripper command.'})
            questions['scale']=dict(type='choice',instructions='Choose movement scale from visible clearance and required precision.',criteria={'coarse':'Free space: 20mm and 10degrees maximum per channel.','fine':'Near contact or alignment: 4mm and 2degrees maximum per channel.'})
            questions['transition']=dict(type='choice',instructions='Judge the observable exit condition for the CURRENT stage. Advance only when it is visibly satisfied. Advance executes no motion this turn.',criteria={'continue':'Continue current stage.','advance':'Current stage complete; enter next stage, or finish at the final stage.','restart':'Return to the first stage to recover.'})
            answer=api.post('/systemone',dict(model='gpt-6-luna',state=state,questions=questions))
            choices={k:v['choice'] for k,v in answer['answers'].items()};before_p,before_R=own_pose()
            previous=[dict(type='input_text',text='PREVIOUS observation, before the last executed command; compare with CURRENT.'),*api.current]
            if choices['transition']=='advance':
                if stage==len(stages)-1:result['program_finished']=True;break
                stage+=1;history.append(dict(choices=choices,execution='No physical action; stage advanced'));continue
            if choices['transition']=='restart':stage=0
            if choices['gripper']!='hold':grip=1. if choices['gripper']=='close' else -1.
            signs=np.array([{'negative':-1,'hold':0,'positive':1}[choices[a]] for a in ('x','y','z','rx','ry','rz')])
            step_m,step_r=(.020,np.deg2rad(10)) if choices['scale']=='coarse' else (.004,np.deg2rad(2))
            dp=signs[:3]*step_m;dr=signs[3:]*step_r
            dp*=min(1.,.03/max(np.linalg.norm(dp),1e-10));dr*=min(1.,.25/max(np.linalg.norm(dr),1e-10))
            target_p=before_p+dp;target_R=Rotation.from_rotvec(dr).as_matrix()@before_R
            for _ in range(4):
                pos,rot=own_pose();u_p=.7*(target_p-pos);u_r=.7*Rotation.from_matrix(target_R@rot.T).as_rotvec()
                action=np.r_[np.clip(u_p/.05,-1,1),np.clip(u_r/.5,-1,1),grip]
                obs,_,_,_=env.step(action);tick+=1
            after_p,after_R=own_pose()
            row=dict(decision=decision,native_steps=tick,stage=stage,choices=choices,
                measured_translation_mm=((after_p-before_p)*1000).tolist(),
                measured_rotation_world_deg=np.rad2deg(Rotation.from_matrix(after_R@before_R.T).as_rotvec()).tolist())
            history.append(row)
            with (out/'execution.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
            print(json.dumps(row),flush=True)
        capture()
        # Evaluator is read only here, after the final action; never sent to either model.
        result['success']=bool(env.check_success())
    except Exception as error:
        result['error']=dict(type=type(error).__name__,message=str(error).replace(api.credential,'[redacted]')[:600])
        raise
    finally:
        result.update(native_steps=tick,seconds=time.monotonic()-started,api_responses=len(list((out/'decision-api').glob('*/response.json'))))
        save(out/'result.json',result)
        if env is not None:env.close()
        print(json.dumps(result),flush=True)


if __name__=='__main__':main()

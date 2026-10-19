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
import urllib.error
import http.client
import urllib.request
from types import SimpleNamespace

from legacy_decisions import english, convert_request,convert_response,ENDPOINT
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
    def __init__(self,cfg,log,role):
        if os.environ.get('DECISION_MM_FILE_ONLY')=='1':
            if role!='jev':raise ValueError('Unexpected actor role')
            self.cfg=dict(model='gpt-6-luna',key_origin='du',authentication='local authorized Decisions caller')
            self.credential='';self.log=log;self.folder=Path(log.__self__.folder)/'decision-api'
            self.folder.mkdir(exist_ok=True);self.calls=0;self.client=None
        else:super().__init__(cfg,log,role)

    def compact_post(self,endpoint,original):
        if endpoint!='/systemone':raise ValueError('Unexpected actor endpoint')
        payload=self.build_payload(original);self.validate_payload(payload)
        folder=self.folder/f'{self.calls:04d}';self.calls+=1;folder.mkdir()
        raw=json.dumps(payload,ensure_ascii=False).encode()
        images=[hashlib.sha256(base64.b64decode(p['image_url'].split(',',1)[1])).hexdigest()
            for p in payload['input'][0]['content'] if p['type']=='input_image']
        save(folder/'request-summary.json',dict(model='gpt-6-luna',body_sha256=hashlib.sha256(raw).hexdigest(),
            image_sha256=images,question_options={k:list(v['criteria']) for k,v in original['questions'].items()},
            stage=original['state']['stage'],native_tick=self.tick))
        save(folder/'dispatch.json',dict(profile=self.profile,key_origin='du',endpoint=ENDPOINT,
            experience_injection=False,compact=True,image_count=len(images),**self.input_audit()))
        request=urllib.request.Request(ENDPOINT,data=raw,
            headers={'Authorization':'Bearer '+self.credential,'Content-Type':'application/json'},method='POST')
        try:
            with self.client.open(request,timeout=120) as response:reply=json.load(response)
            save(folder/'response.json',reply)
            return convert_response(reply,original)
        except Exception as error:
            save(folder/'failure.json',dict(error_type=type(error).__name__,error=str(error)[:500]));raise

    def post(self,endpoint,original):
        for attempt in range(3):
            before=self.calls
            try:return self.compact_post(endpoint,original) if getattr(self,'compact',False) else super().post(endpoint,original)
            except (urllib.error.URLError,http.client.RemoteDisconnected) as error:
                # HTTP errors (including refusals) are handled by the base policy.
                # Never repeat an answer or a parse failure to seek a preferred action.
                if isinstance(error,urllib.error.HTTPError):raise
                allocated=[self.folder/f'{i:04d}' for i in range(before,self.calls)]
                if any((d/'response.json').exists() for d in allocated) or attempt==2:raise
                self.log(dict(kind='unanswered_transport_retry',attempt=attempt+1,
                    error_type=type(error).__name__,no_physics_steps=True))
                time.sleep(2*(attempt+1))
    def revise(self, original):
        return original
    def build_payload(self, sent):
        p=convert_request(sent)
        p['input']=[dict(role='user',content=[dict(type='input_text',text=getattr(self,'motion',MOTION)),
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


def coordinate_questions(state,questions):
    """Expose current coordinates explicitly, without selecting a target or subtracting errors."""
    for i,a in enumerate(('x','y','z')):
        samples={v['label']:v['visible_surface_world_mm'][i] for v in state['visible_surface_samples']}
        questions[a]['instructions']=(f'Current stage goal: {state["stage"]["goal"]} '
            f'This question controls only world {a.upper()}. Current gripper {a.upper()} coordinate '
            f'is {state["own_gripper_world_mm"][i]} mm. CURRENT visible surface {a.upper()} coordinates '
            f'by image dot label are {json.dumps(samples)} mm in the SAME frame. '
            'First use RGB to select the physical grasp/support relationship appropriate to this stage; '
            'dots are observed surfaces, not selected target points, and may lie on background. '
            f'Should the gripper {a.upper()} coordinate increase, decrease, or remain unchanged to establish that relationship? '
            'Positive INCREASES this coordinate, negative DECREASES it. Hold only if this coordinate is already appropriate. '
            'Do not infer a direction from the sign of an absolute coordinate; compare positions in the common frame.')
        questions[a]['criteria']={'positive':f'Increase gripper world {a.upper()} coordinate.',
            'negative':f'Decrease gripper world {a.upper()} coordinate.',
            'hold':f'Keep gripper world {a.upper()} coordinate unchanged.'}
    return questions


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
    p.add_argument('--demos',type=Path);p.add_argument('--libero-root',required=True)
    p.add_argument('--gpu',type=int,default=4)
    p.add_argument('--decisions',type=int,default=180);p.add_argument('--size',type=int,default=512)
    p.add_argument('--grounded',action='store_true',help='Pro RGB source description and fixed external source crop')
    p.add_argument('--relation-prompts',action='store_true',help='Explicit per-channel effects and measured own tool axes; no scene targets')
    p.add_argument('--surface-context',action='store_true',help='Unselected visible RGB-D surface samples in the common world frame, not grasp targets')
    p.add_argument('--file-transport',action='store_true',help='Exact Decisions bodies are relayed through a local authorized caller over SSH files')
    p.add_argument('--coordinate-questions',action='store_true',help='Per-axis current coordinate comparisons, not precomputed signed errors')
    p.add_argument('--task-demo',type=Path,help='Archived same-task real RGB and executed actions, without residual inputs')
    p.add_argument('--adaptive-steps',action='store_true',help='Unsigned step adaptation using only categorical sign history')
    p.add_argument('--positive-frame',action='store_true',help='Translate coordinate display by a fixed scene-independent constant')
    p.add_argument('--compact',action='store_true',help='Keep only results, response choices and hashes; no rollout images or payload archives')
    p.add_argument('--example-bank',type=Path,help='Shared fixed functional demonstration assets')
    p.add_argument('--input-variant',choices=['all_examples','task_only','motion_only','task_native_frame'],default='all_examples')
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    cache=out/'cache';cache.mkdir()
    os.environ.update(LIBERO_CONFIG_PATH=args.libero_root+'/.libero-config',
        TMPDIR=str(cache),XDG_CACHE_HOME=str(cache),MUJOCO_GL='egl',MUJOCO_EGL_DEVICE_ID=str(args.gpu))
    # One lightweight renderer per GPU, with at least 1.4GiB free before allocation.
    query=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free','--format=csv,noheader,nounits'],text=True)
    free={int(r.split(',')[0]):int(r.split(',')[1]) for r in query.strip().splitlines()}
    if args.gpu not in free or free[args.gpu]<1400: raise RuntimeError('Insufficient free GPU memory for isolated renderer')
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
        profile=('compact_bank_'+args.input_variant) if args.example_bank else 'task_demo_axes_v6' if args.task_demo else ('coordinate_rgb_axes_v5' if args.coordinate_questions else ('surface_rgb_axes_v4' if args.surface_context else ('relation_rgb_axes_v3' if args.relation_prompts else ('grounded_rgb_axes_v2' if args.grounded else 'genuine_rgb_direct_axes_v1r2')))),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        plan=plan,plan_sha256=hashlib.sha256(args.plan.read_bytes()).hexdigest(),
        scene_target_or_error_inputs=False,grasp_pose_decided_by_actor=True,experience_injection=False))
    stages=plan['stages'];stage=0;grip=-1.;tick=0;previous=[];history=[];env=None
    if args.file_transport:os.environ['DECISION_MM_FILE_ONLY']='1'
    recorder=Recorder(out);api=DirectAPI({},recorder.log,'jev');api.compact=args.compact
    if args.adaptive_steps:
        api.motion=MOTION.replace('Use fine scale near contact;\nuse coarse scale for clear free-space movement.',
            'Unsigned step sizes adapt from direction history: repeated signs grow the magnitude, reversals shrink it. '
            'Translation stays within 2-20mm per axis, rotation within 1-6degrees. Choose directions only.')
    if args.file_transport:
        from decision_file_bridge import FileClient
        api.client=FileClient(out/'bridge-jobs',compact=args.compact)
    if args.example_bank:
        from libero_example_bank import load_bank
        api.demonstrations=load_bank(args.example_bank,args.task,args.input_variant)
    else:
        assert args.demos is not None, 'Provide --example-bank or --demos'
        examples=out/'examples';examples.mkdir();api.demonstrations=demonstrations(args.demos,examples)
    if args.task_demo and not args.example_bank:
        from libero_task_demonstrations import build_task_examples
        api.demonstrations+=build_task_examples(args.task_demo,out/'task-demo')
    api.previous=[]
    step_sizes=None;last_signs=None
    started=time.monotonic();result=dict(task=args.task,init=args.init,success=False,native_evaluated=False,program_finished=False)
    try:
        with contextlib.redirect_stdout(io.StringIO()):suite=benchmark.get_benchmark_dict()['libero_goal'](0)
        instruction=suite.get_task(args.task).language;english(instruction)
        env=ControlEnv(bddl_file_name=suite.get_task_bddl_file_path(args.task),
            camera_names=['agentview','robot0_eye_in_hand'],camera_heights=args.size,camera_widths=args.size,
            camera_depths=args.surface_context,control_freq=20,horizon=600,controller='OSC_POSE',initialization_noise=None)
        env.seed(0);env.reset();obs=env.set_init_state(np.asarray(suite.get_task_init_states(args.task)[args.init],float))
        for _ in range(10):obs,_,_,_=env.step(np.r_[np.zeros(6),grip]);tick+=1
        native=env.env;site=native.robots[0].eef_site_id
        def own_pose():
            return native.sim.data.site_xpos[site].copy(),native.sim.data.site_xmat[site].reshape(3,3).copy()
        def capture():
            from PIL import ImageDraw
            parts=[];p0,_=own_pose();api.surface_samples=[]
            for camera in ('agentview','robot0_eye_in_hand'):
                im=Image.fromarray(np.ascontiguousarray(obs[camera+'_image'][::-1]));b=io.BytesIO();im.save(b,format='PNG')
                raw=b.getvalue()
                if not args.compact:(out/f'{tick:04d}-{camera}-raw.png').write_bytes(raw)
                K=get_camera_intrinsic_matrix(native.sim,camera,args.size,args.size)
                T=get_camera_extrinsic_matrix(native.sim,camera)
                if args.surface_context and camera=='agentview':
                    from robosuite.utils.camera_utils import get_real_depth_map
                    depth=np.asarray(get_real_depth_map(native.sim,obs[camera+'_depth'])).squeeze()[::-1]
                    draw=ImageDraw.Draw(im)
                    for region,key in (('A','fixed_view_bbox_xyxy'),('B','receiver_fixed_view_bbox_xyxy')):
                        if key not in plan:continue
                        box=np.asarray(plan[key],float)*(args.size/512)
                        # Sample the *current visible surface* on a fixed pixel lattice.
                        # These points are not a tracked object pose, centroid, grasp point or target.
                        for j,y in enumerate(np.linspace(box[1]+4,box[3]-4,3)):
                            for i,x in enumerate(np.linspace(box[0]+4,box[2]-4,3)):
                                u,v=int(np.clip(x,0,args.size-1)),int(np.clip(y,0,args.size-1))
                                z=float(depth[v,u]);point=T@np.r_[np.linalg.solve(K,np.array([u,v,1]))*z,1]
                                if not np.isfinite(point).all() or z<=0:continue
                                label=f'{region}{j*3+i}'
                                api.surface_samples.append(dict(label=label,pixel_uv=[u,v],
                                    visible_surface_world_mm=np.round(point[:3]*1000,1).tolist()))
                                draw.ellipse((u-2,v-2,u+2,v+2),fill='#ffff00',outline='#000000')
                                draw.text((u+3,v-10),label,fill='#ffff00',stroke_width=1,stroke_fill='#000000')
                    b=io.BytesIO();im.save(b,format='PNG');raw=b.getvalue()
                raw,_,audit=overlay_gripper_axes(raw,T,K,p0,camera)
                if not args.compact:(out/f'{tick:04d}-{camera}-input.png').write_bytes(raw)
                parts.extend([dict(type='input_text',text=f'CURRENT {camera}, observation {tick}. World axes at the current gripper.'),image_part(raw)])
                if args.grounded and camera=='agentview' and 'fixed_view_bbox_xyxy' in plan:
                    # Fixed-camera articulated knob base is stationary; this crop is identity/visibility only.
                    box=np.asarray(plan['fixed_view_bbox_xyxy'],float)*(args.size/512)
                    margin=.10*args.size
                    box=[max(0,int(box[0]-margin)),max(0,int(box[1]-margin)),
                         min(args.size,int(box[2]+margin)),min(args.size,int(box[3]+margin))]
                    crop=im.crop(box).resize((512,512));b=io.BytesIO();crop.save(b,format='PNG')
                    if not args.compact:(out/f'{tick:04d}-source-crop.png').write_bytes(b.getvalue())
                    parts.extend([dict(type='input_text',text='CURRENT fixed-view source detail; same observation, zoom only. '+plan['source_description']),image_part(b.getvalue())])
            return parts
        for decision in range(args.decisions):
            import shutil
            if shutil.disk_usage(out).free<8*1024**3:raise RuntimeError('Native artifact storage guard: below8GiB free')
            if tick+4>600:break
            if time.monotonic()-started>1800:raise TimeoutError('Native episode wall budget')
            api.current=capture();api.previous=previous;api.tick=tick
            state=dict(task=instruction,stage=stages[stage],stage_order=stages,
                gripper_joints=obs['robot0_gripper_qpos'].tolist(),last_actions=history[-4:],
                next_stage=stages[min(stage+1,len(stages)-1)])
            if args.grounded:
                state['source_description']=plan.get('source_description','Identify the named object from current images.')
                state['visual_cues']=plan.get('relevant_visual_cues',[])
            if args.relation_prompts:
                own_p,own_R=own_pose()
                # Own hand geometry, never a target orientation or object pose.
                gripper=native.robots[0].gripper
                centres={side:np.mean([native.sim.data.geom_xpos[native.sim.model.geom_name2id(n)]
                    for n in gripper.important_geoms[side]],axis=0)
                    for side in ('left_fingerpad','right_fingerpad')}
                closing=centres['right_fingerpad']-centres['left_fingerpad']
                state['own_tool_geometry']=dict(
                    closing_axis_world_unit=(closing/max(np.linalg.norm(closing),1e-10)).tolist(),
                    grip_site_local_Z_world_unit=own_R[:,2].tolist(),
                    meaning='Measured own-hand axes only. Compare actual finger faces with the object in RGB; these are not desired axes.')
            if args.surface_context:
                own_p,_=own_pose()
                state['own_gripper_world_mm']=np.round(own_p*1000,1).tolist()
                state['visible_surface_samples']=api.surface_samples
                state['surface_sample_meaning']=('Labelled dots are current RGB-D visible surface points in the same fixed world frame as the gripper. '
                    'Regions A/B are initial fixed-camera identity windows, NOT object tracking; after an object moves a dot may show background. '
                    'Use CURRENT RGB to identify what each dot actually lies on. These are not recommended grasp points or desired poses. '
                    'Depth/occlusion boundaries may mix surfaces. First choose a suitable physical grasp or support relationship from RGB, '
                    'then use the matching surface coordinates and own axes to interpret directions. No desired orientation is computed.')
                if args.positive_frame:
                    offset=np.array([2000.,2000.,0.])
                    state['own_gripper_world_mm']=np.round(own_p*1000+offset).tolist()
                    state['visible_surface_samples']=[dict(v,visible_surface_world_mm=np.round(np.array(v['visible_surface_world_mm'])+offset).tolist()) for v in api.surface_samples]
                    state['coordinate_frame_note']='All displayed point and hand coordinates use the SAME fixed translated frame: native world XYZ plus [2000,2000,0] mm. Axis directions are unchanged. This constant is independent of any scene object or current hand position.'
            api.sent_state=state
            questions={}
            for a,label in zip(('x','y','z','rx','ry','rz'),('X translation','Y translation','Z translation','roll about world X','pitch about world Y','yaw about world Z')):
                questions[a]=dict(type='choice',instructions=f'Which {label} direction helps achieve the CURRENT stage goal from the actual images? Use motion examples for the physical effect. Hold if this channel needs no change.',
                    criteria={'positive':'Positive direction on this channel.','negative':'Negative direction on this channel.','hold':'No increment on this channel.'})
            if args.relation_prompts:
                effects={'x':('move forward along world +X','move backward along world -X'),
                    'y':('move left along world +Y','move right along world -Y'),
                    'z':('move up along world +Z','move down along world -Z'),
                    'rx':('right-hand rotation about fixed world +X','opposite rotation about fixed world X'),
                    'ry':('right-hand rotation about fixed world +Y','opposite rotation about fixed world Y'),
                    'rz':('counterclockwise viewed from above, about world Z','clockwise viewed from above, about world Z')}
                for a,(positive,negative) in effects.items():
                    questions[a]['instructions']=(f'Current goal: {stages[stage]["goal"]} '
                        f'For {a} only, compare the physical fingers and the task object in CURRENT images. '
                        f'Would {positive}, {negative}, or no change improve that relationship? '
                        'For translation use both views and the current gripper axis arrows; wrist images move with the hand. '
                        'For rotation compare finger approach/closing direction against the visible grasp or support geometry. '
                        'Use the independent BEFORE/AFTER example to interpret the channel. '
                        'Hold means this channel is already suitable, not that the whole task is done. '
                        'Choose all channels from this same current scene, without treating a stage name as completed.')
                    questions[a]['criteria']={'positive':positive+'.','negative':negative+'.',
                        'hold':'Keep this channel unchanged; its current relationship is suitable.'}
            questions['gripper']=dict(type='choice',instructions='Choose the gripper command for the current manipulation.',criteria={'open':'Open the fingers.','close':'Close or retain the grasp.','hold':'Retain the preceding gripper command.'})
            questions['scale']=dict(type='choice',instructions='Choose movement scale from visible clearance and required precision.',criteria={'coarse':'Free space: 20mm and 10degrees maximum per channel.','fine':'Near contact or alignment: 4mm and 2degrees maximum per channel.'})
            questions['transition']=dict(type='choice',instructions='Judge the observable exit condition for the CURRENT stage. Advance only when it is visibly satisfied. Advance executes no motion this turn.',criteria={'continue':'Continue current stage.','advance':'Current stage complete; enter next stage, or finish at the final stage.','restart':'Return to the first stage to recover.'})
            if args.coordinate_questions:
                if not args.surface_context:raise ValueError('Coordinate questions require current visible surface context')
                questions=coordinate_questions(state,questions)
            if args.adaptive_steps:
                questions.pop('scale')
                state['step_policy']='Direction-history adaptation only; no object-target residual controls magnitude. The last execution contains commanded and measured effects.'
            answer=api.post('/systemone',dict(model='gpt-6-luna',state=state,questions=questions))
            choices={k:v['choice'] for k,v in answer['answers'].items()};before_p,before_R=own_pose()
            previous=[dict(type='input_text',text='PREVIOUS observation, before the last executed command; compare with CURRENT.'),
                *[dict(x,type=x['type'],**({'text':x['text'].replace('CURRENT','PREVIOUS')} if x['type']=='input_text' else {})) for x in api.current]]
            if choices['transition']=='advance':
                if stage==len(stages)-1:result['program_finished']=True;break
                stage+=1;step_sizes=None;last_signs=None
                history.append(dict(choices=choices,execution='No physical action; stage advanced'));continue
            if choices['transition']=='restart':stage=0
            if choices['gripper']!='hold':grip=1. if choices['gripper']=='close' else -1.
            signs=np.array([{'negative':-1,'hold':0,'positive':1}[choices[a]] for a in ('x','y','z','rx','ry','rz')])
            step_m,step_r=(.020,np.deg2rad(10)) if choices.get('scale')=='coarse' else (.004,np.deg2rad(2))
            if args.adaptive_steps:
                if step_sizes is None:step_sizes=np.r_[np.full(3,.006),np.full(3,np.deg2rad(3))]
                if last_signs is not None:
                    for i in range(6):
                        if signs[i] and signs[i]==last_signs[i]:step_sizes[i]*=1.25
                        elif signs[i] and last_signs[i] and signs[i]!=last_signs[i]:step_sizes[i]*=.5
                step_sizes=np.clip(step_sizes,np.r_[np.full(3,.002),np.full(3,np.deg2rad(1))],
                    np.r_[np.full(3,.02),np.full(3,np.deg2rad(6))])
                last_signs=signs.copy();dp=signs[:3]*step_sizes[:3];dr=signs[3:]*step_sizes[3:]
            else:dp=signs[:3]*step_m;dr=signs[3:]*step_r
            dp*=min(1.,.03/max(np.linalg.norm(dp),1e-10));dr*=min(1.,.25/max(np.linalg.norm(dr),1e-10))
            target_p=before_p+dp;target_R=Rotation.from_rotvec(dr).as_matrix()@before_R
            for _ in range(4):
                pos,rot=own_pose();u_p=.7*(target_p-pos);u_r=.7*Rotation.from_matrix(target_R@rot.T).as_rotvec()
                action=np.r_[np.clip(u_p/.05,-1,1),np.clip(u_r/.5,-1,1),grip]
                obs,_,_,_=env.step(action);tick+=1
            after_p,after_R=own_pose()
            row=dict(decision=decision,native_steps=tick,stage=stage,choices=choices,
                commanded_translation_mm=(dp*1000).tolist(),commanded_rotation_world_deg=np.rad2deg(dr).tolist(),
                measured_translation_mm=((after_p-before_p)*1000).tolist(),
                measured_rotation_world_deg=np.rad2deg(Rotation.from_matrix(after_R@before_R.T).as_rotvec()).tolist())
            history.append(row)
            with (out/'execution.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
            print(json.dumps(row),flush=True)
        capture()
        # Evaluator is read only here, after the final action; never sent to either model.
        result['success']=bool(env.check_success())
        result['native_evaluated']=True
    except Exception as error:
        result['error']=dict(type=type(error).__name__,message=(str(error).replace(api.credential,'[redacted]') if api.credential else str(error))[:600])
        raise
    finally:
        result.update(native_steps=tick,seconds=time.monotonic()-started,api_responses=len(list((out/'decision-api').glob('*/response.json'))))
        save(out/'result.json',result)
        if env is not None:env.close()
        print(json.dumps(result),flush=True)


if __name__=='__main__':main()

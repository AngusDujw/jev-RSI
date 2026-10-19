"""Camera-assisted categorical Decisions control with audited observation origins."""
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
from libero_numeric_axes import reference_difference

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
        if getattr(self,'record_evidence',False):
            # Archive the exact request without duplicating base64 images each turn.
            evidence=self.folder.parent/'evidence';assets=evidence/'images';assets.mkdir(parents=True,exist_ok=True)
            readable=json.loads(raw)
            for part in readable['input'][0]['content']:
                if part['type']=='input_image':
                    data=base64.b64decode(part.pop('image_url').split(',',1)[1])
                    name=hashlib.sha256(data).hexdigest()+'.png'
                    if not (assets/name).exists():(assets/name).write_bytes(data)
                    part['image_file']='images/'+name
            save(evidence/f'{self.calls-1:04d}-request.json',readable)
        images=[hashlib.sha256(base64.b64decode(p['image_url'].split(',',1)[1])).hexdigest()
            for p in payload['input'][0]['content'] if p['type']=='input_image']
        save(folder/'request-summary.json',dict(model='gpt-6-luna',body_sha256=hashlib.sha256(raw).hexdigest(),
            image_sha256=images,question_options={k:list(v['criteria']) for k,v in original['questions'].items()},
            stage=original['state']['stage'],request_purpose=original['state'].get('request_purpose','multimodal_policy'),native_tick=self.tick,protocol_sha256=getattr(self,'protocol_sha256',None)))
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
        if sent['state'].get('request_purpose')=='multimodal_reference_selection':
            from libero_reference_decision import reference_payload
            payload=reference_payload(sent,self.current,self.stage_goal_reference)
            self.image_count=sum(x['type']=='input_image' for x in payload['input'][0]['content'])
            return payload
        if sent['state'].get('request_purpose')=='multimodal_rotation_axes':
            from libero_rotation_decision import rotation_payload
            payload=rotation_payload(sent,self.current,self.rotation_effect_examples,self.stage_goal_reference)
            self.image_count=sum(x['type']=='input_image' for x in payload['input'][0]['content'])
            return payload
        if sent['state'].get('request_purpose') in ('formal_stage_classification','visual_stage_classification'):
            from libero_stage_decision import stage_payload
            payload=stage_payload(sent,self.current,getattr(self,'stage_goal_reference',[]))
            self.image_count=sum(x['type']=='input_image' for x in payload['input'][0]['content'])
            return payload
        if sent['state'].get('request_purpose')=='text_only_numeric_axis_classification':
            from libero_numeric_axes import numeric_payload
            self.image_count=0
            return numeric_payload(sent)
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
        return dict(computed_robot_goal_pose_supplied=False,computed_orientation_error_supplied=False,
                    relative_position_feedback_enabled=getattr(self,'actor_attention',False),
                    examples='Measured own-robot primitive effects',
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
    p.add_argument('--wall-seconds',type=int,default=7200)
    p.add_argument('--horizon',type=int,default=600,choices=[600,1200],help='Native physical-step budget; 1200 is an extended development condition, not the standard 600-step evaluation');p.add_argument('--decisions',type=int,default=180);p.add_argument('--size',type=int,default=512)
    p.add_argument('--grounded',action='store_true',help='Pro RGB source description and fixed external source crop')
    p.add_argument('--relation-prompts',action='store_true',help='Explicit per-channel effects and measured own tool axes; no scene targets')
    p.add_argument('--surface-context',action='store_true',help='Unselected visible RGB-D surface samples in the common world frame, not grasp targets')
    p.add_argument('--file-transport',action='store_true',help='Exact Decisions bodies are relayed through a local authorized caller over SSH files')
    p.add_argument('--coordinate-questions',action='store_true',help='Per-axis current coordinate comparisons, not precomputed signed errors')
    p.add_argument('--task-demo',type=Path,help='Archived same-task real RGB and executed actions, without residual inputs')
    p.add_argument('--adaptive-steps',action='store_true',help='Unsigned step adaptation using only categorical sign history')
    p.add_argument('--positive-frame',action='store_true',help='Translate coordinate display by a fixed scene-independent constant')
    p.add_argument('--compact',action='store_true',help='Keep only results, response choices and hashes; no rollout images or payload archives')
    p.add_argument('--record-evidence',action='store_true',help='Save actual images and deduplicated full model inputs even with compact transport')
    p.add_argument('--replay',type=Path,help='Replay archived executed commands without calling any model; diagnostic only')
    p.add_argument('--execution-steps',type=int,default=4,choices=range(4,21),help='Own-pose servo steps per categorical decision')
    p.add_argument('--live-surfaces',action='store_true',help='Current RGB component surface samples instead of stale fixed source-window dots')
    p.add_argument('--actor-attention',action='store_true',help='Decision model chooses a visible reference and orientation relationship before deciding action axes')
    p.add_argument('--focused-questions',action='store_true',help='Three readable source labels, stage-local examples and short legacy-style axis questions')
    p.add_argument('--relative-step-scale',action='store_true',help='Unsigned translation magnitude from actor-selected observed feature differences; never choose signs')
    p.add_argument('--numeric-xy',action='store_true',help='Explicit legacy-style coarse X/Y reference alignment; Z and rotations remain visual/stage judgements')
    p.add_argument('--reference-history',action='store_true',help='Retain actor visual choices within the episode, never stale scene coordinates or cross-run experience')
    p.add_argument('--protocol-file',type=Path,help='English stage/question overrides; no action commands or coordinate targets')
    p.add_argument('--live-protocol',action='store_true',help='Development only: reload and archive protocol revisions in one persistent native episode')
    p.add_argument('--scoped-reference-call',action='store_true',help='Current-image feature selection without motor demonstrations, history or world-position values')
    p.add_argument('--fin-central-samples',action='store_true',help='Additional actual visible upper-fin middle/quarter surface samples, not a hidden pivot')
    p.add_argument('--held-example-bank',type=Path,help='Immutable actual balanced held-object rotation examples for the separate rotation call')
    p.add_argument('--rotation-effect-hints',action='store_true',help='Observed-line local rotation effects only, no desired axis or error')
    p.add_argument('--separate-rotation-call',action='store_true',help='Independent rotation-only visual Decisions call with current shapes and actual examples')
    p.add_argument('--visible-shape-features',action='store_true',help='Current RGB-D bottle axis and observed wood planes; never desired orientation or error')
    p.add_argument('--formal-stage-call',action='store_true',help='Ask a scoped text-only Decisions stage question after visual motor choices for phases with explicit rules')
    p.add_argument('--numeric-axis-call',action='store_true',help='Let Decisions classify selected numeric XYZ references in a separate text-only request before multimodal rotation/grip/stage decisions')
    p.add_argument('--reference-only',action='store_true',help='Select visual features without the ambiguous intermediate orientation-relation label')
    p.add_argument('--overview-camera',choices=['sideview','frontview','birdview'],help='Additional public fixed RGB camera for whole-hand/object coverage; no scene-state input')
    p.add_argument('--goal-example',action='store_true',help='Include an actual archived final object-support relationship during orientation/operation and inspection')
    p.add_argument('--raised-fin-surfaces',action='store_true',help='Propose current highest visible black surfaces in the knob identity region, never a true pose or target angle')
    p.add_argument('--part-questions',action='store_true',help='Name the actual grasp/placement part explicitly in the visual-reference question')
    p.add_argument('--retain-rotation-examples',action='store_true',help='Include independent yaw/pitch/roll before-after cards in each relevant later request; the API has no implicit image memory')
    p.add_argument('--stage-motion',action='store_true',help='Measured own-hand displacement since entering the current stage, never object or desired motion')
    p.add_argument('--receiver-surfaces',action='store_true',help='Current receiver wood-component RGB-D candidates instead of a window lattice')
    p.add_argument('--pad-outlines',action='store_true',help='Project public own inner pad facets on each current RGB image')
    p.add_argument('--visual-near-grasp',action='store_true',help='Near-grasp XY judges finger capture in RGB, not zero skin displacement')
    p.add_argument('--numeric-z',action='store_true',help='Short reference-height sign criteria during near approach; actor still selects the sign')
    p.add_argument('--track-selected',action='store_true',help='Track the actor-selected RGB feature with forward/backward optical flow and fresh depth')
    p.add_argument('--robot-self-mask',action='store_true',help='Reject possible own-robot RGB-D surfaces and anchor the stationary knob identity window')
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
    protocol_hash=None
    if args.live_protocol and not args.protocol_file:raise ValueError('Live protocol requires a file')
    if args.protocol_file:protocol_hash=hashlib.sha256(args.protocol_file.read_bytes()).hexdigest()
    save(out/'manifest.json',dict(task=args.task,init=args.init,gpu=args.gpu,
        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).resolve().parents[2],text=True).strip(),
        profile=('compact_bank_'+args.input_variant) if args.example_bank else 'task_demo_axes_v6' if args.task_demo else ('coordinate_rgb_axes_v5' if args.coordinate_questions else ('surface_rgb_axes_v4' if args.surface_context else ('relation_rgb_axes_v3' if args.relation_prompts else ('grounded_rgb_axes_v2' if args.grounded else 'genuine_rgb_direct_axes_v1r2')))),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        execution_steps=args.execution_steps,horizon=args.horizon,record_evidence=args.record_evidence,
        live_surfaces=args.live_surfaces,actor_attention=args.actor_attention,diagnostic_replay=bool(args.replay),
        focused_questions=args.focused_questions,
        relative_step_scale=args.relative_step_scale,
        numeric_xy=args.numeric_xy,
        reference_history=args.reference_history,
        protocol_file=str(args.protocol_file) if args.protocol_file else None,
        initial_protocol_sha256=protocol_hash,live_protocol=args.live_protocol,
        robot_self_mask=args.robot_self_mask,track_selected=args.track_selected,pad_outlines=args.pad_outlines,numeric_z=args.numeric_z,visual_near_grasp=args.visual_near_grasp,receiver_surfaces=args.receiver_surfaces,stage_motion=args.stage_motion,retain_rotation_examples=args.retain_rotation_examples,part_questions=args.part_questions,raised_fin_surfaces=args.raised_fin_surfaces,overview_camera=args.overview_camera,goal_example=args.goal_example,numeric_axis_call=args.numeric_axis_call,reference_only=args.reference_only,scoped_reference_call=args.scoped_reference_call,fin_central_samples=args.fin_central_samples,held_example_bank=str(args.held_example_bank.resolve()) if args.held_example_bank else None,held_example_bank_sha256=hashlib.sha256(args.held_example_bank.read_bytes()).hexdigest() if args.held_example_bank else None,formal_stage_call=args.formal_stage_call,visible_shape_features=args.visible_shape_features,separate_rotation_call=args.separate_rotation_call,rotation_effect_hints=args.rotation_effect_hints,
        plan=plan,plan_sha256=hashlib.sha256(args.plan.read_bytes()).hexdigest(),
        privileged_scene_targets_or_errors=False,camera_derived_surface_geometry=args.surface_context,
        actor_selected_relative_feedback=args.actor_attention,computed_orientation_error=False,
        grasp_pose_decided_by_actor=True,experience_injection=False))
    stages=plan['stages'];stage=0;grip=-1.;tick=0;previous=[];history=[];visual_history=[];env=None
    if args.file_transport:os.environ['DECISION_MM_FILE_ONLY']='1'
    recorder=Recorder(out);api=DirectAPI({},recorder.log,'jev');api.compact=args.compact
    api.record_evidence=args.record_evidence
    api.actor_attention=args.actor_attention
    replay_rows=[json.loads(s) for s in args.replay.read_text().splitlines()] if args.replay else None
    if args.adaptive_steps:
        api.motion=MOTION.replace('Use fine scale near contact;\nuse coarse scale for clear free-space movement.',
            'Unsigned step sizes adapt from direction history: repeated signs grow the magnitude, reversals shrink it. '
            'Translation stays within 2-20mm per axis, rotation within 1-6degrees. Choose directions only.')
    if args.overview_camera:
        api.motion=getattr(api,'motion',MOTION)+' The CURRENT '+args.overview_camera+' is an additional fixed camera showing the whole held object and support. Its own world-axis arrows use current public calibration; image directions differ from agentview and the moving wrist. The source-detail crop is only a zoom of agentview, not another camera.'
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
    tracker=None
    if args.live_surfaces:
        from libero_visual_surfaces import SurfaceTracker
        tracker=SurfaceTracker('knob' if args.task==1383 else 'bottle',np.asarray(plan['fixed_view_bbox_xyxy'])*args.size/512,sparse=args.focused_questions,anchor_stationary=args.robot_self_mask and args.task==1383,track_selected=args.track_selected,raised_feature=args.raised_fin_surfaces and args.task==1383,shape_features=args.visible_shape_features,central_samples=args.fin_central_samples)
    receiver_tracker=None
    if args.receiver_surfaces and 'receiver_fixed_view_bbox_xyxy' in plan:
        from libero_visual_surfaces import SurfaceTracker
        receiver_tracker=SurfaceTracker('rack',np.asarray(plan['receiver_fixed_view_bbox_xyxy'])*args.size/512,anchor_stationary=True,shape_features=args.visible_shape_features,central_samples=args.fin_central_samples)
    full_demonstrations=api.demonstrations[:]
    rotation_demonstrations=[]
    for i,part in enumerate(full_demonstrations):
        if part['type']=='input_text' and any(part['text'].startswith('Actual independently reset +'+axis+' demonstration.') for axis in ('yaw','pitch','roll')):
            if i+1>=len(full_demonstrations) or full_demonstrations[i+1]['type']!='input_image':raise ValueError('Rotation example lacks its actual before/after image')
            rotation_demonstrations+=full_demonstrations[i:i+2]
    if args.retain_rotation_examples and len(rotation_demonstrations)!=6:raise ValueError('Retained rotation examples require all three independent actual motion cards')
    goal_demonstration=[]
    if args.goal_example:
        goal_phase='verify' if args.task==1383 else 'release'
        for i,part in enumerate(full_demonstrations):
            if part['type']=='input_text' and 'phase '+goal_phase+'.' in part.get('text',''):
                goal_demonstration=[dict(type='input_text',text='ARCHIVED goal-relationship example from a DIFFERENT episode, BEFORE left and AFTER right. Use the actual final object/receiver or operated-control appearance as a visual task example. This is not the CURRENT scene, not a target coordinate, and not a rendered angle answer. Current geometry and all motion signs must be judged from CURRENT images.'),full_demonstrations[i+1]]
                break
        if not goal_demonstration:raise ValueError('Actual goal-relationship example missing')
    api.stage_goal_reference=goal_demonstration
    api.rotation_effect_examples=rotation_demonstrations
    if args.held_example_bank:
        from libero_example_bank import load_bank
        if args.task!=1458 or not args.separate_rotation_call:
            raise ValueError('Held-bottle examples require the separate bottle rotation call')
        held=load_bank(args.held_example_bank,args.task)
        if sum(p['type']=='input_image' for p in held)!=3:
            raise ValueError('Expected three balanced signed-axis example cards')
        api.rotation_effect_examples=held
    cameras=['agentview','robot0_eye_in_hand']+([args.overview_camera] if args.overview_camera else [])
    step_sizes=None;last_signs=None
    started=time.monotonic();result=dict(task=args.task,init=args.init,success=False,native_evaluated=False,program_finished=False)
    try:
        with contextlib.redirect_stdout(io.StringIO()):suite=benchmark.get_benchmark_dict()['libero_goal'](0)
        instruction=suite.get_task(args.task).language;english(instruction)
        env=ControlEnv(bddl_file_name=suite.get_task_bddl_file_path(args.task),
            camera_names=cameras,camera_heights=args.size,camera_widths=args.size,
            camera_depths=args.surface_context,control_freq=20,horizon=args.horizon,controller='OSC_POSE',initialization_noise=None)
        env.seed(0);env.reset();obs=env.set_init_state(np.asarray(suite.get_task_init_states(args.task)[args.init],float))
        for _ in range(10):obs,_,_,_=env.step(np.r_[np.zeros(6),grip]);tick+=1
        native=env.env;site=native.robots[0].eef_site_id
        def own_pose():
            return native.sim.data.site_xpos[site].copy(),native.sim.data.site_xmat[site].reshape(3,3).copy()
        def capture():
            from PIL import ImageDraw
            parts=[];p0,_=own_pose();api.surface_samples=[];api.source_component=None;api.receiver_component=None
            for camera in cameras:
                im=Image.fromarray(np.ascontiguousarray(obs[camera+'_image'][::-1]));b=io.BytesIO();im.save(b,format='PNG')
                raw=b.getvalue()
                if not args.compact or args.record_evidence:(out/f'{tick:04d}-{camera}-raw.png').write_bytes(raw)
                K=get_camera_intrinsic_matrix(native.sim,camera,args.size,args.size)
                T=get_camera_extrinsic_matrix(native.sim,camera)
                if args.surface_context and camera=='agentview':
                    from robosuite.utils.camera_utils import get_real_depth_map
                    depth=np.asarray(get_real_depth_map(native.sim,obs[camera+'_depth'])).squeeze()[::-1]
                    draw=ImageDraw.Draw(im)
                    reject_own=None
                    if args.robot_self_mask:
                        from libero_robot_mask import own_geometry_rejector
                        reject_own=own_geometry_rejector(native)
                    if tracker is not None:
                        api.source_component,current_samples=tracker.observe(np.asarray(im),depth,K,T,reject_own=reject_own)
                        api.surface_samples.extend(current_samples)
                        for sample in current_samples:
                            u,v=sample['pixel_uv'];draw.ellipse((u-2,v-2,u+2,v+2),fill='#00ffff',outline='#000000')
                            if args.focused_questions:
                                from PIL import ImageFont
                                x=min(args.size-32,api.source_component['bbox_xyxy'][2]+15)
                                y=max(2,api.source_component['bbox_xyxy'][1]+(3 if sample['label']=='S' else int(sample['label'][1:]))*25)
                                draw.line((u,v,x,y+8),fill='#00ffff',width=1)
                                draw.text((x,y),sample['label'],font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',16),fill='#00ffff',stroke_width=1,stroke_fill='#000000')
                            else:draw.text((u+3,v-8),sample['label'],fill='#00ffff',stroke_width=1,stroke_fill='#000000')
                    for region,key in (('A','fixed_view_bbox_xyxy'),('B','receiver_fixed_view_bbox_xyxy')):
                        if tracker is not None and region=='A':continue
                        if key not in plan:continue
                        if region=='B' and receiver_tracker is not None:
                            api.receiver_component,receiver_samples=receiver_tracker.observe(np.asarray(im),depth,K,T,reject_own=reject_own)
                            for j,sample in enumerate(receiver_samples):
                                sample['label']='B'+str(j);api.surface_samples.append(sample)
                                u,v=sample['pixel_uv'];draw.ellipse((u-2,v-2,u+2,v+2),fill='#ffff00',outline='#000000')
                                draw.text((u+3,v-10),sample['label'],fill='#ffff00',stroke_width=1,stroke_fill='#000000')
                            continue
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
                if args.pad_outlines:
                    from libero_pad_overlay import overlay_pad_faces
                    overlay_pad_faces(im,native,K,T)
                    b=io.BytesIO();im.save(b,format='PNG');raw=b.getvalue()
                raw,_,audit=overlay_gripper_axes(raw,T,K,p0,camera)
                if not args.compact or args.record_evidence:(out/f'{tick:04d}-{camera}-input.png').write_bytes(raw)
                parts.extend([dict(type='input_text',text=f'CURRENT {camera}, observation {tick}. World axes at the current gripper.'+(
                    ' Magenta PAD-L/PAD-R outlines are projections of measured own inner finger-pad faces, not target points or contact evidence. Projected edges may be occluded in the actual RGB.' if args.pad_outlines else '')),image_part(raw)])
                if args.grounded and camera=='agentview' and 'fixed_view_bbox_xyxy' in plan:
                    crop_unknown=tracker is not None and api.source_component.get('status')!='candidate'
                    # Fixed-camera articulated knob base is stationary; this crop is identity/visibility only.
                    box=(tracker.box.copy() if crop_unknown else np.asarray(api.source_component['bbox_xyxy'],float) if tracker is not None
                         else np.asarray(plan['fixed_view_bbox_xyxy'],float)*(args.size/512))
                    margin=.10*args.size
                    box=[max(0,int(box[0]-margin)),max(0,int(box[1]-margin)),
                         min(args.size,int(box[2]+margin)),min(args.size,int(box[3]+margin))]
                    crop=im.crop(box).resize((512,512));b=io.BytesIO();crop.save(b,format='PNG')
                    if not args.compact or args.record_evidence:(out/f'{tick:04d}-source-crop.png').write_bytes(b.getvalue())
                    caption=('CURRENT detail from the last image-space identity window. Source may be occluded; no current source geometry is implied. '
                        if crop_unknown else 'CURRENT fixed-view source detail; same observation, zoom only. ')
                    parts.extend([dict(type='input_text',text=caption+plan['source_description']),image_part(b.getvalue())])
            if args.record_evidence:
                with (out/'perception.jsonl').open('a') as file:
                    file.write(json.dumps(dict(native_tick=tick,source_component=api.source_component,
                        visible_surface_samples=api.surface_samples,receiver_component=api.receiver_component,frame='native_world_mm_before_optional_display_offset',
                        robot_self_mask=args.robot_self_mask))+'\n')
            return parts
        stage_origin_p,stage_origin_R=own_pose();stage_origin_tick=tick
        for decision in range(args.decisions):
            import shutil
            if shutil.disk_usage(out).free<8*1024**3:raise RuntimeError('Native artifact storage guard: below8GiB free')
            if tick+args.execution_steps>args.horizon:break
            if replay_rows is not None and decision>=len(replay_rows):break
            if time.monotonic()-started>args.wall_seconds:raise TimeoutError('Native episode wall budget')
            protocol={}
            if args.protocol_file:
                raw_protocol=args.protocol_file.read_bytes();digest=hashlib.sha256(raw_protocol).hexdigest()
                if not args.live_protocol and digest!=protocol_hash:raise ValueError('Frozen protocol changed during evaluation')
                protocol=json.loads(raw_protocol);english(protocol)
                if set(protocol)-{'revision','stage_overrides','question_templates','axis_bands_mm','numeric_axis_intervals_mm','stage_decision_rules','visual_stage_rules'}:raise ValueError('Unsupported protocol field')
                if any(not isinstance(v,(int,float)) or not 1<=v<=20 for v in protocol.get('axis_bands_mm',{}).values()):raise ValueError('Invalid positioning band')
                archive=out/'protocols';archive.mkdir(exist_ok=True)
                if not (archive/(digest+'.json')).exists():(archive/(digest+'.json')).write_bytes(raw_protocol)
                api.protocol_sha256=digest
            api.current=capture();api.previous=previous;api.tick=tick
            state=dict(task=instruction,stage=stages[stage],stage_order=stages,
                gripper_joints=obs['robot0_gripper_qpos'].tolist(),
                last_actions=[{k:v for k,v in row.items() if not k.startswith(('own_position_','own_rotation_'))} for row in history[-4:]],
                next_stage=stages[min(stage+1,len(stages)-1)])
            if args.stage_motion:
                p_now,R_now=own_pose()
                state['stage_own_motion']=dict(physical_steps=tick-stage_origin_tick,translation_world_mm=np.round((p_now-stage_origin_p)*1000,1).tolist(),
                    relative_world_rotvec_deg=np.round(np.rad2deg(Rotation.from_matrix(R_now@stage_origin_R.T).as_rotvec()),1).tolist(),
                    meaning='Measured own-hand motion since stage entry only, never object motion, target angle, contact or task completion.')
            if args.stage_motion:
                comparisons=[]
                for row in [r for r in history if 'commanded_translation_mm' in r][-3:]:
                    cmd=np.asarray(row['commanded_translation_mm']);actual=np.asarray(row['measured_translation_mm']);squared=float(cmd@cmd)
                    comparisons.append(dict(commanded_translation_mm=cmd.tolist(),measured_translation_mm=actual.tolist(),
                        commanded_rotation_world_deg=row['commanded_rotation_world_deg'],measured_rotation_world_deg=row['measured_rotation_world_deg'],
                        commanded_length_mm=round(float(np.linalg.norm(cmd)),2),measured_length_mm=round(float(np.linalg.norm(actual)),2),
                        projected_motion_gain=round(float(actual@cmd)/squared,3) if squared>1 else None))
                state['recent_own_execution_comparison']=comparisons
                state['execution_comparison_meaning']='Measured own motion versus own commands only. A low gain is poor execution progress, not a contact flag or a reason to assume a particular scene obstacle.'
            if args.focused_questions:
                state.pop('stage_order');state.pop('next_stage');state['last_actions']=state['last_actions'][-1:]
                phase=('approach' if 'Align above' in stages[stage]['name'] and 'rack' not in stages[stage]['name'] else
                    'orient_receiver' if 'rack' in stages[stage]['name'] and 'Align' in stages[stage]['name'] else
                    'contact' if 'Descend' in stages[stage]['name'] and args.task==1383 else
                    'grasp' if stages[stage]['name']=='Close' or 'Descend' in stages[stage]['name'] else
                    'lift' if stages[stage]['name']=='Lift' else 'turn' if stages[stage]['name']=='Turn' else
                    'lower' if 'Lower' in stages[stage]['name'] else 'release')
                if stages[stage].get('stage_key')=='inspect':phase='inspect'
                api.demonstrations=full_demonstrations[:12] if decision<3 else []
                if args.retain_rotation_examples and decision>=3 and phase in ('approach','contact','grasp','turn','orient_receiver','lower'):
                    api.demonstrations=rotation_demonstrations[:]
                for index,part in enumerate(full_demonstrations):
                    if part['type']=='input_text' and 'phase '+phase+'.' in part['text']:
                        api.demonstrations+=full_demonstrations[index:index+2]
                if args.goal_example and phase in ('turn','orient_receiver','lower','inspect'):
                    api.demonstrations+=goal_demonstration
            if args.reference_history:
                state['recent_actor_visual_choices']=visual_history[-3:]
                state['reference_continuity']='These are your earlier choices in THIS episode, not current geometry. Keep a consistent physical grasp/support part while the stage remains unchanged and fresh RGB confirms it. Current C labels are sampled pixels, not persistent material landmarks. Change the chosen part when current evidence warrants it; never reuse an old XYZ estimate.'
            if protocol:
                key=state['stage'].get('stage_key','')
                override=protocol.get('stage_overrides',{}).get(key,{})
                if set(override)-{'goal','exit','control_contract'}:raise ValueError('Protocol can override stage semantics only')
                state['stage']={**state['stage'],**override}
            if args.grounded:
                state['source_description']=plan.get('source_description','Identify the named object from current images.')
                state['visual_cues']=plan.get('relevant_visual_cues',[])
                if args.focused_questions:state.pop('visual_cues')
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
                state['own_tool_geometry']['pad_centre_separation_mm']=float(np.linalg.norm(closing)*1000)
                state['own_tool_geometry']['last_gripper_command']='close' if grip>0 else 'open'
                state['own_tool_geometry']['reference_description']='Position is the measured robot grip_site between the fingers, not wrist housing or a visible object point. Pad-centre separation includes pad thickness and is not a contact sensor.'
                if args.focused_questions:
                    def axis_words(v):
                        i=int(np.argmax(abs(v)));return ('+' if v[i]>=0 else '-')+'XYZ'[i] if abs(v[i])>.8 else 'oblique; use current RGB and unit vector'
                    state['own_tool_geometry']['fingers_point_approximately']=axis_words(own_R[:,2])
                    state['own_tool_geometry']['fingers_close_across_approximately']=axis_words(closing/max(np.linalg.norm(closing),1e-10))
            if args.surface_context:
                own_p,_=own_pose()
                state['own_gripper_world_mm']=np.round(own_p*1000,1).tolist()
                state['visible_surface_samples']=api.surface_samples
                if receiver_tracker is not None:
                    state['receiver_component']=api.receiver_component
                    state['receiver_candidate_meaning']='B dots are current brown RGB-component surfaces in the initial rack identity region, after own-robot rejection. Verify actual rack wood and choose the slatted cradle rather than an upright/edge. A colour match is not a semantic guarantee or a target pose.'
                state['surface_sample_meaning']=('Labelled dots are current RGB-D visible surface points in the same fixed world frame as the gripper. '
                    'Regions A/B are initial fixed-camera identity windows, NOT object tracking; after an object moves a dot may show background. '
                    'Use CURRENT RGB to identify what each dot actually lies on. These are not recommended grasp points or desired poses. '
                    'Depth/occlusion boundaries may mix surfaces. First choose a suitable physical grasp or support relationship from RGB, '
                    'then use the matching surface coordinates and own axes to interpret directions. No desired orientation is computed.')
                if tracker is not None:
                    state['source_component']=api.source_component
                    state['surface_sample_meaning']=('C dots lie on a CURRENT colour component candidate, tracked from RGB only. '
                        'Verify that this is the task object in current RGB; a surface is not an object centre or desired grasp. '
                        'S, when present, is your previous selection matched in CURRENT RGB and measured with current depth, not stale XYZ. '
                        'B dots are in a fixed receiver identity window and may lie on background/robot. '
                        'S motion fields, when present, compare CURRENT matched visible feature measurements across this episode; they do not establish holding or contact. '
                        'No object pose, target pose, orientation error, or recommended action is calculated. '
                        'Choose the grasp relationship yourself from both current images and compare coordinates only for matching physical features.')
                    if args.focused_questions:state['surface_sample_meaning']+=' C labels identify current sampled pixels, not persistent material landmarks. Dot displacement alone is not evidence of object rotation.'
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
            questions['transition']=dict(type='choice',instructions='Judge the observable exit condition for the CURRENT stage. Advance only when it is visibly satisfied. Advance executes no motion this turn.',criteria={'continue':'Continue current stage.','advance':'Current stage complete; enter next stage, or finish at the final stage.','restart':'Return to the first stage to recover; execute no physical motion this turn.'})
            if args.coordinate_questions:
                if not args.surface_context:raise ValueError('Coordinate questions require current visible surface context')
                questions=coordinate_questions(state,questions)
            if args.actor_attention and replay_rows is None:
                candidates={s['label']:s for s in state['visible_surface_samples']}
                source_candidates={k:v for k,v in candidates.items() if k.startswith('C') or k=='S'} if args.focused_questions else candidates
                attention=dict(reference=dict(type='choice',
                    instructions='Use CURRENT RGB to choose a currently visible labelled surface feature relevant to the CURRENT stage. For grasping choose a graspable part of the actual source, not the robot/background. For rack placement choose the relevant rack support. This is your visual selection, not a movement recommendation. Unknown if no suitable visible labelled feature exists.',
                    criteria={**{k:'Select current observed dot '+k+'.' for k in source_candidates},
                        'unlabelled':'A useful object feature is visible but no current dot identifies it.',
                        'unknown':'No suitable visible feature can be identified.'}),
                    orientation_relation=dict(type='choice',
                    instructions='From CURRENT object and finger geometry, which orientation relationship matters for the CURRENT stage? This identifies a visual relationship, not a rotation sign.',
                    criteria=dict(aligned='The present tool orientation fits the stage relationship.',
                        closing_mismatch='The finger closing direction does not fit the visible grasp or placement geometry.',
                        approach_mismatch='The direction the fingers approach does not fit the visible geometry.',
                        turn_required='The grasped control must now be rotated about its visible shaft.',
                        unclear='The relevant orientation relationship is not visible clearly enough.')))
                stage_key=state['stage'].get('stage_key','')
                placing=stage_key in ('align_source_above_receiver','lower_to_place','release','inspect') and args.task==1458
                if args.focused_questions:
                    attention['reference']['instructions']='Which labelled C surface dot lies on the source part useful for the current manipulation? Choose a visible reference, not a hidden centre. Read current RGB; labels identify observed surfaces only.'
                    if placing:
                        attention['receiver']=dict(type='choice',instructions='Which B dot lies on a useful current rack support for this placement? Use current RGB to distinguish wood from background or robot.',
                            criteria={**{k:'Select receiver surface '+k+'.' for k in candidates if k.startswith('B')},'unknown':'No useful rack support dot is visible.','unlabelled':'A useful support is visible but not labelled.'})
                if args.part_questions:
                    if stage_key in ('align_above_source','descend_to_source'):
                        attention['reference']['instructions']=(
                            'Which labelled dot is on the RAISED THIN FIN above the round stove-knob base? Only that fin is intended for pinching. Reject dots on the circular base, burner, robot or table. If the fin is visible but not labelled choose unlabelled; if hidden choose unknown.'
                            if args.task==1383 else
                            'Which labelled dot is on the NARROW UPPER GREEN NECK immediately below the tan cork? This is the intended grasp region; reject dots on the wider bottle body, robot or background. If the neck is visible but not labelled choose unlabelled; if hidden choose unknown.')
                    elif placing:
                        attention['reference']['instructions']='Which labelled source dot is on a visible BOTTLE BODY region useful for fitting the whole bottle into the wooden cradle? The old neck grip point is not automatically a body-placement reference. Choose from CURRENT RGB; unknown if no body feature can be identified.'
                if args.track_selected:
                    attention['reference']['instructions']+=(' S, when present, is a current RGB match of YOUR previous selection, measured again with current depth. Prefer S to keep the SAME physical grasp region while positioning; select a different C only when current RGB shows the old region is unsuitable. Do not switch from bottle neck to body merely because the dots moved. If S is absent its match was lost; select a genuinely visible suitable region or unknown, never infer current XYZ from history.')
                if args.track_selected and placing:
                    from libero_reference_decision import PLACEMENT_REFERENCE
                    attention['reference']['instructions']=PLACEMENT_REFERENCE
                attention_state=state
                if args.focused_questions:
                    attention_state={k:v for k,v in state.items() if k not in ('own_gripper_world_mm','coordinate_frame_note','visible_surface_samples')}
                    attention_state['visible_dot_labels']=[dict(label=v['label'],pixel_uv=v['pixel_uv']) for v in candidates.values()]
                if args.reference_only:attention.pop('orientation_relation',None)
                if args.scoped_reference_call:attention_state=dict(state,request_purpose='multimodal_reference_selection')
                assessment=api.post('/systemone',dict(model='gpt-6-luna',state=attention_state,questions=attention))
                selected=assessment['answers']['reference']['choice']
                if args.track_selected and tracker is not None:tracker.select(selected)
                state['actor_visual_assessment']={k:v['choice'] for k,v in assessment['answers'].items()}
                state['actor_visual_assessment_confidence']={k:v['confidence'] for k,v in assessment['answers'].items()}
                visual_history.append(dict(native_tick=tick,stage=stage,choices=state['actor_visual_assessment'],confidence=state['actor_visual_assessment_confidence']))
                if selected in candidates:
                    observed=np.array(candidates[selected]['visible_surface_world_mm'])
                    state['actor_selected_surface']=candidates[selected]
                    state['observed_surface_relative_mm']=np.round(observed-np.array(state['own_gripper_world_mm']),1).tolist()
                    state['relative_observation_meaning']='Observed surface minus own gripper, XYZ in millimetres. This feature was selected by YOU from CURRENT RGB. It is not a desired pose or a required displacement. Surface versus object centre and overhead/descent/placement relationships still require visual judgement; no orientation correction is computed.'
                    if placing and 'receiver' in assessment['answers']:
                        receiver=assessment['answers']['receiver']['choice']
                        if receiver in candidates:
                            state['actor_selected_receiver_surface']=candidates[receiver]
                            state['observed_receiver_minus_source_mm']=np.round(np.array(candidates[receiver]['visible_surface_world_mm'])-observed,1).tolist()
                    for i,a in enumerate(('x','y','z')):
                        questions[a]['instructions']=(f'Current stage: {state["stage"]["name"]}. Goal: {state["stage"]["goal"]}. '
                            f'Your RGB-selected observed feature has {a.upper()} coordinate minus gripper coordinate = {state["observed_surface_relative_mm"][i]} mm. '
                            f'Positive increases the gripper world {a.upper()} coordinate; negative decreases it; hold retains it. '
                            'Choose the direction that achieves the stage relationship, using current RGB to judge clearance, object thickness and finger geometry. '
                            'For above-source alignment retain vertical clearance rather than descending directly onto a visible surface. '
                            'For descent move fingers alongside the object; the sampled visible skin is not its hidden centre. '
                            'For close or release keep position unless a visible positioning correction is needed.')
                questions['gripper']['instructions']=('Current stage goal: '+state['stage']['goal']+'. '
                    'Choose open, close, or retain the last command. A Close stage asks you to attempt closure around the positioned object; '
                    'do not require already-proven contact before selecting close. Closing alone does not prove grasp; the next observations test it.')
            if args.focused_questions:
                for a in ('x','y','z'):
                    key=state['stage'].get('stage_key','')
                    template_key=('source_alignment_xy' if key=='align_above_source' and a!='z' else
                        'source_alignment_z' if key=='align_above_source' else
                        'source_descent' if key=='descend_to_source' else
                        'placement_alignment_xy' if key=='align_source_above_receiver' and a!='z' else
                        'placement_alignment_z' if key=='align_source_above_receiver' else
                        'placement_lowering' if key=='lower_to_place' else
                        'turn_translation' if key=='turn' else 'close' if key in ('close','release','inspect') else 'lift')
                    query=plan.get('axis_question_templates',{}).get(template_key,'Which world-{axis} motion helps the current goal?').format(axis=a.upper())
                    reference=(f'Observed selected surface minus hand on {a.upper()} = {state["observed_surface_relative_mm"]["xyz".index(a)]} mm. '
                        if 'observed_surface_relative_mm' in state else '')
                    if 'observed_receiver_minus_source_mm' in state:
                        reference=f'Observed selected receiver minus held source on {a.upper()} = {state["observed_receiver_minus_source_mm"]["xyz".index(a)]} mm. '
                    if key in ('align_source_above_receiver','lower_to_place') and 'observed_receiver_minus_source_mm' not in state:
                        reference='No current receiver reference is identified. Source-to-hand attachment offset is NOT a source-to-rack error; judge the current rack/body relation from RGB.'
                    if key in ('close','release','inspect','turn'):reference=''
                    questions[a]['instructions']=(query+' '+reference+
                        'Judge the intended relationship from current fixed/wrist RGB; an observed surface is not a hidden object centre. '
                        'Hold when this axis is already suitable.')
                    questions[a]['criteria']={'positive':f'Move hand +{a.upper()}; increase hand {a.upper()}, decrease surface-minus-hand {a.upper()}.',
                        'negative':f'Move hand -{a.upper()}; decrease hand {a.upper()}, increase surface-minus-hand {a.upper()}.',
                        'hold':'Keep this axis unchanged.'}
                for a in ('rx','ry','rz'):
                    label={'rx':'roll about world X','ry':'pitch about world Y','rz':'yaw about world Z'}[a]
                    questions[a]['instructions']=(f'{state["stage"]["name"]}: {state["stage"]["goal"]} '
                        f'Which {label} sign improves the actual finger/object or held-object/receiver orientation? '
                        'Compare current RGB, own-hand axes and actual before/after motion; hold if aligned. '
                        'Any earlier actor orientation assessment is an unverified hypothesis, not a desired pose.')
            if args.numeric_xy:
                moving_key=state['stage'].get('stage_key','')
                difference=reference_difference(state)
                if difference is not None and moving_key in ('align_above_source','descend_to_source','align_source_above_receiver','lower_to_place') and not (args.visual_near_grasp and moving_key=='descend_to_source'):
                    band=protocol.get('axis_bands_mm',{}).get(moving_key,10)
                    for i,a in enumerate(('x','y')):
                        questions[a]['instructions']=(f'On world {a.upper()}, the current coarse alignment error is {difference[i]} mm. '
                            'Error means YOUR RGB-selected reference minus the controlled point: source surface minus hand during grasp alignment, '
                            'receiver surface minus held source during placement. Which movement reduces this one-axis error? '
                            f'Positive error needs positive motion; negative error needs negative motion. Hold inside the +/-{band}mm reference-positioning band. '
                            'This aligns a visual reference only; it never certifies contact, a hidden centre, or a desired orientation.')
                        questions[a]['criteria']={'positive':f'Error above +{band}mm: increase the controlled coordinate.',
                            'negative':f'Error below -{band}mm: decrease the controlled coordinate.',
                            'hold':f'Error within -{band}mm to +{band}mm: hold this coordinate.'}
                    state['coarse_alignment_band_mm']=band
                    state['alignment_band_meaning']='Coarse visual-feature positioning band only, not a sensor accuracy claim or grasp/contact certificate.'
            if args.adaptive_steps:
                questions.pop('scale')
                state['step_policy']='Direction-history adaptation only; no object-target residual controls magnitude. The last execution contains commanded and measured effects.'
            if args.relative_step_scale:
                state['step_policy']='Only unsigned translation magnitude uses the absolute observed difference for YOUR selected feature, clipped to 2-20mm. Every sign and hold is still your decision; no orientation error is computed.'
            if args.focused_questions:
                for k in ('own_gripper_world_mm','visible_surface_samples','coordinate_frame_note'):state.pop(k,None)
                for k in ('actor_selected_surface','actor_selected_receiver_surface'):
                    if k in state:state[k]={q:v for q,v in state[k].items() if q!='visible_surface_world_mm'}
            if args.numeric_z and state['stage'].get('stage_key')=='descend_to_source' and 'observed_surface_relative_mm' in state:
                height=state['observed_surface_relative_mm'][2]
                questions['z']['instructions']=(f'Current selected visible-feature height minus hand height is {height} mm. Which Z direction brings the fingers alongside that grasp region? Negative means the region is below the hand. Positive means it is above. Hold within +/-8mm. Visible collision or an already supported capture relationship can justify hold. A large horizontal or vertical distance is not a rotation error.')
                questions['z']['criteria']={'negative':'Move DOWN along world -Z.','positive':'Move UP along world +Z.','hold':'Keep the current physical height.'}
            if protocol:
                relative=state.get('observed_surface_relative_mm',['unknown']*3)
                placement=state.get('observed_receiver_minus_source_mm',['unknown']*3)
                context=dict(stage_name=state['stage']['name'],stage_goal=state['stage']['goal'],stage_exit=state['stage']['exit'],
                    x_mm=relative[0],y_mm=relative[1],z_mm=relative[2],
                    receiver_x_mm=placement[0],receiver_y_mm=placement[1],receiver_z_mm=placement[2],
                    orientation=state.get('actor_visual_assessment',{}).get('orientation_relation','unknown'),
                    gripper_command='close' if grip>0 else 'open',
                    pad_separation_mm=state.get('own_tool_geometry',{}).get('pad_centre_separation_mm','unknown'),
                    stage_steps=state.get('stage_own_motion',{}).get('physical_steps','unknown'),
                    stage_rotvec_z_deg=state.get('stage_own_motion',{}).get('relative_world_rotvec_deg',['unknown']*3)[2])
                templates=protocol.get('question_templates',{}).get(state['stage'].get('stage_key',''),{})
                if set(templates)-set(questions):raise ValueError('Protocol cannot add or remove formal output channels')
                for name,template in templates.items():
                    if not isinstance(template,str):raise ValueError('Protocol questions must be text, never commands')
                    questions[name]['instructions']=template.format_map(context)
            if replay_rows is None:
                numeric_answers={}
                if args.numeric_axis_call:
                    from libero_numeric_axes import build_numeric_request
                    numeric=build_numeric_request(state,protocol)
                    if numeric is not None:
                        saved=(api.current,api.previous,api.demonstrations,getattr(api,'motion',MOTION))
                        try:
                            api.current=[];api.previous=[];api.demonstrations=[]
                            api.motion='Answer the independent numeric-axis questions from the supplied observed differences and stated intervals. Positive hand motion increases the controlled coordinate. This request does not decide object identity, orientation, grasp or stage completion.'
                            numeric_reply=api.post('/systemone',numeric)
                        finally:api.current,api.previous,api.demonstrations,api.motion=saved
                        numeric_answers=numeric_reply['answers']
                        state['numeric_axis_decisions']={a:v['choice'] for a,v in numeric_answers.items()}
                        state['numeric_axis_decision_meaning']='These directions were chosen by YOU in the immediately preceding text-only Decisions call from this SAME observation. They are not clearance or contact certificates. This visual call decides the remaining axes, gripper and transition. Advance/restart executes no physical action.'
                        for a in numeric_answers:questions.pop(a)
                rotation_answers={}
                if args.separate_rotation_call and args.task==1458:
                    from libero_rotation_decision import build_rotation_request
                    rotation_request=build_rotation_request(state,args.rotation_effect_hints)
                    if rotation_request is not None:
                        rotation_reply=api.post('/systemone',rotation_request)
                        rotation_answers=rotation_reply['answers']
                        state['rotation_axis_decisions']={a:v['choice'] for a,v in rotation_answers.items()}
                        for a in rotation_answers:questions.pop(a)
                state['request_purpose']='multimodal_rotation_gripper_transition' if numeric_answers else 'multimodal_policy'
                answer=api.post('/systemone',dict(model='gpt-6-luna',state=state,questions=questions))
                answer['answers']={**numeric_answers,**rotation_answers,**answer['answers']}
                if args.formal_stage_call:
                    from libero_stage_decision import build_stage_request
                    phase_request=build_stage_request(state,answer['answers'],protocol)
                    if phase_request is not None:
                        phase_reply=api.post('/systemone',phase_request)
                        answer['answers']['transition']=phase_reply['answers']['transition']
            else:
                stage=replay_rows[decision]['stage']
                answer=dict(answers={k:dict(choice=v) for k,v in replay_rows[decision]['choices'].items()})
            choices={k:v['choice'] for k,v in answer['answers'].items()};before_p,before_R=own_pose()
            previous=[dict(type='input_text',text='PREVIOUS observation, before the last executed command; compare with CURRENT.'),
                *[dict(x,type=x['type'],**({'text':x['text'].replace('CURRENT','PREVIOUS')} if x['type']=='input_text' else {})) for x in api.current]]
            if choices['transition']=='advance':
                if stage==len(stages)-1:result['program_finished']=True;break
                stage+=1;step_sizes=None;last_signs=None
                stage_origin_p,stage_origin_R=own_pose();stage_origin_tick=tick
                history.append(dict(choices=choices,execution='No physical action; stage advanced'));continue
            if choices['transition']=='restart':
                stage=0;stage_origin_p,stage_origin_R=own_pose();stage_origin_tick=tick
                step_sizes=None;last_signs=None
                history.append(dict(choices=choices,execution='No physical action; returned to first stage'));continue
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
            if args.relative_step_scale:
                difference=reference_difference(state)
                if difference is not None and state['stage'].get('stage_key') in ('align_above_source','descend_to_source','align_source_above_receiver','lower_to_place'):
                    # A magnitude cannot reverse, invent or suppress an actor sign.
                    magnitude=np.clip(.3*np.abs(np.asarray(difference))/1000,.002,.02)
                    dp=signs[:3]*magnitude
            dp*=min(1.,.03/max(np.linalg.norm(dp),1e-10));dr*=min(1.,.25/max(np.linalg.norm(dr),1e-10))
            if replay_rows is not None:
                dp=np.array(replay_rows[decision]['commanded_translation_mm'])/1000
                dr=np.deg2rad(replay_rows[decision]['commanded_rotation_world_deg'])
            target_p=before_p+dp;target_R=Rotation.from_rotvec(dr).as_matrix()@before_R
            for _ in range(args.execution_steps):
                pos,rot=own_pose();u_p=.7*(target_p-pos);u_r=.7*Rotation.from_matrix(target_R@rot.T).as_rotvec()
                action=np.r_[np.clip(u_p/.05,-1,1),np.clip(u_r/.5,-1,1),grip]
                obs,_,_,_=env.step(action);tick+=1
            after_p,after_R=own_pose()
            row=dict(decision=decision,native_steps=tick,stage=stage,choices=choices,
                own_position_before_mm=(before_p*1000).tolist(),own_position_after_mm=(after_p*1000).tolist(),
                own_rotation_before=before_R.tolist(),own_rotation_after=after_R.tolist(),
                commanded_translation_mm=(dp*1000).tolist(),commanded_rotation_world_deg=np.rad2deg(dr).tolist(),
                measured_translation_mm=((after_p-before_p)*1000).tolist(),
                measured_rotation_world_deg=np.rad2deg(Rotation.from_matrix(after_R@before_R.T).as_rotvec()).tolist())
            history.append(row)
            with (out/'execution.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
            print(json.dumps(row),flush=True)
        capture()
        # Evaluator is read only here, after the final action; never sent to either model.
        result['diagnostic_replay']=args.replay is not None
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

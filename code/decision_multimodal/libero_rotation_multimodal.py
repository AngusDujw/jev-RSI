"""Visual whole-rotation choices with independent numerical fine/motor calls."""
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

from legacy_decisions import LegacyAPI,convert_request,english
from libero_prompt_revision import RevisedAPI
from libero_hybrid_vision import FineAPI
from libero_motion_multimodal import assert_no_camera_matrices
from libero_rotation_images import orientation_card
import libero_multimodal as stream

PLAN=Path(__file__).with_name('plans')/'libero_rotation_three_v1.json'
AXES=('rx','ry','rz')


class MotorAPI(FineAPI):
    profile='rotation_numerical_motor_v1'

    def revise(self,original):
        result=super().revise(original)
        state=result['state'];original_values=original['state'].get('required_rotation_world_rad',{})
        state.pop('required_rotation_world_rad',None);state.pop('rotation_relations',None)
        state['rotation_feedback']={a:dict(goal_minus_current_rad=original_values.get(a,0),
            aligned=abs(original_values.get(a,0))<.03) for a in AXES if a in result['questions']}
        for a in state['rotation_feedback']:
            result['questions'][a]['instructions']=(f'Use only rotation_feedback.{a}. '
                'Choose hold when aligned is true. Otherwise positive for positive goal_minus_current_rad, '
                'negative for negative. This is a world rotation-vector increment, not an absolute Euler angle.')
        return result


class RotationVisualAPI(RevisedAPI):
    profile='rotation_visual_candidates_v1'

    def revise(self,original):return deepcopy(original)

    def build_payload(self,sent):
        payload=convert_request(sent)
        content=[dict(type='input_text',text=payload['input'])]
        for view in self.views:
            content.extend([dict(type='input_text',text='CURRENT '+view['camera']+'. '+view['description']),
                dict(type='input_image',detail='high',image_url='data:image/png;base64,'+
                    base64.b64encode(view['raw']).decode())])
        content.extend([dict(type='input_text',text='Robot-only candidate orientation card. Orange is the predicted candidate; cyan is the target. '
            'Compare all three world views. This card does not predict contacts, object motion or collision clearance.'),
            dict(type='input_image',detail='high',image_url='data:image/png;base64,'+base64.b64encode(self.card).decode())])
        self.image_count=len(self.views)+1
        payload['input']=[dict(role='user',content=content)]
        english(payload);assert_no_camera_matrices(payload)
        return payload

    def validate_payload(self,payload):
        english(payload);assert_no_camera_matrices(payload)
        assert len([x for x in payload['input'][0]['content'] if x['type']=='input_image'])==3

    def input_audit(self):return self.metadata


class RotationAPI(LegacyAPI):
    def __init__(self,cfg,log,role):
        super().__init__(cfg,log,role)
        self.motor=MotorAPI(cfg,log,role);self.visual=RotationVisualAPI(cfg,log,role)
        self.root=Path(os.environ['DECISION_MM_ASSET_ROOT']);self.root.mkdir(exist_ok=True)
        self.task=int(log.__self__.cfg['task_id'])
        if self.task not in (1383,1458,1335):raise ValueError('Undeclared rotation task')
        self.plan=json.loads(PLAN.read_text())[str(self.task)];english(self.plan)
        self.visual_root=self.root/'rotation-inputs';self.visual_root.mkdir(exist_ok=True)
        link=self.root/'decision-api'
        if not link.exists():link.symlink_to(self.folder,target_is_directory=True)
        elif link.resolve()!=self.folder.resolve():raise ValueError('Conflicting rotation audit stream')
        self.log=log;self.index=0

    def post(self,endpoint,original):
        import numpy as np
        from scipy.spatial.transform import Rotation
        stage=original['state'].get('stage',original['state'].get('operation'))
        error=np.array([original['state'].get('required_rotation_world_rad',{}).get(a,0.) for a in AXES])
        keys=[a for a in AXES if a in original['questions'] and len(original['questions'][a]['criteria'])>1]
        if self.task==1383:keys=[a for a in keys if a=='rz']
        name=stage.split(':')[-1]
        label={'select':'Align','approach':'Align','align':'Align','observe':'Align','contact':'Align',
            'descend':'Align','grasp':'Grasp','test_lift':'Grasp','lift':'Grasp','carry':'Position',
            'orient_receiver':'Align','lower':'Place','release':'Release','retreat':'Release',
            'turn':'Turn','verify':'Verify'}.get(name,'Align')
        local_plan=next((p for p in self.plan['stages'] if p['name']==label),self.plan['stages'][0])
        task_goal=dict(name=local_plan['name'],goal=local_plan['goal'])
        # The frozen source controls movement only above its 0.03-rad gate.
        # Coarse/fine selection is explicit; no residual or rank is given to vision.
        coarse=bool(keys and max(abs(error))>=.12)
        visual=None;selected='not_requested'
        if coarse:
            views,robot=stream.CURRENT.capture(self.visual_root)
            current=Rotation.from_quat(robot['robot0_eef_quat']).as_matrix()
            target=Rotation.from_rotvec(error).as_matrix()@current
            from libero_robot_geometry import gripper_geometry
            own=gripper_geometry(stream.CURRENT.env,stream.CURRENT.observation)
            pads=np.asarray(own['pad_vertices_tool'],float)
            # Two pad hulls show the real public robot tool orientation.
            if len(pads)%2:raise ValueError('Unexpected public pad vertex geometry')
            vertices=[pads[:len(pads)//2],pads[len(pads)//2:]]
            options=[('hold',current)]
            mapping={'hold':dict.fromkeys(AXES,'hold')}
            for a in keys:
                axis=AXES.index(a)
                for sign,name in ((-1,'negative'),(1,'positive')):
                    value=a+'_'+name;increment=np.zeros(3)
                    increment[axis]=sign*min(.08,.4*abs(error[axis]))
                    options.append((value,Rotation.from_rotvec(increment).as_matrix()@current))
                    mapping[value]=dict.fromkeys(AXES,'hold');mapping[value][a]=name
            # Position in the card cannot be a fixed action hint.
            rng=np.random.default_rng(self.task*10000+self.index)
            rng.shuffle(options)
            self.visual.views=views
            self.visual.card=orientation_card(current,target,options,vertices)
            card_path=self.visual_root/f'{self.index:04d}-orientation-card.png';card_path.write_bytes(self.visual.card)
            self.visual.metadata=dict(camera_views=[{k:v for k,v in w.items() if k not in ('raw','K','camera_to_world')} for w in views],
                orientation_card=str(card_path),orientation_card_sha256=hashlib.sha256(self.visual.card).hexdigest(),
                numeric_orientation_residual_sent=False,numeric_robot_pose_sent=False,
                target_source='Frozen RGB-D task geometry and measured own robot orientation',
                candidate_ranking_sent=False)
            criteria={name:('Keep the current tool orientation' if name=='hold' else
                'Apply the single world-axis rotation shown in panel '+name) for name,_ in options}
            request=dict(model='gpt-6-luna',state=dict(task=original['state']['task'],stage=stage,
                task_plan=task_goal,goal='Match the tool fingers to the cyan target orientation',
                source='Current RGB and public robot-only candidate diagrams'),
                questions={'rotation_action':dict(type='choice',instructions=(
                    'Which candidate panel brings the orange fingers closest to the cyan target across ALL three views? '
                    'Compare orientation, not position or image center. Select one complete candidate. '
                    'Panel hold is the current orientation; choose it only when no displayed rotation improves the match.'),criteria=criteria)})
            visual=self.visual.post(endpoint,request)
            selected=visual['answers']['rotation_action']['choice']
            chosen=mapping[selected]
            (self.visual_root/f'{self.index:04d}-execution-map.json').write_text(json.dumps(dict(
                selected=selected,mapping=mapping,stage=stage,diagnostic_only_error_rad=error.tolist(),
                target_orientation=target.tolist(),current_orientation=current.tolist()),indent=2)+'\n')
        motor_request=deepcopy(original)
        self.motor.plan_stage=task_goal
        if coarse:
            for a in AXES:motor_request['questions'].pop(a,None)
            motor_request['state'].pop('required_rotation_world_rad',None)
            motor_request['state'].pop('rotation_relations',None)
        answer=self.motor.post(endpoint,motor_request)
        if coarse:
            v=visual['answers']['rotation_action']
            for a in AXES:
                if a not in original['questions']:continue
                probabilities={k:sum(p for candidate,p in v['probabilities'].items() if mapping[candidate][a]==k)
                    for k in original['questions'][a]['criteria']}
                answer['answers'][a]=dict(type='choice',choice=chosen[a],confidence=v['confidence'],
                    probabilities=probabilities,decision_source='whole visual candidate mapping')
        self.log(dict(kind='rotation_role_merge',stage=stage,visual_call=coarse,
            selected_visual_action=selected,diagnostic_only_error_rad=error.tolist(),
            rotation_source='visual_candidate' if coarse else 'numerical_fine',
            native_observation_counter=stream.CURRENT.tick))
        self.index+=1
        return answer

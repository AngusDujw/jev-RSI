"""Visual coarse X relation followed by camera-derived numerical fine control."""
from copy import deepcopy
import json
import os
from pathlib import Path

import libero_multimodal as stream
from legacy_decisions import LegacyAPI,convert_request,english
from libero_prompt_revision import RevisedAPI
from libero_prompt_revision_v2 import revise_local
from libero_inframe_axes import reduce_state,arrival_language,MOTION_FILE
from libero_motion_multimodal import remove_xyz_feedback,assert_no_camera_matrices
from libero_visual_relation_servo import RelationAPI

PROFILE='libero-rgb-hybrid-coarse-x-v1'
PLAN_FILE=Path(__file__).with_name('plans')/'libero_hybrid_coarse_x_v1.json'


class FineAPI(RevisedAPI):
    profile='hybrid_text_motor'
    image_count=0

    def revise(self,original):
        sent=revise_local(original)
        original_axes=sent['state'].get('translation_axes',{})
        state=reduce_state(remove_xyz_feedback(sent['state']))
        state['axis_feedback']={a:dict(goal_minus_current_mm=row['goal_minus_current_mm'],
            aligned=row.get('relation','').replace('_',' ')=='within tolerance')
            for a,row in original_axes.items() if a in sent['questions']}
        state['plan_stage']=self.plan_stage
        sent['state']=state
        for axis in 'xyz':
            if axis in sent['questions']:
                sent['questions'][axis]['instructions']=(
                    f'For world {axis.upper()}, use only axis_feedback.{axis}. '
                    'If aligned is true choose hold. Otherwise choose positive for a positive '
                    'goal_minus_current_mm and negative for a negative value. '
                    'The feedback already accounts for the current phase goal.')
        return arrival_language(sent)

    def build_payload(self,sent):
        payload=convert_request(sent)
        payload['input']=[dict(role='user',content=[dict(type='input_text',text=MOTION_FILE.read_text()),
            dict(type='input_text',text=payload['input'])])]
        return payload

    def validate_payload(self,payload):
        assert all(p['type']=='input_text' for p in payload['input'][0]['content'])
        english(payload);assert_no_camera_matrices(payload)


class CoarseAPI(RelationAPI):
    profile='hybrid_visual_relation'

    def revise(self,original):
        sent=super().revise(original)
        for question in sent['questions'].values():
            for key,value in question['criteria'].items():
                question['criteria'][key]=value.replace('above of','above').replace('below of','below')
        return sent


class HybridAPI(LegacyAPI):
    def __init__(self,cfg,log,role):
        super().__init__(cfg,log,role)
        self.motor=FineAPI(cfg,log,role);self.visual=CoarseAPI(cfg,log,role)
        self.root=Path(os.environ['DECISION_MM_ASSET_ROOT']);self.root.mkdir(parents=True,exist_ok=True)
        link=self.root/'decision-api'
        if link.exists() or link.is_symlink():
            if link.resolve()!=self.folder.resolve():raise ValueError('Conflicting hybrid audit link')
        else:link.symlink_to(self.folder,target_is_directory=True)
        self.visual.asset_root=self.root/'visual';self.visual.asset_root.mkdir(exist_ok=True)
        self.visual.temporal=False;self.visual.previous=None
        self.fine_started=False;self.log=log
        self.plan=json.loads(PLAN_FILE.read_text());english(self.plan)

    def post(self,endpoint,original):
        if len(list(self.folder.glob('*/request.json')))>=158:
            raise RuntimeError('Combined hybrid API budget exhausted')
        state=original['state'];stage=state.get('stage',state.get('operation'))
        xerror=state.get('translation_axes',{}).get('x',{}).get('goal_minus_current_mm')
        # A permitted camera-derived readiness gate selects fine input, not an
        # inferred scene true pose. This numerical value never enters the vision call.
        if stage!='approach' or xerror is None or abs(xerror)<=40:
            self.fine_started=True
        coarse=not self.fine_started
        perception=None
        if coarse:
            views,_=stream.CURRENT.capture(self.visual.asset_root);self.visual.views=views
            visual_request=dict(model='gpt-6-luna',state={},questions={'x':original['questions']['x']})
            perception=self.visual.post(endpoint,visual_request)
            if perception['answers']['x']['choice']=='hold':self.fine_started=True;coarse=False
        motor_request=deepcopy(original)
        motor_request['state']['hybrid_substage']='visual_coarse_x' if coarse else 'numerical_fine'
        motor_request['state']['fine_readiness']=self.fine_started
        plan_key='visual_coarse' if coarse else 'numerical_fine'
        # Compile the task goal from the accepted Pro plan. Transport, evaluation
        # and role-routing notes stay outside the actor's task instructions.
        self.motor.plan_stage=dict(name=plan_key,goal=self.plan[plan_key]['goal'])
        if coarse:
            motor_request['questions'].pop('x')
            motor_request['state']['translation_axes'].pop('x')
        answer=self.motor.post(endpoint,motor_request)
        if coarse:answer['answers']['x']=perception['answers']['x']
        self.log(dict(kind='hybrid_role_merge',stage=stage,visual_call=perception is not None,
            x_source='visual_relation' if coarse else 'numerical_feedback',
            x_reference_diagnostic_only_mm=xerror,returned_x=answer['answers'].get('x'),
            fine_entry='camera-derived readiness or visual center; original native stage graph unchanged'))
        return answer

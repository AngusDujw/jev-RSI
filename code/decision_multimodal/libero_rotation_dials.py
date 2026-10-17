"""Version2: explicitly algorithm-assisted visual angular relation feedback."""
from copy import deepcopy
import hashlib
import io
import json
import math

from libero_rotation_multimodal import RotationAPI,RotationVisualAPI,AXES


def dial_card(errors,axes):
    from PIL import Image,ImageDraw,ImageFont
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',23)
    small=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',16)
    im=Image.new('RGB',(440*len(axes),470),'#13262d');d=ImageDraw.Draw(im)
    for j,axis in enumerate(axes):
        x=220+j*440;y=235;r=142;e=errors[AXES.index(axis)]
        d.text((x-30,18),axis.upper(),fill='white',font=font)
        d.text((x-174,55),'CCW / left',fill='#67e6d7',font=small)
        d.text((x+78,55),'CW / right',fill='#67e6d7',font=small)
        d.ellipse((x-r,y-r,x+r,y+r),outline='#526e75',width=2)
        d.line((x,y,x,y-r),fill='white',width=5)
        points=[(x-math.sin(e*t/80)*(r-13),y-math.cos(e*t/80)*(r-13)) for t in range(81)]
        d.line(points,fill='#39877e',width=4)
        tip=(x-math.sin(e)*r,y-math.cos(e)*r)
        d.line((x,y,*tip),fill='#42efcf',width=6)
        d.ellipse((tip[0]-8,tip[1]-8,tip[0]+8,tip[1]+8),fill='#42efcf')
        d.ellipse((x-6,y-6,x+6,y+6),fill='white')
        d.text((x-172,407),'WHITE: reference    CYAN: target',fill='white',font=small)
        d.text((x-173,437),'Signed world rotation-vector component',fill='#b2c8c6',font=small)
    b=io.BytesIO();im.save(b,format='PNG');return b.getvalue()


class DialVisualAPI(RotationVisualAPI):
    profile='rotation_visual_dials_v2'

    def build_payload(self,sent):
        payload=super().build_payload(sent)
        payload['input'][0]['content'][-2]['text']=(
            'Algorithm-assisted angular feedback image. Each named panel depicts one signed world '
            'rotation-vector component derived from permitted RGB-D targets and measured robot state. '
            'WHITE points to the reference. CYAN points to the target. '
            'Judge whether CYAN is counterclockwise (left) or clockwise (right) from WHITE. '
            'Follow the green arc when the target points downward. These are not Euler angles; '
            'the controller combines the axis decisions into one world rotation-vector increment.')
        return payload


class DialRotationAPI(RotationAPI):
    def __init__(self,cfg,log,role):
        super().__init__(cfg,log,role)
        self.visual=DialVisualAPI(cfg,log,role)

    def post(self,endpoint,original):
        import numpy as np
        import libero_multimodal as stream
        stage=original['state'].get('stage',original['state'].get('operation'))
        error=np.array([original['state'].get('required_rotation_world_rad',{}).get(a,0.) for a in AXES])
        axes=[a for i,a in enumerate(AXES) if a in original['questions'] and
              len(original['questions'][a]['criteria'])>1 and abs(error[i])>=.12]
        if self.task==1383:axes=[a for a in axes if a=='rz']
        # The Pro task goals and original manipulation graph stay unchanged.
        goals=self.plan['stages'];name=stage.split(':')[-1]
        label={'turn':'Turn','verify':'Verify','grasp':'Grasp','test_lift':'Grasp',
            'lift':'Grasp','lower':'Place','release':'Release','retreat':'Release',
            'carry':'Position'}.get(name,'Align')
        plan=next((g for g in goals if g['name']==label),goals[0])
        local_plan=dict(name=plan['name'],goal=plan['goal'])
        raw=None;choices={}
        if axes:
            self.visual.views,_=stream.CURRENT.capture(self.visual_root)
            self.visual.card=dial_card(error,axes)
            path=self.visual_root/f'{self.index:04d}-angular-dials.png';path.write_bytes(self.visual.card)
            self.visual.metadata=dict(camera_views=[{k:v for k,v in w.items() if k not in ('raw','K','camera_to_world')} for w in self.visual.views],
                angular_feedback_image=str(path),sha256=hashlib.sha256(self.visual.card).hexdigest(),
                algorithm_derived_signed_angular_residual_visualized=True,
                numerical_angular_values_in_text=False,camera_matrices_sent=False)
            request=dict(model='gpt-6-luna',state=dict(task=original['state']['task'],stage=stage,
                task_plan=local_plan,goal='Judge the cyan target side in each named angular panel',
                source='Current cameras and algorithm-assisted angular feedback image'),
                questions={a:dict(type='choice',instructions=f'In panel {a.upper()} only, '
                    'is the CYAN target counterclockwise/left or clockwise/right of the WHITE reference? '
                    'Read this panel, not another axis or camera. The curved green arc shows the side when needed.',
                    criteria={'counterclockwise':'CYAN is counterclockwise, on the left of WHITE.',
                              'clockwise':'CYAN is clockwise, on the right of WHITE.'}) for a in axes})
            raw=self.visual.post(endpoint,request)
            choices={a:('positive' if raw['answers'][a]['choice']=='counterclockwise' else 'negative') for a in axes}
        motor=deepcopy(original);self.motor.plan_stage=local_plan
        for a in axes:
            motor['questions'].pop(a)
            motor['state']['required_rotation_world_rad'].pop(a,None)
            motor['state'].get('rotation_relations',{}).pop(a,None)
        answer=self.motor.post(endpoint,motor)
        for a in axes:
            v=raw['answers'][a]
            answer['answers'][a]=dict(type='choice',choice=choices[a],confidence=v['confidence'],
                probabilities={'positive':v['probabilities']['counterclockwise'],
                               'negative':v['probabilities']['clockwise'],'hold':0.},
                decision_source='Angular feedback image relation mapping')
        self.log(dict(kind='rotation_role_merge',stage=stage,visual_call=bool(axes),
            selected_visual_actions=choices,selected_visual_action='joint_axis_relations' if axes else 'not_requested',
            diagnostic_only_error_rad=error.tolist(),rotation_source='visual_dials' if axes else 'numerical_fine',
            native_observation_counter=stream.CURRENT.tick,
            visual_condition='Algorithm-derived signed angular feedback is rendered; not raw-RGB inference'))
        (self.visual_root/f'{self.index:04d}-execution-map.json').write_text(json.dumps(dict(
            stage=stage,visual_axes=axes,selected=choices,diagnostic_only_error_rad=error.tolist(),
            mapping={'counterclockwise':'positive','clockwise':'negative'}),indent=2)+'\n')
        self.index+=1
        return answer

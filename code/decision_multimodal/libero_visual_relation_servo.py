"""Classify a current visual relation; compile it through a public fixed-axis map."""
import base64
from copy import deepcopy
import hashlib
import io
import sys

import libero_visual_servo as base
from legacy_decisions import convert_request,english
from libero_motion_multimodal import assert_no_camera_matrices

LINE='--image-midline' in sys.argv
if LINE:sys.argv.remove('--image-midline')


class RelationAPI(base.VisualServoAPI):
    profile='libero-image-relation-line-v5' if LINE else 'libero-image-relation-v4'

    def revise(self,original):
        result=deepcopy(original)
        a,b=('left','right') if self.axis=='y' else ('above','below')
        line='vertical' if self.axis=='y' else 'horizontal'
        result['state']=dict(source='The gray patterned bowl, not the flat plate',
            task='Classify the current bowl center relative to the image center line',
            image='Current fixed-center enlargement of the wrist RGB image')
        result['questions']={'bowl_location':dict(type='choice',
            instructions=f'Where is the CENTER of the gray patterned bowl relative to the {line} image center line? '
                'Judge the center of the bowl outline, not whether some part of the bowl crosses the line. '
                'Use only the current image.',
            criteria={a:f'The bowl center is {a} of the image center line.',
                'center':'The bowl center is aligned with the image center line.',
                b:f'The bowl center is {b} of the image center line.'})}
        return result

    def build_payload(self,sent):
        from PIL import Image,ImageDraw
        payload=convert_request(sent)
        view=next(v for v in self.views if v['camera']=='robot0_eye_in_hand')
        picture=Image.open(io.BytesIO(view['raw'])).convert('RGB').crop((192,192,576,576)).resize((768,768))
        if LINE:
            draw=ImageDraw.Draw(picture)
            endpoints=(384,0,384,767) if self.axis=='y' else (0,384,767,384)
            draw.line(endpoints,fill='#00ffff',width=3)
        buffer=io.BytesIO();picture.save(buffer,format='PNG');raw=buffer.getvalue()
        path=self.asset_root/f'{self.calls:04d}-relation.png';path.write_bytes(raw)
        payload['input']=[dict(role='user',content=[
            dict(type='input_text',text=payload['input']),
            dict(type='input_text',text='The image is a fixed-center enlargement. Its center is the center of the full wrist image.'+
                (' The cyan line marks that image midline.' if LINE else ' Use the midpoint between the image edges.')),
            dict(type='input_image',detail='high',image_url='data:image/png;base64,'+base64.b64encode(raw).decode())])]
        self.image_count=1
        self.metadata=dict(camera_views=[dict(camera='current_wrist_center_crop',rgb_path=str(path),
            sha256=hashlib.sha256(raw).hexdigest(),width=768,height=768,
            native_observation_counter=view['native_observation_counter'])],
            camera_matrices_sent=False,eef_coordinates_sent=False,numeric_residuals_sent=False,
            history_images=False,fixed_image_midline=LINE,target_markers=False,
            decision_role='image relation only; fixed validated map converts relation to motion')
        english(payload);assert_no_camera_matrices(payload)
        return payload

    def post(self,endpoint,original):
        self.axis=next(iter(original['questions']))
        raw=super().post(endpoint,original)
        answer=raw['answers']['bowl_location']
        mapping=({'left':'positive','center':'hold','right':'negative'} if self.axis=='y' else
                 {'above':'positive','center':'hold','below':'negative'})
        choice=mapping[answer['choice']]
        base.save(self.folder/f'{self.calls-1:04d}'/'execution-map.json',dict(
            relation_choice=answer['choice'],world_axis=self.axis,executed_category=choice,
            mapping=mapping,source='Fixed public wrist orientation and independently verified motion semantics',
            no_geometric_residual_used=True))
        converted=deepcopy(raw)
        converted['answers']={self.axis:dict(answer,choice=choice,
            probabilities={mapping[k]:v for k,v in answer['probabilities'].items()})}
        return converted


base.VisualServoAPI=RelationAPI
original_save=base.save


def save(path,value):
    if path.name=='manifest.json':
        value.update(profile=RelationAPI.profile,fixed_image_midline=LINE,
            visual_output_schema='left/center/right or above/center/below',
            execution_mapping='Fixed public orientation; no target residual in mapping')
        value['source_sha256']['libero_visual_relation_servo.py']=hashlib.sha256(base.Path(__file__).read_bytes()).hexdigest()
    original_save(path,value)


base.save=save
if __name__=='__main__':
    base.main()

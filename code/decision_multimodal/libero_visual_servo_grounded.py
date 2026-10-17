"""Grounded visual choice descriptions; optional fixed-center RGB zoom."""
import base64
from copy import deepcopy
import hashlib
import io
import sys

import libero_visual_servo as base

ZOOM='--center-zoom' in sys.argv
if ZOOM:sys.argv.remove('--center-zoom')


class GroundedAPI(base.VisualServoAPI):
    profile='libero-visible-center-grounded-zoom-v3' if ZOOM else 'libero-visible-center-grounded-v2'

    def revise(self,original):
        sent=deepcopy(original)
        axis=next(iter(sent['questions']))
        left,right=('left','right') if axis=='y' else ('above','below')
        goal='vertical' if axis=='y' else 'horizontal'
        sent['questions'][axis].update(
            instructions=('Judge the CENTER of the patterned gray bowl in the CURRENT wrist image. '
                f'Compare that center with the {goal} center line of the image. '
                'A bowl can overlap the line while its center remains off-center. '
                'Choose the option whose visible spatial condition matches now. '
                'The option also specifies the corresponding verified world-axis direction.'),
            criteria=dict(
                negative=f'The bowl center is {right} of the image center line; use the negative world-axis increment to bring it toward the center.',
                hold='The CENTER of the bowl is aligned with the image center line; keep this axis still.',
                positive=f'The bowl center is {left} of the image center line; use the positive world-axis increment to bring it toward the center.'))
        return sent

    def build_payload(self,sent):
        payload=super().build_payload(sent)
        if not ZOOM:return payload
        from PIL import Image
        content=payload['input'][0]['content']
        frames=[]
        if self.temporal and self.previous is not None:frames.append(('PREVIOUS',self.previous))
        frames.append(('CURRENT',self.views))
        for label,views in frames:
            view=next(v for v in views if v['camera']=='robot0_eye_in_hand')
            picture=Image.open(io.BytesIO(view['raw'])).convert('RGB')
            # Fixed image-center crop, never a target-dependent location or marker.
            picture=picture.crop((192,192,576,576)).resize((768,768))
            buffer=io.BytesIO();picture.save(buffer,format='PNG');raw=buffer.getvalue()
            path=self.asset_root/f'{label.lower()}-{self.calls:04d}-center-zoom.png';path.write_bytes(raw)
            content += [dict(type='input_text',text=label+' fixed-center zoom of the wrist image. '
                'Its center is the same as the full wrist image center. No point marks are added. '
                'Use this enlarged view to judge the bowl CENTER, not merely whether the bowl overlaps the center line.'),
                dict(type='input_image',detail='high',image_url='data:image/png;base64,'+base64.b64encode(raw).decode())]
            self.metadata['camera_views'].append(dict(time_label=label,camera='wrist_center_zoom',
                rgb_path=str(path),sha256=hashlib.sha256(raw).hexdigest(),width=768,height=768,
                native_observation_counter=view['native_observation_counter'],fixed_crop_xyxy=[192,192,576,576]))
        self.image_count=len(self.metadata['camera_views'])
        self.metadata['fixed_center_zoom']=True
        return payload


base.VisualServoAPI=GroundedAPI
original_save=base.save


def save(path,value):
    if path.name=='manifest.json':
        value.update(grounded_options=True,fixed_center_zoom=ZOOM,profile=GroundedAPI.profile)
        value['source_sha256']['libero_visual_servo_grounded.py']=hashlib.sha256(
            base.Path(__file__).read_bytes()).hexdigest()
    original_save(path,value)


base.save=save

if __name__=='__main__':
    base.main()

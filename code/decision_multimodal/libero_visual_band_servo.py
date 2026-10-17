"""A visible acceptance band for current-image relation control, version6."""
import base64
import hashlib
import io

from PIL import Image,ImageDraw
import libero_visual_servo as base
from libero_visual_relation_servo import RelationAPI,original_save


class BandAPI(RelationAPI):
    profile='libero-image-relation-band-v6'

    def revise(self,original):
        if next(iter(original['questions']))!='y':
            raise ValueError('The frozen band pilot is horizontal centering only')
        sent=super().revise(original)
        sent['state']['task']='Bring the bowl outline center inside the cyan central band'
        sent['state']['task_plan']=original['state']['task_plan']
        q=sent['questions']['bowl_location']
        q['instructions']=(
            'Where is the CENTER of the gray patterned bowl outline relative to the cyan band? '
            'Choose center if that center is inside the band, even if it is not exactly on the image midpoint. '
            'Judge the bowl center, not whether its rim or another object touches the band. Use only this current image.')
        q['criteria']={
            'left':'The bowl center is left of the left cyan boundary.',
            'center':'The bowl center is inside or on the cyan band boundaries.',
            'right':'The bowl center is right of the right cyan boundary.'}
        return sent

    def build_payload(self,sent):
        payload=super().build_payload(sent)
        content=payload['input'][0]['content']
        item=next(p for p in content if p['type']=='input_image')
        raw=base64.b64decode(item['image_url'].split(',',1)[1])
        picture=Image.open(io.BytesIO(raw)).convert('RGBA')
        layer=Image.new('RGBA',picture.size);draw=ImageDraw.Draw(layer)
        # The crop doubles resolution; +/-32 here equals +/-16 original pixels.
        # No source estimate or robot pose affects this fixed image band.
        draw.rectangle((352,0,416,767),fill=(0,255,255,20))
        draw.line((352,0,352,767),fill=(0,255,255,255),width=2)
        draw.line((416,0,416,767),fill=(0,255,255,255),width=2)
        picture=Image.alpha_composite(picture,layer).convert('RGB')
        buffer=io.BytesIO();picture.save(buffer,format='PNG');raw=buffer.getvalue()
        path=self.asset_root/f'{self.calls:04d}-band.png';path.write_bytes(raw)
        item['image_url']='data:image/png;base64,'+base64.b64encode(raw).decode()
        content[1]['text']=(
            'Current wrist RGB, enlarged around the fixed image center. '
            'The cyan strip between the two vertical cyan boundaries is the acceptable central region. '
            'A bowl whose outline center is inside this strip is centered for this task. '
            'The band is fixed in the image; it is not a TCP or object-position marker.')
        self.metadata['camera_views'][0].update(rgb_path=str(path),sha256=hashlib.sha256(raw).hexdigest())
        self.metadata.update(fixed_image_acceptance_band=True,numeric_residuals_sent=False)
        return payload


base.VisualServoAPI=BandAPI
previous_save=original_save


def save(path,value):
    if path.name=='manifest.json':
        value.update(profile=BandAPI.profile,fixed_image_acceptance_band=True,
            band_in_crop_pixels=[352,416],target_point_markers=False)
        value['source_sha256']['libero_visual_band_servo.py']=hashlib.sha256(base.Path(__file__).read_bytes()).hexdigest()
        value['source_sha256']['libero_visual_relation_servo.py']=hashlib.sha256(base.Path(__file__).with_name('libero_visual_relation_servo.py').read_bytes()).hexdigest()
    previous_save(path,value)


base.save=save
if __name__=='__main__':base.main()

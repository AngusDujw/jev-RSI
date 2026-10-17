"""In-frame world axes, no point markers, EEF coordinates or actor tolerances."""
import argparse
import base64
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import re

from legacy_decisions import convert_request, english
import libero_multimodal as stream
from libero_motion_multimodal import MotionRGBAPI, remove_xyz_feedback

PROFILE = 'libero-rgb-inframe-axes-v1'
GRIPPER_PROFILE = 'libero-rgb-gripper-axes-v1'
MOTION_FILE = Path(__file__).with_name('libero_robot_actions_inframe_v1.txt')
AXIS_DESCRIPTION_FILE = Path(__file__).with_name('libero_gripper_axes_description_v1.txt')
# Remove all Cartesian world components, including old *_world_xy_m fields.
POSITION_KEY = re.compile(r'(?:tolerance|eef|tcp|translation|position|coordinate|'
    r'_world_[xyz]+(?:_|$)|_world_m$|_center_m$|_bounds(?:_m)?$|'
    r'(?:gap|distance|progress|offset).*(?:_mm|_m)$)', re.I)


def removed_field(key,value):
    # Position-arrival booleans are existing stage gates, not coordinates.
    return bool(POSITION_KEY.search(key)) and not (
        isinstance(value,bool) and 'tolerance' not in key.lower())


def categorical_history(value):
    """Retain executed categories, not normalized motor vectors or pose numbers."""
    if isinstance(value, dict):
        return {k:categorical_history(v) for k,v in value.items()
                if isinstance(v, (str, bool, dict)) and not POSITION_KEY.search(k)}
    if isinstance(value, list):
        return [categorical_history(v) for v in value if isinstance(v, dict)]
    return value


def reduce_state(value):
    if isinstance(value, dict):
        return {k:(categorical_history(v) if k=='recent_actions' else reduce_state(v))
                for k,v in value.items() if not removed_field(k,v)}
    if isinstance(value, list):
        return [reduce_state(v) for v in value]
    return value


def arrival_language(value):
    if isinstance(value,dict):
        return {k:arrival_language(v) for k,v in value.items()}
    if isinstance(value,list):
        return [arrival_language(v) for v in value]
    if isinstance(value,str):
        return value.replace('when within tolerance','when the current arrival check passes')
    return value


def assert_no_position_or_tolerance(value):
    if isinstance(value, dict):
        for key,item in value.items():
            if removed_field(key,item):
                raise ValueError('Removed actor field remains: '+key)
            assert_no_position_or_tolerance(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_position_or_tolerance(item)
    elif isinstance(value, str) and value.lstrip().startswith(('{','[')):
        try:
            decoded=json.loads(value)
        except ValueError:
            return
        assert_no_position_or_tolerance(decoded)


def overlay_axes(raw, camera_to_world):
    """Draw free world-axis directions at a fixed pixel anchor, never at a robot/goal."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    picture=Image.open(io.BytesIO(raw)).convert('RGB')
    draw=ImageDraw.Draw(picture)
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',22)
    small=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',15)
    anchor=np.array([picture.width*.145,picture.height*.16])
    length=min(picture.size)*.09
    rotation=np.asarray(camera_to_world,float)[:3,:3].T
    mask=Image.new('L',picture.size)
    maskdraw=ImageDraw.Draw(mask)
    axes=[]
    for i,(name,color) in enumerate(zip('XYZ',('#ff5959','#49df80','#67baff'))):
        v=rotation[:,i];screen=float(np.linalg.norm(v[:2]));depth=v[2]
        if screen < .20:
            x,y=anchor
            for painter,ink in ((draw,color),(maskdraw,255)):
                painter.ellipse((x-8,y-8,x+8,y+8),outline=ink,width=3)
                if depth<0:
                    painter.ellipse((x-2,y-2,x+2,y+2),fill=ink)
                else:
                    painter.line((x-5,y-5,x+5,y+5),fill=ink,width=3)
                    painter.line((x-5,y+5,x+5,y-5),fill=ink,width=3)
            label=anchor+np.array([13.,9.])
            end=None
        else:
            direction=v[:2]/screen
            end=anchor+v[:2]*length
            normal=np.array([-direction[1],direction[0]])
            head=[tuple(end),tuple(end-direction*12+normal*6),tuple(end-direction*12-normal*6)]
            draw.line((tuple(anchor),tuple(end)),fill='#111a16',width=7)
            draw.line((tuple(anchor),tuple(end)),fill=color,width=4)
            draw.polygon(head,fill=color)
            maskdraw.line((tuple(anchor),tuple(end)),fill=255,width=7)
            maskdraw.polygon(head,fill=255)
            if direction[1]<-.5:
                label=end+np.array([4.,-29.])
            elif direction[1]>.5:
                label=end+np.array([4.,4.])
            elif direction[0]<0:
                label=end+np.array([-26.,8.])
            else:
                label=end+np.array([7.,-13.])
        draw.text(tuple(label),'+'+name,font=font,fill=color,stroke_width=2,stroke_fill='#111a16')
        maskdraw.text(tuple(label),'+'+name,font=font,fill=255,stroke_width=2,stroke_fill=255)
        axes.append(dict(axis=name,camera_vector=v.tolist(),end_pixel=end.tolist() if end is not None else None,
                         depth_symbol=('toward' if depth<0 else 'away') if screen<.20 else None))
    label=(18,18)
    draw.text(label,'World axes',font=small,fill='white',stroke_width=2,stroke_fill='#111a16')
    maskdraw.text(label,'World axes',font=small,fill=255,stroke_width=2,stroke_fill=255)
    buffer=io.BytesIO();picture.save(buffer,format='PNG')
    return buffer.getvalue(),mask,dict(anchor_pixel=anchor.tolist(),axes=axes,
        uses_robot_or_target_position=False,dimensions=list(picture.size))


def overlay_gripper_axes(raw,camera_to_world,intrinsics,gripper_world,camera):
    """Project current own grip_site; draw only the two user-selected world axes."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    shown={'agentview':('Y','Z'),'robot0_eye_in_hand':('X','Y')}[camera]
    picture=Image.open(io.BytesIO(raw)).convert('RGB')
    draw=ImageDraw.Draw(picture);mask=Image.new('L',picture.size);md=ImageDraw.Draw(mask)
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',22)
    world_to_camera=np.linalg.inv(np.asarray(camera_to_world,float))
    K=np.asarray(intrinsics,float)
    pc=(world_to_camera@np.r_[np.asarray(gripper_world,float),1.])[:3]
    h=K@pc
    origin=h[:2]/h[2] if pc[2]>0 else None
    visible=origin is not None and 0<=origin[0]<picture.width and 0<=origin[1]<picture.height
    audit=dict(anchor_pixel=origin.tolist() if origin is not None else None,
        origin_visible=bool(visible),shown_axes=list(shown),axes=[],
        origin_source='current measured own gripper control reference',uses_target_position=False,
        dimensions=list(picture.size))
    if visible:
        for name in shown:
            i='XYZ'.index(name);color=('#ff5959','#49df80','#67baff')[i]
            dh=K@world_to_camera[:3,i]
            derivative=(dh[:2]*h[2]-h[:2]*dh[2])/(h[2]**2)
            norm=float(np.linalg.norm(derivative))
            if norm<1e-6:
                audit['axes'].append(dict(axis=name,omitted='no resolvable screen direction'))
                continue
            direction=derivative/norm
            length=min(picture.size)*.09
            for j,limit in enumerate(picture.size):
                if direction[j]>1e-9:
                    length=min(length,(limit-9-origin[j])/direction[j])
                elif direction[j]<-1e-9:
                    length=min(length,(8-origin[j])/direction[j])
            if length<14:
                audit['axes'].append(dict(axis=name,omitted='insufficient image margin'))
                continue
            end=origin+direction*length
            normal=np.array([-direction[1],direction[0]])
            head=[tuple(end),tuple(end-direction*12+normal*6),tuple(end-direction*12-normal*6)]
            draw.line((tuple(origin),tuple(end)),fill='#111a16',width=7)
            draw.line((tuple(origin),tuple(end)),fill=color,width=4);draw.polygon(head,fill=color)
            md.line((tuple(origin),tuple(end)),fill=255,width=7);md.polygon(head,fill=255)
            offset=([4.,-29.] if direction[1]<-.5 else [4.,4.] if direction[1]>.5
                    else [-26.,8.] if direction[0]<0 else [7.,-13.])
            label=end+np.array(offset)
            label[0]=np.clip(label[0],2,picture.width-40);label[1]=np.clip(label[1],2,picture.height-30)
            draw.text(tuple(label),'+'+name,font=font,fill=color,stroke_width=2,stroke_fill='#111a16')
            md.text(tuple(label),'+'+name,font=font,fill=255,stroke_width=2,stroke_fill=255)
            audit['axes'].append(dict(axis=name,end_pixel=end.tolist(),screen_derivative_per_m=derivative.tolist()))
    buffer=io.BytesIO();picture.save(buffer,format='PNG')
    return buffer.getvalue(),mask,audit


class InFrameAxesAPI(MotionRGBAPI):
    profile=PROFILE
    condition='inframe_axes_no_point_markers_no_eef_no_tolerance'

    def revise(self, original):
        # Invoke the shared stable stage questions directly; never mutate v1 profiles.
        sent=stream.MultimodalAPI.revise(self,original)
        sent['state']=reduce_state(remove_xyz_feedback(sent['state']))
        for axis in 'xyz':
            if axis in sent['questions']:
                sent['questions'][axis]['instructions']=(
                    f'Select {axis.upper()} direction toward current phase goal using the current labeled RGB images. '
                    'Choose hold when no adjustment on this axis is visually needed. '
                    'During gripper-only phases grasp/release always hold all XYZ.')
        sent=arrival_language(sent)
        english(sent);assert_no_position_or_tolerance(sent['state'])
        return sent

    def transform_views(self,views,robot):
        folder=self.asset_root/'inframe-inputs';folder.mkdir(exist_ok=True)
        for view in views:
            raw,_,audit=overlay_axes(view['raw'],view['camera_to_world'])
            path=folder/f'{view["native_observation_counter"]:06d}-{self.calls:04d}-{view["camera"]}.png'
            path.write_bytes(raw)
            view.update(original_rgb_path=view['rgb_path'],rgb_path=str(path),raw=raw,
                        sha256=hashlib.sha256(raw).hexdigest(),overlay_audit=audit)
            view['description'] += (' The arrows drawn inside the image show positive world-axis '
                'directions: red +X, green +Y, blue +Z. A circled dot points toward the camera; '
                'a circled cross points away. Their common origin is a fixed graphic anchor. '
                'Use the scene to identify the source and destination for the current phase.')
        return views

    def payload_from_views(self,sent,views,robot):
        if not sent['questions']:
            return None
        payload=convert_request(sent)
        views=self.transform_views(deepcopy(views),robot)
        cameras=[{k:v[k] for k in ('camera','description','native_observation_counter','width','height')}
                 for v in views]
        context=dict(camera_views=cameras,
            measured_robot={k:v for k,v in robot.items() if k=='robot0_gripper_qpos'},
            units='Gripper joint positions are metres.',
            timing='Both views are current. No simulator steps occur during this decision.')
        content=[dict(type='input_text',text=MOTION_FILE.read_text()),
                 dict(type='input_text',text=payload['input']),
                 dict(type='input_text',text=json.dumps(context,allow_nan=False))]
        for view in views:
            content += [dict(type='input_text',text='Current RGB image: '+view['camera']+'. '+view['description']),
                dict(type='input_image',detail='high',image_url='data:image/png;base64,'+base64.b64encode(view['raw']).decode())]
        payload['input']=[dict(role='user',content=content)]
        self.last_input_metadata=dict(camera_views=[{k:v for k,v in view.items() if k!='raw'} for view in views],
            image_condition=self.condition,camera_matrices_sent=False,target_markers=False,
            eef_coordinates_sent=False,numeric_tolerances_sent=False,experience_injection=False)
        self.validate_payload(payload)
        return payload

    def build_payload(self,sent):
        if not sent['questions']:
            return None
        views,robot=stream.CURRENT.capture(self.asset_root)
        return self.payload_from_views(sent,views,robot)

    def validate_payload(self,payload):
        super().validate_payload(payload)
        if payload is not None:
            english(payload);assert_no_position_or_tolerance(payload)
            texts=[p['text'] for p in payload['input'][0]['content'] if p['type']=='input_text']
            texts += [q['instructions'] for q in payload['questions']]
            if any(re.search(r'\btolerance\b',t,re.I) for t in texts):
                raise ValueError('Tolerance wording remains in the actor input')


class GripperAxesAPI(InFrameAxesAPI):
    profile=GRIPPER_PROFILE
    condition='gripper_axes_two_per_view_no_numeric_eef_or_tolerance'

    def transform_views(self,views,robot):
        folder=self.asset_root/'gripper-inputs';folder.mkdir(exist_ok=True)
        for view in views:
            raw,_,audit=overlay_gripper_axes(view['raw'],view['camera_to_world'],view['K'],
                robot['robot0_eef_pos'],view['camera'])
            path=folder/f'{view["native_observation_counter"]:06d}-{self.calls:04d}-{view["camera"]}.png'
            path.write_bytes(raw)
            view.update(original_rgb_path=view['rgb_path'],rgb_path=str(path),raw=raw,
                sha256=hashlib.sha256(raw).hexdigest(),overlay_audit=audit)
            if not audit['origin_visible']:
                view['description'] += ' The gripper reference is outside this image; its arrows are omitted.'
            else:
                view['description'] += (' Green +Y and blue +Z arrows start at the current gripper reference.'
                    if view['camera']=='agentview' else
                    ' Red +X and green +Y arrows start at the current gripper reference.')
        return views

    def payload_from_views(self,sent,views,robot):
        payload=super().payload_from_views(sent,views,robot)
        if payload is not None:
            description=AXIS_DESCRIPTION_FILE.read_text()
            payload['input'][0]['content'].insert(1,dict(type='input_text',text=description))
            self.last_input_metadata.update(axis_origin_uses_current_own_gripper_position=True,
                axis_description_sha256=hashlib.sha256(description.encode()).hexdigest())
            self.validate_payload(payload)
        return payload


def preview():
    parser=argparse.ArgumentParser(description='Prepare an archived-RGB preview without model or simulator calls.')
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--task',type=int,default=1144)
    parser.add_argument('--gripper-axes',action='store_true',help='Anchor two selected axes at the current gripper projection')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    kind=GripperAxesAPI if args.gripper_axes else InFrameAxesAPI
    api=kind.__new__(kind)
    api.asset_root=args.output;api.calls=0;api.task=args.task
    original=json.loads((args.source/'legacy-request.json').read_text())
    dispatch=json.loads((args.source/'source-dispatch.json').read_text())
    from PIL import Image
    views=[]
    for source in dispatch['camera_views']:
        camera=source['camera'];path=args.source/(camera+'.png');raw=path.read_bytes()
        width,height=Image.open(io.BytesIO(raw)).size
        views.append(dict(camera=camera,description=stream.DESCRIPTIONS[camera],
            native_observation_counter=source['native_observation_counter'],width=width,height=height,
            K=source['K'],camera_to_world=source['camera_to_world'],rgb_path=str(path),raw=raw))
    sent=api.revise(original)
    payload=api.payload_from_views(sent,views,dispatch['measured_robot'])
    (args.output/'prepared-request-NOT-SENT.json').write_text(json.dumps(payload,indent=2)+'\n')
    (args.output/'revised-legacy-request-NOT-SENT.json').write_text(json.dumps(sent,indent=2)+'\n')
    (args.output/'dispatch.json').write_text(json.dumps(dict(preview_only=True,model_calls=0,native_steps=0,
        source=str(args.source),**api.last_input_metadata),indent=2)+'\n')
    texts=[part['text'] for part in payload['input'][0]['content'] if part['type']=='input_text']
    (args.output/'prepared-input-text-NOT-SENT.txt').write_text(
        'PREVIEW ONLY — no model call or new native episode.\n\n'+'\n\n'.join(texts)+
        '\n\nQuestions:\n'+json.dumps(payload['questions'],indent=2)+'\n')
    print(json.dumps(dict(preview_only=True,model_calls=0,native_steps=0,output=str(args.output))))


if __name__=='__main__':
    preview()

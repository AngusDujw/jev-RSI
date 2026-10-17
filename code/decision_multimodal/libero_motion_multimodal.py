"""Matched LIBERO motion-description conditions with no camera matrices in model input."""
import base64
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import re

import libero_multimodal as stream
from legacy_decisions import convert_request, english
from libero_multimodal import MultimodalAPI
from libero_visual_ablation import WaypointAPI

PROFILES = ('libero-rgb-motion-full-v1', 'libero-rgb-motion-marker-v1',
            'libero-rgb-motion-axes-v1')
MOTION_FILE = Path(__file__).with_name('libero_robot_actions_v1.txt')
POSITION_FIELDS = {'translation_axes', 'error_mm', 'axis_relations', 'max_error_mm',
    'phase_goal_distance_mm', 'last_progress_m', 'progress_mm', 'position_error_m',
    'position_error_mm', 'target_position_m', 'goal_position_m', 'target_xyz', 'goal_xyz'}
GEOMETRY_KEY = re.compile(r'(?:_world_m$|_world_[xyz](?:_|$)|_coordinate_m$|_center_m$|_bounds(?:_m)?$)')
FORBIDDEN_CAMERA_KEYS = {'K', 'T', 'camera_to_world', 'world_to_camera', 'intrinsics',
                         'extrinsics', 'camera_intrinsics', 'camera_extrinsics'}


def remove_xyz_feedback(value):
    """Remove positional feedback; keep phase contracts and non-XYZ questions intact."""
    if isinstance(value, dict):
        return {k:remove_xyz_feedback(v) for k,v in value.items()
                if k not in POSITION_FIELDS and not GEOMETRY_KEY.search(k)}
    if isinstance(value, list):
        return [remove_xyz_feedback(v) for v in value]
    return value


def assert_no_camera_matrices(value):
    if isinstance(value, dict):
        if FORBIDDEN_CAMERA_KEYS.intersection(value):
            raise ValueError('Camera matrices must not be sent to the actor')
        for v in value.values():
            assert_no_camera_matrices(v)
    elif isinstance(value, list):
        for v in value:
            assert_no_camera_matrices(v)
    elif isinstance(value, str) and value.lstrip().startswith(('{','[')):
        try:
            decoded = json.loads(value)
        except ValueError:
            return
        assert_no_camera_matrices(decoded)


class MotionRGBAPI(MultimodalAPI):
    profile = PROFILES[0]
    condition = 'motion_full_no_camera_matrices'
    remove_xyz = False
    markers = False
    axes = False

    def revise(self, original):
        # Same latest stable stage/closure protocol in every condition.
        revised = super().revise(original)
        self.unmasked_state = deepcopy(revised['state'])
        if self.remove_xyz:
            revised['state'] = remove_xyz_feedback(revised['state'])
        for axis in 'xyz':
            if axis in revised['questions']:
                basis = ('the current labeled RGB images' if self.remove_xyz else
                         'observed error and the current labeled RGB images')
                revised['questions'][axis]['instructions'] = (
                    f'Select {axis.upper()} direction toward current phase goal using {basis}. '
                    'Hold within tolerance. During gripper-only phases grasp/release always hold all XYZ.')
        english(revised)
        return revised

    def transform_views(self, views, robot):
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont
        if self.markers:
            views = WaypointAPI.transform_views(self, views, robot)
        folder = self.asset_root/'motion-inputs'
        folder.mkdir(exist_ok=True)
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 16)
        small = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 13)
        for view in views:
            original = Image.open(io.BytesIO(view['raw'])).convert('RGB')
            picture = Image.new('RGB',(original.width,original.height+160),'#13251e')
            picture.paste(original,(0,0))
            draw = ImageDraw.Draw(picture)
            draw.text((15,original.height+10),view['camera']+' / current RGB',font=font,fill='white')
            if self.axes:
                # A camera-oriented compass of free world vectors, not a target-dependent ruler.
                # Translation is omitted deliberately; no image-motion magnitude is encoded.
                R = np.asarray(view['camera_to_world'],float)[:3,:3].T
                origin = np.array([86.,original.height+96.])
                for index,(axis,color) in enumerate(zip('XYZ',('#ff6868','#63e48d','#75b7ff'))):
                    v = R[:,index]
                    length = float(np.linalg.norm(v[:2]))
                    if length < .20:
                        center = origin + np.array([0.,0.])
                        draw.ellipse((center[0]-8,center[1]-8,center[0]+8,center[1]+8),outline=color,width=2)
                        if v[2] < 0:
                            draw.ellipse((center[0]-2,center[1]-2,center[0]+2,center[1]+2),fill=color)
                        else:
                            draw.line((center[0]-4,center[1]-4,center[0]+4,center[1]+4),fill=color,width=2)
                            draw.line((center[0]-4,center[1]+4,center[0]+4,center[1]-4),fill=color,width=2)
                    else:
                        end = origin+v[:2]*47
                        unit=v[:2]/length
                        normal=np.array([-unit[1],unit[0]])
                        draw.line((tuple(origin),tuple(end)),fill=color,width=3)
                        draw.polygon([tuple(end),tuple(end-unit*8+normal*4),tuple(end-unit*8-normal*4)],fill=color)
                        draw.text(tuple(end+np.array([3.,-9.])), '+'+axis,font=font,fill=color)
                    depth = 'toward camera' if v[2]<0 else 'away from camera'
                    draw.text((190,original.height+45+index*27),
                        '+'+axis+(' / '+depth if length<.20 else ''),font=font,fill=color)
                draw.text((390,original.height+46),'World-axis orientation legend',font=font,fill='white')
                draw.text((390,original.height+76),'Arrow: positive world direction',font=small,fill='#cad9cd')
                draw.text((390,original.height+101),'Dot: toward camera / cross: away',font=small,fill='#cad9cd')
                draw.text((390,original.height+125),'Not a target or metric error',font=small,fill='#cad9cd')
                view['description'] += (' Footer: camera-oriented world-axis legend, red +X, green +Y, '
                    'blue +Z. Arrows show axis orientation, not the target direction or metric pixel '
                    'motion. A circled dot points toward the camera; a circled cross points away.')
            buffer=io.BytesIO();picture.save(buffer,format='PNG');raw=buffer.getvalue()
            path=folder/f'{view["native_observation_counter"]:06d}-{self.calls:04d}-{view["camera"]}.png'
            path.write_bytes(raw)
            view.update(unpadded_rgb_path=view['rgb_path'],rgb_path=str(path),raw=raw,
                sha256=hashlib.sha256(raw).hexdigest(),height=picture.height,
                world_axis_legend=self.axes,legend_uses_target=False)
        return views

    def build_payload(self,sent):
        if not sent['questions']:
            return None
        payload=convert_request(sent)
        views,robot=stream.CURRENT.capture(self.asset_root)
        views=self.transform_views(views,robot)
        # The camera matrices and local paths remain in the audit, never in the payload.
        cameras=[{k:v[k] for k in ('camera','description','native_observation_counter','width','height')}
                 for v in views]
        context=dict(camera_views=cameras,
            measured_robot={k:v for k,v in robot.items() if k in ('robot0_eef_pos','robot0_gripper_qpos')},
            units='Robot position and gripper joint positions are metres.',
            timing='Both views are current. No simulator steps occur during this decision.')
        motion=MOTION_FILE.read_text()
        content=[dict(type='input_text',text=motion),
                 dict(type='input_text',text=payload['input']),
                 dict(type='input_text',text=json.dumps(context,allow_nan=False))]
        for view in views:
            content += [dict(type='input_text',text='Current RGB image: '+view['camera']+'. '+view['description']),
                dict(type='input_image',detail='high',image_url='data:image/png;base64,'+base64.b64encode(view['raw']).decode())]
        payload['input']=[dict(role='user',content=content)]
        self.last_input_metadata=dict(camera_views=[{k:v for k,v in x.items() if k!='raw'} for x in views],
            measured_robot=robot,image_condition=self.condition,target_markers=self.markers,
            camera_matrices_sent=False,motion_description_sha256=hashlib.sha256(motion.encode()).hexdigest(),
            non_xyz_questions_unchanged_from_common_text_profile=True,
            xyz_feedback_removed=self.remove_xyz,world_axis_legend=self.axes)
        english(payload);assert_no_camera_matrices(payload)
        return payload

    def validate_payload(self,payload):
        super().validate_payload(payload)
        if payload is not None:
            assert_no_camera_matrices(payload)


class MotionMarkerAPI(MotionRGBAPI):
    profile=PROFILES[1]
    condition='motion_no_xyz_markers_no_camera_matrices'
    remove_xyz=True
    markers=True


class MotionAxesAPI(MotionMarkerAPI):
    profile=PROFILES[2]
    condition='motion_no_xyz_markers_world_axes_no_camera_matrices'
    axes=True

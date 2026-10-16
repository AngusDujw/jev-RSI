"""Fresh, named LIBERO RGB inputs; no evaluator or object-state access."""
import base64
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import sys

from legacy_decisions import MODEL, convert_request, english
from libero_prompt_revision import RevisedAPI
from libero_prompt_revision_v2 import revise_local, revise_recovery

CAMERAS = ('agentview', 'robot0_eye_in_hand')
DESCRIPTIONS = {
    'agentview': 'Fixed external camera. It observes the robot and tabletop workspace from outside the hand; its world pose stays fixed.',
    'robot0_eye_in_hand': 'Robot-mounted wrist camera. It moves and rotates with the hand; its image axes are not fixed world axes.'}
CURRENT = None


class ObservationStream:
    def __init__(self):
        self.tick = 0
        self.env = self.observation = None

    def record(self, env, observation):
        # Whitelist public sensor outputs. Never store reward/done/info or object fields.
        self.env = env
        self.observation = {name: observation[name].copy() for name in (
            'agentview_image', 'robot0_eye_in_hand_image', 'robot0_eef_pos',
            'robot0_eef_quat', 'robot0_joint_pos', 'robot0_gripper_qpos') if name in observation}

    def capture(self, asset_root):
        import numpy as np
        from PIL import Image
        from robosuite.utils.camera_utils import get_camera_intrinsic_matrix, get_camera_extrinsic_matrix
        if self.observation is None:
            raise ValueError('No fresh public RGB observation')
        root = asset_root/'rgb'
        root.mkdir(exist_ok=True)
        views = []
        for camera in CAMERAS:
            rgb = np.ascontiguousarray(self.observation[camera+'_image'][::-1])
            buffer = io.BytesIO()
            Image.fromarray(rgb).save(buffer, format='PNG')
            raw = buffer.getvalue()
            path = root/f'{self.tick:06d}-{camera}.png'
            if path.exists() and path.read_bytes() != raw:
                raise ValueError('Conflicting RGB at identical native observation counter')
            if not path.exists():
                path.write_bytes(raw)
            K = get_camera_intrinsic_matrix(self.env.sim, camera, *rgb.shape[:2])
            T = get_camera_extrinsic_matrix(self.env.sim, camera)
            views.append(dict(camera=camera, description=DESCRIPTIONS[camera],
                native_observation_counter=self.tick, width=rgb.shape[1], height=rgb.shape[0],
                rgb_path=str(path), sha256=hashlib.sha256(raw).hexdigest(),
                K=K.tolist(), camera_to_world=T.tolist(), raw=raw))
        robot = {name: self.observation[name].tolist() for name in (
            'robot0_eef_pos', 'robot0_eef_quat', 'robot0_joint_pos', 'robot0_gripper_qpos') if name in self.observation}
        return views, robot


def install_stream(arguments):
    """Wrap public reset/step returns before executing the frozen rollout."""
    global CURRENT
    if CURRENT is not None:
        raise ValueError('Observation hook already installed')
    root = os.environ['JEV_RSI_LIBERO_ROOT']
    cache = Path(os.environ['DECISION_MM_ASSET_ROOT'])/'cache'
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.update(LIBERO_CONFIG_PATH=root+'/.libero-config', TMPDIR=str(cache),
                      XDG_CACHE_HOME=str(cache), MUJOCO_GL='egl')
    sys.path.insert(0, root)
    from libero.libero.envs.env_wrapper import ControlEnv
    CURRENT = ObservationStream()
    for name in ('reset', 'set_init_state', 'step'):
        original = getattr(ControlEnv, name)
        def wrapped(self, *args, _original=original, _name=name, **kwargs):
            result = _original(self, *args, **kwargs)
            if _name == 'step':
                CURRENT.tick += 1
                observation = result[0]
            else:
                CURRENT.tick = 0
                observation = result
            if isinstance(observation, dict) and 'agentview_image' in observation:
                CURRENT.record(self, observation)
            return result
        setattr(ControlEnv, name, wrapped)


class MultimodalAPI(RevisedAPI):
    profile = 'libero-rgb-full'
    image_count = 2

    def __init__(self, cfg, log, role):
        # New large image/API artifacts stay outside the old recorder byte budget.
        self.asset_root = Path(os.environ['DECISION_MM_ASSET_ROOT']).resolve()
        target = self.asset_root/'decision-api'
        target.mkdir(parents=True, exist_ok=True)
        recorder = log.__self__
        link = Path(recorder.folder)/'decision-api'
        if link.is_symlink():
            if link.resolve() != target:
                raise ValueError('Unexpected API audit symlink')
        elif link.exists():
            raise ValueError('Refusing to replace an existing API log directory')
        else:
            link.symlink_to(target, target_is_directory=True)
        super().__init__(cfg, log, role)
        self.task = int(recorder.cfg['task_id'])
        self.last_input_metadata = {}

    def revise(self, original):
        if self.task == 1423:
            return revise_recovery(original)
        if self.task in (1144, 1202, 1252, 1296):
            return revise_local(original)
        return deepcopy(original)

    def build_payload(self, sent):
        payload = convert_request(sent) if sent['questions'] else None
        if payload is None:
            return None
        views, robot = CURRENT.capture(self.asset_root)
        metadata = [dict((k,v) for k,v in view.items() if k != 'raw') for view in views]
        context = dict(camera_views=metadata, measured_robot=robot,
            units='Robot world positions are metres; robot quaternion is XYZW. Camera matrices map OpenCV camera coordinates to world.',
            timing='Both RGB views are from the current observation. Counter includes ten neutral warmup steps; no simulator steps occur while the model is called.',
            interpretation='Image up/right is camera-dependent. Use the supplied current camera pose when relating world XYZ to image directions. No depth image is attached.')
        content = [dict(type='input_text', text=payload['input']),
                   dict(type='input_text', text=json.dumps(context, allow_nan=False))]
        for view in views:
            content.extend([dict(type='input_text', text=f'Current RGB image: {view["camera"]}. {view["description"]} Native observation counter {view["native_observation_counter"]}.'),
                dict(type='input_image', detail='high', image_url='data:image/png;base64,'+base64.b64encode(view['raw']).decode())])
        payload['input'] = [dict(role='user', content=content)]
        self.last_input_metadata = dict(camera_views=metadata, measured_robot=robot,
            original_structured_text_sha256=hashlib.sha256(content[0]['text'].encode()).hexdigest(),
            image_condition='rgb_full', target_markers=False)
        english(payload)
        return payload

    def validate_payload(self, payload):
        if payload is None:
            return
        if payload['model'] != MODEL or not isinstance(payload['input'], list):
            raise ValueError('Expected multimodal Decision payload')
        content = payload['input'][0]['content']
        if sum(c['type'] == 'input_image' for c in content) != 2:
            raise ValueError('Exactly two named current RGB images required')

    def input_audit(self):
        return self.last_input_metadata

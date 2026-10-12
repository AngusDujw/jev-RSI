"""Sensor-only, multimodal choices for a bounded stage controller."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image


CAMERAS = ('cam_high', 'cam_left_wrist', 'cam_right_wrist')
OBJECT_FIELDS = (
    'id', 'descriptions', 'visual_boxes', 'position_m', 'position_provenance',
    'position_measurement', 'last_stereo_age_ticks', 'last_seen_tick',
    'possibly_mobile', 'visual_motion_confirmed',
    'visual_cycle_count', 'visual_cycle_down', 'visual_cycle_valid',
    'visual_cycle_relative_m', 'visual_cycle_displacement_m',
)

DECISION_PROMPT = '''You are the lower-level GPT decision model in a RoboDojo
robot episode. The planner owns entity identity, sensing method, stage goals,
and replanning. You own only the listed discrete motor and stage choices.
Use the current camera images, planner-declared visual method, derived visual
measurements, and robot proprioception supplied here. Images are observations,
not simulator truth. A triangulated box centre is an estimate, not a grasp
contact or a success flag. Never infer hidden object pose, reward, native
success, collision state or grasp solely from a finger command. Judge each
motor sign from its measured target error and deadband; images may reveal a
specific contradiction or missing evidence and then you should request a
new observation or replan. Keep choices within the supplied criteria.
Return one JSON object mapping every question name to one criterion key,
with no additional keys, explanations, or Markdown.'''


def add_visual_question(questions, stage):
    result = dict(questions)
    if stage.visual_requirements:
        if stage.purpose == 'sense':
            result['visual_integrity'] = dict(type='choice', instructions=(
                'This is a bounded camera-search stage whose arm target depends only on robot state. '
                'Missing, occluded, or non-stereo target evidence is the reason to move the camera, '
                'not a reason to veto that safe search. Choose consistent unless the current images '
                'show a concrete wrong identity, unsafe camera path, or other contradiction to the '
                'declared search. Choose replan for such a specific contradiction.'),
                criteria={
                    'consistent': 'Proceed with bounded camera-search motion or measured stage transition',
                    'replan': 'Stop search and return a visible contradiction to the planner',
                })
            return result
        result['visual_integrity'] = dict(type='choice', instructions=(
            'Use the attached current images and sensor-derived object records. '
            'Choose consistent when they do not show a concrete contradiction to '
            'this stage. Choose reobserve if a required target is visually ambiguous '
            'or occluded. Choose replan only for a specific visible contradiction, '
            'such as the target moved, grasp failed, or the intended receiver differs. '
            'Do not treat lack of native success information as a contradiction.'),
            criteria={
                'consistent': 'Proceed with the bounded motor and transition choices',
                'reobserve': 'Get fresh camera evidence before another action',
                'replan': 'Stop action and return the current evidence to the planner',
            })
    return result


def prepare(log_folder, number, instruction, stage, state, questions, vision,
            evidence, observation, notes):
    """Choose views from the planner's current visual method; retain audit JPEGs."""
    needed = {item.id for item in stage.visual_requirements}
    entities = [item for item in (vision.method.entities if vision and vision.method else [])
                if item.id in needed]
    requested = {camera for item in entities for camera in item.preferred_views}
    if not requested:
        requested.add('cam_high')
        for arm in stage.arms:
            requested.add('cam_' + arm + '_wrist')
    names = [name for name in CAMERAS if name in requested and name in observation]
    if not names:
        raise ValueError('Decision input has no permitted current RGB camera')
    cameras = {}
    hashes = {}
    folder = Path(log_folder)
    for name in names:
        frame = observation[name]
        target = folder / f'decision-{number:04d}-{name}.jpg'
        Image.fromarray(frame).save(target, 'JPEG', quality=85)
        hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
        cameras[name] = SimpleNamespace(rgb=frame)
    objects = [{key: value for key, value in item.items() if key in OBJECT_FIELDS}
               for item in evidence['objects'] if item.get('id') in needed]
    robot = evidence['robot']
    request = dict(
        public_instruction=instruction,
        stage=dict(id=stage.id, objective=stage.objective, purpose=stage.purpose,
                   visual_requirements=[item.model_dump() for item in stage.visual_requirements]),
        motor_state=state,
        visual_method=[item.model_dump() for item in entities],
        visual_event_monitors=[item.model_dump() for item in vision.method.event_monitors
                               if item.moving_id in needed] if vision and vision.method else [],
        camera_derived_objects=objects,
        robot_proprioception={key: robot[key] for key in ('eef_positions_m', 'states')
                              if key in robot},
        questions=questions,
        reviewed_experience=notes,
        image_views=names,
        image_sha256=hashes,
        observation_boundary='public task, current RGB, camera-derived estimates, robot state only',
    )
    schema = dict(type='object', additionalProperties=False,
                  properties={name: dict(type='string', enum=list(question['criteria']))
                              for name, question in questions.items()},
                  required=list(questions))
    (folder / f'decision-input-{number:04d}.json').write_text(
        json.dumps(request, ensure_ascii=False, allow_nan=False))
    return request, cameras, schema


def validate(raw, questions):
    if not isinstance(raw, dict) or set(raw) != set(questions):
        raise ValueError('Decision response does not match the exact question set')
    answer = {}
    for name, choice in raw.items():
        if not isinstance(choice, str) or choice not in questions[name]['criteria']:
            raise ValueError('Decision response selected an undeclared criterion: ' + name)
        answer[name] = dict(type='choice', choice=choice,
                            probability_source='none; model did not report calibrated probabilities')
    return answer

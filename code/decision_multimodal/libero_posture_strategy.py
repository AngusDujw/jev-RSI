"""Planner-defined posture preparation; observed relations never choose signs."""
from copy import deepcopy
import json
import math


def _vector(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 3
            or not all(type(x) in (float, int) and math.isfinite(x) for x in value)):
        return None
    return value


def observed_relations(state):
    source = state.get('observed_bottle_shape') or {}
    wood = state.get('observed_wood_shape') or {}
    endpoints = source.get('fitted_visible_segment_world_mm')
    if (not isinstance(endpoints, list) or len(endpoints) != 2
            or any(_vector(v) is None for v in endpoints)):
        endpoints = None
    planes = []
    for plane in wood.get('observed_wood_planes', []):
        normal = _vector(plane.get('surface_normal_world_unit'))
        centre = _vector(plane.get('visible_centroid_world_mm'))
        if normal is None or centre is None:
            continue
        length = math.sqrt(sum(x*x for x in normal))
        if not length:
            continue
        normal = [x/length for x in normal]
        planes.append(dict(label=plane['label'], surface_normal_world_unit=normal,
            visible_centre_world_mm=centre, fit_rms_mm=plane.get('plane_fit_rms_mm'),
            current_inliers=plane.get('current_inliers'),
            observed_endpoint_signed_plane_distances_mm=[
                round(sum(normal[i]*(point[i]-centre[i]) for i in range(3)), 1)
                for point in endpoints] if endpoints else None))
    return dict(observed_segment_endpoints_world_mm=endpoints,
        all_observed_wood_plane_relations=planes,
        meaning='Unranked CURRENT partial RGB-D fits only. E0/E1 are fitted visible-segment endpoints, not complete physical bottle ends or contact points. Signed distances follow each observed normal. No target plane, desired angle, orientation error or motor sign is computed. Identify the actual upper receiver from CURRENT RGB.')


def revise_direction(sent, strategy):
    if (sent['state'].get('request_purpose') != 'multimodal_receiving_direction'
            or not strategy.get('receiving_reference_question')):
        return sent
    revised = deepcopy(sent)
    revised['state']['stage'] = dict(name='Identify the receiving support direction',
                                    goal=strategy['posture_preparation_goal'])
    revised['state']['meaning'] = (
        'Unranked CURRENT visible wood directions, not motor candidates. '
        'Select the actual upper-rack slat-length support direction from current images. '
        'A longer fitted span is not necessarily the intended physical direction.')
    revised['questions']['rack_direction']['instructions'] = strategy['receiving_reference_question']
    return revised


def receiving_detail_parts(api, sent):
    """Enlarge all CURRENT observed wood spans in two views; never rank them."""
    import base64
    import hashlib
    import io
    import numpy as np
    from PIL import Image
    from libero_visible_shape import overlay_observed_wood_lines
    shape = dict(observed_wood_planes=[])
    for label, row in sent['state']['observed_wood_directions'].items():
        # Each A/B row is an actual unranked physical span from this request.
        # Recreate one two-axis plane only when both rows exist.
        if not label.endswith('A'):
            continue
        other = sent['state']['observed_wood_directions'].get(label[:-1]+'B')
        if other is None:
            continue
        shape['observed_wood_planes'].append(dict(label=label[:-1],
            visible_centroid_world_mm=row['observed_centre_world_mm'],
            in_plane_axes_world_unit=[row['unit_world_line'], other['unit_world_line']],
            visible_in_plane_spans_mm=[row['visible_span_mm'], other['visible_span_mm']]))
    parts = []
    for camera in ('agentview', 'sideview'):
        calibration = getattr(api, 'current_camera_calibration', {}).get(camera)
        raw = getattr(api, 'raw_camera_images', {}).get(camera)
        if calibration is None or raw is None:
            continue
        if calibration['native_tick'] != api.tick:
            raise ValueError('Receiving detail requires same-observation calibration')
        image = Image.open(io.BytesIO(raw)).convert('RGB')
        projected = overlay_observed_wood_lines(image, shape,
            np.asarray(calibration['intrinsics']), np.asarray(calibration['camera_to_world']))
        points = [point for segment in projected.values() for point in segment]
        if not points or not all(math.isfinite(x) for point in points for x in point):
            continue
        bounds = (max(0, int(min(p[0] for p in points))-20),
                  max(0, int(min(p[1] for p in points))-20),
                  min(image.width, int(max(p[0] for p in points))+21),
                  min(image.height, int(max(p[1] for p in points))+21))
        if bounds[2]-bounds[0] < 8 or bounds[3]-bounds[1] < 8:
            continue
        crop = image.crop(bounds)
        scale = 640 / max(crop.size)
        crop = crop.resize(tuple(max(1, round(v*scale)) for v in crop.size), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        crop.save(output, format='PNG')
        if hasattr(api, 'log'):
            api.log(dict(kind='receiving_detail_view', native_tick=api.tick,
                camera=camera, model_input=False, calibration=calibration,
                source_rgb_sha256=hashlib.sha256(raw).hexdigest(),
                crop_bounds_xyxy=bounds, projected_observed_spans=projected))
        parts.extend([dict(type='input_text', text=(
            f'CURRENT {camera} wood-region zoom, observation {api.tick}. '
            'ALL current fitted wood spans have the SAME labels as the physical-reference catalog. '
            'Use the actual visible slats to distinguish their longitudinal direction from panel width. '
            'These are projected observed segments, not selected target axes or action arrows. '
            'A projection does not establish visibility, contact, or support.')),
            dict(type='input_image', image_url='data:image/png;base64,'+base64.b64encode(output.getvalue()).decode())])
    return parts


def revise_rotation(sent, strategy):
    if sent['state'].get('request_purpose') != 'multimodal_rotation_axes':
        return sent
    if not sent['state'].get('free_placement_posture'):
        raise ValueError('Posture strategy requires the bottle free-posture input path')
    revised = deepcopy(sent)
    # The orientation subquery has its own planner goal. Keeping the parent
    # height/translation goal here gives the actor two different stage scopes.
    revised['state']['stage'] = dict(name='Prepare held-bottle posture',
                                    goal=strategy['posture_preparation_goal'])
    effects = {'rx': ('X', 'Positive rotates +Y toward +Z and +Z toward -Y.'),
               'ry': ('Y', 'Positive rotates +Z toward +X and +X toward -Z.'),
               'rz': ('Z', 'Positive rotates +X toward +Y and +Y toward -X.')}
    if set(revised['questions']) != set(effects):
        raise ValueError('Unexpected rotation questions; preserve the original axis schema')
    for name, (axis, effect) in effects.items():
        question = revised['questions'][name]
        old = question['instructions']
        marker = ' Current observed body line v='
        suffix = old[old.index(marker):] if marker in old else ''
        binding = revised['state'].get('actor_selected_observed_span') or {}
        template = (strategy['axis_question_template'].replace('{axis}', axis)
                    .replace('{reference_label}', binding.get('label', 'unknown'))
                    .replace('{reference_direction_world}', json.dumps(binding.get('observed_world_unit_line'))))
        question['instructions'] = (template
                                    + ' ' + effect + ' Negative reverses.' + suffix)
        question['criteria'] = dict(strategy['choice_descriptions'])
    revised['questions']['posture_readiness'] = dict(type='choice',
        instructions=strategy['current_phase_readiness_question'],
        criteria=dict(strategy['readiness_choices']))
    return revised


def revise_rotation_payload(payload, sent, strategy):
    if (sent['state'].get('request_purpose') == 'multimodal_receiving_direction'
            and strategy.get('receiving_reference_question')):
        result = deepcopy(payload)
        result['input'][0]['content'][0]['text'] = (
            'Identify the CURRENT upper-rack physical support direction. '
            'All labelled spans are observed features, not proposed motions. '
            + strategy['posture_preparation_goal'])
        return result
    if sent['state'].get('request_purpose') != 'multimodal_rotation_axes':
        return payload
    result = deepcopy(payload)
    content = result['input'][0]['content']
    if content[0]['type'] != 'input_text' or content[1]['type'] != 'input_text':
        raise ValueError('Rotation header/state contract changed')
    import json
    if json.loads(content[1]['text']).get('stage', {}).get('goal') != strategy['posture_preparation_goal']:
        raise ValueError('Rotation state must carry the planner posture goal, not its parent phase goal')
    content[0]['text'] = strategy['posture_preparation_goal'] + ' ' + ' '.join(strategy['common_instructions'])
    content.insert(2, dict(type='input_text', text=json.dumps(
        observed_relations(sent['state']), separators=(',', ':'))))
    return result


def separate_readiness(reply, tick):
    """Keep the original persisted response; expose only R axes to its caller."""
    result = deepcopy(reply)
    ready = result['answers'].pop('posture_readiness')
    if ready.get('choice') not in ('ready', 'not_ready', 'unclear'):
        raise ValueError('Invalid actor posture-readiness answer')
    return result, dict(native_tick=tick, answer=ready)


def revise_phase(sent, readiness, tick, strategy):
    state = sent['state']
    if (state.get('request_purpose') != 'formal_stage_classification'
            or state.get('stage', {}).get('stage_key') not in (
                'align_source_above_receiver', 'lower_to_place')):
        return sent
    if not readiness or readiness['native_tick'] != tick:
        raise ValueError('Phase requires this same observation actor posture judgment')
    revised = deepcopy(sent)
    value = readiness['answer']['choice']
    if (strategy.get('readiness_scope', 'all_carry') == 'lower_to_place_only'
            and state['stage']['stage_key'] == 'align_source_above_receiver'):
        addition = (
            f'CURRENT phase: {state["stage"].get("name", "clearance or transport")}. '
            f'Your SAME-observation posture_readiness answer is {value}. '
            'In this phase that orientation judgment is informative only, not an additional exit requirement. '
            'Apply the original restart, positioning and actor-rotation conditions printed below unchanged. '
            'A not_ready or unclear orientation answer alone does not keep this phase active. '
            'Later lowering/seating retains its additional orientation-readiness requirement. ')
        revised['state']['actor_posture_readiness'] = dict(choice=value,
            meaning='Same-observation orientation judgment; informative, not an extra exit condition in this phase.')
        revised['state']['formal_stage_input'] = addition + state.get('formal_stage_input', '')
        revised['questions']['transition']['instructions'] = addition + revised['questions']['transition']['instructions']
        return revised
    addition = (f'Current method posture preparation: {strategy["posture_preparation_goal"]} '
        f'Your SAME-observation posture_readiness answer is {value}. '
        'First apply any restart condition in the original rule. Otherwise continue when posture_readiness is not_ready or unclear. '
        'Only when posture_readiness is ready apply the original phase exit rule. '
        'This readiness concerns orientation only, not support contact or a release command. ')
    revised['state']['actor_posture_readiness'] = dict(choice=value,
        meaning='Your same-observation orientation judgment; not current contact or a release command.')
    revised['state']['formal_stage_input'] = addition + state.get('formal_stage_input', '')
    question = revised['questions']['transition']
    question['instructions'] = addition + question['instructions']
    if 'advance' in question['criteria']:
        question['criteria']['advance'] = 'The actor posture judgment is ready and the original current phase exit rule permits advance.'
    question['criteria']['continue'] = 'Posture is not_ready or unclear, or the original current phase rule requires continuing.'
    return revised

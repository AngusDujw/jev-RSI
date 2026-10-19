"""Numeric Decisions primitives for current camera-derived correspondences."""
import json
import math


NUMERIC_INPUT = ('Answer each independent question from its printed position error. '
    'Error means CURRENT minus DESIRED on that world axis. '
    'Positive motion increases the current coordinate; negative motion decreases it. '
    'Select the direction that brings the error inside the stated tolerance.')


def visible_height_observation(state):
    """Partial RGB-D height statistics, never a collision/clearance flag."""
    mode=state['stage'].get('control_contract',{}).get('height_reference')
    if mode not in ('visible_extents','visible_source_lower_to_selected_receiver'):
        return None
    source=state.get('source_component') or {};receiver=state.get('receiver_component') or {}
    source_shape=source.get('visible_shape') or {};receiver_shape=receiver.get('visible_shape') or {}
    def interval(shape):
        value=shape.get('visible_world_z_quantiles_mm')
        if shape.get('status')!='observed_partial_shape' or not isinstance(value,list) or len(value)!=2:return None
        return value if all(type(v) in (int,float) and math.isfinite(v) for v in value) and value[0]<=value[1] else None
    low=interval(source_shape) if source.get('status')=='candidate' else None
    upper=interval(receiver_shape) if receiver.get('status')=='candidate' else None
    selected=state.get('actor_selected_receiver_surface',{}).get('visible_surface_world_mm')
    target=upper[1] if upper is not None else None
    if mode=='visible_source_lower_to_selected_receiver':
        target=selected[2] if isinstance(selected,(list,tuple)) and len(selected)==3 and type(selected[2]) in (int,float) and math.isfinite(selected[2]) else None
    return dict(available=low is not None and target is not None,
        receiver_height_minus_visible_source_lower_mm=round(target-low[0],1) if low is not None and target is not None else None,
        source_sample_count=source_shape.get('sample_count'),receiver_sample_count=receiver_shape.get('sample_count'),
        source_visible_height_span_mm=round(low[1]-low[0],1) if low is not None else None,
        receiver_visible_height_span_mm=round(upper[1]-upper[0],1) if upper is not None else None,
        source_observation_camera=source.get('observation_camera','agentview'),height_reference=mode,
        occlusion='Hidden extent is unknown; colour masks and visible spans do not certify a complete body or support.',
        meaning='Current RGB-D partial colour surfaces only: source5th height quantile versus receiver95th height quantile, or actor-selected receiving pixel during seating. Verify source/upper-support identity in RGB. Occlusion or colour mixing can bias these statistics; they are not true bounds, contact, a safety certificate or an orientation correction. Missing values remain null.')


def reference_difference(state):
    key=state['stage'].get('stage_key')
    if key=='lift':
        motion=state.get('source_motion_test') or {}
        return motion.get('observed_feature_change_world_mm') if motion.get('available') else None
    if key=='orient_held_body':
        return state.get('stage_entry_own_minus_current_mm')
    if key in ('align_source_above_receiver','lower_to_place'):
        if state['stage'].get('control_contract',{}).get('height_reference'):
            height=state.get('extent_height_observation') or {}
            observed=state.get('observed_receiver_minus_source_mm')
            if state['stage'].get('control_contract',{}).get('translation_mode')=='own_entry_xy_clearance':
                observed=state.get('stage_entry_own_minus_current_mm')
            return [observed[0] if observed is not None else None,observed[1] if observed is not None else None,
                    height.get('receiver_height_minus_visible_source_lower_mm') if height.get('available') else None]
        return state.get('observed_receiver_minus_source_mm')
    return state.get('observed_surface_relative_mm')


def build_numeric_request(state,protocol):
    key=state['stage'].get('stage_key')
    intervals=protocol.get('numeric_axis_intervals_mm',{}).get(key,{})
    observed=reference_difference(state)
    if observed is None or not intervals:return None
    errors={};questions={}
    for axis,bounds in intervals.items():
        if axis not in ('x','y','z') or not isinstance(bounds,list) or len(bounds)!=2:
            raise ValueError('Numeric interval must name an XYZ axis and two bounds')
        lo,hi=bounds
        if not all(type(v) in (int,float) and math.isfinite(v) for v in bounds) or lo>=hi:
            raise ValueError('Numeric interval bounds must be finite and ordered')
        value=observed['xyz'.index(axis)]
        if axis in ('x','y') and state['stage'].get('control_contract',{}).get('height_reference')=='visible_extents' and state['stage'].get('control_contract',{}).get('translation_mode')!='own_entry_xy_clearance':
            height=state.get('extent_height_observation') or {};gap=height.get('receiver_height_minus_visible_source_lower_mm')
            zband=intervals.get('z')
            if not height.get('available') or gap is None or (zband and gap>zband[1]):continue
        if type(value) not in (int,float) or not math.isfinite(value):continue
        # Lift observes controlled feature displacement directly. Other stages
        # observe reference-minus-controlled. Neither branch chooses a sign.
        error=round(value-(lo+hi)/2 if key=='lift' else (lo+hi)/2-value,6);tolerance=(hi-lo)/2;errors[axis]=error
        questions[axis]=dict(type='choice',
            instructions=f'On world {axis.upper()}, position error (CURRENT minus DESIRED) is {error:g} mm and tolerance is {tolerance:g} mm. Which direction should the current hand position move?',
            criteria={'positive':f'Error below -{tolerance:g} mm: positive {axis.upper()} direction.',
                      'negative':f'Error above +{tolerance:g} mm: negative {axis.upper()} direction.',
                      'hold':f'Error within -{tolerance:g} to +{tolerance:g} mm: hold {axis.upper()}.'})
    if not questions:return None
    return dict(model='gpt-6-luna',
        state=dict(stage={k:v for k,v in state['stage'].items() if k in ('name','stage_key')},
            request_purpose='text_only_numeric_axis_classification',
            current_minus_desired_error_mm=errors,
            numeric_input=NUMERIC_INPUT),
        questions=questions)


def numeric_payload(original):
    from legacy_decisions import convert_request
    payload=convert_request(original)
    payload['input']=[dict(role='user',content=[dict(type='input_text',text=original['state']['numeric_input'])])]
    return payload

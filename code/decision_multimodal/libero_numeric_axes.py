"""Numeric Decisions primitives for current camera-derived correspondences."""
import json
import math


NUMERIC_INPUT = ('Answer each independent question from its printed position error. '
    'Error means CURRENT minus DESIRED on that world axis. '
    'Positive motion increases the current coordinate; negative motion decreases it. '
    'Select the direction that brings the error inside the stated tolerance.')


def reference_difference(state):
    key=state['stage'].get('stage_key')
    if key=='orient_held_body':
        return state.get('stage_entry_own_minus_current_mm')
    if key in ('align_source_above_receiver','lower_to_place'):
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
        if type(value) not in (int,float) or not math.isfinite(value):continue
        # Reference-minus-controlled is converted to CURRENT-minus-DESIRED.
        # This normalizes a measurement and interval; it never selects a sign.
        error=round((lo+hi)/2-value,6);tolerance=(hi-lo)/2;errors[axis]=error
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

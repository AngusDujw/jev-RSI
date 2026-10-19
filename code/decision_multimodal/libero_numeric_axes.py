"""Small text-only Decisions questions for already selected sensor references.

No directions are chosen here: this module describes observed differences and
task-defined intervals, and the authorized Decisions API selects every sign.
"""
import math


def reference_difference(state):
    key=state['stage'].get('stage_key')
    if key in ('align_source_above_receiver','lower_to_place'):
        return state.get('observed_receiver_minus_source_mm')
    return state.get('observed_surface_relative_mm')


def build_numeric_request(state,protocol):
    key=state['stage'].get('stage_key')
    intervals=protocol.get('numeric_axis_intervals_mm',{}).get(key,{})
    observed=reference_difference(state)
    if observed is None or not intervals:return None
    differences={};questions={}
    for axis,bounds in intervals.items():
        if axis not in ('x','y','z') or not isinstance(bounds,list) or len(bounds)!=2:
            raise ValueError('Numeric interval must name an XYZ axis and two bounds')
        lo,hi=bounds
        if not all(type(v) in (int,float) and math.isfinite(v) for v in bounds) or lo>hi:
            raise ValueError('Numeric interval bounds must be finite and ordered')
        value=observed['xyz'.index(axis)]
        if type(value) not in (int,float) or not math.isfinite(value):continue
        differences[axis]=value
        questions[axis]=dict(type='choice',
            instructions=f'Observed feature minus controlled coordinate on world {axis.upper()} is {value} mm. Which hand direction brings it into [{lo},{hi}] mm?',
            criteria={'negative':f'Value below {lo}mm: decrease the controlled {axis.upper()} coordinate.',
                      'positive':f'Value above {hi}mm: increase the controlled {axis.upper()} coordinate.',
                      'hold':f'Value within [{lo},{hi}]mm: retain the controlled {axis.upper()} coordinate.'})
    if not questions:return None
    return dict(model='gpt-6-luna',
        state=dict(stage={k:v for k,v in state['stage'].items() if k in ('name','stage_key')},
            request_purpose='text_only_numeric_axis_classification',
            observed_feature_minus_control_mm=differences,
            permitted_intervals_mm={a:intervals[a] for a in questions},
            meaning='The observed differences use the SAME world axes. Positive hand/source motion increases the controlled coordinate and DECREASES feature-minus-control. Negative motion decreases the controlled coordinate and INCREASES the difference. These are current camera-derived selected-feature measurements, not contact evidence or object orientation.'),
        questions=questions)

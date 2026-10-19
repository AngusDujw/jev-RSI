"""Decisions evaluates unevaluated expressions over actor-selected observations.

External code never computes the products, alignment score, angular residual
or motor sign. Visual Decisions selects the physical reference beforehand.
"""
import math
from legacy_decisions import convert_request
from libero_rotation_decision import selected_span_binding


LINE_INPUT = ('Compute each printed expression yourself and classify its result '
    'using the threshold stated in that question. No result or preferred answer is supplied.')


def observed_lines(state):
    if state['stage'].get('stage_key')!='orient_held_body':return None
    binding=selected_span_binding(state)
    v=((state.get('source_component') or {}).get('visible_shape') or {}).get('visible_long_axis_world_unit')
    if binding is None or v is None:return None
    b=binding['observed_world_unit_line']
    if len(v)!=3 or len(b)!=3 or not all(type(x) in (int,float) and math.isfinite(x) for x in [*v,*b]):return None
    return v,b,binding


def build_line_rotation_request(state):
    lines=observed_lines(state)
    if lines is None:return None
    v,b,binding=lines;questions={}
    for name,(i,j) in {'rx':(1,2),'ry':(2,0),'rz':(0,1)}.items():
        questions[name]=dict(type='choice',instructions=
            f'Compute S=({v[i]} * {b[j]}) - ({v[j]} * {b[i]}). '
            'Select positive if S>0.04, negative if S<-0.04, otherwise hold.',
            criteria={'positive':'Your computed S is greater than +0.04.',
                      'negative':'Your computed S is below -0.04.',
                      'hold':'Your computed S lies within -0.04 to +0.04.'})
    return dict(model='gpt-6-luna',state=dict(stage=state['stage'],
        request_purpose='text_only_observed_line_rotation',line_input=LINE_INPUT,
        observed_bottle_line=v,actor_selected_observed_span=binding,
        meaning='Coefficients are CURRENT observed lines. The actor selected the wood span visually. Expressions are generic world-rotation effects; no product, difference, angular error or sign is evaluated externally. Displayed line representatives define a consistent branch; no twist about the bottle is requested.'),questions=questions)


def build_line_stage_request(state,answers):
    lines=observed_lines(state)
    if lines is None:return None
    v,b,binding=lines
    expression=' + '.join(f'({v[i]} * {b[i]})' for i in range(3))
    recovery=answers.get('transition',{}).get('choice')=='restart'
    return dict(model='gpt-6-luna',state=dict(stage=state['stage'],
        request_purpose='text_only_observed_line_transition',line_input=
            'Compute the printed line-alignment expression yourself and apply only the stated transition rule. This is a coarse posture check, not support, contact, holding or native task success.',
        observed_bottle_line=v,actor_selected_observed_span=binding),questions=dict(transition=dict(type='choice',instructions=
            f'Visual recovery requested={recovery}. If true, restart. Otherwise compute C=abs({expression}). '
            'If C>=0.97 advance to transport; otherwise continue posture adjustment. Both inputs are measured unit-line representatives; parallel or opposite lines describe the same lengthwise relationship. No computed score is supplied.',
            criteria={'continue':'No visual recovery, and your computed C is below 0.97.',
                      'advance':'No visual recovery, and your computed C is at least 0.97.',
                      'restart':'Visual recovery was explicitly requested.'})))


def line_payload(original):
    payload=convert_request(original)
    payload['input']=[dict(role='user',content=[dict(type='input_text',text=original['state']['line_input'])])]
    return payload

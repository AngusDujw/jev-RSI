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


def build_line_stage_request(state,answers,task_exit=False):
    lines=observed_lines(state)
    if task_exit and state['stage'].get('stage_key')=='orient_held_body':
        for axis in ('rx','ry','rz'):
            if answers.get(axis,{}).get('choice') not in ('positive','negative','hold'):
                raise ValueError('Posture phase requires complete original categorical rotation answers')
        recovery=answers.get('transition',{}).get('choice')=='restart'
        evidence=answers.get('posture_evidence',{}).get('choice','unclear')
        facts='; '.join(a+' decision='+str(answers.get(a,{}).get('choice','unknown')) for a in ('rx','ry','rz'))
        return dict(model='gpt-6-luna',state=dict(stage=state['stage'],
            request_purpose='text_only_observed_line_transition',line_input=
                'Judge the free-space posture exit from your actual visual evidence and rotation choices. The phase-entry hand point is a secondary preference; transport starts from the actual current position.'),
            questions=dict(transition=dict(type='choice',instructions=
                f'Visual recovery requested={recovery}; current observed source/reference lines available={lines is not None}; your visual posture evidence={evidence}; {facts}. '
                'Restart if visual recovery is requested. Otherwise continue if the current source/reference lines are unavailable, visual evidence is not supported, or ANY rotation choice is positive, negative or unknown. '
                'Advance to transport ONLY when the current lines are available, visual evidence is supported, and ALL THREE rotation choices are hold. XYZ choices need not be hold; exact return to an arbitrary entry hand point is not the posture task. No pending correction is executed by advance.',
                criteria={'continue':'A rotation, observation or clearance requirement remains unmet.',
                    'advance':'All three rotation choices hold, current reference available, and visual evidence supported.',
                    'restart':'Visual recovery was explicitly requested.'})))
    if lines is None:return None
    v,b,binding=lines
    recovery=answers.get('transition',{}).get('choice')=='restart'
    facts='; '.join(a+' decision='+str(answers.get(a,{}).get('choice','unknown'))
        for a in ('x','y','z','rx','ry','rz'))
    return dict(model='gpt-6-luna',state=dict(stage=state['stage'],
        request_purpose='text_only_observed_line_transition',line_input=
            'Judge the transition from your actual same-observation direction choices and the printed rule. No physical action executes with advance or restart. This is not support, holding or task success.',
        observed_bottle_line=v,actor_selected_observed_span=binding),questions=dict(transition=dict(type='choice',instructions=
            f'Visual recovery requested={recovery}. Current choices: {facts}. '
            'If visual recovery is requested, restart. Otherwise continue if ANY listed choice is positive, negative or unknown. Advance to transport ONLY if ALL SIX listed choices are hold. Do not skip a correction that has not executed.',
            criteria={'continue':'At least one listed choice is positive, negative or unknown; no visual recovery.',
                      'advance':'All six listed choices are hold; no visual recovery.',
                      'restart':'Visual recovery was explicitly requested.'})))


def line_payload(original):
    payload=convert_request(original)
    payload['input']=[dict(role='user',content=[dict(type='input_text',text=original['state']['line_input'])])]
    return payload

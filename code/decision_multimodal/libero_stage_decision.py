"""Scoped stage decisions from prior model answers and own execution facts."""
from legacy_decisions import convert_request


STAGE_INPUT = ('Judge only the phase transition from the facts and rule printed '
    'in the question. Advance and restart execute no physical action. '
    'A phase transition is not a task-success assertion.')


def build_stage_request(state,answers,protocol):
    key=state['stage'].get('stage_key')
    visual_rule=protocol.get('visual_stage_rules',{}).get(key)
    if visual_rule is not None:
        facts='Measured own motion in this phase: '+str(state.get('stage_own_motion',{}))+'. Last executed gripper command: '+str(state.get('own_tool_geometry',{}).get('last_gripper_command','unknown'))+'. '
        if key=='orient_held_body':
            facts+='Your SAME-observation motion choices: '+str({k:v['choice'] for k,v in answers.items() if k in ('x','y','z','rx','ry','rz')})+'. Your selected receiving direction: '+str(state.get('actor_selected_rack_direction','unknown'))+'. '
        return dict(model='gpt-6-luna',state=dict(stage=state['stage'],request_purpose='visual_stage_classification',formal_stage_input='Judge the one phase-transition question from CURRENT images. Archived images are goal references, never current observations.'),questions=dict(transition=dict(type='choice',instructions=facts+visual_rule,criteria={'continue':'Continue this phase; its visible exit is not met.','advance':'Enter the next phase; no robot action executes with this answer.','restart':'The visible attempt failed or needs a new grasp; return to approach.'})))
    rule=protocol.get('stage_decision_rules',{}).get(key)
    if rule is None:return None
    choices={k:v['choice'] for k,v in answers.items()}
    own=state.get('own_tool_geometry',{})
    steps=state.get('stage_own_motion',{}).get('physical_steps','unknown')
    source_known='actor_selected_surface' in state
    if key=='align_above_source':
        relative=state.get('observed_surface_relative_mm')
        clearance=round(-relative[2],1) if relative is not None else 'unknown'
        facts=f"X decision={choices.get('x')}; Y decision={choices.get('y')}; source reference known={source_known}; hand clearance above source={clearance} mm."
    elif key=='descend_to_source':
        facts='; '.join(a+' decision='+str(choices.get(a)) for a in ('x','y','z','rx','ry','rz'))
        facts+=f"; source reference known={source_known}; visual recovery requested={choices.get('transition')=='restart'}."
        if not source_known:facts+=' Visual transition recommendation='+str(choices.get('transition'))+'.'
    elif key in ('close','release'):
        facts=f"Physical steps actually executed in this phase={steps}; last executed gripper command={own.get('last_gripper_command','unknown')}; visual recovery requested={choices.get('transition')=='restart'}."
    else:return None
    return dict(model='gpt-6-luna',
        state=dict(stage=state['stage'],request_purpose='formal_stage_classification',formal_stage_input=STAGE_INPUT),
        questions=dict(transition=dict(type='choice',instructions=facts+' '+rule,
            criteria={'continue':'The stated exit is not met; continue this phase.',
                      'advance':'The stated exit is met; enter the next phase without physical motion.',
                      'restart':'The phase premise is invalid and recovery is requested; return to coarse approach without physical motion.'})))


def stage_payload(original,current=(),goal_reference=()):
    payload=convert_request(original)
    payload['input']=[dict(role='user',content=[dict(type='input_text',text=original['state']['formal_stage_input'])])]
    if original['state'].get('request_purpose')=='visual_stage_classification':
        content=payload['input'][0]['content']
        for part in goal_reference:
            if part['type']=='input_image':
                content.extend([dict(type='input_text',text='ARCHIVED goal appearance, BEFORE left and AFTER right; never a current observation.'),part])
        caption='';number=0
        for part in current:
            if part['type']=='input_text':caption=part['text']
            elif part['type']=='input_image' and 'detail' not in caption.lower():
                number+=1
                content.extend([dict(type='input_text',text=f'CURRENT view {number}, same synchronized observation.'),part])
    return payload

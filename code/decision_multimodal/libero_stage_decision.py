"""Scoped stage decisions from prior model answers and own execution facts."""
import json
from legacy_decisions import convert_request


STAGE_INPUT = ('Judge only the phase transition from the facts and rule printed '
    'in the question. Advance and restart execute no physical action. '
    'A phase transition is not a task-success assertion.')


def build_stage_request(state,answers,protocol):
    key=state['stage'].get('stage_key')
    motion=state.get('source_motion_test')
    if key=='lift' and motion and motion.get('available'):
        own=state.get('own_tool_geometry',{})
        recovery=answers.get('transition',{}).get('choice')=='restart'
        return dict(model='gpt-6-luna',state=dict(stage=state['stage'],
            request_purpose='formal_stage_classification',
            formal_stage_input='Classify one short source-motion test from current camera-derived measurements. The source feature was selected by the actor from RGB. This is not a holding, contact or task-success certificate.\n'+json.dumps(motion,separators=(',',':'))),
            questions=dict(transition=dict(type='choice',instructions=
                f"Actual physical steps in this phase={state.get('stage_own_motion',{}).get('physical_steps')}; last executed gripper command={own.get('last_gripper_command')}; visual recovery requested={recovery}. "
                'First restart if visual recovery was requested. Otherwise advance if the last gripper command is close, the observed feature has risen at least20mm, and EACH feature-minus-hand motion component is within -10 to +10mm inclusive. '
                'If not passed, restart when the hand has risen at least80mm. Also restart when hand rise is at least30mm AND either feature rise is at most5mm or at least one motion-error component has magnitude greater than20mm. Otherwise continue this brief test. '
                'Use the printed measurements; do not require rack placement or exact point-to-point alignment.',
                criteria={'advance':'The measured short source-motion test passes; enter combined reorientation and approach.',
                    'restart':'The stated recovery or failed-test condition is met; reassess the grasp.',
                    'continue':'Neither the pass nor failed-test condition is met; continue the short test.'})))
    visual_rule=protocol.get('visual_stage_rules',{}).get(key)
    if visual_rule is not None:
        facts='Measured own motion in this phase: '+str(state.get('stage_own_motion',{}))+'. Last executed gripper command: '+str(state.get('own_tool_geometry',{}).get('last_gripper_command','unknown'))+'. '
        if state.get('free_placement_posture'):
            facts+='CURRENT uncertain positioning evidence: '+json.dumps(dict(
                receiver_minus_selected_source_world_mm=state.get('observed_receiver_minus_source_mm'),
                source_feature=state.get('actor_visual_assessment',{}).get('reference'),
                receiving_feature=state.get('actor_visual_assessment',{}).get('receiver'),
                same_observation_direction_choices={k:v['choice'] for k,v in answers.items() if k in ('x','y','z','rx','ry','rz')}),separators=(',',':'))+'. These are camera-derived actor-selected skin features, not hidden centres, exact support or contact. Large support-relative separation must not be mistaken for placement merely because images overlap. '
        if key=='orient_held_body':
            facts+='Your SAME-observation motion choices: '+str({k:v['choice'] for k,v in answers.items() if k in ('x','y','z','rx','ry','rz')})+'. Your selected receiving direction: '+str(state.get('actor_selected_rack_direction','unknown'))+'. '
        return dict(model='gpt-6-luna',state=dict(stage=state['stage'],next_phase=state.get('next_phase'),request_purpose='visual_stage_classification',formal_stage_input='Judge the CURRENT phase exit, not completion of later phases. Advance enters NEXT PHASE without physical motion. Use CURRENT images and explicitly labelled PHASE ENTRY/PREVIOUS observations when supplied. ARCHIVED examples are historical, not current evidence.'),questions=dict(transition=dict(type='choice',instructions=facts+visual_rule,criteria={'continue':'Continue this phase; its own exit is not met.','advance':'This phase is ready to hand off to NEXT PHASE; later actions need not have happened yet.','restart':'The visible attempt failed or needs a new grasp; return to approach.'})))
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
    elif key in ('align_source_above_receiver','lower_to_place'):
        facts='; '.join(a+' decision='+str(choices.get(a)) for a in ('x','y','z','rx','ry','rz'))
        facts+=f"; source reference known={source_known}; receiver reference known={'actor_selected_receiver_surface' in state}; visual recovery requested={choices.get('transition')=='restart'}."
        if not source_known or 'actor_selected_receiver_surface' not in state:
            facts+=' Visual transition recommendation='+str(choices.get('transition'))+'.'
    else:return None
    return dict(model='gpt-6-luna',
        state=dict(stage=state['stage'],request_purpose='formal_stage_classification',formal_stage_input=STAGE_INPUT),
        questions=dict(transition=dict(type='choice',instructions=facts+' '+rule,
            criteria={'continue':'The stated exit is not met; continue this phase.',
                      'advance':'The stated exit is met; enter the next phase without physical motion.',
                      'restart':'The phase premise is invalid and recovery is requested; return to coarse approach without physical motion.'})))


def stage_payload(original,current=(),goal_reference=(),previous=(),stage_entry=()):
    payload=convert_request(original)
    payload['input']=[dict(role='user',content=[dict(type='input_text',text=original['state']['formal_stage_input'])])]
    if original['state'].get('request_purpose')=='visual_stage_classification':
        content=payload['input'][0]['content']
        content.append(dict(type='input_text',text=json.dumps(dict(
            CURRENT_PHASE={k:v for k,v in original['state']['stage'].items() if k in ('name','stage_key','goal','exit')},
            NEXT_PHASE=original['state'].get('next_phase')),separators=(',',':'))))
        # Lift is judged against the current table/hand, not the future rack goal.
        for part in (() if original['state']['stage'].get('stage_key')=='lift' else goal_reference):
            if part['type']=='input_image':
                content.extend([dict(type='input_text',text='ARCHIVED goal appearance, BEFORE left and AFTER right; never a current observation.'),part])
        key=original['state']['stage'].get('stage_key')
        temporal=stage_entry if key=='lift' and stage_entry else previous if key in ('lift','inspect') else ()
        if temporal:
            caption=''
            for part in temporal:
                if part['type']=='input_text':caption=part['text']
                elif part['type']=='input_image' and 'detail' not in caption.lower():
                    description=' Phase-entry observation before the lift test; compare the bottle itself against CURRENT.' if key=='lift' and stage_entry else ' Historical observation before the last executed command; not current evidence.'
                    content.extend([dict(type='input_text',text=caption+description),part])
        caption='';number=0
        for part in current:
            if part['type']=='input_text':caption=part['text']
            elif part['type']=='input_image' and 'detail' not in caption.lower():
                number+=1
                content.extend([dict(type='input_text',text=caption+f' Synchronized current view {number}.'),part])
    return payload

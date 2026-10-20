"""Scoped stage decisions from prior model answers and own execution facts."""
import json
import math
from legacy_decisions import convert_request


STAGE_INPUT = ('Judge only the phase transition from the facts and rule printed '
    'in the question. Advance and restart execute no physical action. '
    'A phase transition is not a task-success assertion.')


def hand_detail_parts(raw,camera,tick,anchor):
    """Unmarked same-frame crop around a projected measured OWN reference."""
    import base64
    import io
    from PIL import Image
    if camera not in ('agentview','sideview') or anchor is None:return []
    picture=Image.open(io.BytesIO(raw)).convert('RGB')
    if len(anchor)!=2 or not all(math.isfinite(float(v)) for v in anchor):return []
    u,v=map(float,anchor)
    if not (0<=u<picture.width and 0<=v<picture.height):return []
    radius=round(min(picture.size)*.1875)
    box=(max(0,round(u)-radius),max(0,round(v)-radius),
         min(picture.width,round(u)+radius),min(picture.height,round(v)+radius))
    crop=picture.crop(box)
    # Preserve pixel aspect ratio; a clipped border is not synthesized content.
    scale=512/max(crop.size)
    crop=crop.resize(tuple(max(1,round(n*scale)) for n in crop.size),Image.Resampling.LANCZOS)
    stream=io.BytesIO();crop.save(stream,format='PNG')
    caption=(f'CURRENT hand detail from {camera}, observation {tick}, original pixel box {list(box)}. '
        'Unmarked enlargement from the SAME raw frame, centred using measured own finger midpoint and public camera projection; not a new camera or object detector. '
        'Inspect the actual fingers, neck and any visible gap. The full raw frame supplies body/support context. '
        'Cropped-out or occluded parts remain unknown; the crop location does not prove capture, release or support.')
    return [dict(type='input_text',text=caption),dict(type='input_image',detail='high',
        image_url='data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode())]


def build_retention_request(state,protocol):
    """Scoped visual recovery; no geometric lost/held flag is computed."""
    rule=protocol.get('retention_question')
    if not rule or state['stage'].get('stage_key') not in ('align_source_above_receiver','lower_to_place'):
        return None
    own=state.get('own_tool_geometry',{})
    evidence=dict(source_feature_minus_measured_grip_site_world_mm=state.get('observed_surface_relative_mm'),
        source_feature=state.get('actor_selected_surface'),
        measured_own_pad_centre_separation_mm=own.get('pad_centre_separation_mm'),
        last_executed_gripper_command=own.get('last_gripper_command'),
        meaning='The selected feature is a current RGB-D visible skin point, not an object centre or holding flag. Estimates are coarse and may change with the visible part. A held bottle can extend below the fingers; zero feature offset is not required. The grip_site is measured between the fingers. Use current RGB to judge whether the bottle and fingers are separate. Unknown remains unknown.')
    return dict(model='gpt-6-luna',state=dict(stage=state['stage'],
        request_purpose='visual_retention_check',
        formal_stage_input='Judge only whether the wine bottle is clearly lost from the fingers in the CURRENT synchronized views. The phase label is not evidence of attachment. No hidden contact or holding signal is supplied.\n'+json.dumps(evidence,separators=(',',':'))),
        questions=dict(transition=dict(type='choice',instructions=rule,
            criteria={'continue':'Attachment remains plausible or loss is not clearly established. This does not authorize opening or certify holding.',
                      'restart':'The bottle is clearly separate from the fingers and requires a new grasp.'})))


def build_scene_relation_request(state,protocol):
    rule=protocol.get('scene_relation_question')
    if not rule or state['stage'].get('stage_key') not in ('align_source_above_receiver','lower_to_place','release'):
        return None
    source_relative=state.get('observed_surface_relative_mm')
    receiver_relative=state.get('observed_receiver_minus_source_mm')
    def distance(value):
        return round(math.sqrt(sum(float(v)**2 for v in value)),1) if isinstance(value,(list,tuple)) and len(value)==3 and all(isinstance(v,(int,float)) and math.isfinite(v) for v in value) else None
    evidence=dict(source_feature_minus_measured_grip_site_world_mm=source_relative,
        selected_upper_rack_feature_minus_source_feature_world_mm=receiver_relative,
        source_feature_to_finger_midpoint_distance_mm=distance(source_relative),
        source_feature_to_upper_rack_feature_distance_mm=distance(receiver_relative),
        source_feature=state.get('actor_selected_surface'),
        receiving_feature=state.get('actor_selected_receiver_surface'),
        meaning='Coordinates and Euclidean distances are coarse current RGB-D estimates for actor-selected visible skin features, not object centres, exact support or contact. Distances are millimetres:100mm is10cm;1000mm is1m. A bottle can extend below the fingers while held. Use the actual object extent and support in RGB; near a rack feature does not alone prove support. Unknown measurements remain null.')
    return dict(model='gpt-6-luna',state=dict(stage=state['stage'],request_purpose='visual_scene_relation',
        use_raw_rgb=bool(protocol.get('scene_relation_raw_rgb')),
        use_hand_details=bool(protocol.get('scene_relation_hand_details')),
        formal_stage_input='Classify the CURRENT wine-bottle relationship using camera-identified current views and labelled previous observations. Previous images are historical. The phase label is not evidence that the bottle is still held or already placed. No hidden object pose, contact or outcome flag is supplied.\n'+json.dumps(evidence,separators=(',',':'))),
        questions=dict(scene_relation=dict(type='choice',instructions=rule['question'],criteria=rule['choices'])))


def build_position_progress_request(state,answers,protocol,numeric_errors):
    if answers.get('transition',{}).get('choice')=='restart':return None
    intervals=protocol.get('numeric_axis_intervals_mm',{}).get(state['stage'].get('stage_key'),{})
    ratios=[]
    for axis in ('x','y','z'):
        error=(numeric_errors or {}).get(axis);bounds=intervals.get(axis)
        if type(error) not in (int,float) or not math.isfinite(error) or not isinstance(bounds,list) or len(bounds)!=2 or bounds[1]<=bounds[0]:
            ratios=[];break
        ratios.append(abs(error)/((bounds[1]-bounds[0])/2))
    if not ratios:
        instructions='At least one current XYZ positioning measurement is unavailable. Do not treat missing values as zero. No visual recovery was requested. Continue this stage to get a usable current estimate, or restart only for a requested visual recovery.'
        criteria={'continue':'Remain in this stage; positioning is not yet judgeable.','restart':'Visual recovery was requested.'}
    else:
        value=round(max(ratios),6)
        rx,ry,rz=(answers.get(a,{}).get('choice','unknown') for a in ('rx','ry','rz'))
        instructions=(f'Current normalized positioning deviation={value:g}. This means the worst XYZ position error is {value:g} times its tolerance. '
            f'Actor rotation choices: RX={rx}, RY={ry}, RZ={rz}. No visual recovery was requested. '
            'Continue when deviation is greater than1 OR a rotation choice is not hold. Advance only when deviation is from0 through1 inclusive AND all rotation choices are hold.')
        criteria={'continue':'Positioning deviation is above1 or a rotation correction remains.',
                  'advance':'Positioning deviation is within0..1 and all rotation choices hold.'}
    return dict(model='gpt-6-luna',state=dict(stage=state['stage'],request_purpose='formal_stage_classification',
        formal_stage_input='Classify the stage question from its printed current positioning deviation and the actor preceding rotation choices. The deviation uses current measured-robot and camera-derived positional errors, not a task-success or contact flag.'),
        questions=dict(transition=dict(type='choice',instructions=instructions,criteria=criteria)))


def build_stage_request(state,answers,protocol,numeric_errors=None):
    key=state['stage'].get('stage_key')
    if protocol.get('position_progress_gate') and key in ('align_source_above_receiver','lower_to_place'):
        return build_position_progress_request(state,answers,protocol,numeric_errors)
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
    rule=state['stage'].get('control_contract',{}).get('stage_decision_rule') or protocol.get('stage_decision_rules',{}).get(key)
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
        anchored=state['stage'].get('control_contract',{}).get('translation_mode')=='own_entry_xy_clearance'
        if not anchored:facts+=f"; source reference known={source_known}; receiver reference known={'actor_selected_receiver_surface' in state}"
        facts+=f"; visual recovery requested={choices.get('transition')=='restart'}."
        if not anchored and (not source_known or 'actor_selected_receiver_surface' not in state):
            facts+=' Visual transition recommendation='+str(choices.get('transition'))+'.'
        if state['stage'].get('control_contract',{}).get('height_reference'):
            height=state.get('extent_height_observation') or {}
            facts+=' Current partial-height estimate available='+str(height.get('available',False))+'; receiver height minus lower-visible bottle height='+str(height.get('receiver_height_minus_visible_source_lower_mm'))+' mm; translation mode='+str(state['stage']['control_contract'].get('translation_mode'))+'. This is uncertain sensor geometry, not contact or complete clearance.'
    else:return None
    return dict(model='gpt-6-luna',
        state=dict(stage=state['stage'],request_purpose='formal_stage_classification',formal_stage_input=STAGE_INPUT),
        questions=dict(transition=dict(type='choice',instructions=facts+' '+rule,
            criteria={'continue':'The stated exit is not met; continue this phase.',
                      'advance':'The stated exit is met; enter the next phase without physical motion.',
                      'restart':'The phase premise is invalid and recovery is requested; return to coarse approach without physical motion.'})))


def stage_payload(original,current=(),goal_reference=(),previous=(),stage_entry=(),hand_details=()):
    payload=convert_request(original)
    payload['input']=[dict(role='user',content=[dict(type='input_text',text=original['state']['formal_stage_input'])])]
    if original['state'].get('request_purpose')=='visual_scene_relation':
        content=payload['input'][0]['content']
        for views in (previous,current):
            caption=''
            for part in views:
                if part['type']=='input_text':caption=part['text']
                elif part['type']=='input_image' and 'detail' not in caption.lower():
                    content.extend([dict(type='input_text',text=caption),part])
        if original['state'].get('use_hand_details'):content.extend(hand_details)
        return payload
    if original['state'].get('request_purpose')=='visual_retention_check':
        content=payload['input'][0]['content'];caption=''
        for part in current:
            if part['type']=='input_text':caption=part['text']
            elif part['type']=='input_image' and 'detail' not in caption.lower():
                content.extend([dict(type='input_text',text=caption),part])
        return payload
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

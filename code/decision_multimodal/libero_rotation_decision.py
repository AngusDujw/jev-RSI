"""Independent visual rotation choices, without a computed desired orientation."""
import json
from legacy_decisions import convert_request


ROTATION_INPUT = ('Choose the HAND rotation signs from the CURRENT views, measured own axes, '
    'observed partial surface shapes and actual motion examples. The held bottle may already '
    'be horizontal. Do not apply an upright-object example as if it were the current posture. '
    'The goal image shows a relationship to reproduce, not a current observation. '
    'No desired rotation, angular error or recommended motor direction is supplied. '
    'Use measured execution rather than assuming a commanded rotation happened. '
    'Decide each channel independently; the selected components form one world rotation vector.')


def build_rotation_request(state,explain_current_effect=False,bind_span=False):
    key=state['stage'].get('stage_key')
    if key not in ('orient_held_body','align_source_above_receiver','lower_to_place'):return None
    effects={'rx':('X','Positive rotates +Y toward +Z and +Z toward -Y.'),
             'ry':('Y','Positive rotates +Z toward +X and +X toward -Z.'),
             'rz':('Z','Positive rotates +X toward +Y and +Y toward -X.')}
    questions={}
    for name,(axis,effect) in effects.items():
        questions[name]=dict(type='choice',instructions=
            f'For rotation about fixed world {axis}, choose positive, negative or hold to fit the CURRENT bottle body lengthwise on the wooden cradle, as in the archived goal. {effect} Negative reverses this effect. Use the CURRENT body, not an assumed upright bottle. Hold when this rotation channel is not needed for the current visible fit. Ignore pure positional distance. Observed shape axes are unoriented lines: v and -v are equivalent; they are not target axes.',
            criteria={'positive':f'Positive rotation about world {axis}.',
                      'negative':f'Negative rotation about world {axis}.',
                      'hold':f'No increment about world {axis}.'})
    shape=(state.get('source_component') or {}).get('visible_shape') or {}
    current=shape.get('visible_long_axis_world_unit')
    if explain_current_effect and current is not None:
        x,y,z=current
        derivatives={'rx':[0.,-z,y],'ry':[z,0.,-x],'rz':[-y,x,0.]}
        for name,derivative in derivatives.items():
            derivative=[round(v,3) for v in derivative]
            questions[name]['instructions']+=f' CURRENT observed body line v={current}. If the bottle follows the hand rigidly, a small positive increment on this channel changes this representative line in direction dv/dtheta={derivative}; negative reverses that change. This is a local physical effect, NOT a desired axis or angle error. Use CURRENT RGB and the goal example to judge whether that effect helps; v and -v are the same line.'
    selected=state.get('actor_selected_rack_direction')
    if selected is not None:
        for question in questions.values():
            question['instructions']+=' YOUR preceding same-observation receiving-direction selection is '+str(selected['choice'])+'. Fit the body lengthwise to that physical line, checking CURRENT images. The selection is your judgment, not an externally chosen target. Unknown does not specify an axis.'
    if key=='orient_held_body':
        for question in questions.values():
            question['instructions']+=' This phase establishes posture near the lift location, before rack-directed transport. Translation questions preserve the own-hand position recorded at phase entry. Judge whether the whole visible body has room; a stable hand point alone is not clearance.'
    elif state.get('accepted_posture_available'):
        for question in questions.values():
            question['instructions']+=' The ACCEPTED posture images are your earlier accepted observation in THIS episode. Preserve that actual posture during transport/lowering rather than starting a new unrestricted rotation search. Select hold unless CURRENT evidence shows a real posture drift needing this component.'
    binding=selected_span_binding(state) if bind_span else None
    if binding is not None and current is not None:
        pairs={'rx':('X',(1,2),'Y/Z','+Y toward +Z'),
               'ry':('Y',(2,0),'Z/X','+Z toward +X'),
               'rz':('Z',(0,1),'X/Y','+X toward +Y')}
        for name,(axis,indices,pair,positive) in pairs.items():
            v=[current[i] for i in indices]
            b=[binding['observed_world_unit_line'][i] for i in indices]
            questions[name]['instructions']=(
                f'Your selected physical wood span is {binding["label"]}, highlighted in CURRENT agentview. '
                f'Current visible BOTTLE unit line={current}; selected observed WOOD unit line={binding["observed_world_unit_line"]}. '
                f'For world {axis} rotation, observed {pair} components are BOTTLE={v}, WOOD={b}. '
                f'Positive rotates {positive}; negative reverses. Rotation about {axis} leaves the {axis} component unchanged and rotates only the {pair} pair. '
                'Choose positive, negative or hold as your contribution to making the two physical lines parallel. '
                'Either sign of a line represents the same physical direction. A tiny or collapsed projection cannot justify a large correction by itself; consult the full three-dimensional lines and actual RGB. '
                'Hold if this component does not help the current lengthwise fit. Do not invent a twist objective about the bottle line. '
                'All three choices form ONE world rotation vector. Ignore position differences. No angular error or recommended component is supplied.')
            if key!='orient_held_body' and state.get('accepted_posture_available'):
                questions[name]['instructions']+=' Preserve the accepted actual current-episode posture shown in the historical acceptance images; hold unless current observations show a real posture drift.'
    return dict(model='gpt-6-luna',state=dict(
        stage={k:v for k,v in state['stage'].items() if k in ('name','goal')},
        request_purpose='multimodal_rotation_axes',
        own_tool_geometry=state.get('own_tool_geometry',{}),
        observed_bottle_shape=(state.get('source_component') or {}).get('visible_shape'),
        observed_wood_shape=(state.get('receiver_component') or {}).get('visible_shape'),
        actor_selected_rack_direction=selected,
        actor_selected_observed_span=binding,
        observed_bottle_segment_agentview=(state.get('source_component') or {}).get('projected_visible_segment_agentview') if bind_span else None,
        recent_own_execution=state.get('recent_own_execution_comparison',[])),questions=questions)


def selected_span_binding(state):
    """Copy exactly the actor-selected observation; no ranking or direction math."""
    selected=(state.get('actor_selected_rack_direction') or {}).get('choice')
    component=state.get('receiver_component') or {}
    planes=(component.get('visible_shape') or {}).get('observed_wood_planes',[])
    for plane in planes:
        for i,axis in enumerate(plane['in_plane_axes_world_unit']):
            label=plane['label']+('A','B')[i]
            if label!=selected:continue
            return dict(label=label,observed_world_unit_line=axis,
                observed_visible_centre_world_mm=plane['visible_centroid_world_mm'],
                visible_span_mm=plane['visible_in_plane_spans_mm'][i],
                projected_segment_agentview=component.get('projected_span_lines_agentview',{}).get(label),
                meaning='Exactly the CURRENT physical span selected by Decisions, not an externally selected target orientation. A fitted visible segment is not a full support certificate.')
    return None


def highlight_observed_segments(part,binding,bottle):
    """Highlight only current observed physical segments, never a target error."""
    import base64,io
    from PIL import Image,ImageDraw,ImageFont
    image=Image.open(io.BytesIO(base64.b64decode(part['image_url'].split(',',1)[1]))).convert('RGB')
    draw=ImageDraw.Draw(image)
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',14)
    for points,label,colour in ((binding.get('projected_segment_agentview'),'SELECTED '+binding['label'],'#ff8cff'),(bottle,'BOTTLE visible fit','#00ffff')):
        if not points:continue
        draw.line([tuple(p) for p in points],fill=colour,width=4)
        x,y=points[0]
        draw.text((max(0,min(image.width-150,x)),max(0,min(image.height-20,y))),label,font=font,fill=colour,stroke_width=1,stroke_fill='black')
    buf=io.BytesIO();image.save(buf,format='PNG')
    return dict(part,image_url='data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode())


def build_direction_request(state):
    """Actor selects a physical observation, never an externally ranked target."""
    planes=((state.get('receiver_component') or {}).get('visible_shape') or {}).get('observed_wood_planes',[])
    catalog={}
    for plane in planes:
        for i,axis in enumerate(plane['in_plane_axes_world_unit']):
            label=plane['label']+('A','B')[i]
            catalog[label]=dict(unit_world_line=axis,
                observed_centre_world_mm=plane['visible_centroid_world_mm'],
                visible_span_mm=plane['visible_in_plane_spans_mm'][i])
    if not catalog:return None
    return dict(model='gpt-6-luna',state=dict(stage=state['stage'],
        request_purpose='multimodal_receiving_direction',
        observed_wood_directions=catalog,
        meaning='All lines are fits to CURRENT visible wood, with matching labels in agentview. They are unoriented physical observations, not desired axes, motor candidates or contact certificates. Select the direction expressing the archived lengthwise bottle-on-rack relationship. A plane can describe an irrelevant support or leg.'),
        questions=dict(rack_direction=dict(type='choice',
            instructions='Which CURRENT labelled wood direction should the bottle body run along to reproduce the archived placement relationship? Use the actual current rack and archived image to select the physical direction. This is not a rotation sign. Choose unknown if none is a useful visible cradle direction.',
            criteria={**{label:'Use observed wood direction '+label+'.' for label in catalog},
                'unknown':'No listed direction reliably expresses the receiving relationship.'})))


def rotation_payload(original,current,examples,goal_reference):
    payload=convert_request(original)
    selecting=original['state'].get('request_purpose')=='multimodal_receiving_direction'
    header=('Select the physical receiving direction from CURRENT observed wood lines and the archived placement relationship. This question chooses a physical reference, not motor signs.' if selecting else ROTATION_INPUT)
    content=[dict(type='input_text',text=header),
        dict(type='input_text',text=json.dumps(original['state'],separators=(',',':'))),
        *([] if selecting else examples),*goal_reference]
    caption=''
    for part in current:
        if part['type']=='input_text':caption=part['text']
        elif part['type']=='input_image' and 'detail' not in caption.lower():
            binding=original['state'].get('actor_selected_observed_span')
            if binding is not None and caption.startswith('CURRENT agentview'):
                part=highlight_observed_segments(part,binding,original['state'].get('observed_bottle_segment_agentview'))
                caption+=' Thick SELECTED and BOTTLE lines highlight the actor-selected CURRENT wood span and a fit to the CURRENT visible bottle segment. These are physical observations, not an angular residual, action arrow or full object extent.'
            content.extend([dict(type='input_text',text=caption),part])
    payload['input']=[dict(role='user',content=content)]
    return payload

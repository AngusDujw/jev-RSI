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


def build_rotation_request(state):
    key=state['stage'].get('stage_key')
    if key not in ('align_source_above_receiver','lower_to_place'):return None
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
    return dict(model='gpt-6-luna',state=dict(
        stage={k:v for k,v in state['stage'].items() if k in ('name','goal')},
        request_purpose='multimodal_rotation_axes',
        own_tool_geometry=state.get('own_tool_geometry',{}),
        observed_bottle_shape=(state.get('source_component') or {}).get('visible_shape'),
        observed_wood_shape=(state.get('receiver_component') or {}).get('visible_shape'),
        recent_own_execution=state.get('recent_own_execution_comparison',[])),questions=questions)


def rotation_payload(original,current,examples,goal_reference):
    payload=convert_request(original)
    content=[dict(type='input_text',text=ROTATION_INPUT),
        dict(type='input_text',text=json.dumps(original['state'],separators=(',',':'))),
        *examples,*goal_reference]
    caption=''
    for part in current:
        if part['type']=='input_text':caption=part['text']
        elif part['type']=='input_image' and 'detail' not in caption.lower():
            content.extend([dict(type='input_text',text=caption),part])
    payload['input']=[dict(role='user',content=content)]
    return payload

"""Two-step visual selection of physical rack spans, without motor answers."""
import base64
import io
import json

from legacy_decisions import convert_request


def build_span_request(state, judgments=None):
    component=state.get('receiver_component') or {}
    segments=component.get('projected_span_lines_agentview',{})
    if not segments:return None
    catalog={label:dict(pixel_endpoints_agentview=points,
        colour='magenta' if label.endswith('A') else 'orange')
        for label,points in segments.items()}
    context=dict(stage=state['stage'],observed_segments=catalog,
        selected_receiving_surface={k:v for k,v in (state.get('actor_selected_receiver_surface') or {}).items()
            if k in ('label','pixel_uv','observation_camera')},
        request_purpose='multimodal_span_fit' if judgments is None else 'multimodal_span_choice')
    if judgments is None:
        questions={}
        for label,row in catalog.items():
            questions['fits_'+label]=dict(type='choice',instructions=
                f'Image1 is the archived bottle-and-rack relationship; Image2 is CURRENT wood. '
                f'Inspect ONLY current {row["colour"]} segment {label}, original agentview endpoints '
                f'{row["pixel_endpoints_agentview"]}. Does this segment follow the same direction '
                'through its wooden boards as the green bottle body in Image1? Compare the bottle '
                'shoulder-to-base direction with individual slat edges, rather than gripper fingers '
                'or progression across successive slats. This is a physical relation, not a motor sign.',
                criteria={'matches':'This segment follows the illustrated bottle-to-board direction.',
                    'different':'This segment follows a different direction through the boards.',
                    'unclear':'The relation cannot be judged from these views.'})
    else:
        context['your_same_observation_fit_judgments']=judgments
        questions=dict(rack_direction=dict(type='choice',instructions=
            'Your preceding visual judgments are '+json.dumps(judgments,separators=(',',':'))+'. '
            'Which CURRENT span should be the body-placement reference? Select a span YOU judged '
            'matches on the illustrated receiving shelf. Use CURRENT rack pixels and the selected '
            'receiving surface label to distinguish shelf levels. Choose unknown if unsupported. '
            'A changed label is not evidence of correctness.',criteria={
                **{label:'Your preceding judgment for '+label+' is '+str(judgments.get(label,'unclear'))+
                    '. Choose only if it matches and belongs to the receiving shelf.' for label in catalog},
                'unknown':'No listed direction reliably expresses the receiving relationship.'}))
    return dict(model='gpt-6-luna',state=context,questions=questions)


def _crop(part,box):
    from PIL import Image
    image=Image.open(io.BytesIO(base64.b64decode(part['image_url'].split(',',1)[1]))).convert('RGB')
    image=image.crop(box(image.size)).resize((512,512))
    buffer=io.BytesIO();image.save(buffer,format='PNG')
    return dict(type='input_image',detail='high',image_url='data:image/png;base64,'+
        base64.b64encode(buffer.getvalue()).decode())


def span_payload(original,current,goal):
    """Crop actual images only; never render a future pose or angle residual."""
    archive=next((x for x in goal if x['type']=='input_image'),None)
    caption='';overview=None
    for part in current:
        if part['type']=='input_text':caption=part['text']
        elif part['type']=='input_image' and caption.startswith('CURRENT agentview'):
            overview=part;break
    if archive is None or overview is None:raise ValueError('Span selection requires actual archive and current agentview')
    state=original['state'];points=[p for row in state['observed_segments'].values()
        for p in row['pixel_endpoints_agentview']]
    def box(size):
        w,h=size
        return (max(0,int(min(p[0] for p in points)-45)),
            max(0,int(min(p[1] for p in points)-45)),
            min(w,int(max(p[0] for p in points)+45)),
            min(h,int(max(p[1] for p in points)+45)))
    payload=convert_request(original)
    payload['input']=[dict(role='user',content=[
        dict(type='input_text',text='Compare physical bottle-to-board relationships. Image1 is an actual historical AFTER image from another episode. Image2 is CURRENT observed wood with unranked fitted segment labels. No future robot action or computed angular error is depicted.'),
        dict(type='input_text',text=json.dumps(state,separators=(',',':'))),
        dict(type='input_text',text='Image1: archived AFTER right half of the actual BEFORE/AFTER card. It is a relationship example, not the current scene.'),
        _crop(archive,lambda size:(size[0]//2,0,size[0],size[1])),
        dict(type='input_text',text='Image2: CURRENT agentview rack detail, crop and resize only. Segment endpoint numbers refer to the original uncropped agentview pixels. Labels mark physical observed spans, not motion recommendations.'),
        _crop(overview,box)])]
    return payload

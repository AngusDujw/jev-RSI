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
        previous=state.get('previous_actor_span_selection')
        continuity=''
        if previous is not None:
            context['your_previous_episode_reference_intent']=previous
            continuity=(' Your preceding physical-reference intention in THIS episode is '+json.dumps(previous,separators=(',',':'))+
                '. Keep a consistent physical receiving relationship unless CURRENT evidence contradicts it. Revalidate its CURRENT correspondence; plane labels can change. This history is not current geometry and does not authorize using an invisible span.')
        questions=dict(rack_direction=dict(type='choice',instructions=
            'Your preceding visual judgments are '+json.dumps(judgments,separators=(',',':'))+'. '
            'Which CURRENT span should be the body-placement reference? Select a span YOU judged '
            'matches on the illustrated receiving shelf. Use CURRENT rack pixels and the selected '
            'receiving surface label to distinguish shelf levels. Choose unknown if unsupported. '
            'A changed label is not evidence of correctness.'+continuity,criteria={
                **{label:'Your preceding judgment for '+label+' is '+str(judgments.get(label,'unclear'))+
                    '. Choose only if it matches and belongs to the receiving shelf.' for label in catalog},
                'unknown':'No listed direction reliably expresses the receiving relationship.'}))
    return dict(model='gpt-6-luna',state=context,questions=questions)


def _crop(part,box,preserve_aspect=False):
    from PIL import Image,ImageOps
    image=Image.open(io.BytesIO(base64.b64decode(part['image_url'].split(',',1)[1]))).convert('RGB')
    image=image.crop(box(image.size))
    if preserve_aspect:image=ImageOps.pad(image,(512,512),color='#10222a')
    else:image=image.resize((512,512))
    buffer=io.BytesIO();image.save(buffer,format='PNG')
    return dict(type='input_image',detail='high',image_url='data:image/png;base64,'+
        base64.b64encode(buffer.getvalue()).decode())


def observed_span_card(state,raw):
    """Show each unranked observed line on its own CURRENT raw image panel."""
    from PIL import Image,ImageDraw,ImageFont
    image=Image.open(io.BytesIO(raw)).convert('RGB')
    segments=state['observed_segments'];points=[p for r in segments.values() for p in r['pixel_endpoints_agentview']]
    left=max(0,int(min(p[0] for p in points)-45));top=max(0,int(min(p[1] for p in points)-45))
    right=min(image.width,int(max(p[0] for p in points)+45));bottom=min(image.height,int(max(p[1] for p in points)+45))
    if right<=left or bottom<=top:raise ValueError('No visible current span region')
    crop=image.crop((left,top,right,bottom));tile=384;header=28
    scale=min(tile/crop.width,tile/crop.height);width=round(crop.width*scale);height=round(crop.height*scale)
    pad_x=(tile-width)//2;pad_y=(tile-height)//2
    canvas=Image.new('RGB',(tile*2,(tile+header)*((len(segments)+1)//2)),'#10222a')
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',15)
    def project(point):return ((point[0]-left)*width/crop.width+pad_x,(point[1]-top)*height/crop.height+pad_y)
    selected=state.get('selected_receiving_surface') or {}
    for index,(label,row) in enumerate(segments.items()):
        panel=Image.new('RGB',(tile,tile),'#10222a');panel.paste(crop.resize((width,height)),(pad_x,pad_y))
        draw=ImageDraw.Draw(panel);colour='#ff8cff' if row['colour']=='magenta' else '#ffaf48'
        draw.line([project(p) for p in row['pixel_endpoints_agentview']],fill=colour,width=4)
        if 'pixel_uv' in selected and selected.get('observation_camera','agentview')=='agentview':
            x,y=project(selected['pixel_uv']);draw.ellipse((x-6,y-6,x+6,y+6),outline='#67baff',width=2)
        x=(index%2)*tile;y=(index//2)*(tile+header)
        canvas.paste(panel,(x,y+header));ImageDraw.Draw(canvas).text((x+7,y+5),label+' | CURRENT observed span only',font=font,fill='white')
    buffer=io.BytesIO();canvas.save(buffer,format='PNG')
    return dict(type='input_image',detail='high',image_url='data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode())


def span_payload(original,current,goal,raw_cameras=None):
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
    if raw_cameras:
        if 'agentview' not in raw_cameras:raise ValueError('Span details need the current raw fixed view')
        # Task-specific crop of the actual archived receiver/bottle example;
        # no CURRENT object coordinates or future orientation are generated.
        example=_crop(archive,lambda size:(size[0]//2,34,min(size[0],size[0]//2+220),min(size[1],274)),preserve_aspect=True)
        content=[dict(type='input_text',text='Compare the physical bottle-to-board relationship in Image1 with each separately displayed CURRENT observed line in Image2. Each named tile shows the SAME raw current rack, with ONLY that observed span highlighted. These are observation features, not robot action candidates, future poses or angular corrections.'),
            dict(type='input_text',text=json.dumps(state,separators=(',',':'))),
            dict(type='input_text',text='Image1: actual archived AFTER receiver-and-bottle detail from the right half of the goal card. This is historical, not the current scene.'),example,
            dict(type='input_text',text='Image2: unranked CURRENT span tiles. Use the tile name to inspect the matching physical line. The blue ring, if present, marks YOUR currently selected receiving-surface pixel, not a tool target. Original endpoint numbers still refer to the uncropped agentview. No other span or displaced label is overlaid within a tile.'),
            observed_span_card(state,raw_cameras['agentview'])]
        payload['input']=[dict(role='user',content=content)]
        return payload
    payload['input']=[dict(role='user',content=[
        dict(type='input_text',text='Compare physical bottle-to-board relationships. Image1 is an actual historical AFTER image from another episode. Image2 is CURRENT observed wood with unranked fitted segment labels. No future robot action or computed angular error is depicted.'),
        dict(type='input_text',text=json.dumps(state,separators=(',',':'))),
        dict(type='input_text',text='Image1: archived AFTER right half of the actual BEFORE/AFTER card. It is a relationship example, not the current scene.'),
        _crop(archive,lambda size:(size[0]//2,0,size[0],size[1])),
        dict(type='input_text',text='Image2: CURRENT agentview rack detail, crop and resize only. Segment endpoint numbers refer to the original uncropped agentview pixels. Labels mark physical observed spans, not motion recommendations.'),
        _crop(overview,box)])]
    return payload

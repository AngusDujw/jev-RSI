"""Current-image feature selection without unrelated motor or example context."""
import json
from legacy_decisions import convert_request


PLACEMENT_REFERENCE = 'Which labelled source dot is on a visible WIDE BOTTLE BODY region useful for placing the whole bottle into the wooden cradle? The reference purpose has changed from neck grasping to body placement. A previously selected neck S may be replaced with a suitable current BODY C dot. Keep S only if it already tracks the useful BODY-placement feature in CURRENT RGB. A current match is not proof of holding. Choose unknown or unlabelled when needed.'

REFERENCE_INPUT = ('Select physical surface features for the CURRENT named phase from CURRENT images. '
    'Labels mark observed surfaces, not recommended grasps, target poses or hidden centres. '
    'For bottle grasping identify the narrow upper neck. For placement identify the wider bottle BODY '
    'and the actual slatted wooden receiving area. A previously tracked neck point is not automatically '
    'a useful body-placement point. Use unlabelled or unknown when appropriate.')


def bind_receiver_choice(state,answers,candidates):
    """Preserve the actor receiver choice independently of source visibility."""
    state.pop('actor_selected_receiver_surface',None)
    label=answers.get('receiver',{}).get('choice','unknown')
    if isinstance(label,str) and label.startswith('B') and label in candidates:
        state['actor_selected_receiver_surface']=candidates[label]


def reference_payload(original,current,goal_reference,raw_cameras=None):
    state=original['state'];catalog=[]
    box=(state.get('source_component') or {}).get('bbox_xyxy')
    for sample in state.get('visible_surface_samples',[]):
        row={k:sample[k] for k in ('label','pixel_uv','observation_camera','visible_part_note','meaning') if k in sample}
        if sample['label'].startswith('C') and box and box[3]>box[1]:
            row['fraction_from_top_of_current_visible_source_component']=round((sample['pixel_uv'][1]-box[1])/(box[3]-box[1]),3)
        catalog.append(row)
    curated=dict(task=state['task'],stage={k:v for k,v in state['stage'].items() if k in ('name','goal')},
        current_label_catalog=catalog,
        current_source_observation_camera=(state.get('source_component') or {}).get('observation_camera','agentview'),
        current_source_component_status=(state.get('source_component') or {}).get('status'),
        current_receiver_component_status=(state.get('receiver_component') or {}).get('status'))
    payload=convert_request(original)
    header=REFERENCE_INPUT
    if state.get('free_placement_posture') and state['stage'].get('stage_key') in ('align_source_above_receiver','lower_to_place','release','inspect'):
        header='Select physical features from CURRENT images for placing the bottle on the uppermost rack support. Select a load-bearing source feature: a visible base-footprint point for upright placement, or a body-side patch for laid-down placement. Neither posture is prescribed. Reject lower-shelf/table receiving references. Sampled skin points are not hidden centres or complete support footprints.'
    content=[dict(type='input_text',text=header+' C labels and their pixel coordinates belong to current_source_observation_camera; verify that camera image, not a different view. A candidate from another current camera remains a visual hypothesis.'),dict(type='input_text',text=json.dumps(curated,separators=(',',':')))]
    if state['stage'].get('stage_key') in ('orient_held_body','align_source_above_receiver','lower_to_place','release','inspect'):
        content.extend(goal_reference)
    card=None
    if raw_cameras:
        card=candidate_detail_card(state,raw_cameras)
    if card is None:content.extend(current)
    else:
        # Replace the displaced-label detail with actual-pixel details rather
        # than asking the actor to reconcile two conflicting enlarged views.
        skip_image=False
        for part in current:
            if part['type']=='input_text' and part['text'].startswith(('CURRENT fixed-view source detail','CURRENT detail from the last')):
                skip_image=True;continue
            if skip_image:
                if part['type']!='input_image':raise ValueError('Source detail caption lacks its image')
                skip_image=False;continue
            content.append(part)
        if skip_image:raise ValueError('Incomplete source detail pair')
        content.extend([dict(type='input_text',text='CURRENT candidate details, same synchronized observation. Each ring is at that candidate ACTUAL pixel in raw RGB. Overview text may be displaced by a leader line: classify the ring location here, not the overview text position. All candidates are unranked observations, not action candidates or grasp recommendations.'),card])
    payload['input']=[dict(role='user',content=content)]
    return payload


def candidate_detail_card(state,raw_cameras):
    import base64,io
    from PIL import Image,ImageDraw,ImageFont
    samples=[s for s in state.get('visible_surface_samples',[]) if s['label'].startswith(('C','N')) or s['label']=='S']
    if not samples:return None
    columns=2;tile=256;header=30
    canvas=Image.new('RGB',(columns*tile,((len(samples)+1)//columns)*(tile+header)),'#101c25')
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',14)
    default=(state.get('source_component') or {}).get('observation_camera','agentview')
    for index,sample in enumerate(samples):
        camera=sample.get('observation_camera',default)
        if camera not in raw_cameras:raise ValueError('Candidate detail lacks its current raw camera')
        raw=Image.open(io.BytesIO(raw_cameras[camera])).convert('RGB');u,v=sample['pixel_uv']
        left,top=max(0,u-45),max(0,v-45);right,bottom=min(raw.width,u+45),min(raw.height,v+45)
        crop=raw.crop((left,top,right,bottom)).resize((tile,tile))
        draw=ImageDraw.Draw(crop);x=(u-left)*tile/(right-left);y=(v-top)*tile/(bottom-top)
        draw.ellipse((x-7,y-7,x+7,y+7),outline='#ff5959',width=3)
        cx=(index%columns)*tile;cy=(index//columns)*(tile+header)
        canvas.paste(crop,(cx,cy+header))
        ImageDraw.Draw(canvas).text((cx+5,cy+5),f'{sample["label"]} | {camera} ({u},{v})',font=font,fill='white')
    buffer=io.BytesIO();canvas.save(buffer,format='PNG')
    return dict(type='input_image',detail='high',image_url='data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode())

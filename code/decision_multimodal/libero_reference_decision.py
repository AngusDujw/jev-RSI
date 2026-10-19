"""Current-image feature selection without unrelated motor or example context."""
import json
from legacy_decisions import convert_request


PLACEMENT_REFERENCE = 'Which labelled source dot is on a visible WIDE BOTTLE BODY region useful for placing the whole bottle into the wooden cradle? The reference purpose has changed from neck grasping to body placement. A previously selected neck S may be replaced with a suitable current BODY C dot. Keep S only if it already tracks the useful BODY-placement feature in CURRENT RGB. A current match is not proof of holding. Choose unknown or unlabelled when needed.'

REFERENCE_INPUT = ('Select physical surface features for the CURRENT named phase from CURRENT images. '
    'Labels mark observed surfaces, not recommended grasps, target poses or hidden centres. '
    'For bottle grasping identify the narrow upper neck. For placement identify the wider bottle BODY '
    'and the actual slatted wooden receiving area. A previously tracked neck point is not automatically '
    'a useful body-placement point. Use unlabelled or unknown when appropriate.')


def reference_payload(original,current,goal_reference):
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
    content=[dict(type='input_text',text=REFERENCE_INPUT+' C labels and their pixel coordinates belong to current_source_observation_camera; verify that camera image, not a different view. A candidate from another current camera remains a visual hypothesis.'),dict(type='input_text',text=json.dumps(curated,separators=(',',':')))]
    if state['stage'].get('stage_key') in ('orient_held_body','align_source_above_receiver','lower_to_place','release','inspect'):
        content.extend(goal_reference)
    content.extend(current)
    payload['input']=[dict(role='user',content=content)]
    return payload

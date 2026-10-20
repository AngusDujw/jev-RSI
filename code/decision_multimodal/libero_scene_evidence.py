"""RGB scene evidence and actor-only symbolic classification; no simulator state."""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from legacy_decisions import english

EXAMPLE_HEADER='The next THREE examples are historical references only, not current observations. Use the subsequently labelled CURRENT frames for both current answers. Labels are RGB-reviewed example annotations, not simulation contact/outcome flags.'
EXAMPLE_END='END OF ARCHIVED EXAMPLES. The following PREVIOUS and CURRENT observations belong to the evaluated episode.'
QUESTIONS_PATH=Path(__file__).with_name('protocols')/'libero_scene_evidence_v53.json'
_SCHEMA_RAW=QUESTIONS_PATH.read_bytes()
SCHEMA_SHA256=hashlib.sha256(_SCHEMA_RAW).hexdigest()
_QUESTIONS=json.loads(_SCHEMA_RAW);english(_QUESTIONS)


def build_evidence_request(original):
    request=deepcopy(original)
    rows=_QUESTIONS
    if {r['name'] for r in rows}!={'capture','support'}:raise ValueError('Unexpected scene evidence questions')
    request['state']['request_purpose']='visual_scene_evidence'
    request['questions']={r['name']:dict(type='choice',instructions=r['instructions'],
        criteria={c['value']:c['description'] for c in r['choices']}) for r in rows}
    return request


def load_scene_examples(path):
    path=Path(path).resolve();root=path.parent;raw=path.read_bytes()
    bank=json.loads(raw);english(bank)
    if bank.get('task')!=1458 or len(bank.get('examples',[]))!=3:
        raise ValueError('Expected three bottle scene examples')
    if {r['scene_label'] for r in bank['examples']}!={'retained','separated_off_target','released_on_upper_support'}:
        raise ValueError('Incomplete scene example labels')
    parts=[dict(type='input_text',text=EXAMPLE_HEADER)];assets=[]
    for row in bank['examples']:
        name=row['file']
        if Path(name).name!=name:raise ValueError('Scene image must be in its bank directory')
        image=root/name
        if image.is_symlink() or image.resolve().parent!=root:raise ValueError('Scene image must be a local regular asset')
        data=image.read_bytes();digest=hashlib.sha256(data).hexdigest()
        if not data.startswith(b'\x89PNG\r\n\x1a\n') or digest!=row['sha256']:
            raise ValueError('Scene example PNG/hash mismatch')
        parts.extend([dict(type='input_text',text=row['caption']),dict(type='input_image',detail='high',
            image_url='data:image/png;base64,'+base64.b64encode(data).decode())])
        assets.append(dict(scene_label=row['scene_label'],file=name,sha256=digest))
    parts.append(dict(type='input_text',text=EXAMPLE_END))
    return parts,dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest(),
        assets=assets,label_source='Archived RGB-reviewed annotations, not native contact/outcome flags')


def build_mapping_request(stage,answers):
    capture=answers['capture']['choice'];support=answers['support']['choice']
    if capture not in ('captured','clearly_free','unknown') or support not in (
            'uppermost_shelf','lower_shelf','dark_pedestal','tabletop','no_visible_support','unknown'):
        raise ValueError('Invalid preceding visual evidence answer')
    # Supply the actor's own labels, never a geometry-derived scene class.
    instructions=(f'Your preceding CURRENT visual answers: capture={capture}; support={support}. '
        'Apply this mapping only: captured -> retained, regardless of support. '
        'Otherwise clearly_free AND uppermost_shelf -> released_on_upper_support. '
        'Otherwise clearly_free AND one of lower_shelf, dark_pedestal, tabletop -> separated_off_target. '
        'All remaining combinations -> uncertain. These labels are your own visual estimates, not hidden contact or task outcome.')
    return dict(model='gpt-6-luna',state=dict(stage=stage,request_purpose='formal_scene_relation',
        formal_stage_input='Classify your preceding capture/support choices using the printed mapping. This request performs no physical action and receives no scene-state truth.'),
        questions=dict(scene_relation=dict(type='choice',instructions=instructions,criteria={
            'retained':'Capture is captured, regardless of the support label.',
            'released_on_upper_support':'Capture is clearly_free and support is uppermost_shelf.',
            'separated_off_target':'Capture is clearly_free and support is lower_shelf, dark_pedestal or tabletop.',
            'uncertain':'Every other capture/support combination.'})))

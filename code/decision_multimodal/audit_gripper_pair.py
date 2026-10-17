"""Prepare paired inputs from archived actual requests without inference or stepping."""
import argparse
import base64
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path

from PIL import Image
import numpy as np
import libero_multimodal as stream
from libero_gripper_pair import PairedArrowsAPI, PairedRawAPI


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    rows = []
    seen = set()
    for folder in sorted(args.source.glob('task-*/multimodal/decision-api/*')):
        original = json.loads((folder/'legacy-request.json').read_text())
        task = int(folder.parents[2].name.split('-')[1])
        stage = original['state'].get('stage', original['state'].get('phase'))
        key = (task, stage)
        if key in seen:
            continue
        seen.add(key)
        dispatch = json.loads((folder/'dispatch.json').read_text())
        old_payload = json.loads((folder/'request.json').read_text())
        images = [p for p in old_payload['input'][0]['content'] if p['type']=='input_image']
        views = []
        for source, encoded in zip(dispatch['camera_views'], images):
            raw = base64.b64decode(encoded['image_url'].split(',', 1)[1])
            assert hashlib.sha256(raw).hexdigest() == source['sha256']
            picture = Image.open(io.BytesIO(raw))
            # Historical full-v1 adds only a footer. Retain every native pixel.
            assert picture.size == (768, 928)
            native = picture.crop((0, 0, 768, 768)).convert('RGB')
            buffer = io.BytesIO(); native.save(buffer, format='PNG'); raw=buffer.getvalue()
            camera = source['camera']
            views.append(dict(camera=camera, description=stream.DESCRIPTIONS[camera],
                native_observation_counter=source['native_observation_counter'], width=768,
                height=768, raw=raw, sha256=hashlib.sha256(raw).hexdigest(),
                rgb_path=str(folder/'request.json'), K=source['K'],
                camera_to_world=source['camera_to_world']))
        payloads=[]
        for name, kind in (('arrows', PairedArrowsAPI), ('raw', PairedRawAPI)):
            api=kind.__new__(kind); api.task=task; api.calls=0
            api.asset_root=args.output/f'{task}-{stage}-{name}';api.asset_root.mkdir()
            sent=api.revise(original)
            payload=api.payload_from_views(sent, views, dispatch['measured_robot'])
            api.validate_payload(payload)
            if task==1144 and stage=='approach':
                (api.asset_root/'prepared-request-NOT-SENT.json').write_text(json.dumps(payload,indent=2)+'\n')
                texts=[p['text'] for p in payload['input'][0]['content'] if p['type']=='input_text']
                (api.asset_root/'prepared-input-NOT-SENT.txt').write_text('\n\n'.join(texts)+'\n\nQuestions:\n'+json.dumps(payload['questions'],indent=2)+'\n')
                for view, part in zip(views,[p for p in payload['input'][0]['content'] if p['type']=='input_image']):
                    (api.asset_root/(view['camera']+'.png')).write_bytes(base64.b64decode(part['image_url'].split(',',1)[1]))
            payloads.append(payload)
        normalized=[]
        for payload in payloads:
            value=deepcopy(payload)
            for part in value['input'][0]['content']:
                if part['type']=='input_image':
                    part['image_url']='IMAGE-BYTES-ONLY-DIFFERENCE'
            normalized.append(value)
        assert normalized[0]==normalized[1], 'Non-image input differs'
        glyph_changes=[]
        for view, arrows, raw in zip(views,
                [p for p in payloads[0]['input'][0]['content'] if p['type']=='input_image'],
                [p for p in payloads[1]['input'][0]['content'] if p['type']=='input_image']):
            assert base64.b64decode(raw['image_url'].split(',',1)[1])==view['raw']
            a=np.asarray(Image.open(io.BytesIO(base64.b64decode(arrows['image_url'].split(',',1)[1]))))
            b=np.asarray(Image.open(io.BytesIO(view['raw'])))
            glyph_changes.append(int(np.any(a!=b,axis=2).sum()))
        rows.append(dict(task=task, stage=stage, source=str(folder),
            identical_nonimage_payload=True, raw_pixels_unchanged=True,
            changed_pixels=glyph_changes, questions=[q['name'] if 'name' in q else q.get('id') for q in payloads[0]['questions']]))
    assert len({r['task'] for r in rows})==10
    report=dict(model_calls=0, native_steps=0, experience_injection=False,
        task_count=10, stage_snapshots=len(rows), all_nonimage_inputs_identical=True, rows=rows)
    (args.output/'audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'}))


if __name__=='__main__':
    main()

"""Responses transport with explicit provenance and no credential logging."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import os
import uuid


def dump(path, value):
    path=Path(path)
    temporary=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.partial')
    data=json.dumps(value,indent=2,allow_nan=False)+'\n'
    descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'w') as stream:
        stream.write(data)
    os.replace(temporary,path)


def english(value):
    text=json.dumps(value,ensure_ascii=False,allow_nan=False)
    for _ in range(4):
        text=re.sub(r'\\u([0-9a-fA-F]{4})',lambda m:chr(int(m.group(1),16)),text)
    if re.search(r'[\u3400-\u9fff]',text):
        raise ValueError('Non-English model input detected')


def image_content(paths):
    items = []
    for label, path in paths.items():
        items += [dict(type='input_text', text=label),
                  dict(type='input_image', image_url='data:image/png;base64,' +
                       base64.b64encode(Path(path).read_bytes()).decode(), detail='high')]
    return items


def post_json(config,wire,folder,timeout=600):
    """Retry empty transport failures only, never completed model decisions."""
    records=[]
    for attempt in range(4):
        started=time.time()
        if os.environ.get('ROBO_MODEL_PROXY_SOCKET'):
            from unix_proxy import post
            result=post(config,wire,os.environ['ROBO_MODEL_PROXY_SOCKET'],timeout)
        else:
            result=subprocess.run(['curl','--silent','--show-error','--fail-with-body','--connect-timeout','25',
                    '--max-time',str(timeout),'--config','-','--data-binary','@'+str(wire)],
                    input=config,text=True,capture_output=True)
        retry=result.returncode in {5,6,7,18,28,35,52,55,56,92} and not result.stdout.strip() and attempt<3
        records.append(dict(attempt=attempt+1,returncode=result.returncode,seconds=time.time()-started,
                            transport='owned_unix_proxy' if os.environ.get('ROBO_MODEL_PROXY_SOCKET') else 'curl',
                            response_bytes=len(result.stdout.encode()),stderr=result.stderr[-500:],retry_same_request=retry))
        dump(Path(folder)/'transport_attempts.json',records)
        if result.returncode:
            (Path(folder)/f'transport-failure-{attempt+1}.txt').write_text(result.stdout)
        if not retry:
            return result
        time.sleep((1,3,7)[attempt])


def legacy_input_contract(observation):
    modes={'native' if str(c.get('calibration_source','')).startswith('Native CameraManager') else 'sdk'
           for c in observation['cameras'].values()}
    geometry={'public_tool_geometry' in observation['robot_state'][arm] for arm in ('left','right')}
    if len(modes)!=1 or len(geometry)!=1:
        raise ValueError('Mixed observation protocols cannot form a paired condition')
    return dict(camera_intrinsics=modes.pop(),tool_geometry_details=geometry.pop(),execution_budget_details=False)


def normalize_input_contract(protocol):
    if not isinstance(protocol,dict):
        raise ValueError('Invalid source input contract')
    protocol=dict(protocol)
    protocol.setdefault('perception_tools',False)
    protocol.setdefault('ik_comparison_details',False)
    protocol.setdefault('ik_comparison_format','matrix')
    flags=('tool_geometry_details','execution_budget_details','perception_tools','ik_comparison_details')
    if set(protocol)!={'camera_intrinsics','ik_comparison_format',*flags} or protocol['camera_intrinsics'] not in ('sdk','native') or any(type(protocol[k]) is not bool for k in flags):
        raise ValueError('Invalid source input contract')
    if protocol['ik_comparison_format'] not in ('matrix','named','named_rates') or (protocol['ik_comparison_format']!='matrix' and not protocol['ik_comparison_details']):
        raise ValueError('Invalid robot IK input representation contract')
    return protocol


def call(kind, prompt, images, folder, schema=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    private = Path(__file__).resolve().parents[2] / '.private'
    if kind == 'planner':
        model, base, keyfile, provenance = 'gpt-6.1-sol', 'https://ai2robcowork.site/openai/v1', 'planner-ai2robcowork.key', 'user-ai2robcowork'
    else:
        model, base, keyfile, provenance = 'gpt-6-luna', 'https://api.openai.com/v1', 'du-openai-direct.key', 'du'
    body = dict(model=model, input=[dict(role='user', content=[dict(type='input_text', text=prompt)] + image_content(images))],
                reasoning=dict(effort='high'), max_output_tokens=32768 if kind == 'planner' else 16384,
                store=False)
    if schema:
        body['text'] = dict(format=dict(type='json_schema', name='robot_decision', strict=True, schema=schema))
    english(prompt)
    # Preserve exact text, image provenance and body hash without duplicating binary images.
    wire = json.dumps(body).encode()
    dump(folder / 'request.json', dict(model=model, reasoning=body['reasoning'], provenance=provenance,
         prompt=prompt, images={k:dict(path=str(v), sha256=hashlib.sha256(Path(v).read_bytes()).hexdigest()) for k,v in images.items()},
         text=body.get('text'), max_output_tokens=body['max_output_tokens'], wire_sha256=hashlib.sha256(wire).hexdigest()))
    transport = folder / '.wire.json'
    transport.write_bytes(wire)
    transport.chmod(0o600)
    key = (private / keyfile).read_text().strip()
    config = 'url = "' + base + '/responses"\nheader = "Authorization: Bearer ' + key + '"\nheader = "Content-Type: application/json"\n'
    started = time.time()
    try:
        result = post_json(config,transport,folder)
        (folder / 'response.json').write_text(result.stdout)
        if result.returncode:
            raise RuntimeError('Model transport failed: ' + result.stderr[-300:] + ' HTTP body: '+result.stdout[:500])
        raw = json.loads(result.stdout)
        if raw.get('model') != model:
            raise RuntimeError('Unexpected response model: '+str(raw.get('model')))
        if raw.get('status') not in (None, 'completed'):
            raise RuntimeError('Incomplete model response: '+str(raw.get('status')))
        text = '\n'.join(c.get('text','') for o in raw.get('output',[]) for c in o.get('content',[]) if c.get('type')=='output_text')
        (folder / 'output.txt').write_text(text)
        english(text)
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip())
        return json.loads(text)
    finally:
        transport.unlink(missing_ok=True)
        dump(folder / 'timing.json', dict(seconds=time.time()-started, provenance=provenance))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--probe', choices=['planner','decision'], required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(call(args.probe, 'Return only the JSON object {"ready":true}.', {}, args.output))

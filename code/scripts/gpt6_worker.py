"""Run the user-requested GPT-6 coding worker on the experiment server.

Transport/orchestration only. The server model authors the observation schema,
task adapters and controller. Tools are limited to listed source files and a
new generated output directory; no shell, credentials, layouts or audit access.
"""
import argparse
import json
import os
import shutil
from pathlib import Path
import time
import urllib.request
import urllib.error


def request(payload, key_file, base_url, timeout=600):
    credential = Path(key_file).read_text().strip()
    req = urllib.request.Request(base_url.rstrip('/')+'/responses', data=json.dumps(payload).encode(),
        headers={'Authorization':'Bearer '+credential,'Content-Type':'application/json','User-Agent':'jev-rsi/1'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            message = exc.read().decode(errors='replace').replace(credential,'[redacted]')
            if exc.code in (502,503,504) and attempt<2:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(f'Gateway HTTP {exc.code}: {message[:1000]}') from None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--requirements',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--generated',type=Path,required=True)
    p.add_argument('--key-file',default='.private/openai.key')
    p.add_argument('--base-url',default='https://sub2api.qinjiu8.com/v1')
    p.add_argument('--model',default='gpt-6-astra')
    p.add_argument('--rounds',type=int,default=16)
    p.add_argument('--reference-generated',type=Path)
    args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    args.generated.mkdir(parents=True,exist_ok=False)
    root=Path.cwd().resolve()
    upstream=Path('/root/yekangjie/project/robodojo-jev')
    allowed={str(x.resolve()) for x in (root/'code/scripts').glob('*.py')}
    if args.reference_generated:
        reference=args.reference_generated.resolve()
        if not reference.is_relative_to(root/'code/generated'):
            raise ValueError('Reference must be a project generated source directory')
        allowed.update(str(x.resolve()) for x in reference.rglob('*') if x.is_file() and x.suffix in ('.py','.md'))
    allowed.update(str((upstream/x).resolve()) for x in (
        'controller/src/realman_jev/robodojo_rgb.py',
        'GPT-as-Policy/hybrid_rollout/robodojo/robodojo_server/kinematics.py',
        'GPT-as-Policy/hybrid_rollout/robodojo/robodojo_server/protocol.py'))
    functions=[dict(type='function',name='read_source',description='Read one allowed source file; no credentials/layouts/rewards.',
        parameters=dict(type='object',properties=dict(path=dict(type='string')),required=['path'],additionalProperties=False)),
        dict(type='function',name='write_generated',description='Write a NEW candidate source/document file under the generated directory; do not create test scripts.',
        parameters=dict(type='object',properties=dict(name=dict(type='string'),content=dict(type='string')),
            required=['name','content'],additionalProperties=False)),
        dict(type='function',name='copy_reference',description='Copy one allowed reference source into the new candidate, preserving its contents.',
        parameters=dict(type='object',properties=dict(path=dict(type='string'),name=dict(type='string')),
            required=['path','name'],additionalProperties=False)),
        dict(type='function',name='patch_generated',description='Replace one unique exact text span in a new candidate file. Read first; old must occur exactly once.',
        parameters=dict(type='object',properties=dict(name=dict(type='string'),old=dict(type='string'),new=dict(type='string')),
            required=['name','old','new'],additionalProperties=False))]
    text=args.requirements.read_text()+'\nAllowed source paths:\n'+'\n'.join(sorted(allowed))
    conversation=[dict(role='user',content=text)]
    (args.output/'requirements.txt').write_text(text)
    started=time.monotonic()
    for index in range(args.rounds):
        payload=dict(model=args.model,input=conversation,tools=functions,parallel_tool_calls=False,
            reasoning=dict(effort='high'),max_output_tokens=18000,store=False)
        response=request(payload,args.key_file,args.base_url)
        (args.output/f'response-{index:02d}.json').write_text(json.dumps(response,indent=2))
        print(json.dumps(dict(round=index,model=response.get('model'),status=response.get('status'),
            seconds=round(time.monotonic()-started,1),usage=response.get('usage'))),flush=True)
        if response.get('model') != args.model:
            raise RuntimeError('Unexpected model; no fallback authorized')
        outputs=response.get('output',[])
        conversation.extend(outputs)
        calls=[item for item in outputs if item.get('type')=='function_call']
        if not calls:
            final='\n'.join(c.get('text','') for item in outputs for c in item.get('content',[]) if c.get('type')=='output_text')
            (args.output/'final.md').write_text(final)
            if response.get('status')!='completed':
                raise RuntimeError('Worker output incomplete')
            return
        for call in calls:
            try:
                data=json.loads(call['arguments'])
                if call['name']=='read_source':
                    path=Path(data['path']).resolve()
                    if str(path) not in allowed:
                        raise PermissionError('Path not in source allowlist')
                    result=path.read_text()
                elif call['name'] in ('write_generated','copy_reference','patch_generated'):
                    name=Path(data['name'])
                    if name.is_absolute() or '..' in name.parts or name.suffix not in ('.py','.json','.md'):
                        raise ValueError('Invalid generated file name')
                    path=args.generated/name
                    path.parent.mkdir(parents=True,exist_ok=True)
                    if call['name']=='copy_reference':
                        source=Path(data['path']).resolve()
                        if str(source) not in allowed: raise PermissionError('Source not allowed')
                        if path.exists(): raise FileExistsError(path)
                        shutil.copyfile(source,path)
                    elif call['name']=='patch_generated':
                        content=path.read_text()
                        if not data['old'] or content.count(data['old'])!=1:
                            raise ValueError('Old text must occur exactly once')
                        path.write_text(content.replace(data['old'],data['new'],1))
                    else:
                        path.write_text(data['content'])
                    allowed.add(str(path.resolve()))
                    result=f'Written {path} ({path.stat().st_size} bytes)'
                else:
                    raise ValueError('Unknown function')
            except Exception as exc:
                result=f'{type(exc).__name__}: {exc}'
            conversation.append(dict(type='function_call_output',call_id=call['call_id'],output=result))
    raise RuntimeError('Worker round budget reached; review partial artifacts')


if __name__=='__main__':
    main()

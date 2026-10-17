"""Tool-enabled initial planning. Processing artifacts stay outside plan JSON."""
import json
from pathlib import Path
import subprocess
import re
import time
import shutil
from models import dump,english,image_content
from sandbox import execute

TOOLS=[dict(type='function',name=name,description=description,strict=True,
       parameters=dict(type='object',properties={arg:dict(type='string')},required=[arg],additionalProperties=False))
       for name,arg,description in [
           ('run','command','Run a shell command in the isolated /work directory. Read current observations in /input and public robot files in /robot. Save generated code in /work and test outputs in /output.'),
           ('view_image','path','Inspect an input or generated PNG image under /input, /work, or /output.')]]


def prepare(prompt,images,inputs,folder,resume_implementation=None):
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=False)
    workspace=folder/'implementation'
    if resume_implementation:
        shutil.copytree(resume_implementation,workspace,symlinks=True)
    else:
        workspace.mkdir()
    output=folder/'verification'
    output.mkdir()
    instructions='''PROCESSING DELIVERY
Additional processing is enabled. Use tools to design, implement, and verify the information needed by this advancer. Make the required spatial comparisons explicit and provide interpretable measurements when RGB alone is difficult for the advancer.
The execution tool provides CPU Python, NumPy, SciPy, OpenCV, Pillow and shell utilities. Other dependencies can be installed under /work/site-packages. /robot contains only public robot assets. /input contains current RGB images, robot state and camera calibration. No simulator object state or task-success signals are available.
Create an executable /work/processor. It accepts two arguments: an observation JSON path and an output JSON path. It must recompute information from the supplied fresh observation. Its output is a JSON object mapping additional-input names to values for the supplied current_stage. It must not command the robot or select the advancer's action choices.
For an additional image input, use a value object with image_path pointing to a PNG under /output and an English description. The runtime will attach that image for Luna; text-only comparison conditions omit images. Prefer explicit numerical or textual measurements when those make the fixed categorical decisions easier.
The input observation JSON contains task, current_stage, robot_state, cameras and images. Image paths are sandbox paths under /input. Camera matrices state their conventions explicitly.
Before stages are defined, current_stage is a planning placeholder. For a test, copy the input JSON to /output and replace only current_stage with a proposed stage; preserve the supplied observations and image paths.
Use /input/observation.json for testing. Run ./processor /input/observation.json /output/additional.json and inspect the numerical and visual results. You may inspect generated overlays with view_image. Correct errors before final delivery.
A workflow is not ready merely because it runs or outputs placeholders. Verify that it produces information useful for the initial stage's decisions on the supplied observations. When uncertainty limits precision, provide usable coarse information for earlier stages instead of making every stage depend on final-contact precision.
Return only the final stage-plan JSON after verification. additional_inputs is a list of objects with name and description, plus units/frame/uncertainty/missing_data explanations where relevant. Each name binds to a key in the processor's output. Include no code, paths to implementations, dependencies or test records in the final JSON. Keep stages and completion conditions easy for the advancer to use. The fixed eight questions and motion choices remain unchanged.
'''
    if resume_implementation:
        instructions+='\nAn unfinished implementation is present in /work. Inspect it, adapt or replace it for the current observations, and complete verification. It is reference code, not a validated method or a final plan.\n'
    english(prompt+'\n\n'+instructions)
    messages=[dict(role='user',content=[dict(type='input_text',text=prompt+'\n\n'+instructions)]+image_content(images))]
    dump(folder/'context.json',dict(prompt=prompt+'\n\n'+instructions,images={k:str(v) for k,v in images.items()}))
    key=(Path(__file__).resolve().parents[2]/'.private/planner-ai2robcowork.key').read_text().strip()
    for index in range(64):
        step=folder/f'tool-{index:02d}'
        step.mkdir()
        body=dict(model='gpt-6.1-sol',reasoning=dict(effort='high'),max_output_tokens=32768,
                  store=False,include=['reasoning.encrypted_content'],input=messages,tools=TOOLS,parallel_tool_calls=False)
        english(messages)
        wire=step/'.wire.json'
        wire.write_text(json.dumps(body))
        config='url = "https://ai2robcowork.site/openai/v1/responses"\nheader = "Authorization: Bearer '+key+'"\nheader = "Content-Type: application/json"\n'
        started=time.time()
        try:
            result=subprocess.run(['curl','--silent','--show-error','--fail-with-body','--max-time','600','--connect-timeout','25',
                                   '--config','-','--data-binary','@'+str(wire)],input=config,text=True,capture_output=True)
            (step/'response.json').write_text(result.stdout)
            if result.returncode:
                raise RuntimeError('Planner transport: '+result.stdout[:300]+result.stderr[-200:])
            raw=json.loads(result.stdout)
            if raw.get('model')!='gpt-6.1-sol' or raw.get('status')!='completed':
                raise RuntimeError('Wrong model or incomplete planning response')
        finally:
            wire.unlink(missing_ok=True)
            dump(step/'timing.json',dict(seconds=time.time()-started))
        items=raw.get('output',[])
        messages+=items
        calls=[o for o in items if o.get('type')=='function_call']
        if not calls:
            text='\n'.join(c.get('text','') for o in items for c in o.get('content',[]) if c.get('type')=='output_text')
            english(text)
            try:
                plan=json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',text.strip()))
                stages=plan['stages']
                ids=[s['id'] for s in stages]
                assert ids and len(ids)==len(set(ids)), 'Stage ids must be unique.'
                assert plan['initial_stage'] in ids, 'initial_stage must name an existing stage.'
                for stage in stages:
                    for field in ('goal','target_description','controlled_arm','completion_condition','next_stage','additional_inputs'):
                        assert field in stage, 'Missing stage field: '+field
                    assert stage['controlled_arm'] in ('left','right'), 'controlled_arm must be left or right.'
                    assert stage['next_stage'] is None or stage['next_stage'] in ids, 'next_stage must name an existing stage or be null.'
                    assert isinstance(stage['additional_inputs'],list), 'additional_inputs must be a list.'
                    for entry in stage['additional_inputs']:
                        assert isinstance(entry,dict) and 'name' in entry and 'description' in entry, 'Additional inputs need name and description.'
            except (ValueError,KeyError,TypeError,AssertionError) as error:
                messages.append(dict(role='user',content='Plan interface validation failed: '+str(error)+'. Correct the final JSON using the specified schema.'))
                continue
            if not (workspace/'processor').is_file() or (workspace/'processor').is_symlink():
                messages.append(dict(role='user',content='Delivery check failed: /work/processor is missing. Implement and test it before returning the final JSON.'))
                continue
            # Verify delivery with the model's actual initial stage, not its test placeholder.
            observation=json.loads((Path(inputs)/'observation.json').read_text())
            observation['current_stage']=next(s for s in plan['stages'] if s['id']==plan['initial_stage'])
            dump(Path(inputs)/'observation.json',observation)
            check=execute(workspace,inputs,output,'./processor /input/observation.json /output/additional.json',readonly=True)
            dump(output/'delivery_check.json',check)
            if check['returncode'] or not (output/'additional.json').is_file() or (output/'additional.json').is_symlink():
                messages.append(dict(role='user',content='Delivery check failed in read-only implementation mode. Write runtime outputs only under /output. Correct the processor and test again. '+json.dumps(check)[-10000:]))
                continue
            values=json.loads((output/'additional.json').read_text())
            english(values)
            required=[x['name'] for x in observation['current_stage']['additional_inputs']]
            if any(name not in values for name in required):
                messages.append(dict(role='user',content='Delivery check failed: required additional-input names are missing from processor output. Correct the interface and test again.'))
                continue
            dump(folder/'plan.json',plan)
            return plan,workspace
        for tool in calls:
            args=json.loads(tool['arguments'])
            english(args)
            inspected=None
            if tool['name']=='run':
                try:
                    evidence=execute(workspace,inputs,output,args['command'])
                except Exception as error:
                    evidence=dict(error=str(error))
                dump(step/'execution.json',dict(arguments=args,result=evidence))
                reply=json.dumps(evidence,ensure_ascii=False)[-24000:]
            elif tool['name']=='view_image':
                path=Path(args['path'])
                mappings={'/input':Path(inputs),'/work':workspace,'/output':output}
                inspected=None
                for prefix,host in mappings.items():
                    if str(path).startswith(prefix+'/'):
                        candidate=(host/str(path)[len(prefix)+1:]).resolve()
                        if candidate.is_relative_to(host.resolve()) and candidate.is_file() and candidate.suffix.lower()=='.png':
                            inspected=candidate
                        break
                reply='Image attached.' if inspected else 'Image path not available.'
            else:
                reply='Unknown tool.'
            try:
                english(reply)
            except ValueError:
                reply='Tool output contains non-English text. Correct its source and produce English output.'
            messages.append(dict(type='function_call_output',call_id=tool['call_id'],output=reply))
            if inspected:
                messages.append(dict(role='user',content=image_content({args['path']:inspected})))
    raise RuntimeError('Initial planning tool budget exhausted without a verified final plan')

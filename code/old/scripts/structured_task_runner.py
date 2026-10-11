"""Transport and execution harness for server-GPT-6-authored Jev adapters.

No task target/stage/perception algorithm is supplied here. The generated
controller designs those. This harness keeps native evaluation and raw logs.
"""
import base64
import hashlib
import importlib.util
import io
import gzip
import json
from pathlib import Path
import sys
import time
import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation
from gpt6_worker import request
from run_position_pilot import dump, append


def run(rec,rpc,reset):
    cfg=rec.cfg
    sys.path.insert(0,cfg['existing_root']+'/controller/src')
    pro = cfg.get('model_backend') == 'codex_pro'
    if pro:
        from codex_pro_bridge import API, MODEL, EFFORT
        api_settings = {'model': MODEL, 'timeout_s': 700}
        if cfg.get('deepseek_key_file') or cfg.get('jev_transport_backend') != 'codex_pro':
            raise ValueError('Pro trial cannot use a legacy model transport or DeepSeek')
    else:
        from realman_jev.api import API
        api_settings=dict(json.loads(Path(cfg['api_config']).read_text())['jev'])
        if 'jev_timeout_seconds' in cfg:api_settings['timeout_s']=cfg['jev_timeout_seconds']
    api=API(api_settings,rec.event,'jev')
    if cfg.get('jev_proxy_url') and not pro:
        import httpx
        old_client = api.client
        api.client = httpx.Client(proxy=cfg['jev_proxy_url'], trust_env=False,
                                  timeout=api_settings['timeout_s'], headers=old_client.headers,
                                  base_url=old_client.base_url)
        old_client.close()
    directory=Path(cfg['generated_controller']).resolve().parent
    sys.path.insert(0,str(directory))
    spec=importlib.util.spec_from_file_location('server_generated_controller',cfg['generated_controller'])
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    settings=dict(gpu=cfg['gpu'],existing_root=cfg['existing_root'],schema_variant=cfg['schema_variant'],
        max_step_m=.04,position_tolerance_m=.005,seed=cfg['seed'],run_dir=str(rec.folder))
    settings['experience_enabled']=cfg.get('experience_enabled',False)
    settings.update(cfg.get('controller_settings',{}))
    controller=module.Controller(cfg['runtime_task'].removesuffix('_random'),settings)
    dump(rec.folder/'generated_provenance.json',dict(files={str(p):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in directory.rglob('*') if p.is_file() and p.suffix in ('.py','.md','.json')},settings=settings))
    episode,tick=reset['episode_id'],reset['step_id']
    ended=False
    status='running'
    frame_count=vision_calls=actions=0
    previous=None
    current=None
    vision_cache={}

    def call(op,**kw):
        return rpc.request(op,episode_id=episode,step_id=tick,**kw)

    def ask_jev(state,questions):
        payload=dict(model=api.cfg['model'],state=state,questions=questions)
        import httpx
        attempts=1 if pro else cfg.get('jev_transport_attempts',1)
        if type(attempts) is not int or not 1<=attempts<=3:
            raise ValueError('Jev transport attempts must be an integer from 1 to 3')
        backend=cfg.get('jev_transport_backend','httpx')
        if backend not in ('httpx','curl','codex_pro') or (backend=='codex_pro') != pro:
            raise ValueError('Unknown Jev transport backend')
        for transport_attempt in range(attempts):
            rec.check_budget()
            index=len(rec.decisions)
            if index>=cfg['max_jev_decisions']:
                raise RuntimeError('Jev decision budget exhausted')
            folder=rec.folder/f'decision-{index:04d}'
            folder.mkdir()
            if transport_attempt:
                # The original call is audited by the controller. Retries use
                # the identical English payload and get their own audit entry.
                from input_contract import audit_request
                audit_request(state,questions,rec.folder)
            dump(folder/'request.json',payload)
            row=dict(decision_id=folder.name,native_step=tick,stage=state.get('stage','unspecified'),
                schema_variant=cfg['schema_variant'],observation=state,questions=questions,
                transport_attempt=transport_attempt+1)
            rec.decisions.append(row)
            start=time.monotonic()
            try:
                if backend=='curl':
                    from jev_curl_transport import post
                    response=post(api,payload,folder,cfg['jev_proxy_url'],api_settings['timeout_s'])
                else:
                    response=api.post('/systemone',payload)
            except (httpx.TransportError, RuntimeError) as exc:
                failure=dict(error_type=type(exc).__name__,error=str(exc),
                    request_seconds=time.monotonic()-start,usage_unknown=True,
                    decision_id=folder.name,transport_attempt=transport_attempt+1)
                dump(folder/'error.json',failure)
                rec.event(dict(kind='jev_transport_failure',**failure))
                if transport_attempt+1==attempts:
                    raise
                time.sleep(.5)
                continue
            dump(folder/'response.json',response)
            break
        if pro and (response.get('model') != MODEL or response.get('reasoning_effort') != EFFORT):
            raise RuntimeError('Pro control model/effort mismatch')
        if set(response.get('answers',{}))!=set(questions):
            raise ValueError('Jev did not answer all requested questions')
        for key,answer in response['answers'].items():
            if answer.get('choice') not in questions[key]['criteria']:
                raise ValueError('Jev choice outside declared criteria')
        row.update(answers=response['answers'],model=response.get('model'),request_seconds=time.monotonic()-start)
        dump(folder/'decision.json',row)
        append(rec.folder/'decisions.jsonl',row)
        return response

    detector = None
    detector_cfg = None
    if cfg.get("runtime_perception") == "groundingdino_sam2":
        if pro:
            raise ValueError('Pro trial must route semantic vision through GPT-6 Sol')
        from local_rgbd_perception import build_detector, visible_schema
        detector, detector_cfg = build_detector(cfg, cfg["gpu"])
        dump(rec.folder / "perception_config.json", detector_cfg)

    fallback = None
    if cfg.get("deepseek_key_file"):
        from deepseek_fallback import DeepSeekFallback
        fallback = DeepSeekFallback(cfg,rec.folder)

    def perceive(prompt,observation):
        nonlocal vision_calls
        rec.check_budget()
        batched=pro and cfg.get('pro_batch_views',False)
        cache_key=(frame_count,prompt,str(observation.get('instruction',''))) if batched else None
        if batched and cache_key in vision_cache:
            rec.event(dict(kind='pro_multiview_cache_hit',frame=frame_count,
                cameras=sorted(observation['cameras'])))
            return vision_cache[cache_key]
        if vision_calls>=cfg.get('max_vision_calls',40):
            raise RuntimeError('Vision perception call budget exhausted')
        folder=rec.folder/f'perception-{vision_calls:04d}'
        folder.mkdir()
        if detector is not None:
            vision_calls += 1
            detector_observation = dict(observation, robot=current['robot'])
            result = visible_schema(detector, detector_observation)
            active_arm=(controller.plan or {}).get('arms',['right'])[0]
            fallback_needed=(getattr(controller,'recovery_count',0)>0 and
                'cam_'+active_arm+'_wrist' in observation['cameras'])
            if fallback is not None and fallback_needed:
                labels=[r for v in result['views'].values() for r in v['objects'] if r['confidence']>=.5 and 'gripper' not in r['label']]
                if not labels and fallback.calls<fallback.limit:
                    result=fallback(prompt,observation,'wrist local detector has no confident non-robot instance')
            dump(folder/'response.json', dict(source='local_detector_with_logged_bounded_deepseek_fallback', result=result))
            dump(folder/'measurements.json', result)
            return result
        if cfg.get('forbid_runtime_gpt6',False):
            raise RuntimeError('Runtime GPT-6 disabled by campaign policy')
        cameras=current['cameras'] if batched else observation['cameras']
        visual_prompt=prompt
        if batched:
            visual_prompt=visual_prompt.replace('Inspect ONLY the supplied reference-camera RGB image.',
                'Inspect each supplied camera RGB image independently.')
            visual_prompt=visual_prompt.replace('Use the actual supplied camera name;',
                'Use every actual supplied camera name;')
            visual_prompt='Apply this visible-only contract independently to every attached camera; return all views in one JSON object.\n'+visual_prompt
        content=[dict(type='input_text',text=visual_prompt+'\nPublic instruction (visible noun disambiguation only): '+str(observation.get('instruction','')))]
        for name,view in cameras.items():
            buff=io.BytesIO()
            Image.fromarray(np.asarray(view['rgb'])).save(buff,format='JPEG',quality=90)
            content.extend([dict(type='input_text',text=f'Camera: {name}; image pixel width/height {view["rgb"].shape[1]}/{view["rgb"].shape[0]}'),
                dict(type='input_image',image_url='data:image/jpeg;base64,'+base64.b64encode(buff.getvalue()).decode())])
        payload=dict(model=MODEL if pro else 'gpt-6-astra',instructions='You are a visual measurement/OCR service. Return requested JSON of visible facts only. Do NOT plan robot actions, supply target waypoints, stages or movement directions. State missing observations explicitly.',
            input=[dict(role='user',content=content)],reasoning=dict(effort=EFFORT if pro else 'medium'),max_output_tokens=8000,
            text=dict(format=dict(type='json_object')),store=False)
        dump(folder/'request.json',payload)
        vision_calls+=1
        if pro:
            response=API({'model': MODEL},rec.event,'runtime_vision').post('/responses',payload)
        else:
            response=request(payload,cfg['gpt6_key_file'],cfg['gpt6_base_url'])
        dump(folder/'response.json',response)
        if response.get('model')!=(MODEL if pro else 'gpt-6-astra') or response.get('status')!='completed' or (pro and response.get('reasoning_effort')!=EFFORT):
            raise RuntimeError('Unexpected/incomplete GPT-6 perception response')
        text='\n'.join(c.get('text','') for x in response.get('output',[]) for c in x.get('content',[]) if c.get('type')=='output_text').strip()
        if text.startswith('```'):
            text=text.split('\n',1)[1].rsplit('```',1)[0].strip()
        result=json.loads(text)
        if batched:
            if not isinstance(result,dict) or not isinstance(result.get('views'),dict) or set(result['views'])!=set(cameras):
                raise ValueError('Batched visual response does not cover the exact camera set')
            vision_cache[cache_key]=result
        dump(folder/'measurements.json',result)
        return result

    try:
        metadata=rpc.request('metadata')
        while not ended:
            rec.check_budget()
            if actions>=cfg.get('max_outer_actions',200):
                status='outer_action_budget'; break
            current=call('rgbd_observation')
            current.update(remaining_steps=max(0,metadata['max_episode_steps']-tick),previous_execution=previous)
            frame=rec.folder/f'frame-{frame_count:04d}'
            frame.mkdir()
            for name,view in current['cameras'].items():
                view['rgb']=np.asarray(view['rgb'],dtype=np.uint8)
                view['depth_m']=np.asarray(view['depth_m'],dtype=np.float32)
                Image.fromarray(view['rgb']).save(frame/f'{name}.png')
                depth_path = frame/f'{name}-depth.npy'
                if cfg.get('compress_snapshot_depth', False):
                    # Store the exact NPY byte stream losslessly; observations
                    # used by the controller remain the original float32 array.
                    raw_depth = io.BytesIO()
                    np.save(raw_depth, view['depth_m'], allow_pickle=False)
                    depth_path.with_suffix('.npy.gz').write_bytes(gzip.compress(raw_depth.getvalue(), compresslevel=1, mtime=0))
                else:
                    np.save(depth_path,view['depth_m'])
            dump(frame/'metadata.json',{**{k:v for k,v in current.items() if k!='cameras'},
                'cameras':{name:{k:v for k,v in view.items() if k not in ('rgb','depth_m')} for name,view in current['cameras'].items()}})
            frame_count+=1
            old_calls=len(rec.decisions)
            command=controller.step(current,ask_jev,perceive)
            dump(frame/'command.json',command)
            if command.get('stop'):
                status='controller_stop:'+str(command.get('reason','unspecified')); break
            arms=command.get('arms',{})
            if not isinstance(arms,dict) or set(arms)-{'left','right'}:
                raise ValueError('Invalid arm command')
            ticks=command.get('ticks')
            if not isinstance(ticks,int) or not 1<=ticks<=15:
                raise ValueError('Invalid execution tick count')
            robot=current['robot']
            targets={name:dict(position=robot['eef_positions'][i],quaternion_wxyz=robot['eef_quaternions_wxyz'][i],
                gripper_opening=robot['states'][7*i+6],gripper_closed=robot['states'][7*i+6]<.5)
                for i,name in enumerate(('left','right'))}
            for name,arm in arms.items():
                i=('left','right').index(name)
                delta=np.asarray(arm['delta_xyz_m'],dtype=float)
                quat=np.asarray(arm['quaternion_wxyz'],dtype=float)
                grip=float(arm['gripper_opening'])
                if delta.shape!=(3,) or not np.isfinite(delta).all() or np.linalg.norm(delta)>.040001:
                    raise ValueError('Translation outside 40mm budget')
                if np.linalg.norm(delta)>1e-10 and len(rec.decisions)==old_calls:
                    raise ValueError('Translation without a fresh Jev call')
                if quat.shape!=(4,) or not np.isfinite(quat).all() or abs(np.linalg.norm(quat)-1)>.001 or not 0<=grip<=1:
                    raise ValueError('Invalid pose/gripper command')
                observed=np.asarray(robot['eef_quaternions_wxyz'][i])
                before_offset=Rotation.from_quat(observed[[1,2,3,0]]).apply([current['gripper_bias_m'][i],0,0])
                after_offset=Rotation.from_quat(quat[[1,2,3,0]]).apply([current['gripper_bias_m'][i],0,0])
                targets[name].update(position=(np.asarray(robot['eef_positions'][i])+before_offset+delta-after_offset).tolist(),
                    quaternion_wxyz=quat.tolist(),gripper_opening=grip,gripper_closed=grip<.5)
            call('audit_before',decision=actions,declaration=dict(stage=command.get('stage'),
                decision_ids=[r['decision_id'] for r in rec.decisions[old_calls:]],command=command))
            acknowledgements=[]
            for _ in range(ticks):
                proposal=(call('eef_joint_target',targets=targets) if arms else
                    dict(action=robot['states'],hold_current_joints=True))
                action=np.asarray(proposal['action'],np.float32)
                for i,name in enumerate(('left','right')):
                    if name not in arms:
                        action[i*7:i*7+7]=robot['states'][i*7:i*7+7]
                ack=call('chunk_step',actions=action.reshape(1,14),controller='gpt6_authored_structured_jev')
                tick=ack['step_id']
                acknowledgements.append(dict(action=action,ik=proposal,ack=ack))
                ended=any(row['terminated'] or row['truncated'] for row in ack['steps'])
                if ended: break
            call('audit_after',execution=dict(native_step=tick,command=command))
            previous=dict(stage=command.get('stage'),command=command,robot_before=robot,native_step=tick)
            rec.branch(dict(kind='structured_task_action',**previous,acks=acknowledgements))
            actions+=1
            print(json.dumps(dict(task=cfg['runtime_task'],stage=command.get('stage'),actions=actions,
                tick=tick,jev_calls=len(rec.decisions),vision_calls=vision_calls)),flush=True)
        if ended: status='native_episode_ended'
    except Exception as exc:
        status='exception:'+type(exc).__name__
        raise
    finally:
        api.close()
        try:
            final=call('finish_pilot',reason=status)
        except Exception as finish_error:
            final=dict(success=None,evaluation_unavailable=True,reason=status,
                finalization_error=str(finish_error),step_id=tick)
        dump(rec.folder/'native_finish.json',final)
        dump(rec.folder/'structured_result.json',dict(status=status,native=final,jev_calls=len(rec.decisions),
            model_control_calls=len(rec.decisions) if pro else 0,
            visual_model_calls=vision_calls if pro else 0,
            vision_calls=vision_calls,deepseek_calls=fallback.calls if fallback else 0,actions=actions,steps=tick,frames=frame_count,
            task=cfg['runtime_task'],schema=cfg['schema_variant'],
            model_backend='codex_pro' if pro else 'legacy_jev',
            model='gpt-6-sol' if pro else api.cfg.get('model'),
            reasoning_effort='xhigh' if pro else None))

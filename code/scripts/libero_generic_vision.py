"""Bounded semantic RGB recognition + SAM masks + calibrated geometry.
No category-specific colour, circle, task-id or relational selectors.
"""
import base64,io,json,os,select,subprocess,sys,time
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from run_position_pilot import dump

class GenericVision:
    def __init__(self,rec):
        self.rec=rec;self.calls=0;self.refreshes=0;self.identity=None;self.reasons=set()
        sys.path.insert(0,rec.cfg['existing_root']+'/controller/src')
        from realman_jev.api import API
        cfg=dict(base_url='https://sub2api.qinjiu8.com/v1',model='gpt-6-astra',key_file='/root/yekangjie/project/jev_rsi/.private/openai.key',timeout_s=90,expected_model_prefix='gpt-6',max_tokens=4000)
        self.api=API(cfg,rec.event,'semantic_vision')
        self.log=(rec.folder/'grounding-worker.log').open('w')
        env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
        self.worker=subprocess.Popen(['/root/yekangjie/project/robodojo-jev/envs/robodojo-isaac51/bin/python','-B',str(Path(__file__).with_name('libero_grounding_worker.py'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True,env=env)
        try:
            if not self.receive().get('ready'):raise RuntimeError('Grounding worker not ready')
        except Exception:
            self.close();raise
    def receive(self):
        if not select.select([self.worker.stdout],[],[],120)[0]:raise RuntimeError('Grounding worker timeout')
        line=self.worker.stdout.readline()
        if not line:raise RuntimeError('Grounding worker exited')
        result=json.loads(line)
        if 'error' in result:raise RuntimeError(result['error'])
        return result
    def recognize(self,views,task,reason):
        if self.calls>=3:raise RuntimeError('Semantic vision limit 3 reached')
        if reason not in ('initial','pregrasp','stalled'):raise ValueError(reason)
        if reason in self.reasons:raise RuntimeError('Repeated semantic trigger disallowed')
        self.reasons.add(reason)
        self.calls+=1;p=self.rec.folder/f'semantic-{self.calls}';p.mkdir()
        prompt='''Identify only visible objects required by the public pick-and-place instruction. No robot actions, trajectories, simulator truth or completion claims. Return JSON with source and destination. Each is {label:short plain noun phrase,camera:camera name,bbox:[x1,y1,x2,y2] in pixels,visible:boolean}. Resolve relational references from images. source is the object to move, destination the receiving object/surface. At pregrasp or stalled, locate the SAME source, preferably in wrist if visible; use previous identity description, do not switch instances. Reject ambiguity with visible=false. Bounding boxes enclose the whole visible object, exclude robot fingers and background. Coordinates are absolute pixels for the provided images; sizes are explicitly given for each camera. Return concise evidence string. Do not infer invisible boundaries.'''
        if self.rec.cfg.get('geometry_profile')=='observed_surfaces':
            prompt += " Carefully resolve exact product identity from visible packaging, especially when several similar objects exist. Describe visible distinguishing evidence; if identity is ambiguous set visible=false instead of choosing a convenient object. For destination, bound only the VISIBLE receiving region: the interior opening of an open container (exclude outside walls and handles), or the exposed support surface. Report receiver_kind as open_container or support_surface in destination. This is visual region recognition only; do not propose robot motions or hidden bottom geometry."
        content=[dict(type='input_text',text='Return JSON. '+json.dumps(dict(task=task,reason=reason,previous_identity=self.identity))) ]
        for name,v in views.items():
            buf=io.BytesIO();Image.fromarray(v['rgb']).save(buf,'PNG')
            content.extend([dict(type='input_text',text='Camera '+name+' size '+str(v['rgb'].shape[1])+'x'+str(v['rgb'].shape[0])),dict(type='input_image',image_url='data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode(),detail='high')])
        request=dict(model='gpt-6-astra',instructions=prompt,input=[dict(role='user',content=content)],max_output_tokens=4000,store=False,text=dict(format=dict(type='json_object')))
        dump(p/'request.json',request);raw=self.api.post('/responses',request);dump(p/'response.json',raw)
        if raw.get('status')!='completed':raise RuntimeError('Semantic model incomplete')
        text=''.join(c.get('text','') for item in raw.get('output',[]) for c in item.get('content',[]) if c.get('type')=='output_text')
        result=json.loads(text)
        for role in ['source','destination']:
            ob=result[role]
            if not ob['visible']:raise RuntimeError('Semantic evidence unavailable: '+role)
            b=np.asarray(ob['bbox'],float)
            if ob['camera'] not in views or b.shape!=(4,) or not np.isfinite(b).all() or (b<0).any() or (b>np.array([views[ob['camera']]['rgb'].shape[1],views[ob['camera']]['rgb'].shape[0]]*2)).any() or b[2]<=b[0] or b[3]<=b[1]:raise ValueError('Invalid semantic bounding box')
        self.identity=result;dump(p/'objects.json',result);return result
    def measure(self,view,bbox,label,reason):
        self.refreshes+=1;p=self.rec.folder/f'mask-{self.refreshes}';p.mkdir();image=p/'rgb.png';cv2.imwrite(str(image),cv2.cvtColor(view['rgb'],cv2.COLOR_RGB2BGR));np.save(p/'depth.npy',view['depth']);dump(p/'calibration.json',dict(K=view['K'],T=view['T'],reason=reason))
        req=dict(image=str(image),boxes=[dict(label=label,bbox=bbox)],output=str(p/'segmentation'))
        self.worker.stdin.write(json.dumps(req)+'\n');self.worker.stdin.flush();r=self.receive()
        if len(r['objects'])!=1:raise RuntimeError('Object segmentation missing')
        mask=np.load(r['objects'][0]['mask_path']);d=view['depth'];K=view['K'];T=view['T'];vv,uu=np.indices(d.shape)
        box=np.asarray(bbox,float);inside=(uu>=box[0])&(uu<=box[2])&(vv>=box[1])&(vv<=box[3])
        if (mask&inside).sum()/max(1,mask.sum())<.7:
            raise RuntimeError('Mask largely outside semantic/projected bounding box')
        pts=np.stack([(uu-K[0,2])*d/K[0,0],(vv-K[1,2])*d/K[1,1],d],-1)@T[:3,:3].T+T[:3,3]
        good=mask&np.isfinite(d)&(d>.02)&(d<3)
        data=pts[good]
        if len(data)<80:raise RuntimeError('Too few valid segmented depth points')
        lo,hi=np.quantile(data,[.05,.95],axis=0);center=(lo+hi)/2
        if (hi-lo>.35).any():raise RuntimeError('Foreground depth extent exceeds 35cm')
        result=dict(center=center,low=lo,high=hi,points=len(data),label=label,source='semantic box + SAM visible mask + RGB-D quantiles')
        dump(p/'geometry.json',result);return result
    def close(self):
        self.api.close()
        if self.worker.poll() is None:
            try:self.worker.stdin.write('{"close":true}\n');self.worker.stdin.flush();self.worker.wait(timeout=20)
            except Exception:self.worker.terminate();self.worker.wait(timeout=20)
        self.log.close()


def run_generic(env,obs,rec,task,depth_fn,k_fn,t_fn):
    """Single-object pick/place only; semantic recognition never chooses actions."""
    from run_position_pilot import Jev
    vision=GenericVision(rec);model=Jev(rec);ticks=0;recovery_used=False
    start_tcp=obs['robot0_eef_pos'].copy()
    def views():
        return {c:dict(rgb=np.ascontiguousarray(obs[c+'_image'][::-1]),depth=depth_fn(env.sim,obs[c+'_depth'])[::-1].squeeze(),K=k_fn(env.sim,c,384,384),T=t_fn(env.sim,c)) for c in ['agentview','robot0_eye_in_hand']}
    def snapshot(stage):
        for c,v in views().items():cv2.imwrite(str(rec.folder/f'{ticks:04d}-{stage}-{c}.png'),cv2.cvtColor(v['rgb'],cv2.COLOR_RGB2BGR))
    def step(action,n):
        nonlocal ticks,obs
        for _ in range(n):
            rec.check_budget()
            if ticks>=550:raise RuntimeError('Native step budget')
            obs,_,_,_=env.step(np.asarray(action,float));ticks+=1
    def move(target,stage,grip):
        stall=0
        rec.event(dict(kind='stage',stage=stage,target=target.tolist()))
        for i in range(40):
            p=obs['robot0_eef_pos'].copy();err=target-p
            if np.max(np.abs(err))<.007:return
            state=dict(task=task.language,stage=stage,position_m=p.tolist(),target_position_m=target.tolist(),hold_tolerance_m=.004,
                       observation_source='semantic object masks + fresh RGB-D + robot state',target_source='external generic pick/place geometry',
                       error_m=err.tolist(),frame='world metres',gripper=grip)
            d=model.choose(state,dict(stage=stage,iteration=i,environment='libero_plus_generic'))
            if d is None:raise RuntimeError('Jev budget')
            delta=np.asarray(d['signs'])*np.minimum(.02,np.abs(err)*.5)
            step(np.r_[delta/.05,0,0,0,grip],3)
            after=obs['robot0_eef_pos'].copy()
            rec.branch(dict(stage=stage,decision_id=d['decision_id'],before=p,after=after,delta=delta,native_steps=ticks))
            snapshot(stage)
            stall=stall+1 if np.linalg.norm(after-p)<.0008 and np.linalg.norm(err)>.015 else 0
            if stall>=3:raise RuntimeError('Physical stall: '+stage)
        if np.max(np.abs(target-obs['robot0_eef_pos']))>=.007:raise RuntimeError('Stage budget: '+stage)
    def grasp_point(src):
        # Own gripper pad geometry is robot proprioception, not object truth.
        robot=env.robots[0]
        names=robot.gripper.important_geoms
        centers=[]
        for key in ['left_fingerpad','right_fingerpad']:
            centers.append(np.mean([env.sim.data.geom_xpos[env.sim.model.geom_name2id(n)] for n in names[key]],axis=0))
        axis=np.asarray(centers[1])-centers[0];axis=axis[:2]/max(np.linalg.norm(axis[:2]),1e-9)
        perpendicular=np.array([-axis[1],axis[0]])
        extent=src['high']-src['low'];target=src['center'].copy()
        width=float(np.dot(np.abs(axis),extent[:2]))
        if width>.065:
            # Wider than a comfortable pad span: pinch an observed boundary,
            # not the whole object center. Generic edge heuristic, not learned grasp.
            sign=1 if np.dot(start_tcp[:2]-target[:2],axis)>0 else -1
            distance=max(0,.90*width/2)
            target[:2]+=sign*distance*axis
        target[2]=src['low'][2]+.40*extent[2]
        dump(rec.folder/f'grasp-{vision.calls}.json',dict(target=target,closing_axis=axis,observed_width=width,
             source='visible extent plus own gripper span; generic boundary pinch heuristic'))
        return target
    def locate(reason):
        v=views();sem=vision.recognize(v,task.language,reason);geom={}
        for role in ['source','destination']:
            x=sem[role];geom[role]=vision.measure(v[x['camera']],x['bbox'],x['label'],reason+'-'+role)
        dump(rec.folder/(reason+'-geometry.json'),geom)
        return sem,geom
    try:
        sem,g=locate('initial');src=g['source'];dst=g['destination']
        hover=max(src['high'][2],dst['high'][2])+.14
        move(np.r_[src['center'][:2],hover],'approach',-1)
        # Mandatory fresh wrist-inclusive localization before descending / closing.
        sem,g=locate('pregrasp');src=g['source'];dst=g['destination']
        target=grasp_point(src)
        move(np.r_[target[:2],hover],'align',-1)
        try:move(target,'descend',-1)
        except RuntimeError as exc:
            if 'Physical stall' not in str(exc):raise
            recovery_used=True
            move(obs['robot0_eef_pos']+np.array([0,0,.06]),'retract',-1)
            sem,g=locate('stalled');src=g['source'];dst=g['destination']
            target=grasp_point(src)
            move(np.r_[target[:2],obs['robot0_eef_pos'][2]],'realign',-1)
            move(target,'descend_recovery',-1)
        # Every grasp uses newly localized geometry; explicit robot geometry offset.
        tcp_before=obs['robot0_eef_pos'].copy();source_before=src['center'].copy()
        step([0,0,0,0,0,0,1],16);snapshot('close')
        dump(rec.folder/'gripper-close.json',dict(qpos=obs['robot0_gripper_qpos'],tcp=obs['robot0_eef_pos']))
        move(np.r_[tcp_before[:2],hover],'lift',1)
        # Verify source using a fresh detector, associated to predicted source location.
        v=views();cam='robot0_eye_in_hand'
        predicted=source_before+(obs['robot0_eef_pos']-tcp_before)
        T=v[cam]['T'];K=v[cam]['K'];cp=T[:3,:3].T@(predicted-T[:3,3])
        if cp[2]<=0:raise RuntimeError('Source behind wrist camera')
        uv=(K@cp)[:2]/cp[2];extent=np.clip(max(src['high']-src['low'])*K[0,0]/cp[2],30,250)
        box=np.r_[uv-extent*.65,uv+extent*.65].clip(0,383).tolist()
        held=vision.measure(v[cam],box,sem['source']['label'],'lift-association')
        if (held['low'][2]-src['low'][2]<.04 or
            (held['high'][2]-held['low'][2])>max(.06,1.8*(src['high'][2]-src['low'][2])) or
            np.linalg.norm(held['center']-predicted)>.06):
            raise RuntimeError('No reliable RGB-D evidence of lifted source')
        offset=held['center']-obs['robot0_eef_pos'];dump(rec.folder/'generic-held-offset.json',dict(offset=offset,held=held,predicted=predicted))
        move(np.r_[dst['center'][:2]-offset[:2],hover],'carry',1)
        # Fresh same-view source/destination geometry at placement, no new semantic call.
        current=views();cam='agentview';view=current[cam]
        def project_box(center,size):
            half=np.maximum(np.asarray(size)/2,.01)
            corners=np.array([center+half*np.array([i,j,k]) for i in [-1,1] for j in [-1,1] for k in [-1,1]])
            camera=(corners-view['T'][:3,3])@view['T'][:3,:3]
            if (camera[:,2]<=.02).any():raise RuntimeError('Placement region outside camera')
            uv=(camera@view['K'].T);uv=uv[:,:2]/uv[:,2,None]
            lo=uv.min(axis=0)-6;hi=uv.max(axis=0)+6
            return np.r_[lo,hi].clip(0,383).tolist()
        predicted_center=obs['robot0_eef_pos']+offset
        observed_source=vision.measure(view,project_box(predicted_center,src['high']-src['low']),sem['source']['label'],'preplace-source')
        observed_destination=vision.measure(view,project_box(dst['center'],dst['high']-dst['low']),sem['destination']['label'],'preplace-destination')
        if np.linalg.norm(observed_source['center']-predicted_center)>.065:
            raise RuntimeError('Preplace source association inconsistent')
        if np.linalg.norm(observed_destination['center']-dst['center'])>.03:
            raise RuntimeError('Preplace destination association inconsistent')
        if observed_source['low'][2]<observed_destination['high'][2]+.04:
            raise RuntimeError('Preplace source not visibly held above receiver')
        offset=observed_source['center']-obs['robot0_eef_pos'];held=observed_source;dst=observed_destination
        dump(rec.folder/'preplace-geometry.json',dict(source=held,destination=dst,offset=offset,predicted_source=predicted_center))
        move(np.r_[dst['center'][:2]-offset[:2],hover],'preplace_align',1)
        # Lower to observed receiving surface plus observed source half-height.
        height=(held['high'][2]-held['low'][2])/2
        place=np.r_[dst['center'][:2]-offset[:2],dst['high'][2]+height+.012-offset[2]]
        move(place,'lower',1);step([0,0,0,0,0,0,-1],16);snapshot('release')
        move(np.r_[place[:2],hover],'retreat',-1)
        success=bool(env.check_success())
        dump(rec.folder/'result.json',dict(success=success,native_steps=ticks,jev_calls=len(rec.decisions),semantic_calls=vision.calls,deepseek_calls=0,recovery_used=recovery_used))
        rec.finish('success' if success else 'task_failed')
    except Exception as exc:
        dump(rec.folder/'result.json',dict(success=False,error_type=type(exc).__name__,error=str(exc),native_steps=ticks,jev_calls=len(rec.decisions),semantic_calls=vision.calls,deepseek_calls=0,recovery_used=recovery_used))
        rec.finish('failed');raise
    finally:model.close();vision.close()

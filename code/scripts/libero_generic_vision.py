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
        self.rec=rec;self.calls=0;self.refreshes=0;self.identity=None
        sys.path.insert(0,rec.cfg['existing_root']+'/controller/src')
        from realman_jev.api import API
        cfg=dict(base_url='https://sub2api.qinjiu8.com/v1',model='gpt-6-astra',key_file='/root/yekangjie/project/jev_rsi/.private/openai.key',timeout_s=90,expected_model_prefix='gpt-6',max_tokens=4000)
        self.api=API(cfg,rec.event,'semantic_vision')
        self.log=(rec.folder/'grounding-worker.log').open('w')
        env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
        self.worker=subprocess.Popen(['/root/yekangjie/project/robodojo-jev/envs/robodojo-isaac51/bin/python','-B',str(Path(__file__).with_name('libero_grounding_worker.py'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True,env=env)
        if not self.receive().get('ready'):raise RuntimeError('Grounding worker not ready')
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
        self.calls+=1;p=self.rec.folder/f'semantic-{self.calls}';p.mkdir()
        prompt='''Identify only visible objects required by the public pick-and-place instruction. No robot actions, trajectories, simulator truth or completion claims. Return JSON with source and destination. Each is {label:short plain noun phrase,camera:camera name,bbox:[x1,y1,x2,y2] in pixels,visible:boolean}. Resolve relational references from images. source is the object to move, destination the receiving object/surface. At pregrasp or stalled, locate the SAME source, preferably in wrist if visible; use previous identity description, do not switch instances. Reject ambiguity with visible=false. Bounding boxes enclose the whole visible object, exclude robot fingers and background. Coordinates are for the 384x384 provided images. Return concise evidence string. Do not infer invisible boundaries.'''
        content=[dict(type='input_text',text=json.dumps(dict(task=task,reason=reason,previous_identity=self.identity))) ]
        for name,v in views.items():
            buf=io.BytesIO();Image.fromarray(v['rgb']).save(buf,'PNG')
            content.extend([dict(type='input_text',text='Camera '+name),dict(type='input_image',image_url='data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode(),detail='high')])
        request=dict(model='gpt-6-astra',instructions=prompt,input=[dict(role='user',content=content)],max_output_tokens=4000,store=False,text=dict(format=dict(type='json_object')))
        dump(p/'request.json',request);raw=self.api.post('/responses',request);dump(p/'response.json',raw)
        if raw.get('status')!='completed':raise RuntimeError('Semantic model incomplete')
        text=''.join(c.get('text','') for item in raw.get('output',[]) for c in item.get('content',[]) if c.get('type')=='output_text')
        result=json.loads(text)
        for role in ['source','destination']:
            ob=result[role]
            if not ob['visible']:raise RuntimeError('Semantic evidence unavailable: '+role)
            b=np.asarray(ob['bbox'],float)
            if ob['camera'] not in views or b.shape!=(4,) or not np.isfinite(b).all() or (b<0).any() or (b>384).any() or b[2]<=b[0] or b[3]<=b[1]:raise ValueError('Invalid semantic bounding box')
        self.identity=result;dump(p/'objects.json',result);return result
    def measure(self,view,bbox,label,reason):
        self.refreshes+=1;p=self.rec.folder/f'mask-{self.refreshes}';p.mkdir();image=p/'rgb.png';cv2.imwrite(str(image),cv2.cvtColor(view['rgb'],cv2.COLOR_RGB2BGR));np.save(p/'depth.npy',view['depth']);dump(p/'calibration.json',dict(K=view['K'],T=view['T'],reason=reason))
        req=dict(image=str(image),boxes=[dict(label=label,bbox=bbox)],output=str(p/'segmentation'))
        self.worker.stdin.write(json.dumps(req)+'\n');self.worker.stdin.flush();r=self.receive()
        if len(r['objects'])!=1:raise RuntimeError('Object segmentation missing')
        mask=np.load(r['objects'][0]['mask_path']);d=view['depth'];K=view['K'];T=view['T'];vv,uu=np.indices(d.shape)
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

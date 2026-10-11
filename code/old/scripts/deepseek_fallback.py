"""Bounded visual-only fallback: no action, stage, direction or truth access."""
import base64
import io
import json
import urllib.request
from pathlib import Path
from PIL import Image


class DeepSeekFallback:
    def __init__(self,cfg,folder):
        self.cfg=cfg; self.folder=Path(folder); self.calls=0; self.limit=cfg.get('deepseek_max_calls',3)
    def __call__(self,prompt,observation,reason):
        if self.calls>=self.limit: raise RuntimeError('DeepSeek fallback call budget exhausted')
        self.calls+=1; folder=self.folder/f'deepseek-{self.calls:03d}'; folder.mkdir()
        content=[dict(type='text',text=prompt+'\nPublic instruction: '+str(observation.get('instruction',''))+
            '\nOnly report visible facts. No robot actions or hidden geometry. Return JSON.')]
        for name,view in observation['cameras'].items():
            b=io.BytesIO(); Image.fromarray(view['rgb']).save(b,format='JPEG',quality=90)
            content.extend([dict(type='text',text='Camera '+name),dict(type='image_url',image_url=dict(url='data:image/jpeg;base64,'+base64.b64encode(b.getvalue()).decode()))])
        payload=dict(model='deepseek-flash',messages=[dict(role='user',content=content)],
            max_tokens=3000,response_format=dict(type='json_object'),thinking=dict(type='disabled'),stream=False)
        (folder/'request.json').write_text(json.dumps(dict(reason=reason,payload=payload)))
        key=Path(self.cfg['deepseek_key_file']).read_text().strip()
        req=urllib.request.Request('https://api.deepseek.com/chat/completions',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=90) as response: result=json.load(response)
        except Exception as exc:
            (folder/'error.json').write_text(json.dumps(dict(type=type(exc).__name__,message=str(exc).replace(key,'[redacted]')))); raise
        (folder/'response.json').write_text(json.dumps(result))
        choice=result['choices'][0]
        if choice['finish_reason']!='stop': raise RuntimeError('Incomplete DeepSeek visual response')
        return json.loads(choice['message']['content'])

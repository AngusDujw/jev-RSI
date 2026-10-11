"""Frozen Markdown memory, stage retrieval and auditable bounded parameters."""
import hashlib,json,re
from pathlib import Path

class Experience:
    def __init__(self,root,run):
        self.records=[]; self.run=Path(run)
        for folder in ('global','tasks'):
            for p in sorted((Path(root)/folder).glob('*.md')):
                text=p.read_text(); match=re.search(r'```json\s*(.*?)\s*```',text,re.S)
                if not match: raise ValueError('Missing memory metadata: '+str(p))
                meta=json.loads(match[1])
                if meta['status']!='active': continue
                self.records.append(dict(**meta,sha256=hashlib.sha256(text.encode()).hexdigest(),path=str(p),content=text))
        (self.run/'experience_snapshot.json').write_text(json.dumps(self.records,ensure_ascii=False,indent=2))
    def retrieve(self,stage):
        return [r for r in self.records if stage in r['stages'] and 'pick_lift' in r['kinds']][:3]
    def parameters(self):
        rows=[r for r in self.records if r['id']=='pick_lift']
        if len(rows)!=1:raise ValueError('Exactly one pickup recipe required')
        p=rows[0]['parameters']
        for key,lo,hi in [('anchor_offset_m',0,.01),('approach_clearance_m',.02,.10),('retry_depth_m',0,.01),('retry_count',0,1)]:
            if not lo<=p[key]<=hi:raise ValueError('Memory parameter outside validated bounds: '+key)
        return p
    def save_step(self,stage,loaded,result):
        row=dict(stage=stage,memory_ids=[r['id'] for r in loaded],hashes=[r['sha256'] for r in loaded],outcome=result['reason'])
        with (self.run/'experience_usage.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
        with (self.run/'episode_notes.md').open('a') as f:f.write(f"- {stage}: {result['reason']}；memory={row['memory_ids']}\n")

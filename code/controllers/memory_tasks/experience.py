"""Task-independent immutable Markdown loading; empty means genuinely no history."""
import hashlib,json,re
from pathlib import Path

class Experience:
    def __init__(self,root,run,task,enabled):
        self.run=Path(run);self.records=[];self.task=task;self.enabled=bool(enabled)
        if self.enabled:
            files=sorted(Path(root).glob('*.md'))+sorted((Path(root).parent/'global').glob('*.md'))
            for path in files:
                text=path.read_text();match=re.search(r'```json\s*(.*?)\s*```',text,re.S)
                if not match:raise ValueError('No memory metadata')
                meta=json.loads(match[1])
                applicable=task in meta.get('tasks',[]) or path.parent.name=='global'
                if meta['status']=='active' and applicable:
                    self.records.append(dict(**meta,content=text,sha256=hashlib.sha256(text.encode()).hexdigest()))
        (self.run/'experience_snapshot.json').write_text(json.dumps(dict(enabled=self.enabled,task=task,records=self.records),ensure_ascii=False,indent=2))
    def retrieve(self,stage):return [r for r in self.records if stage in r['stages']][:3]
    def rules(self):
        out={}
        for row in self.records:out.update(row.get('rules',{}))
        return out
    def record(self,state,used):
        with (self.run/'experience_usage.jsonl').open('a') as f:f.write(json.dumps(dict(stage=state['stage'],memory_ids=[r['id'] for r in used],enabled=self.enabled))+'\n')

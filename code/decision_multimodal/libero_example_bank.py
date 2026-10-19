"""Share fixed, actual demonstration inputs once; never archive rollout images."""
import argparse
import base64
import hashlib
import json
from pathlib import Path


def load_bank(path,task,variant='all_examples'):
    bank=json.loads(path.read_text());rows=bank['tasks'][str(task)]
    if variant in ('task_only','task_native_frame'):rows=rows[12:]
    elif variant=='motion_only':rows=rows[:12]
    parts=[]
    for row in rows:
        if row['type']=='input_text':parts.append(row)
        else:
            raw=(path.parent/row['file']).read_bytes()
            assert hashlib.sha256(raw).hexdigest()==row['sha256']
            parts.append(dict(type='input_image',detail='high',image_url='data:image/png;base64,'+base64.b64encode(raw).decode()))
    return parts


def main():
    p=argparse.ArgumentParser();p.add_argument('--knob-request',type=Path,required=True)
    p.add_argument('--bottle-request',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);tasks={}
    for task,path in ((1383,a.knob_request),(1458,a.bottle_request)):
        content=json.loads(path.read_text())['input'][0]['content'];rows=[]
        for part in content[1:]:
            if part['type']=='input_text' and part['text'].startswith('{'):break
            if part['type']=='input_text':rows.append(part)
            else:
                raw=base64.b64decode(part['image_url'].split(',',1)[1]);h=hashlib.sha256(raw).hexdigest()
                file=h+'.png';dest=a.output/file
                if not dest.exists():dest.write_bytes(raw)
                rows.append(dict(type='input_image',file=file,sha256=h))
        assert sum(r['type']=='input_image' for r in rows)>=10
        tasks[str(task)]=rows
    (a.output/'bank.json').write_text(json.dumps(dict(tasks=tasks,source='Archived actual native demonstration inputs only; no current target/error/evaluator fields.'),indent=2)+'\n')
    print(json.dumps(dict(shared_files=len(list(a.output.glob('*.png'))),bytes=sum(p.stat().st_size for p in a.output.iterdir()))))


if __name__=='__main__':main()

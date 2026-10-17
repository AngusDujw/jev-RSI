"""Fetch official layout files for native evaluation; never model inputs."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--tasks',nargs='+',default=['stack_blocks','classify_objects'])
    parser.add_argument('--count',type=int,default=5)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    def fetch(case):
        task,layout=case
        filename=f'{task}_{layout}.json'
        path=args.output/filename
        url='https://huggingface.co/datasets/RoboDojo-Benchmark/RoboDojo/resolve/main/Assets/Eval_Layout/RoboDojo/arx_x5/0/'+filename
        if path.exists():
            body=path.read_bytes()
        else:
            with urllib.request.urlopen(url,timeout=60) as response:
                body=response.read()
            json.loads(body)
            temp=path.with_suffix('.download')
            temp.write_bytes(body)
            temp.replace(path)
        return dict(task=task,layout_id=layout,eval_seed=0,path=str(path.resolve()),url=url,
                    sha256=hashlib.sha256(body).hexdigest(),bytes=len(body))
    cases=[(task,layout) for task in args.tasks for layout in range(args.count)]
    with ThreadPoolExecutor(max_workers=5) as pool:
        entries=list(pool.map(fetch,cases))
    manifest=dict(source='Official RoboDojo assets repository, as specified by scripts/init_assets.sh',
                  layout_contents_are_not_model_inputs=True,entries=entries)
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(dict(files=len(entries),total_bytes=sum(e['bytes'] for e in entries),manifest=str(args.output/'manifest.json'))))


if __name__=='__main__':
    main()

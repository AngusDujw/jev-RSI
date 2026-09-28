"""Fresh native stack episodes with frozen config; no rollback or silent retries."""
import argparse
import json
from pathlib import Path
import subprocess
import time


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--config',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--count',type=int,default=20)
    p.add_argument('--start',type=int,default=0)
    a=p.parse_args()
    root=Path(a.output).resolve(); root.mkdir(parents=True,exist_ok=True)
    cfg=json.loads(Path(a.config).read_text())
    failures=0
    for index in range(a.start,a.start+a.count):
        if (root/'STOP').exists(): break
        folder=root/f'episode-{index:03d}'
        if folder.exists(): raise RuntimeError(f'Refusing overwrite: {folder}')
        case=dict(cfg,robodojo_layout_id=index%2)
        config=root/f'config-{index:03d}.json'
        with config.open('x') as stream: json.dump(case,stream,indent=2)
        command=[cfg['robodojo_python'],'-B','-u','code/scripts/run_position_pilot.py',
                 '--config',str(config),'--output',str(folder),'--backend','robodojo','--with-jev']
        start=time.time()
        with (root/f'episode-{index:03d}.log').open('x') as log:
            result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
        stack=json.loads((folder/'stack_result.json').read_text()) if (folder/'stack_result.json').exists() else {}
        success=stack.get('native',{}).get('success',False)
        failures=0 if success else failures+1
        row=dict(index=index,layout_id=index%2,returncode=result.returncode,success=success,
                 started=start,finished=time.time(),stack=stack,consecutive_failures=failures)
        with (root/'batch.jsonl').open('a') as stream: stream.write(json.dumps(row)+'\n')
        print(json.dumps(row),flush=True)
        if failures>=3:
            (root/'STOP').write_text('Three consecutive task failures; user escalation required.\n')
            break
    (root/'finished.json').write_text(json.dumps(dict(finished=time.time(),consecutive_failures=failures)))


if __name__=='__main__': main()

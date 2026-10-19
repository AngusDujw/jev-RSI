"""Launch and verify two native tmux windows and a durable local Decisions bridge."""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

REMOTE='/root/yekangjie/project/jev_rsi/.worktrees/decision-multimodal-20261016'
HOST='company-server-2'


def remote(code):
    return subprocess.check_output(['ssh','--',HOST,'python3 -c '+shlex.quote(code)],text=True)


def worker(config_path):
    config=json.loads(config_path.read_text());output=config_path.parent
    deadline=time.monotonic()+3600
    while time.monotonic()<deadline:
        with (output/'bridge.log').open('a') as log:
            command=[sys.executable,'-B','code/decision_multimodal/decision_file_bridge.py',
                '--host',HOST,'--remote-roots',*config['remote_roots'],
                '--key-file','.private/du-openai-direct.key','--output',str(output/'bridge'),
                '--resume','--seconds',str(max(1,int(deadline-time.monotonic()))),
                '--control-path','code/runs/'+config['session']+'.sock']
            (output/'worker.json').write_text(json.dumps(dict(time=time.time(),status='running',command=command)))
            code=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT).returncode
        if code==0:
            (output/'worker.json').write_text(json.dumps(dict(time=time.time(),status='batch_finished',returncode=code)))
            return
        (output/'worker.json').write_text(json.dumps(dict(time=time.time(),status='restarting_bridge',returncode=code)))
        time.sleep(2)
    raise TimeoutError('Managed bridge wall budget reached; artifacts retained')


def main():
    p=argparse.ArgumentParser();p.add_argument('--run-id',default='v6r2')
    p.add_argument('--bridge-worker',type=Path)
    a=p.parse_args()
    if a.bridge_worker:return worker(a.bridge_worker.resolve())
    if not re.fullmatch('[a-z0-9-]{1,24}',a.run_id):raise ValueError('Invalid run identifier')
    root=Path(__file__).resolve().parents[2]
    session='dm-20261019-'+a.run_id
    output=root/'code/runs/2026-10-19-direct-axes-preparation'/('managed-'+a.run_id)
    if output.exists():raise FileExistsError('Run output already exists; inspect the recorded sessions instead')
    output.mkdir()
    roots=[];windows=[]
    for task,init,gpu,label,plan,example in (
        (1383,8,4,'knob','knob-plan-v2.json','task-1383-init-10'),
        (1458,11,5,'bottle','bottle-plan-v4.json','task-1458-init-11')):
        destination=REMOTE+'/code/runs/2026-10-19-direct-axes-'+label+'-'+a.run_id+'-init'+str(init)
        roots.append(destination)
        log=REMOTE+'/code/runs/2026-10-19-direct-axes-preparation/'+label+'-'+a.run_id+'-launcher.log'
        command=['env','DECISION_MM_KEY_FILE='+REMOTE+'/.private/du-openai-direct.key',
            'DECISION_MM_PROXY=http://127.0.0.1:7897','OMP_NUM_THREADS=2','OPENBLAS_NUM_THREADS=2',
            '/root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python','-B',
            'code/decision_multimodal/libero_direct_axes.py','--task',str(task),'--init',str(init),'--gpu',str(gpu),
            '--grounded','--relation-prompts','--surface-context','--coordinate-questions',
            '--positive-frame','--adaptive-steps','--file-transport',
            '--task-demo','code/runs/2026-10-18-libero-rotation-dials-v3/'+example+'/episode',
            '--plan','code/runs/2026-10-19-direct-axes-preparation/'+plan,
            '--demos','code/runs/2026-10-17-libero-six-axis-motion-v2',
            '--libero-root','/root/yekangjie/project/embodied-jev/.sim/LIBERO-plus',
            '--output',destination]
        windows.append(dict(name=label,command='exec '+shlex.join(command)+' > '+shlex.quote(log)+' 2>&1'))
    config=dict(session=session,host=HOST,remote_project=REMOTE,remote_roots=roots,windows=windows)
    path=output/'launcher.json';path.write_text(json.dumps(config,indent=2)+'\n')
    code=('import pathlib,shutil,subprocess; root='+repr(REMOTE)+'; session='+repr(session)+'; '
        'windows='+repr(windows)+'; roots='+repr(roots)+'; '
        'assert shutil.disk_usage(root).free>10*1024**3,"Storage guard"; '
        'assert all(not pathlib.Path(p).exists() for p in roots),"Native output exists"; '
        'assert subprocess.run(["tmux","has-session","-t",session],capture_output=True).returncode!=0,"Session exists"; '
        'subprocess.run(["tmux","new-session","-d","-s",session,"-n",windows[0]["name"],"-c",root,windows[0]["command"]],check=True); '
        'subprocess.run(["tmux","set-option","-t",session,"remain-on-exit","on"],check=True); '
        'subprocess.run(["tmux","new-window","-t",session,"-n",windows[1]["name"],"-c",root,windows[1]["command"]],check=True); '
        'print(subprocess.check_output(["tmux","list-panes","-s","-t",session,"-F","#{window_name}:#{pane_dead}:#{pane_pid}"],text=True))')
    print(remote(code),flush=True)
    bridge='exec '+shlex.join([sys.executable,'-B',str(Path(__file__).resolve()),'--bridge-worker',str(path)])
    subprocess.run(['tmux','new-session','-d','-s',session,'-n','bridge','-c',str(root),bridge],check=True)
    subprocess.run(['tmux','set-option','-t',session,'remain-on-exit','on'],check=True)
    print(subprocess.check_output(['tmux','list-panes','-s','-t',session,'-F','#{window_name}:#{pane_dead}:#{pane_pid}'],text=True),flush=True)
    print(json.dumps(dict(launched=session,config=str(path))),flush=True)


if __name__=='__main__':main()

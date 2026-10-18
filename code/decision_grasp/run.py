"""Foreground native Decisions grasp pilots, independent of the Pro comparison."""
import argparse
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time

PROJECT=Path(__file__).resolve().parents[2]
CAMPAIGN='/home/user/ykj/project/gpt6/jev-RSI/code/runs/server02-decision-grasp-20261019'
ROOT=Path('/home/ykj/project/gpt6/benchmark/gpt_as_policy_robodojo/runs/server02-decision-grasp-20261019')
RUNTIME=PROJECT/'code/runs/server02-policy-comparison-20261018/official_runtime'
PYTHON=Path('/home/ykj/project/gpt6/benchmark/gpt_as_policy_robodojo/.venv/bin/python')
SSH=['ssh','-F','/dev/null','-S','/home/ykj/.ssh/s2-policy-20261018.ctl','--','server02']
STOP=False


def save(path,value):path.write_text(json.dumps(value,indent=2)+'\n')


def remote(argv,**kwargs):
    return subprocess.run(SSH+[shlex.join(argv)],check=True,capture_output=True,text=True,**kwargs)


def admission(gpu):
    code="""import subprocess,sys
gpu=sys.argv[1]
containers=subprocess.check_output(['docker','ps','--format','{{.Names}}'],text=True).split()
owned=[x for x in containers if x.startswith(('policy-20261018-','grasp-20261019-'))]
if len(owned)>=3:raise RuntimeError('At most three total own simulator environments')
known={int(subprocess.check_output(['docker','inspect','--format','{{.State.Pid}}',x],text=True)) for x in owned}
raw=subprocess.check_output(['nvidia-smi','--id='+gpu,'--query-compute-apps=pid','--format=csv,noheader,nounits'],text=True)
if {int(x.strip()) for x in raw.splitlines() if x.strip().isdigit()}-known:raise RuntimeError('Foreign GPU occupant')
free=int(subprocess.check_output(['nvidia-smi','--id='+gpu,'--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True))
mem={x.split(':')[0]:int(x.split()[1]) for x in open('/proc/meminfo')}
if free<8192 or mem['MemAvailable']<20*1024**2:raise RuntimeError('Need 8GiB GPU and 20GiB available host RAM before startup')
print('admitted')
"""
    return remote(['python3','-c',code,str(gpu)],timeout=30)


def one(layout,gpu):
    name=f'rgb-v1-general_pickup-layout{layout}'
    run=ROOT/name
    if run.exists():raise FileExistsError('Never resume or overwrite '+name)
    admission(gpu)
    run.mkdir()
    port=24500+layout
    state=dict(condition='generic-current-rgb-v1',task='general_pickup',layout=layout,
        gpu=gpu,port=port,status='starting',endpoint='https://api.openai.com/v1/decisions')
    save(run/'status.json',state)
    sim=controller=None
    try:
        subprocess.run(SSH[:-2]+['-O','forward','-L',f'127.0.0.1:{port}:127.0.0.1:{port}','--','server02'],check=True,capture_output=True)
        with (run/'server.log').open('w') as server_log, (run/'controller.log').open('w') as controller_log:
            sim=subprocess.Popen(SSH+[shlex.join(['bash',CAMPAIGN+'/launch_server.sh',str(gpu),
                'general_pickup',CAMPAIGN+'/'+name,str(port)])],stdout=server_log,stderr=subprocess.STDOUT)
            state['ssh_pid']=sim.pid;save(run/'status.json',state)
            deadline=time.monotonic()+600
            while True:
                if STOP:raise KeyboardInterrupt('User interruption')
                if sim.poll() is not None:raise RuntimeError('Native startup failed')
                if '"event": "ready"' in (run/'server.log').read_text(errors='replace'):break
                if time.monotonic()>deadline:raise TimeoutError('Native server ready timeout')
                time.sleep(3)
            env=os.environ.copy()
            for key in list(env):
                if key.startswith(('OPENAI_','CODEX_API_')):env.pop(key)
            env.update(PYTHONPATH=str(RUNTIME),TMPDIR=str(run/'tmp'))
            (run/'tmp').mkdir()
            controller=subprocess.Popen([str(PYTHON),'-u',str(Path(__file__).with_name('controller.py')),
                '--output',str(run/'controller'),'--sim-port',str(port),'--seed',str(layout)],
                env=env,stdout=controller_log,stderr=subprocess.STDOUT)
            state.update(status='running',controller_pid=controller.pid);save(run/'status.json',state)
            while controller.poll() is None:
                if STOP:raise KeyboardInterrupt('User interruption')
                progress=run/'controller/progress.json'
                try:state.update(progress=json.loads(progress.read_text()))
                except (OSError,ValueError):pass
                save(run/'status.json',state)
                time.sleep(3)
            state.update(controller_exit=controller.returncode)
            try:sim.wait(timeout=30)
            except subprocess.TimeoutExpired:
                remote(['docker','stop','-t','10',f'grasp-20261019-general_pickup-{port}'],timeout=30)
                sim.wait(timeout=30)
            state['status']='finished'
    except BaseException as error:
        state.update(status='failed',error_type=type(error).__name__,error=str(error))
    finally:
        if controller and controller.poll() is None:
            controller.terminate();controller.wait(timeout=20)
        if sim and sim.poll() is None:
            remote(['docker','stop','-t','10',f'grasp-20261019-general_pickup-{port}'],timeout=30)
            sim.wait(timeout=30)
        subprocess.run(SSH[:-2]+['-O','cancel','-L',f'127.0.0.1:{port}:127.0.0.1:{port}','--','server02'],capture_output=True)
        for label,filename in (('native','sim/evaluation_outcome.json'),('failure','controller/failure.json')):
            if (run/filename).exists():state[label]=json.loads((run/filename).read_text())
        save(run/'status.json',state)
    print(json.dumps(state),flush=True)
    return state


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--layouts',type=int,nargs='+',default=[0,1,2])
    parser.add_argument('--gpu',type=int,choices=(0,1),default=0)
    args=parser.parse_args()
    def stop(*_):
        global STOP
        STOP=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    if not ROOT.is_mount():raise RuntimeError('Expected remote artifact mount')
    rows=[]
    for layout in args.layouts:
        if STOP:break
        row=one(layout,args.gpu);rows.append(row);save(ROOT/'pilot-v1.json',rows)
        if row.get('controller_exit')!=0:break


if __name__=='__main__':main()

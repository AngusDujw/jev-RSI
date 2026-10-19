"""Foreground, observable official-policy trials; no replay of an existing run."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import threading
import time

from prepare import PROJECT, ROOT, PYTHON

REMOTE = '/home/user/ykj/project/gpt6/jev-RSI/code/runs/server02-policy-comparison-20261018'
LOCK = threading.Lock()
STARTUP = threading.Semaphore(1)
STOP = threading.Event()
ARTIFACT_ROOT = Path('/home/ykj/project/gpt6/benchmark/gpt_as_policy_robodojo/runs/server02-policy-comparison-20261018')
SSH = ['ssh', '-F', '/dev/null', '-S', '/home/ykj/.ssh/s2-grasp-20261019.ctl',
       '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15']


def save(path, value):
    with LOCK:
        path.write_text(json.dumps(value, indent=2) + '\n')


def run_one(task, layout, ordinal, mode, trial, recovery=None):
    name = f'{mode}-{task}-trial{trial}-layout{layout}'
    if recovery:name += '-'+recovery
    run = ARTIFACT_ROOT / name
    if run.exists():
        raise FileExistsError('Never replay an existing trial: ' + str(run))
    run.mkdir()
    gpu = ordinal % 2
    port = 24300 + ordinal + (100 if mode == 'decisions' else 0) + (500 if recovery else 0)
    remote = REMOTE + '/' + name
    command = ['bash', REMOTE + '/launch_server.sh', str(gpu), task, remote, str(port)]
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(('OPENAI_', 'CODEX_API_')):
            env.pop(key)
    env.update(CODEX_HOME=str(PROJECT / '.private/server02-policy-pro-20261018' / f'{task}-{layout}'),
        ROLLOUT_AUTH_PROFILE='codex_a', ROLLOUT_EVALUATION_METHOD='gpt_only',
        ROLLOUT_CODEX_STATE_DIR=str(ROOT / 'local_state' / name),
        PYTHONPATH=str(ROOT / 'official_runtime'), TMPDIR=str(run / 'tmp'))
    (run / 'tmp').mkdir()
    sim = controller = None
    state = dict(task=task, layout=layout, mode=mode, gpu=gpu, port=port,
                 remote=remote, status='starting', native_episode_started=False)
    save(run / 'status.json', state)
    try:
        if mode=='luna' and recovery:
            check=subprocess.run([str(PYTHON),'-u',str(Path(__file__).with_name('preflight_pro.py')),
                '--output',str(run/'preflight')],env=env,capture_output=True,text=True,timeout=180)
            (run/'preflight-host.log').write_text(check.stdout+check.stderr)
            if check.returncode:raise RuntimeError('Pro preflight failed: '+check.stderr[-1500:])
        with (run / 'server.log').open('w') as slog, (run / 'controller.log').open('w') as clog:
            with STARTUP:
                # Ports are reserved for this trial; do not reuse an external listener.
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1', port))
                admission = subprocess.run(SSH + ['--', 'server02',
                    f'nvidia-smi --id={gpu} --query-gpu=memory.free --format=csv,noheader,nounits'],
                    check=True, capture_output=True, text=True)
                if int(admission.stdout.strip()) < 8192:
                    raise RuntimeError('Less than 8GiB free before simulator start')
                inventory_code = """import subprocess,sys
gpu=sys.argv[1]
containers=subprocess.check_output(['docker','ps','--format','{{.Names}}'],text=True).split()
containers=[x for x in containers if x.startswith(('policy-20261018-','grasp-20261019-'))]
known=set()
for container in containers:
    known.add(int(subprocess.check_output(['docker','inspect','--format','{{.State.Pid}}',container],text=True).strip()))
raw=subprocess.check_output(['nvidia-smi','--id='+gpu,'--query-compute-apps=pid','--format=csv,noheader,nounits'],text=True)
occupants={int(x.strip()) for x in raw.splitlines() if x.strip().isdigit()}
if occupants-known: raise RuntimeError('Foreign GPU occupant; refusing to share')
mem={x.split(':')[0]:int(x.split()[1]) for x in open('/proc/meminfo')}
if len(containers)>=3 or mem['MemAvailable']<20*1024**2: raise RuntimeError('WAIT_RESOURCE')
"""
                while True:
                    check=subprocess.run(SSH+['--','server02',shlex.join(['python3','-c',inventory_code,str(gpu)])],capture_output=True,text=True)
                    if check.returncode==0:break
                    if 'WAIT_RESOURCE' not in check.stderr:raise RuntimeError(check.stderr[-1000:])
                    state['status']='waiting_for_resources';save(run/'status.json',state)
                    if STOP.is_set():raise KeyboardInterrupt('Batch cancellation')
                    time.sleep(15)
                subprocess.run(SSH + ['-O','forward','-L',f'127.0.0.1:{port}:127.0.0.1:{port}',
                    '--','server02'],check=True,capture_output=True)
                sim = subprocess.Popen(SSH + ['--', 'server02', shlex.join(command)],
                    stdin=subprocess.DEVNULL, stdout=slog, stderr=subprocess.STDOUT)
                state['ssh_pid'] = sim.pid
                save(run / 'status.json', state)
                deadline = time.monotonic() + 600
                # The official server accepts one owner only. Never consume that
                # connection for a readiness probe: wait for its ready log event.
                while time.monotonic() < deadline:
                    if STOP.is_set():
                        raise KeyboardInterrupt('User interrupted the campaign')
                    if sim.poll() is not None:
                        raise RuntimeError('Simulator startup failed: ' + str(sim.returncode))
                    log_text = (run / 'server.log').read_text(errors='replace')
                    if '"event": "ready"' in log_text:
                        break
                    time.sleep(3)
                else:
                    raise TimeoutError('Simulator did not become ready')
            if mode == 'luna':
                argv = [str(PYTHON), '-u', '-m', 'hybrid_rollout.robodojo.skill.run',
                    '--output', str(run / 'controller'), '--task', task,
                    '--evaluation-method', 'gpt_only', '--codex', shutil.which('codex'),
                    '--sim-port', str(port), '--seed', str(layout), '--max-decisions', '0']
            else:
                entry='decisions_comparison_completion.py' if recovery else 'decisions_policy.py'
                argv = [str(PYTHON), '-u', str(Path(__file__).with_name(entry)),
                    '--output', str(run / 'controller'), '--task', task,
                    '--sim-port', str(port), '--seed', str(layout)]
            controller = subprocess.Popen(argv, cwd=ROOT / 'official_runtime', env=env,
                                          stdout=clog, stderr=subprocess.STDOUT)
            state.update(status='running', controller_pid=controller.pid)
            save(run / 'status.json', state)
            while controller.poll() is None:
                if STOP.is_set():
                    raise KeyboardInterrupt('User interrupted the campaign')
                history = run / 'controller/history.json'
                try:
                    records = json.loads(history.read_text())
                    state.update(decisions=len(records),
                        native_steps=records[-1]['end_tick'] if records else 0)
                    state['native_episode_started'] = (run / 'controller/run.json').exists()
                except (OSError, ValueError, KeyError):
                    pass
                save(run / 'status.json', state)
                time.sleep(10)
            state.update(controller_exit=controller.returncode, status='controller_finished')
            save(run / 'status.json', state)
            # Native tool host closes the RPC after terminal; allow recorder flush.
            try:
                sim.wait(timeout=90)
            except subprocess.TimeoutExpired:
                subprocess.run(SSH + ['--', 'server02',
                    shlex.join(['docker', 'stop', '-t', '15', f'policy-20261018-{task}-{port}'])],
                    stdout=slog, stderr=subprocess.STDOUT, timeout=45)
                sim.wait(timeout=30)
    except BaseException as exc:
        state.update(status='failed', error_type=type(exc).__name__, error=str(exc))
    finally:
        if controller and controller.poll() is None:
            controller.terminate()
            controller.wait(timeout=20)
        if sim and sim.poll() is None:
            subprocess.run(SSH + ['--', 'server02',
                shlex.join(['docker', 'stop', '-t', '15', f'policy-20261018-{task}-{port}'])],
                capture_output=True, timeout=45)
            sim.terminate()
            sim.wait(timeout=20)
        # The FUSE-backed run directory is already the remote artifact directory.
        subprocess.run(SSH + ['-O','cancel','-L',f'127.0.0.1:{port}:127.0.0.1:{port}',
            '--','server02'],capture_output=True)
        native = run / 'sim/evaluation_outcome.json'
        if native.exists():
            state['native'] = json.loads(native.read_text())
        save(run / 'status.json', state)
    print(json.dumps(state), flush=True)
    return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['luna', 'decisions', 'all'], required=True)
    parser.add_argument('--parallel', type=int, default=2)
    args = parser.parse_args()
    import sys
    sys.path.insert(0, str(ROOT / 'official_runtime'))
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    if not ARTIFACT_ROOT.is_mount():
        raise RuntimeError('Remote artifact mount is required; never fill the local disk')
    for mode in (['luna','decisions'] if args.mode == 'all' else [args.mode]):
        if STOP.is_set():
            break
        if mode == 'decisions':
            baseline = ROOT / 'luna_native_trials.json'
            if not baseline.exists() or len(json.loads(baseline.read_text())) != 6:
                raise RuntimeError('All six Luna trials must finish first')
            for row in json.loads(baseline.read_text()):
                if not (ARTIFACT_ROOT / Path(row['remote']).name / 'controller/run.json').exists():
                    raise RuntimeError('Baseline setup failed before observations; do not start Decisions')
        layouts = [0,1,0] if mode == 'luna' else [0,1,0,1,0]
        rows = []
        def queue(task, gpu):
            for trial, layout in enumerate(layouts,1):
                if STOP.is_set():
                    return
                ordinal = (trial-1)*2+gpu
                row = run_one(task,layout,ordinal,mode,trial)
                rows.append(row)
                save(ROOT / f'{mode}_native_trials.json',rows)
                save(ARTIFACT_ROOT / f'{mode}_native_trials.json',rows)
                if not (ARTIFACT_ROOT / Path(row['remote']).name / 'controller/run.json').exists():
                    STOP.set()
                    raise RuntimeError('Setup failed before first observation; stop further trials for diagnosis')
        with ThreadPoolExecutor(max_workers=min(args.parallel,2)) as pool:
            futures = [pool.submit(queue,task,gpu) for gpu,task in enumerate(('stack_blocks','classify_objects'))]
            for future in as_completed(futures):
                future.result()


if __name__ == '__main__':
    main()

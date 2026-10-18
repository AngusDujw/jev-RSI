"""Foreground, observable official-policy trials; no replay of an existing run."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import threading
import time

from prepare import PROJECT, ROOT, PYTHON

REMOTE = '/home/user/ykj/project/gpt6/jev-RSI/code/runs/server02-policy-comparison-20261018'
LOCK = threading.Lock()
STARTUP = threading.Semaphore(6)
SSH = ['ssh', '-F', '/dev/null', '-S', '/home/ykj/.ssh/s2-policy-20261018.ctl',
       '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15']


def save(path, value):
    with LOCK:
        path.write_text(json.dumps(value, indent=2) + '\n')


def run_one(task, layout, ordinal, mode):
    name = f'{mode}-{task}-layout{layout}'
    run = ROOT / 'remote_assets' / name
    if run.exists():
        raise FileExistsError('Never replay an existing trial: ' + str(run))
    run.mkdir()
    gpu = ordinal % 2
    port = 24300 + ordinal + (100 if mode == 'decisions' else 0)
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
containers=subprocess.check_output(['docker','ps','--filter','name=policy-20261018-','--format','{{.ID}}'],text=True).split()
known=set()
for container in containers:
    known.add(int(subprocess.check_output(['docker','inspect','--format','{{.State.Pid}}',container],text=True).strip()))
raw=subprocess.check_output(['nvidia-smi','--id='+gpu,'--query-compute-apps=pid','--format=csv,noheader,nounits'],text=True)
occupants={int(x.strip()) for x in raw.splitlines() if x.strip().isdigit()}
if occupants-known: raise RuntimeError('Foreign GPU occupant; refusing to share')
if len(occupants)>=3: raise RuntimeError('Three own workers already occupy this GPU')
"""
                subprocess.run(SSH + ['--','server02',shlex.join(['python3','-c',inventory_code,str(gpu)])],
                               check=True,capture_output=True)
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
                argv = [str(PYTHON), '-u', str(Path(__file__).with_name('decisions_policy.py')),
                    '--output', str(run / 'controller'), '--task', task,
                    '--sim-port', str(port), '--seed', str(layout)]
            controller = subprocess.Popen(argv, cwd=ROOT / 'official_runtime', env=env,
                                          stdout=clog, stderr=subprocess.STDOUT)
            state.update(status='running', controller_pid=controller.pid)
            save(run / 'status.json', state)
            while controller.poll() is None:
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
    parser.add_argument('--mode', choices=['luna', 'decisions'], required=True)
    parser.add_argument('--parallel', type=int, default=6)
    args = parser.parse_args()
    import sys
    sys.path.insert(0, str(ROOT / 'official_runtime'))
    if args.mode == 'decisions':
        baseline = ROOT / 'luna_batch_results.json'
        if not baseline.exists() or len(json.loads(baseline.read_text())) != 6:
            raise RuntimeError('All six Luna attempts must finish first')
    count = 3 if args.mode == 'luna' else 5
    items = [(task, layout) for layout in range(count)
             for task in ('stack_blocks', 'classify_objects')]
    rows = []
    with ThreadPoolExecutor(max_workers=min(args.parallel, 6)) as pool:
        futures = [pool.submit(run_one, task, layout, i, args.mode)
                   for i, (task, layout) in enumerate(items)]
        for future in as_completed(futures):
            rows.append(future.result())
            save(ROOT / f'{args.mode}_batch_results.json', rows)


if __name__ == '__main__':
    main()

"""Run the six user-authorized paired bowl episodes without automatic reruns."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
GUIDANCE = (
    'Complete the task as quickly as possible, using as few control steps as necessary. '
    'After the object-level goal, release, safely retract and return, reserving steps for this finish.'
)
CONDITIONS = {'fast_h5': (5, True), 'default_h1': (1, False), 'fast_h1': (1, True)}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def results(folder):
    records = []
    for path in folder.glob('*/result.json'):
        records.append({'path': str(path), 'result': json.loads(path.read_text())})
    native = []
    for path in folder.rglob('*_result.json'):
        native.append({'path': str(path), 'result': json.loads(path.read_text())})
    return {'runner_results': records, 'native_results': native}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--sim-python', required=True)
    ap.add_argument('--policy-python', required=True)
    ap.add_argument('--parallel', type=int, choices=(1, 2, 3), default=2)
    ap.add_argument('--minimum-free-mib', type=int, required=True)
    ap.add_argument('--endpoint', default='http://127.0.0.1:7915/responses')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--capture-only', action='store_true')
    args = ap.parse_args()
    if args.endpoint != 'http://127.0.0.1:7915/responses':
        raise ValueError('This experiment only uses its local ChatGPT Pro bridge')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    base = json.loads((ROOT/'configs/protocols/zero_shot_b25.json').read_text())
    profiles = {}
    for condition, (horizon, fast) in CONDITIONS.items():
        profile = dict(base, id='bowl-speed-20261023-' + condition,
                       model='gpt-6-astra', endpoint=args.endpoint)
        profile['harness_overrides'] = dict(base['harness_overrides'],
            max_translation_m=.06 if fast else .03,
            max_rotation_rad=.30 if fast else .15,
            completion_efficiency_guidance=GUIDANCE if fast else '')
        path = out/'profiles'/f'{condition}.json'
        if path.exists() and json.loads(path.read_text()) != profile:
            raise ValueError('Existing frozen profile differs: ' + str(path))
        save(path, profile)
        profiles[condition] = path
    protocol = {'date': '2026-10-23', 'task': 'stack_bowls', 'layouts': [0, 1],
        'conditions': CONDITIONS, 'episode_control_step_limit': 800,
        'guidance': GUIDANCE, 'guidance_provenance': 'First sentence requested by user; second from GPT-as-Policy SKILL.md finish-budget guidance.',
        'model': 'gpt-6-astra', 'effort': 'xhigh', 'account': 'workstation ChatGPT Pro',
        'shots': 0, 'seed': 0, 'maximum_physical_attempts': 6,
        'native_outcomes_are_not_rerun': True, 'parallel': args.parallel,
        'sim_python': args.sim_python, 'policy_python': args.policy_python}
    save(out/'protocol.json', protocol)
    jobs = queue.Queue()
    for layout in (0, 1):
        for condition in CONDITIONS:
            jobs.put((condition, layout))
    admission = threading.Lock()

    def worker(slot):
        while True:
            try:
                condition, layout = jobs.get_nowait()
            except queue.Empty:
                return
            horizon, _ = CONDITIONS[condition]
            folder = out/condition/f'layout-{layout}'
            folder.mkdir(parents=True, exist_ok=False)
            env = os.environ.copy()
            for key in ('OPENAI_API_KEY', 'OPENAI_BASE_URL', 'CODEX_API_KEY', 'ASTRA_ENDPOINT'):
                env.pop(key, None)
            env.update(ASTRA_API_KEY='local-chatgpt-placeholder', ROBOICL_REUSE_MODE='pure',
                ROBOICL_PREDICT_HORIZON=str(horizon), ROBOICL_EXECUTE_HORIZON=str(horizon),
                ROBOICL_GPU_SLOTS='3', ROBOICL_NO_MEDIA='1',
                TMPDIR=str(ROOT/'.runtime/tmp'), XDG_CACHE_HOME=str(ROOT/'.runtime/cache'),
                TORCH_EXTENSIONS_DIR=str(ROOT/'.runtime/torch-extensions'),
                CUDA_CACHE_PATH=str(ROOT/'.runtime/cuda-cache'),
                ROBOICL_KIT_PORTABLE_ROOT=str(ROOT/'.runtime'/f'speed-kit-slot{slot}'))
            command = [args.policy_python, '-B', '-m', 'roboicl.run', 'stack_bowls',
                '--shots', '0', '--seed', '0', '--layout', str(layout),
                '--gpu', '0', '--gpu-slot', str(slot), '--port', str(18450+slot),
                '--sim-python', args.sim_python, '--policy-python', args.policy_python,
                '--model', 'gpt-6-astra', '--reasoning-effort', 'xhigh',
                '--action-horizon', str(horizon), '--profile', str(profiles[condition]),
                '--results-root', str(folder)]
            if args.dry_run:
                command.append('--dry-run')
            if args.capture_only:
                command.append('--capture-only')
            case = {'condition': condition, 'layout': layout, 'slot': slot,
                    'command': command, 'started_at': datetime.datetime.now().isoformat()}
            save(folder/'case.json', case)
            # Admission is serialized; the caller chooses concurrency from measured peaks.
            with admission:
                while True:
                    free = int(subprocess.check_output(['nvidia-smi', '--id=0',
                        '--query-gpu=memory.free', '--format=csv,noheader,nounits'], text=True).strip())
                    if args.dry_run or free >= args.minimum_free_mib:
                        break
                    print(json.dumps({'event': 'waiting_for_memory', 'slot': slot,
                                      'free_mib': free}), flush=True)
                    time.sleep(30)
                print(json.dumps({'event': 'start', 'condition': condition, 'layout': layout, 'slot': slot}), flush=True)
                started = time.monotonic()
                log = (folder/'launcher.log').open('w')
                process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
                # Avoid simultaneous Isaac initializations hiding each other's peak.
                if not args.dry_run:
                    while process.poll() is None:
                        ready = list(folder.glob('*/astra/*/observations.jsonl'))
                        ready += list(folder.glob('*/capture_probe.json'))
                        if ready:
                            break
                        time.sleep(2)
            code = process.wait()
            log.close()
            summary = {'returncode': code, 'wall_seconds': time.monotonic()-started, **results(folder)}
            save(folder/'finished.json', summary)
            print(json.dumps({'event': 'end', 'condition': condition, 'layout': layout,
                              'returncode': code, 'wall_seconds': summary['wall_seconds']}), flush=True)

    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = [pool.submit(worker, slot) for slot in range(args.parallel)]
        for future in futures:
            future.result()
    summary = []
    for layout in (0, 1):
        for condition in CONDITIONS:
            folder = out/condition/f'layout-{layout}'
            final = folder/'finished.json'
            summary.append({'condition': condition, 'layout': layout,
                            **(json.loads(final.read_text()) if final.exists() else {'status': 'not_started'})})
    save(out/'summary.json', summary)


if __name__ == '__main__':
    main()

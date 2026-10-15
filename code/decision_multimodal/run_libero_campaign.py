"""Foreground, resumable paired evaluation of unchanged LIBERO policies."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time

GPU_UUIDS = {
    4: 'GPU-24ec90aa-e797-2f51-0a92-2a93b57d419b',
    5: 'GPU-fbd98bc0-7dc5-4d94-44a6-7c9d5b5fce27',
    6: 'GPU-eb04c8a8-bd86-966a-805d-64b75c088fcf',
    7: 'GPU-033adeec-53b6-d417-6fa6-115ae6aeb90d',
}


def now():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def command_for(task, folder, episode, init_index, controller_root):
    original = list(task['argv_template'])
    script = next(i for i, item in enumerate(original)
                  if Path(item).name == 'libero_jev_rollout.py')
    if original[:script] != ['-B']:
        raise ValueError('Unexpected frozen interpreter options')
    arguments = original[script+1:]
    for flag, value in (('--init-index', init_index), ('--output', episode)):
        if arguments.count(flag) != 1:
            raise ValueError('Frozen launch flag missing or duplicated: ' + flag)
        arguments[arguments.index(flag)+1] = str(value)
    return [task['native_python'], '-B', str(Path(__file__).with_name('libero_entry.py')),
            '--policy', str(folder/'libero_jev_rollout.py'),
            '--controller-root', str(controller_root), '--', *arguments]


def verify(folder, task):
    for name, expected in task['source_sha256'].items():
        if Path(name).name != name:
            raise ValueError('Invalid frozen source filename')
        if hashlib.sha256((folder/name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'Frozen policy changed: {folder.name}/{name}')
    if json.loads((folder/'decision-api-config.json').read_text()) != {'jev': {'model': 'gpt-6-luna'}}:
        raise ValueError('Unexpected frozen API configuration')


def classify(directory, returncode, termination):
    path = directory/'episode/result.json'
    result = json.loads(path.read_text()) if path.is_file() else None
    failures = sorted((directory/'episode/decision-api').glob('*/failure.json'))
    answers = len(list((directory/'episode/decision-api').glob('*/response.json')))
    native = result.get('success') if result else None
    program = result.get('program_finished') if result else None
    joint = (native is True and program is True)
    category = ('transport_or_schema_failure' if failures else
                'external_termination' if termination else
                'environment_or_startup_failure' if result is None or (not answers and result.get('error')) else
                'joint_success' if joint else 'task_failure')
    return dict(returncode=returncode, termination=termination, category=category,
                native_success=native, program_finished=program,
                joint_success=joint, native_result=result,
                api_failure_files=[str(p.relative_to(directory)) for p in failures],
                decision_answers=answers)


class Campaign:
    def __init__(self, args):
        self.args = args
        self.root = args.output_root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.children = set()
        self.pending = queue.Queue()
        self.rows = []
        self.claimed = 0
        self.tasks = json.loads((args.baselines/'campaign.json').read_text())['tasks']
        for task in self.tasks:
            verify(args.baselines/f'task-{task["task_id"]}', task)
        specification = dict(phase='1_frozen_text_only', actor_model='gpt-6-luna',
            key_origin='du', actor_images=0, experience_injection=False,
            allowed_physical_gpus=[4, 5, 6, 7],
            expected_episodes=sum(len(t['paired_init_indices']) for t in self.tasks),
            tasks=[{k: t[k] for k in ('task_id', 'source_commit', 'source_sha256',
                'paired_init_indices', 'original_options', 'cpu_vision', 'baseline_status')} for t in self.tasks])
        spec_path = self.root/'campaign.json'
        if spec_path.exists():
            if json.loads(spec_path.read_text()) != specification:
                raise ValueError('Existing campaign has a different frozen specification')
        else:
            write(spec_path, specification)
        # Round robin tasks before their second initial state; no selective reruns.
        for index in range(5):
            for task in self.tasks:
                init = task['paired_init_indices'][index]
                folder = self.root/f'task-{task["task_id"]}-init-{init}'
                if (folder/'outcome.json').is_file():
                    self.rows.append(json.loads((folder/'outcome.json').read_text()))
                elif folder.exists():
                    raise ValueError('Interrupted episode needs explicit inspection: ' + str(folder))
                else:
                    self.pending.put((task, init, folder))

    def ledger(self, event):
        with self.lock:
            with (self.root/'events.jsonl').open('a') as handle:
                handle.write(json.dumps(dict(time=now(), **event), allow_nan=False)+'\n')
            print(json.dumps(event, allow_nan=False), flush=True)

    def interrupt(self, signum, frame):
        self.stop.set()
        # Only direct children of this foreground campaign are signalled.
        for child in list(self.children):
            if child.poll() is None:
                child.terminate()

    def run_one(self, task, init, folder, gpu):
        folder.mkdir()
        episode = folder/'episode'
        source = self.args.baselines/f'task-{task["task_id"]}'
        command = command_for(task, source, episode, init, self.args.controller_root)
        env = dict(os.environ, MUJOCO_GL='egl', MUJOCO_EGL_DEVICE_ID=str(gpu),
            CUDA_VISIBLE_DEVICES=GPU_UUIDS[gpu],
            JEV_RSI_VISION_DEVICE='-1' if task['cpu_vision'] else '0',
            JEV_RSI_VISION_PYTHON=str(self.args.vision_python),
            JEV_RSI_MODEL_CACHE=str(self.args.model_cache),
            JEV_RSI_EXISTING_ROOT=str(self.args.controller_root),
            JEV_RSI_LIBERO_ROOT=str(self.args.libero_root),
            DECISION_MM_KEY_FILE=str(self.args.key_file),
            DECISION_MM_PROXY='http://127.0.0.1:7897',
            OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2',
            HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
            TOKENIZERS_PARALLELISM='false')
        # Existing frozen code records its historical ownership wording. This
        # outer manifest identifies the actual transport without editing it.
        write(folder/'manifest.json', dict(started_at=now(), task_id=task['task_id'],
            init_index=init, physical_gpu=gpu, gpu_uuid=GPU_UUIDS[gpu],
            actor_model='gpt-6-luna', key_origin='du', actor_images=0,
            experience_injection=False, frozen_baseline=task, command=command,
            evaluation='Read native success and program_finished only after final action',
            historical_ownership_labels='Unchanged frozen policy wording, not actual model identity'))
        self.ledger(dict(event='episode_started', task=task['task_id'], init=init, gpu=gpu))
        started = time.monotonic()
        termination = None
        with (folder/'launcher.log').open('w') as log:
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env)
            with self.lock:
                self.children.add(child)
            try:
                while child.poll() is None:
                    if self.stop.wait(2):
                        termination = 'campaign_interrupted'
                        child.terminate()
                        break
                    if time.monotonic()-started > 1400:
                        termination = 'original_1400s_launcher_timeout'
                        child.terminate()
                        break
                    if shutil.disk_usage(self.root).free < 2*1024**3:
                        termination = 'disk_emergency_guard'
                        self.stop.set()
                        child.terminate()
                        break
                try:
                    code = child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    child.kill()
                    code = child.wait(timeout=10)
            finally:
                with self.lock:
                    self.children.discard(child)
        outcome = dict(task=task['task_id'], init=init, gpu=gpu,
            ended_at=now(), seconds=round(time.monotonic()-started, 3),
            **classify(folder, code, termination))
        write(folder/'outcome.json', outcome)
        with self.lock:
            self.rows.append(outcome)
        self.ledger({k: v for k, v in dict(event='episode_finished', **outcome).items()
                     if k not in ('native_result', 'api_failure_files')})

    def worker(self, gpu):
        while not self.stop.is_set():
            # Reserve the original 600MiB cap per active slot plus 8GiB headroom.
            reserve = 8*1024**3 + len(self.args.gpus)*self.args.jobs_per_gpu*600*1024**2
            if shutil.disk_usage(self.root).free < reserve:
                self.stop.set()
                self.ledger(dict(event='storage_guard', free_bytes=shutil.disk_usage(self.root).free))
                return
            with self.lock:
                if self.args.max_new_episodes is not None and self.claimed >= self.args.max_new_episodes:
                    return
                try:
                    task, init, folder = self.pending.get_nowait()
                except queue.Empty:
                    return
                self.claimed += 1
            try:
                self.run_one(task, init, folder, gpu)
            except Exception as error:
                self.stop.set()
                self.ledger(dict(event='campaign_error', task=task['task_id'], init=init,
                                 error_type=type(error).__name__, error=str(error)[:500]))
            finally:
                self.pending.task_done()

    def run(self):
        signal.signal(signal.SIGTERM, self.interrupt)
        signal.signal(signal.SIGINT, self.interrupt)
        slots = self.args.gpus*self.args.jobs_per_gpu
        self.ledger(dict(event='foreground_invocation', gpus=self.args.gpus,
            jobs_per_gpu=self.args.jobs_per_gpu, max_new_episodes=self.args.max_new_episodes))
        with ThreadPoolExecutor(max_workers=len(slots)) as pool:
            futures = [pool.submit(self.worker, gpu) for gpu in slots]
            for future in futures:
                future.result()
        rows = sorted(self.rows, key=lambda r: (r['task'], r['init']))
        write(self.root/'summary.json', dict(ended_at=now(), completed=len(rows),
            remaining=self.pending.qsize(), stopped=self.stop.is_set(),
            joint_successes=sum(r['joint_success'] for r in rows), episodes=rows))
        return 2 if self.stop.is_set() else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baselines', required=True, type=Path)
    parser.add_argument('--output-root', required=True, type=Path)
    parser.add_argument('--key-file', required=True, type=Path)
    parser.add_argument('--gpus', type=int, nargs='+', default=[4, 5, 6, 7])
    parser.add_argument('--jobs-per-gpu', type=int, choices=[1, 2, 3], default=1)
    parser.add_argument('--max-new-episodes', type=int,
                        help='Bound a first resource-measurement wave; resume leaves the frozen policy unchanged')
    parser.add_argument('--controller-root', type=Path, default=Path('/root/yekangjie/project/robodojo-jev'))
    parser.add_argument('--libero-root', type=Path, default=Path('/root/yekangjie/project/embodied-jev/.sim/LIBERO-plus'))
    parser.add_argument('--vision-python', type=Path, default=Path('/root/yekangjie/project/robodojo-jev/envs/robodojo-isaac51/bin/python'))
    parser.add_argument('--model-cache', type=Path, default=Path('/root/yekangjie/project/robodojo-jev/.cache/models'))
    args = parser.parse_args()
    if args.max_new_episodes is not None and args.max_new_episodes < 1:
        parser.error('Episode limit must be positive')
    if not args.gpus or len(set(args.gpus)) != len(args.gpus) or not set(args.gpus) <= set(GPU_UUIDS):
        parser.error('Only distinct physical GPUs4..7 are authorized')
    args.baselines = args.baselines.resolve()
    args.key_file = args.key_file.resolve()
    if not args.key_file.is_file() or args.key_file.name != 'du-openai-direct.key':
        parser.error('Explicitly authorized du key file required')
    # Recheck hardware identity before writing a campaign or launching children.
    hardware = subprocess.check_output(['nvidia-smi', '--query-gpu=index,uuid', '--format=csv,noheader'], text=True)
    found = {int(line.split(',')[0]): line.split(',')[1].strip() for line in hardware.splitlines()}
    if any(found.get(gpu) != GPU_UUIDS[gpu] for gpu in args.gpus):
        parser.error('GPU identity differs from the inspected company-server-2 machine')
    return Campaign(args).run()


if __name__ == '__main__':
    sys.exit(main())

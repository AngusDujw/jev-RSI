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
REPAIR_INITS = {1144: list(range(5, 10)), 1202: list(range(3, 8)),
    1252: list(range(4, 9)), 1296: list(range(12, 17)), 1423: list(range(10, 15))}


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


def connection_interruption(failure):
    if failure['error_type'] in ('URLError', 'RemoteDisconnected', 'TimeoutError', 'ConnectionResetError'):
        return True
    # This gateway interruption returned no provider response. Do not admit
    # HTTP4xx, schema errors, or any answered decision as a replacement case.
    return failure['error_type']=='HTTPError' and failure.get('error')=='HTTP Error 520: <none>'


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
        multimodal = args.profile.startswith('libero-rgb-')
        if multimodal:
            self.tasks = [{**task, 'paired_init_indices': task['paired_init_indices'][:3]}
                          for task in self.tasks]
        if args.tasks:
            self.tasks = [t for t in self.tasks if t['task_id'] in args.tasks]
            if {t['task_id'] for t in self.tasks} != set(args.tasks):
                raise ValueError('Requested task absent from the frozen baseline')
        if args.profile in ('libero-clarity-v1', 'libero-clarity-v2', 'libero-clarity-v3'):
            actual = {t['task_id']: t['paired_init_indices'] for t in self.tasks}
            expected = {1423: REPAIR_INITS[1423]} if args.profile == 'libero-clarity-v3' else REPAIR_INITS
            if len(self.tasks) != len(expected) or len(actual) != len(self.tasks) or actual != expected:
                raise ValueError('Repair requires the predeclared five tasks and five paired states')
        for task in self.tasks:
            verify(args.baselines/f'task-{task["task_id"]}', task)
        replacement_cases = None
        replacement_provenance = None
        if args.replace_transport_from:
            if not multimodal:
                raise ValueError('Transport replacement is declared only for the RGB comparisons')
            previous = args.replace_transport_from.resolve()
            old_spec = json.loads((previous/'campaign.json').read_text())
            old = json.loads((previous/'summary.json').read_text())
            if (old_spec.get('request_profile') != args.profile or old.get('remaining') != 0
                    or len(old['episodes']) != 30):
                raise ValueError('Require a completed30-episode campaign with the identical input condition')
            # The runner adds selection/provenance only; every inference adapter
            # and frozen policy must still match the interrupted source campaign.
            for name, expected in old_spec['adapter_source_sha256'].items():
                if name != Path(__file__).name:
                    p = Path(__file__).with_name(name)
                    if hashlib.sha256(p.read_bytes()).hexdigest() != expected:
                        raise ValueError('Replacement inference source differs: '+name)
            replacement_cases = set()
            provenance = []
            for row in old['episodes']:
                if row['category'] != 'transport_or_schema_failure':
                    continue
                case = previous/f'task-{row["task"]}-init-{row["init"]}'
                failure_paths = list((case/'multimodal/decision-api').glob('*/failure.json'))
                failures = [json.loads(p.read_text()) for p in failure_paths]
                if (not failures or any(not connection_interruption(f) for f in failures)
                        or any((p.parent/'response.json').exists() or (p.parent/'legacy-response.json').exists()
                               for p in failure_paths)):
                    raise ValueError('Only explicit connection faults may receive a replacement episode')
                replacement_cases.add((row['task'], row['init']))
                provenance.append(dict(task=row['task'], init=row['init'], source=str(case),
                    outcome_sha256=hashlib.sha256((case/'outcome.json').read_bytes()).hexdigest()))
            if not replacement_cases:
                raise ValueError('No eligible transport-interrupted episode')
            replacement_provenance = provenance
        specification = dict(phase='1_frozen_text_only', actor_model='gpt-6-luna',
            key_origin='du', actor_images=0, experience_injection=False,
            allowed_physical_gpus=[4, 5, 6, 7],
            expected_episodes=sum(len(t['paired_init_indices']) for t in self.tasks),
            tasks=[{k: t[k] for k in ('task_id', 'source_commit', 'source_sha256',
                'paired_init_indices', 'original_options', 'cpu_vision', 'baseline_status')} for t in self.tasks])
        if args.profile != 'frozen':
            specification['phase'] = '1b_prompt_interface_repair'
            specification['request_profile'] = args.profile
            specification['adapter_source_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (Path(__file__), Path(__file__).with_name('libero_entry.py'),
                          Path(__file__).with_name('legacy_decisions.py'),
                          Path(__file__).with_name('libero_prompt_revision.py'))}
            if args.profile in ('libero-clarity-v2', 'libero-clarity-v3'):
                p = Path(__file__).with_name('libero_prompt_revision_v2.py')
                specification['adapter_source_sha256'][p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
            if multimodal:
                specification['phase'] = 'LIBERO_multimodal'
                specification['actor_images'] = 2
                for name in ('libero_multimodal.py', 'libero_prompt_revision_v2.py', 'libero_visual_ablation.py'):
                    p = Path(__file__).with_name(name)
                    specification['adapter_source_sha256'][name] = hashlib.sha256(p.read_bytes()).hexdigest()
                specification['text_profiles'] = '1423:clarity-v3;1144/1202/1252/1296:clarity-v2;others:original'
                specification['repetitions_per_task'] = 3
                specification['input_condition'] = args.profile
                specification['retained_processing'] = 'Original stage gates, visual holding/arrival booleans, rotation feedback and controller-internal motor scaling'
                if args.profile.startswith('libero-rgb-motion-'):
                    for name in ('libero_motion_multimodal.py', 'libero_robot_actions_v1.txt'):
                        p = Path(__file__).with_name(name)
                        specification['adapter_source_sha256'][name] = hashlib.sha256(p.read_bytes()).hexdigest()
                    specification['camera_matrices_sent'] = False
                    specification['motion_description'] = 'Verified native world-axis / rotation-vector description; no new YPR controller'
                    specification['question_changes'] = 'Short original Jev XYZ template, error and/or labeled RGB evidence; common non-XYZ questions unchanged'
                    specification['image_layout'] = 'Same768x928 in all conditions: native768 RGB plus160px footer; axes compass is goal-independent'
                if args.profile in ('libero-rgb-inframe-axes-v1','libero-rgb-gripper-axes-v1',
                                    'libero-rgb-gripper-pair-arrows-v1','libero-rgb-gripper-pair-raw-v1'):
                    for name in ('libero_motion_multimodal.py', 'libero_robot_actions_v1.txt',
                                 'libero_inframe_axes.py', 'libero_robot_actions_inframe_v1.txt'):
                        p = Path(__file__).with_name(name)
                        specification['adapter_source_sha256'][name] = hashlib.sha256(p.read_bytes()).hexdigest()
                    specification.update(camera_matrices_sent=False, eef_coordinates_sent=False,
                        numeric_tolerances_sent=False, target_markers=False,
                        motion_description='Verified native world-axis / rotation-vector description; no EEF-position field reference',
                        question_changes='Short visual XYZ questions with visual HOLD, no tolerance wording; original non-XYZ questions',
                        image_layout='Native768x768; world-axis arrows inside the frame at a fixed graphic anchor; no footer or TCP/target markers')
                    if args.profile=='libero-rgb-gripper-axes-v1':
                        p=Path(__file__).with_name('libero_gripper_axes_description_v1.txt')
                        specification['adapter_source_sha256'][p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
                        specification.update(axis_origin_uses_current_own_gripper_position=True,
                            drawn_axes={'agentview':['Y','Z'],'robot0_eye_in_hand':['X','Y']},
                            image_layout='Native768x768; two world axes start at the current own gripper projection in each fresh view; no footer or target point')
                    if args.profile.startswith('libero-rgb-gripper-pair-'):
                        for name in ('libero_gripper_pair.py','libero_gripper_pair_description_v1.txt'):
                            p=Path(__file__).with_name(name)
                            specification['adapter_source_sha256'][name]=hashlib.sha256(p.read_bytes()).hexdigest()
                        arrows=args.profile=='libero-rgb-gripper-pair-arrows-v1'
                        specification.update(arrows_drawn=arrows, matched_actor_text=True,
                            axis_origin_uses_current_own_gripper_position=arrows,
                            drawn_axes={'agentview':['Y','Z'],'robot0_eye_in_hand':['X','Y']} if arrows else {},
                            image_layout='Native768x768; no footer, target point or separate control-point marker; optional gripper-anchored axes')
        if replacement_cases is not None:
            specification['expected_episodes'] = len(replacement_cases)
            specification['transport_replacements'] = replacement_provenance
            specification['interpretation'] = 'New complete episodes for connection interruptions only; original failures preserved. Never resample a received decision or a normally failed episode.'
        spec_path = self.root/'campaign.json'
        if spec_path.exists():
            if json.loads(spec_path.read_text()) != specification:
                raise ValueError('Existing campaign has a different frozen specification')
        else:
            write(spec_path, specification)
        # Round robin tasks before their second initial state; no selective reruns.
        for index in range(3 if multimodal else 5):
            for task in self.tasks:
                init = task['paired_init_indices'][index]
                if replacement_cases is not None and (task['task_id'], init) not in replacement_cases:
                    continue
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
        env['DECISION_MM_LIBERO_PROFILE'] = self.args.profile
        if self.args.profile.startswith('libero-rgb-'):
            env['DECISION_MM_ASSET_ROOT'] = str(folder/'multimodal')
        # Existing frozen code records its historical ownership wording. This
        # outer manifest identifies the actual transport without editing it.
        write(folder/'manifest.json', dict(started_at=now(), task_id=task['task_id'],
            init_index=init, physical_gpu=gpu, gpu_uuid=GPU_UUIDS[gpu],
            actor_model='gpt-6-luna', key_origin='du', actor_images=0,
            experience_injection=False, frozen_baseline=task, command=command,
            evaluation='Read native success and program_finished only after final action',
            historical_ownership_labels='Unchanged frozen policy wording, not actual model identity'))
        if self.args.profile != 'frozen':
            manifest_path = folder/'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['request_profile'] = self.args.profile
            manifest['comparison'] = 'Revised prompts/interface; original frozen policy, processing, thresholds, stages and paired initial states'
            if self.args.profile.startswith('libero-rgb-'):
                manifest['actor_images'] = 2
                manifest['multimodal_asset_root'] = str(folder/'multimodal')
                manifest['comparison'] = self.args.profile+'; latest task profiles; original processing/control preserved, actor-input ablation only'
            write(manifest_path, manifest)
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
            slot_mb = 1500 if self.args.profile.startswith('libero-rgb-') else 600
            reserve = 8*1024**3 + len(self.args.gpus)*self.args.jobs_per_gpu*slot_mb*1024**2
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
    parser.add_argument('--jobs-per-gpu', type=int, choices=[1, 2, 3, 4, 5, 6], default=1)
    parser.add_argument('--max-new-episodes', type=int,
                        help='Bound a first resource-measurement wave; resume leaves the frozen policy unchanged')
    parser.add_argument('--profile', choices=['frozen', 'libero-clarity-v1', 'libero-clarity-v2', 'libero-clarity-v3', 'libero-rgb-full', 'libero-rgb-waypoint', 'libero-rgb-raw', 'libero-rgb-motion-full-v1', 'libero-rgb-motion-marker-v1', 'libero-rgb-motion-axes-v1', 'libero-rgb-inframe-axes-v1', 'libero-rgb-gripper-axes-v1', 'libero-rgb-gripper-pair-arrows-v1', 'libero-rgb-gripper-pair-raw-v1'], default='frozen')
    parser.add_argument('--tasks', nargs='+', type=int)
    parser.add_argument('--replace-transport-from', type=Path,
                        help='Explicit new episodes for connection-interrupted cases only; preserve original outcomes')
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

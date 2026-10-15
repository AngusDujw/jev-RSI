"""Freeze exact per-task policy sources and original options, without running them."""
import argparse
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import subprocess

INITS = {1098: list(range(6, 11)), 1144: list(range(5, 10)),
    1163: list(range(5, 10)), 1202: list(range(3, 8)),
    1252: list(range(4, 9)), 1296: list(range(12, 17)),
    1335: list(range(23, 28)), 1383: list(range(8, 13)),
    1423: list(range(10, 15)), 1458: list(range(11, 16))}


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def prepare(repo, output):
    report = repo / 'code/reports/libero-ten-workflows/data.js'
    text = report.read_text()
    cases = json.loads(text[text.index('['):].rstrip().rstrip(';'))
    output.mkdir(parents=True, exist_ok=False)
    tasks = []
    for case in cases:
        task = case['id']
        original = repo / 'code/runs' / case['source_run']
        manifest = json.loads((original / 'manifest.json').read_text())
        protocol = json.loads((original / 'episode/protocol.json').read_text())
        folder = output / f'task-{task}'
        folder.mkdir()
        for name, expected in case['sources'].items():
            if Path(name).name != name:
                raise ValueError('Invalid policy source filename')
            raw = subprocess.check_output(['git', '-C', str(repo), 'show',
                case['commit'] + ':code/scripts/' + name])
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError(f'Frozen source mismatch: {task}/{name}')
            (folder / name).write_bytes(raw)
        write(folder / 'decision-api-config.json', {'jev': {'model': 'gpt-6-luna'}})
        settings = {**protocol, **manifest, **manifest.get('cli_options', {})}
        # Persist only plain options, not evaluator outcome or private paths.
        spec = importlib.util.spec_from_file_location(f'launcher_{task}',
            folder / 'run_libero_goal_jev.py')
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        values = {**settings, 'source': folder, 'task_id': task,
            'init_index': INITS[task][0], 'episode': output/'placeholder-episode',
            'mode': manifest['mode']}
        kwargs = {}
        frozen_options = {}
        for name, parameter in inspect.signature(launcher.launch_command).parameters.items():
            if name in values:
                value = values[name]
            elif parameter.default is not inspect.Parameter.empty:
                value = parameter.default
            else:
                raise ValueError(f'Missing original launch option: {task}/{name}')
            kwargs[name] = value
            if name not in ('source', 'episode', 'task_id', 'init_index'):
                frozen_options[name] = value
        command = launcher.launch_command(**kwargs)
        item = dict(task_id=task, source_commit=case['commit'],
            source_run=case['source_run'], source_sha256=case['sources'],
            source_folder=str(folder), original_options=frozen_options,
            cpu_vision=bool(manifest['cpu_vision']), paired_init_indices=INITS[task],
            native_python=command[0], argv_template=command[1:],
            baseline_status=('unstable_reference_development_episode' if task == 1202
                else 'prior_frozen_five_successes; now paired comparison, not new unseen states'),
            original_manifest_sha256=hashlib.sha256((original/'manifest.json').read_bytes()).hexdigest(),
            original_protocol_sha256=hashlib.sha256((original/'episode/protocol.json').read_bytes()).hexdigest(),
            state_and_question_instructions='unchanged', actor_images=0,
            experience_injection=False, actor_model='gpt-6-luna', key_origin='du')
        write(folder / 'baseline.json', item)
        tasks.append(item)
    write(output / 'campaign.json', dict(phase='1_frozen_text_only',
        episodes=50, allowed_physical_gpus=[4, 5, 6, 7], tasks=tasks,
        scope='No controller, stage, preprocessing, tolerance or question edits.',
        first_failure_does_not_truncate_the_five_episode_comparison=True,
        task1202='All five episodes included; no stable Jev reference is claimed.'))
    return tasks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-repo', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    tasks = prepare(args.source_repo.resolve(), args.output.resolve())
    print(json.dumps([dict(task=t['task_id'], inits=t['paired_init_indices'],
        cpu_vision=t['cpu_vision'], source_files=len(t['source_sha256'])) for t in tasks]))


if __name__ == '__main__':
    main()

"""Start actual policy workers only after native smoke/readiness is reviewed."""
import argparse
import json
import os
from pathlib import Path
import subprocess

from transport import save
from worker import rpc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--roboicl', type=Path, required=True)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--gpus', type=int, nargs='+', required=True)
    args = parser.parse_args()
    manifest = json.loads((args.campaign/'manifest.json').read_text())
    selected = [case for case in manifest['cases'] if case['gpu'] in args.gpus]
    if len(selected) != len(set(args.gpus)):
        raise ValueError('GPU selection must match the existing native manifest')
    if not args.key_file.is_file():
        raise ValueError('Configure the previously authorized du credential privately')
    code = Path(__file__).resolve().parent
    for case in selected:
        if case.get('worker_pid') or (Path(case['case'])/'worker').exists():
            raise FileExistsError('A policy worker was already started; never duplicate it')
        os.kill(case['native_pid'], 0)
        native = rpc(case['port'], 'status')
        if native['ended'] or native['step'] != 0:
            raise ValueError('Policy starts only on an explicitly fresh native attempt')
    for case in selected:
        output = Path(case['case'])/'worker'
        env = dict(os.environ, TMPDIR=str(Path(case['case'])/'tmp'), PYTHONUNBUFFERED='1')
        for key in list(env):
            if key.startswith(('ASTRA_', 'OPENAI_', 'CODEX_API_')):
                env.pop(key)
        command = [str(args.roboicl/'.venv-policy/bin/python'), '-B', '-u', str(code/'worker.py'),
            '--output', str(output), '--sim-port', str(case['port']),
            '--knowledge', str(args.campaign/'knowledge/current.json'),
            '--key-file', str(args.key_file), '--segment-decisions', '3']
        if case['visual_history']:
            command.append('--visual-history')
        if case['retain_history']:
            command.append('--retain-history')
        with (Path(case['case'])/'worker.log').open('wb') as log:
            process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        case['worker_pid'] = process.pid
        case['worker_command'] = command
        save(args.campaign/'manifest.json', manifest)
        print(json.dumps(dict(gpu=case['gpu'], layout=case['layout'], worker_pid=process.pid,
            visual_history=case['visual_history'])), flush=True)


if __name__ == '__main__':
    main()

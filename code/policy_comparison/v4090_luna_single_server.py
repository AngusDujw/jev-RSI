"""Launch one original GPT-as-Policy RPC server in the existing v4090 environment."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys


def main():
    run = Path(sys.argv[1]).resolve()
    runtime = Path(sys.argv[2]).resolve()
    port = int(sys.argv[3])
    base = Path('/home/v4090-1/DataStorage/gpt6-dec')
    if not run.is_relative_to(base / 'gpt-as-policy-single'):
        raise ValueError('Run must remain under the authorized DataStorage root')
    if run.exists():
        raise FileExistsError('Never restart or overwrite a native attempt')
    run.mkdir(parents=True)
    (run / 'sim').mkdir()
    driver = Path('/home/v4090-1/ykj/project/jev-RSI-gpt6-dec/code/robodojo_decisions/run_episode.py')
    namespace = runpy.run_path(str(driver))
    python = namespace['executable']()
    env = namespace['native_env'](run, python)
    env['PYTHONPATH'] = str(runtime) + ':' + env['PYTHONPATH']
    entry = runtime.parent / 'v4090_luna_entry.py'
    command = [str(python), '-B', '-u', str(entry), '--task', 'stack_blocks',
               '--output', str(run / 'sim'), '--port', str(port), '--eval-seed', '0',
               '--headless', '--enable_cameras', '--device', 'cuda:0']
    (run / 'launch.json').write_text(json.dumps(dict(command=command, task='stack_blocks',
        layout=0, attempts=1, preserve_media=True, interpreter=str(python)), indent=2) + '\n')
    os.execve(str(python), command, env)


if __name__ == '__main__':
    main()

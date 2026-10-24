"""Launch one original GPT-as-Policy RPC server in the existing v4090 environment."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys


RPC_IDLE_TIMEOUT_SECONDS = 7200


def configure_rpc_wait(runtime):
    """Change only the fresh server copy's receive timeout, never its scoring."""
    rpc = runtime / 'hybrid_rollout/robodojo/robodojo_server/rpc.py'
    if (not rpc.resolve().is_relative_to(runtime.resolve()) or not rpc.is_file()
            or rpc.is_symlink() or rpc.stat().st_nlink != 1):
        raise ValueError('RPC source must be an independent regular copy')
    original = rpc.read_bytes()
    anchor = b'connection.settimeout(900)'
    if original.count(anchor) != 1:
        raise ValueError('Expected exactly one original RPC receive timeout')
    updated = original.replace(anchor,
        f'connection.settimeout({RPC_IDLE_TIMEOUT_SECONDS})'.encode())
    rpc.write_bytes(updated)
    return dict(original_idle_timeout_seconds=900,
        idle_timeout_seconds=RPC_IDLE_TIMEOUT_SECONDS,
        original_sha256=hashlib.sha256(original).hexdigest(),
        configured_sha256=hashlib.sha256(updated).hexdigest(),
        scope='Fresh isolated server receive wait only; physical steps and scoring unchanged.')


def main():
    run = Path(sys.argv[1]).resolve()
    runtime = Path(sys.argv[2]).resolve()
    port = int(sys.argv[3])
    base = Path('/home/v4090-1/DataStorage/gpt6-dec')
    if not run.is_relative_to(base / 'gpt-as-policy-single'):
        raise ValueError('Run must remain under the authorized DataStorage root')
    if run.exists():
        raise FileExistsError('Never restart or overwrite a native attempt')
    expected_runtime = base / 'gpt-as-policy-single' / ('source-' + run.name) / 'official_runtime'
    if runtime != expected_runtime:
        raise ValueError('Only this new attempt\'s isolated server copy may be configured')
    run.mkdir(parents=True)
    (run / 'sim').mkdir()
    rpc_wait = configure_rpc_wait(runtime)
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
        layout=0, attempts=1, preserve_media=True, interpreter=str(python),
        rpc_wait=rpc_wait), indent=2) + '\n')
    os.execve(str(python), command, env)


if __name__ == '__main__':
    main()

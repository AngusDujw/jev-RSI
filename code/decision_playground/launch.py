"""Launch owned native Playground sessions; workers start only after review."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from transport import save


def resources(gpus):
    ram = {x.split(':')[0]: int(x.split()[1]) for x in Path('/proc/meminfo').read_text().splitlines()}
    if ram['MemAvailable'] < (len(gpus)*20+20)*1024**2:
        raise RuntimeError('Need 20GiB RAM per initial simulator plus 20GiB headroom')
    raw = subprocess.check_output(['nvidia-smi', '--query-gpu=index,memory.free',
        '--format=csv,noheader,nounits'], text=True)
    free = {int(x.split(',')[0]): int(x.split(',')[1]) for x in raw.splitlines()}
    occupied = subprocess.check_output(['nvidia-smi', '--query-compute-apps=gpu_uuid,pid',
        '--format=csv,noheader,nounits'], text=True).strip()
    if occupied:
        raise RuntimeError('Initial native launch requires no preexisting GPU occupants; inspect ownership first')
    if any(free[gpu] < 8192 for gpu in gpus):
        raise RuntimeError('Need 8GiB GPU admission headroom')
    return dict(gpu_free_mib=free, ram_available_kib=ram['MemAvailable'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--roboicl', type=Path, required=True)
    parser.add_argument('--gpus', type=int, nargs='+', default=list(range(8)))
    parser.add_argument('--port-base', type=int, default=25300)
    parser.add_argument('--native-only', action='store_true')
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--native-step-multiplier', type=int, choices=(1, 5), default=5)
    args = parser.parse_args()
    if len(set(args.gpus)) != len(args.gpus) or any(g not in range(8) for g in args.gpus):
        raise ValueError('Use unique allocated GPUs 0..7')
    if args.campaign.exists():
        raise FileExistsError('Use a new campaign, never silently resume or overwrite')
    if shutil.disk_usage(args.campaign.parent).free < 8*1024**3:
        raise RuntimeError('Need 8GiB free campaign disk')
    admission = resources(args.gpus)
    args.campaign.mkdir(parents=True)
    (args.campaign/'tmp').mkdir()
    knowledge = args.campaign/'knowledge'
    knowledge.mkdir()
    save(knowledge/'current.json', dict(revision='r000', guidance='', visual_lessons=[], skills=[]))
    records = []
    sim_python = args.roboicl/'.venv-sim/bin/python'
    policy_python = args.roboicl/'.venv-policy/bin/python'
    code = Path(__file__).resolve().parent
    base_env = os.environ.copy()
    for key in list(base_env):
        if key.startswith(('ASTRA_', 'OPENAI_', 'CODEX_API_')):
            base_env.pop(key)
    for index, gpu in enumerate(args.gpus):
        layout = index % 4
        visual = index < 4
        case = args.campaign/f'general_pickup-layout{layout}-gpu{gpu}'
        case.mkdir()
        (case/'tmp').mkdir()
        native = case/'native'
        native.mkdir()
        env = dict(base_env, CUDA_VISIBLE_DEVICES=str(gpu), PYTHONPATH=str(args.roboicl),
            PYTHONUNBUFFERED='1', PYTHONNOUSERSITE='1', TMPDIR=str(case/'tmp'),
            XDG_CACHE_HOME=str(args.campaign/'cache'),
            CUDA_CACHE_PATH=str(args.campaign/'cuda-cache'),
            TORCH_EXTENSIONS_DIR=str(args.campaign/'torch-extensions'),
            OMNI_KIT_ALLOW_ROOT='1', ROBOICL_NO_MEDIA='1',
            ROBODOJO_RUN_ID='playground-'+args.campaign.name+'-'+str(gpu),
            PLAYGROUND_RPC_PORT=str(args.port_base+index), PLAYGROUND_OUTPUT=str(native))
        env['PLAYGROUND_STEP_MULTIPLIER'] = str(args.native_step_multiplier)
        command = [str(sim_python), '-B', '-u', str(code/'native_server.py'),
            '--task', 'general_pickup', '--seed', '0', '--layout', str(layout),
            '--data-root', str(args.roboicl/'data'), '--results-root', str(native),
            '--port', str(args.port_base+index+100), '--host', '127.0.0.1',
            '--enable_cameras', '--headless', '--kit_args',
            '--enable isaacsim.replicator.behavior --enable isaacsim.sensors.camera --portable-root '+str(case/'kit')]
        icd = '/etc/vulkan/icd.d/nvidia_icd.json'
        if Path(icd).exists():
            env.update(VK_DRIVER_FILES=icd, VK_ICD_FILENAMES=icd)
        with (case/'native.log').open('wb') as log:
            process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        record = dict(task='general_pickup', layout=layout, gpu=gpu, port=args.port_base+index,
            official_step_limit=200, development_step_limit=200*args.native_step_multiplier,
            step_multiplier=args.native_step_multiplier,
            native_pid=process.pid, case=str(case), visual_history=visual,
            retain_history=index == 0, command=command)
        records.append(record)
        save(args.campaign/'manifest.json', dict(created_at=time.time(), admission=admission,
            cases=records, server='company-server-2-ykj', native_only=args.native_only))
        time.sleep(2)
    if not args.native_only:
        raise RuntimeError('Review native readiness and zero-motion smoke before explicitly starting policy workers')


if __name__ == '__main__':
    main()

"""New authorized evaluation/development ledger; never reset the task's 50 cap.

Freeze the supplied policy snapshot and its configuration before the first run.
Archival is post-episode instrumentation, verified byte-reversible, not a policy
change. No discarded episode or automatic rerun of a failed initial state.
"""
import argparse
import fcntl
import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from libero_frame_archive import archive
from libero_proxy_transport import probe, validate_proxy, EXISTING_ROOT

SIM_PYTHON = '/root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python'


def gpu_preflight():
    """Existing environments only; no physical episode or ledger reservation."""
    code = ('import ctypes,json; lib=ctypes.CDLL("libcuda.so.1"); '
        'rc=lib.cuInit(0); n=ctypes.c_int(); count_rc=lib.cuDeviceGetCount(ctypes.byref(n)); '
        'print(json.dumps(dict(cuInit=rc,cuDeviceGetCount=count_rc,device_count=n.value))); '
        'raise SystemExit(0 if rc==0 and count_rc==0 and n.value>0 else 2)')
    rows = []
    for role, python in [('simulator', SIM_PYTHON), ('grounding',
        '/root/yekangjie/project/robodojo-jev/envs/robodojo-isaac51/bin/python')]:
        try:
            result = subprocess.run([python, '-B', '-c', code],
                capture_output=True, text=True, timeout=30)
            detail = json.loads(result.stdout) if result.stdout.strip() else {}
            row = dict(role=role, python=python, returncode=result.returncode,
                **detail, stderr=result.stderr[-500:], ok=result.returncode == 0)
        except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
            row = dict(role=role, python=python, ok=False,
                error_type=type(exc).__name__, error=str(exc)[:500])
        rows.append(row)
    return dict(ok=all(r['ok'] for r in rows), checks=rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--frozen-from', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--campaign', required=True)
    p.add_argument('--inits', required=True)
    p.add_argument('--tasks', help='Override environment task only; policy unchanged')
    p.add_argument('--episode-cap', type=int, default=20, choices=[20, 30])
    p.add_argument('--purpose', choices=['evaluation', 'development'], default='evaluation')
    p.add_argument('--jev-proxy', type=validate_proxy)
    p.add_argument('--vision-proxy', type=validate_proxy)
    p.add_argument('--preflight-only', action='store_true',
        help='Check actual API transport and CUDA; reserve no physical trial')
    a = p.parse_args()
    if bool(a.jev_proxy) != bool(a.vision_proxy):
        p.error('Set both --jev-proxy and --vision-proxy, or neither')
    assert a.campaign.startswith(('2026-10-04-libero-verify20-', '2026-10-04-libero-top5-'))
    source = Path(__file__).resolve().parent
    repo = source.parents[1]
    prior = json.loads((a.frozen_from.parent/'manifest.json').read_text())
    options = dict(prior.get('options', prior))
    if 'input_organization' in options:
        # These were explicit fixed arguments in the original recovery runner.
        options.setdefault('geometry_profile', 'observed_surfaces')
        options.setdefault('camera_size', 768)
    tasks = a.tasks or options.get('tasks')
    if not isinstance(tasks, str):
        tasks = ','.join(f'{s}:{t}' for s, t in tasks)
    specs = [(s, int(t)) for s, t in (x.split(':') for x in tasks.split(','))]
    inits = [int(i) for i in a.inits.split(',')]
    assert len(set(inits)) == len(inits) and len(set(specs)) == len(specs)
    assert len(specs)*len(inits) <= a.episode_cap
    if a.purpose == 'evaluation':
        development_inits = options.get('inits', [])
        if isinstance(development_inits, str):
            development_inits = [int(i) for i in development_inits.split(',')]
        assert not set(inits).intersection(development_inits), 'Evaluation must use new initial states'
    root = a.output.resolve(); root.mkdir(parents=True, exist_ok=False)
    frozen = root/'frozen'; frozen.mkdir()
    for name, expected in prior['source_sha256'].items():
        data = (a.frozen_from/name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected, name
        (frozen/name).write_bytes(data)
    manifest = dict(options=options, commit=prior['commit'],
        runner_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        source_sha256=prior['source_sha256'], campaign=a.campaign,
        purpose=a.purpose, episode_cap=a.episode_cap, task_total_cap=50,
        evaluation_inits=inits, environment_tasks=specs, args=vars(a),
        frame_archival='Lossless RGB video; exact original PNG byte reconstruction verified',
        transport=dict(jev_proxy=a.jev_proxy, vision_proxy=a.vision_proxy,
            wrapper_sha256=hashlib.sha256((source/'libero_proxy_transport.py').read_bytes()).hexdigest(),
            api_source_sha256=hashlib.sha256((EXISTING_ROOT/'controller/src/realman_jev/api.py').read_bytes()).hexdigest(),
            policy_payload_changed=False))
    (root/'manifest.json').write_text(json.dumps(manifest, indent=2, default=str)+'\n')
    network = probe(a.jev_proxy, a.vision_proxy)
    gpu = gpu_preflight()
    preflight = dict(network=network, gpu=gpu, planned_episodes=len(specs)*len(inits),
        physical_episodes=0, trial_ledger_reserved=False)
    (root/'preflight.json').write_text(json.dumps(preflight, indent=2)+'\n')
    if not network['ok'] or not gpu['ok']:
        (root/'not-started.json').write_text(json.dumps(dict(
            reason='API transport or CUDA preflight failed', physical_episodes=0,
            trial_ledger_reserved=False), indent=2)+'\n')
        print(json.dumps(dict(preflight_ok=False, network_ok=network['ok'], gpu_ok=gpu['ok'],
            physical_episodes=0, output=str(root))), flush=True)
        raise SystemExit(2)
    if a.preflight_only:
        print(json.dumps(dict(preflight_ok=True, physical_episodes=0, output=str(root))), flush=True)
        return
    ledger = repo/'code/runs/libero-supervisor-ledger.jsonl'
    campaign = repo/'code/runs'/f'{a.campaign}-ledger.jsonl'
    rows = []
    for suite, task in specs:
        for init in inits:
            out = root/f'{suite}-{task}-init-{init}'
            if shutil.disk_usage(root).free < 6*1024**3:
                raise RuntimeError('Need >=6GiB before starting another episode')
            with ledger.open('a+') as lf:
                fcntl.flock(lf, fcntl.LOCK_EX); lf.seek(0)
                old = [json.loads(s) for s in lf if s.strip()]
                with campaign.open('a+') as cf:
                    cf.seek(0); previous = [json.loads(s) for s in cf if s.strip()]
                    count = sum(r['suite']==suite and r['task']==task for r in old)
                    assert count < 50 and len(previous) < a.episode_cap, 'Authorized cap reached'
                    assert not any(r['suite']==suite and r['task']==task and r['init']==init
                        for r in previous), 'Do not rerun an initial state in this campaign'
                    reservation = dict(suite=suite, task=task, init=init, attempt=count+1,
                        campaign_attempt=len(previous)+1, campaign=a.campaign,
                        purpose=a.purpose, output=str(out), options=options)
                    for stream in [lf, cf]:
                        stream.write(json.dumps(reservation)+'\n'); stream.flush(); os.fsync(stream.fileno())
            cmd = [SIM_PYTHON, '-B', str(frozen/'libero_jev_rollout.py'),
                '--suite', suite, '--task-id', str(task), '--init-index', str(init),
                '--output', str(out)]
            if 'input_organization' in options:
                cmd.append('--recovery-supervisor')
                for key in ['input_organization', 'grasp_algorithm', 'contact_angle_deg',
                    'pad_overlap_mm', 'table_margin_mm', 'execution_profile']:
                    cmd.extend(['--'+key.replace('_','-'), str(options.get(key, 'baseline'))])
                for key in ['preserve_source', 'allow_retry']:
                    if options.get(key): cmd.append('--'+key.replace('_','-'))
            else:
                cmd.append('--jev-supervisor')
                for key in ['schema', 'grasp_fraction', 'approach_mode']:
                    cmd.extend(['--'+key.replace('_','-'), str(options[key])])
                if options.get('lift_check'): cmd.append('--lift-check')
            for key in ['geometry_profile', 'camera_size', 'max_jev_decisions']:
                cmd.extend(['--'+key.replace('_','-'), str(options[key])])
            if a.jev_proxy or a.vision_proxy:
                cmd = [SIM_PYTHON, '-B', str(source/'libero_proxy_transport.py'), 'run',
                    '--jev-proxy', a.jev_proxy, '--vision-proxy', a.vision_proxy,
                    '--policy', str(frozen/'libero_jev_rollout.py'), '--', *cmd[3:]]
            start = time.monotonic(); termination = None
            with (root/f'{out.name}.log').open('w') as log:
                child = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
                while child.poll() is None:
                    if time.monotonic()-start > 960 or shutil.disk_usage(root).free < 4*1024**3:
                        termination = 'Runner timeout or shared filesystem below 4GiB'
                        child.send_signal(signal.SIGINT)
                        try: child.wait(timeout=45)
                        except subprocess.TimeoutExpired: child.kill(); child.wait()
                        break
                    try: child.wait(timeout=5)
                    except subprocess.TimeoutExpired: pass
                    except KeyboardInterrupt:
                        termination = 'User/protocol interruption of owned runner'
                        child.send_signal(signal.SIGINT)
                        try: child.wait(timeout=45)
                        except subprocess.TimeoutExpired: child.kill(); child.wait()
                        break
            result = json.loads((out/'result.json').read_text()) if (out/'result.json').exists() else dict(success=False, error='Setup/no result')
            row = dict(reservation, seconds=time.monotonic()-start,
                returncode=child.returncode, result=result, runner_termination=termination)
            rows.append(row)
            (root/'batch.json').write_text(json.dumps(rows, indent=2)+'\n')
            print(json.dumps(row), flush=True)
            network_error = any(s in str(result.get('error', '')) for s in
                ['Name or service not known', 'Temporary failure in name resolution',
                 'Connection refused', 'Network is unreachable', 'ConnectError',
                 'unexpected EOF', 'ReadTimeout', 'ConnectTimeout'])
            if termination or network_error:
                # Stop on the first infrastructure failure, preserving the row.
                (root/'stopped.json').write_text(json.dumps(dict(
                    reason=termination or 'API/network infrastructure failure',
                    episode=str(out), completed_rows=len(rows)), indent=2)+'\n')
                raise RuntimeError('Stopped without an automatic retry: '+str(out))
            if (out/'result.json').exists():
                audit_name = 'audit_libero_recovery.py' if 'input_organization' in options else 'audit_libero_supervisor.py'
                with (out/'audit.stdout').open('w') as log:
                    rc = subprocess.run([SIM_PYTHON, '-B', str(source/audit_name), str(out),
                        '--output', str(out/'audit.json')], stdout=log, stderr=subprocess.STDOUT).returncode
                if rc != 0: raise RuntimeError('Recorded control audit failed: '+str(out))
                row['archive'] = archive(out, remove_source=True)
                (root/'batch.json').write_text(json.dumps(rows, indent=2)+'\n')
            if sum(f.stat().st_size for f in root.rglob('*') if f.is_file()) > 3*1024**3:
                raise RuntimeError('Batch disk cap 3GiB')
    (root/'finished.json').write_text(json.dumps(dict(episodes=len(rows),
        native_successes=sum(r['result']['success'] for r in rows),
        complete_successes=sum(r['result']['success'] and r['result'].get('program_finished',False) for r in rows)))+'\n')


if __name__ == '__main__':
    main()

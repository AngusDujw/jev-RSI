"""Bounded LIBERO comparison using ChatGPT-signed-in GPT-6 Sol/xhigh only.

Old Jev/API episodes remain in their ledgers. Every new physical attempt,
including a setup or transport failure, consumes the existing 50/task cap.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import urllib.request

from libero_frame_archive import archive
from run_libero_frozen_validation import gpu_preflight, SIM_PYTHON


FILES = ['libero_jev_rollout.py', 'libero_jev_supervisor.py',
    'libero_jev_recovery.py', 'libero_robot_geometry.py',
    'libero_generic_vision.py', 'libero_grounding_worker.py',
    'local_rgbd_perception.py', 'run_position_pilot.py',
    'codex_pro_bridge.py']
PROFILES = {
    'cheese': dict(mode='recovery', geometry_profile='observed_surfaces',
        camera_size=768, max_decisions=180),
    'soup': dict(mode='supervisor', geometry_profile='observed_surfaces',
        camera_size=768, max_decisions=160),
    'bowl': dict(mode='supervisor', geometry_profile='base',
        camera_size=384, max_decisions=120),
}


def bridge_health():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open('http://127.0.0.1:7903/health', timeout=20) as reply:
        health = json.load(reply)
    if health != dict(ok=True, model='gpt-6-sol',
            reasoning_effort='xhigh', auth='ChatGPT'):
        raise RuntimeError('Pro bridge health/model/auth mismatch')
    return health


def bridge_model_preflight():
    request = dict(role='jev', request=dict(model='gpt-6-sol',
        state=dict(task='preflight only; no physical episode',
            translation_axes=dict(x=dict(current_coordinate_m=0.0,
                goal_coordinate_m=0.1, relation='goal_coordinate_larger'))),
        questions=dict(x=dict(type='choice', instructions='Choose the sign of the x goal',
            criteria=dict(negative='decrease', hold='no displacement',
                positive='increase')))))
    body = json.dumps(request).encode()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    call = urllib.request.Request('http://127.0.0.1:7903/infer', data=body,
        headers={'Content-Type':'application/json'})
    with opener.open(call, timeout=250) as reply:
        result = json.load(reply)
    if (result.get('model')!='gpt-6-sol' or result.get('reasoning_effort')!='xhigh'
            or result.get('answers',{}).get('x',{}).get('choice')!='positive'):
        raise RuntimeError('Model preflight returned unexpected decision/model')
    return dict(model=result['model'], reasoning_effort=result['reasoning_effort'],
        codex_request_id=result.get('codex_request_id'), usage=result.get('usage'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--profile', choices=PROFILES, required=True)
    parser.add_argument('--suite', choices=['libero_object', 'libero_spatial'], required=True)
    parser.add_argument('--task-id', type=int, required=True)
    parser.add_argument('--inits', required=True, help='Comma-separated official init indices')
    parser.add_argument('--purpose', choices=['development', 'evaluation'], default='development')
    parser.add_argument('--frozen-from', type=Path,
        help='Required for evaluation: previously frozen Pro policy directory')
    parser.add_argument('--preflight-only', action='store_true')
    args = parser.parse_args()
    if args.purpose == 'evaluation' and args.frozen_from is None:
        parser.error('Evaluation requires --frozen-from')
    inits = [int(x) for x in args.inits.split(',')]
    if not inits or len(inits) != len(set(inits)) or len(inits) > 20:
        parser.error('Provide 1-20 distinct init indices')
    source = Path(__file__).resolve().parent
    repo = source.parents[1]
    root = args.output.resolve()
    if not root.is_relative_to(repo/'code/runs'):
        parser.error('Output must be under this project code/runs mount')
    root.mkdir(parents=True, exist_ok=False)
    frozen = root/'frozen'
    frozen.mkdir()
    health = bridge_health()
    try:
        model_preflight = bridge_model_preflight()
    except Exception as exc:
        (root/'not-started.json').write_text(json.dumps(dict(
            physical_episodes=0, trial_ledger_reserved=False,
            reason='Codex model preflight failed', error_type=type(exc).__name__,
            error=str(exc)[:500]), indent=2)+'\n')
        raise
    gpu = gpu_preflight()
    (root/'preflight.json').write_text(json.dumps(dict(bridge=health,
        model=model_preflight,gpu=gpu), indent=2)+'\n')
    if not gpu['ok']:
        raise RuntimeError('CUDA preflight failed before reserving a trial')
    if args.preflight_only:
        print(json.dumps(dict(preflight_ok=True, physical_episodes=0)))
        return
    snapshot = args.frozen_from.resolve() if args.frozen_from else source
    prior = json.loads((snapshot.parent/'manifest.json').read_text()) if args.frozen_from else None
    if prior and (prior['model'] != 'gpt-6-sol' or prior['reasoning_effort'] != 'xhigh'
            or prior['profile'] != args.profile):
        raise RuntimeError('Frozen model/profile mismatch')
    for name in FILES:
        data = (snapshot/name).read_bytes()
        if prior and hashlib.sha256(data).hexdigest() != prior['source_sha256'][name]:
            raise RuntimeError('Frozen source hash mismatch: ' + name)
        (frozen/name).write_bytes(data)
    policy = PROFILES[args.profile]
    commit = subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip()
    manifest = dict(model='gpt-6-sol', reasoning_effort='xhigh',
        authentication='ChatGPT-signed-in Codex CLI on workstation',
        endpoint='SSH reverse-forwarded loopback 7903',
        profile=args.profile, policy=policy, purpose=args.purpose,
        suite=args.suite, task_id=args.task_id, inits=inits,
        policy_commit=prior['policy_commit'] if prior else commit,
        runner_commit=commit, task_total_cap=50, campaign_cap=20,
        source_sha256={name:hashlib.sha256((frozen/name).read_bytes()).hexdigest()
            for name in FILES})
    (root/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    global_ledger = repo/'code/runs/libero-supervisor-ledger.jsonl'
    campaign_ledger = repo/'code/runs'/(root.name+'-ledger.jsonl')
    rows = []
    for init in inits:
        bridge_health()
        if shutil.disk_usage(root).free < 6*1024**3:
            raise RuntimeError('Need 6GiB free before another physical attempt')
        out = root/f'{args.suite}-{args.task_id}-init-{init}'
        with global_ledger.open('a+') as ledger:
            fcntl.flock(ledger, fcntl.LOCK_EX)
            ledger.seek(0)
            previous = [json.loads(line) for line in ledger if line.strip()]
            with campaign_ledger.open('a+') as own:
                own.seek(0)
                campaign_rows = [json.loads(line) for line in own if line.strip()]
                count = sum(row['suite']==args.suite and row['task']==args.task_id
                    for row in previous)
                if count >= 50 or len(campaign_rows) >= 20:
                    raise RuntimeError('Authorized task/campaign attempt cap reached')
                if any(row['init']==init for row in campaign_rows):
                    raise RuntimeError('Init already reserved in this campaign')
                reservation = dict(suite=args.suite, task=args.task_id, init=init,
                    attempt=count+1, campaign_attempt=len(campaign_rows)+1,
                    campaign=root.name, output=str(out), model='gpt-6-sol',
                    reasoning_effort='xhigh', purpose=args.purpose)
                for stream in (ledger,own):
                    stream.write(json.dumps(reservation)+'\n')
                    stream.flush()
                    os.fsync(stream.fileno())
        cmd = [SIM_PYTHON, '-B', str(frozen/'libero_jev_rollout.py'),
            '--suite', args.suite, '--task-id', str(args.task_id),
            '--init-index', str(init), '--output', str(out),
            '--wall-limit-seconds', '3600', '--max-jev-decisions',
            str(policy['max_decisions']), '--geometry-profile',
            policy['geometry_profile'], '--camera-size', str(policy['camera_size'])]
        if policy['mode']=='recovery':
            cmd += ['--recovery-supervisor', '--input-organization', 'focused',
                '--grasp-algorithm', 'pad_fit', '--preserve-source',
                '--execution-profile', 'adaptive', '--pad-overlap-mm', '6',
                '--table-margin-mm', '1', '--contact-angle-deg', '0']
        else:
            cmd += ['--jev-supervisor', '--schema', 'feedback',
                '--approach-mode', 'top', '--grasp-fraction', '.4']
            if args.profile=='soup':
                cmd.append('--lift-check')
        env = dict(os.environ, JEV_RSI_MODEL_BACKEND='codex_pro',
            JEV_RSI_PRO_BRIDGE_URL='http://127.0.0.1:7903')
        start = time.monotonic()
        termination = None
        with (root/f'{out.name}.log').open('w') as log:
            child = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env)
            while child.poll() is None:
                if time.monotonic()-start > 3660 or shutil.disk_usage(root).free < 4*1024**3:
                    termination = 'Runner wall/disk guard'
                    child.send_signal(signal.SIGINT)
                    try: child.wait(timeout=45)
                    except subprocess.TimeoutExpired: child.kill(); child.wait()
                    break
                try: child.wait(timeout=5)
                except subprocess.TimeoutExpired: pass
                except KeyboardInterrupt:
                    termination = 'Owned runner interrupted'
                    child.send_signal(signal.SIGINT)
                    try: child.wait(timeout=45)
                    except subprocess.TimeoutExpired: child.kill(); child.wait()
                    break
        result = json.loads((out/'result.json').read_text()) if (out/'result.json').exists() else dict(
            success=False, error='Setup/no result')
        row = dict(reservation, result=result, returncode=child.returncode,
            seconds=time.monotonic()-start, runner_termination=termination)
        rows.append(row)
        (root/'batch.json').write_text(json.dumps(rows, indent=2)+'\n')
        print(json.dumps(row), flush=True)
        events = [json.loads(s) for s in (out/'events.jsonl').read_text().splitlines()
            if s.strip()] if (out/'events.jsonl').exists() else []
        if (termination or any(e.get('kind')=='pro_bridge_transport_failure' for e in events)
                or 'Pro bridge HTTP error' in str(result.get('error'))):
            (root/'stopped.json').write_text(json.dumps(dict(reason=termination or
                'Pro bridge/model transport failure', episode=str(out)), indent=2)+'\n')
            raise RuntimeError('Stopped after infrastructure failure: '+str(out))
        if (out/'result.json').exists():
            audit_name = ('audit_libero_recovery.py' if policy['mode']=='recovery'
                else 'audit_libero_supervisor.py')
            with (out/'audit.stdout').open('w') as log:
                audit_return = subprocess.run([SIM_PYTHON, '-B', str(source/audit_name),
                    str(out), '--output', str(out/'audit.json')],
                    stdout=log, stderr=subprocess.STDOUT).returncode
            if audit_return != 0:
                raise RuntimeError('Action/input ownership audit failed: '+str(out))
            model_responses = sorted(out.glob('decision-*/response.json')) + sorted(
                out.glob('semantic-*/response.json'))
            if any((r.get('model'),r.get('reasoning_effort')) != ('gpt-6-sol','xhigh')
                    for r in (json.loads(p.read_text()) for p in model_responses)):
                raise RuntimeError('Recorded model/effort mismatch: '+str(out))
            (out/'pro-model-audit.json').write_text(json.dumps(dict(
                model='gpt-6-sol', reasoning_effort='xhigh',
                control_responses=len(list(out.glob('decision-*/response.json'))),
                visual_responses=len(list(out.glob('semantic-*/response.json'))),
                all_recorded_responses_match=True), indent=2)+'\n')
            row['archive'] = archive(out, remove_source=True)
            (root/'batch.json').write_text(json.dumps(rows, indent=2)+'\n')
        if sum(path.stat().st_size for path in root.rglob('*') if path.is_file())>3*1024**3:
            raise RuntimeError('Batch disk cap 3GiB')
    (root/'finished.json').write_text(json.dumps(dict(episodes=len(rows),
        complete_successes=sum(bool(r['result'].get('success') and
            r['result'].get('program_finished')) for r in rows)), indent=2)+'\n')


if __name__=='__main__':
    main()

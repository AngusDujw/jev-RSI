"""One foreground Luna/high GPT-only episode; preserve media and never retry a trial."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time


ROOT = Path('/home/ykj/project/gpt6/benchmark/gpt_as_policy_robodojo')
SOURCE = ROOT / 'runs/server02-policy-execution-20261019/official_runtime'
LOCAL = ROOT / 'runs/v4090-luna-high-stack-layout0-20261023-once'
REMOTE_BASE = '/home/v4090-1/DataStorage/gpt6-dec/gpt-as-policy-single'
REMOTE = REMOTE_BASE + '/v4090-luna-high-stack-layout0-20261023-once'
REMOTE_SOURCE = REMOTE_BASE + '/source-v4090-luna-high-20261023-once'
PORT = 25423
PYTHON = ROOT / '.venv/bin/python'
CODE = Path(__file__).resolve().parent


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def sensor_sync_gate(runtime):
    """Production preflight: fixed noncontact motions, no model or API calls."""
    import copy
    import cv2
    import numpy as np
    from PIL import Image
    sys.path.insert(0, str(runtime))
    from hybrid_rollout.robodojo.robodojo_server.gpt_only_client import GPTOnlyTools
    tools = GPTOnlyTools(LOCAL/'controller', 'stack_blocks', sim_port=PORT,
                         seed=0, max_decisions=0)
    def invoke(response=None):
        call = tools.next_call().copy()
        name = call.pop('tool')
        if response is not None:
            call['response'] = response
        return (tools.start if name == 'robodojo_start' else tools.act)(**call)
    def flow(a, b, rectangle):
        a = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
        b = cv2.cvtColor(b, cv2.COLOR_RGB2GRAY)
        mask = np.zeros_like(a)
        x0,y0,x1,y1 = rectangle
        mask[y0:y1, x0:x1] = 255
        points = cv2.goodFeaturesToTrack(a, 120, .01, 5, mask=mask)
        if points is None:
            raise RuntimeError('No trackable public-image features for sync gate')
        end, status, _ = cv2.calcOpticalFlowPyrLK(a,b,points,None,
            winSize=(31,31), maxLevel=4)
        back, reverse, _ = cv2.calcOpticalFlowPyrLK(b,a,end,None,
            winSize=(31,31), maxLevel=4)
        valid = (status.ravel()>0) & (reverse.ravel()>0)
        valid &= np.linalg.norm((back-points).reshape(-1,2),axis=1)<1.0
        delta = (end-points).reshape(-1,2)[valid]
        if len(delta)<6:
            raise RuntimeError('Too few consistent image tracks for sync gate')
        return dict(tracks=len(delta), median_motion_px=float(np.median(np.linalg.norm(delta,axis=1))),
                    median_delta_px=np.median(delta,axis=0).tolist())
    try:
        invoke()
        initial = copy.deepcopy(tools.current_eef())
        before = {k:tools.obs[k].copy() for k in tools.camera_keys}
        # Move away from the source cluster and upward, then change view yaw.
        for axis, amount in [(0,-.04),(2,.04),(1,.04),(None,.2)]:
            target = copy.deepcopy(tools.current_eef())
            for arm in target:
                target[arm] = {k:target[arm][k] for k in ('position','quaternion_wxyz')}
                target[arm]['gripper_closed'] = False
            if axis is None:
                w,x,y,z = target['right']['quaternion_wxyz']
                c,s = np.cos(amount/2),np.sin(amount/2)
                target['right']['quaternion_wxyz']=[float(c*w-s*z),float(c*x-s*y),float(c*y+s*x),float(c*z+s*w)]
            else:
                target['right']['position'][axis] += amount
            invoke(dict(mode='eef',request_id=tools.request['request_id'],steps=5,
                target=target,reason='Fixed noncontact sensor synchronization commissioning motion; no model inference.'))
        final = tools.current_eef()
        metrics = dict(
            right_displacement_m=float(np.linalg.norm(np.array(final['right']['position'])-initial['right']['position'])),
            left_displacement_m=float(np.linalg.norm(np.array(final['left']['position'])-initial['left']['position'])))
        metrics['high_hand']=flow(before['cam_high'],tools.obs['cam_high'],(510,268,612,310))
        metrics['right_wrist_background']=flow(before['cam_right_wrist'],tools.obs['cam_right_wrist'],(20,10,620,240))
        metrics['left_wrist_background']=flow(before['cam_left_wrist'],tools.obs['cam_left_wrist'],(20,10,620,240))
        passed=(metrics['right_displacement_m']>.01 and metrics['left_displacement_m']<.002
            and metrics['high_hand']['median_motion_px']>3
            and metrics['right_wrist_background']['median_motion_px']>3
            and metrics['left_wrist_background']['median_motion_px']<2)
        certificate=dict(passed=bool(passed),metrics=metrics,physical_steps=tools.tick,
            model_calls=0,scope='Robot render and wrist-camera movement commissioning, not task success or global correctness.',
            entry_sha256=hashlib.sha256((CODE/'v4090_luna_entry.py').read_bytes()).hexdigest())
        write(LOCAL/'sensor-sync-report.json',certificate)
        canvas=Image.new('RGB',(1920,960))
        for n,k in enumerate(tools.camera_keys):
            canvas.paste(Image.fromarray(before[k]),(n*640,0))
            canvas.paste(Image.fromarray(tools.obs[k]),(n*640,480))
        canvas.save(LOCAL/'sensor-sync-before-after.png')
        print(json.dumps(certificate),flush=True)
        if not passed:
            raise RuntimeError('Sensor synchronization commissioning failed; model run forbidden')
    finally:
        if tools.episode is not None:
            tools.finish('sensor_sync_commissioning')
        tools.close()


def prepare():
    if LOCAL.exists():
        raise FileExistsError('Single attempt already prepared; inspect it, never auto-restart')
    auth = json.loads((Path.home() / '.codex/auth.json').read_text())
    if auth.get('auth_mode') != 'chatgpt' or not auth.get('tokens') or auth.get('OPENAI_API_KEY'):
        raise RuntimeError('Local ChatGPT login required; API fallback forbidden')
    LOCAL.mkdir(parents=True)
    runtime = LOCAL / 'runtime'
    shutil.copytree(SOURCE / 'hybrid_rollout', runtime / 'hybrid_rollout',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    # Retain the original ordinary Luna/high policy and native image/tool access.
    # Remove evaluator fields from model-readable JSON, not from native scoring.
    io = runtime / 'hybrid_rollout/robodojo/io.py'
    text = io.read_text()
    text += '''\n\n# This run keeps evaluator feedback outside the policy workspace.\n_original_write_json = write_json\n_HIDDEN = {'success', 'native_success', 'native_score', 'reward', 'score', 'contact', 'contacts', 'object_pose', 'object_poses'}\ndef public_only(value):\n    if isinstance(value, dict):\n        return {k: public_only(v) for k, v in value.items() if k not in _HIDDEN}\n    if isinstance(value, list):\n        return [public_only(v) for v in value]\n    return value\ndef write_json(path, value):\n    return _original_write_json(path, public_only(value))\n'''
    io.write_text(text)
    policy = runtime / 'hybrid_rollout/robodojo/skill/run.py'
    text = policy.read_text().replace('visible_packet = packet\n', 'from ..io import public_only\n    packet = public_only(packet)\n    visible_packet = packet\n')
    policy.write_text(text)
    skill = runtime / 'hybrid_rollout/robodojo/robodojo-gpt-only-rollout/SKILL.md'
    text = skill.read_text().replace('when it becomes true, read the native outcome, which may also be failure.',
        'when it becomes true, stop. The host reports the native outcome separately; it is not policy input.')
    text = text.replace('briefly report the native outcome and saved paths, then end.',
        'briefly report the observed progress and saved paths, then end; do not invent the hidden native outcome.')
    skill.write_text(text)
    shutil.copyfile(CODE / 'server_entry.py', LOCAL / 'server_entry.py')
    home = LOCAL / 'private_pro_home'; home.mkdir(mode=0o700)
    fd = os.open(home / 'auth.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(auth, stream)
    (home / 'config.toml').write_text('model_provider = "openai"\nmodel = "gpt-6-luna"\nmodel_reasoning_effort = "high"\ncli_auth_credentials_store = "file"\nforced_login_method = "chatgpt"\n')
    files = {str(p.relative_to(runtime)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in runtime.rglob('*') if p.is_file()}
    write(LOCAL / 'launch.json', dict(host='v4090-t', task='stack_blocks', layout=0,
        model='gpt-6-luna', reasoning_effort='high', authentication='local ChatGPT Pro',
        evaluation_method='gpt_only', native_step_limit=550, attempts=1,
        preserve_images=True, preserve_video=True, api_fallback=False,
        evaluator_feedback_to_policy=False, remote=REMOTE, files=files))
    return runtime, home


def main():
    global LOCAL, REMOTE, REMOTE_SOURCE
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepared', action='store_true')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--recover-empty-startup', action='store_true')
    parser.add_argument('--run-name')
    parser.add_argument('--sensor-check', action='store_true')
    parser.add_argument('--sync-report', type=Path)
    args = parser.parse_args()
    if args.run_name:
        if not args.run_name.startswith('v4090-luna-high-stack-') or '/' in args.run_name or '..' in args.run_name:
            raise ValueError('Invalid isolated run name')
        LOCAL = ROOT/'runs'/args.run_name
        REMOTE = REMOTE_BASE+'/'+args.run_name
        REMOTE_SOURCE = REMOTE_BASE+'/source-'+args.run_name
    if not args.sensor_check and args.run_name:
        if args.sync_report is None:
            raise ValueError('A reviewed sensor synchronization report is required')
        report = json.loads(args.sync_report.read_text())
        if not report.get('passed') or report.get('entry_sha256') != hashlib.sha256((CODE/'v4090_luna_entry.py').read_bytes()).hexdigest():
            raise ValueError('Missing successful commissioning for this exact native entry')
    if args.recover_empty_startup:
        prior = LOCAL
        camera_prior = prior.with_name(prior.name + '-camera-extension')
        candidates = [p for p in prior.parent.glob(prior.name + '*')
                      if p.is_dir() and not p.is_symlink() and (p / 'attempt-started.json').exists()]
        if candidates:
            prior = max(candidates, key=lambda p: len(p.name))
        log = prior / 'server.log'
        if (prior / 'controller').exists() or not log.exists() or '"event": "ready"' in log.read_text():
            raise RuntimeError('Cannot replace a started policy episode')
        if not any(x in log.read_text() for x in ("No module named 'isaacsim.sensors'", "No module named 'isaacsim.replicator'", '.resolved_config.json.')):
            raise RuntimeError('Empty-startup recovery requires the recorded camera import failure')
        suffix = ('-sim-directory' if '.resolved_config.json.' in log.read_text() else
                  '-installed-extension-paths' if prior == camera_prior else '-camera-extension')
        LOCAL = prior.with_name(prior.name + suffix)
        REMOTE = REMOTE_BASE + '/' + LOCAL.name
        REMOTE_SOURCE = REMOTE_BASE + '/source-' + LOCAL.name
    if args.prepared:
        runtime, home = LOCAL / 'runtime', LOCAL / 'private_pro_home'
        if (LOCAL / 'attempt-started.json').exists():
            raise RuntimeError('One attempt already started; no rerun')
    else:
        runtime, home = prepare()
    if args.prepare_only:
        print(json.dumps(dict(event='prepared', local=str(LOCAL))), flush=True)
        return
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(('OPENAI_', 'CODEX_API_')):
            env.pop(key)
    (LOCAL / 'tmp').mkdir(exist_ok=True)
    env.update(CODEX_HOME=str(home), ROLLOUT_AUTH_PROFILE='codex_a',
        ROLLOUT_EVALUATION_METHOD='gpt_only', ROLLOUT_CODEX_STATE_DIR=str(LOCAL / 'codex_state'),
        PYTHONPATH=str(runtime), TMPDIR=str(LOCAL / 'tmp'))
    subprocess.run(['ssh', '-o', 'ConnectTimeout=15', '--', 'v4090-t',
        'mkdir -p ' + shlex.quote(REMOTE_BASE) + ' && test ! -e ' + shlex.quote(REMOTE)
        + ' && mkdir ' + shlex.quote(REMOTE_SOURCE)], check=True)
    # Native scoring uses the unchanged original runtime, never the policy's
    # public-feedback filter. Only the local actor copy is sanitized.
    subprocess.run(['rsync', '-rl', str(SOURCE), str(LOCAL / 'server_entry.py'), str(CODE / 'v4090_luna_entry.py'),
                    str(CODE / 'v4090_luna_single_server.py'), 'v4090-t:' + REMOTE_SOURCE + '/'], check=True)
    remote_command = shlex.join(['python3', REMOTE_SOURCE + '/v4090_luna_single_server.py',
                                REMOTE, REMOTE_SOURCE + '/official_runtime', str(PORT)])
    write(LOCAL / 'attempt-started.json', dict(time=time.time(), attempts=1, command=remote_command))
    sim = controller = None
    with (LOCAL / 'server.log').open('w') as slog, (LOCAL / 'controller.log').open('w') as clog:
        try:
            sim = subprocess.Popen(['ssh', '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15',
                '-o', 'ServerAliveCountMax=4', '-o', 'ExitOnForwardFailure=yes',
                '-L', f'127.0.0.1:{PORT}:127.0.0.1:{PORT}', '--', 'v4090-t', remote_command],
                stdout=slog, stderr=subprocess.STDOUT)
            print(json.dumps(dict(event='native_starting', ssh_pid=sim.pid, local=str(LOCAL), remote=REMOTE)), flush=True)
            deadline = time.monotonic() + 1200
            while time.monotonic() < deadline:
                if sim.poll() is not None:
                    raise RuntimeError('Native startup failed; inspect server.log; no second attempt')
                if '"event": "ready"' in (LOCAL / 'server.log').read_text(errors='replace'):
                    break
                time.sleep(3)
            else:
                raise TimeoutError('Native RPC readiness deadline')
            if '"event": "simulation_sync_config"' not in (LOCAL/'server.log').read_text():
                raise RuntimeError('Native server did not confirm synchronization configuration')
            if args.sensor_check:
                sensor_sync_gate(runtime)
                return
            controller = subprocess.Popen([str(PYTHON), '-B', '-u', '-m', 'hybrid_rollout.robodojo.skill.run',
                '--output', str(LOCAL / 'controller'), '--task', 'stack_blocks',
                '--evaluation-method', 'gpt_only', '--codex', shutil.which('codex'),
                '--sim-port', str(PORT), '--seed', '0', '--max-decisions', '0'],
                cwd=runtime, env=env, stdout=clog, stderr=subprocess.STDOUT)
            while controller.poll() is None:
                progress = LOCAL / 'controller/progress.json'
                write(LOCAL / 'status.json', dict(time=time.time(), controller_pid=controller.pid,
                    ssh_pid=sim.pid, progress=json.loads(progress.read_text()) if progress.exists() else {},
                    preserve_media=True, attempts=1))
                print((LOCAL / 'status.json').read_text(), flush=True)
                time.sleep(15)
            write(LOCAL / 'controller-exit.json', dict(returncode=controller.returncode))
            try:
                sim.wait(timeout=180)
            except subprocess.TimeoutExpired:
                sim.terminate(); sim.wait(timeout=30)
        finally:
            if controller is not None and controller.poll() is None:
                controller.terminate(); controller.wait(timeout=90)
            if sim is not None and sim.poll() is None:
                sim.terminate(); sim.wait(timeout=30)
            # Preserve both raw controller images and videos; never run the old pruner.
            subprocess.run(['rsync', '-rl', '--exclude=private_pro_home/', '--exclude=codex_state/',
                '--exclude=tmp/', str(LOCAL) + '/', 'v4090-t:' + REMOTE + '/local-controller-archive/'], check=False)
            subprocess.run(['rsync', '-rl', 'v4090-t:' + REMOTE + '/sim/', str(LOCAL / 'native-results') + '/'], check=False)
    print(json.dumps(dict(event='single_attempt_finished', local=str(LOCAL), remote=REMOTE)), flush=True)


if __name__ == '__main__':
    main()

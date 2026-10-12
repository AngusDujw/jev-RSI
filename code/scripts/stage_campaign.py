"""Durable 1000-attempt ledger and isolated RoboDojo launches."""
import argparse
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
from company_campaign import write, stop_child


def archive_completed_logs(out):
    """Losslessly archive only this closed episode's large inference evidence."""
    files=list((out/'policy').glob('planner-input-*.json'))+[out/'experience-bank.jsonl',out/'policy/events.jsonl']
    reclaimed=0
    for path in files:
        if not path.is_file() or path.stat().st_size<131072:
            continue
        destination=path.with_suffix(path.suffix+'.gz')
        pending=path.with_suffix(path.suffix+'.archive-in-progress')
        if destination.exists():
            raise FileExistsError(destination)
        raw=path.read_bytes()
        with pending.open('xb') as stream:
            stream.write(gzip.compress(raw,compresslevel=6))
        if hashlib.sha256(gzip.decompress(pending.read_bytes())).digest()!=hashlib.sha256(raw).digest():
            raise ValueError('Closed-episode archive verification failed')
        pending.replace(destination)
        reclaimed+=len(raw)-destination.stat().st_size
        path.unlink()
    return dict(reclaimed_bytes=reclaimed,verification='decompressed SHA256 equals original')


def reserve(folder, case, variant):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder/'ledger.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = folder/'ledger.json'
        ledger = json.loads(path.read_text()) if path.exists() else dict(max_attempts=1000, attempts=[])
        if len(ledger['attempts']) >= ledger['max_attempts']:
            raise RuntimeError('1000-attempt budget exhausted')
        number = len(ledger['attempts'])
        entry = dict(attempt=number, case=case, variant=variant, time=time.time(), status='reserved')
        ledger['attempts'].append(entry)
        write(path, ledger)
        return number


def ensure_launch_available(cfg):
    """Reject a held campaign or unavailable GPUs before reserving an attempt."""
    hold = Path(cfg['campaign'])/'LAUNCH_HOLD.json'
    if hold.exists():
        raise RuntimeError('Native launches held; inspect '+str(hold))
    enabled = cfg.get('preflight_gpu_health', False)
    if type(enabled) is not bool:
        raise ValueError('preflight_gpu_health must be boolean')
    if not enabled:
        return
    gpu_ids = cfg.get('gpu_ids', [])
    if not gpu_ids or any(type(gpu) is not int or gpu < 0 for gpu in gpu_ids):
        raise ValueError('gpu_ids must contain nonnegative integer device indices')
    try:
        check = subprocess.run(
            ['nvidia-smi', '--query-gpu=index,uuid', '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('GPU health preflight unavailable') from exc
    if check.returncode:
        raise RuntimeError('GPU health preflight failed; no native attempt reserved')
    present = set()
    for line in check.stdout.splitlines():
        fields = [field.strip() for field in line.split(',')]
        if len(fields) != 2 or not fields[0].isdigit() or not fields[1].startswith('GPU-'):
            raise RuntimeError('Invalid GPU health inventory; no native attempt reserved')
        present.add(int(fields[0]))
    if not set(gpu_ids) <= present:
        raise RuntimeError('Configured GPU missing; no native attempt reserved')


def cleanup_children(policy, server):
    """Retain outcomes even when a failed device prevents process cleanup."""
    errors=[]
    for role,process in (('policy',policy),('simulator',server)):
        try:
            stop_child(process)
        except (OSError,subprocess.TimeoutExpired) as exc:
            errors.append(dict(role=role,pid=process.pid if process is not None else None,
                               error_type=type(exc).__name__,error=str(exc)[:1000]))
    return errors


def run_one(cfg, case, campaign):
    root = Path(cfg['root']); code = Path(cfg['controller_root'])
    if not campaign.resolve().is_relative_to(root.resolve()):
        raise ValueError('Campaign artifacts must stay on the RoboDojo data mount')
    if cfg.get('observation_mode') != 'vision' or cfg.get('planner_prompt_mode') != 'vision_method_v1':
        raise ValueError('This campaign requires the sensor-only visual method planner')
    policy_python = cfg.get('policy_python', cfg['sim_python'])
    ensure_launch_available(cfg)
    if cfg.get('planner_prompt_mode','full') not in ('full','compact_contract','legacy_v11','legacy_v11_adaptive','legacy_v11_protected','legacy_v11_compliant','legacy_v11_measured_reuse','legacy_v11_retention','legacy_v11_conditional_reuse','legacy_v11_contact_progress','legacy_v11_task_frame_progress','legacy_v11_anchored_approach','legacy_v11_contact_recovery','vision_v1','vision_method_v1'):
        raise ValueError('Unknown planner prompt mode')
    observation_mode = cfg.get('observation_mode', 'oracle')
    if observation_mode != 'vision':
        raise ValueError('Oracle observation is forbidden for this campaign')
    if observation_mode == 'vision' and cfg.get('reviewed_plan'):
        raise ValueError('Vision trials require a fresh GPT plan from current RGB evidence')
    if cfg.get('experience_context_mode','mixed') not in ('mixed','validated_first','executed_first','efficient_executed','matched_executed','matched_recent_executed'):
        raise ValueError('Unknown planner experience mode')
    if 'stage_contract_reuse' in cfg and type(cfg['stage_contract_reuse']) is not bool:
        raise ValueError('stage_contract_reuse must be boolean')
    if 'stage_entry_contracts' in cfg and type(cfg['stage_entry_contracts']) is not bool:
        raise ValueError('stage_entry_contracts must be boolean')
    if 'decision_hold_stall_actions' in cfg and (type(cfg['decision_hold_stall_actions']) is not int or cfg['decision_hold_stall_actions']<1):
        raise ValueError('decision_hold_stall_actions must be a positive integer')
    if cfg.get('numeric_threads') is not None and (type(cfg['numeric_threads']) is not int or not 1<=cfg['numeric_threads']<=16):
        raise ValueError('numeric_threads must be an integer from 1 through 16')
    cpus=cfg.get('cpu_ids',[])
    if any(type(c) is not int for c in cpus) or not set(cpus)<=os.sched_getaffinity(0) or len(set(cpus))!=len(cpus):
        raise ValueError('cpu_ids must be distinct available CPU IDs')
    if shutil.disk_usage(root).free < cfg['minimum_free_gb']*1e9:
        raise RuntimeError('Filesystem reserve reached before launch')
    if cfg.get('preflight_api_connections',False):
        for attempt in range(3):
            check=subprocess.run([policy_python,'-m','realman_jev.stage_network','--config',cfg['api_config']],
                cwd=code,env=dict(os.environ,PYTHONPATH=str(code/'src')),capture_output=True,text=True,timeout=45)
            if not check.returncode:
                break
            detail=check.stderr.strip().splitlines()
            message=detail[-1][:200] if detail else 'unknown connectivity error'
            if attempt == 2:
                raise RuntimeError('API connectivity preflight failed after 3 tries: '+message)
            print(f'API connectivity preflight retry {attempt+1}/2: {message}', flush=True)
            time.sleep(5)
    port = cfg['base_port']
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', port))
    layout = root/'robodojo'/case['layout']
    import hashlib
    if hashlib.sha256(layout.read_bytes()).hexdigest() != case['layout_sha256']:
        raise ValueError('Frozen layout mismatch')
    commit=subprocess.check_output(['git','-C',str(code),'rev-parse',cfg.get('controller_commit','HEAD')+'^{commit}'],text=True).strip()
    archived=subprocess.check_output(['git','-C',str(code.parent),'archive',commit,
        'code/src/realman_jev','code/config/staged-task-specs.json','code/experience'])
    number = reserve(campaign, case, cfg.get('variant', 'relational-v1'))
    out = campaign/f'{number:04d}-{case["runtime_task"]}-{case["layout_id"]}'
    out.mkdir(exist_ok=False); (out/'sim').mkdir()
    snapshot=out/'controller_snapshot';snapshot.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archived)) as archive:
        members=archive.getmembers()
        if any(Path(m.name).is_absolute() or '..' in Path(m.name).parts or not (m.isfile() or m.isdir()) for m in members):
            raise ValueError('Controller snapshot contains non-regular or escaping entries')
        archive.extractall(snapshot,members=members)
    experience_source=Path(cfg.get('experience_bank_path',str(campaign/'experience.jsonl')))
    with (campaign/'ledger.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_SH)
        experience_bytes=experience_source.read_bytes() if experience_source.exists() else b''
    experience_snapshot=out/'experience-bank.jsonl'
    experience_snapshot.write_bytes(experience_bytes)
    cfg=dict(cfg,task_specs=str(snapshot/'code/config/staged-task-specs.json'),
        experience_notes_root=str(snapshot/'code/experience'),
        experience_bank_path=str(experience_snapshot),experience_bank_sha256=hashlib.sha256(experience_bytes).hexdigest())
    write(out/'case.json', case); write(out/'config.json', cfg)
    cache=campaign/'cache'
    for folder in (cache/'tmp',cache/'xdg',cache/'torch-extensions',cache/'kit-extensions'):
        folder.mkdir(parents=True,exist_ok=True)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(snapshot/'code/src'),str(root/'GPT-as-Policy'),str(root/'robodojo'),str(root/'robodojo/XPolicyLab')]),
        TMPDIR=str(cache/'tmp'), XDG_CACHE_HOME=str(cache/'xdg'),TORCH_EXTENSIONS_DIR=str(cache/'torch-extensions'),
        ROBO_PROJECT_ROOT=str(root), ISAAC_JOB_CACHE=str(cache),
        OMNI_KIT_ACCEPT_EULA='YES', ACCEPT_EULA='Y', PYTHONNOUSERSITE='1',
        CUDA_VISIBLE_DEVICES=str(cfg['gpu_ids'][0]), COMPANY_OBSERVATION=observation_mode,
        COMPANY_LAYOUT_SHA256=case['layout_sha256'], COMPANY_LAYOUT_PATH=str(layout.resolve()),
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    if cfg.get('numeric_threads'):
        for name in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS'):
            env[name]=str(cfg['numeric_threads'])
    simcmd = [cfg['sim_python'],'-u','-m','realman_jev.stage_bridge','--task',case['runtime_task'],
              '--eval-seed',str(case['eval_seed']),'--output',str(out/'sim'),'--port',str(port),
              '--headless','--enable_cameras','--device','cuda:0',
              f'--kit_args=--/exts/omni.kit.registry.nucleus/cachePath={cache}/kit-extensions '
              f'--ext-folder={root}/.cache/kit-extensions/v2 '
              f'--/renderer/activeGpu={cfg.get("renderer_gpu_id", cfg["gpu_ids"][0])} --/renderer/multiGpu/enabled=false '
              '--/app/updateOrder/checkForHydraRenderComplete=1000 --/app/renderer/waitIdle=true --/app/hydraEngine/waitIdle=true']
    policycmd = [policy_python,'-u','-m','realman_jev.stage_policy','--config',str(out/'config.json'),
                 '--case',str(out/'case.json'),'--output',str(out/'policy'),'--port',str(port),'--api-config',cfg['api_config']]
    if cpus:
        prefix=['taskset','-c',','.join(map(str,cpus))]
        simcmd=prefix+simcmd;policycmd=prefix+policycmd
    write(out/'launch.json',dict(sim=simcmd,policy=policycmd,controller_commit=commit,
                               immutable_controller_snapshot=str(snapshot),
                               immutable_experience_snapshot=str(experience_snapshot)))
    server = policy = None
    started = time.monotonic()
    try:
        with (out/'server.log').open('w') as s, (out/'policy.log').open('w') as p:
            server = subprocess.Popen(simcmd,cwd=root/'robodojo',env=env,stdout=s,stderr=subprocess.STDOUT,start_new_session=True)
            while '"event": "ready"' not in (out/'server.log').read_text(errors='replace'):
                if server.poll() is not None:
                    raise RuntimeError('Simulator exited before ready')
                if time.monotonic()-started > cfg['startup_timeout_s']:
                    raise TimeoutError('Startup timeout')
                time.sleep(2)
            policy = subprocess.Popen(policycmd,cwd=code,env=env,stdout=p,stderr=subprocess.STDOUT,start_new_session=True)
            write(out/'processes.json',dict(simulator_pid=server.pid,policy_pid=policy.pid))
            while policy.poll() is None:
                if server.poll() is not None:
                    raise RuntimeError('Simulator exited during policy')
                if Path(cfg['stop_file']).exists() or time.monotonic()-started > cfg['timeout_s']+cfg['startup_timeout_s']:
                    raise RuntimeError('Stopped or hard timeout')
                if shutil.disk_usage(root).free < cfg['minimum_free_gb']*1e9:
                    raise RuntimeError('Filesystem reserve reached')
                time.sleep(3)
            result = json.loads((out/'policy/summary.json').read_text())
            try:
                server.wait(timeout=30)
            except subprocess.TimeoutExpired:
                pass
            native = json.loads((out/'sim/evaluation_outcome.json').read_text())
            result['native_evaluation'] = native
            result['verified_success'] = native.get('valid_for_success_rate') is True and native.get('native_success') is True
    except Exception as exc:
        result = dict(status='infrastructure_error',error_type=type(exc).__name__,error=str(exc),verified_success=False)
    finally:
        cleanup_errors = cleanup_children(policy,server)
    if cleanup_errors:
        result['process_cleanup_errors'] = cleanup_errors
    result.update(attempt=number,elapsed_s=time.monotonic()-started,case=case)
    # Store actual outcomes and GPT plan revisions as planner-only experience.
    # Never expose native results to Jev or use them to select an action.
    plans=[json.loads(p.read_text()) for p in sorted((out/'policy').glob('plan-[0-9]*.json'))]
    event_path=out/'policy/events.jsonl'
    events=[json.loads(line) for line in event_path.read_text().splitlines()] if event_path.exists() else []
    failures=[{k:v for k,v in e.items() if k not in ('rejected_plan','current','entry')}
              for e in events if e.get('kind') in ('stage_failed','plan_rejected','stage_entry_blocked','error')][-3:]
    executed=[e for e in events if e.get('kind')=='execution']
    record=dict(task=case['task'],layout_sha256=case['layout_sha256'],
                verified_native_success=result['verified_success'],status=result['status'],
                plans=plans,failure_events=failures,final_physical_state=executed[-1]['current'] if executed else None,
                source=str(out),observation=observation_mode)
    if cfg.get('archive_completed_logs',False):
        try:
            result['log_archival']=archive_completed_logs(out)
        except (OSError,ValueError,EOFError) as exc:
            result['log_archival']=dict(error_type=type(exc).__name__,error=str(exc))
    write(out/'result.json',result)
    with (campaign/'ledger.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        ledger=json.loads((campaign/'ledger.json').read_text())
        ledger['attempts'][number].update(status=result['status'],verified_success=result['verified_success'],output=str(out))
        write(campaign/'ledger.json',ledger)
        with (campaign/'experience.jsonl').open('a') as stream:
            stream.write(json.dumps(record)+'\n')
    print(json.dumps(result),flush=True)
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--task',required=True)
    p.add_argument('--layout',type=int,default=0);p.add_argument('--count',type=int,default=1)
    args=p.parse_args();cfg=json.loads(Path(args.config).read_text())
    manifest=json.loads(Path(cfg['manifest']).read_text())
    cases=[c for c in manifest['cases'] if c['runtime_task']==args.task and c['layout_id']==args.layout]
    if len(cases)!=1:raise ValueError('Expected one frozen case')
    for _ in range(args.count):run_one(cfg,cases[0],Path(cfg['campaign']))


if __name__=='__main__':main()

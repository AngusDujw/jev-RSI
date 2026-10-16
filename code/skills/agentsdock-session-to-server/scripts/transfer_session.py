#!/usr/bin/env python3
"""One-way, selected-thread Codex/AgentsDock migration. Python standard library only."""
import argparse
import collections
import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import uuid


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def snapshot(source, dest):
    """Copy only the immutable prefix visible at open time; discard a partial tail."""
    with source.open('rb') as src, dest.open('xb') as out:
        remaining = os.fstat(src.fileno()).st_size
        while remaining:
            line = src.readline(remaining)
            remaining -= len(line)
            if not line or not line.endswith(b'\n'):
                break
            json.loads(line)
            out.write(line)
    os.chmod(dest, 0o600)


def sessions(home):
    path = home / '.agentsdock/sessions.json'
    data = json.loads(path.read_text()) if path.exists() else {}
    return list(data.values()) if isinstance(data, dict) else data


def select(home, query):
    matches = [s for s in sessions(home) if query in
               (s.get('id'), s.get('codex_thread_id'), s.get('session_id'), s.get('title'))]
    if len(matches) != 1:
        raise ValueError('Select one exact AgentsDock ID, Codex UUID, or unambiguous title; use list first.')
    s = matches[0]
    if s.get('backend') != 'codex':
        raise ValueError('Only Codex sessions are supported.')
    thread = str(s.get('codex_thread_id') or s.get('session_id') or '')
    uuid.UUID(thread)
    files = list((home / '.codex/sessions').rglob('*-' + thread + '.jsonl'))
    if len(files) != 1:
        raise ValueError('Expected exactly one native rollout for this thread.')
    return s, files[0]


def pack_registered_files(home, source_id, events, root):
    ids = set()
    for line in events.open():
        event = json.loads(line)
        ids.update(event.get('file_ids') or [])
        for key in ('file', 'artifact'):
            record = event.get(key)
            if isinstance(record, dict) and record.get('id'):
                ids.add(record['id'])
    selected = []
    with tarfile.open(root / 'registered-files.tar', 'w') as tar:
        for fid in sorted(ids):
            if not re.fullmatch(r'(?:art|file)_[A-Za-z0-9_-]+', fid):
                continue
            base = home / '.agentsdock/files' / fid
            meta = base / 'meta.json'
            if not meta.is_file():
                continue
            record = json.loads(meta.read_text())
            if record.get('session_id') != source_id:
                continue
            files = []
            for path in sorted(base.iterdir()):
                if path.is_file() and not path.is_symlink():
                    tar.add(path, arcname=fid + '/' + path.name, recursive=False)
                    files.append({'name': path.name, 'bytes': path.stat().st_size, 'sha256': digest(path)})
            selected.append({'id': fid, 'files': files})
    (root / 'registered-files-manifest.json').write_text(json.dumps(selected, indent=2))
    return selected


def install_registered_files(root, state, sid):
    archive = root / 'registered-files.tar'
    if not archive.exists():
        return
    base = root / 'registered-files'
    base.mkdir(exist_ok=True)
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            p = Path(member.name)
            if not member.isfile() or len(p.parts) != 2 or '..' in p.parts or not re.fullmatch(r'(?:art|file)_[A-Za-z0-9_-]+', p.parts[0]):
                raise ValueError('Unsafe registered file member.')
            out = base / p
            out.parent.mkdir(exist_ok=True)
            if out.exists():
                raise ValueError('Registered file staging collision.')
            with tar.extractfile(member) as src, out.open('xb') as dst:
                shutil.copyfileobj(src, dst)
    selected = json.loads((root / 'registered-files-manifest.json').read_text())
    (state / 'files').mkdir(exist_ok=True)
    for record in selected:
        folder = base / record['id']
        for f in record['files']:
            if digest(folder / f['name']) != f['sha256']:
                raise ValueError('Registered attachment checksum mismatch.')
        meta = folder / 'meta.json'
        data = json.loads(meta.read_text())
        data['session_id'] = sid
        data['path'] = str(folder / Path(data['path']).name)
        meta.write_text(json.dumps(data, indent=2))
        link = state / 'files' / record['id']
        if link.exists() or link.is_symlink():
            raise ValueError('Destination file ID collision.')
        link.symlink_to(folder, target_is_directory=True)


def map_event(row, source_id, sid, root):
    if isinstance(row, dict):
        for key, value in row.items():
            if key == 'session_id' and value == source_id:
                row[key] = sid
            elif key == 'path' and isinstance(value, str) and '/.agentsdock/files/' in value:
                suffix = value.split('/.agentsdock/files/', 1)[1]
                if '..' not in Path(suffix).parts:
                    row[key] = str(root / 'registered-files' / suffix)
            else:
                map_event(value, source_id, sid, root)
    elif isinstance(row, list):
        for value in row:
            map_event(value, source_id, sid, root)


def export(args):
    home = Path.home()
    source, rollout = select(home, args.session or os.environ.get('CODEX_THREAD_ID'))
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    root = Path(args.output).expanduser() / (source['id'] + '-' + stamp)
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    snapshot(rollout, root / 'native.jsonl')
    source_dir = home / '.agentsdock/sessions' / source['id']
    snapshot(source_dir / 'events.jsonl', root / 'events.jsonl')
    pack_registered_files(home, source['id'], root / 'events.jsonl', root)
    # Only this conversation's attachment/publication files. Never follow external links.
    with tarfile.open(root / 'attachments.tar.gz', 'w:gz') as tar:
        for name in ('uploads', 'artifact_publications', 'manifests'):
            base = source_dir / name
            if base.exists():
                for p in sorted(base.rglob('*')):
                    if p.is_file() and not p.is_symlink():
                        tar.add(p, arcname=str(p.relative_to(source_dir)), recursive=False)
    with (root / 'native.jsonl').open('rb') as f:
        head = json.loads(f.readline())
    thread = source.get('codex_thread_id') or source.get('session_id')
    if head.get('payload', {}).get('id') != thread:
        raise ValueError('Native rollout identity does not match the selected chat.')
    counts = collections.Counter()
    with (root / 'native.jsonl').open('rb') as f:
        for line in f:
            counts[json.loads(line).get('type')] += 1
    manifest = {
        'format': 1, 'created_at': stamp, 'thread_id': thread,
        'source_session_id': source['id'], 'title': source['title'],
        'source_cwd': source.get('cwd'), 'remote_cwd': args.remote_cwd,
        'model': source.get('model'), 'effort': source.get('effort'),
        'native_relative_path': str(rollout.relative_to(home / '.codex/sessions')),
        'native_record_counts': dict(counts),
        'files': {p.name: {'sha256': digest(p), 'bytes': p.stat().st_size}
                  for p in root.iterdir() if p.is_file()},
        'snapshot_note': 'Complete lines at snapshot time. No later local messages are synchronized.',
    }
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    with (root / 'native.jsonl').open('rb') as src, gzip.open(root / 'native.jsonl.gz', 'wb') as dst:
        shutil.copyfileobj(src, dst)
    emit({'export': str(root), 'records': sum(counts.values()), 'native_bytes': (root / 'native.jsonl').stat().st_size})
    return root


def api_client(base, env_file):
    env = {}
    for line in Path(env_file).expanduser().read_text().splitlines():
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            parts = shlex.split(value)
            env[key] = parts[0] if parts else ''
    token = env.get('AGENTSDOCK_AGENT_TOKEN', '')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(method, path, body=None):
        req = urllib.request.Request(base.rstrip('/') + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, method=method)
        with opener.open(req, timeout=180) as response:
            return json.load(response)
    return request


def import_remote(args):
    if not args.allow_native_home:
        raise ValueError('Native history uses the home filesystem. Obtain authorization and pass --allow-native-home.')
    root = Path(args.bundle).resolve()
    m = json.loads((root / 'manifest.json').read_text())
    receipt = root / 'receipt.json'
    api = api_client(args.api, args.env_file)
    if receipt.exists():
        r = json.loads(receipt.read_text())
        runtime = validate_runtime(api, r['destination_session_id'])
        verify_timeline(Path(r['ui_data']) / 'events.jsonl')
        r['native_loaded'] = True
        receipt.write_text(json.dumps(r, indent=2))
        emit({'already_imported': True, 'receipt': str(receipt), 'session_id': r['destination_session_id']})
        return
    native_source = root / 'native.jsonl'
    if not native_source.exists():
        with gzip.open(root / 'native.jsonl.gz', 'rb') as src, native_source.open('xb') as dst:
            shutil.copyfileobj(src, dst)
    for name, expected in m['files'].items():
        if Path(name).name != name or digest(root / name) != expected['sha256']:
            raise ValueError('Bundle integrity failure: ' + name)
    cwd = Path(m['remote_cwd'])
    if not cwd.is_absolute() or not cwd.is_dir():
        raise ValueError('Destination working directory must exist; project files are not included in the export.')
    existing = api('GET', '/api/sessions?summary=true')['sessions']
    if any(m['thread_id'] in (s.get('codex_thread_id'), s.get('session_id')) for s in existing):
        raise ValueError('Destination already owns this native thread. Refusing to overwrite or attach a second chat.')
    relative = Path(m['native_relative_path'])
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Unsafe native path.')
    target = Path.home() / '.codex/sessions' / relative
    if target.exists():
        raise ValueError('Native rollout already exists; inspect the previous import before retrying.')
    target.parent.mkdir(parents=True, exist_ok=True)
    # Preserve message/tool text exactly. Remap only execution-context path metadata.
    counts = collections.Counter()
    with native_source.open('rb') as src, target.open('xb') as dst:
        for line in src:
            row = json.loads(line)
            kind = row.get('type')
            counts[kind] += 1
            if kind in ('session_meta', 'turn_context'):
                payload = row.get('payload', {})
                if 'cwd' in payload:
                    payload['cwd'] = str(cwd)
                if 'runtime_workspace_roots' in payload:
                    payload['runtime_workspace_roots'] = [str(cwd)]
                line = (json.dumps(row, ensure_ascii=False) + '\n').encode()
            dst.write(line)
    os.chmod(target, 0o600)
    if dict(counts) != m['native_record_counts']:
        raise ValueError('Native record counts changed.')
    # Official API creates clean inactive metadata; never edit a running server's sessions.json.
    body = {'title': m['title'] + ' [from local ' + m['created_at'] + ']',
        'cwd': str(cwd), 'backend': 'codex', 'codex_thread_id': m['thread_id'],
        'import_history': False}
    if m.get('model'):
        body['model'] = m['model']
    if m.get('effort'):
        body['effort'] = m['effort']
    session = api('POST', '/api/sessions', body)['session']
    sid = session['id']
    # Stage a complete UI history before loading the newly-created chat. This bypasses
    # AgentDock's 256 MiB / 2000-message native import caps without changing its server.
    state = Path(args.state_dir).expanduser()
    ui_link = state / 'sessions' / sid
    if ui_link.is_symlink():
        raise ValueError('New session directory unexpectedly is a symlink.')
    initial_events = ui_link / 'events.jsonl'
    if initial_events.exists():
        for line in initial_events.open():
            if json.loads(line).get('type') != 'session_created':
                raise ValueError('New chat was opened or modified concurrently. Refusing to overwrite.')
    ui_data = root / 'agentsdock-session'
    if ui_data.exists():
        raise ValueError('UI staging directory already exists.')
    if ui_link.exists():
        shutil.move(str(ui_link), str(ui_data))
    else:
        ui_data.mkdir()
    ui_link.symlink_to(ui_data, target_is_directory=True)
    n = 0
    live_runs = set()
    with (root / 'events.jsonl').open() as src, (ui_data / 'events.jsonl').open('w') as dst:
        for line in src:
            row = json.loads(line)
            map_event(row, m['source_session_id'], sid, root)
            row['session_id'] = sid
            if row.get('type') == 'session_created':
                row['session'] = session
            if row.get('type') == 'turn_started':
                live_runs.add(row.get('run_id'))
            if row.get('type') == 'turn_finished':
                live_runs.discard(row.get('run_id'))
            n = max(n, row.get('seq', 0))
            dst.write(json.dumps(row, ensure_ascii=False) + '\n')
        for run_id in live_runs:
            n += 1
            dst.write(json.dumps({'seq': n, 'id': 'evt_' + uuid.uuid4().hex[:16],
                'session_id': sid, 'type': 'turn_finished', 'run_id': run_id,
                'ts': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'backend': 'codex', 'stopped': True, 'migration_snapshot': True,
                'result_text': 'Migration snapshot ended during a local turn. No remote turn was started.'}) + '\n')
    # Discard only the freshly-created index owned by this import; it will be rebuilt.
    idx = ui_data / 'events.idx'
    if idx.exists():
        idx.unlink()
    with tarfile.open(root / 'attachments.tar.gz') as tar:
        for member in tar.getmembers():
            p = Path(member.name)
            if not member.isfile() or p.is_absolute() or '..' in p.parts or p.parts[0] not in ('uploads', 'artifact_publications', 'manifests'):
                raise ValueError('Unsafe attachment member.')
            out = ui_data / p
            out.parent.mkdir(parents=True, exist_ok=True)
            if out.exists():
                raise ValueError('Attachment collision.')
            with tar.extractfile(member) as src, out.open('xb') as dst:
                shutil.copyfileobj(src, dst)
    for directory in ('artifact_publications', 'manifests'):
        for path in (ui_data / directory).rglob('*.json'):
            metadata = json.loads(path.read_text())
            map_event(metadata, m['source_session_id'], sid, root)
            path.write_text(json.dumps(metadata, ensure_ascii=False))
    result = {'destination_session_id': sid, 'thread_id': m['thread_id'],
        'title': body['title'], 'cwd': str(cwd), 'native_path': str(target),
        'native_sha256': digest(target), 'native_record_counts': dict(counts),
        'ui_events': n, 'ui_data': str(ui_data), 'native_loaded': False}
    # Save the recovery receipt before resume: failed runtime validation can be retried safely.
    receipt.write_text(json.dumps(result, indent=2))
    install_registered_files(root, state, sid)
    repair_sequence_cache(api, sid, ui_data)
    emit({'registered': sid, 'events': n, 'resuming_without_model_call': True})
    runtime = validate_runtime(api, sid)
    result['ui_events_after_maintenance'] = verify_timeline(ui_data / 'events.jsonl')
    (root / 'runtime-validation.json').write_text(json.dumps(runtime, indent=2))
    result['native_loaded'] = True
    receipt.write_text(json.dumps(result, indent=2))
    emit(result)


def verify_timeline(path):
    previous = 0
    count = 0
    with path.open() as source:
        for line in source:
            seq = int(json.loads(line).get('seq', 0))
            if seq <= previous:
                raise ValueError('Imported timeline sequences are not strictly increasing.')
            previous = seq
            count += 1
    return count


def validate_runtime(api, sid):
    runtime = api('POST', '/api/sessions/' + sid + '/codex/load', {})
    if not runtime.get('thread_loaded') or runtime.get('status', {}).get('type') != 'idle':
        raise ValueError('Native thread did not load idle; inspect runtime without starting a model turn.')
    if runtime.get('goal') or runtime.get('pending_interactions'):
        raise ValueError('Unexpected active goal or pending interaction in imported chat.')
    return runtime


def repair_sequence_cache(api, sid, ui_data):
    """Use the server's own per-chat maintenance lock to refresh its sequence cache.

    An intentionally empty imported marker is removed by the supported pruning
    endpoint, which also persists the sequence high-water mark and resets caches.
    Original raw events remain in the bundle; duplicate imported display rows may
    be removed by this standard maintenance operation.
    """
    events = ui_data / 'events.jsonl'
    maximum = 0
    with events.open() as src:
        for line in src:
            maximum = max(maximum, int(json.loads(line).get('seq', 0)))
    with events.open('a') as dst:
        dst.write(json.dumps({'seq': maximum + 1, 'id': 'evt_' + uuid.uuid4().hex[:16],
            'session_id': sid, 'type': 'history_imported', 'imported': True,
            'run_id': 'import_migration_checkpoint_' + uuid.uuid4().hex,
            'ts': datetime.datetime.now(datetime.timezone.utc).isoformat()}) + '\n')
    summary = api('POST', '/api/sessions/' + sid + '/history/prune-duplicates', {'dry_run': False})
    (ui_data.parent / 'timeline-maintenance.json').write_text(json.dumps(summary, indent=2))
    if summary.get('removed_events', 0) < 1:
        raise ValueError('AgentDock did not refresh the copied timeline sequence cache.')


def transfer(args):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', args.host):
        raise ValueError('Use an SSH config Host alias, not a shell expression.')
    if not args.remote_root.startswith('/') or args.remote_root.startswith('/tmp'):
        raise ValueError('Choose an explicitly authorized absolute remote asset directory outside /tmp.')
    root = export(args)
    remote = args.remote_root.rstrip('/') + '/' + root.name
    ssh = ['ssh', '-o', 'ClearAllForwardings=yes', '--', args.host]
    subprocess.run(ssh + ['install -d -m 700 -- ' + shlex.quote(remote)], check=True)
    # Stream only an explicit allowlist, never an entire profile, database or auth directory.
    names = ['native.jsonl.gz', 'events.jsonl', 'attachments.tar.gz', 'manifest.json',
             'registered-files.tar', 'registered-files-manifest.json']
    proc = subprocess.Popen(ssh + ['tar -xzf - -C ' + shlex.quote(remote)], stdin=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=proc.stdin, mode='w|gz') as tar:
            for name in names:
                tar.add(root / name, arcname=name)
            tar.add(Path(__file__).resolve(), arcname='transfer_session.py')
    finally:
        proc.stdin.close()
    if proc.wait():
        raise RuntimeError('SSH bundle transfer failed.')
    emit({'remote_bundle': remote})
    if args.allow_native_home:
        command = shlex.join(['python3', remote + '/transfer_session.py', 'import',
            '--bundle', remote, '--allow-native-home'])
        subprocess.run(ssh + [command], check=True)
    else:
        emit({'pending': 'Bundle transferred only. Native home placement requires explicit user authorization.'})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('list')
    for name in ('export', 'transfer'):
        q = sub.add_parser(name)
        q.add_argument('--session', help='Exact local chat ID, native UUID or title; default CODEX_THREAD_ID')
        q.add_argument('--remote-cwd', required=True)
        q.add_argument('--output', default='~/.codex/session-exports')
        if name == 'transfer':
            q.add_argument('--host', default='server02')
            q.add_argument('--remote-root', default='/data/ykj_robodojo/session_exports')
            q.add_argument('--allow-native-home', action='store_true')
    q = sub.add_parser('import')
    q.add_argument('--bundle', required=True)
    q.add_argument('--allow-native-home', action='store_true')
    q.add_argument('--api', default='http://127.0.0.1:7850')
    q.add_argument('--env-file', default='~/.config/agents-server/env')
    q.add_argument('--state-dir', default='~/.agentsdock')
    args = p.parse_args()
    if args.command == 'list':
        for s in sessions(Path.home()):
            if s.get('backend') == 'codex':
                emit({k: s.get(k) for k in ('id', 'title', 'cwd', 'codex_thread_id')})
    elif args.command == 'export':
        export(args)
    elif args.command == 'transfer':
        transfer(args)
    else:
        import_remote(args)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Do not echo HTTP response bodies, request headers, or transcript contents.
        print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        sys.exit(1)

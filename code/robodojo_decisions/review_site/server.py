"""Read-only RoboDojo evidence viewer. All runtime assets stay in DataStorage."""
from __future__ import annotations

import argparse
import json
import mimetypes
import re
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

ROOT = Path('/home/v4090-1/DataStorage/gpt6-dec')
WEB = Path(__file__).resolve().parent
CACHE = {'time': 0, 'data': None}
LOCK = threading.Lock()
LABELS = {'general_pickup': '拾取剪刀', 'stack_blocks': '叠积木',
          'fold_clothes': '折衣服', 'press_by_number': '按数字按钮',
          'stack_bowls': '叠碗', 'play_xylophone': '敲木琴',
          'push_t': '推 T', 'cut_paper': '剪纸'}
CURATED = {'general_pickup': '2026-10-13-gpt61-du-pickup-close-hypothesis-native-204',
           'press_by_number': '2026-10-13-gpt6-dec-press-gpu-fabric-path-aware-three-view-152'}


def read(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def public_asset(path):
    if not path:
        return None
    path = Path(path).resolve()
    for base in (ROOT / 'runs', ROOT / 'plans', ROOT / 'experience/model'):
        if path.is_relative_to(base.resolve()) and path.is_file():
            return '/assets/' + quote(str(path.relative_to(ROOT)), safe='/')
    return None


def result_for(path):
    status = read(path / 'episode_status.json', {})
    result = read(path / 'controller/result.json', {})
    if not isinstance(result, dict):
        result = {}
    if isinstance(status, dict) and isinstance(status.get('native_result'), dict):
        result = status['native_result']
    for file in sorted(path.glob('*trace.json')):
        data = read(file, {})
        if isinstance(data, dict) and isinstance(data.get('native_result'), dict):
            result = data['native_result']
            status = data
    return result, status if isinstance(status, dict) else {}


def input_object(decision):
    value = decision.get('input_text', '')
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return {}


def images(rows):
    result = []
    for row in rows or []:
        path = row.get('path') or row.get('original_path')
        result.append({**row, 'url': public_asset(path)})
    return result


def index(force=False):
    with LOCK:
        if not force and CACHE['data'] and time.time() - CACHE['time'] < 25:
            return CACHE['data']
        tasks = {}
        for path in sorted((ROOT / 'runs').iterdir()):
            if not path.is_dir():
                continue
            plan = read(path / 'plan.json', {}) or {}
            request = read(path / 'controller/request_000.json', {}) or {}
            launch = read(path / 'launch.json', {}) or {}
            task = request.get('task') or plan.get('task') or launch.get('task')
            if not task:
                continue
            result, status = result_for(path)
            decisions = list((path / 'decisions').glob('*.json'))
            history = read(path / 'controller/history.json', []) or []
            history = history if isinstance(history, list) else []
            step = result.get('step_id')
            if step is None:
                ticks = [row.get('end_tick', 0) for row in history]
                step = max(ticks, default=0)
            item = {'name': path.name, 'task': task,
                    'physical_steps': step, 'decision_count': len(decisions),
                    'success': result.get('success'), 'complete': result.get('complete'),
                    'status': status.get('status') or result.get('reason') or '未记录终局',
                    'has_plan': bool(plan), 'mtime': path.stat().st_mtime,
                    'is_preflight': not decisions and not step}
            group = tasks.setdefault(task, {'id': task, 'label': LABELS.get(task, task),
                                           'instruction': request.get('instruction') or '',
                                           'runs': []})
            group['runs'].append(item)
        for task in tasks.values():
            task['runs'].sort(key=lambda r: r['mtime'], reverse=True)
            controlled = [r for r in task['runs'] if r['decision_count']]
            native = [r for r in controlled if r['physical_steps']]
            preferred = next((r for r in controlled if r['name'] == CURATED.get(task['id'])), None)
            task['representative'] = (preferred or (native or controlled or task['runs'])[0])['name']
            task['control_runs'] = len(controlled)
            task['native_success'] = any(r['success'] is True for r in task['runs'])
        ordered = sorted(tasks.values(), key=lambda t: (not t['control_runs'], t['id']))
        data = {'generated_at': datetime.now(timezone.utc).isoformat(), 'tasks': ordered,
                'task_count': len(ordered), 'controlled_tasks': sum(bool(t['control_runs']) for t in ordered),
                'success_tasks': sum(t['native_success'] for t in ordered),
                'run_count': sum(len(t['runs']) for t in ordered),
                'decision_count': sum(r['decision_count'] for t in ordered for r in t['runs']),
                'success_definition': '只有原生 success=true 才计任务成功；complete=true 仅表示回合结束。',
                'read_only': True}
        CACHE.update(time=time.time(), data=data)
        return data


def run_detail(name):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
        raise ValueError('Invalid run name')
    path = (ROOT / 'runs' / name).resolve()
    if not path.is_relative_to((ROOT / 'runs').resolve()) or not path.is_dir():
        raise ValueError('Unknown run')
    result, status = result_for(path)
    history = read(path / 'controller/history.json', []) or []
    history = history if isinstance(history, list) else []
    traces = []
    trace_files = []
    for file in sorted(path.glob('*trace.json')):
        data = read(file, {})
        trace_files.append({'name': file.name, 'url': public_asset(file), 'data': data})
        if isinstance(data, dict) and isinstance(data.get('records'), list):
            traces.extend(data['records'])
        elif isinstance(data, dict):
            traces.append(data)
        elif isinstance(data, list):
            traces.extend(data)
    decisions = []
    files = sorted((path / 'decisions').glob('*.json'),
                   key=lambda f: ((read(f, {}) or {}).get('step_id', -1), f.name))
    for file in files:
        raw = read(file, {})
        if not isinstance(raw, dict):
            continue
        obj = input_object(raw)
        step = raw.get('step_id')
        trace = next((r for r in traces if isinstance(r, dict) and r.get('step_id') == step), {})
        execution = next((r for r in history if r.get('start_tick') == step), None)
        runtime_stage = obj.get('current_stage') or obj.get('active_stage') or obj.get('stage')
        if runtime_stage is None:
            runtime_stage = trace.get('stage')
        decoded = raw.get('decoded_answers') or {}
        row = {**raw, 'file': file.name, 'url': public_asset(file),
               'input_object': obj, 'images': images(raw.get('images')),
               'runtime_stage': runtime_stage, 'planner_stage': obj.get('planner_stage'),
               'model_stage': decoded.get('stage'), 'execution': execution,
               'trace': trace, 'questions_available': bool(raw.get('questions'))}
        decisions.append(row)
    plans = []
    plan_paths = [path / 'plan.json'] + sorted(path.glob('planner_method_refresh_step_*/plan.json'))
    for file in plan_paths:
        data = read(file)
        if data is not None:
            plans.append({'name': str(file.relative_to(path)), 'url': public_asset(file), 'data': data})
    planner_attempts = []
    for folder in sorted(path.glob('planner_method_refresh_step_*')):
        step = folder.name.rsplit('_', 1)[-1]
        log = path / f'planner_refresh_step_{step}.log'
        planner_attempts.append({'step': int(step), 'has_new_plan': (folder / 'plan.json').is_file(),
                                 'manifest_url': public_asset(folder / 'planner-input-manifest.json'),
                                 'log_url': public_asset(log),
                                 'log_tail': log.read_text(errors='replace')[-1600:] if log.exists() else None})
    observations = []
    for file in sorted((path / 'controller/observations').glob('*/observation.json')):
        data = read(file, {}) or {}
        observations.append({'step_id': data.get('step_id'), 'images': images(data.get('images')),
                             'url': public_asset(file)})
    video_paths = [path / 'controller/debug_video/debug_rollout.mp4', path / 'sim/sensors.mp4']
    videos = [{'name': f.name, 'url': public_asset(f)} for f in video_paths if f.is_file()]
    return {'name': name, 'task': (read(path / 'plan.json', {}) or {}).get('task'),
            'result': result, 'status': status.get('status'), 'decisions': decisions,
            'plans': plans, 'planner_attempts': planner_attempts, 'traces': trace_files,
            'history': history, 'history_url': public_asset(path / 'controller/history.json'),
            'result_url': public_asset(path / 'controller/result.json'),
            'observations': observations, 'videos': videos,
            'source_directory': str(path),
            'historical_question_gap': sum(not d['questions_available'] for d in decisions)}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = urlsplit(self.path)
        try:
            if route.path == '/api/index':
                self.send_json(index(parse_qs(route.query).get('refresh') == ['1']))
            elif route.path == '/api/run':
                self.send_json(run_detail(parse_qs(route.query).get('name', [''])[0]))
            elif route.path in ('/', '/index.html'):
                self.send_file(WEB / 'index.html')
            elif route.path.startswith('/assets/'):
                file = (ROOT / unquote(route.path[len('/assets/'):])).resolve()
                if not public_asset(file):
                    self.send_error(404)
                    return
                if file.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.mp4', '.json', '.md', '.log', '.txt'}:
                    self.send_error(403)
                    return
                self.send_file(file)
            else:
                self.send_error(404)
        except (ValueError, OSError) as error:
            self.send_json({'error': str(error)}, 400)

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_file(self, file):
        size = file.stat().st_size
        start, end = 0, size - 1
        requested = self.headers.get('Range')
        if requested:
            match = re.fullmatch(r'bytes=(\d+)-(\d*)', requested)
            if not match:
                self.send_error(416)
                return
            start = int(match[1])
            end = min(int(match[2]) if match[2] else end, end)
            if start > end:
                self.send_error(416)
                return
        self.send_response(206 if requested else 200)
        mime = mimetypes.guess_type(str(file))[0] or 'application/octet-stream'
        self.send_header('Content-Type', mime + ('; charset=utf-8' if mime.startswith('text/') else ''))
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Accept-Ranges', 'bytes')
        if requested:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        try:
            with file.open('rb') as stream:
                stream.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = stream.read(min(262144, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    global ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--port', type=int, default=18942)
    parser.add_argument('--bind', default='127.0.0.1')
    args = parser.parse_args()
    ROOT = args.root.resolve()
    print(f'RoboDojo evidence viewer http://{args.bind}:{args.port} root={ROOT}', flush=True)
    ThreadingHTTPServer((args.bind, args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()

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
from planner_audit import PlannerArchive

ROOT = Path('/home/v4090-1/DataStorage/gpt6-dec')
WEB = Path(__file__).resolve().parent
CACHE = {'time': 0, 'data': None}
LOCK = threading.Lock()
LABELS = {'general_pickup': '拾取剪刀', 'stack_blocks': '叠积木',
          'fold_clothes': '折衣服', 'press_by_number': '按数字按钮',
          'stack_bowls': '叠碗', 'play_Xylophone': '敲木琴',
          'push_T': '推 T', 'align_blocks': '对齐积木',
          'arrange_largest_number': '排列最大数字', 'classify_objects': '物体分类',
          'classify_objects_by_language': '按语言分类', 'cover_blocks': '盖住积木',
          'imitate_sorting_sequence': '模仿排序', 'match_and_pick_from_conveyor': '传送带匹配拾取',
          'solve_equation': '解方程', 'stack_blocks_by_language': '按语言叠积木',
          'build_tower': '搭塔', 'deposit_coin': '投硬币', 'fasten_screws': '拧螺丝',
          'fill_egg_holder': '放鸡蛋', 'fill_pen_holder': '放笔', 'hang_mugs': '挂杯子',
          'insert_key': '插钥匙', 'insert_tubes': '插管', 'make_kong': '装填玩具',
          'make_toast': '制作吐司', 'organize_table': '整理桌面',
          'pack_objects_into_box': '装箱', 'pick_from_conveyor_by_image': '按图传送带拾取',
          'play_stacking_toy': '叠玩具', 'play_tic_tac_toe': '井字棋',
          'plug_in_charger': '插充电器', 'pour_balls_into_vase': '倒球入花瓶',
          'pour_by_language': '按语言倒物', 'pour_liquid_into_cup': '倒液体',
          'put_bottles_into_dustbin': '丢瓶子', 'sort_nesting_dolls_by_size': '套娃排序',
          'store_laptop_and_headphones': '收纳电脑耳机', 'store_tools_in_toolbox': '收纳工具',
          'swap_T': '交换 T', 'swap_blocks': '交换积木', 'sweep_blocks': '扫积木'}
CURATED = {'general_pickup': '2026-10-14-gpt61-du-pickup-phase-tagged-native-461',
           'stack_blocks': '2026-10-14-gpt61-du-stack-roles477-tool-pair-native-482',
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
    for file in sorted(path.glob('*trace.json')) if not result else []:
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
    files = [(file, read(file, {}) or {}) for file in (path / 'decisions').glob('*.json')]
    files.sort(key=lambda pair: (pair[1].get('step_id', -1), pair[0].stat().st_mtime, pair[0].name))
    last_by_step = {raw.get('step_id'): i for i, (_, raw) in enumerate(files)}
    for i, (file, raw) in enumerate(files):
        if not isinstance(raw, dict):
            continue
        obj = input_object(raw)
        step = raw.get('step_id')
        trace = next((r for r in traces if isinstance(r, dict) and r.get('step_id') == step), {})
        names = set(raw.get('question_names', [])) | {q.get('name') for q in raw.get('questions', [])}
        perception_only = bool(names) and names <= {'source_receiver_roles', 'observable_stage', 'identity_stage_EXIT'}
        later_same_step = last_by_step.get(step) != i
        execution = (next((r for r in history if r.get('start_tick') == step), None)
                     if not perception_only and not later_same_step else None)
        runtime_stage = obj.get('current_stage') or obj.get('active_stage') or obj.get('stage')
        if runtime_stage is None:
            runtime_stage = trace.get('stage')
        decoded = raw.get('decoded_answers') or {}
        row = {**raw, 'file': file.name, 'url': public_asset(file),
               'input_object': obj, 'images': images(raw.get('images')),
               'runtime_stage': runtime_stage, 'planner_stage': obj.get('planner_stage'),
               'model_stage': decoded.get('observable_stage') or decoded.get('stage'), 'execution': execution,
               'perception_only': perception_only,
               'trace': trace, 'questions_available': bool(raw.get('questions'))}
        snapshot = obj.get('memory_read_manifest', {}).get('full_snapshot_directory')
        evidence_assets = []
        if snapshot:
            for filename in ('global.md', 'general_pickup.md', 'selected-task-experience.md'):
                file = Path(snapshot) / filename
                url = public_asset(file)
                if url:
                    evidence_assets.append({'name': filename, 'url': url})
        geometry_file = path / f"full_actor_geometry_step_{step:03d}.json" if isinstance(step, int) else None
        geometry_url = public_asset(geometry_file)
        if geometry_url:
            evidence_assets.append({'name': '未精简几何快照（非实际输入）', 'url': geometry_url})
        row['evidence_assets'] = evidence_assets
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


def review_detail(name):
    data = run_detail(name)
    data.pop('traces', None)
    data.pop('history', None)
    keep = {'stage', 'luna_choice', 'status', 'luna_action_family', 'post_action',
            'luna_program_decision', 'luna_source_identity', 'proposed_complete_program',
            'luna_capture_evidence_assessment', 'decision_policy_variant'}
    for row in data['decisions']:
        row['trace'] = {k: v for k, v in row['trace'].items() if k in keep}
    archive = PlannerArchive(ROOT, public_asset)
    data['planner_sources'] = archive.sources_for_run(ROOT / 'runs' / name)
    data['planner_catalog'] = archive.catalog()
    return data


class Handler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        route = urlsplit(self.path)
        try:
            if route.path == '/api/index':
                self.send_json(index(parse_qs(route.query).get('refresh') == ['1']))
            elif route.path == '/api/run':
                self.send_json(run_detail(parse_qs(route.query).get('name', [''])[0]))
            elif route.path == '/api/review':
                self.send_json(review_detail(parse_qs(route.query).get('name', [''])[0]))
            elif route.path == '/api/planner':
                self.send_json(PlannerArchive(ROOT, public_asset).detail(parse_qs(route.query).get('source', [''])[0]))
            elif route.path in ('/prompts', '/prompts.html', '/prompts.js', '/prompts.css'):
                self.send_file(WEB / ('prompts.html' if route.path in ('/prompts', '/prompts.html') else route.path[1:]))
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
        if self.command == 'HEAD':
            return
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
        if self.command == 'HEAD':
            return
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

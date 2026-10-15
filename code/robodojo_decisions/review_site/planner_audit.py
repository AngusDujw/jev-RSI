"""Saved planner requests and final outputs; never reconstruct missing prompts."""
import json
import re
from pathlib import Path


def load(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def final_text(response):
    if not isinstance(response, dict):
        return ''
    wrapped = response.get('output_text')
    if isinstance(wrapped, str) and wrapped.startswith('event: '):
        for line in reversed(wrapped.splitlines()):
            if line.startswith('data: '):
                try:
                    event = json.loads(line[6:])
                except ValueError:
                    continue
                if event.get('type') == 'response.completed':
                    return final_text(event.get('response'))
        return ''
    if isinstance(wrapped, str):
        return wrapped
    pieces = [part['text'] for item in response.get('output', [])
              if item.get('type') == 'message' and item.get('role') == 'assistant'
              for part in item.get('content', []) if part.get('type') == 'output_text']
    if pieces:
        return '\n'.join(pieces)
    choices = response.get('choices') or []
    return choices[0].get('message', {}).get('content', '') if choices else ''


class PlannerArchive:
    def __init__(self, root, asset):
        self.root, self.asset = Path(root).resolve(), asset

    def folder(self, source):
        path = (self.root / source).resolve()
        if (not any(path.is_relative_to((self.root / name).resolve()) for name in ('plans', 'runs'))
                or not path.is_dir()):
            raise ValueError('Unknown planner source')
        return path

    def detail(self, source):
        path = self.folder(source)
        request_path = next((path / n for n in ('planner-request.json', 'request.json')
                             if (path / n).is_file()), None)
        request = load(request_path, {}) if request_path else {}
        if not isinstance(request, dict) or not request.get('model') or not any(k in request for k in ('input', 'messages')):
            request, request_path = {}, None
        response_path = next((path / n for n in ('response.json', 'planner-response.json')
                              if (path / n).is_file()), None)
        response = load(response_path, {}) if response_path else {}
        plan_path = next((path / n for n in ('plan.json', 'method-schema.json')
                          if (path / n).is_file()), None)
        plan = load(plan_path, {}) if plan_path else {}
        manifest_path = next((path / n for n in ('manifest.json', 'planner-input-manifest.json', 'planner-read-manifest.json')
                              if (path / n).is_file()), None)
        manifest = load(manifest_path, {}) if manifest_path else {}
        text = final_text(response)
        messages = []
        if request.get('instructions'):
            messages.append({'role': 'instructions', 'parts': [{'type': 'text', 'text': request['instructions']}]})
        for row in request.get('input', request.get('messages', [])):
            if not isinstance(row, dict):
                continue
            content = row.get('content', [])
            if isinstance(content, str):
                content = [{'type': 'text', 'text': content}]
            parts = []
            for part in content:
                if part.get('type') in ('input_text', 'text'):
                    parts.append({'type': 'text', 'text': part.get('text', '')})
                elif part.get('type') in ('input_image', 'image_url'):
                    url = part.get('image_url', '')
                    url = url.get('url', '') if isinstance(url, dict) else url
                    valid = isinstance(url, str) and re.match(r'^data:image/(png|jpeg|webp);base64,', url)
                    parts.append({'type': 'image', 'url': url if valid else None,
                                  'detail': part.get('detail'), 'saved_payload_image': bool(valid)})
            messages.append({'role': row.get('role', 'unknown'), 'parts': parts})
        provenance = plan.get('planner_provenance', {}) if isinstance(plan, dict) else {}
        return {'source': str(path.relative_to(self.root)), 'name': path.name,
                'model': request.get('model') or response.get('model') or provenance.get('model'),
                'reasoning_effort': request.get('reasoning', {}).get('effort') or provenance.get('reasoning_effort'),
                'request_saved': bool(request), 'messages': messages,
                'image_count': sum(p['type'] == 'image' for m in messages for p in m['parts']),
                'request_url': self.asset(request_path), 'response_url': self.asset(response_path),
                'plan_url': self.asset(plan_path), 'manifest_url': self.asset(manifest_path),
                'request_settings': {k: request[k] for k in ('model', 'reasoning', 'text', 'max_output_tokens', 'temperature', 'store', 'stream', 'response_format') if k in request},
                'final_text': text, 'plan': plan, 'manifest': manifest,
                'response_status': response.get('status'), 'response_id': response.get('id'),
                'failure': load(path / 'failure.json'),
                'scope': 'Only saved request text/images are shown. Missing requests are not rebuilt from current source.'}

    def sources_for_run(self, run_path):
        linked = {}
        def add(file, role):
            if not file:
                return
            file = Path(file).resolve()
            if self.asset(file):
                source = str(file.parent.relative_to(self.root))
                linked.setdefault(source, {'source': source, 'role': role, 'name': file.parent.name})
        for filename in ('plan.json', 'launch.json', 'planner_input_mode.json'):
            data = load(run_path / filename, {}) or {}
            add(data.get('source_method'), '本回合复用的规划方法')
            for key in ('planner_provenance', 'planner_schema_provenance'):
                provenance = data.get(key, {}) or {}
                add(provenance.get('fresh_stage_source'), '阶段计划来源')
                add(provenance.get('generic_processing_method_source'), '历史感知方法来源')
            flags = data.get('runtime_feature_flags', {})
            add(flags.get('ROBODOJO_RGB_STAGE_AUTHORED_METHOD'), '本回合复用的规划方法')
        for folder in [run_path / 'initial_fresh_method', *sorted(run_path.glob('planner_method_refresh_step_*'))]:
            if folder.is_dir():
                add(folder / 'plan.json', '本回合规划调用')
                if not (folder / 'plan.json').exists():
                    add(folder / 'planner-input-manifest.json', '本回合规划尝试，未找到新计划')
        return list(linked.values())

    def catalog(self):
        result = []
        for path in sorted((self.root / 'plans').iterdir(), reverse=True):
            if not path.is_dir():
                continue
            if not any((path / name).exists() for name in ('plan.json', 'method-schema.json', 'request.json', 'planner-request.json')):
                continue
            result.append({'source': str(path.relative_to(self.root)), 'name': path.name,
                           'request_saved': any((path / name).exists() for name in ('request.json', 'planner-request.json'))})
        return result

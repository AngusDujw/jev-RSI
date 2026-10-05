"""Loopback-only Codex CLI transport for the Pro-account robot comparisons.

The server runs on the signed-in workstation. An SSH reverse forward carries
requests from the simulator; OAuth credentials never leave this machine.
"""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

from codex_pro_bridge import MODEL, EFFORT


LIMIT = 24 * 1024 * 1024


def model_turn(role, request, root):
    if request.get('model') != MODEL:
        raise ValueError('Requested model does not match the pinned Codex model')
    ident = uuid.uuid4().hex
    folder = root / ident
    folder.mkdir()
    attachments = []
    if role == 'jev':
        if set(request) != {'model', 'state', 'questions'}:
            raise ValueError('Unexpected controller request fields')
        questions = request['questions']
        if not questions or any(not q.get('criteria') for q in questions.values()):
            raise ValueError('Missing choice criteria')
        prompt = ('You are the decision model in a robot experiment. Use only the '
            'supplied public task, observations, state, history and question contracts. '
            'Do not use tools, inspect files or invent hidden simulator state. Return '
            'one JSON object mapping every question name to exactly one criterion key. '
            'Output JSON only.\n' + json.dumps(dict(state=request['state'], questions=questions),
                ensure_ascii=True, separators=(',', ':')))
    elif role in ('semantic_vision', 'runtime_vision'):
        content = request['input'][0]['content']
        text_parts = []
        for item in content:
            if item['type'] == 'input_text':
                text_parts.append(item['text'])
            elif item['type'] == 'input_image':
                url = item['image_url']
                if url.startswith('data:image/png;base64,'):
                    extension = '.png'
                elif url.startswith('data:image/jpeg;base64,'):
                    extension = '.jpg'
                else:
                    raise ValueError('Only PNG/JPEG observation attachments are permitted')
                path = folder / f'image-{len(attachments)}{extension}'
                path.write_bytes(base64.b64decode(url.partition(',')[2], validate=True))
                attachments.append(path)
            else:
                raise ValueError('Unexpected visual content type')
        if not attachments:
            raise ValueError('Visual request has no camera image')
        prompt = ('You are the bounded visual measurement service in a robot '
            'experiment. Use only the attached camera images and supplied public '
            'instruction. Do not use tools or inspect files other than the attachments. '
            'Follow the supplied response contract and return JSON only. '
            'Write all labels and evidence strings in English.\n'
            + request['instructions'] + '\n' + '\n'.join(text_parts))
    else:
        raise ValueError('Unknown model role')

    (folder / 'request-summary.json').write_text(json.dumps(dict(
        role=role, model=MODEL, reasoning_effort=EFFORT,
        request_sha256=hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest(),
        image_sha256=[hashlib.sha256(p.read_bytes()).hexdigest() for p in attachments],
        prompt=prompt), indent=2) + '\n')
    command = ['codex', 'exec', '--ephemeral', '--ignore-user-config',
        '--skip-git-repo-check', '--model', MODEL,
        '-c', f'model_reasoning_effort="{EFFORT}"', '--sandbox', 'read-only',
        '--json', '-C', str(root)]
    if attachments:
        command += ['-i', *map(str, attachments)]
    command += ['--', prompt]
    start = time.monotonic()
    env = dict(os.environ, TMPDIR=str(root), TMP=str(root), TEMP=str(root))
    try:
        for attempt in range(3):
            result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                text=True, timeout=400 if role=='runtime_vision' and len(attachments)>1 else 200,
                env=env)
            (folder / f'codex-events-{attempt+1}.jsonl').write_text(result.stdout)
            (folder / f'codex-stderr-{attempt+1}.log').write_text(result.stderr)
            events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            failures = [e.get('error', {}).get('message', 'turn failed') for e in events
                if e.get('type') == 'turn.failed']
            if failures and 'Selected model is at capacity' in failures[-1] and attempt < 2:
                time.sleep(5 * (attempt+1))
                continue
            break
        messages = [e['item']['text'] for e in events if e.get('type') == 'item.completed'
            and e.get('item', {}).get('type') == 'agent_message']
        completions = [e for e in events if e.get('type') == 'turn.completed']
        if failures:
            raise RuntimeError('Codex turn failed: ' + failures[-1][:250])
        if result.returncode != 0 or len(messages) != 1 or len(completions) != 1:
            raise RuntimeError('Codex turn did not complete exactly once')
        content = json.loads(messages[0])
        usage = completions[0].get('usage', {})
        if role == 'jev':
            if set(content) != set(questions):
                raise ValueError('Decision did not answer the exact question set')
            answers = {}
            for name, choice in content.items():
                criteria = questions[name]['criteria']
                if choice not in criteria:
                    raise ValueError('Decision outside declared criteria: ' + name)
                # The CLI gives choices, not calibrated probabilities. Uniform
                # placeholders satisfy the legacy parser and are never model scores.
                p = 1 / len(criteria)
                answers[name] = dict(type='choice', choice=choice,
                    probabilities={key:p for key in criteria}, confidence=p)
            response = dict(model=MODEL, reasoning_effort=EFFORT, answers=answers,
                probability_source='uniform compatibility placeholder; not a model score')
        else:
            if not isinstance(content, dict):
                raise ValueError('Visual response must be a JSON object')
            if role == 'semantic_vision':
                if not {'source', 'destination'} <= set(content):
                    raise ValueError('Missing visual source or destination')
                for item in (content['source'], content['destination']):
                    if not item['label'].isascii():
                        raise ValueError('Visual object label must be English ASCII')
            response = dict(model=MODEL, reasoning_effort=EFFORT, status='completed',
                output=[dict(type='message', content=[dict(type='output_text',
                    text=json.dumps(content, ensure_ascii=False))])])
        response.update(usage=usage, codex_request_id=ident,
            codex_elapsed_seconds=time.monotonic()-start,
            codex_transport_attempts=attempt+1)
        (folder / 'response.json').write_text(json.dumps(response, indent=2) + '\n')
        return response
    finally:
        for path in attachments:
            path.unlink(missing_ok=True)


class Handler(BaseHTTPRequestHandler):
    def _reply(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != '/health':
            return self._reply(404, dict(error='not found'))
        login = subprocess.run(['codex', 'login', 'status'], capture_output=True,
            text=True, timeout=15)
        ok = login.returncode == 0 and 'Logged in using ChatGPT' in (login.stdout + login.stderr)
        self._reply(200 if ok else 503, dict(ok=ok, model=MODEL,
            reasoning_effort=EFFORT, auth='ChatGPT' if ok else 'unavailable'))

    def do_POST(self):
        if self.path != '/infer':
            return self._reply(404, dict(error='not found'))
        size = int(self.headers.get('Content-Length', '0'))
        if not 0 < size <= LIMIT:
            return self._reply(413, dict(error='invalid request size'))
        try:
            body = json.loads(self.rfile.read(size))
            with self.server.request_slots:
                response = model_turn(body['role'], body['request'], self.server.work_root)
            self._reply(200, response)
        except Exception as exc:
            self._reply(502, dict(error_type=type(exc).__name__, error=str(exc)[:500]))

    def log_message(self, fmt, *args):
        print('%s %s' % (self.address_string(), fmt % args), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--work-root', type=Path, required=True)
    parser.add_argument('--port', type=int, default=7903)
    parser.add_argument('--max-inflight', type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    if args.max_inflight < 1:
        parser.error('--max-inflight must be positive')
    args.work_root.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.work_root = args.work_root.resolve()
    server.request_slots = threading.BoundedSemaphore(args.max_inflight)
    print(json.dumps(dict(listen=f'127.0.0.1:{args.port}', model=MODEL,
        reasoning_effort=EFFORT, max_inflight=args.max_inflight,
        work_root=str(server.work_root))), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()

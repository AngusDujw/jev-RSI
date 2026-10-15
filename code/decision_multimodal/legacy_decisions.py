"""Transport-only Jev Choice to OpenAI Decisions adapter for frozen policies.

Phase 1 preserves state, question instructions, option values and descriptions.
It sends no image, experience, extra instruction, evaluator label or fallback
answer. Real provider probabilities are converted to the legacy mapping.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

MODEL = 'gpt-6-luna'
ENDPOINT = 'https://api.openai.com/v1/decisions'
HAN = re.compile('[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0003347f]')


def english(value, depth=0):
    if depth > 16:
        raise ValueError('Input JSON nesting exceeds audit limit')
    if isinstance(value, str):
        if HAN.search(value):
            raise ValueError('English-only model input required')
        if value.lstrip().startswith(('{', '[', '"')):
            try:
                decoded = json.loads(value)
            except (ValueError, RecursionError):
                return
            english(decoded, depth + 1)
    elif isinstance(value, dict):
        for key, item in value.items():
            english(str(key), depth)
            english(item, depth)
    elif isinstance(value, (tuple, list)):
        for item in value:
            english(item, depth)


def digest(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False,
                     allow_nan=False, separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest()


def convert_request(legacy):
    if set(legacy) != {'model', 'state', 'questions'}:
        raise ValueError('Unexpected legacy request fields')
    english(legacy)
    if not isinstance(legacy['questions'], dict) or not 1 <= len(legacy['questions']) <= 200:
        raise ValueError('Invalid legacy question count')
    questions = []
    for name, question in legacy['questions'].items():
        if set(question) != {'type', 'instructions', 'criteria'} or question['type'] != 'choice':
            raise ValueError('Phase 1 accepts the original Choice schema only')
        criteria = question['criteria']
        if not isinstance(criteria, dict) or not 2 <= len(criteria) <= 255:
            raise ValueError('Choice needs 2..255 original options')
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in criteria.items()):
            raise ValueError('Original option values and descriptions must be strings')
        questions.append(dict(type='choice', name=name,
            instructions=question['instructions'], choices=[
                dict(value=value, description=description)
                for value, description in criteria.items()]))
    text = json.dumps(legacy['state'], ensure_ascii=False, allow_nan=False,
                      separators=(',', ':'))
    return dict(model=MODEL, input=text, questions=questions)


def probability(value):
    if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Invalid provider probability')
    return value


def convert_response(response, legacy):
    if response.get('model') != MODEL:
        raise ValueError('Unexpected provider model')
    rows = response.get('answers')
    if not isinstance(rows, list) or len(rows) != len(legacy['questions']):
        raise ValueError('Provider did not answer the complete original question set')
    answers = {}
    for row in rows:
        name = row.get('name')
        if name not in legacy['questions'] or name in answers or row.get('type') != 'choice':
            raise ValueError('Missing, duplicate, refused or invalid provider answer')
        criteria = legacy['questions'][name]['criteria']
        selected = row.get('choice')
        if type(selected) is not str or selected not in criteria:
            raise ValueError('Provider answer is outside original options')
        distribution = row.get('probabilities')
        if not isinstance(distribution, list) or len(distribution) != len(criteria):
            raise ValueError('Missing provider option distribution')
        probs = {}
        for option in distribution:
            value = option.get('value')
            if type(value) is not str or value not in criteria or value in probs:
                raise ValueError('Invalid or duplicate provider probability option')
            probs[value] = probability(option.get('probability'))
        if set(probs) != set(criteria) or abs(sum(probs.values()) - 1) > .02:
            raise ValueError('Incomplete or unnormalized provider probabilities')
        answers[name] = dict(type='choice', choice=selected,
            confidence=probability(row.get('confidence')), probabilities=probs)
    return dict(model=MODEL, answers=answers, usage=response.get('usage', {}),
                probability_source='original OpenAI Decisions response')


class LegacyAPI:
    def __init__(self, cfg, log, role):
        if role != 'jev':
            raise ValueError('Unexpected non-decision model call in frozen Phase 1')
        path = Path(os.environ['DECISION_MM_KEY_FILE']).resolve()
        if path.name != 'du-openai-direct.key':
            raise ValueError('Only the explicitly authorized du key file may be used')
        self.credential = path.read_text().strip()
        if not self.credential.startswith('sk-'):
            raise ValueError('Authorized du key is unavailable')
        self.cfg = dict(model=MODEL, key_origin='du', key_file=str(path))
        self.log = log
        recorder = getattr(log, '__self__', None)
        if recorder is None or not hasattr(recorder, 'folder'):
            raise ValueError('Original recorder is required for model request audit')
        self.folder = Path(recorder.folder) / 'decision-api'
        self.folder.mkdir(exist_ok=True)
        # Drawer+bowl has two sequential model instances in one recorder.
        # Keep one append-only audit stream across that handoff.
        numbers = [int(p.name) for p in self.folder.iterdir() if p.is_dir() and p.name.isdigit()]
        self.calls = max(numbers, default=-1) + 1
        proxy = os.environ.get('DECISION_MM_PROXY')
        if proxy not in (None, 'http://127.0.0.1:7897'):
            raise ValueError('Only the authorized loopback proxy is supported')
        self.client = urllib.request.build_opener(
            urllib.request.ProxyHandler({'https': proxy} if proxy else {}))

    def post(self, endpoint, legacy):
        if endpoint != '/systemone':
            raise ValueError('Frozen policy requested an unexpected endpoint')
        payload = convert_request(legacy)
        while True:
            directory = self.folder / f'{self.calls:04d}'
            self.calls += 1
            try:
                directory.mkdir()
                break
            except FileExistsError:
                continue  # Allocation only; never retries the model request.
        def save(name, value):
            (directory / name).write_text(json.dumps(value, ensure_ascii=False,
                allow_nan=False, indent=2) + '\n')
        save('legacy-request.json', legacy)
        save('request.json', payload)
        save('dispatch.json', dict(status='prepared_before_network',
            key_origin='du', endpoint=ENDPOINT, image_count=0,
            state_sha256=digest(legacy['state']),
            original_questions_sha256=digest(legacy['questions'])))
        request = urllib.request.Request(ENDPOINT,
            data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(),
            headers={'Authorization': 'Bearer ' + self.credential,
                     'Content-Type': 'application/json'}, method='POST')
        started = time.monotonic()
        try:
            with self.client.open(request, timeout=120) as handle:
                raw = json.load(handle)
            save('response.json', raw)
            converted = convert_response(raw, legacy)
            save('legacy-response.json', converted)
            self.log(dict(kind='decision_api_response', key_origin='du', model=MODEL,
                image_count=0, seconds=time.monotonic()-started,
                request_sha256=digest(payload), audit_directory=str(directory)))
            return converted
        except Exception as error:
            save('failure.json', dict(error_type=type(error).__name__,
                error=str(error).replace(self.credential, '[redacted]')[:600],
                seconds=time.monotonic()-started))
            raise

    def close(self):
        pass

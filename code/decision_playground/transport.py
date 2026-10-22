"""One authorized Decisions request. Never retry, probe, or use another API."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from contract import validate_answers

ENDPOINT = 'https://api.openai.com/v1/decisions'
MODEL = 'gpt-6-luna'


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.writing')
    temporary.write_text(json.dumps(value, indent=2)+'\n')
    temporary.replace(path)


def request(body, folder, key_path):
    if body.get('model') != MODEL or set(body) != {'model', 'input', 'questions'}:
        raise ValueError('Only the fixed Decisions request contract is authorized')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    redacted = json.loads(json.dumps(body))
    for message in redacted['input']:
        for item in message.get('content', []):
            if item.get('type') == 'input_image':
                item['image_url'] = 'sha256:'+hashlib.sha256(item['image_url'].encode()).hexdigest()
            elif item.get('type') == 'input_text' and not item['text'].isascii():
                raise ValueError('Model text must be English ASCII')
    wire = json.dumps(body).encode()
    save(folder/'request.json', dict(endpoint=ENDPOINT, body=redacted,
        wire_sha256=hashlib.sha256(wire).hexdigest()))
    key = Path(key_path).read_text().strip()
    if not key.startswith('sk-'):
        raise ValueError('Invalid configured authorized du credential')
    read_fd, write_fd = os.pipe()
    os.write(write_fd, ('header = "Authorization: Bearer '+key+'"\n').encode())
    os.close(write_fd)
    started = time.monotonic()
    try:
        result = subprocess.run(['curl', '--silent', '--show-error', '--http1.1',
            '--connect-timeout', '20', '--max-time', '300', '--retry', '0',
            '--config', f'/proc/self/fd/{read_fd}', '--header', 'Content-Type: application/json',
            '--header', 'Expect:', '--data-binary', '@-', '--write-out',
            '\n%{http_code} %{time_connect} %{time_appconnect} %{size_upload}\n', ENDPOINT],
            input=wire, capture_output=True, pass_fds=(read_fd,), timeout=310)
        raw, _, trailer = result.stdout.rstrip(b'\n').rpartition(b'\n')
        measurements = trailer.decode(errors='replace').split()
        save(folder/'transport.json', dict(returncode=result.returncode,
            http_status=measurements[0] if measurements else None,
            measurements=measurements, elapsed_s=time.monotonic()-started,
            no_retry=True, endpoint=ENDPOINT))
        (folder/'response.json').write_bytes(raw)
        (folder/'transport_error.txt').write_bytes(result.stderr)
        if result.returncode or not measurements or not measurements[0].startswith('2'):
            raise RuntimeError('Decisions transmission failed; preserve and do not resend')
        data = json.loads(raw)
        if data.get('model') != MODEL:
            raise ValueError('Unexpected Decisions response model')
        return validate_answers(data['answers'])
    finally:
        os.close(read_fd)

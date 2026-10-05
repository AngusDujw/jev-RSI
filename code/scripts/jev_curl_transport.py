"""Audited curl transport for identical Jev requests; credentials stay on stdin."""
import json
from pathlib import Path
import subprocess
import time

import httpx


def post(api, payload, folder, proxy, timeout):
    folder = Path(folder)
    wire = folder / 'response-wire.json'
    request = folder / 'request.json'
    # Refuse to send a different payload from the reviewable request on disk.
    if json.loads(request.read_text()) != payload:
        raise ValueError('curl payload differs from saved Jev request')
    headers = ('header = ' + json.dumps('Authorization: Bearer ' + api.credential)
               + '\nheader = "Content-Type: application/json"\n')
    # The proxy has intermittently terminated HTTP/2 streams mid-response.
    # Use HTTP/1.1 for this audited POST; the payload and response contract stay unchanged.
    command = ['curl', '--http1.1', '--config', '-', '--silent', '--show-error',
               '--connect-timeout', str(min(15, timeout)), '--max-time', str(timeout),
               '--proxy', proxy, '--noproxy', '', '--data-binary', '@' + str(request),
               '--output', str(wire), '--write-out', '%{http_code}',
               api.cfg['base_url'].rstrip('/') + '/systemone']
    api.calls += 1
    started = time.monotonic()
    record = dict(kind='api', role='jev', call=api.calls,
                  requested_model=payload['model'], transport='curl')
    try:
        try:
            result = subprocess.run(command, input=headers, text=True,
                                    capture_output=True, timeout=timeout + 5)
        except subprocess.TimeoutExpired as exc:
            raise httpx.ReadTimeout('curl Jev transport deadline exceeded') from exc
        if result.returncode:
            detail = result.stderr.replace(api.credential, '[redacted]')[:500]
            error = httpx.ReadTimeout if result.returncode == 28 else httpx.ConnectError
            raise error('curl exit ' + str(result.returncode) + ': ' + detail)
        record['http_status'] = int(result.stdout.strip())
        if record['http_status'] != 200:
            raise RuntimeError('jev HTTP ' + str(record['http_status']) + '; body saved on disk')
        response = json.loads(wire.read_text())
        record.update(model=response.get('model'), usage=response.get('usage'))
        expected = api.cfg.get('expected_model_prefix', payload['model'])
        if not str(response.get('model', '')).startswith(expected):
            raise RuntimeError('jev returned unexpected model ' + str(response.get('model')))
        return response
    except Exception as exc:
        record.update(error_type=type(exc).__name__, usage_unknown=True)
        raise
    finally:
        record['seconds'] = round(time.monotonic() - started, 3)
        api.log(record)

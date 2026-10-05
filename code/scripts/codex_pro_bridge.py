"""Use the local ChatGPT-signed-in Codex CLI as the experiment's model transport.

This module runs on the simulation host. It sends only the already constructed
model request over an SSH reverse-forwarded loopback port. Credentials stay on
the workstation; no Platform API key or Jev endpoint is used.
"""
import json
import os
import urllib.error
import urllib.request


MODEL = 'gpt-6-sol'
EFFORT = 'xhigh'


class API:
    def __init__(self, cfg, event, role):
        if role not in ('jev', 'semantic_vision'):
            raise ValueError('Unsupported Pro bridge role: ' + role)
        self.cfg = dict(cfg, model=MODEL)
        self.event = event
        self.role = role
        self.credential = None
        self.url = os.environ.get('JEV_RSI_PRO_BRIDGE_URL', 'http://127.0.0.1:7903')
        if self.url != 'http://127.0.0.1:7903':
            raise ValueError('Pro bridge must use the authorized loopback port 7903')

    def post(self, path, request):
        expected = '/systemone' if self.role == 'jev' else '/responses'
        if path != expected or request.get('model') != MODEL:
            raise ValueError('Unexpected Pro bridge path or model')
        payload = json.dumps(dict(role=self.role, request=request), ensure_ascii=False).encode()
        transport = urllib.request.Request(self.url + '/infer', data=payload,
            headers={'Content-Type': 'application/json'})
        # Never send the workstation request to a configured internet proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(transport, timeout=700) as reply:
                response = json.load(reply)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors='replace')[:500]
            self.event(dict(kind='pro_bridge_transport_failure', role=self.role,
                error_type='HTTPError', error=detail))
            raise RuntimeError('Pro bridge HTTP error: ' + detail) from None
        except Exception as exc:
            self.event(dict(kind='pro_bridge_transport_failure', role=self.role,
                error_type=type(exc).__name__, error=str(exc)[:500]))
            raise
        if response.get('model') != MODEL or response.get('reasoning_effort') != EFFORT:
            raise RuntimeError('Pro bridge model/effort mismatch')
        self.event(dict(kind='pro_bridge_response', role=self.role, model=MODEL,
            reasoning_effort=EFFORT, usage=response.get('usage', {}),
            codex_request_id=response.get('codex_request_id')))
        return response

    def close(self):
        pass

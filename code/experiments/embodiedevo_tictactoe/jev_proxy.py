"""Local Jev relay. Credential arrives on stdin and is never logged."""
import argparse
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import time
import urllib.request
import uuid
from jev_protocol import payload, VERSION

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        if self.path != '/route':
            self.send_error(404); return
        ident = uuid.uuid4().hex
        folder = self.server.output / ident
        folder.mkdir()
        start = time.monotonic()
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length < 100000: raise ValueError('Invalid request size')
            state = json.loads(self.rfile.read(length))
            body = payload(state)
            (folder/'request.json').write_text(json.dumps(body,indent=2))
            req = urllib.request.Request('https://api.typesafe.ai/v1/systemone',
                data=json.dumps(body).encode(), headers={'Authorization':'Bearer '+self.server.key,
                                                        'Content-Type':'application/json'})
            with urllib.request.urlopen(req, timeout=60) as stream:
                raw = json.load(stream)
            (folder/'response.json').write_text(json.dumps(raw,indent=2))
            result = {'request_id':ident, 'protocol':VERSION, 'raw':raw,
                      'elapsed_seconds':time.monotonic()-start}
            code = 200
        except Exception as exc:
            # Avoid logging HTTP headers, credentials, or arbitrary upstream body.
            result = {'request_id':ident,'error_type':type(exc).__name__,
                      'usage_unknown':True,'elapsed_seconds':time.monotonic()-start}
            code = 502
        (folder/'ledger.json').write_text(json.dumps(result,indent=2))
        data=json.dumps(result).encode()
        self.send_response(code); self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)

if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--port',type=int,default=7934)
    p.add_argument('--output',type=Path,required=True); a=p.parse_args()
    key=sys.stdin.readline().strip()
    if not key.startswith('apikey_'): raise ValueError('Expected authorized Jev credential on stdin')
    a.output.mkdir(parents=True,exist_ok=True)
    server=ThreadingHTTPServer(('127.0.0.1',a.port),Handler)
    server.key=key; server.output=a.output
    print(json.dumps({'ready':True,'port':a.port,'protocol':VERSION}),flush=True)
    server.serve_forever()

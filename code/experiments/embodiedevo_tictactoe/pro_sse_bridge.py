"""Transparent, locally authenticated ChatGPT SSE transport for paired trials."""
import argparse
import gzip
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request
import uuid


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def do_GET(self):
        body = json.dumps(dict(ok=True, model="gpt-6-astra", effort="high", auth="local ChatGPT OAuth")).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        ident = uuid.uuid4().hex
        record = dict(id=ident, started=time.time(), completed=False, usage=None, run_id=self.headers.get("X-Experiment-Run", "preflight"))
        sent = False
        try:
            if self.server.transport_token and self.headers.get("Authorization") != "Bearer "+self.server.transport_token:
                raise ValueError("Invalid experiment transport credential")
            if self.path not in ("/responses", "/v1/responses"):
                raise ValueError("Only Responses requests are accepted")
            n = int(self.headers.get("Content-Length", "0"))
            if not 0 < n < 128 * 1024 * 1024:
                raise ValueError("Invalid request size")
            raw = self.rfile.read(n)
            if self.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            payload = json.loads(raw)
            if payload.get("model") != "gpt-6-astra" or payload.get("reasoning", {}).get("effort") != "high":
                raise ValueError("Expected gpt-6-astra/high")
            auth = json.loads(self.server.auth.read_text())
            if auth.get("auth_mode") != "chatgpt":
                raise ValueError("Only local ChatGPT login is accepted")
            tokens = auth["tokens"]
            # Codex provider cache hints are not accepted by the native endpoint.
            omitted = [k for k in ("prompt_cache_options", "prompt_cache_breakpoint") if k in payload]
            for k in omitted:
                payload.pop(k)
            payload.update(store=False, stream=True)
            wire = json.dumps(payload).encode()
            record.update(model=payload["model"], effort="high", request_sha256=hashlib.sha256(wire).hexdigest(),
                          request_bytes=len(wire), omitted_provider_fields=omitted)
            req = urllib.request.Request("https://chatgpt.com/backend-api/codex/responses", data=wire,
                headers={"Authorization":"Bearer "+tokens["access_token"],
                         "ChatGPT-Account-ID":tokens["account_id"], "Content-Type":"application/json",
                         "Accept":"text/event-stream", "originator":"codex_cli_rs", "User-Agent":"codex_cli_rs"})
            with urllib.request.urlopen(req, timeout=1800) as upstream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                sent = True
                for line in upstream:
                    self.wfile.write(line)
                    self.wfile.flush()
                    if line.startswith(b"data:") and line[5:].strip() != b"[DONE]":
                        event = json.loads(line[5:])
                        if event.get("type") == "response.completed":
                            result = event["response"]
                            record.update(completed=True, usage=result.get("usage"), response_model=result.get("model"), response_id=result.get("id"))
                        elif event.get("type") in ("response.failed", "error"):
                            record["upstream_error"] = event
            self.close_connection = True
        except Exception as exc:
            record["error"] = type(exc).__name__ + ": " + str(exc)[:800]
            if not sent:
                body = json.dumps({"error":{"message":record["error"],"type":"transport_error"}}).encode()
                self.send_response(502)
                self.send_header("Content-Length",str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            self.close_connection = True
        finally:
            record["elapsed_s"] = time.time()-record["started"]
            with self.server.lock:
                with (self.server.output/"usage.jsonl").open("a") as f:
                    f.write(json.dumps(record)+"\n")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--port",type=int,default=7933)
    p.add_argument("--auth",type=Path,default=Path.home()/".codex/auth.json")
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--transport-token-file",type=Path)
    a=p.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
    server=ThreadingHTTPServer(("127.0.0.1",a.port),Handler)
    server.auth=a.auth; server.output=a.output; server.lock=threading.Lock()
    server.transport_token=a.transport_token_file.read_text().strip() if a.transport_token_file else None
    print(json.dumps({"listen":a.port,"model":"gpt-6-astra","effort":"high"}),flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

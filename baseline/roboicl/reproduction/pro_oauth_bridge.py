"""Loopback Responses transport using the local signed-in ChatGPT account.

Never accepts or reads a Platform API key. Image bytes remain in memory only.
The native Responses tool-call grammar is preserved rather than flattened into
a coding-agent prompt. This transport is a reproduction-specific deviation.
"""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.request

MODEL = "gpt-6-astra"
ENDPOINT = "https://chatgpt.com/backend-api/codex/responses"
CJK = re.compile(r"[\u3400-\u9fff]")


def check_english(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key not in ("encrypted_content", "image_url"):
                check_english(item)
    elif isinstance(value, list):
        for item in value:
            check_english(item)
    elif isinstance(value, str) and not value.startswith("data:image/") and CJK.search(value):
        raise ValueError("Non-English CJK text in the final model request")


def audit(value):
    if isinstance(value, str):
        if value.startswith("data:image/"):
            return {"image_sha256": hashlib.sha256(value.encode()).hexdigest(), "characters": len(value)}
        return re.sub(r"data:image/[^;\s]+;base64,[A-Za-z0-9+/=]+", "<image omitted>", value)
    if isinstance(value, list):
        return [audit(item) for item in value]
    if isinstance(value, dict):
        return {key: audit(item) for key, item in value.items() if key != "encrypted_content"}
    return value


def pro_payload(value):
    """Remove provider-only cache hints rejected by the Pro backend.

    This does not remove text, images, tools, actions, or history messages.
    Cache performance cannot be claimed equivalent to the paper's provider.
    """
    if isinstance(value, dict):
        return {key: pro_payload(item) for key, item in value.items()
                if key not in ("prompt_cache_options", "prompt_cache_breakpoint")}
    if isinstance(value, list):
        return [pro_payload(item) for item in value]
    return value


def native_request(payload, auth_file, timeout=900):
    check_english(payload)
    if payload.get("model") != MODEL or payload.get("reasoning", {}).get("effort") != "xhigh":
        raise ValueError("Only the pinned Astra/xhigh request is authorized")
    auth = json.loads(Path(auth_file).read_text())
    if auth.get("auth_mode") != "chatgpt" or not auth.get("tokens", {}).get("access_token"):
        raise ValueError("A local ChatGPT login is required; API-key auth is refused")
    tokens = auth["tokens"]
    body = dict(pro_payload(payload), store=False, stream=True)
    wire = json.dumps(body).encode()
    request = urllib.request.Request(ENDPOINT, data=wire, headers={
        "Authorization": "Bearer " + tokens["access_token"],
        "ChatGPT-Account-ID": tokens["account_id"],
        "Content-Type": "application/json", "Accept": "text/event-stream",
        "originator": "codex_cli_rs", "User-Agent": "codex_cli_rs",
    })
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        raw = error.read(4096).decode(errors="replace")
        raise RuntimeError(f"Native Pro HTTP {error.code}: " + str(audit(raw))[:1500]) from None
    with response:
        for line in response:
            if not line.startswith(b"data:"):
                continue
            text = line[5:].strip()
            if text == b"[DONE]":
                break
            event = json.loads(text)
            if event.get("type") in ("response.failed", "response.incomplete", "error"):
                raise RuntimeError("Native Pro response failed: " + json.dumps(audit(event))[:1200])
            if event.get("type") == "response.completed":
                result = event["response"]
                if not result.get("model", "").startswith(MODEL):
                    raise RuntimeError("Wrong model in native Pro response")
                return result
    raise RuntimeError("Native Pro stream ended without a completed response")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, status, body, content_type="application/json"):
        wire = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(wire)))
        self.end_headers()
        self.wfile.write(wire)

    def do_GET(self):
        self.reply(200, {"ok": True, "model": MODEL, "effort": "xhigh", "auth": "ChatGPT", "images_persisted": False})

    def do_POST(self):
        if self.path != "/responses":
            self.reply(404, {"error": "Unsupported path"})
            return
        started = time.monotonic()
        record = {}
        try:
            count = int(self.headers.get("Content-Length", "0"))
            if not 0 < count <= 64 * 2**20:
                raise ValueError("Invalid request size")
            payload = json.loads(self.rfile.read(count))
            record = {"started": time.time(), "request": audit(payload),
                      "transport_omits": ["prompt_cache_options", "prompt_cache_breakpoint"]}
            with self.server.limit:
                result = native_request(payload, self.server.auth_file)
            record.update(response=audit(result), elapsed_s=time.monotonic()-started)
            if payload.get("stream"):
                data = ("data: " + json.dumps({"type": "response.completed", "response": result}) + "\n\n").encode()
                self.reply(200, data, "text/event-stream")
            else:
                self.reply(200, result)
        except Exception as error:
            record.update(error_type=type(error).__name__, error=str(error)[:600], elapsed_s=time.monotonic()-started)
            self.reply(502, {"error": {"message": record["error"], "type": "pro_transport_error"}})
        finally:
            with self.server.audit_lock:
                with (self.server.output / "requests.jsonl").open("a") as stream:
                    stream.write(json.dumps(record) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--auth-file", type=Path, default=Path.home()/".codex/auth.json")
    parser.add_argument("--port", type=int, default=7911)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.probe:
        response = native_request({"model": MODEL, "reasoning": {"effort": "xhigh"},
            "instructions": "Return the ready tool call. Do not use any other tools.",
            "input": [{"role": "user", "content": "Test the signed-in ChatGPT transport."}],
            "tools": [{"type": "function", "name": "ready", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}],
            "tool_choice": {"type": "function", "name": "ready"}, "parallel_tool_calls": False}, args.auth_file)
        (args.output/"probe.json").write_text(json.dumps(audit(response), indent=2))
        print(json.dumps({"model": response.get("model"), "status": response.get("status"), "output_types": [x.get("type") for x in response.get("output", [])]}))
        return
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.auth_file = args.auth_file
    server.output = args.output
    server.limit = threading.BoundedSemaphore(args.concurrency)
    server.audit_lock = threading.Lock()
    print(json.dumps({"listen": f"127.0.0.1:{args.port}", "model": MODEL, "auth": "ChatGPT"}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

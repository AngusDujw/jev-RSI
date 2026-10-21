"""Loopback Responses transport using the local signed-in ChatGPT account.

Never accepts or reads a Platform API key. Image bytes remain in memory only.
The native Responses tool-call grammar is preserved rather than flattened into
a coding-agent prompt. This transport is a reproduction-specific deviation.
An optional Jev route uses a separate user-authorized credential and forwards
the unchanged image-free gate request to the official Jev endpoint.
"""
import argparse
import hashlib
import http.client
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
JEV_RETRY_DELAYS_S = (15, 45)
PRO_RETRY_DELAYS_S = (15, 45)
CJK = re.compile(r"[\u3400-\u9fff]")


def check_english(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key not in ("encrypted_content", "image_url"):
                check_english(item)
    elif isinstance(value, list):
        for item in value:
            check_english(item)
    elif isinstance(value, str) and not value.startswith("data:image/"):
        escaped = re.findall(r"\\u([0-9a-fA-F]{4})", value)
        if CJK.search(value) or any(0x3400 <= int(code, 16) <= 0x9fff for code in escaped):
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


class ProTransportError(RuntimeError):
    def __init__(self, message, *, retryable=False, http_status=None):
        super().__init__(message)
        self.retryable = retryable
        self.http_status = http_status


def _native_pro_once(payload, auth_file, timeout=900, attempt_record=None):
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
        if attempt_record is not None:
            attempt_record["request_sent"] = True
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        raw = error.read(4096).decode(errors="replace")
        raise ProTransportError(f"Native Pro HTTP {error.code}: " + str(audit(raw))[:1500],
            retryable=error.code in (408, 429, 500, 502, 503, 504), http_status=error.code) from None
    with response:
        for line in response:
            if not line.startswith(b"data:"):
                continue
            text = line[5:].strip()
            if text == b"[DONE]":
                break
            event = json.loads(text)
            if event.get("type") in ("response.failed", "response.incomplete", "error"):
                details = event.get("response", {}).get("error") or event.get("error") or {}
                code = details.get("code") if isinstance(details, dict) else None
                raise ProTransportError("Native Pro response failed: " + json.dumps(audit(event))[:1200],
                    retryable=code in {"server_error", "internal_error", "rate_limit_exceeded",
                        "rate_limit_error", "overloaded_error", "model_capacity",
                        "model_capacity_exceeded", "model_overloaded", "service_unavailable"})
            if event.get("type") == "response.completed":
                result = event["response"]
                if attempt_record is not None:
                    attempt_record.update(model=result.get("model"), usage=result.get("usage"))
                if not result.get("model", "").startswith(MODEL):
                    raise RuntimeError("Wrong model in native Pro response")
                return result
    raise ProTransportError("Native Pro stream ended without a completed response", retryable=True)


def native_request(payload, auth_file, timeout=900, attempt_records=None):
    """Retry transport failures only; return the first completed pinned response.

    Every retry has the identical model-visible payload. A failed inference may
    have consumed quota; its unknown usage is retained rather than treated as zero.
    Socket timeouts do not provide an absolute whole-call deadline.
    """
    attempt_records = [] if attempt_records is None else attempt_records
    for attempt in range(1, 4):
        record = {"attempt": attempt, "started": time.time(), "request_sent": False}
        started = time.monotonic()
        retryable = False
        try:
            result = _native_pro_once(payload, auth_file, timeout, record)
            record.update(model=result.get("model"), usage=result.get("usage"))
            return result
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as error:
            retryable = True
            record.update(error_type=type(error).__name__, error=str(error)[:600],
                          usage_unknown=record["request_sent"])
            if attempt == 3:
                raise ProTransportError("Native Pro transport attempts exhausted: " + str(error)[:600]) from None
        except Exception as error:
            retryable = isinstance(error, ProTransportError) and error.retryable
            record.update(error_type=type(error).__name__, error=str(error)[:600],
                          http_status=getattr(error, "http_status", None),
                          usage_unknown=record["request_sent"])
            if not retryable or attempt == 3:
                raise
        finally:
            record["elapsed_s"] = time.monotonic() - started
            attempt_records.append(record)
        if retryable:
            record["retry_delay_s"] = PRO_RETRY_DELAYS_S[attempt - 1]
            time.sleep(record["retry_delay_s"])


def native_jev_request(payload, config_file, attempt_records=None):
    """Relay the unchanged, image-free gate request through the workstation."""
    check_english(payload)
    config_file = Path(config_file)
    config = json.loads(config_file.read_text())
    config = config.get("jev", config)
    if payload.get("model") != config["model"] or payload.get("assets"):
        raise ValueError("Unexpected Jev model or image assets")
    if config["base_url"].rstrip("/") != "https://api.typesafe.ai/v1":
        raise ValueError("Only the official Jev endpoint is configured")
    key_file = Path(config["key_file"])
    if not key_file.is_absolute():
        key_file = config_file.parent / key_file
    key = key_file.read_text().strip()
    request = urllib.request.Request(config["base_url"].rstrip("/") + "/systemone",
        data=json.dumps(payload).encode(), headers={"Authorization": "Bearer " + key,
        "Content-Type": "application/json"})
    attempts = config.get("max_attempts", 3)
    if type(attempts) is not int or not 1 <= attempts <= 3:
        raise ValueError("Jev transport allows one to three attempts")
    attempt_records = [] if attempt_records is None else attempt_records
    timeout = min(config.get("attempt_timeout_s", 60), 60)
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        record = {"attempt": attempt}
        try:
            with urllib.request.urlopen(request, timeout=timeout) as reply:
                result = json.load(reply)
            record.update(model=result.get("model"), usage=result.get("usage"))
            if result.get("model") != config["model"]:
                raise ValueError("Unexpected model in Jev response")
            return result
        except urllib.error.HTTPError as error:
            detail = error.read(2048).decode(errors="replace").replace(key, "[redacted]")
            message = f"Jev HTTP {error.code}: " + str(audit(detail))[:1200]
            record.update(http_status=error.code, error_type=type(error).__name__,
                          error=message, usage_unknown=True)
            if error.code not in (408, 429, 500, 502, 503, 504) or attempt == attempts:
                raise RuntimeError(message) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as error:
            message = str(error).replace(key, "[redacted]")[:600]
            record.update(error_type=type(error).__name__, error=message, usage_unknown=True)
            if attempt == attempts:
                raise RuntimeError("Jev transport attempts exhausted: " + message) from None
        finally:
            record["elapsed_s"] = time.monotonic() - started
            attempt_records.append(record)
        record["retry_delay_s"] = JEV_RETRY_DELAYS_S[attempt - 1]
        time.sleep(record["retry_delay_s"])


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
        is_jev = self.path == "/systemone" and self.server.jev_config is not None
        if self.path != "/responses" and not is_jev:
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
                      "transport_omits": [] if is_jev else ["prompt_cache_options", "prompt_cache_breakpoint"]}
            if is_jev:
                record["upstream_attempts"] = []
                with self.server.jev_limit:
                    result = native_jev_request(payload, self.server.jev_config, record["upstream_attempts"])
            else:
                record["upstream_attempts"] = []
                with self.server.limit:
                    result = native_request(payload, self.server.auth_file,
                                            attempt_records=record["upstream_attempts"])
            record.update(response=audit(result), elapsed_s=time.monotonic()-started)
            if payload.get("stream") and not is_jev:
                data = ("data: " + json.dumps({"type": "response.completed", "response": result}) + "\n\n").encode()
                self.reply(200, data, "text/event-stream")
            else:
                self.reply(200, result)
        except Exception as error:
            record.update(error_type=type(error).__name__, error=str(error)[:600], elapsed_s=time.monotonic()-started)
            self.reply(502, {"error": {"message": record["error"],
                "type": "jev_transport_error" if is_jev else "pro_transport_error"}})
        finally:
            with self.server.audit_lock:
                with (self.server.output / ("jev-requests.jsonl" if is_jev else "requests.jsonl")).open("a") as stream:
                    stream.write(json.dumps(record) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--auth-file", type=Path, default=Path.home()/".codex/auth.json")
    parser.add_argument("--port", type=int, default=7911)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--jev-config", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.probe:
        attempts = []
        response = native_request({"model": MODEL, "reasoning": {"effort": "xhigh"},
            "instructions": "Return the ready tool call. Do not use any other tools.",
            "input": [{"role": "user", "content": "Test the signed-in ChatGPT transport."}],
            "tools": [{"type": "function", "name": "ready", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}],
            "tool_choice": {"type": "function", "name": "ready"}, "parallel_tool_calls": False}, args.auth_file,
            attempt_records=attempts)
        (args.output/"probe-attempts.json").write_text(json.dumps(attempts, indent=2))
        (args.output/"probe.json").write_text(json.dumps(audit(response), indent=2))
        print(json.dumps({"model": response.get("model"), "status": response.get("status"), "output_types": [x.get("type") for x in response.get("output", [])]}))
        return
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.auth_file = args.auth_file
    server.jev_config = args.jev_config
    server.output = args.output
    server.limit = threading.BoundedSemaphore(args.concurrency)
    server.jev_limit = threading.BoundedSemaphore(args.concurrency)
    server.audit_lock = threading.Lock()
    print(json.dumps({"listen": f"127.0.0.1:{args.port}", "model": MODEL, "auth": "ChatGPT"}), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

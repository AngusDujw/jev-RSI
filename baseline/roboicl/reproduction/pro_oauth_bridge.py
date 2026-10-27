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
JEV_RETRY_DELAYS_S = (15, 45, 60, 60)
PRO_RETRY_DELAYS_S = (15, 45)
BRIDGE_IMPLEMENTATION_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
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


class ProDeadlineError(ProTransportError):
    pass


def remaining_budget(deadline):
    remaining = deadline-time.monotonic()
    if remaining <= 0:
        raise ProDeadlineError("Native Pro whole-call deadline exceeded")
    return remaining


def deadline_lines(response, deadline):
    """Bound SSE heartbeats and silent reads by one absolute deadline."""
    while True:
        remaining = remaining_budget(deadline)
        raw = getattr(getattr(response, "fp", None), "raw", None)
        sock = getattr(raw, "_sock", None)
        if sock is not None:
            sock.settimeout(remaining)
        line = response.readline()
        remaining_budget(deadline)
        if not line:
            return
        yield line


def _native_pro_once(payload, auth_file, timeout=900, attempt_record=None, *, deadline=None,
                     progress_callback=None):
    deadline = time.monotonic()+timeout if deadline is None else deadline
    progress_started = time.monotonic()
    progress = dict(event_counts={}, reasoning_items_completed=0,
        function_items_completed=0, function_argument_delta_characters=0,
        completed_function_argument_characters=0, function_argument_characters=0,
        completed_event_seen=False) if progress_callback is not None else None
    if progress is not None and attempt_record is not None:
        attempt_record["progress"] = progress

    def emit_progress():
        if progress is None:
            return
        try:
            progress_callback((attempt_record or {}).get("attempt", 0), progress)
        except Exception as error:
            # Observation failures must not change the model request or response.
            if attempt_record is not None:
                attempt_record["progress_observer_error"] = type(error).__name__
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
        response = urllib.request.urlopen(request, timeout=min(timeout, remaining_budget(deadline)))
    except urllib.error.HTTPError as error:
        raw = error.read(4096).decode(errors="replace")
        raise ProTransportError(f"Native Pro HTTP {error.code}: " + str(audit(raw))[:1500],
            retryable=error.code in (408, 429, 500, 502, 503, 504), http_status=error.code) from None
    with response:
        if progress is not None:
            progress["header_received_s"] = time.monotonic()-progress_started
            emit_progress()
        for line in deadline_lines(response, deadline):
            if not line.startswith(b"data:"):
                continue
            text = line[5:].strip()
            if text == b"[DONE]":
                break
            event = json.loads(text)
            if progress is not None:
                elapsed = time.monotonic()-progress_started
                progress.setdefault("first_sse_s", elapsed)
                progress["last_sse_s"] = elapsed
                event_type = event.get("type", "unknown")
                event_type = event_type[:120] if isinstance(event_type, str) else "unknown"
                counts = progress["event_counts"]
                counts[event_type] = counts.get(event_type, 0)+1
                item = event.get("item")
                item = item if isinstance(item, dict) else {}
                if event_type == "response.output_item.done" and item.get("type") == "reasoning":
                    progress["reasoning_items_completed"] += 1
                    progress["last_reasoning_item_s"] = elapsed
                if event_type == "response.function_call_arguments.delta":
                    delta = event.get("delta")
                    progress["function_argument_delta_characters"] += len(delta) if isinstance(delta, str) else 0
                    progress.setdefault("first_function_arguments_s", elapsed)
                if event_type == "response.output_item.done" and item.get("type") == "function_call":
                    progress["function_items_completed"] += 1
                    arguments = item.get("arguments")
                    progress["completed_function_argument_characters"] += len(arguments) if isinstance(arguments, str) else 0
                progress["function_argument_characters"] = max(
                    progress["function_argument_delta_characters"], progress["completed_function_argument_characters"])
                progress["completed_event_seen"] = event_type == "response.completed"
                emit_progress()
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


def native_request(payload, auth_file, timeout=900, attempt_records=None, *, deadline=None,
                   progress_callback=None):
    """Retry transport failures only; return the first completed pinned response.

    Every retry has the identical model-visible payload. A failed inference may
    have consumed quota; its unknown usage is retained rather than treated as zero.
    One absolute deadline covers connection, SSE reads, retries and backoff.
    """
    attempt_records = [] if attempt_records is None else attempt_records
    deadline = time.monotonic()+timeout if deadline is None else deadline
    for attempt in range(1, 4):
        remaining_budget(deadline)
        record = {"attempt": attempt, "started": time.time(), "request_sent": False}
        started = time.monotonic()
        retryable = False
        try:
            result = _native_pro_once(payload, auth_file, min(timeout, remaining_budget(deadline)), record,
                                      deadline=deadline, progress_callback=progress_callback)
            record.update(model=result.get("model"), usage=result.get("usage"))
            return result
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as error:
            retryable = True
            record.update(error_type=type(error).__name__, error=str(error)[:600],
                          usage_unknown=record["request_sent"])
            if time.monotonic() >= deadline:
                raise ProDeadlineError("Native Pro whole-call deadline exceeded") from None
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
            if record["retry_delay_s"] >= remaining_budget(deadline):
                record["retry_skipped"] = "Insufficient whole-call deadline budget"
                raise ProDeadlineError("Native Pro retry would exceed whole-call deadline")
            time.sleep(record["retry_delay_s"])


class JevDeadlineError(RuntimeError):
    pass


def jev_remaining_budget(deadline):
    remaining = deadline-time.monotonic()
    if remaining <= 0:
        raise JevDeadlineError("Jev whole-call deadline exceeded")
    return remaining


def jev_json_response(reply, deadline, timeout):
    """Read a small JSON response without allowing slow chunks to reset its budget."""
    chunks, size = [], 0
    while True:
        remaining = jev_remaining_budget(deadline)
        raw = getattr(getattr(reply, "fp", None), "raw", None)
        sock = getattr(raw, "_sock", None)
        if sock is not None:
            sock.settimeout(min(timeout, remaining))
        chunk = reply.read1(65536)
        jev_remaining_budget(deadline)
        if not chunk:
            break
        size += len(chunk)
        if size > 2 * 2**20:
            raise ValueError("Jev JSON response exceeds 2 MiB")
        chunks.append(chunk)
    return json.loads(b"".join(chunks))


def native_jev_request(payload, config_file, attempt_records=None, *, deadline=None):
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
    attempts = config.get("max_attempts", 5)
    if type(attempts) is not int or not 1 <= attempts <= 5:
        raise ValueError("Jev transport allows one to five attempts")
    attempt_records = [] if attempt_records is None else attempt_records
    timeout = min(config.get("attempt_timeout_s", 60), 60)
    deadline = time.monotonic()+900 if deadline is None else deadline
    for attempt in range(1, attempts + 1):
        remaining = jev_remaining_budget(deadline)
        started = time.monotonic()
        record = {"attempt": attempt}
        try:
            record["request_sent"] = True
            with urllib.request.urlopen(request, timeout=min(timeout, remaining)) as reply:
                result = jev_json_response(reply, deadline, timeout)
            record.update(model=result.get("model"), usage=result.get("usage"))
            jev_remaining_budget(deadline)
            if result.get("model") != config["model"]:
                raise ValueError("Unexpected model in Jev response")
            return result
        except JevDeadlineError as error:
            record.update(error_type=type(error).__name__, error=str(error), usage_unknown=record.get("usage") is None)
            raise
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
        if record["retry_delay_s"] >= jev_remaining_budget(deadline):
            record["retry_skipped"] = "Insufficient whole-call deadline budget"
            raise JevDeadlineError("Jev retry would exceed whole-call deadline")
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
                      "transport_implementation_sha256": BRIDGE_IMPLEMENTATION_SHA256,
                      "transport_omits": [] if is_jev else ["prompt_cache_options", "prompt_cache_breakpoint"]}
            if is_jev:
                record["upstream_attempts"] = []
                requested_budget = float(self.headers.get("X-Model-Request-Timeout-Seconds", "900"))
                if not .1 <= requested_budget <= 900:
                    raise ValueError("Jev request budget must be 0.1..900 seconds")
                deadline = started+requested_budget
                record["request_budget_s"] = requested_budget
                if not self.server.jev_limit.acquire(timeout=jev_remaining_budget(deadline)):
                    raise JevDeadlineError("Jev deadline while waiting for relay slot")
                try:
                    result = native_jev_request(payload, self.server.jev_config, record["upstream_attempts"], deadline=deadline)
                finally:
                    self.server.jev_limit.release()
            else:
                record["upstream_attempts"] = []
                progress_callback = None
                if getattr(self.server, "progress_metadata", False):
                    request_hash = hashlib.sha256(json.dumps(record["request"], sort_keys=True,
                        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
                    call_tag = f"{time.time_ns()}-{request_hash[:16]}"

                    def progress_callback(attempt, progress):
                        path = self.server.output / f"{call_tag}-attempt-{attempt}.progress.json"
                        pending = path.with_suffix(".pending")
                        metadata = dict(request_sha256=request_hash, tool=payload.get("tool_choice"),
                            attempt=attempt, updated_at=time.time(), progress=progress,
                            text_recorded=False)
                        pending.write_text(json.dumps(metadata))
                        pending.replace(path)
                requested_budget = float(self.headers.get("X-Model-Request-Timeout-Seconds", "900"))
                if not .1 <= requested_budget <= 1800:
                    raise ValueError("Pro request budget must be 0.1..1800 seconds")
                deadline = started+requested_budget
                record["request_budget_s"] = requested_budget
                if not self.server.limit.acquire(timeout=remaining_budget(deadline)):
                    raise ProDeadlineError("Native Pro deadline while waiting for relay slot")
                try:
                    result = native_request(payload, self.server.auth_file,
                                            attempt_records=record["upstream_attempts"], deadline=deadline,
                                            progress_callback=progress_callback)
                finally:
                    self.server.limit.release()
            record.update(response=audit(result), elapsed_s=time.monotonic()-started)
            if payload.get("stream") and not is_jev:
                data = ("data: " + json.dumps({"type": "response.completed", "response": result}) + "\n\n").encode()
                self.reply(200, data, "text/event-stream")
            else:
                self.reply(200, result)
        except Exception as error:
            record.update(error_type=type(error).__name__, error=str(error)[:600], elapsed_s=time.monotonic()-started)
            self.reply(504 if isinstance(error, (ProDeadlineError, JevDeadlineError)) else 502, {"error": {"message": record["error"],
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
    parser.add_argument("--progress-metadata", action="store_true",
        help="Save live SSE timing/count metadata without reasoning text or method arguments")
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
    server.progress_metadata = args.progress_metadata
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

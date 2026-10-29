"""Metadata-only timing and signal diagnostics for the historical Pro bridge.

No Platform credentials, prompt edits, reasoning text logs or partial execution.
Unlimited mode removes application/socket read deadlines, not provider limits.
Retries remain bounded by the historical three-attempt policy.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
import uuid
import _thread


def atomic(path, value):
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(json.dumps(value, indent=2) + "\n")
    pending.replace(path)


def append(path, value):
    with path.open("a") as stream:
        stream.write(json.dumps(dict(epoch=time.time(), **value)) + "\n")


def lifecycle(folder, *, capture_sender=True):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "lifecycle.jsonl"
    append(path, dict(event="started", pid=os.getpid(), ppid=os.getppid(),
                      pgid=os.getpgid(0), sid=os.getsid(0)))
    # sigwaitinfo records the sender PID/UID; a normal Python handler cannot.
    watched = {signal.SIGTERM, signal.SIGHUP}
    if capture_sender:
        signal.pthread_sigmask(signal.SIG_BLOCK, watched)
    else:
        # Workers must not inherit a blocked SIGTERM mask from the host.
        def terminate(signum, frame):
            append(path, dict(event="signal_received", signal=signum,
                              sender_pid=None, sender_scope="Unavailable in Python handler"))
            raise KeyboardInterrupt
        for signum in watched:
            signal.signal(signum, terminate)

    def receive():
        info = signal.sigwaitinfo(watched)
        append(path, dict(event="signal_received", signal=info.si_signo,
                          sender_pid=info.si_pid, sender_uid=info.si_uid,
                          signal_code=info.si_code))
        _thread.interrupt_main()

    if capture_sender:
        threading.Thread(target=receive, daemon=True).start()

    def heartbeat():
        while True:
            append(path, dict(event="alive", pid=os.getpid(), ppid=os.getppid()))
            time.sleep(15)

    threading.Thread(target=heartbeat, daemon=True).start()
    return path


class Trace:
    def __init__(self, folder, payload):
        self.folder = folder / ("attempt-" + uuid.uuid4().hex)
        self.folder.mkdir()
        self.started = time.monotonic()
        self.last_save = 0.
        self.state = dict(started_epoch=time.time(), pid=os.getpid(), events={},
                          argument_characters=0, first_event_s=None,
                          first_argument_s=None, first_reasoning_event_s=None,
                          last_event_s=None, max_event_gap_s=0.,
                          payload_sha256=hashlib.sha256(json.dumps(payload,
                              sort_keys=True).encode()).hexdigest(),
                          scope="Client-observed events; not pure server compute time")
        self.save()

    def save(self):
        atomic(self.folder / "progress.json", self.state)
        self.last_save = time.monotonic()

    def mark(self, kind, **data):
        elapsed = time.monotonic() - self.started
        append(self.folder / "events.jsonl", dict(elapsed_s=elapsed, kind=kind, **data))

    def event(self, event):
        kind = event.get("type", "unknown")
        elapsed = time.monotonic() - self.started
        self.state["events"][kind] = self.state["events"].get(kind, 0) + 1
        last = self.state["last_event_s"]
        self.state["max_event_gap_s"] = max(self.state["max_event_gap_s"],
                                             elapsed - last if last is not None else 0)
        self.state["last_event_s"] = elapsed
        if self.state["first_event_s"] is None:
            self.state["first_event_s"] = elapsed
            self.mark("first_event", event_type=kind)
        item_type = event.get("item", {}).get("type")
        if item_type == "reasoning" and self.state["first_reasoning_event_s"] is None:
            self.state["first_reasoning_event_s"] = elapsed
        if kind == "response.function_call_arguments.delta":
            if self.state["first_argument_s"] is None:
                self.state["first_argument_s"] = elapsed
                self.mark("first_argument")
            self.state["argument_characters"] += len(event.get("delta", ""))
        if not kind.endswith(".delta"):
            self.mark("stream_event", event_type=kind, item_type=item_type)
        if kind == "response.completed":
            usage = event.get("response", {}).get("usage", {})
            self.state["usage"] = {k: usage[k] for k in (
                "input_tokens", "output_tokens", "input_tokens_details",
                "output_tokens_details") if k in usage}
        if time.monotonic() - self.last_save >= 1 or kind == "response.completed":
            self.save()


def instrument(bridge, output):
    context = threading.local()
    once = bridge._native_pro_once
    lines = bridge.deadline_lines
    urlopen = bridge.urllib.request.urlopen
    chunk_left = http.client.HTTPResponse._get_chunk_left

    def opened(request, *args, **kwargs):
        trace = getattr(context, "trace", None)
        if trace is not None and request.full_url == bridge.ENDPOINT:
            kwargs["timeout"] = None
            response = urlopen(request, *args, **kwargs)
            trace.mark("response_headers", status=response.status)
            return response
        return urlopen(request, *args, **kwargs)

    def chunk(self, *args, **kwargs):
        try:
            return chunk_left(self, *args, **kwargs)
        except Exception as error:
            trace = getattr(context, "trace", None)
            if trace is not None:
                trace.mark("http_chunk_error", error_type=type(error).__name__,
                           message=str(error)[:300])
            raise

    def observed(response, deadline):
        trace = context.trace
        raw = getattr(getattr(response, "fp", None), "raw", None)
        sock = getattr(raw, "_sock", None)
        if sock is not None:
            sock.settimeout(None)
        while True:
            line = response.readline()
            if not line:
                trace.mark("stream_eof")
                return
            if line.startswith(b"data:"):
                value = line[5:].strip()
                if value and value != b"[DONE]":
                    trace.event(json.loads(value))
            yield line

    def measured(payload, auth_file, timeout=900, attempt_record=None, *, deadline=None):
        trace = Trace(output, payload)
        context.trace = trace
        try:
            result = once(payload, auth_file, float("inf"), attempt_record,
                          deadline=float("inf"))
            trace.state["status"] = "completed"
            return result
        except BaseException as error:
            trace.state.update(status="failed", error_type=type(error).__name__,
                               error=str(error)[:500])
            raise
        finally:
            trace.state["elapsed_s"] = time.monotonic() - trace.started
            trace.save()
            trace.mark("attempt_finished", status=trace.state.get("status"))
            context.trace = None

    bridge._native_pro_once = measured
    bridge.deadline_lines = observed
    bridge.urllib.request.urlopen = opened
    http.client.HTTPResponse._get_chunk_left = chunk
    return (once, lines, urlopen, chunk_left)


def restore_images(payload, folder):
    for message in payload["input"]:
        camera = None
        for item in message["content"]:
            if item["type"] == "input_text" and item["text"].startswith("Current "):
                camera = item["text"].split(";")[0].split()[1]
            if item["type"] == "input_image" and isinstance(item["image_url"], dict):
                encoded = "data:image/jpeg;base64," + base64.b64encode(
                    (folder / ("gpt-00-" + camera + ".jpg")).read_bytes()).decode()
                if hashlib.sha256(encoded.encode()).hexdigest() != item["image_url"]["image_sha256"]:
                    raise ValueError("Saved image does not match exact request hash")
                item["image_url"] = encoded
    return payload


def serve(bridge, args):
    class Handler(bridge.Handler):
        def do_POST(self):
            is_jev = self.path == "/systemone"
            if self.path not in ("/responses", "/systemone"):
                self.reply(404, {"error": "Unsupported path"})
                return
            record = {}
            started = time.monotonic()
            try:
                count = int(self.headers.get("Content-Length", "0"))
                if not 0 < count <= 64 * 2**20:
                    raise ValueError("Invalid request size")
                payload = json.loads(self.rfile.read(count))
                record = dict(started=time.time(), request=bridge.audit(payload),
                              upstream_attempts=[], request_budget_s=None)
                with self.server.limit:
                    if is_jev:
                        result = bridge.native_jev_request(payload, args.jev_config,
                                                          record["upstream_attempts"])
                    else:
                        result = bridge.native_request(payload, args.auth_file,
                            attempt_records=record["upstream_attempts"],
                            timeout=float("inf"), deadline=float("inf"))
                record.update(response=bridge.audit(result))
                self.reply(200, result)
            except Exception as error:
                record.update(error_type=type(error).__name__, error=str(error)[:600])
                self.reply(502, {"error": {"message": record["error"], "type": "diagnostic_transport_error"}})
            finally:
                record["elapsed_s"] = time.monotonic() - started
                with self.server.audit_lock:
                    append(args.output / ("jev-requests.jsonl" if is_jev else "requests.jsonl"), record)

    server = bridge.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.limit = threading.BoundedSemaphore(1)
    server.audit_lock = threading.Lock()
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("replay", "bridge", "host", "life"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--auth-file", type=Path, default=Path.home()/".codex/auth.json")
    parser.add_argument("--jev-config", type=Path)
    parser.add_argument("--port", type=int, default=7921)
    args, remaining = parser.parse_known_args()
    if remaining[:1] == ["--"]:
        remaining = remaining[1:]
    if remaining and args.mode != "host":
        parser.error("Unexpected arguments")
    args.output.mkdir(parents=True, exist_ok=True)
    path = lifecycle(args.output, capture_sender=args.mode != "host")
    try:
        if args.mode == "life":
            while True:
                time.sleep(1)
        if args.mode == "host":
            root = Path(__file__).resolve().parents[3]
            sys.path.insert(0, str(root / "code/scripts"))
            import run_gpt_jev_program as host
            sys.argv = [host.__file__, *remaining]
            host.main()
            return
        import pro_oauth_bridge as bridge
        instrument(bridge, args.output)
        if args.mode == "bridge":
            serve(bridge, args)
        else:
            payload = restore_images(json.loads(args.request.read_text()), args.request.parent)
            bridge.check_english(payload)
            record = dict(request=bridge.audit(payload), upstream_attempts=[], started=time.time())
            started = time.monotonic()
            try:
                result = bridge.native_request(payload, args.auth_file,
                    attempt_records=record["upstream_attempts"],
                    timeout=float("inf"), deadline=float("inf"))
                record.update(response=bridge.audit(result), completed=True)
                atomic(args.output / "response.json", result)
            except Exception as error:
                record.update(completed=False, error_type=type(error).__name__, error=str(error)[:600])
            finally:
                record["elapsed_s"] = time.monotonic() - started
                atomic(args.output / "result.json", record)
    except KeyboardInterrupt:
        append(path, dict(event="interrupted"))
    finally:
        append(path, dict(event="exited"))


if __name__ == "__main__":
    main()

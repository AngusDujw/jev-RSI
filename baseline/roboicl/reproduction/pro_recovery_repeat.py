"""Repeated exact-input Pro delivery and persistent-thread fault diagnostics.

Uses local ChatGPT auth only. No robot, Platform key, hidden-reasoning logs,
prompt edits, or application generation deadline. Raw and native framing differ.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import signal
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

from pro_session_client import NativeRpc, SessionPlanner, atomic, validate_submission, digest

ROOT = Path(__file__).resolve().parents[3]


def append(path, value):
    with path.open("a") as stream:
        stream.write(json.dumps(dict(epoch=time.time(), **value)) + "\n")


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def diagnostic_modules(folder):
    base = folder / "baseline/roboicl/reproduction"
    bridge = load_file("repeat_historical_bridge", base / "pro_oauth_bridge.py")
    timing = load_file("repeat_timing", base / "pro_timing_diagnostic.py")
    return bridge, timing


def payload_from(request, diagnostic):
    _, timing = diagnostic_modules(diagnostic)
    payload = timing.restore_images(json.loads(request.read_text()), request.parent)
    if payload["model"] != "gpt-6-astra" or payload["reasoning"]["effort"] != "xhigh":
        raise ValueError("Pinned model/effort required")
    return payload


def complete_method(response, payload):
    calls = [x for x in response.get("output", []) if x.get("type") == "function_call"]
    if len(calls) != 1 or calls[0]["name"] != payload["tools"][0]["name"]:
        raise ValueError("Unexpected function result")
    answer = json.loads(calls[0]["arguments"])
    validate_submission(answer, payload["tools"][0])
    return answer


def raw_case(args):
    bridge, timing = diagnostic_modules(args.diagnostic)
    payload = payload_from(args.request, args.diagnostic)
    original = bridge.urllib.request.urlopen

    def headers(request, *values, **kwargs):
        result = original(request, *values, **kwargs)
        if request.full_url == bridge.ENDPOINT:
            allowed = ("server", "via", "cf-ray", "x-request-id", "content-type",
                       "connection", "transfer-encoding", "content-length")
            append(args.output / "headers.jsonl", dict(status=result.status,
                http_version=result.version,
                headers={k: result.getheader(k) for k in allowed if result.getheader(k)}))
        return result

    bridge.urllib.request.urlopen = headers
    timing.instrument(bridge, args.output)
    record = dict(arm="raw", payload_sha256=digest(payload), started=time.time(),
                  retry_policy="One independent upstream attempt; no automatic resend")
    started = time.monotonic()
    attempt = {}
    try:
        response = bridge._native_pro_once(payload, Path.home()/".codex/auth.json",
            float("inf"), attempt, deadline=float("inf"))
        atomic(args.output / "response.json", response)
        record["response_completed"] = True
        method = complete_method(response, payload)
        atomic(args.output / "method.json", method)
        record.update(completed=True,
            source_sha256=hashlib.sha256(method["source"].encode()).hexdigest(),
            source_lines=len(method["source"].splitlines()))
    except Exception as error:
        record.update(completed=False, error_type=type(error).__name__, error=str(error)[:700])
    finally:
        record.update(elapsed_s=time.monotonic()-started, upstream_attempt=attempt)
        if not record.get("response_completed"):
            record["usage_unknown"] = True
        atomic(args.output / "result.json", record)


def inject_faults(planner, count, interval, stop, output):
    injected = 0
    last = time.monotonic()
    killed = set()
    while not stop.wait(.2):
        if injected >= count or time.monotonic()-last < interval:
            continue
        rpc = planner.rpc
        state = planner.state
        if rpc is None or not state.get("thread_id") or not state.get("turns"):
            continue
        if state.get("status") not in ("generating", "continuing") or state.get("submission"):
            continue
        process = rpc.process
        if process.pid in killed or process.poll() is not None:
            continue
        evidence = dict(kind="own_rpc_process_termination",
            pid=process.pid, thread_id=state["thread_id"],
            turns=[dict(x) for x in state["turns"]],
            events=dict(state["events"]), partial_usage=state.get("token_usage"))
        try:
            process.terminate()
        except ProcessLookupError:
            continue
        killed.add(process.pid)
        append(output / "injected-faults.jsonl", evidence)
        injected += 1
        last = time.monotonic()


def native_case(args):
    payload = payload_from(args.request, args.diagnostic)
    class ObservedRpc(NativeRpc):
        def next(self):
            event = super().next()
            if event.get("method") == "item/completed":
                params = event.get("params", {})
                item = params.get("item", {})
                append(args.output / "native-items.jsonl", dict(
                    thread_id=params.get("threadId"), turn_id=params.get("turnId"),
                    item_id=item.get("id"), item_type=item.get("type")))
            return event

    planner = SessionPlanner(payload, args.output / "session", float("inf"),
                             rpc_factory=ObservedRpc)
    stop = threading.Event()
    fault = threading.Thread(target=inject_faults,
        args=(planner, args.faults, args.fault_interval, stop, args.output), daemon=True)
    fault.start()
    record = dict(arm="native", payload_sha256=digest(payload), started=time.time(),
                  requested_faults=args.faults, fault_interval=args.fault_interval)
    started = time.monotonic()
    try:
        response, state = planner.run()
        atomic(args.output / "response.json", response)
        method = complete_method(response, payload)
        atomic(args.output / "method.json", method)
        record.update(completed=True, thread_id=state["thread_id"], turns=state["turns"],
            recoveries=state["recoveries"], usage=response.get("usage"),
            source_sha256=hashlib.sha256(method["source"].encode()).hexdigest(),
            source_lines=len(method["source"].splitlines()),
            accounting_scope="Native thread aggregate, not exact provider attempt count")
    except Exception as error:
        record.update(completed=False, error_type=type(error).__name__, error=str(error)[:700],
            thread_id=planner.state.get("thread_id"), turns=planner.state.get("turns"),
            recoveries=planner.state.get("recoveries"), usage_unknown=True)
    finally:
        stop.set()
        fault.join(timeout=2)
        injected = args.output / "injected-faults.jsonl"
        faults = [json.loads(line) for line in injected.read_text().splitlines()] if injected.exists() else []
        record.update(elapsed_s=time.monotonic()-started, injected_faults=len(faults),
            model_turns_started=len(planner.state.get("turns", [])),
            same_thread_after_faults=all(x["thread_id"] == planner.state.get("thread_id") for x in faults),
            requested_faults_observed=len(faults) == args.faults,
            observed_rpc_reconnects=sum(x["kind"] == "rpc_reconnect"
                for x in planner.state.get("recoveries", [])))
        atomic(args.output / "result.json", record)


def public_probe(args):
    conn = None
    ident = 0
    proxy = urllib.request.getproxies().get("https")
    while not (args.output / "stop").exists():
        started = time.monotonic()
        record = dict(kind="unauthenticated_public_https", host="chatgpt.com",
                      path="/favicon.ico")
        try:
            if conn is None or conn.sock is None:
                if proxy:
                    parsed = urllib.parse.urlsplit(proxy)
                    if parsed.scheme != "http" or parsed.username:
                        raise ValueError("Probe requires the existing plain HTTP proxy without credentials")
                    conn = http.client.HTTPSConnection(parsed.hostname, parsed.port or 80,
                        timeout=10, context=ssl.create_default_context())
                    conn.set_tunnel("chatgpt.com", 443)
                else:
                    conn = http.client.HTTPSConnection("chatgpt.com", timeout=10)
                conn.connect()
                ident += 1
            record.update(connection_id=ident, tls_version=conn.sock.version())
            conn.request("GET", "/favicon.ico", headers={"Connection": "keep-alive"})
            response = conn.getresponse()
            body = response.read(262144)
            record.update(status=response.status, bytes_received=len(body),
                          reachable_http=True, connection_will_close=response.will_close)
            if len(body) == 262144 or response.will_close:
                conn.close()
                conn = None
        except Exception as error:
            record.update(error_type=type(error).__name__, error=str(error)[:400],
                          reachable_http=False)
            if conn is not None:
                conn.close()
            conn = None
        record["elapsed_s"] = time.monotonic()-started
        append(args.output / "probe.jsonl", record)
        for _ in range(20):
            if (args.output / "stop").exists():
                break
            time.sleep(1)
    if conn is not None:
        conn.close()


def batch(args):
    cases = [("native-1", "native", 0), ("native-2", "native", 1),
             ("native-3", "native", 2)] if args.mode == "native-batch" else [
             ("raw-1", "raw", 0), ("native-1", "native", 0),
             ("raw-2", "raw", 0), ("native-2", "native", 1),
             ("raw-3", "raw", 0), ("native-3", "native", 2)]
    record = dict(started=time.time(), cases=[], current=None, completed=False)
    try:
        for name, mode, faults in cases:
            output = args.output / name
            if output.exists():
                raise ValueError("Use a fresh case directory; never overwrite a declared trial")
            output.mkdir()
            command = [sys.executable, "-B", __file__, mode, "--output", str(output),
                "--request", str(args.request), "--diagnostic", str(args.diagnostic),
                "--faults", str(faults), "--fault-interval", str(args.fault_interval)]
            record["current"] = name
            with (output / "console.log").open("w") as log:
                process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
                record["child_pid"] = process.pid
                atomic(args.output / "batch.json", record)
                code = process.wait()
            result = output / "result.json"
            if not result.exists():
                atomic(result, dict(completed=False, infrastructure_exit=code,
                    error="Case process exited without a terminal receipt", usage_unknown=True))
            record["cases"].append(dict(name=name, exit_code=code,
                result=json.loads(result.read_text())))
            atomic(args.output / "batch.json", record)
        record["completed"] = True
    finally:
        record["finished"] = time.time()
        atomic(args.output / "batch.json", record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("raw", "native", "batch", "native-batch", "probe"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--diagnostic", type=Path,
        default=ROOT/".worktrees/gpt-jev-timing-unlimited-20261029")
    parser.add_argument("--faults", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--fault-interval", type=float, default=45.)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.request is not None:
        args.request = args.request.resolve()
    if args.mode != "probe" and args.request is None:
        parser.error("--request required")
    {"raw": raw_case, "native": native_case, "batch": batch, "native-batch": batch,
     "probe": public_probe}[args.mode](args)


if __name__ == "__main__":
    main()

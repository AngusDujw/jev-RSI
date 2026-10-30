"""Idempotent local jobs: HTTP disconnects never cancel native Pro inference."""
import json
from pathlib import Path
import re
import threading
import time

from pro_session_client import SessionPlanner, atomic, digest


class SessionJobs:
    def __init__(self, output, semaphore, audit_lock, audit, implementation):
        self.output = Path(output)
        self.semaphore, self.audit_lock = semaphore, audit_lock
        self.audit, self.implementation = audit, implementation
        self.lock = threading.Lock()
        self.running = set()

    def folder(self, ident):
        if not re.fullmatch(r"[a-f0-9]{32}", ident):
            raise ValueError("A 32-character hexadecimal X-Request-ID is required")
        return self.output / "jobs" / ident

    def submit(self, ident, payload, budget):
        folder = self.folder(ident)
        signature = digest(payload)
        with self.lock:
            folder.mkdir(parents=True, exist_ok=True)
            meta = folder / "job.json"
            if meta.exists():
                value = json.loads(meta.read_text())
                if value["payload_sha256"] != signature:
                    raise ValueError("Request ID already belongs to different input")
            else:
                value = dict(payload_sha256=signature, deadline=None if budget is None else time.time()+budget,
                    started=time.time(), job_id=ident)
                atomic(meta, value)
            if not (folder / "result.json").exists() and ident not in self.running:
                self.running.add(ident)
                threading.Thread(target=self.execute, args=(ident, payload, value),
                    daemon=True, name="pro-session-"+ident[:8]).start()
        return self.get(ident)

    def execute(self, ident, payload, meta):
        folder = self.folder(ident)
        deadline = float("inf") if meta["deadline"] is None else time.monotonic()+max(0, meta["deadline"]-time.time())
        record = dict(started=meta["started"], request=self.audit(payload), job_id=ident,
            transport_implementation_sha256=self.implementation, transport_omits=[],
            transport_kind="codex_app_server", upstream_attempts=[])
        try:
            remaining = deadline-time.monotonic()
            admitted = self.semaphore.acquire() if meta["deadline"] is None else (
                remaining > 0 and self.semaphore.acquire(timeout=remaining))
            if not admitted:
                raise TimeoutError("Native job deadline exhausted while queued")
            try:
                response, state = SessionPlanner(payload, folder, deadline).run()
            finally:
                self.semaphore.release()
            record.update(response=self.audit(response), native_session=state,
                accounting_scope="Native thread aggregate; internal provider attempt count unavailable")
            # Native aggregate is one accounting record, not one upstream HTTP attempt.
            record["native_accounting"] = [dict(usage=response.get("usage"),
                kind="native_thread_aggregate", status="completed")]
            if state.get("recoveries"):
                record["native_accounting"].append(dict(usage=None,
                    kind="native_recovery_usage_unknown", status="unknown"))
            result = dict(status="completed", response=response, job_id=ident)
        except Exception as error:
            record.update(error_type=type(error).__name__, error=str(error)[:600])
            record["native_accounting"] = [dict(usage=None, kind="native_failed_job")]
            result = dict(status="failed", job_id=ident,
                error=dict(type=type(error).__name__, message=str(error)[:600]))
            session = folder / "session.json"
            try:
                state = json.loads(session.read_text()) if session.exists() else {}
                result["validation_errors"] = [item["error"] for item in
                    state.get("invalid_submissions", [])[-3:] if "error" in item]
            except (OSError, ValueError, KeyError, TypeError):
                result["validation_errors"] = []  # Diagnostics cannot mask the original failure.
        record["elapsed_s"] = time.time()-meta["started"]
        atomic(folder / "receipt.json", record)
        # Exactly one receipt per job. Polling and duplicate POSTs never add calls.
        with self.audit_lock:
            ledger = self.output / "requests.jsonl"
            seen = set()
            if ledger.exists():
                seen = {json.loads(line).get("job_id") for line in ledger.read_text().splitlines() if line}
            if ident not in seen:
                with ledger.open("a") as stream:
                    stream.write(json.dumps(record)+"\n")
        atomic(folder / "result.json", result)
        with self.lock:
            self.running.discard(ident)

    def get(self, ident):
        folder = self.folder(ident)
        if not (folder / "job.json").exists():
            return 404, dict(status="missing", job_id=ident)
        result = folder / "result.json"
        if result.exists():
            value = json.loads(result.read_text())
            if value["status"] == "completed":
                return 200, value["response"]
            return 502, dict(**value, terminal=True)
        if ident not in self.running:
            # The bridge restarted. Ask the client to attach its original
            # payload under the same ID; no image request is kept in our ledger.
            return 404, dict(status="reattach_required", job_id=ident)
        session = folder / "session.json"
        state = json.loads(session.read_text()) if session.exists() else {}
        return 202, dict(status=state.get("status", "queued"), job_id=ident,
            poll_path="/responses/jobs/"+ident,
            thread_id=state.get("thread_id"), recoveries=len(state.get("recoveries", [])))

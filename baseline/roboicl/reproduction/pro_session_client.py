"""Pinned ChatGPT Codex sessions for recoverable, tool-only planner requests.

The app-server owns provider reconnection and conversation history. A failed
stream can be continued in the same native thread; this is not a claim that a
provider resumes an unfinished inference token-for-token. No Platform key is
accepted. Only validated complete dynamic-tool arguments leave this adapter.
"""
from __future__ import annotations

from collections import deque
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import sys
import time

MODEL = "gpt-6-astra"
EFFORT = "xhigh"
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code/scripts"))
from gpt_jev_review_contract import validate_value
from gpt_jev_program_worker import validate_source
from gpt_jev_contract import english


def atomic(path, value):
    path = Path(path)
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n")
    pending.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def session_config():
    config = {
        "model_provider": "openai", "forced_login_method": "chatgpt",
        "model": MODEL, "model_reasoning_effort": EFFORT,
        "model_reasoning_summary": "none", "project_doc_max_bytes": 0,
        "developer_instructions": "", "approval_policy": "never",
        "sandbox_mode": "read-only", "web_search": "disabled",
        "include_permissions_instructions": False, "include_apps_instructions": False,
        "include_collaboration_mode_instructions": False,
        "skills.include_instructions": False,
    }
    for name in ("shell_tool", "apps", "remote_plugin", "hooks", "skill_search",
                 "multi_agent", "multi_agent_v2", "browser_use", "computer_use",
                 "view_image", "sleep_tool", "unbounded_connection_retries"):
        config["features." + name] = False
    config["features.skip_host_skill_discovery"] = True
    return config


class RpcDisconnected(RuntimeError):
    pass


class NativeRpc:
    """Bounded JSONL RPC. Never save raw events or reasoning summaries."""

    def __init__(self, cwd, deadline, *, command=None):
        self.deadline = deadline
        self.inbox = deque()
        self.buffer = b""
        self.counter = 0
        self.stderr = b""
        if command is None:
            executable = shutil.which("codex")
            if executable is None:
                raise FileNotFoundError("Codex executable is missing from PATH; pass the local Codex bin directory to the service environment")
            # Mask global guidance only in this child mount namespace. Do not
            # edit user files, change CODEX_HOME, or copy account credentials.
            cwd = Path(cwd).resolve()
            clean_config = cwd / "native-config.toml"
            clean_config.write_text('forced_login_method = "chatgpt"\n')
            empty = cwd / "empty-guidance"
            empty.mkdir(exist_ok=True)
            command = ["bwrap", "--die-with-parent", "--bind", "/", "/",
                "--ro-bind", str(clean_config), str(Path.home()/".codex/config.toml")]
            for target in (Path.home()/".codex/skills", Path.home()/".agents/skills",
                           Path.home()/".codex/plugins", ROOT/".agents/skills"):
                if target.is_dir():
                    command += ["--ro-bind", str(empty), str(target)]
            for name in ("AGENTS.md", "AGENTS.override.md"):
                target = Path.home() / ".codex" / name
                if target.exists():
                    command += ["--ro-bind", "/dev/null", str(target)]
            command += ["--", executable, "app-server", "--stdio"] + [
                part for key, value in session_config().items()
                for part in ("-c", key + "=" + json.dumps(value))]
        env = dict(os.environ)
        for name in list(env):
            if name.startswith(("AGENTSDOCK_", "AGENTS_SERVER_")) or name in (
                    "CODEX_THREAD_ID", "CODEX_SESSION_ID", "CODEX_TOOL_CALL_ID"):
                env.pop(name, None)
        for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID",
                     "OPENAI_PROJECT", "ANTHROPIC_API_KEY"):
            env.pop(name, None)
        env.update(TMPDIR=str(cwd), TMP=str(cwd), TEMP=str(cwd))
        self.process = subprocess.Popen(command, cwd=cwd, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ, "out")
        self.selector.register(self.process.stderr, selectors.EVENT_READ, "err")
        try:
            self.call("initialize", dict(clientInfo=dict(name="jev_method_session",
                version="1"), capabilities=dict(experimentalApi=True)))
            self.send(dict(method="initialized", params={}))
        except BaseException:
            self.close()
            raise

    def send(self, value):
        try:
            self.process.stdin.write(json.dumps(value).encode() + b"\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise RpcDisconnected("Native session RPC disconnected") from error

    def raw(self, limit=None):
        end = min(self.deadline, limit) if limit is not None else self.deadline
        while time.monotonic() < end:
            if b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                if line.strip():
                    return json.loads(line)
            if len(self.buffer) > 16 * 1024 * 1024:
                raise ValueError("Oversized native RPC message")
            for key, _ in self.selector.select(min(1., max(.01, end-time.monotonic()))):
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    self.selector.unregister(key.fileobj)
                    if key.data == "out":
                        raise RpcDisconnected("Native app-server stdout closed")
                elif key.data == "out":
                    self.buffer += data
                else:
                    # Retain no raw stderr on disk; only a bounded in-memory tail.
                    self.stderr = (self.stderr + data)[-4096:]
            if self.process.poll() is not None and not self.buffer:
                raise RpcDisconnected("Native app-server exited")
        raise TimeoutError("Native planner logical request deadline exceeded")

    def next(self):
        return self.inbox.popleft() if self.inbox else self.raw()

    def call(self, method, params, timeout=45):
        self.counter += 1
        ident = self.counter
        self.send(dict(id=ident, method=method, params=params))
        held = []
        end = time.monotonic()+timeout
        try:
            while True:
                item = self.raw(end)
                if item.get("id") == ident and "method" not in item:
                    if "error" in item:
                        raise ValueError("Native RPC " + method + ": " +
                            str(item["error"].get("message", "failed"))[:600])
                    return item["result"]
                held.append(item)
        finally:
            self.inbox.extend(held)

    def close(self):
        self.selector.close()
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
        for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
            pipe.close()


def native_input(payload):
    result = []
    for message in payload["input"]:
        if message.get("role") != "user":
            raise ValueError("Only explicit user observation input is supported")
        for item in message["content"]:
            if item["type"] == "input_text":
                result.append(dict(type="text", text=item["text"]))
            elif item["type"] == "input_image":
                result.append(dict(type="image", url=item["image_url"],
                    detail=item.get("detail", "high")))
            else:
                raise ValueError("Unsupported session input item")
    english(result)
    return result


def validate_submission(arguments, definition):
    english(arguments)
    validate_value(arguments, definition["parameters"], definition["name"])
    if definition["name"] == "submit_method":
        validate_source(arguments["source"])


class SessionPlanner:
    def __init__(self, payload, folder, deadline, *, rpc_factory=NativeRpc):
        self.payload, self.folder, self.deadline = payload, Path(folder), deadline
        self.rpc_factory = rpc_factory
        self.folder.mkdir(parents=True, exist_ok=True)
        self.state_path = self.folder / "session.json"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else dict(
            version=1, thread_id=None, turns=[], recoveries=[], events={}, token_usage=None,
            payload_sha256=digest(payload), completed=False)
        if self.state["payload_sha256"] != digest(payload):
            raise ValueError("Cannot resume a session with different planner input")
        if payload.get("model") != MODEL or payload.get("reasoning", {}).get("effort") != EFFORT:
            raise ValueError("Only the pinned Astra/xhigh Pro session is supported")
        english(payload)
        self.definition = payload["tools"][0]
        if len(payload["tools"]) != 1 or payload["tool_choice"] != dict(
                type="function", name=self.definition["name"]):
            raise ValueError("Session planner requires exactly one forced function contract")
        self.rpc = None

    def save(self, status):
        self.state["status"] = status
        self.state["updated_at"] = time.time()
        atomic(self.state_path, self.state)

    def connect(self):
        self.rpc = self.rpc_factory(self.folder, self.deadline)
        account = self.rpc.call("account/read", dict(refreshToken=False))
        if (account.get("account") or {}).get("type") != "chatgpt":
            raise ValueError("Native planner requires ChatGPT login; API-key login refused")
        params = dict(model=MODEL, modelProvider="openai", cwd=str(self.folder.resolve()),
            approvalPolicy="never", sandbox="read-only", config=session_config(),
            baseInstructions=self.payload["instructions"], developerInstructions="")
        if self.state["thread_id"]:
            params.update(threadId=self.state["thread_id"], excludeTurns=True)
            try:
                result = self.rpc.call("thread/resume", params)
            except ValueError as error:
                # Codex materializes a new thread on its first turn, rather
                # than thread/start. Recover a crash in that small empty gap.
                if self.state["turns"] or "no rollout found" not in str(error):
                    raise
                self.state["thread_id"] = None
                params.pop("threadId")
                params.pop("excludeTurns")
        if not self.state["thread_id"]:
            params.update(ephemeral=False, allowProviderModelFallback=False, environments=[],
                dynamicTools=[dict(type="function", name=self.definition["name"],
                    description=self.definition.get("description", "Return the requested result"),
                    inputSchema=self.definition["parameters"], deferLoading=False)])
            result = self.rpc.call("thread/start", params)
        if result.get("model") != MODEL or result.get("modelProvider") != "openai":
            raise ValueError("Native session silently changed the requested model/provider")
        if result.get("reasoningEffort") != EFFORT:
            raise ValueError("Native session reasoning effort mismatch")
        if result.get("instructionSources"):
            raise ValueError("Unexpected instruction files loaded into native planner")
        if self.state["thread_id"] and result["thread"]["id"] != self.state["thread_id"]:
            raise ValueError("Native resume returned a different thread; refusing silent cold restart")
        self.state["thread_id"] = result["thread"]["id"]
        self.state["instruction_sources"] = result.get("instructionSources", [])
        self.save("connected")

    def start_turn(self, continuation=False):
        content = native_input(self.payload) if not continuation else [dict(type="text",
            text="Continue the interrupted request in this same conversation. Submit the complete "
                 "result using " + self.definition["name"] + ". Keep the original task and contract.")]
        result = self.rpc.call("turn/start", dict(threadId=self.state["thread_id"],
            input=content, model=MODEL, effort=EFFORT, summary="none", environments=[]))
        ident = result["turn"]["id"]
        self.state["turns"].append(dict(id=ident, continuation=continuation))
        self.save("continuing" if continuation else "generating")
        return ident

    def envelope(self):
        call = self.state["submission"]
        return dict(object="response", id=call["callId"], status="completed", model=MODEL,
            output=[dict(type="function_call", name=call["tool"], call_id=call["callId"],
                arguments=json.dumps(call["arguments"], ensure_ascii=True))],
            usage=self.state.get("usage"), transport=dict(kind="codex_app_server",
                thread_id=self.state["thread_id"], turn_ids=[x["id"] for x in self.state["turns"]],
                envelope_source="validated native dynamic-tool call; not a raw Responses response"))

    def run(self):
        if self.state.get("completed"):
            validate_submission(self.state["submission"]["arguments"], self.definition)
            return self.envelope(), self.state
        if self.state.get("submission"):
            # A durable, complete dynamic-tool request is already an output.
            # Never regenerate it merely because the subsequent end-of-turn
            # acknowledgment was lost. No partial stream is accepted here.
            validate_submission(self.state["submission"]["arguments"], self.definition)
            self.state.update(completed=True, usage=None,
                completion_basis="validated submission recovered; final usage unavailable")
            self.save("completed")
            return self.envelope(), self.state
        restarts = 0
        try:
            while time.monotonic() < self.deadline:
                try:
                    if self.rpc is None:
                        self.connect()
                        self.start_turn(bool(self.state["turns"]))
                    item = self.rpc.next()
                except RpcDisconnected:
                    if self.state.get("submission"):
                        validate_submission(self.state["submission"]["arguments"], self.definition)
                        self.state.update(completed=True, usage=None,
                            completion_basis="validated submission before RPC EOF; final usage unavailable")
                        self.save("completed")
                        return self.envelope(), self.state
                    if restarts >= 2:
                        raise
                    restarts += 1
                    self.state["recoveries"].append(dict(kind="rpc_reconnect", at=time.time()))
                    self.save("reconnecting")
                    if self.rpc is not None:
                        self.rpc.close()
                    self.rpc = None
                    continue
                method = item.get("method", "")
                params = item.get("params", {})
                if params.get("threadId") not in (None, self.state["thread_id"]):
                    continue
                self.state["events"][method] = self.state["events"].get(method, 0)+1
                if method == "item/tool/call":
                    if params.get("threadId") != self.state["thread_id"] or params.get("tool") != self.definition["name"]:
                        raise ValueError("Unexpected native dynamic tool request")
                    try:
                        validate_submission(params["arguments"], self.definition)
                    except (ValueError, SyntaxError) as error:
                        failures = self.state.setdefault("invalid_submissions", [])
                        failures.append(dict(call_id=params["callId"], turn_id=params["turnId"],
                            arguments=params["arguments"], error=str(error)[:600]))
                        self.save("correcting_invalid_submission")
                        if len(failures) >= 3:
                            raise ValueError("Native submission validation repair budget exhausted") from error
                        feedback = dict(error=str(error)[:600],
                            required_schema=self.definition["parameters"],
                            action="Submit a corrected complete result using the same tool. Keep the original task and include every required field.")
                        english(feedback)
                        self.rpc.send(dict(id=item["id"], result=dict(success=False,
                            contentItems=[dict(type="inputText", text=json.dumps(feedback))])))
                        continue
                    if self.state.get("submission") and self.state["submission"]["arguments"] != params["arguments"]:
                        raise ValueError("Conflicting duplicate native submission")
                    self.state["submission"] = {k: params[k] for k in
                        ("threadId", "turnId", "callId", "tool", "arguments")}
                    self.save("submitted")
                    self.rpc.send(dict(id=item["id"], result=dict(success=True,
                        contentItems=[dict(type="inputText", text="Result accepted. End this turn.")])))
                elif method == "thread/tokenUsage/updated":
                    self.state["token_usage"] = params.get("tokenUsage")
                elif method == "error":
                    error = params.get("error", {})
                    self.state["recoveries"].append(dict(kind="native_stream_error",
                        will_retry=params.get("willRetry"), error=error, at=time.time()))
                elif method == "turn/completed":
                    turn = params["turn"]
                    if turn["id"] != self.state["turns"][-1]["id"]:
                        continue
                    if turn["status"] == "completed" and self.state.get("submission"):
                        total = (self.state.get("token_usage") or {}).get("total", {})
                        if all(type(total.get(k)) is int for k in ("inputTokens", "outputTokens")):
                            self.state["usage"] = dict(input_tokens=total["inputTokens"],
                                output_tokens=total["outputTokens"],
                                output_tokens_details=dict(reasoning_tokens=total.get("reasoningOutputTokens")))
                        self.state["completed"] = True
                        self.save("completed")
                        return self.envelope(), self.state
                    if len(self.state["turns"]) >= 3:
                        raise RuntimeError("Native planner exhausted automatic same-thread continuations")
                    error = turn.get("error") or {}
                    code = json.dumps(error.get("codexErrorInfo", "")).lower()
                    overloaded = "serveroverloaded" in code
                    if turn["status"] == "failed" and not any(x in code for x in
                            ("stream", "connection", "http", "internalserver", "serveroverloaded")):
                        raise RuntimeError("Non-transport native turn failure: " + str(error)[:600])
                    delay = (15, 45)[min(len(self.state["turns"])-1, 1)] if overloaded else 0
                    if time.monotonic()+delay >= self.deadline:
                        raise TimeoutError("No logical request budget remains for capacity recovery")
                    self.state["recoveries"].append(dict(kind="same_thread_continue",
                        error=error, retry_delay_s=delay))
                    self.save("capacity_backoff" if overloaded else "continuing")
                    if delay:
                        time.sleep(delay)
                    self.start_turn(True)
                elif "id" in item and method:
                    # No shell, filesystem, connector, approval or other tool is admitted.
                    self.rpc.send(dict(id=item["id"], error=dict(code=-32601,
                        message="Only the declared planner submission tool is supported.")))
                    raise ValueError("Unexpected native client request: " + method)
                if time.time()-self.state.get("updated_at", 0) >= 1:
                    self.save(self.state.get("status", "generating"))
            raise TimeoutError("Native planner logical request deadline exceeded")
        except Exception:
            self.save("failed")
            raise
        finally:
            if self.rpc is not None:
                self.rpc.close()
            self.save(self.state.get("status", "failed"))

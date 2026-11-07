"""Unmodified HexaShell runtime plus local Pro and host-side judgment adapters."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

from judgments import Decisions, Evidence, JudgmentServiceError, ascii_wire, plain

PIN = "e0190ddb757955131578e9f9071f4ee8e7113f7a"


def load_upstream(root):
    root = Path(root).resolve()
    rev = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if rev != PIN:
        raise ValueError(f"HexaShell revision {rev} differs from the audited pin {PIN}")
    dirty = subprocess.check_output(["git", "-C", str(root), "diff", "--name-only", "HEAD"], text=True).strip()
    if dirty:
        raise ValueError("Upstream tracked files have modifications: " + dirty)
    sys.path.insert(0, str(root))
    import hexashell.kernel.host as kernel
    # The upstream worker accepts only a proxy inside hexashell. Extend its
    # package search path before sandbox confinement; do not edit upstream files.
    extension = str(Path(__file__).resolve().parent)
    kernel.BOOT = ("import sys; sys.path.insert(0, sys.argv[3]); import hexashell; "
                   f"hexashell.__path__.append({extension!r}); "
                   "from hexashell.kernel.worker import main; main(sys.argv[1:])")
    return root


class Pro:
    """Use only the existing ChatGPT-authenticated native-session bridge."""
    def __init__(self, url, output, timeout=1800):
        from run_gpt_jev_program import post
        if not url.startswith("http://127.0.0.1:"):
            raise ValueError("Pro bridge must be a loopback SSH forward")
        self.url, self.output, self.timeout = url.rstrip("/"), Path(output), timeout
        self.post = post
        self.calls = []

    def submit(self, name, schema, instructions, content, path=None):
        path = Path(path) if path is not None else self.output / f"pro-{len(self.calls):03d}"
        request = ascii_wire(dict(model="gpt-6-astra", reasoning=dict(effort="xhigh", summary="none"),
            instructions=instructions, input=[dict(role="user", content=content)],
            tools=[dict(type="function", name=name, description="Return the requested complete result",
                        parameters=schema, strict=True)],
            tool_choice=dict(type="function", name=name), parallel_tool_calls=False, store=False))
        t0 = time.monotonic()
        self.calls.append(dict(name=name, path=str(path), status="requested"))
        try:
            response = self.post(self.url + "/responses", request, path, timeout=self.timeout)
            calls = [x for x in response.get("output", []) if x.get("type") == "function_call"]
            if len(calls) != 1 or calls[0].get("name") != name or response.get("model") != "gpt-6-astra":
                raise ValueError("Native Pro returned an unexpected function/model")
            value = json.loads(calls[0]["arguments"])
            self.calls[-1].update(status="completed", usage=response.get("usage"),
                transport=response.get("transport"), seconds=time.monotonic()-t0)
            return value, response
        except Exception as exc:
            self.calls[-1].update(status="failed", error=type(exc).__name__ + ": " + str(exc)[:800],
                                 seconds=time.monotonic()-t0, usage_unknown=True)
            raise
        finally:
            (self.output / "pro-accounting.json").write_text(json.dumps(self.calls, indent=2)+"\n")


POLICY_SCHEMA = dict(type="object", properties=dict(
    action=dict(type="string", enum=["python", "finish"]),
    code=dict(type="string", maxLength=50000),
    status=dict(type="string", enum=["continue", "no_budget", "stuck", "keep_partial"]),
    summary=dict(type="string", maxLength=2000)),
    required=["action", "code", "status", "summary"], additionalProperties=False)

COOPERATION = """
Additional public robot API:
robot.decide(question, options, context=None) -> dict with choice, backend,
decision_id, evidence_step. options maps English branch identifiers to their
descriptions and must include unknown. This invokes the configured local
judgment backend; it never moves the robot or changes your program.
robot.evidence() returns the host-recorded evidence available to that backend.

Keep exact geometry, feasibility checks, numerical thresholds and routine phase
transitions in Python. Do not ask a model to approve a condition Python already
determines. Use the decision model to choose among alternative executable recovery
or observation methods when execution history admits different useful responses.

robot.recover(methods, observe=refresh, resolved=recovery_goal_met,
              context={...}, max_attempts=3, rule_selector=None) -> dict
Register 2..10 methods BEFORE selection. Each entry is
name: {"description": English applicability and expected effect,
       "eligible": callable(obs)->bool, "run": callable(obs), "max_uses": 1}.
observe() refreshes public measurements and returns an observation object;
resolved(obs) and eligible(obs) are pure Python bool predicates, without motion.
resolved means the local recovery goal, never native task success. run(obs)
executes one bounded method with numerical guards and returns; it must not hide
another planner or decision call. Describe missing prerequisites honestly.
Use distinct alternatives such as reobservation, changed approach, or reacquisition
only when those methods can actually be implemented from current public geometry.
Do not invent task-independent motions or forcibly create unsafe alternatives.
The helper calls the configured selector, dispatches its choice immediately,
refreshes measurements, and selects again in the SAME cell without a GPT turn.
It rechecks eligibility, limits attempts (1..6) and per-method uses (1..3), and
returns on resolved, unknown, unavailable methods, changed guard or exhausted
budget. Service errors and terminal exceptions propagate without replay. A
method that partially moved and then failed must never be silently retried.
Inspect the returned reason; resume the task only after the local goal is met.
Do not repeatedly restart recovery loops after exhaustion; return to GPT.
The optional rule_selector(evidence, options, context)->name is ONLY for an
explicit rule-control experiment; leave it None in normal model-selected runs.
Decisions have a separate finite budget. The helper records selection and actual
dispatch separately. Prefer reusable parameterized helper definitions and learned
method applicability over scene constants. Never put your final diagnosis into
context as if it were sensor evidence. Unknown must remain a valid choice.
The host independently supplies recorded measurements, robot feedback and
temporal differences. Re-measure the target before and after relevant motion
to make retention/progress observable. A close command, holding heuristic or
one old measurement does not establish that the intended object is retained.
Put goals, target labels and candidate-plan descriptions in context; do not put
your own final state verdict there. The decision backend cannot see images.
Use unknown to obtain another observation or return to the planner, rather than
repeating identical questions on unchanged evidence. Do not ask it to calculate
exact geometry: compute numeric deltas in code. Standard motion and geometry
tools execute directly; no per-axis model call is required. A gripper cannot
certify task completion; only the environment can end the task successfully.
"""


class ProGateway:
    def __init__(self, pro, log):
        self.pro, self.log = pro, log
        self.lost_s = 0.

    def settings(self):
        return dict(model="gpt-6-astra", reasoning_effort="xhigh", auth="local ChatGPT",
                    transport="native-session", policy_contract="submit_policy -> one Python cell or finish")

    def close(self):
        pass

    def ask(self, messages, tools, *, deadline, stop):
        from hexashell.runtime.llm import GatewayError, Reply
        if stop():
            raise GatewayError("Episode ended", "stopped")
        if time.monotonic() >= deadline:
            raise GatewayError("Episode deadline", "time")
        instructions = messages[0]["content"] + COOPERATION + (
            "\nCall submit_policy exactly once. action=python submits code to the persistent "
            "robot session; use status=continue. action=finish ends the episode; code must "
            "then be empty and status must be no_budget, stuck or keep_partial. The transcript "
            "below contains actual prior Python cells and their results, not additional tools. "
            "All code, questions and prose must be English ASCII.")
        content = []
        for message in messages[1:]:
            header = {k: v for k, v in message.items() if k != "content"}
            content.append(dict(type="input_text", text="Transcript message: " + json.dumps(header)))
            body = message.get("content")
            if isinstance(body, list):
                for item in body:
                    if item.get("type") == "image_url":
                        content.append(dict(type="input_image", image_url=item["image_url"]["url"], detail="high"))
                    elif item.get("type") == "text":
                        content.append(dict(type="input_text", text=item["text"]))
                    else:
                        raise ValueError("Unsupported upstream conversation item")
            elif body:
                content.append(dict(type="input_text", text=str(body)))
        t0 = time.monotonic()
        try:
            value, raw = self.pro.submit("submit_policy", POLICY_SCHEMA, instructions, content)
            if value["action"] == "python":
                if not value["code"].strip() or value["status"] != "continue":
                    raise ValueError("Python policy needs code and continue status")
                name, arguments = "python", dict(code=value["code"])
            else:
                if value["code"] or value["status"] == "continue":
                    raise ValueError("Invalid finish submission")
                name, arguments = "finish", dict(status=value["status"], summary=value["summary"])
            usage = raw.get("usage") or {}
            mapped = dict(prompt=usage.get("input_tokens", 0), completion=usage.get("output_tokens", 0),
                          cached=(usage.get("input_tokens_details") or {}).get("cached_tokens", 0), reasoning=0)
            return Reply(text=value["summary"], calls=[dict(id=uuid.uuid4().hex, type="function",
                function=dict(name=name, arguments=json.dumps(arguments)))], finish_reason="tool_calls",
                usage=mapped, seconds=time.monotonic()-t0)
        except Exception as exc:
            self.log(dict(kind="native_pro_failure", error=str(exc)[:1000]))
            raise GatewayError(str(exc), "failing") from exc


def run_episode(args, memory_text=""):
    load_upstream(args.upstream)
    from hexashell.benches.libero.session import LiberoSession
    from hexashell.kernel.host import CallFailed, Kernel, Stop
    from hexashell.runtime import card as cards
    from hexashell.runtime.conversation import Conversation
    from hexashell.runtime.episode import Episode, Settings

    class Session(LiberoSession):
        proxy = "hexashell.jev_proxy"

        def __init__(self):
            super().__init__(dict(task_name=args.task, eval_seed=args.seed), python=str(args.sim_python),
                             env_file=str(args.sim_env), egl_device=args.gpu)
            self.evidence_log = Evidence()
            self.decisions = None
            self.infrastructure_failure = None

        def snapshot(self):
            return self.evidence_log.snapshot(step=self.step, instruction=self.instruction,
                proprio=dict(self.host.proprio, width_heuristic_holding=self.host.holding))

        def dispatch(self, name, a, kw):
            if name == "recovery_event":
                if self.over:
                    raise Stop(self.over_reason())
                payload = ascii_wire(plain(a[0]))
                if (payload.get("event") not in ("start", "selected", "dispatch", "observed", "finish")
                        or len(json.dumps(payload)) > 16000):
                    raise CallFailed("RobotError", "Invalid recovery event")
                self.rec.event(dict(kind="recovery", step=self.step, payload=payload,
                                    source="sandbox helper; dispatch records entry, not physical completion"))
                return None
            if name in ("evidence", "decide"):
                if self.over:
                    raise Stop(self.over_reason())
                if name == "evidence":
                    return self.snapshot()
                try:
                    receipt = self.decisions.choose(self.snapshot(), *a, **kw)
                    self.rec.event(dict(kind="local_judgment", **receipt))
                    return receipt
                except JudgmentServiceError as exc:
                    self.infrastructure_failure = "local_judgment_service: " + str(exc)[:800]
                    self.errors.append(self.infrastructure_failure)
                    self.finished = True
                    self.rec.event(dict(kind="local_judgment_service_failure", error=self.infrastructure_failure))
                    raise Stop("Judgment service failed; episode stopped without executing a branch") from exc
                except Exception as exc:
                    self.rec.event(dict(kind="local_judgment_error", error=str(exc)[:1000]))
                    raise CallFailed("RobotError", "Local judgment failed; no branch was executed: " + str(exc)[:800]) from exc
            try:
                result = super().dispatch(name, a, kw)
            except Exception as exc:
                if self.host is not None:
                    self.evidence_log.add(name, None, step=self.step, proprio=self.host.proprio, error=exc)
                message = str(exc)
                if "SAM3" in message and any(marker in message for marker in (
                        "CUDA error:", "CUDA out of memory", "doesn't have valid Grid license")):
                    self.infrastructure_failure = "perception_service: " + message[:800]
                    self.errors.append(self.infrastructure_failure)
                    self.finished = True
                    self.rec.event(dict(kind="perception_service_failure", error=self.infrastructure_failure))
                    raise Stop("Perception infrastructure failed; no fallback policy admitted") from exc
                raise
            self.evidence_log.add(name, result, step=self.step, proprio=self.host.proprio)
            return result

        def frames(self):
            return {}  # retain requested observation evidence, not per-motion media

        def report(self, finish):
            return dict(super().report(finish), infrastructure_failure=self.infrastructure_failure,
                local_judgments=dict(backend=args.judgment_backend,
                    attempted=self.decisions.count if self.decisions else 0))

    class NativeEpisode(Episode):
        def _setup(self):
            session, s = self.session, self.s
            self.rec.write_json("implementation.json", dict(upstream_commit=PIN,
                recovery_protocol="method-selection-v1",
                judgment_backend=args.judgment_backend, phase=args.phase, memory_sha256=hashlib.sha256(
                    memory_text.encode()).hexdigest(), native_scoring=True, generic_motion="upstream",
                integration_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in Path(__file__).parent.glob("*.py")}))
            session.open(s, self.rec, self._attach)
            if not session.perception:
                raise RuntimeError("SAM3 perception is required for this implementation test")
            self.t_agent = time.monotonic()
            self.open_s = round(self.t_agent-self.t0, 1)
            self.deadline = self.t_agent + session.deadline_budgets*s.budget_s
            self.tools = session.tools()
            self.conv = Conversation(cards.system_prompt(session.prompt_folder()), images_max=s.images_max,
                images_low=s.images_low, bytes_max=s.images_bytes_max, quality=s.jpeg_quality)
            self.pro = Pro(args.bridge, self.rec.dir, timeout=args.request_timeout)
            session.decisions = Decisions(args.judgment_backend, args.bridge, self.rec.dir,
                pro_submit=self.pro.submit, post=self.pro.post, max_calls=args.max_decisions)
            self.gateway = ProGateway(self.pro, self.rec.event)
            self.kernel = Kernel(self.rec.workspace, session.dispatch, cpu_s=s.cell_cpu_s,
                idle_s=s.cell_idle_s, total_s=s.cell_total_s, proxy=session.proxy, log=self.rec.event)
            self.kernel.start()
            text, self.used = session.card(s)
            if memory_text:
                text += "\nFrozen Playground knowledge (read-only):\n" + memory_text
            text += f"\nYou have {s.max_turns} planner replies and {args.max_decisions} local judgments.\n"
            pictures = [self._keep(self.conv.picture(image, f"{cam} at start", pinned=True, kind=f"start_{cam}"))
                        for cam, image in session.start_pictures()]
            self.conv.user(text, pictures)
            self.rec.write_text("prompt.md", self.conv.messages[0]["content"] + COOPERATION + "\n" + text)
            self.rec.event(dict(kind="start", settings=self._settings_record(), perception=session.perception))

    settings = Settings(model="gpt-6-astra", reasoning_effort="xhigh", skills=False,
        max_turns=args.max_turns, budget_s=args.budget_seconds, images_max=20, images_low=14,
        sam3_url=args.sam3_url, cell_total_s=args.budget_seconds,
        cell_idle_s=max(360, args.request_timeout+30))
    session = Session()
    episode = NativeEpisode(session, settings, Path(args.out))
    episode.run()
    path = episode.rec.dir
    report = dict(result=str(path / "result.json"), phase=args.phase,
        judgment_backend=args.judgment_backend, local_judgments=session.decisions.count if session.decisions else 0)
    (path / "cooperation.json").write_text(json.dumps(report, indent=2)+"\n")
    return path

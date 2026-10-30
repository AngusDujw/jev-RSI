"""Task-independent, evidence-triggered staged GPT/Jev orchestration.

Only public observations and acknowledged execution enter planner callbacks.
This module never selects robot targets, edits task code or reads native scores.
"""
from __future__ import annotations

import hashlib
import json
import time

from gpt_jev_contract import english
from gpt_jev_program_worker import validate_source
from gpt_jev_review_contract import validate_value


def obj(properties):
    return dict(type="object", properties=properties, required=list(properties), additionalProperties=False)


def text(limit=1600):
    return dict(type="string", minLength=1, maxLength=limit)


def strings(limit=8):
    return dict(type="array", items=text(), maxItems=limit)


STAGE_SCHEMA = obj(dict(id=text(40), objective=text(), entry_evidence=text(),
    success_evidence=text(), handoff_requirements=text(), replan_conditions=text()))
PLAN_SCHEMA = obj(dict(explanation=text(), goal_evidence=text(),
    stages=dict(type="array", items=STAGE_SCHEMA, minItems=1, maxItems=8)))
DECISION_SCHEMA = obj(dict(action=dict(type="string", enum=["continue", "advance", "revise", "replan", "stop"]),
    stage_satisfied=dict(type="string", enum=["yes", "no", "unknown"]),
    task_satisfied=dict(type="string", enum=["yes", "no", "unknown"]),
    plan_valid=dict(type="string", enum=["yes", "no", "unknown"]),
    recovery_available=dict(type="string", enum=["yes", "no", "unknown"]),
    reason=text(), evidence=strings(), invalidated_assumptions=strings()))
KINDS = dict(stage_plan=("submit_stage_plan", PLAN_SCHEMA, "gpt_jev_stage_plan_v1.txt"),
             stage_supervise=("submit_stage_decision", DECISION_SCHEMA, "gpt_jev_stage_supervisor_v1.txt"))
HARD_LIMITS = {"gpt_budget", "jev_budget", "native_step_budget", "wall_budget"}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


class StageYield(RuntimeError):
    def __init__(self, event):
        self.event = event
        super().__init__(event["trigger"])


class StageWatchdog:
    """Bound a running worker slice; never turn missing evidence into motion."""
    def __init__(self, state, controls=24, steps=72, rpcs=180, silence=90):
        self.start = state
        self.controls, self.steps, self.rpcs, self.silence = controls, steps, rpcs, silence
        self.rpc_count = self.stalls = self.no_progress = self.measurement_failures = 0
        self.pending = None
        self.target = self.error = None
        self.last_rpc = time.monotonic()
        self.measurements = set()
        self.on_slice = None
        self.suspended_decision = None

    def event(self, trigger, **detail):
        if self.pending is None:
            self.pending = dict(trigger=trigger, **detail)

    def before_control(self, state):
        if state["budgets"]["gpt_remaining"] <= 0:
            self.event("verification_budget_reserve")
        if state["native_steps"]-self.start["native_steps"] >= self.steps or (
                self.start["budgets"]["jev_remaining"]-state["budgets"]["jev_remaining"] >= self.controls):
            self.event("control_slice_limit")
        if self.pending:
            if self.pending["trigger"] == "control_slice_limit" and self.on_slice is not None:
                if self.on_slice(self, state):
                    self.start = state
                    self.pending = None
                    self.rpc_count = 0
                    self.last_rpc = time.monotonic()
                    return
            raise StageYield(self.pending)

    def after_control(self, receipt, requested_gripper, state, quaternion=None):
        self.stalls = self.stalls+1 if receipt["status"] == "stalled" else 0
        target = (receipt["target_tcp"], quaternion)
        error = receipt["position_error_m"]
        rotation = receipt["rotation_error_rad"]
        if target == self.target and self.error is not None and (
                self.error[0]-error < .0005 and self.error[1]-rotation < .005):
            self.no_progress += 1
        else:
            self.no_progress = 0
        self.target, self.error = target, (error, rotation)
        if self.stalls >= 2:
            self.event("repeated_stall", consecutive=self.stalls)
        elif self.no_progress >= 3 and (error > .012 or rotation > .10):
            self.event("no_pose_progress", position_error_m=error, rotation_error_rad=rotation)
        elif requested_gripper != "keep" and state["last_gripper_command"] != requested_gripper:
            self.event("gripper_command_mismatch", requested=requested_gripper,
                       acknowledged=state["last_gripper_command"])

    def before_rpc(self):
        self.rpc_count += 1
        if self.rpc_count > self.rpcs:
            self.event("rpc_slice_limit")
        if self.pending:
            raise StageYield(self.pending)

    def after_rpc(self, message, response, frame):
        self.last_rpc = time.monotonic()  # Model/network waiting is not worker silence.
        name = message["method"]
        if name in ("point", "cloud", "plane_point", "track_init", "track_update", "review"):
            result = response.get("result", {})
            unknown = "error" in response or result.get("status") == "unknown" or bool(result.get("measurement_errors"))
            self.measurement_failures = self.measurement_failures+1 if unknown else 0
            if name == "review":
                selected = dict(points=sorted((x["camera"], x["pixel"]) for x in result.get("points", {}).values()),
                    regions=sorted((x["camera"], x["box"], x["stride"]) for x in result.get("regions", {}).values()))
                if selected["points"] or selected["regions"]:
                    self.measurements.add(fingerprint(dict(method=name, frame=frame, selected=selected)))
            elif not unknown:
                self.measurements.add(fingerprint(dict(method=name, args=message["args"], kwargs=message["kwargs"], frame=frame)))
            if self.measurement_failures >= 2:
                self.event("repeated_measurement_failure")
        elif "error" in response:
            self.event("api_contract_error", error=response["error"])

    def waiting(self):
        if time.monotonic()-self.last_rpc > self.silence:
            self.event("worker_silent")
            raise StageYield(self.pending)


def budgeted_plan_schema(remaining_calls):
    """remaining_calls excludes the plan request itself; this is a lower bound."""
    maximum = min(8, int(remaining_calls) // 2)
    if maximum < 1:
        raise RuntimeError("gpt_budget")
    schema = json.loads(json.dumps(PLAN_SCHEMA))
    schema["properties"]["stages"]["maxItems"] = maximum
    return schema


def validate_plan(plan, remaining_calls=None):
    english(plan)
    schema = PLAN_SCHEMA if remaining_calls is None else budgeted_plan_schema(remaining_calls)
    validate_value(plan, schema, "submit_stage_plan")
    ids = [s["id"] for s in plan["stages"]]
    if len(set(ids)) != len(ids) or any(not x.isascii() or not all(c.isalnum() or c in "_.-" for c in x) for x in ids):
        raise ValueError("Stage IDs must be unique ASCII identifiers")


def stage_outcome(value):
    """Legacy incomplete returns also reach supervision, rather than fail shut."""
    english(value)
    json.dumps(value, allow_nan=False)
    if not isinstance(value, dict):
        raise ValueError("Stage outcome must be an object")
    if value.get("completion_proposed", False) is not False:
        raise ValueError("A stage method cannot propose whole-task completion")
    status = value.get("stage_status", "blocked")
    if status not in ("stage_complete", "blocked", "needs_replan", "yield", "abort"):
        raise ValueError("Unknown stage_status")
    if len(json.dumps(value.get("handoff", {})).encode()) > 16384:
        raise ValueError("Stage handoff exceeds 16384 bytes")
    return dict(value, stage_status=status)


def run_stages(plan_call, method_call, supervise, execute, state, persist,
               *, max_updates=12, max_replans=2, max_revisions=3,
               controls=24, steps=72):
    """Callbacks isolate model I/O and physics for real-host and replay checks."""
    journal = dict(version=1, plans=[], events=[], completed=[], current_stage=None)
    persist(journal)
    outcome = method = None
    cursor = revisions = replans = no_new_evidence = 0
    prior_signature = None
    def obtain_plan(context):
        for _ in range(2):
            remaining = state()["budgets"]["gpt_remaining"] - 1
            schema = budgeted_plan_schema(remaining)
            context = dict(context, planning_budget=dict(
                calls_after_plan=remaining,
                maximum_stages=schema["properties"]["stages"]["maxItems"],
                minimum_calls_per_stage=2,
                scope="One method and one supervisor per stage are mandatory; observations and repairs cost extra. Reserve room for them."))
            candidate = plan_call(context)
            try:
                validate_plan(candidate, state()["budgets"]["gpt_remaining"])
                return candidate
            except ValueError as error:
                journal.setdefault("invalid_plans", []).append(dict(proposal=candidate, error=str(error)))
                persist(journal)
                context = dict(context, plan_contract_error=str(error), rejected_plan=candidate)
        raise RuntimeError("stage_plan_contract_budget")

    plan = obtain_plan(dict(trigger="initial_plan", completed=[], current_state=state()))
    journal["plans"].append(plan)

    def finish(reason, proposed=False):
        journal["termination"] = reason
        persist(journal)
        return dict(completion_proposed=proposed, evidence=journal["events"],
                    stage_history=journal["completed"], hierarchical_termination=reason)

    for update in range(max_updates):
        if len(journal["events"]) >= max_updates:
            return finish("stage_update_budget")
        if state()["budgets"]["gpt_remaining"] < 2:
            return finish("gpt_budget")
        stage = plan["stages"][cursor]
        journal["current_stage"] = dict(plan_revision=len(journal["plans"])-1, index=cursor, definition=stage)
        context = dict(overall_plan=plan, plan_revision=len(journal["plans"])-1, current_stage=stage, stage_index=cursor,
            final_stage=cursor == len(plan["stages"])-1, completed_stage_history=journal["completed"][-8:],
            latest_outcome=outcome, latest_decision=journal["events"][-1:] if journal["events"] else [],
            remaining_stage_updates=max_updates-update, method_revision=revisions,
            slice_limits=dict(jev_calls=controls, policy_steps=steps),
            historical_scope="Completed stages and handoffs are historical; revalidate affected dependencies after changes")
        persist(journal)
        method = method_call(context, method)
        watch = StageWatchdog(state(), controls=controls, steps=steps)
        def review_live_slice(watch, now):
            # Called before the next control, inside the live worker/RPC stack.
            # Continuing does not re-invoke main or replay a partially executed drive.
            if now["budgets"]["gpt_remaining"] < 2 or len(journal["events"]) >= max_updates:
                return False
            suspended = dict(stage_status="yield", completion_proposed=False,
                reason="Control slice ended before the next unexecuted control; worker stack remains live.")
            decision = supervise(dict(context, trigger="control_slice_limit", stage_outcome=suspended,
                public_state=now, watchdog_event=watch.pending, live_continuation_available=True,
                no_new_evidence_count=no_new_evidence))
            english(decision)
            validate_value(decision, DECISION_SCHEMA, "submit_stage_decision")
            permitted = (decision["action"] == "continue" and decision["plan_valid"] == "yes"
                and bool(decision["evidence"]) and not decision["invalidated_assumptions"]
                and now["frame_id"] > watch.start["frame_id"])
            if not permitted:
                watch.suspended_decision = decision
                return False
            event = dict(update=update, stage=stage["id"], plan_revision=len(journal["plans"])-1,
                stage_index=cursor, frame_id=now["frame_id"], trigger="control_slice_limit",
                source_sha256=hashlib.sha256(method["source"].encode()).hexdigest(),
                outcome=suspended, decision=decision, live_continuation=True)
            journal["events"].append(event)
            persist(journal)
            return True
        watch.on_slice = review_live_slice
        trigger = "stage_returned"
        try:
            validate_source(method["source"])
            outcome = stage_outcome(execute(method, watch))
            if watch.pending:
                trigger = watch.pending["trigger"]
        except StageYield as event:
            trigger = event.event["trigger"]
            outcome = dict(stage_status="yield", completion_proposed=False, evidence=event.event)
        except (RuntimeError, ValueError, SyntaxError, KeyError, TypeError) as error:
            if str(error) in HARD_LIMITS:
                return finish(str(error))
            trigger = "execution_error"
            outcome = dict(stage_status="blocked", completion_proposed=False, error=str(error)[:1400])
        now = state()
        signature = fingerprint(dict(frame=now["frame_id"], stage=stage,
            measurements=sorted(watch.measurements)))
        no_new_evidence = no_new_evidence+1 if signature == prior_signature else 0
        prior_signature = signature
        if no_new_evidence >= 2:
            trigger = "no_new_evidence"
        if now["budgets"]["gpt_remaining"] <= 0:
            return finish("gpt_budget")
        if len(journal["events"]) >= max_updates:
            return finish("stage_update_budget")
        decision = watch.suspended_decision or supervise(dict(context, trigger=trigger, stage_outcome=outcome,
            public_state=now, watchdog_event=watch.pending,
            no_new_evidence_count=no_new_evidence, live_continuation_available=False))
        english(decision)
        validate_value(decision, DECISION_SCHEMA, "submit_stage_decision")
        event = dict(update=update, stage=stage["id"], plan_revision=len(journal["plans"])-1,
            stage_index=cursor, frame_id=now["frame_id"], trigger=trigger,
            source_sha256=hashlib.sha256(method["source"].encode()).hexdigest(),
            outcome=outcome, decision=decision)
        journal["events"].append(event)
        persist(journal)
        action = decision["action"]
        if action == "continue":
            action = "revise"
            event["host_override"] = "No eligible live continuation; revise without replaying the terminated worker"
        if decision["plan_valid"] == "no" and action in ("advance", "revise"):
            action = "replan"
            event["host_override"] = "Invalidated overall plan requires plan-level reconsideration"
        if action == "stop" and (decision["recovery_available"] != "no" or not decision["evidence"]):
            action = "revise"
            event["host_override"] = "Unresolved recovery availability is not an evidenced terminal stop"
        if action == "advance" and (outcome["stage_status"] != "stage_complete" or
                decision["stage_satisfied"] != "yes" or not decision["evidence"]):
            action = "revise"
            event["host_override"] = "Advancement requires a stage completion return and fresh affirmative evidence"
        if action == "advance":
            if cursor == len(plan["stages"])-1:
                if decision["task_satisfied"] == "yes":
                    journal["completed"].append(event)
                    return finish("completion_proposed", True)
                action = "replan"
                event["host_override"] = "Final task evidence remains missing"
            else:
                journal["completed"].append(event)
                cursor += 1
                method = outcome = None
                revisions = no_new_evidence = 0
                prior_signature = None
                continue
        if action == "stop":
            return finish("planner_stop")
        if action == "revise":
            revisions += 1
            if revisions <= max_revisions and no_new_evidence < 2:
                continue
            action = "replan"
            event["host_override"] = "Repeated unproductive revisions require a plan-level reconsideration"
        if action == "replan":
            if replans >= max_replans:
                return finish("plan_revision_budget")
            replans += 1
            plan = obtain_plan(dict(trigger=trigger, previous_plan=plan,
                latest_event=event, completed=journal["completed"][-8:], current_state=state(),
                scope="Plan only remaining work from current physical state; prior completion is historical, not a guarantee"))
            journal["plans"].append(plan)
            cursor = revisions = no_new_evidence = 0
            prior_signature = None
            method = None
    return finish("stage_update_budget")

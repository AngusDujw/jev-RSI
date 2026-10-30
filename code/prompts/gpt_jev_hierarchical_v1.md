# Incremental GPT/Jev protocol v1

The hierarchical mode uses an overall plan, just-in-time current-stage methods
and event-triggered supervision. It is separate from legacy whole-method
generation and the older design-then-whole-program mode. No task ID, stage
template, object recipe or trajectory is built into this orchestration.

## Model roles

- Overall planner: submit_stage_plan defines remaining observable subgoals and
  final goal evidence, without future-stage code or numerical commands.
- Stage builder: submit_method returns the existing four-string package, but
  executable source covers only the current stage. interface and jev_protocol
  still describe measurements, features/questions, choices and local recovery.
- Supervisor: submit_stage_decision selects advance, revise, replan or stop
  using actual current images, acknowledged effects and the trigger/outcome.

The exact schemas are in gpt_jev_stage_protocol.py. Separate stage_plan_v1,
stage_method_v1 and stage_supervisor_v1 English prompts implement these roles.
These planner instructions are not appended to Jev inputs. Physical control
retains the existing real-Jev-before-dispatch contract.

## Stage outcomes and handoff

main(api) returns stage_status, reason, evidence, handoff and
completion_proposed=false. Status is stage_complete, blocked, needs_replan,
yield or abort. Legacy incomplete returns are treated as blocked and supervised.
A stage cannot directly propose whole-task completion.

Use api.checkpoint/recall for precise numerical references. Handoff describes
keys, identities, frames, assumptions and invalidation conditions. Revised and
subsequent methods get new Python namespaces, but the physical scene, action
history, tracker bank and episode checkpoints persist. No actions are undone.
Revalidate affected historical references. Local revision receives only the
current-stage source; replanning creates remaining work from current evidence.

## When GPT is called

- Initially: overall plan, then the current-stage method.
- On a stage return: fresh supervision assesses effects or routes recovery.
- On runtime/contract error: supervision receives the actual error and scene.
- Before the next action after two stalls, three non-improving pose updates,
  command mismatch, or two measurement failures. Rotation progress counts.
- At a slice limit (default24 Jev calls/72 policy steps),180 RPCs, or90 seconds
  of worker silence. Model/network waiting is not worker silence.
- Repeated same-frame revisions without different successful measurements
  require plan-level reconsideration rather than indefinite source replay.

These are configurable engineering defaults, not measured optimal thresholds.
Semantic failures such as retention loss remain the method's evidence duty;
the method can return blocked/needs_replan whenever needed.

Advance requires a stage_complete return plus fresh stage_satisfied=yes with
evidence. Final task proposal additionally requires task_satisfied=yes on the
last stage. Stop requires evidence and recovery_available=no. Invalid plans
force replanning. Global budgets still terminate; transport errors remain in
the persistent transport recovery path rather than source-repair policy.

Native observation submissions that exhaust their bounded schema correction
budget are classified separately from connection/authentication failures. They
raise PlannerSubmissionFailure in the worker host and reach stage supervision
with the declared-field errors, so the method/question can be revised. No invalid
reply becomes an observation, no string is truncated, and no schema is relaxed.
Validation feedback includes actual length and allowed limits. This recovery is
still bounded by the global GPT and stage-update budgets.

## Host options

Append the following flags on one line to the existing host invocation:

```text
--hierarchical --max-stage-updates 12 --max-plan-revisions 2 --max-stage-revisions 3 --stage-control-calls 24 --stage-policy-steps 72
```

Global max-gpt/max-jev/max-native-steps remain authoritative. max-repairs is
legacy whole-method only; max-stage-revisions limits local stage revisions.
Explicit unlimited-time removes time cutoffs, not count limits. Archived-method
reuse and design-then-whole-code cannot be combined with hierarchical mode.
Identical same-frame earlier image pairs are not duplicated in this mode.

stage-journal.json retains plans, stage definitions, source hashes, outcomes,
triggers, decisions, host overrides and confirmed stages. The auditor matches
plans/decisions to actual tool returns, validates transitions, source provenance,
dispatch consistency and costs. Native scoring remains terminal and isolated.
Offline transitions and schema checks do not establish physical task success.

When launching the local relay with systemd-run, explicitly pass the existing
proxy environment needed by the provider; a transient unit does not inherit the
interactive shell's proxy settings automatically. The2026-10-30 live trial
received Typesafe HTTP451 without that environment, while the same request
through the configured proxy succeeded. Keep NO_PROXY for loopback. This is a
deployment condition, not a task-prompt change or physical success evidence.

Planning now constrains stage count by remaining calls after the plan request: at most floor(remaining/2), capped at eight. Each stage minimally needs a builder and supervisor. This is only a lower bound: reserve extra observation/repair calls. Actual tool schema and host validation both apply the bound; historical audit schemas remain unchanged.

## Live continuation (2026-10-31)

The supervisor can additionally return continue at a normal control_slice_limit.
The host pauses inside the live control/drive call before the next unexecuted
control, preserving worker locals and the partial drive stack. It requires an
unchanged valid plan, explicit evidence, no invalidated assumptions and actual
frame progress. The acknowledged commands are never reissued by the host.
A continuation consumes a supervision call and stage-update slot, not a new
source-generation call or method revision. Slice quotas reset; stall/progress
counters remain. Errors, stalls, missing measurements and returned programs are
not eligible. A refused continuation passes its existing supervision decision
back to the stage loop, which may revise/replan/stop without another review.
Global call/step/update bounds remain authoritative. Generated methods should
not return yield solely for a normal slice; a returned Python stack cannot be
resumed through this mechanism. The auditor validates live-continuation evidence
and source provenance. Software checks do not establish physical success.

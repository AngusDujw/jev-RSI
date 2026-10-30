---
name: libero-continuation-recovery
description: Resume live bounded programs without replay and reconcile acknowledged state after interrupted operations.
---

# Continuation and interrupted-operation recovery

## Finding A: Resume a live control slice

**Status:** verified, narrowly within this run. Three distinct slice boundaries supported same-stack continuation with continuing progress; this is not evidence of restart safety after process loss.

**Applicability:** A control-slice limit pauses a worker whose live continuation is explicitly available.

**Inputs and frames/units:** Trigger, live-stack availability, program/source identity, last acknowledged phase, frame and native-step counters, actual TCP pose in world meters and xyzw quaternion, gripper command, and fresh scoped review.

**Jev versus program:** The supervisor decides continue versus revise. The live program retains its local state and resumes at the next unexecuted control. Jev continues the existing local residual contract; it does not reconstruct execution history.

**Procedure:** Continue the same stack when progress is acknowledged, geometry remains applicable, and fresh review shows no new failure. A normal slice boundary is neither a stall nor a reason to start the method again. Keep stage success pending until its effect test returns.

**Failure/stopping conditions:** Do not use this rule if the stack is gone, acknowledgements are uncertain, motion is stalled, the scene changed, or an effect contradicts the plan. Reconcile state rather than rerunning entry logic.

**Evidence IDs:** E-JS and E-JA, defined in [the evidence ledger](../lessons/libero-evidence.md). Continue decisions at three boundaries led to the later acquisition result without a method revision at those boundaries. E-D is only a sample and is not treated as a complete replay audit.

## Finding B: Reconcile after a service interruption

**Status:** hypothesis for recovery procedure; no post-502 recovery was observed.

**Applicability:** An RPC or service error interrupts a stage that may already have changed physical state.

**Inputs and frames/units:** Durable intent and acknowledgement records, last full robot state, current observations, method provenance, gripper command, release/withdrawal flags, and reference measurement frames. Positions are world meters; counters are native steps, not elapsed seconds.

**Jev versus program:** The supervisor and program establish which actions were acknowledged and which effects remain uncertain before issuing any new segment. Jev is not an execution-history oracle.

**Procedure:**
1. Persist intent before an operation and actual state/receipt after acknowledgement. Distinguish commanded opening, actual finger separation, observed object release, and withdrawal.
2. After interruption, inspect durable progress and obtain fresh state. If an operation lacks an acknowledgement, treat its physical effect as uncertain rather than absent.
3. Preserve the actual gripper command unless fresh evidence authorizes a change. Do not automatically reopen, reacquire, repeat a lift, or repeat release.
4. Reject fresh-entry methods when their entry conditions no longer hold. Synthesize a continuation from the reconciled phase.
5. Audit geometry provenance too: original measurement frame, validation frame, and attachment-reference frame are distinct.

**Failure/stopping conditions:** Stop for supervision if current state cannot be obtained, acknowledgements cannot be reconciled, or attachment/clearance is unresolved. Resource or service failure must not be relabeled as manipulation success or mechanical failure.

**Evidence IDs:** E-SUM, E-P, E-M2, E-G. Placement progress acknowledged the initial upward move with no opening or withdrawal before the 502 termination. No evidence demonstrates the proposed recovery.

---
name: libero-continuation-recovery
description: Resume live control slices without replay and reconcile actual state before restarting interrupted or returned programs.
---

# Continuation and interrupted-operation recovery

## A. Resume an explicitly live stack

**Status:** verified for same-stack continuation across three episode-0 boundaries and one episode-1 boundary. This does not establish restart safety after process loss.

**Applicability:** A control-slice limit pauses a worker whose live continuation is explicitly available.

**Inputs and frames/units:** Current trigger, stack availability, program identity, acknowledged phase, frame/native-step counters, actual world-meter TCP pose with xyzw quaternion, gripper command and fresh scoped review.

**Jev versus program:** Supervisor chooses continue versus revise. Live program retains local state and resumes its next unexecuted control. Jev continues the existing residual contract, not reconstructed execution history.

Continue when progress is acknowledged, dependencies remain applicable and current review shows no new failure. A normal slice boundary is not a stall. Keep stage success pending until its independent effect test returns.

**Failure/stopping conditions:** Do not apply when the stack is gone, the trigger is a returned blocked stage or API error, acknowledgements are uncertain, or physical evidence changed. Reconcile instead of rerunning entry.

**Evidence IDs:** E-JS, E-JA; N-JS, N-J2. Sampled dispatches are not complete replay audits.

## B. Resume after a returned stage or persistence failure

**Status:** scene-specific. Episode 1 continued from acknowledged offset and descent states without replaying those segments. Its final containment recovery failed before motion.

**Applicability:** No live stack remains, but durable acknowledged progress and current state can be inspected.

**Inputs and frames/units:** Durable intent/acknowledgement records and write provenance; actual pose, aperture and command; measured geometry/reference frames; phase-specific approvals; native steps, not elapsed seconds.

**Jev versus program:** Supervisor/program reconstructs the valid continuation entry and pending evidence. Jev cannot determine history or repair storage.

1. Inspect the current trigger, not a historical error.
2. Reconcile actual state with the last acknowledged phase. Preserve completed approach, offset, descent, closure and lift separately.
3. Refuse fresh-entry logic whose preconditions no longer hold.
4. Reuse a scoped same-frame review only while its physical dependencies and provenance remain applicable.
5. If a write failed, verify whether the old checkpoint remains. Recover from acknowledged feedback only when available, then persist a compact record successfully before relying on it.
6. Preserve the actual gripper command; do not automatically reopen, reclose or repeat a lift.
7. Distinguish command delivery, actual aperture, attachment, release and withdrawal flags. A handoff narrative does not prove any of them.

**Failure/stopping conditions:** Stop for supervision if state or acknowledgements cannot be reconciled, contact/attachment is unresolved, or persistence remains unreliable. Never infer that an unacknowledged operation had no physical effect.

**Evidence IDs:** N-J4 through N-J6, N-P, N-J9, N-J10, N-C; N-M05, N-M06, N-M10. See the bounded-checkpoint skill for the failed final repair.

## C. Service interruption with uncertain physical effect

**Status:** hypothesis for the full recovery procedure; no post-502 recovery was observed.

**Applicability:** RPC/service interruption during a stage that may already have changed physical state.

**Inputs and frames/units:** Intent and receipt records, last full pose, current observations, method provenance, actual gripper state, and distinct measurement/validation/attachment-reference frames; world meters and native-step counts.

**Jev versus program:** Supervisor/program reconciles acknowledged actions and uncertain effects before authorizing any new segment. Jev is not an execution-history oracle.

Persist intent before an operation and actual state after acknowledgement. On interruption, obtain fresh state, preserve uncertainty for missing acknowledgements, and synthesize from the reconciled phase. Do not assume an opening, release or withdrawal occurred merely because it was planned.

**Failure/stopping conditions:** Stop if state, attachment, clearance or acknowledgement cannot be resolved. Infrastructure failure is neither manipulation success nor proof of mechanical infeasibility.

**Evidence IDs:** E-SUM, E-P, E-M2, E-G. Only the preliminary upward placement move was acknowledged before the service termination.

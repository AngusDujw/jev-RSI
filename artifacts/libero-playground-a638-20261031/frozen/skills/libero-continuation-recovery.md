---
name: libero-continuation-recovery
description: Reconcile live suspension, returned stages, exhausted leases and uncertain service effects without replay.
---

# Continuation and recovery

For every finding, **inputs/frames** are current trigger/stack availability, method and acknowledgement provenance, durable intent, actual command/aperture, full world-meter TCP and xyzw pose, measurement/validation frames and native-step counters. **Responsibilities:** supervisor/program chooses the valid entry and resolves history; Jev continues approved residual control and is not an execution-history oracle.

## A. Explicit live continuation

**Status:** verified across three E, one N and two T slice boundaries; not restart safety after process loss.
**Applicability:** Runtime explicitly preserves a live worker stack.

Resume the next unexecuted control when progress is acknowledged and dependencies remain valid. Normal slice boundaries are not stalls; historical errors are not current triggers. Keep success pending until effects are tested.
**Stop:** no live stack, returned blocked stage, API error, changed evidence or uncertain acknowledgement requires reconciliation, not entry replay.
**Evidence IDs:** E-JS, E-JA; N-JS, N-J2; T-JS, T-J1, T-J2. Dispatch samples are not complete replay audits.

## B. Returned-stage reconstruction

**Status:** scene-specific. N resumed offset/descent states; T preserved standoff, exhausted descent and evolving closure. Not every recovery succeeded.
**Applicability:** Stack gone but acknowledged progress and actual state inspectable.

Reconcile approach, offset, descent, each close/keep and lift separately. Refuse fresh-entry logic whose preconditions no longer hold. Use current state/receipt relations, not copied episode frame guards. Reuse same-frame review only with valid dependencies. After failed persistence, inspect what old value remains and durably record the reconciled continuation before relying on it. Preserve actual command; include aperture evolution under keep. Distinguish delivered command, aperture, attachment, release and withdrawal.
**Stop:** unresolved state/contact/acknowledgement or unreliable storage. An unacknowledged operation is not necessarily physically unexecuted.
**Evidence IDs:** N-J4 through N-J6, N-P, N-J9, N-J10, N-C; T-J1 through T-J7, T-P, T-C.

## C. Exhaustion does not diagnose collision

**Status:** scene-specific. One exhausted descent led to an actual-pose closing assessment/delivery, then a margin stop; successful general recovery is unestablished.
**Applicability:** Lease stops short with diminishing progress.
**Additional inputs:** target error/tolerance, acknowledged tail progress and fresh current contact/sweep geometry.

T ended a 36-call descent at about 1.614 mm residual against 0.789 mm tolerance. Journal reports about 0.105 mm motion over the last five deliveries. Cause remains unresolved.

Keep the old target unachieved; do not blindly extend its lease or relax tolerance. A fixed-current-pose action is a distinct candidate, not retrospective success. Independently review unwanted contact/sweep and recompute clearance, overlap, centering and supported hold reserve. Save post-action predicates; pre-close margins or reached pose cannot authorize further closure. A later authored practical tolerance floor based on this residual was not a calibrated controller limit or tested placement rule.
**Stop:** inadequate current evidence/margin/resources; no automatic descent correction or replay.
**Evidence IDs:** T-J2 through T-J4, T-P, T-C, T-M03, T-M08. Tail figures are journal evidence, not supplied dispatch samples.

## D. Service interruption

**Status:** hypothesis for full recovery; no post-502 continuation observed.
**Applicability:** RPC interruption during potentially state-changing work.

Persist intent before dispatch and actual state after acknowledgement. Obtain fresh state after interruption, preserve uncertainty for missing receipts, and resume only from reconciled effects. Planned opening/release/withdrawal is not execution.
**Stop:** unresolved attachment, clearance, state or acknowledgement. Infrastructure failure is neither success nor mechanical infeasibility.
**Evidence IDs:** E-SUM, E-P, E-M2, E-G; only preliminary placement-preparation rise was acknowledged.

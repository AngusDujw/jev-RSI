---
name: libero-bounded-jev-control
description: Bind Jev choices to numerical residual relations and distinguish a full control lease from its final update.
---

# Bounded residual-driven control

## A. Explicit question and execution contract

**Status:** scene-specific. Acknowledged approach, closing and lift controls exercised this design; sampled receipts do not audit every choice or establish superiority over other controllers.

**Applicability:** A runtime exposing current proprioception, host residual relations, discrete Jev choices and bounded drive leases.

**Inputs and frames/units:** Target and current TCP or pad-center positions in world meters; tool-to-world xyzw quaternions; host world rotation-vector residuals in radians; measured tool offsets in tool-frame meters; supported tolerances and native-step/call budgets. Native action-vector magnitudes are not assumed to be meters.

**Jev versus program:** Program selects target, tool point, margins, tolerances, gripper request and lease. Host computes fresh residuals and numerical action. Jev answers six axis questions and one gripper question without calculating geometry or certifying effects.

For every axis a in x, y, z, rx, ry, rz, explicitly read state.processed_features.axes.a.goal_relation:

| Relation | Candidate | Meaning |
| --- | --- | --- |
| decrease | negative | Decrease the named world component |
| within_tolerance | hold | Request no change on that component |
| increase | positive | Increase the named world component |

Rotational choices are world rotation-vector components, not independent Euler-angle goals. Bind the gripper question to state.processed_features.objective.gripper: open, close or keep exactly as requested. Keep preserves the prior command, not an assumed aperture or grasp.

Provide compact features: phase, source/measurement frames, uncertainty, checked local segment, calculated margins, requested command and pending effect. Do not make the direction selector infer these from images.

- Convert pad goals to TCP using the current tool transform; never add tool-frame offsets directly in world coordinates.
- Use finite leases capped by remaining resources, leaving effect-check reserves.
- Derive tolerance from robust geometric slack and documented API precision; do not clamp an infeasible tolerance upward.
- Reached establishes pose feedback and command delivery only. Hold does not guarantee zero drift; close does not establish attachment.
- Checked individual closing deliveries may use a different accepted receipt status than an ordinary pose lease, but only when that distinction is explicit and actual geometry/progress are checked.

**Failure/stopping conditions:** Stop on stall, exhaustion, mismatch, unsupported precision or uncertain acknowledgement. Inspect actual state before another contact action; never blindly repeat a stopped lease.

**Evidence IDs:** E-M1, E-M2, E-D, E-JA; N-M06, N-P, N-D, N-J6.

## B. Measure whole-lease motion from saved endpoints

**Status:** verified for the accounting distinction, repeatedly observed across both episodes.

**Applicability:** A drive call contains multiple acknowledged updates but returns a receipt whose before/after fields cover only the last update.

**Inputs and frames/units:** Full lease-start and lease-end states, final receipt, frame IDs and native-step counts; translations in world meters and rotations as full xyzw poses.

**Jev versus program:** Jev continues the same residual contract. Program saves intent and start state before dispatch, then actual end state and acknowledgement; it computes whole-lease displacement and elapsed native steps.

Do not infer whole motion from the final receipt pair or commanded target. Episode 0's preliminary placement rise was about 34.13 mm across six calls, while its final update rose about 2.31 mm. Episode 1's retention lift rose about 49.26 mm across seven calls, while its final update rose about 1.65 mm.

**Failure/stopping conditions:** Without trustworthy endpoints, do not claim a differential effect or replay the action to recreate a missing record. Reconcile current state and acknowledgements.

**Evidence IDs:** E-P, E-D; N-P, N-A, N-D.

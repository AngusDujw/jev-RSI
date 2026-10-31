---
name: libero-bounded-jev-control
description: Bind Jev to host residuals and account for actual whole-lease motion and persistent gripper commands.
---

# Bounded residual control

For every finding below, **inputs/frames** are actual and target TCP/pad positions in world meters, tool-to-world xyzw poses, tool offsets in tool-frame meters, host world rotation-vector residuals in radians, documented tolerances and call/native-step counters. Native action-vector magnitudes are not assumed to be meters. **Responsibilities:** program owns targets, geometry, limits and effect checks; host supplies fresh residuals/numerical actions; Jev selects directions and the requested gripper command.

## A. Explicit seven-question contract

**Status:** scene-specific; exercised by acknowledged controls, not an audit of every sampled choice or proof of controller superiority.
**Applicability:** APIs exposing host residual relations and bounded discrete control leases.

For each a in x, y, z, rx, ry, rz, explicitly read state.processed_features.axes.a.goal_relation:
- decrease -> negative: decrease that world component.
- within_tolerance -> hold: request no change on that component.
- increase -> positive: increase that world component.

Rotation choices are world rotation-vector components, not independent Euler goals. Bind the seventh question to state.processed_features.objective.gripper: open, close or keep exactly.

Supply compact features: phase, measurement frames, uncertainty, checked segment/margins, requested command and pending effect. Jev must not infer geometry from images. Transform pad offsets with the current tool rotation before converting pad goals to TCP. Derive tolerances from robust slack and supported API precision; never clamp an infeasible tolerance upward. API acceptance does not guarantee convergence at contact. Reserve effect-check resources inside finite leases. Reached proves pose/command delivery, not attachment; hold need not eliminate drift. Distinct contact-receipt semantics require an explicit documented contract and actual progress checks.

**Stop:** stall, exhaustion, mismatch, unsupported tolerance or uncertain acknowledgement; inspect actual state before another contact action, without blind retry.
**Evidence IDs:** E-M1, E-M2, E-D; N-M06, N-P, N-D; T-M01 through T-M08, T-P, T-D.

## B. Whole lease versus final update

**Status:** verified for repeated accounting differences across all three episodes.
**Applicability:** Multi-update drives whose returned before/after receipt covers only the final update.
**Additional inputs:** saved full lease-start/end states and acknowledgement.

Save intent/start before dispatch and actual endpoint afterward. Compute displacement and native steps from those endpoints, not target or final receipt. Historical whole-rise/final-update examples: E about 34.13/2.31 mm; N about 49.26/1.65 mm; T about 99.08/2.49 mm. These are accounting examples, not targets.
**Stop:** missing trustworthy endpoints prevents differential claims; do not replay motion to recreate records.
**Evidence IDs:** E-P, E-D; N-P, N-A, N-D; T-P, T-D.

## C. Keep is not frozen aperture

**Status:** scene-specific direct observation.
**Applicability:** Persistent gripper commands during stationary controls, travel or settling.
**Additional inputs:** command history, actual finger positions/aperture, aperture-dependent own geometry and before/after acknowledgements.

One T keep delivery preserved close while separation decreased from about 68 to 42.5 mm over three native steps; TCP displacement was about 0.14 mm. Account for continuing closure during any physical steps under close. Bound deliveries and refresh affected contact geometry. Do not issue keep merely to obtain another image when its contact effect is unreviewed.
**Stop:** unexpected aperture evolution, failed margins or uncertain delivery. Preserve/reconcile command rather than automatically reopening; stabilization is not retention.
**Evidence IDs:** T-J3, T-J6, T-P, T-RSIDE. Earlier keep progress is represented by journal/handoff evidence, not the overwritten final progress record.

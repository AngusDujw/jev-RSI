---
name: libero-bounded-jev-control
description: Bind Jev choices to explicit numerical residual relations while keeping geometry and effect checks in the program.
---

# Bounded residual-driven control

**Status:** scene-specific. The contract was exercised in acknowledged approach, closing, and lift controls. The sampled receipts do not verify every decision, axis, or alternative controller design.

**Applicability:** A runtime that exposes current proprioception, target residual relations, discrete Jev choices, and bounded drive leases.

**Inputs and frames/units:** Target and measured TCP or pad-center positions in world meters; tool orientation as xyzw quaternions; host rotational residuals in radians using the documented world rotation-vector convention; measured tool offsets in tool-frame meters. Native action-vector magnitudes are not assumed to be meters.

**Jev versus program:**
- The program chooses the tool point, target, margins, tolerances, gripper request, and finite lease budget.
- The host computes fresh residuals and the numerical action from the selected choices.
- Jev answers six axis questions and one gripper question. It neither computes scene geometry nor certifies contact or success.

## Question and state design
For each axis a in x, y, z, rx, ry, rz, explicitly bind the question to state.processed_features.axes.a.goal_relation:

| Relation | Candidate | Meaning |
| --- | --- | --- |
| decrease | negative | Decrease this world coordinate or rotation-vector component |
| within_tolerance | hold | Request no change on this component |
| increase | positive | Increase this world coordinate or rotation-vector component |

Do not reinterpret rx, ry, rz as independently chosen Euler-angle goals. Bind the gripper question to state.processed_features.objective.gripper: open, close, or keep exactly as requested. Keep preserves the current command, not an assumed open or closed state.

Supply compact program features: phase, geometry frame, uncertainty, checked local segment, clearance/overlap margins, requested gripper action, and the effect that still needs verification. Avoid asking the direction selector to infer these facts from images.

## Execution and interpretation
- Use finite call and native-step limits. Cap a lease by remaining resources and leave budget for verification.
- Choose final tolerance from available geometric slack; do not demand precision below the API's supported minimum.
- Record a full state before the lease and after it, as well as the final receipt. A receipt's before/after pair may cover only its last update.
- Convert between pad-center goals and TCP using the current tool transform. Do not add a tool-frame offset directly in world coordinates.
- Reached means pose convergence and checked command delivery only. Hold does not prove zero physical drift; close does not prove attachment.

**Failure/stopping conditions:** Stop on lease exhaustion, stall, mismatched gripper choice, unsupported precision, or missing acknowledgement. Inspect actual state before another contact action. Do not repeat a failed lease blindly or derive whole-lease motion from its final update.

**Evidence IDs:** E-M1, E-M2, E-D, E-JA, E-P, defined in [the evidence ledger](../lessons/libero-evidence.md). The placement upward lease's actual hand rise was about 34.13 mm across six calls, while its final update rose about 2.31 mm. This directly illustrates why lease-start state must be preserved.

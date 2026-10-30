---
name: libero-observable-stages
description: Define observable stage contracts and keep command delivery, retained acquisition and completed placement distinct.
---

# Observable stage contracts

**Status:** scene-specific for the complete decomposition. Acquisition effects were established in two episodes; placement and the complete task contract remain untested.

**Applicability:** Manipulation where reaching, closing or opening can occur without the intended object effect.

**Inputs and frames/units:** Fresh public views; frame-tagged identity, support and disturbance relations; world-meter measurements; full TCP poses with tool-to-world xyzw quaternions; actual gripper state; acknowledged native-step counters and resource limits. Pixels belong to a camera and frame.

**Jev versus program:** Planner/reviewer defines observable relations and scoped clearances. The program chooses subgoals, computes geometry, records execution and tests effects. Jev delivers bounded directions and gripper requests, not identity, attachment, support or completion judgments.

## Contract design
1. Specify entry evidence, physical effect, success evidence, handoff and replan conditions before controls.
2. Keep alignment, contact, closure, retention test, transit, release and final verification distinguishable even when grouped into two physical stages.
3. Acquisition requires current identity, visible finger retention and support separation, plus measured material motion consistent with actual full hand motion. Closed fingers alone do not establish these effects.
4. Placement requires actual opening and hand separation, measured containment, visible interior support rather than rim bridging, and stability after acknowledged physical settling.
5. Advance from the actual acquired state and preserve the actual gripper command. Carry historical shape only with its assumptions and original measurement provenance.
6. Scope every approval: a high approach is not descent clearance; fixed-pose closure approval is not a lift corridor; retention is not an opening fit or transport certificate.
7. Separate incomplete evidence from contradiction. Missing required evidence is blocked; reliable slip, lost support relations or failed effects require replanning; a reviewer stop aborts.
8. Reserve resources for independent effects and outer supervision. Renaming a stage or revising a plan does not reset physical execution or restore budgets.

**Failure/stopping conditions:** Stop on unresolved necessary evidence, exhausted resources, uncertain acknowledgement or contradicted geometry/effects. Replan from actual state, not original entry. Never equate stage completion with task completion.

**Evidence IDs:** E-PLAN, E-J0, E-JA, E-A, E-P, E-RA; N-PLAN, N-J3, N-J5, N-J6, N-J7 through N-J10, N-A. The closed baselines preceded successful differential lifts. Episode 0 stopped during placement preparation; episode 1 stopped before any containment motion.

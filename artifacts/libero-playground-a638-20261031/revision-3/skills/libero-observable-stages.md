---
name: libero-observable-stages
description: Separate command delivery, object effects, disturbance and final task evidence.
---

# Observable stage contracts

**Status:** scene-specific for the complete decomposition. Two earlier acquisition stages passed measured retention tests. Episode 2 supplied lift co-motion and support-separation observations but stopped before numerical attachment acceptance. No placement is established.

**Applicability:** Manipulation where pose arrival, closing or opening can occur without the intended object effect.

**Inputs and frames/units:** Current public views; physical identities and support/disturbance relations; camera/frame-tagged pixels and world-meter measurements; actual TCP poses with tool-to-world xyzw quaternions; aperture, command, acknowledged native steps and resource counters.

**Jev versus program:** Planner/reviewer defines observable relations and local permissions. Program selects subgoals, computes geometry, records execution and checks effects. Jev delivers bounded directions and exact gripper requests, not identity, attachment or completion judgments.

- Define entry, effect, success evidence, handoff and replan conditions before action.
- Keep alignment, contact, closure, retention test, transit, release and verification distinguishable, even inside one stage.
- Acquisition needs corresponding material motion consistent with actual full hand motion, visible finger retention and support separation. Closure alone proves none of these.
- Placement needs actual release, hand separation, measured containment, interior support rather than rim bridging, and stability across acknowledged settling steps.
- Preserve independent predicates: pose delivered, aperture changed, material followed, support separated, destination disturbed, fit pending. One failed conjunct does not make all others false.
- Scope permissions: high approach is not descent; closing is not lift clearance; retention is not opening fit; horizontal transfer approval excludes descent/release.
- Continue from actual state/command. Historical shape retains its original measurement frame and hidden-surface assumptions.
- Missing necessary evidence blocks; reliable contradiction requires replanning; reviewer stop aborts. A compound failure string does not identify every possible cause.
- Merging stages may combine compatible same-frame questions, but cannot establish future effects in advance. Its end-to-end resource benefit remains a hypothesis.

**Failure/stopping conditions:** Stop on unresolved necessary evidence, contradiction, uncertain acknowledgement or insufficient verification resources. A held object and disturbed destination can coexist: preserve the lifted state, reconcile affected target dependencies, and do not repeat acquisition. Partial effects and authored branches are not stage/task completion.

**Evidence IDs:** E-PLAN, E-JA, E-A, E-P; N-PLAN, N-J3, N-J5 through N-J10, N-A; T-PLAN, T-J8, T-P, T-RLIFT, T-M08.

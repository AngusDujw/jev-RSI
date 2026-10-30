---
name: libero-observable-stages
description: Define observable manipulation stage contracts and keep partial success separate from task completion.
---

# Observable stage contracts

**Status:** scene-specific. Acquisition satisfied its contract once; the placement contract remained untested.

**Applicability:** Pick-and-place tasks where reaching a pose, closing fingers, or issuing release can occur without the desired object effect.

**Inputs and frames/units:** Fresh public views, depth measurements in world meters, full hand poses with xyzw quaternions, acknowledged control receipts, native-step counters, and frame-tagged object/support relations. Camera pixels are local to their camera and frame.

**Jev versus program:** The planner and visual reviewer define observable relations and uncertainty. The program selects subgoals, computes geometry, executes bounded segments, and evaluates evidence. Jev delivers discrete control choices for those segments; it does not decide object identity, retention, support, or stage completion.

## Procedure
1. Write each stage's entry evidence, intended physical effect, success evidence, handoff, and replan conditions before choosing controls.
2. An acquisition contract should require current object identity, visible separation from the original support, visible finger retention, and measured object motion consistent with actual hand motion. Closed fingers alone satisfy none of these effects.
3. A placement contract should require acknowledged opening and withdrawal plus fresh containment, interior support rather than rim bridging, and stable object measurements after physical settling.
4. Keep approach alignment, contact, retention testing, transit, release, and final verification distinguishable in checkpoints even when grouped into two larger stages.
5. Advance from the actual acquired state, preserving the actual gripper command. Carry only conditional shape information and frame-tagged measurements. Preliminary rim samples are not an opening fit or a transit certificate.
6. Reserve observation and control budget for effect verification and recovery, not only nominal travel.

**Failure/stopping conditions:** Missing evidence is blocked, not success. Observed slip, support contact inconsistent with the goal, or disturbance requires replanning from the observed state. A review stop aborts. Stage completion must not imply whole-task completion; an outer supervisor still checks the task contract.

**Evidence IDs:** E-PLAN, E-J0, E-JA, E-A, E-P, E-RA, defined in [the evidence ledger](../lessons/libero-evidence.md). The closed-hand baseline still showed table contact; only the later differential lift established acquisition. Placement remained incomplete after the infrastructure interruption.

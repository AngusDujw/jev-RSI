# Collected development observations

Collection only. This file is not loaded into either model.

## 2026-10-19

- Fixed source windows become invalid after an object moves. Recompute current visible pixels or report unknown; never present the original location as the current object.
- An observation-only stage can reward withdrawal without manipulation progress. Use a physical subgoal such as aligning an open finger gap above the source.
- Four OSC steps often achieve only part of a small requested increment. Report achieved motion. Twelve steps improved free-space tracking in the current pilot; this does not certify grasping or clearance.
- A visible surface point is not a hidden object centre or desired grasp pose. The actor must select the useful relationship from current RGB.
- Selecting a source feature does not guarantee a correct axis decision. In one pilot, the actor selected a bottle surface but chose positive Y despite a negative surface-minus-hand Y coordinate. Keep the original answer and inspect the question semantics.
- Nine labels crowded onto a small knob can be unreadable. Test fewer separated labels and a current source-detail crop.
- For placement, compare the held source with the receiver. Gripper-to-receiver alignment alone ignores how the object sits in the hand.
- Visible knob rotation and appliance activation are different observations. An absent visual indicator must remain unknown.

No claim of stable success follows from these observations. Complete native outcomes and fixed-policy replications are still required.

- Coarse overhead alignment and grasp-height alignment are different stages. Requiring fingers already alongside an object before entering descent can produce an all-hold loop. Use the same positioning band in the axis questions and the coarse-stage transition.
- Keep the chosen physical reference part consistent within a stage. A fresh coordinate is still a moving goal if the actor keeps switching between neck and body. Preserve actor intent, never stale scene coordinates.

- Black task parts and black robot parts can merge in colour tracking. Reject current RGB-D points inside public own-robot geometry; unknown is safer than chasing the hand. This does not establish scene clearance.
- A named candidate at a silhouette quantile is not a persistent physical reference. Track the actor-selected image feature with current correspondence/depth checks, and expose loss instead of silently replacing the grasp region.
- A suitable downward finger approach can coexist with a large translation offset. Judge tilt separately from distance; preserve actual task-image judgement for jaw heading and operated-object orientation.

- Matching a visible skin point exactly is not equivalent to centring a narrow part between the fingers. Near-grasp conditions should refer to actual capture geometry; own pad projections can explain that geometry without revealing an object pose.
- After a visible lift, vague requests for more clearance can continue indefinitely. Give the actor observed source motion, distinguish it from measured hand motion, and define the next transport transition explicitly. Neither motion alone certifies a secure grasp.

- A receiver identity window is not a receiver mask. Fixed grid dots may land on walls, the robot or other furniture and produce metre-scale false references. Generate current surface candidates on a plausible RGB component and retain semantic verification.
- A top-down image overlap can trigger closure while the source is still centimetres below the hand. Check a physical capture-height relationship separately; contact proof is not required, but absence of height overlap is real contrary evidence.
- Placement needs the held object body to fit the receiver, not automatic retention of its lift posture. State the body-versus-support relationship separately from translation.

- Name the required part in the visual-selection question itself: a knob fin is not its base, and an upper bottle neck is not its body. A generic source-feature question permits physically wrong but semantically related references.
- Repeated tiny measured motion despite nonzero own commands needs recovery and fresh part identification, not more of the same correction. Own execution gain does not identify contact or an obstacle.
- Release and inspection have a causal order: execute opening, expose the object, then inspect. Requiring the hidden outcome before entering inspection can create another endless gate.

- Stateless requests need their relevant examples every time. Initial-only motion cards do not teach a later independent API call.
- A phase example with the hand/object outside the frame cannot show the intended orientation. Retain an actual final object-support relationship during orientation and use complementary current cameras that cover the whole interaction.

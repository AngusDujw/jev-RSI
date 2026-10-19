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

# RoboDojo joint decisions: candidate lessons from the bounded campaign

```json
{"id":"robodojo-opt30","status":"candidate","tasks":["general_pickup","stack_bowls","fold_clothes","press_by_number","match_and_pick_from_conveyor"],"rules":{},"evidence":["LOGS/robodojo-opt30-analysis.md","LOGS/robodojo-opt30-results.json"]}
```

This file is an offline candidate, not an active runtime memory. Mixed development does not establish a memory gain.

Keep measured surface geometry, historical references, robot waypoints and association predictions separate. A previous grasp verification is history, not a current attachment sensor. A robot-motion prediction may gate CURRENT RGB-D candidates but must never replace their measurements.

Prioritize the carried source during association so a stationary destination cannot consume its observation. When a stationary base is occluded, disclose the reference age and stationary assumption; use active observation or bounded uncertainty rather than asserting a fresh position.

Acquire the cloth appearance from a clear overview before using wrist depth. Robot-colored pixels inside a semantic polygon can imitate cloth rising with the hand. Visible cloth near a gripper alone is insufficient; check motion correspondence and both hands. Re-numbered rectangle corners are not persistent garment landmarks. A smaller outline after release is not proof of a neat fold.

Keep the first conveyor appearance immutable. Update recent position and motion separately, and reject jumps to robot parts using robot geometry, visible support and trajectory consistency. Initial identification can be correct while later association is wrong.

A button candidate may use an explicitly historical fixed-fixture map. A selection question should focus on that candidate's availability and provenance. Retract to expose the button for RGB-D. An attempted press or actuator stall is not proof of activation.

A phase label names a current objective. Ask phase completion first, then current action if unfinished. Future grasp, future activation and global task completion must not be required at selection or approach. Preserve Jev ownership of signs, grippers, retries and phase transitions.

All actual model-facing memories, states and questions must pass the final English/ASCII boundary check. Raw requests are the evidence; debug summaries may contain additional context that was not sent.

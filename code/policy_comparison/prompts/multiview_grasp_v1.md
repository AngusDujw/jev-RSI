# Multi-view grasping guidance

Complete the original task using the available RGB views and measured robot
state. The following are observation and feedback guidelines; you still choose
every pose, orientation, gripper command and correction.

- Before closing, compare the current high view with the working wrist view.
  Check three different questions: is the chosen grasp region between the inner
  finger faces laterally, does it reach the actual closing region in depth,
  and are the fingers at the object's grasp height? A block between two fingers
  in a projected image can still be beyond their tips, below them or behind
  them. Do not substitute image centering or silhouette overlap for these checks.
  Use the other wrist view or a useful camera-changing motion if a relevant
  dimension is occluded. Prefer a useful bounded observation motion to repeated
  inspections of unchanged images; then resume the approach.

- The reported control pose is LINK6, not the center of the gripping faces.
  Inspect the allowed robot-only geometry early and relate the real closing
  region to LINK6 and the visible fingers. Do not place LINK6 at an estimated
  object center and assume that the jaws are there. Verify the finger extension
  and closing directions in the current orientation. Changing yaw alone does
  not turn horizontally extending fingers into a downward grasp.

- Use measured motion after each action, not just the requested target. A lower
  target does not establish lower fingers or contact if actual descent stalls.
  Check viewpoint, reach and posture before trying to close at the same stalled
  pose. In the existing brief action reason, name the relevant cross-view
  evidence and, after a miss, the specific change that should improve capture.

- After closing, test a short lift while retaining the closed command. Confirm
  that the object moves with the hand using the fixed high view together with
  the wrist view. A visible colored edge, a narrowed gripper or an object centered
  in a moving wrist image is not enough. Mark an occluded result as unconfirmed.

- After a failed lift, record a short observation-based hypothesis in NOTES.md
  and make a meaningful correction to depth, grasp region or posture before
  another close. After two similar misses, reconsider the geometry or obtain a
  distinctly informative view instead of repeating the same pinch. Keep the
  working arm unless changing arms offers a concrete geometric advantage worth
  the transit. Establish one verified pickup before planning the next placement.

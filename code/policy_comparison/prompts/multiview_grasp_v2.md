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


## Quaternion and tool-axis check

The unit quaternion is wxyz and maps LINK6-local vectors into the shared
world/environment frame. For q=(w,x,y,z), the local +X direction in world is
[1-2*(y*y+z*z), 2*(x*y+w*z), 2*(x*z-w*y)]. Check this direction for the measured
pose and your proposed pose. A roll/pitch number or a rotating wrist image alone
does not establish that the finger extension points downward. Rotating about
the finger extension itself leaves that direction unchanged.

Use the full rotation matrix to relate both the finger-extension and closing
axes to the chosen visible grasp region. If using scipy Rotation.from_quat,
convert wxyz to xyzw first. With rotation matrices, a world-axis increment is
R_new=R_increment@R_current, whereas a local-axis increment is
R_new=R_current@R_increment. Choose the desired orientation yourself from the
geometry and RGB; verify that it actually changes the intended tool direction
before issuing it. Check measured orientation afterward, since a target is not
proof of tracking. Keep the existing local angular bound.

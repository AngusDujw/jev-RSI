## Recognize loss of capture during transport

Inspect the four original historical images in
`/home/ykj/project/gpt6/benchmark/gpt_as_policy_reference_assets/x5_block_slip_v8/`:
`seated_cam_high.png`, `seated_cam_right_wrist.png`,
`outside_cam_high.png`, and `outside_cam_right_wrist.png`.
The seated pair shows the white body between the finger faces. In the outside
pair the fingers have closed together while the white body is beyond their
tips. Its color remains visible in the wrist image, but it is no longer held.
These are historical visual examples, not current observations or an action
sequence to copy.

During transport, compare the object-to-finger relation with the last confirmed
held view and corroborate it in the fixed high view. Rotation relative to the
pads, sliding toward or beyond their tips, or closed fingers with the object
outside require reassessment before further transport or descent. Keep the
closed command while checking, but do not treat that command as continued
capture. Choose a bounded verification or recovery from the current images and
measured state; retract any held-object claim when following is contradicted.

## Include the robot-return stage in this stacking task

This stacking task includes returning both robot arms to their episode-start
EEF positions and orientations after the blocks have been placed. Save the
measured initial poses from the step-zero observation and reserve control steps
for this final stage.

Once the three-block stack is visibly stable, open the grippers, retreat clear
of the stack, and use bounded EEF motions to return each arm to its saved initial
position and orientation. Verify the measured poses during the return. A high
clearance waypoint is a transit pose; the final parking target is the saved
episode-start pose. Keep the stack undisturbed throughout the return.

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


## Empty-grasp corrections

The returned gripper_opening_command is an interpolated controller command,
not a measured gap, force or resistance signal. A value such as 0.077 after a
close does not mean that an object stopped the fingers. Judge grasp only from
actual finger/object images and subsequent object following.

Before a new close after a miss, use native image tools or your own PIL crops
to inspect enlarged CURRENT images of the chosen block and actual inner finger
faces in both the high and working-wrist views. Retain the surrounding geometry
for depth; do not rely only on a whole-scene preview or a tiny colored patch.
Match the same named block across views. In the existing short action reason,
state the evidence for lateral fit, depth overlap and grasp height; distinguish
an object below/outside the jaws from one inside their closing volume.

Compare requested descent with measured descent before claiming arrival. Two
commands to lower that produce little actual descent indicate an unresolved
reach/posture problem, not evidence of object contact. Change the approach or
orientation and verify actual motion before another closure at that location.
Image left/right is not a fixed world-axis sign, especially after wrist rotation;
check the observed effect of your last measured movement before repeating it.


## Default grasp strategy for simple blocks

For these tabletop blocks, prefer a near-vertical top-down pinch over a shallow
side approach. Before final descent, aim the actual finger-extension axis to
within about 15 degrees of world down, with the closing direction approximately
in the tabletop plane. Check this using the measured quaternion and images;
an Euler angle alone is insufficient. Choose your own quaternion and bounded
sequence. Reacquire the chosen block after changing orientation. Retain the
validated grasp orientation while translating, rather than silently accepting
orientation drift at every new observation. This is a strategy prior, not
evidence of clearance, contact or capture; verify the remaining conditions.


## Placing a held block on a base

A held block and a tabletop base have different heights. Their centers sharing
the same pixel coordinates in the high view does not prove shared world XY.
Likewise an image offset can partly be height parallax rather than lateral error.
Use both views of the same base and recheck alignment as the held block descends.

Approach above the base while preserving the verified grasp. Reduce vertical
increments near the support and refine the horizontal offset using the current
bottom-face/top-face relationship, not the earlier high-clearance image centers.
Look for support across the base top face rather than contact at one corner or
an apparent projected overlap. If placement support is unclear, keep holding
and obtain a useful view or small correction before releasing. Avoid forcing
continued descent after support. Once supported, open, withdraw vertically and
check that the placed block stays on the base. A release command alone is not a
completed stack; if it lands beside the base, recover that placement explicitly.

## Use the gripping region, not a projected fingertip corner

The wrist image's V apex is not a calibrated control point or a grasp goal.
For a block, aim to seat the body between the opposing inner pad faces at a
useful side-face height before closing. Touching one visible corner with the
tips can still be an empty or unstable pinch. Compare the block body with the
pad length and both inner faces, not only its lowest corner with a projected
tip line. Use a closed lift to resolve uncertain capture instead of repeatedly
opening and closing on nearly unchanged images.

In a view that exposes the finger length, a block lying entirely beyond the
line joining the fingertips is still outside the jaws. Bringing just its corner
to that line does not seat its body. The opposing side faces must overlap the
inner pad length toward the finger roots, not remain past the tips. Check this
in both views; do not turn this image relationship into a fixed world direction.

Static public robot files are available at
`/home/ykj/project/gpt6/benchmark/gpt_as_policy_robodojo/public_robot_reference/x5/`:
`X5A.urdf` and `meshes/link7.STL`, `meshes/link8.STL`. These describe only the
robot, not the scene or any block. Inspect them early to relate the gripping
region to the measured LINK6 pose and opening; then check against current RGB.
A mesh bounding box is not a contact measurement or a scene-clearance proof.

## Historical visual reference, not current scene evidence

Before the first grasp, view the four original PNGs in
`/home/ykj/project/gpt6/benchmark/gpt_as_policy_reference_assets/x5_block_grasp_v4/`:
`open_cam_high.png`, `open_cam_right_wrist.png`,
`lifted_cam_high.png`, and `lifted_cam_right_wrist.png`.

The open pair shows a block body seated along the opposing inner pad lengths,
not merely a corner at a projected fingertip line. The lifted pair shows visual
object-following across a fixed camera and a moving wrist camera. The folder's
README explains this reference and the manifest identifies its source images.

These are historical photos from another episode using the same robot. They
do not show the current object or current contact. Use them to recognize the
visible gripping region; choose every live correction and target yourself from
fresh observations. Do not copy old positions or treat reference holding as
evidence that the current block is held. Verify every live pickup and placement.

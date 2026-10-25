## Read the labelled historical attachments with the initial live observation

The first observation supplies the current high, left-wrist and right-wrist
images first, followed by sixteen labelled historical raw RGB examples.
The separate historical_reference_images descriptors identify their order,
appearance meaning and original file paths. Inspect these supplied examples;
you may reopen their source files for detail, but need not reopen an image
already inspected as an attachment. They are not current camera frames,
current block locations, action targets or complete task outcomes. Continue
to choose every current motion from the fresh live images and measured state.

## Establish the initial grasp posture before approaching purple

Before beginning the purple-block approach, keep the working gripper open at a clear
pose and turn the finger-extension axis toward world -Z. Calculate the actual
axis from the MEASURED LINK6 quaternion using
`Rotation.from_quat([x, y, z, w]).apply([1, 0, 0])`.
Its angle from down is `degrees(acos(clip(-axis[2], -1, 1)))`.
Keep an idle arm at its saved initial pose unless current evidence requires it
to participate or move clear. The near-down startup applies to the working arm.
First reach an actual angle of at most 15 degrees; a requested quaternion,
Euler label or wrist image is not proof that this posture was reached.

Until the purple pickup is verified, retain this near-downward extension and
correct position or the in-plane closing direction instead of starting with
a horizontal side pinch. Choose every bounded rotation and translation yourself
from current evidence. In the existing brief action reason, state the calculated
measured angle during this startup and at the first close, so the physical
posture is explicit.


# Task-specific stacking guidance

Choose every robot pose, orientation, gripper command and correction yourself
from the current RGB images, measured robot state and your same-episode history.
Use the normal calculation, image and code tools when useful.

## Goal and working plan

Stack all three blocks and then return both arms to their episode-start LINK6
positions and orientations. Save those initial measured poses now.

Leave the white block on the tabletop at its current location as the base.
Pick purple and place it on white, then place the wood-colored block on purple.
Do not first pick up or relocate white: a preliminary base move is unnecessary.
Select all actual grasp points, clearances and target poses from current evidence.

After purple is visibly supported on white and remains there after withdrawal,
save that measured LINK6 release pose, tool orientation and wrist image. This is
a robot reference, not an object pose. For placing wood, use its XY as a coarse
alignment anchor at clearance, with the same tool orientation. The support is
now higher: choose the release height from current evidence rather than reusing
the old release Z. Account for different seating of wood within the fingers;
matching LINK6 coordinates alone does not prove that the blocks align.

Stacking requires vertical support along world Z. A cube farther along the
table can appear above another in a wrist image while both remain on the
tabletop. Seeing separate top faces next to each other does not establish
vertical support. Use the fixed high view to inspect side-face height and the
upper block's bottom relative to the lower block's top. If the blocks are beside
each other after release, correct that lateral miss before attempting the next
layer. Account for perspective when comparing the two views.

## Robot and movement meaning

Both arms share one world frame. Stand behind the bases facing the workspace:
+X is right, +Y is forward away from the bases, and +Z is up. Position entries
0, 1 and 2 correspond to these axes. The wrist camera rotates with the hand;
image directions are not fixed world directions.

The commanded reference is LINK6, not the point between the gripping faces.
The X5 fingers extend along LINK6-local +X and oppose along local Y. Inspect
the real finger ends and inner faces, not the palm or wrist housing. Public
robot-only geometry is available at
`/home/ykj/project/gpt6/benchmark/gpt_as_policy_robodojo/public_robot_reference/x5/`.

Quaternions are absolute, unit wxyz. With SciPy, convert to xyzw before use.
Calculate `Rotation.from_quat([x, y, z, w]).apply([1, 0, 0])` to check the
measured finger-extension axis;
do not infer a downward grasp from an Euler label or a turning wrist image.
World-axis rotation increments premultiply the current orientation and follow
the right-hand rule. Prefer a near-downward pinch for these blocks, then retain
a verified useful orientation unless a specific failure requires changing it.

## Align the actual selected object

Match the same named block in the fixed high and working wrist views. A target
under the palm in the high image may be outside the actual finger region.
If the wrist shows a different block, investigate XY alignment at clearance;
do not repeatedly lower to solve that identity conflict. Bring the selected
block into the actual open jaw region. Use a small single-axis probe when a
direction is unclear, compare the measured motion and new images, and discard
the old image-direction mapping after changing orientation.

Before closing, inspect enlarged current views for the block body between both
inner faces, along their useful length and at side-face height. Check measured
descent. A stalled target is not proof of contact. Change the approach after a
miss instead of repeating the same pinch.

## Verify capture, support and completion

The opening command is not a measured finger gap or a contact signal. Close at
the chosen pose, inspect the fingers, and test a small retained-close lift.
Confirm object following against the fixed tabletop and moving wrist view;
a colored patch or image centering alone is insufficient. Reassess during
transport if the object rotates relative to the pads or slides beyond the tips.

Carry with the fingers and held block clear of existing blocks. Compare the
held block bottom with the current uppermost support face while approaching;
different image heights cause parallax. Release when support is plausible,
withdraw straight upward, and verify that the block remains on the stack.
If it lands beside the base, recover from that observed state.

Once all three remain stacked, open, retreat clear and return both arms to
their saved initial positions AND orientations using the bounded EEF interface.
Reserve control steps for this finish; a high transit pose is not the final
parking pose. Stop when the host reports the episode finished.


## Compare purple against the real useful finger length

Before the first approach, view these four original historical RGB images in
`/home/ykj/project/gpt6/benchmark/gpt_as_policy_reference_assets/x5_purple_v24/`:

- `missed_cam_high.png` and `missed_cam_right_wrist.png`: after a close, purple
  is beyond the converging finger ends. Its lower edge reaches the tips, but
  the body does not extend back along both inner faces. Being between the
  extrapolated jaw lines is insufficient.
- `retained_cam_high.png` and `retained_cam_right_wrist.png`: purple occupies
  substantial length between the separated inner faces after a small lift.
  Compare the full body relative to the actual finger ends, not pixel centering.

These are raw appearance examples, not current coordinates or commands to copy.
Keep the current white block as the base. Re-find each current cube after a
push, slip or camera rotation. Choose all current motions from fresh evidence.

Separate three alignment questions: across the closing direction, along the
finger length, and at the cube side-face height. A cube beyond the tips is not
automatically too high or too low. Use both views and measured motion to decide
which relationship is wrong; a wrist image alone cannot distinguish these
depths. If uncertain, make one small open single-axis probe and compare the new
cube-to-finger relationship. Do not combine XY and Z in that diagnostic probe.
Use the observed response to select the next correction, rather than repeatedly
lowering or repeating the same close/lift after the cube stays on the table.

## Inspect object faces, not the whole-image impression

Before closing or releasing, inspect enlarged crops of BOTH current high and
working-wrist images. You may make crops with the image/code tools; choose the
crop from the current RGB and retain enough surrounding pixels to identify the
fingers, source and intended support. Crops are details of the same observation,
not extra measurements. Keep the uncropped view available for context.

For pickup, locate the source side faces relative to the inner finger faces and
the actual fingertip ends. For placement, locate the held block's bottom edge
and the support's top face. Distinguish the white cube from white robot parts.
In your brief action reason, state one concrete visible relationship that
supports the chosen close or release. If the relationship is inconsistent
between views, retain the object and correct the specific mismatch. Do not
replace the inspection with a generic claim of being centered.

## Compare actual wood capture with a misleading closed-tip appearance

Before acting, view all six historical raw RGB images in
`/home/ykj/project/gpt6/benchmark/gpt_as_policy_reference_assets/x5_wood_v20/`:

- `retained_cam_high.png` and `retained_cam_right_wrist.png`: wood was carried
  above the table. Its side faces extend between the separated inner finger
  faces, with substantial body overlap along the finger length.
- `missed_cam_high.png` and `missed_cam_right_wrist.png`: wood is beyond the
  nearly touching fingertips. A centered wood patch, a small opening-command
  value and a tilted cube are NOT a retained grasp. This is a missed lift.
- `released_beside_cam_high.png` and `released_beside_cam_right_wrist.png`:
  wood is beside purple and white after release, not a third supported layer.

These are previous observations, not current object coordinates or motions
to replay. Use them to distinguish body-between-faces from body-beyond-tips.
Check current fixed and wrist images together. For both purple and wood, retain
the verified near-down finger-extension posture while correcting position and
the in-plane closing direction; do not switch to a horizontal pinch merely
because a close missed. If a lift leaves the cube on the tabletop or outside
the finger ends, reopen and correct its position within the useful finger
length before another close. Do not spend repeated lifts on that miss.

For placement, compare the held cube bottom and support top in both views.
Keep the known useful orientation and use the saved previous-layer robot
release XY only as a coarse anchor. When the support top is hidden, a small
change of view or approach may reveal the edge; wrist-image vertical ordering
alone is not support. Verify the released block after moving the hand clear;
recover a lateral miss before proceeding. Choose every current target yourself.

## Validate a bounded return command for each arm

Before submitting any target, calculate translation norm and quaternion
geodesic angle separately for LEFT and RIGHT against the latest measured pose.
For unit wxyz quaternions q and target t, the angle in radians is
`2*acos(clip(abs(dot(q,t)),0,1))`. Require each arm to be at most 0.05 m and
0.35 rad per call, with at most five physical steps. A fractional move toward
home is not automatically within these bounds. Use smaller intermediate
poses when needed; do not repeat a rejected target. Read the exact current
`next_call` and observation paths supplied by the tool instead of guessing an
observation index. These checks validate your own chosen command, not an
object pose or a grasp.

## Track executed progress and preserve the finish budget

A commanded target is not the measured reached pose. The five-control horizon
may execute only part of a rotation or translation. Recompute each next target
from fresh measured feedback; do not count requested increments as completed
motion. The opening command is neither actual gap nor proof of side contact.

After a failed retained-close lift, compare before/after fixed-view tabletop
landmarks and wrist finger geometry before spending more lifts. A camera moving
past a stationary cube can create apparent image motion. If the fixed view is
occluded, obtain a revealing view while maintaining a safe grip rather than
asserting capture. Check retention again after transport begins.

Plan the return early from measured distance and remaining orientation, allowing
for observed underreach per call. Preserve at least 80 of the 550 physical
controls for clearing the blocks and returning both arms when needed. At that
budget boundary, reassess the achievable finish instead of repeating a failed
pickup until no return time remains. During return, verify actual position AND
orientation errors after each call; a bounded command alone does not finish it.
All current targets and tradeoffs remain your choices from allowed observations.

## Check the support hypothesis against a matched visual counterexample

Before attempting a layer release, view all six original RGB images in
`/home/ykj/project/gpt6/benchmark/gpt_as_policy_reference_assets/x5_support_v25/`:

- `before_missed_release_cam_high.png` and
  `before_missed_release_cam_right_wrist.png`: purple is still held near white.
  The wrist makes their edges look as if they meet, but that impression did not
  predict a supported layer.
- `adjacent_after_release_cam_high.png` and
  `adjacent_after_release_cam_right_wrist.png`: after opening and withdrawal,
  the wrist still puts purple above white on screen. The simultaneous high
  view shows separate cubes adjacent on the tabletop. This is not a layer.
- `supported_two_layer_appearance_cam_high.png` and
  `supported_two_layer_appearance_cam_right_wrist.png`: after withdrawal the
  high view shows purple elevated on white with the lower white side face
  beneath it. The wrist ordering differs from the misleading adjacent example.
  This illustrates two-layer geometry only, not a complete task outcome.

These historical images supply appearance evidence, not current poses, motion
commands or pixel coordinates to copy. In fresh high and wrist images, locate
the two actual cube bodies separately from the fingers. A hidden support,
matching image centers, a stalled descent or touching projected edges leaves
support uncertain; none alone is a release criterion. At a clear height, use
your own small measured single-axis corrections to resolve lateral alignment.
Inspect the lower block's side face and the upper block's bottom at the support
approach height before opening. If the fixed view and wrist disagree, preserve
the grasp and seek a revealing view rather than treating occlusion as overlap.

After each release, move the open hand clear enough to expose both cubes in a
fresh high view. Compare with BOTH historical post-release examples. Continue
to the next block only when the released upper cube remains visibly elevated
on the lower cube; two separate top faces at different tabletop depths remain
a failed placement. If support is uncertain, keep the current layer as the
unfinished objective. If the cubes are adjacent, re-localize and recover that
layer before selecting wood. Do not promote a plausible wrist interpretation
into a completed stage. Choose all current probes, targets and recoveries yourself.

## Preserve the existing layer during the next block's transit

The initial historical attachments include two high-view frames named
x5_clearance_v27_before_layer_loss and x5_clearance_v27_after_layer_loss.
They show the same previous episode before and after a CLOSED wood-carry
approach: purple becomes displaced beside white before wood is opened.
These images establish a visible ordering of events, not a hidden contact
measurement, current object coordinates or motion to copy.

For wood, first establish in fresh high and working-wrist views that the
entire carried block AND the lowest finger parts clear the current purple top
before translating across the stack footprint. Pickup clearance over the table
does not establish clearance over an existing layer. A high LINK6 value or
matching a saved release XY does not locate the carried block's bottom.
Choose your own bounded vertical rise and verify its actual execution while
remaining laterally clear; then carry over the support at the verified height.
Only begin the final vertical approach after lateral alignment at clearance.

Inspect the previously completed purple-white layer again during the approach,
not just after the earlier purple release. If purple tilts, shifts or disappears
from white, stop treating the saved release anchor as an intact support.
Keep wood retained and clear while reassessing the actual pair. Do not descend
toward exposed white or open wood merely because it now overlaps that lower
cube. Resolve the damaged lower-layer state before attempting a third layer.

For a third-layer release, the held WOOD BOTTOM must approach the PURPLE TOP
from above in world gravity. A wrist image showing the purple bottom meeting
the wood top is the opposite relation and does not justify opening. Use both
fresh views and actual measured motion to resolve depth and occlusion; preserve
the grasp if that relation is uncertain. All current clearance heights, probes,
targets and recovery choices remain yours.


## Keep an observation evidence ledger and latch the final return

For the selected block, keep a compact record of the last diagnostic pair:
physical step IDs, current object identity in BOTH views, measured hand change,
and the actual block-to-finger relationship before and after. Use the same
raw-image coordinate frame or explicitly map crop offsets and scale; pixel
numbers from differently resized crops cannot be subtracted. Locate the real
inner faces and fingertip segments before interpreting a block as between them.
Being inside the extended jaw lines or having its bottom pass a tip on screen
does not show body contact along the finite finger faces.

During a retained-close lift, record capture as UNKNOWN if the source location
is hidden. A wrist patch that stays centered does not remove that uncertainty.
Before lateral transport, reveal the original source footprint in the fixed
view and check that the SAME block follows the hand, separately from white and
wood. If the source remains on the table, invalidate the previous capture claim
and diagnose the actual side-face mismatch rather than citing that claim again.

For an open single-axis probe, compare the signed change in one chosen
block-to-finger gap with the measured executed displacement. Keep orientation
and the other axes fixed. If a correction repeatedly reverses sign without
reducing the same gap, stop extrapolating from screen up/down: reidentify the
object, actual finger ends and crop frame. Make one revealing diagnostic rather
than repeating an unverified direction story. Clear this mapping after a
rotation or object motion. Choose every correction from the new evidence.

Once the remaining control budget has caused you to begin the final clear-and-
return phase, latch that phase. Verify both measured home poses and keep the
open arms there until the host finishes; do not start a new pickup merely
because the return used fewer controls than expected. In the normal startup
or return motion, use the allowed control horizon to realize your chosen
bounded target and remeasure; repeated one-control rotations can underreach.
These checks organize your observations, not object poses or predetermined
robot actions.

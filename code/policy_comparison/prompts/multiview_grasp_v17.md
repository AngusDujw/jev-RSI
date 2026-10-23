## Establish the initial grasp posture before approaching purple

Before beginning the purple-block approach, keep the gripper open at a clear
pose and turn the finger-extension axis toward world -Z. Calculate the actual
axis from the MEASURED LINK6 quaternion using
`Rotation.from_quat([x, y, z, w]).apply([1, 0, 0])`.
Its angle from down is `degrees(acos(clip(-axis[2], -1, 1)))`.
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


## Recognize the cube relative to the actual fingers

Before the first grasp, inspect the six original historical RGB illustrations in
`/home/ykj/project/gpt6/benchmark/gpt_as_policy_reference_assets/x5_white_grasp_v14/`:

- `missed_cam_high.png` and `missed_cam_right_wrist.png`: after an unsuccessful
  lift, white stayed on the tabletop, ahead of the finger ends. A white patch
  centered in the wrist image did not mean that the block was held.
- `open_cam_high.png` and `open_cam_right_wrist.png`: an open approach before a
  later pickup. This is an approach illustration, not evidence of capture.
- `lifted_cam_high.png` and `lifted_cam_right_wrist.png`: white is seated alongside
  both inner faces; the fixed view and changed background support its lift.

White appears only to illustrate finger-to-block geometry; keep the CURRENT
white block as the untouched base. These are historical appearance examples,
not current observations or poses to copy. Compare the cube body, fingertip ends and inner faces across both views.
Distinguish the separate white cube from white robot parts. Re-find the cube in
fresh images after a push or slip; its former tabletop location is no longer a
valid target. Choose all current motions yourself and verify object following.


## Check measured placement height before opening

For each captured block, keep its measured tabletop pickup pose from just before
the verified lift. At an unchanged orientation and unchanged seating inside the
fingers, a LINK6 height change produces the same block height change. Releasing
at its tabletop pickup height returns the block to table level; placing it on
another block requires a higher support level. Choose that height from current
RGB evidence, your robot geometry and the historical illustration below.

Before the first stacking release, inspect the four original RGB images and
`robot_reference_change.json` in
`/home/ykj/project/gpt6/benchmark/gpt_as_policy_reference_assets/x5_two_layer_v12/`.
`base_only_cam_high.png` and `base_only_cam_right_wrist.png` show a single base.
`two_layers_cam_high.png` and `two_layers_cam_right_wrist.png` show a later
visible pair after release and withdrawal. The metadata describes only measured
robot-reference change between the two historical releases. It is not a cube
height, current target or one action to copy. Select all current poses yourself.

Before opening, calculate your ACTUAL measured LINK6 difference from the intended
release pose and, when applicable, the previous release reference. Record the
pose at the release action, not the later withdrawn pose. Large XY changes need
evidence of different block seating inside the fingers; a base displaced in the
wrist image by height parallax alone does not justify them. First reach the
chosen placement pose while retaining the grip. Then open without translating
or rotating, inspect support, and withdraw. In the existing brief reason, state
the measured height and how its support level differs from tabletop pickup.

# Task-specific stacking guidance

Choose every robot pose, orientation, gripper command and correction yourself
from the current RGB images, measured robot state and your same-episode history.
Use the normal calculation, image and code tools when useful.

## Goal and working plan

Stack all three blocks and then return both arms to their episode-start LINK6
positions and orientations. Save those initial measured poses now.

For this layout, use the white block as the base: pick it, place it on clear
central tabletop, and verify that it stays there after release and withdrawal.
Next place purple on white, then the wood-colored block on purple. Select all
actual grasp points, clearances and target poses from current evidence.

When a base placement is verified, save its measured LINK6 release pose, tool
orientation and a wrist image. This is a robot reference, not an object pose.
For the next placement, use it as a coarse alignment anchor rather than trying
to center an elevated object over the base solely in the high image. Restore
the reference tool orientation at clearance before using that anchor. Account
for visibly different seating of the held block within the fingers; matching
LINK6 coordinates alone does not prove that the blocks align.

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
Calculate `R(q).apply([1, 0, 0])` to check the measured finger-extension axis;
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

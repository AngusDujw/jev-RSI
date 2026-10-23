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

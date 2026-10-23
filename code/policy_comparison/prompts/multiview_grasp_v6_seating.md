## Use the gripping region, not a projected fingertip corner

The wrist image's V apex is not a calibrated control point or a grasp goal.
For a block, aim to seat the body between the opposing inner pad faces at a
useful side-face height before closing. Touching one visible corner with the
tips can still be an empty or unstable pinch. Compare the block body with the
pad length and both inner faces, not only its lowest corner with a projected
tip line. Use a closed lift to resolve uncertain capture instead of repeatedly
opening and closing on nearly unchanged images.

Static public robot files are available at
`/home/ykj/project/gpt6/benchmark/gpt_as_policy_robodojo/public_robot_reference/x5/`:
`X5A.urdf` and `meshes/link7.STL`, `meshes/link8.STL`. These describe only the
robot, not the scene or any block. Inspect them early to relate the gripping
region to the measured LINK6 pose and opening; then check against current RGB.
A mesh bounding box is not a contact measurement or a scene-clearance proof.

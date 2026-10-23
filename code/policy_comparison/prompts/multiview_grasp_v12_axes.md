## Meaning of the shared world axes

Both arms use the same environment-origin frame. Stand behind the robot bases,
facing into the table workspace: world +X is to your right, world +Y is forward
away from the bases, and world +Z is up. Negative reverses each direction.
Increasing position[0], position[1], or position[2] moves LINK6 along world +X,
+Y, or +Z respectively. These axes do not rotate with the hand or its camera.

A world-Y translation is horizontal even when the fingers point down. Finger
extension is LINK6-local +X, whose world direction is determined by the current
quaternion. Keep world translation axes, local tool axes, and image directions
distinct. Do not assume image-up means world +Y, or that the same wrist-image
direction survives a hand rotation. Use fresh images and measured motion to
check your chosen direction.

The action interface uses absolute unit quaternions in wxyz order, not Euler
increments. A positive world-axis rotation follows the right-hand rule and
premultiplies the current orientation. Rotation changes finger geometry as
well as the wrist image; calculate its intended effect before execution and
check the measured pose afterward.

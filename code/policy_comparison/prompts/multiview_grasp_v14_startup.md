## Establish the initial grasp posture before approaching white

Before beginning the white-block approach, keep the gripper open at a clear
pose and turn the finger-extension axis toward world -Z. Calculate the actual
axis from the MEASURED LINK6 quaternion using
`Rotation.from_quat([x, y, z, w]).apply([1, 0, 0])`.
Its angle from down is `degrees(acos(clip(-axis[2], -1, 1)))`.
First reach an actual angle of at most 15 degrees; a requested quaternion,
Euler label or wrist image is not proof that this posture was reached.

Until the white pickup is verified, retain this near-downward extension and
correct position or the in-plane closing direction instead of starting with
a horizontal side pinch. Choose every bounded rotation and translation yourself
from current evidence. In the existing brief action reason, state the calculated
measured angle during this startup and at the first close, so the physical
posture is explicit.


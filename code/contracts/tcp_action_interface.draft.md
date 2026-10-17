# Shared TCP action description

Status: TCP is confirmed. All six positive single-axis directions below were physically demonstrated in RoboDojo on 2026-10-17 (run04, 620 native controls). They are not yet connected to a planner/advancer runtime. Combined rotations, gripper ownership, step scheduling, arm-selection output and stage-progress enums remain separate discussion items. The stated combination order is an explicit proposal, not a claim that a combined motion was tested.

Read the same marked English block into both model requests: after the planner/advancer role description, before the task or current-stage observations. Supply the current arm and step sizes alongside it. No separate wording-generation step is required.

<!-- SHARED_ACTION_DESCRIPTION_START -->
Robot actions

Control the TCP, the center between the gripping faces. Both arms use the same world frame. Stand behind the robot bases facing the workspace: +X is right, +Y is forward, +Z is up.

- x positive / negative: move the TCP right / left.
- y positive / negative: move the TCP forward / backward.
- z positive / negative: move the TCP up / down.
- yaw: rotate about world Z. Positive is counterclockwise viewed from above.
- pitch: rotate about world X. From a straight-down grasp, positive tilts the fingers forward toward +Y.
- roll: rotate about world Y. From a straight-down grasp, positive tilts the fingers left toward -X.

Positive rotations follow the right-hand rule; negative reverses them. Hold means zero increment on that channel. Rotation axes stay fixed in the world. Rotate about the TCP: rotation alone keeps its target position fixed; translation alone keeps tool orientation fixed.

These are increments, not absolute Euler angles. Combine rotations in this order: pitch about X, roll about Y, yaw about Z. Step sizes are supplied in meters and radians; select directions only.

Image directions depend on the camera, and wrist cameras move with their arms. Check subsequent measured state and images to verify actual motion.
<!-- SHARED_ACTION_DESCRIPTION_END -->

## Exact implementation convention

For signs s_x, s_y, s_z, s_yaw, s_pitch, s_roll in {-1, 0, +1}, translation increments have the specified world components. With the configured per-channel rotation increments, R_next = Rz(delta_yaw) @ Ry(delta_roll) @ Rx(delta_pitch) @ R_current. The flange target is an internal implementation detail and is omitted from the model-facing description as requested.

The demonstration uses only one nonzero channel at a time, +0.05 m for translations or +pi/6 rad for rotations. These totals are demonstrations, not a proposed single-decision step size. The native simulator follows a dense sequence of small joint commands, with fresh measured state and RGB recording.

Verified recording: `/data/ykj_robodojo/RoboLaya/runs/tcp-axis-audit-20261017/run04`. Review audit: `../runs/tcp-axis-audit-20261017/audit.json`. This is a continuous diagnostic with the recording horizon extended from 200 to 2000; it is not a benchmark score. The robot physically returns to its common initial TCP before each clip. Maximum initial TCP spread: 0.000965 mm; maximum endpoint position error: 0.000970 mm; maximum endpoint orientation error: 0.000373 degrees; maximum TCP drift during rotation: 0.030197 mm. These are simulated robot-state measurements, not real-hardware accuracy claims.

## Sources and differences

- Local Inspect Robots RealMan: `plugins/inspect-robots-realman/src/inspect_robots_realman/model_description.txt` and `embodiment.py` (`observe`, `solve`). It uses per-arm configured frames (+X forward, +Y left), start-relative intrinsic ZYX with a negated pitch coordinate. Copy its concise effect descriptions, not its numeric axes.
- RoboProbe: `policy/RoboDojo_Agent_L3_Inspect_EEF/docs.py` and `pose.py` (`angles_to_quat`, `pose_to_values`, `values_to_pose`). Its world frame has +Y forward and +X lateral. Its single-axis pitch/roll/yaw definitions are world X/Y/Z. Our direction channels reuse those axis names but are incremental about the current pose, rather than absolute angles about its top-down reference.
- TCP for this diagnostic: public X5A URDF gripping-face center at LINK6-local [0.15007, 0, 0] m. This reference is not a contact or grasp assertion.

Only the marked block is shared model input. Experiment management, sources and verification notes stay outside model prompts.

# Shared TCP action interface — discussion draft

Status: TCP control is confirmed by the user. The exact incremental rotation convention, motion scales, arm-selection protocol, gripper control and stage-progress enumeration remain under discussion. This document is not an enabled runtime contract.

Sources: RoboProbe `policy/RoboDojo_Agent_L3_Inspect_EEF/README.md`, `docs.py` and `pose.py`. The reference controls a grasp center and converts it to a flange pose. Its absolute angle convention must not be silently reused as our incremental YPR convention.

## Shared model-facing block

The same block below is intended for both model calls. Its contents are English.

<!-- SHARED_ACTION_DESCRIPTION_START -->
Robot action interface

Position observations and translation commands refer to the nominal tool center point (TCP), defined between the gripping faces using public robot geometry. The TCP is a robot reference point; it does not imply contact or capture.

The runtime converts TCP pose targets into flange targets. Do not add a flange-to-TCP offset to an already reported TCP position.

Translation channels x, y and z refer to the RoboDojo world frame. Positive selects the corresponding positive world-axis direction, negative selects the opposite direction, and hold commands zero increment on that channel. World +Z is upward. The verified robot mounting description supplies the world X/Y orientation relative to the workspace.

The runtime supplies the exact signed rotation-channel definitions, rotation pivot, composition rule, current motion scales and execution horizon with this interface before control is enabled. Do not infer those definitions from the words yaw, pitch and roll alone.

Camera image directions are not world-axis directions. A wrist camera moves with its arm. Any supplied axis overlay describes the named robot point and camera at the stated observation step.

Commanded motion is not measured motion. Use the subsequent measured robot state and RGB observations to assess execution and task progress.
<!-- SHARED_ACTION_DESCRIPTION_END -->

## Intended insertion points — not yet wired

Planner request order: planner-role instructions, this shared action block and verified robot description, available processing-tool interfaces, then the task and initial observations. The planner designs stages and observation processing compatible with this interface; it does not redefine the action protocol.

Advancer request order: advancer-role instructions, the identical shared action block and current runtime parameters, then the current stage, measured robot state, actual image content, processing results and execution feedback. Fixed direction/stage questions follow the evidence.

Store this text once and read the same marked block for both requests. No wording-generation model and no independent second description are required. A later implementation should record the block version/hash in both requests. Until the pending conventions are agreed, do not connect this draft to the robot runtime.

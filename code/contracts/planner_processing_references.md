# Reference implementations

These are optional code examples from the earlier LIBERO implementation. They illustrate converting observations into extra decision inputs; they are not a pipeline already prepared for the current task. You are responsible for choosing, implementing or adapting, and testing the method for the current task. You may design other methods. Do not import the previous controller's fixed stages, actions, historical inputs, thresholds or robot conventions.

## Example 1: Visible measurements to world-space geometry

Source: `code/scripts/libero_jev_recovery.py`, the nested `cloud` function in `run_recovery`:

```python
def cloud(v):
    vv, uu = np.indices(v['depth'].shape)
    d, K, T = v['depth'], v['K'], v['T']
    return np.stack([(uu-K[0,2])*d/K[0,0], (vv-K[1,2])*d/K[1,1], d], -1) @ T[:3,:3].T + T[:3,3]
```

This back-projects depth pixels using intrinsics K and a camera-to-world transform T. The earlier workflow selected visible regions and measured their geometry using `GenericVision.recognize` and `GenericVision.measure` in `code/scripts/libero_generic_vision.py`. Those implementations can be inspected using code tools.

Depth, calibration and transform conventions must be established and tested for the current task. An RGB-only observation does not directly supply measured depth. RGB-based depth estimation, multi-view geometry or another method may be chosen instead, with their uncertainty evaluated. A visible region's center is not necessarily a suitable grasp point.

## Example 2: Geometry to per-axis structured decision inputs

Source: `code/scripts/libero_jev_recovery.py`, `run_recovery`, construction of `state['translation_axes']`:

```python
state['translation_axes'] = {
    a: dict(
        current_coordinate_m=float(position[i]),
        goal_coordinate_m=float(target[i]),
        goal_minus_current_mm=round(float(error[i])*1000, 2),
        relation='within_tolerance' if abs(error[i]) < .002
                 else 'goal_coordinate_larger' if error[i] > 0
                 else 'goal_coordinate_smaller'
    ) for i, a in enumerate('xyz')
}
```

This example exposes current and goal coordinates, their signed difference, and a categorical relation. Its tolerance is a historical example, not a prescribed threshold. Establish how the target and current TCP are defined, validate error = target - current in the same frame, and choose a tolerance justified by measurement uncertainty and the stage's needs. Additional information need not use this representation.

## Example 3: Robot geometry as an observation-processing ingredient

Source: `code/scripts/libero_robot_geometry.py`, `gripper_geometry` and `envelope`; `code/scripts/libero_jev_recovery.py`, `fit_candidates`.

The previous implementation combined visible source bounds with robot gripper geometry to estimate finger-region alignment, opening requirements, and support clearance. These are estimates derived from observations and robot geometry, not scene contact truth or proof of a successful grasp. Inspect the source if useful, adapt robot-specific geometry and coordinate definitions, and verify the current implementation instead of copying the earlier task-specific candidate selection policy.

These examples are non-exhaustive. Their source code is reference material, not an experience bank or a requirement to reproduce the earlier LIBERO controller.

## Example 4: Make a visual comparison explicit

Additional reference implementations: `libero_visual_relation_servo.py`, `libero_visual_band_servo.py`, and `libero_hybrid_vision.py` in the separate `decision_multimodal` implementation. Their transferable idea is a named visual relation with a visible acceptance region. A fixed-center image band was used there for a narrowly defined centering test; its location and fixed motion mapping are not general manipulation targets.

An excerpt of the image-band construction is:

```python
layer = Image.new('RGBA', picture.size)
draw = ImageDraw.Draw(layer)
draw.rectangle((352, 0, 416, 767), fill=(0, 255, 255, 20))
draw.line((352, 0, 352, 767), fill=(0, 255, 255, 255), width=2)
draw.line((416, 0, 416, 767), fill=(0, 255, 255, 255), width=2)
picture = Image.alpha_composite(picture, layer).convert('RGB')
```

Those pixel coordinates belong to that example's crop. For a new task, select the relevant physical feature and reference: a graspable part versus the opposing finger region, a source bottom versus a support region, or a visible pointer versus its desired angular sector. Explain the feature identities and overlay legend. Use a crop only when it retains enough context; retain a current full view when a crop could hide an obstacle or confuse identity. An image midpoint is a valid target only after establishing its relationship to the actual stage goal.

You may provide fresh annotated images as additional inputs through the image_path interface. They can show detected contours, a justified tolerance region, named tool/source axes, and uncertainty. Preserve the distinction between measured features and hypothetical geometry. A projected overlap, a marker, or an image band does not certify metric precision, grasping, contact or support.

The advancer in this architecture still answers its fixed XYZ, yaw, pitch, roll, gripper and stage-progress questions. The earlier relation-only output schema and its hard-coded image-direction-to-world-direction conversion are not part of this interface. Make the visual evidence and its interpretation usable for the fixed questions instead.

The hybrid reference used visual relations for coarse approach and explicit signed errors for finer alignment. This is an optional division of evidence, not a mandatory pipeline or prescribed threshold. Decide which representation is useful at each stage, and verify the information actually produced on permitted observations. A coarse approach need not depend on the precision required for final contact.

## Example 5: Extend the comparison to rotation

Useful visual relations include an opposing-jaw line versus a target grasp axis, finger extension versus a support normal, or an elongated object axis versus a receiving fixture. Name the particular axes or features. Object-center alignment alone does not determine orientation. Projection can hide out-of-plane ambiguity; select additional views or derived geometric information when the intended decision requires it.

The following generic robot-only calculation illustrates hypothetical orientation cues; it is not an action selector or a ready perception pipeline:

```python
import numpy as np
from scipy.spatial.transform import Rotation

WORLD_AXIS = {'yaw': [0., 0., 1.],
              'pitch': [1., 0., 0.],
              'roll': [0., 1., 0.]}

def hypothetical_tool_rotation(current_world_from_tool, channel, angle_rad):
    delta = Rotation.from_rotvec(angle_rad * np.asarray(WORLD_AXIS[channel]))
    return delta.as_matrix() @ current_world_from_tool
```

For an annotated fixed-camera view, a processor may project the current tool axes and separately labeled hypothetical positive/negative single-channel rotations. Derive image projections using the current camera convention and measured robot pose, then test the sign interpretation. Explain that these are robot-only hypothetical orientations, not future rendered observations or a scene-clearance certificate. In X5, tool-local +X follows finger extension and tool-local Y follows jaw sliding; establish the actual tool geometry instead of assuming a conventional tool-Z approach axis.

For a wrist camera, propagate its mounting transform with the hypothetical TCP orientation: world_from_camera_candidate = world_from_tcp_candidate @ tcp_from_camera_mount. Holding the wrist camera fixed while rotating its parent gives a false image-effect prediction. Projecting an object under a hypothetical camera additionally requires a current camera-derived feature hypothesis and an explicit assumption about whether that feature remains stationary; unknown attachment or object motion cannot be silently assumed. A world-axis orientation legend is helpful context but is not a metric image-motion predictor.

Choose, adapt or replace these representations for the task. Test XYZ and rotational interpretation separately where useful, then check their combination under the fixed interface. At most one rotational channel may change in a decision; translation may accompany that rotation. The examples prescribe neither the stage graph nor the processing algorithm, and introduce no history or experience inputs.

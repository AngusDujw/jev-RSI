"""The established stage contract with honest camera-derived evidence semantics."""
from .stage_prompts import LEGACY_V11_PROMPT


VISION_V1_PROMPT = LEGACY_V11_PROMPT.replace(
    'Input mode is explicitly privileged physical observation, NOT an RGB-only performance claim. Labels/rewards are excluded.',
    'Input mode is RGB-only object observation with calibrated cameras and measured robot proprioception. Visual object IDs come from GPT image detection, not simulator assets. No object truth, scene metadata, depth, reward or success label enters the policy. Positions are estimated by triangulating RGB boxes; tracking can be lost or stale.')
VISION_V1_PROMPT = VISION_V1_PROMPT.replace(
    'The object IDs, geometry, keypoints and measured joint fields listed in variables are available; never invent fields.\nObject up_x/up_y/up_z are measured world components of the object\'s local +Z; qw/qx/qy/qz are observed WXYZ.\nThese can test uprightness when present. Older experience saying orientation is unavailable must not override them.',
    'Use only fields actually listed in variables; never invent fields. Object orientation is UNKNOWN. Its neutral quaternion and up vector are placeholders required by the expression interface, never evidence of orientation or uprightness. Object bbox thickness is only a coarse visual uncertainty envelope, not an asset mesh or precise collision surface. A position marked STALE cannot prove grasp, lift, or final acceptance. Inspect RGB, box provenance and ray gap before relying on a tight contact.')
VISION_V1_PROMPT += '''
Camera-estimated object XYZ can differ by centimeters from its physical origin.
Some objects appear in only one view: their XY may be projected using a depth
proxy from prior visual evidence or other triangulated objects. Their Z is
UNVERIFIED and must never prove a lift, stack height, grasp following or final
vertical acceptance. Obtain a second view before using target-height change as
evidence; bounded hand descent may use the last validated table-height estimate.
When a previously well-localized, ungrasped tabletop target is briefly hidden
by the approaching gripper, its last RGB-derived position may guide a short
reach and finger closure if no image shows it moving. Mark that position as
stale and never use it to prove capture, lift, or success. Arrange a clear
second view for the subsequent object-motion check. An observation handoff
after every reach increment can hide the target repeatedly; reserve
observe_after for a view that can actually improve evidence or for a meaningful
contact/lift verification boundary.
If present, last_stereo_x/y/z and last_stereo_age_ticks name the last accepted
two-camera RGB measurement and its age in native control ticks. For a still
ungrasped tabletop target, these values may guide a bounded approach through
temporary occlusion. Use them only as past camera evidence, not an exact mesh
pose, a current object location after possible motion, or a success predicate.
An item can be marked visual_motion_confirmed after sustained, same-direction,
appearance-consistent displacement in the fixed head RGB camera. Only then
may camera-derived vx/vy and visual_xy_velocity_age_ticks be exposed. These are
noisy horizontal estimates, not simulator velocity or a measured vertical
component. For moving targets use short, updated interception stages and do
not aim at a stale starting position or infer capture from the velocity alone.
Images labeled reference_* are historical RGB crops of previously detected
moving items. They can help compare a currently visible item with an earlier
appearance, but are not current observations. Keep physical-instance IDs and
the order of observed appearances distinct; similar appearance alone cannot
prove that a new item is the same physical instance or that it has been lifted.
For an active camera-observation stage, a hand pose is a search waypoint, not
the goal. VisualDetection variables provide stereo_valid, stereo_streak and
xy_fresh from camera evidence. Use finish_on="checks" with completion such as
now.o.TARGET.stereo_streak >= 2 for each target that needs depth, so observation
ends as soon as two consecutive trustworthy stereo frames arrive. These flags
show sensing quality only; they never prove contact or task completion.
Plan reachable, conservative short stages and refresh visual localization at
measured milestones. Prefer visual motion that is sustained across multiple views
to a single noisy frame. Do not turn a robot-only hand displacement into object
displacement. For tasks needing exact orientation, named mesh/material points,
button joints or counts, acknowledge when current visual variables cannot test
the required predicate and request visual re-observation or a suitable measured
sensor; never substitute the neutral object quaternion for evidence.
'''

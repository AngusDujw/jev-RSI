## Recognize loss of capture during transport

Inspect the four original historical images in
`/home/ykj/project/gpt6/benchmark/gpt_as_policy_reference_assets/x5_block_slip_v8/`:
`seated_cam_high.png`, `seated_cam_right_wrist.png`,
`outside_cam_high.png`, and `outside_cam_right_wrist.png`.
The seated pair shows the white body between the finger faces. In the outside
pair the fingers have closed together while the white body is beyond their
tips. Its color remains visible in the wrist image, but it is no longer held.
These are historical visual examples, not current observations or an action
sequence to copy.

During transport, compare the object-to-finger relation with the last confirmed
held view and corroborate it in the fixed high view. Rotation relative to the
pads, sliding toward or beyond their tips, or closed fingers with the object
outside require reassessment before further transport or descent. Keep the
closed command while checking, but do not treat that command as continued
capture. Choose a bounded verification or recovery from the current images and
measured state; retract any held-object claim when following is contradicted.

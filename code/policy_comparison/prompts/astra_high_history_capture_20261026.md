# Single-episode block stacking

Use the fresh high, left-wrist and right-wrist RGB images and public measured
robot state to complete stack_blocks. Choose the working plan, block order,
grasps, poses and corrections yourself. No historical demonstration is supplied.

Record the episode-start measured LINK6 positions and orientations of both
arms. The requested finish includes a stable three-block stack and returning
both open arms to those measured starting poses. Use feedback to verify the
arrangement and the return separately. Follow the host's original bounded EEF
interface and remaining control budget. Keep public action reasons concise
and describe the evidence for your chosen motion. Treat occluded relationships
as uncertain rather than inventing contact or object poses.

All current actions must be selected from the allowed fresh observations and
your own same-episode history. Native evaluation is reported separately by
the host and is not policy input.

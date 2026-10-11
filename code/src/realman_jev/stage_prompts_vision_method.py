"""Stage planning after a live GPT visual-method decision."""
from .stage_prompts_vision import VISION_V1_PROMPT


VISION_METHOD_V1_PROMPT = VISION_V1_PROMPT + '''
The visual_method in this request is YOUR separate, live, per-episode method
plan from public task language and the first RGB images. Use its declared
visual IDs and available algorithms. Do not assume an RGB box, GrabCut mask or
triangulated center measures a support surface, opening, exact grasp contact,
orientation, whole mesh, or final native success. Any item in
unobservable_requirements remains unknown until new permitted camera evidence
actually resolves it. If the required relation cannot be measured with these
sensors, say so in reasoning and make a bounded reobservation stage, rather
than inventing an object coordinate or marking task completion.

For EVERY stage whose target, completion or abort expression refers to an
object, declare visual_requirements covering EACH referenced visual entity.
Choose visible_rgb for a currently visible 2D identity; choose fresh_stereo
when current metric XYZ is required. For a SHORT approach/closure through
gripper occlusion, last_stereo_bounded may use the most recent accepted
two-view point within the declared age. It cannot prove capture, lift,
placement or task completion, and no object completion predicate may rely on
that stale point. A requirement is
checked immediately before each Jev decision. If it fails, no motor action is
sent and you receive the failed measurement for replanning. For robot-only
withdrawal, visual_requirements may be empty. Every decision already obtains
new RGB and updates local tracking; observe_after causes an EXTRA full GPT
planning call. Use it only when the remaining stage design truly depends on
new post-contact or post-placement evidence, at most THREE times in one plan.
Do not set it on ordinary alignment, descent, release or retreat stages just
to refresh camera evidence.
Camera-derived object coordinates are estimates, never simulator truth.
'''

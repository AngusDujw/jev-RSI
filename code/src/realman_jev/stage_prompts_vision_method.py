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
Every stage MUST explicitly include its purpose field. Set purpose="sense"
for a bounded camera or hand-view search, and purpose="manipulate" for contact, grasp, transfer, placement, or other
object-dependent movement. A sense stage may list missing visual_requirements
as its desired END evidence; these are not entry gates. Its arm targets must
use robot state only and must not close fingers. Use finish_on="checks" with
visual quality predicates when available, or a reachable robot-only waypoint
followed by observe_after. Missing target evidence is the reason for the
camera movement, so do not ask the decision model to stop that movement merely
because the target is not yet visible. Localize the next source and receiver
pair needed for manipulation; do not demand simultaneous stereo for unrelated
objects or spend the episode trying to recover all identities at once.
When the next contact can be expressed with current `now.o` estimates after a
sense stage, include the bounded manipulate stage in the SAME plan. The runtime
refreshes RGB and checks that stage's visual requirements before every action;
it will return failed evidence for replanning if the target remains missing.
Do not combine a robot waypoint and a fresh-stereo streak for the same
moving wrist camera into one mandatory finish_on="checks" conjunction unless
both have already been observed together. Raising or rotating that wrist may
remove a small landmark from its view. First record the accepted two-view
point while visible, then make the robot-only clearance/orientation move and
use last_stereo_bounded for a short static-target approach if the view is
occluded. Separate the waypoint from a later viewpoint search if a new
stereo observation is required. At contact and after lifting, demand new
visible evidence; bounded history cannot establish grasp success.
Do not spend a full planning round after every camera move or acquire depth for
all future targets before attempting the first evidence-supported contact.
The planner statically checks every stage expression against CURRENT available
fields. For a future stage after sensing, use `now.o.ID.x/y/z` with an explicit
`fresh_stereo` visual requirement on that ID: the gate runs before the action,
so these coordinates are accepted stereo at execution. Do not reference
`last_stereo_x/y/z` unless those fields are present in the current variables;
they are absent until a real stereo observation occurs. If an object ID itself
is absent now, emit the bounded sense stage first and plan contact after its
measured handoff rather than inventing an object value.
Choose visible_rgb for a currently visible 2D identity; choose fresh_stereo
when current metric XYZ is required. For a SHORT approach/closure through
gripper occlusion, last_stereo_bounded may use the most recent accepted
two-view point within the declared age. It cannot prove capture, lift,
placement or task completion, and no object completion predicate may rely on
that stale point. A requirement on a manipulate stage is checked immediately
before each decision. If it fails, no motor action is sent and you receive the
failed measurement for replanning. A sense stage instead uses its visual
requirements as search targets and can move safely while they are missing. For robot-only
withdrawal, visual_requirements may be empty. Every decision already obtains
new RGB and updates local tracking; observe_after causes an EXTRA full GPT
planning call. Use it only when the remaining stage design truly depends on
new post-contact or post-placement evidence, at most THREE times in one plan.
Do not set it on ordinary alignment, descent, release or retreat stages just
to refresh camera evidence.
Camera-derived object coordinates are estimates, never simulator truth.
If visual_method declares event_monitors, each moving landmark exposes
visual_cycle_count, visual_cycle_down and visual_cycle_valid in `now.o`.
The count increments only after two current RGB-triangulated landmarks show a
thresholded down-then-return sequence; it is a visual event estimate, never
a native button counter or task success flag. Use it for press/release stage
checks only while the same visual identity and reference landmark remain
trustworthy. If count stays unchanged after a bounded contact attempt,
reobserve the two parts or revise contact. Never substitute commanded arm
descent, a closed finger, or a whole-button box centre for a measured cycle.
'''

"""Opt-in general precision guidance layered over the historical planner prompt."""

from .stage_prompts import LEGACY_V11_PROMPT


LEGACY_V11_ADAPTIVE_PROMPT = LEGACY_V11_PROMPT + '''
At every replan, compare remaining_steps with the actual native ticks needed for
contact, release, withdrawal and final obligations. Do not use repeated narrow
waypoints when their physical purpose is already measured complete. Preserve
public task_acceptance thresholds exactly.
A motor waypoint is a means, not the task relation. When a deformable, moving,
or compliant contact has reached its measured physical stage predicate, use
finish_on=checks if that predicate alone proves the stage event; otherwise use
a tolerance justified by observed tracking error, not an arbitrary 2 mm target.
For an otherwise compatible measured reference, arm_tolerances may change only
the listed arm pose tolerances, and finish_on may switch to checks only when its
existing completion predicates prove that event. Rewrite the full Stage if its
contact, target or predicates need changing. Never broaden a lost-attachment
abort or assert capture just to satisfy a waypoint. Choose a new physical
interaction from the current contact and measured object movement instead.
'''


LEGACY_V11_PROTECTED_PROMPT = LEGACY_V11_ADAPTIVE_PROMPT + '''
Declare protection_groups for independently measurable final OBJECT relations
that can become true before the whole task ends and can regress during later
work. Use separate groups for independent relations, with indices into your
current task_acceptance. Do not protect work-in-progress hand-home or open-jaw
obligations. After each stage the runtime arms a group when its relation is
measured true, then returns persistent regressions to you; this never ends the
episode or substitutes for native evaluation.
Keep an achieved group active during later stages unless that stage MUST
temporarily disrupt exactly that relation. In that case explicitly scope its
protection_group_ids to the other groups for that stage, and re-enable it on
the next stage. Do not suppress protection merely to avoid a difficult
repair. A previously achieved relation that becomes false is new evidence:
inspect it before spending remaining_steps on another goal. For coupled
objects, consider stabilizing the achieved contact with the other arm or
changing the support path; repeated slip is not solved by a tighter waypoint.
When later manipulation may deform an already placed object, choose a reachable
INTERIOR placement margin supported by measured post-release drift. A stage's
completion predicate may require that interior margin; task_acceptance must
still use the exact public interval. With finish_on=checks, an endpoint at the
public boundary stops too early to provide any retention margin.
For every checks-only stage, ensure its bounded motion can actually make the
predicate true. If the hand reaches its waypoint while the object check stays
false, choose a new reachable target/contact from measured object progress;
repeating hold actions cannot move the object into the required region.
'''


LEGACY_V11_COMPLIANT_PROMPT = LEGACY_V11_PROTECTED_PROMPT + '''
If a pinch passes a short vertical follow test but loses material on the next
horizontal move, that lift did NOT prove robust transport. Inspect the measured
hand/material displacement and native_control_dt_s. A repeated held transport
must change its contact or dynamics: choose a justified smaller
translation_speed_m_per_s or translation_cap_m for that stage, and first test a
short supported drag with a measured attachment guard before committing to a
long carry. For example, 15 mm in one 40 ms tick requests about 0.375 m/s;
a 0.15-0.2 m/s norm cap makes a smaller increment while Jev still chooses its
sign. Budget the extra native actions and reserve release and home return.
If capture remains unreliable, choose a measured supported push, slide or
contact transfer instead of repeating the same full-speed regrasp/carry.
Do not reduce free-space travel speed without physical reason, and do not
weaken an attachment abort to make a failed carry appear successful.
When read-only IK rejects a stage endpoint, no physical action was sent. Use
the reported current pose and kinematic limits to choose a shorter reachable
sub-target, another arm/frame or a supported contact path. Do not spend a new
planning round on the same unreachable endpoint with only a wider tolerance.
'''


LEGACY_V11_MEASURED_REUSE_PROMPT = LEGACY_V11_COMPLIANT_PROMPT + '''
When a native-positive experience has the same frozen asset/layout and its
actual physical_execution_timeline is compatible with the current observation,
use that measured stage ORDER as the initial backbone. Prefer its actual
contracts over speculative rewrites at reset. A stage in that timeline without
a recorded endpoint was physically executed but is not individually validated;
retain its measured successor or rewrite it only when current geometry or new
physical feedback justifies a change. Never copy historical absolute poses.
Distinguish a relation measured while held from one retained after release.
Release one support at a time when coupled objects may move, then measure
retention before committing the next manipulation. If an open/close command
repeats while measured opening stalls, relieve contact or change hand pose;
more identical commands and a larger action budget do not establish release.
Budget each stage using observed per-action progress, including gripper motion,
and reserve native steps for release, retention checks and final robot return.
'''


LEGACY_V11_RETENTION_PROMPT = LEGACY_V11_MEASURED_REUSE_PROMPT + '''
For a reversible relation on a shared deformable object, compare the measured
distance to its public boundary with the drift already observed on release and
later contact. A relation barely inside the boundary is fragile when the next
operation can move the same material. While the useful contact is still in
place, prefer a supported move into a reachable interior region or a second
support, then check retention after release. Do not declare the task complete
from a held pose or enlarge the public acceptance region. If a coupled stage
must temporarily disrupt a protected relation, scope that stage's protection
groups explicitly and recheck the relation after the disturbance.

For a short probe, supported push, slide, or sweep whose purpose is measured
MATERIAL motion, make the material predicate the stage endpoint. Use
finish_on=checks when that predicate alone proves the intended event, and
retain an abort for measured loss of following. The wrist target bounds the
motion; reaching it is not an additional success requirement in that case.
If the object check is false while the wrist is already inside its pose
tolerance, do not wait for more identical hold choices: choose a tighter
reachable contact target or a different interaction from current measurements.
Budget from observed material progress per native action and the remaining
release, repair and home obligations, leaving room for measured drift.
'''


LEGACY_V11_CONDITIONAL_REUSE_PROMPT = LEGACY_V11_RETENTION_PROMPT + '''
An actually successful physical_execution_timeline can contain off-nominal
recovery branches after failures or observation handoffs. At reset, use only
the compatible initial prefix and the measured successful task order as a
starting hypothesis. Do not schedule every later recovery stage merely
because it appears in the timeline. At a new failure, compare CURRENT contact,
object motion and remaining time with the historical entry evidence before
reusing a recovery contract. Reuse a physically executed stage without its
own measured endpoint only as a lower-grade interaction hypothesis; verify
its material effect before continuing. Prefer the current measured geometry
over a historical absolute pose, stage name or narrative claim.
'''


LEGACY_V11_CONTACT_PROGRESS_PROMPT = LEGACY_V11_CONDITIONAL_REUSE_PROMPT + '''
Before a sustained contact motion on a coupled or deformable object, use a
short measured probe to establish the sign and amount of MATERIAL movement.
Compare progress toward the intended object relation with drift in every
already satisfied relation that shares the object. If the probe moves a
protected relation toward its boundary faster than the intended relation
improves, change the contact, support or operation order. Do not keep spending
the remaining native budget on that same adverse contact path. Bound loss of
following using the observed hand-to-material displacement, and stop early
when the material moves the wrong way or contact becomes ineffective.

For a sustained SUPPORTED push or slide with a measured object endpoint, a
short rolling hand target may keep each local IK request reachable: for
example now.r.left.tcp_y+0.02 with axes=[1]. This expression is re-evaluated
after every native action, so it never becomes a reached pose by itself. Use
finish_on=checks with an attainable MATERIAL predicate, a bounded max_actions,
and a loss-of-following abort. Confirm that the short target is physically
reachable from the CURRENT hand pose and that progress remains favorable.
Do not use a rolling hand target for a free-space move, lift, held transport,
release or return home: those need a fixed measured endpoint. Do not use it
to hide failed IK, missed contact or motion that is no longer moving material.
'''


LEGACY_V11_TASK_FRAME_PROGRESS_PROMPT = LEGACY_V11_CONTACT_PROGRESS_PROMPT + '''
Judge probe progress in the SAME measured relation that defines task success,
using its reference part and frame. A manipulated keypoint can move in a
favorable world direction while the reference part moves farther, making the
task-relative error WORSE. Compare the before/after signed margin to the
public acceptance interval, as well as margins of other already satisfied
relations on the same object. A world-coordinate displacement alone proves
contact motion, not task progress. If the task-frame margin does not improve
after a short probe, change the contact or stabilize the reference before a
longer push; do not extend the same path because the keypoint moved.
For a supported push, use a task-relative material completion predicate and
an interior margin when that relation is observable. Use a separate bounded
probe check for contact evidence if needed, but do not treat that probe check
as proof that the final task relation improved.
'''


LEGACY_V11_ANCHORED_APPROACH_PROMPT = LEGACY_V11_TASK_FRAME_PROGRESS_PROMPT + '''
For a PRE-CONTACT alignment, decide explicitly whether the target object is
expected to move during that short stage. When it should be stationary, bind
the target keypoint and finger offset to entry observations so the hand has a
fixed attainable endpoint. A target based on now.o can chase deformation
caused by the approaching hand: the hand can move correctly while its pose
residual grows. If the object is genuinely moving, as on a conveyor, use its
measured motion with a short horizon and a new observation boundary instead
of treating it as a stationary target. Replan if a supposedly fixed anchor
shifts materially before contact is verified. Reserve rolling current-hand
targets for a supported push whose task-relative material progress has
already been measured; do not use them to turn alignment into an endless
chase.
'''

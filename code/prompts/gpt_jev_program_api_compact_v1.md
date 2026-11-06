# Exact compact runtime reference

Define main(api). Globals: np, math, geo. Allowed builtins: abs,all,any,bool,dict,
enumerate,float,int,len,list,max,min,range,reversed,round,set,sorted,str,sum,
tuple,zip,isinstance,type,Exception,RuntimeError,ValueError,print. No imports,
filesystem, network or other builtins. Source <=120000 ASCII chars. API inputs
and returned program data must be JSON-compatible; convert arrays with .tolist().
World positions are meters; world rotation vectors radians; quaternions xyzw.
Images are 768x768, top-left [u,v]. Cameras: agentview, robot0_eye_in_hand.
No hidden object state, task oracle, reset, or collision certificate is exposed.

## Sensing (does not advance physics)

api.state() -> frame_id,native_steps,budgets,tcp_position_world_m,
tcp_quaternion_xyzw,gripper_qpos_m,last_gripper_command,own_geometry.
budgets: gpt_remaining,jev_remaining,native_steps_remaining,wall_seconds_remaining.
own_geometry: pad_center_in_tool_m,pad_extent_in_tool_m,
finger_low_offset_tool_m,finger_high_offset_tool_m.
api.camera(camera) -> K,camera_to_world_opencv,frame_id.
api.point(camera,pixel,radius=3) -> world_m,depth_m,frame_id,pixel,camera,source.
radius integer1..6; invalid/discontinuous depth raises an error, no fallback pose.
api.cloud(camera,box,stride=6) -> world_m,rgb,pixels,frame_id,camera,box,stride,source.
box integer[u0,v0,u1,v1] within image; stride integer4..32. Samples include
occluders/background: the caller must validate surface identity/membership.
api.plane_point(camera,pixel,plane) -> world_m,pixel,plane,frame_id,source.
plane=[nx,ny,nz,d], n dot X+d=0, fitted/validated by caller. Calibrated ray
intersection does not establish selected pixel membership; grazing rays reject.
api.compose(quaternion_xyzw,rotation_delta_world_rad) -> quaternion xyzw.

api.review(question,context=None,fields=None) -> status(continue/complete/stop),
explanation,parameters,points,regions,measurement_errors,frame_id.
This consumes one real GPT call with fresh images. All generated methods MUST
declare fields for branch-critical parameters: dict name -> "boolean"/"number"/
"integer"/"string", a list of string enum choices, or strict JSON Schema with
type/properties/items/enum/description/minimum/maximum/minLength/maxLength/
minItems/maxItems. All fields required; no implicit coercion or extra properties.
Use explicit unknown enums or nullable types. Max32 fields,depth8,256 nodes.
Ask explicitly for named measurements: max32 points,8 regions. Point requests
use camera,pixel,radius; regions camera,box,stride4..32. Returned points/regions
are dictionaries name -> point/cloud receipt. Failed names are omitted and
listed as {name,error} in measurement_errors; inspect membership before indexing.
Only this call's measurements are returned; historical labels are not merged.
parameters are model interpretations, not independent sensor truth. Persist
same physical landmark identity across camera motion. Supplied context can
contain your numerical references; excerpts may omit data and must not be
treated as complete history. Reviews cannot read source or hidden evaluator state.

api.track_init(camera,polygon) -> handle,reference_features,frame_id plus provenance.
polygon3..16 vertices on an identified textured RGB-D surface; needs >=12 valid
features. Max32 handles; they persist through source repair in this episode.
api.track_update(handle) -> status tracked/unknown,frame_id,reference_frame_id.
tracked additionally provides transform_initial_world_to_current_world(4x4),
camera,matches,inliers,rms_m,inlier_spread_m,uncertainty_floor_m,
reference_inlier_world_m,current_inlier_world_m,
reference_patch_centroid_world_m,current_patch_centroid_world_m.
unknown has reason/candidates/source but NO transform or pose. Validate identity,
rigidity,coverage and error; tracking alone is not retention. Apply the rigid
transform to points; its translation column is not displacement under rotation.
Appearance keyframes can grow from observed registration; uncertainty is heuristic.

## Pure geometry (no sensing or robot skills)

geo.rotation(quaternion_xyzw) -> tool-to-world3x3.
geo.transform(points,matrix) -> transformed Nx3 points, proper rigid4x4 matrix.
geo.pad_position(state) -> world pad center.
geo.plane(points) -> coefficients[nx,ny,nz,d] toward+z,center_world_m,rms_m,
in_plane_spread_m(two values); needs>=3 noncollinear points.
geo.circle_xy(points) -> center_xy_m,radius_m,rms_m,max_radial_error_m,
largest_angular_gap_rad; needs>=3 noncollinear XY/XYZ points. XY fit only;
caller validates horizontal model and actual inner/outer boundary identity.
geo.attachment_error(points_before,points_after,state_before,state_after) ->
maximum discrepancy(m) from TCP-predicted rigid transform for corresponding
measured landmarks; not a grasp label. Fits may reject inadequate inputs.

## Jev and physical execution

api.control(target,quaternion,gripper,questions,features=None,tool_point="tcp",
 translation_limit=0.02,rotation_limit=0.10,steps=3,
 position_tolerance=0.006,rotation_tolerance=0.06)
target world3-vector,quaternion xyzw,gripper open/close/keep,tool_point tcp/pad_center.
Limits: translation0.001..0.02m,rotation0.01..0.10rad,steps integer1..3,
position_tolerance0.0005..0.012m,rotation_tolerance0.01..0.10rad. Target <=0.6m.
Every update calls real Jev; its unchanged axis/gripper choices are dispatched.
questions EXACTLY x,y,z,rx,ry,rz,gripper; each is
{"type":"choice","instructions":"...","criteria":{"option":"meaning"}}.
Axis options negative,hold,positive; gripper options open,close,keep.
Explicitly bind each question to its feature selector. Jev wire state includes
robot=state(),processed_features.program=features,objective.gripper/tool_point,
translation_error_world_m,rotation_error_world_rad,axes.<axis>.error/goal_relation.
goal_relation is increase/decrease/within_tolerance. Positive increases world
coordinate or world rotation-vector component. Magnitude is bounded absolute
residual feedback, zero within tolerance/sqrt(3); vector L2 limits also apply.
Caller features stay fixed within a lease. Jev is text-only, not a numeric sensor.
Returns status reached/moved/stalled,choices,before,after,target_tcp,
position_error_m,rotation_error_rad,native_steps,acknowledged_steps,frame_id.
before/after/target_tcp are world TCP3-vectors, NOT full state dictionaries.
reached checks measured robot pose and delivered gripper command, NOT object effect.
api.drive(target,quaternion,gripper,questions,features=None,max_calls=30,**limits)
uses the same api.control loop, real Jev every update; max_calls integer1..40.
Stops on reached,three consecutive stalled updates or lease limit. Last receipt
plus lease_calls; status reached/stalled/lease_exhausted. before/after cover only
the last update: save api.state() before lease for whole-lease progress.
api.choose(questions,features) -> choices,frame_id. Real Jev text branch decision,
zero motion; <=8 questions,2..8 options each with explicit feature binding.

## Persistence and budgets

api.checkpoint(key,value) -> key,frame_id,method_number,source_sha256,bytes,source.
key1..64 ASCII letters/digits/underscore/dot/hyphen; <=16 keys,16384 bytes/value,
131072 bytes total. Overwrite permitted. Save compact evidence, not whole reviews.
api.recall(key=None) -> metadata list; with key -> metadata PLUS value. Unknown
key raises. Checkpoint values are historical caller assertions, not fresh truth.
Track handles persist in host, Python locals do not survive source replacement.
api.note(text),print(...) -> bounded trace via RPC.
All loops finite. Errors reach supervision. Total GPT/Jev/step budgets include
repairs. Control slices may pause and resume the same live stack; do not replay.
Different sensing can recover locally, but repeated failures have bounded limits
and unresolved repeated sensing errors require supervision before actuation.

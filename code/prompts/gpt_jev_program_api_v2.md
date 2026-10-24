# Program runtime v2: exact API

The host owns the LIBERO OSC_POSE environment. Images are current 768x768 RGB,
top-left pixel origin. Depth and calibration support metric backprojection.
Robot state is proprioception and own finger geometry only. World units are m,
rotation vectors rad, quaternions xyzw. Nothing exposes hidden object state.

Available globals: np, math and ordinary Python builtins; define main(api).
The complete source limit is 120000 ASCII characters; all helpers must resolve.
Return completion_proposed as a boolean and evidence as a JSON-compatible object
or list. A list of diagnostic log entries is supported by the repair interface.
All API arguments/results are JSON-compatible: use ndarray.tolist() at boundaries.
print(...) and api.note(text) write bounded trace notes through host RPC.

## Observation and geometry

- api.state(): frame_id, native_steps, budgets, tcp_position_world_m,
  tcp_quaternion_xyzw, gripper_qpos_m, last_gripper_command, own_geometry.
  own_geometry contains pad_center_in_tool_m, pad_extent_in_tool_m,
  finger_low_offset_tool_m and finger_high_offset_tool_m.
- api.point(camera, pixel, radius=3): current visible surface point as
  world_m, depth_m, frame_id, pixel, camera, source. camera is agentview or robot0_eye_in_hand.
  pixel=[u,v]; radius 1..6. Invalid/discontinuous depth raises an error.
- api.camera(camera): current K, camera_to_world_opencv, frame_id.
- api.plane_point(camera, pixel, plane): intersect the calibrated current pixel ray
  with a program-supplied world plane [nx,ny,nz,d], n dot X + d = 0. Returns
  world_m, pixel, plane, frame_id and an explicit derived-source label. Rejects
  grazing, behind-camera and out-of-range intersections. Fit/validate the plane
  from actual visible measurements first. This can support visible boundary
  landmarks whose depth patch mixes surfaces; it does not prove that a selected
  pixel belongs to that plane or reveal a hidden object boundary.
- api.cloud(camera, box, stride=6): sampled visible surface points world_m,
  corresponding rgb and pixels, frame_id, camera, box, stride, source.
  box=[u0,v0,u1,v1], integer image bounds.
  stride 4..32. Includes background/occluders; no object isolation is implied.
  Process it yourself; geometric extrema need validity checks.
- api.compose(quaternion_xyzw, rotation_delta_world_rad): compose a world
  rotation-vector delta with a quaternion; returns quaternion xyzw.
- api.track_init(camera, polygon): initialize a generic textured RGB-D surface
  patch tracker on a currently visible 3..16 vertex polygon. Returns handle,
  reference_features and frame_id; at least 12 textured depth-valid features are
  required. Up to 16 handles per method; handles reset for a repaired method.
- api.track_update(handle): compare the reference patch with both current views
  using SIFT descriptors, depth backprojection and robust rigid registration.
  Returns status tracked or unknown. tracked includes a 4x4
  transform_initial_world_to_current_world, camera, frame_id (current observation),
  reference_frame_id (initial observation; there is no current_frame_id field),
  matches, inliers, rms_m, inlier_spread_m, uncertainty_floor_m, and reference/current
  inlier world points (reference_inlier_world_m, current_inlier_world_m) and patch
  centroids (reference_patch_centroid_world_m, current_patch_centroid_world_m).
  Apply the rigid transform to a point
  to obtain its position: its translation column alone is not point displacement
  when rotation is present. unknown provides no pose estimate. No physics advances.
  This tracks a caller-selected textured surface, not a named object oracle.
  Validate identity, rigidity, feature coverage and uncertainty before using it.
  Partial occlusion may still leave enough correspondences; total occlusion or
  insufficient texture yields unknown. unknown returns frame_id, reference_frame_id,
  reason, candidates and source, but no transform or pose estimate. A transform alone does not certify a grasp.
  Comparing observed patch motion with measured hand motion can support retention
  tests without requiring every object perimeter corner to remain visible.
- api.review(question, context=None): obtains fresh images and a real GPT observation review.
  Each review supports at most 32 named points and 8 named regions. Request only
  the measurements needed now; use additional reviews when a valid view is missing.
  Returns status (continue/complete/stop), explanation, parameters (dict),
  points (dict name -> api.point result), regions (dict name -> api.cloud result),
  frame_id. Specify the needed visible evidence and named measurements explicitly.
  Parameters are a model interpretation, not independent sensor certification.
  Named region requests have explicit camera, box and stride fields; stride is
  4..32. Arbitrary region_strides inside parameters are not executable requests.
  Review sees previous review images, your question, current state, and receipts.
  It does not read your source or invent a new API. Every review uses GPT budget.
  Optional context is your JSON-compatible reference geometry, label definitions,
  or other needed program state. Historical initial/previous label annotations
  are also retained within the current method execution, together with current
  camera projections of previous world points under a stationary-point hypothesis.
  These projections are reference aids, not tracking detections or current poses.
  Physical landmark IDs must persist across camera motion; screen upper-left is
  not a stable identity. Reference annotation scope resets for a repaired method.

## Real Jev and bounded physical action

api.control(target, quaternion, gripper, questions, features=None,
            tool_point="tcp", translation_limit=0.02, rotation_limit=0.10,
            steps=3, position_tolerance=0.006, rotation_tolerance=0.06)

target is a desired world point. quaternion is the desired tool orientation xyzw.
tool_point is tcp or pad_center (host subtracts the rotated own pad offset).
gripper is open/close/keep. This requirement is sent to Jev; the actual gripper
choice is dispatched unchanged. Features is your JSON-compatible processed state.
The host adds trusted current robot state, pose residuals, and axis relations.
Each translation/rotation vector is L2-limited; translation_limit 0.001..0.02,
rotation_limit 0.01..0.10. A decision executes 1..3 native steps. A goal farther
than 0.6m is rejected. No object collision certification or grasp is implicit.
position_tolerance accepts 0.0005..0.012 m; rotation_tolerance 0.01..0.10 rad.
Tighter tolerances do not certify physical accuracy or successful convergence;
they can require more decisions, and every controller still has bounded budgets.

questions is a dictionary with exactly x,y,z,rx,ry,rz,gripper. Each value is:
{"type":"choice","instructions":"...","criteria":{"option":"meaning",...}}.
The six axis keys have exactly negative,hold,positive; gripper has open,close,keep.
You author instructions and criteria. The host maps negative/hold/positive to
-1/0/+1, times bounded magnitudes derived from absolute pose residuals. Positive
means increasing world coordinate or positive world rotation-vector component.
Host axis relation is increase/decrease/within_tolerance. The host does not fix
Jev's answer. Inputs include controller limits and a source-labelled feature dict.

Exact wire state: {"robot": <state()>, "processed_features": {"program": <your
features>, "objective": {"gripper": ..., "tool_point": ...},
"translation_error_world_m": [...], "rotation_error_world_rad": [...],
"axes": {"x": {"error": ..., "goal_relation": ...}, ...}}, "feature_source": ...}.
The compiler prefixes each control question with its explicit
state.processed_features.axes.<axis>.goal_relation selector (and the objective
gripper selector), then appends your instructions and preserves your criteria.
Question names alone are labels, not sufficient semantic bindings. Full compiled
requests and unchanged answers are archived. No answer is silently corrected.
Jev does not see the question ID at all: each question is evaluated from its
instructions/criteria against state. Therefore all custom api.choose questions
must state their subject and relevant feature fields explicitly as well.
Source: https://docs.typesafe.ai/primitives/choice (request structure).
The numerical controller uses a per-axis deadband of the respective pose
tolerance divided by sqrt(3): magnitude is zero inside it, including when Jev
selects a nonzero sign. Outside it the signed bounded residual rule applies.
This is declared magnitude computation, not a substituted Jev direction.

Returns status (reached/moved/stalled), choices, before, after, target_tcp,
position_error_m, rotation_error_rad, native_steps, acknowledged_steps, frame_id.
reached uses measured post-action pose and commanded-gripper delivery only.
It does not prove any object effect. status=stalled means negligible translation
despite a nontrivial translation residual; verify your objective before retrying.

api.drive(target, quaternion, gripper, questions, features=None, max_calls=30,
          **controller_limits)
is an optional generic local feedback lease using exactly the same control
interface. Each update still calls real Jev with current robot residuals and
dispatches its answer unchanged. It stops on reached, three consecutive stalled
updates, or max_calls (integer 1..40). Returns the last receipt and lease_calls;
status is reached, stalled, or lease_exhausted. It does not choose task phases,
verify object effects, retry a grasp, or perform recovery. Program-authored
features remain fixed within this lease; use individual control calls if those
features must be recomputed each update. All normal episode budgets still apply.

api.choose(questions, features): real Jev choices for finite local branch decisions.
Each question uses the same type/instructions/criteria shape. At most 8 questions,
2..8 options each. Returns choices and frame_id. It executes zero robot steps.
Never treat it as an image observation: Jev receives structured text features.

## Persistence, failure and budgets

- api.checkpoint(key, value): retain caller-owned JSON data across method repairs
  in this physical episode. key is 1..64 ASCII letters, digits, underscores, dots
  or hyphens. At most 16 keys, 16384 bytes per value and 131072 total value bytes.
  Overwriting a key is allowed. Returns key, frame_id, method_number,
  source_sha256, bytes and source. The host adds these provenance fields; it does
  not certify the content. Store only useful measurements, assumptions,
  uncertainties, landmark identities and acknowledged phase evidence.
- api.recall(key=None): without a key, return a list of checkpoint metadata;
  with a key, return that record plus value. Unknown keys raise an error. The
  planner sees the metadata manifest, not every value automatically. Memory is
  empty in a new episode and is never loaded from an archived method. Stored data
  are historical program assertions, not fresh observations or native success.
  Revalidate identity, stationarity and dependencies before reuse. Tracker handles
  and Python objects are not preserved by storing their names in JSON.

Every physical control request invokes Jev and every native step has a receipt.
State and measurements change only after actual motion. Scene geometry can become
stale after any motion. Python in one submitted method persists until return;
a repaired method starts a fresh Python namespace in the same physical scene.
No reset exists. All loops must be finite. Invalid calls raise RuntimeError.
The host enforces total GPT/Jev/native-step/wall budgets across repairs and reviews.
Stop with an incomplete result if needed evidence or resources are unavailable.

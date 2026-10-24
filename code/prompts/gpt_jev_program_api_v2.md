# Program runtime v2: exact API

The host owns the LIBERO OSC_POSE environment. Images are current 768x768 RGB,
top-left pixel origin. Depth and calibration support metric backprojection.
Robot state is proprioception and own finger geometry only. World units are m,
rotation vectors rad, quaternions xyzw. Nothing exposes hidden object state.

Available globals: np, math and ordinary Python builtins; define main(api).
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
- api.review(question): obtains fresh images and a real GPT observation review.
  Each review supports at most 32 named points and 8 named regions. Request only
  the measurements needed now; use additional reviews when a valid view is missing.
  Returns status (continue/complete/stop), explanation, parameters (dict),
  points (dict name -> api.point result), regions (dict name -> api.cloud result),
  frame_id. Specify the needed visible evidence and named measurements explicitly.
  Parameters are a model interpretation, not independent sensor certification.
  Review sees previous review images, your question, current state, and receipts.
  It does not read your source or invent a new API. Every review uses GPT budget.

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

Every physical control request invokes Jev and every native step has a receipt.
State and measurements change only after actual motion. Scene geometry can become
stale after any motion. Python in one submitted method persists until return;
a repaired method starts a fresh Python namespace in the same physical scene.
No reset exists. All loops must be finite. Invalid calls raise RuntimeError.
The host enforces total GPT/Jev/native-step/wall budgets across repairs and reviews.
Stop with an incomplete result if needed evidence or resources are unavailable.

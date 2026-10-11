# Server GPT-6 assignment: design AND implement structured observation adapters for Jev

You are the explicitly requested GPT-6 implementation worker running on company-server-2.
Write executable production candidate code with write_generated, not just advice.
The supervisor will review, run bounded simulator tests, return failures, and ask you to revise.

Tasks: general_pickup, fold_clothes (including randomized variant), press_by_number,
match_and_pick_from_conveyor, stack_bowls (including randomized variant).
These are the five strongest official GPT-6 task families excluding previously tested stack_blocks.
Include stack_blocks as an optional sixth adapter for a strict-ranking interpretation.
Target: exceed 20% native full-task success per family, then freeze code and collect extensive Jev judgments.
Do not promise this outcome; report uncertainty. No cherry-picking successful initializations.

## Information boundary

Retain RGB-D + calibrated cameras + robot proprioception permissions from prior experiments.
NO object simulator pose, scene layout, asset size, semantic simulator segmentation, reward state,
hidden task answer, scripted native solution, oracle RPC, or audit file in online policy.
Task language is allowed. Native success/score only in external evaluator. Historical ground-truth
direction scores may calibrate an offline prior but cannot enter online state.
Do not read task implementation/reward code. Do not install anything, change drivers or external files.
Use NumPy/SciPy/OpenCV/PIL and the existing GroundingDINO+SAM2 RGBEvidence module if helpful.

GPT-6 must design observation schemas and write code. Runtime GPT-6, if essential for OCR/semantic
perception, may extract visible labels/2D keypoints only; NEVER output waypoints, directions, stages,
gripper actions or a solution sequence. Keep those distinct from actual Jev decisions; log perception
costs separately. Prefer deterministic RGB-D geometry for coordinates. No hard-coded layout positions.

## Deliverables and exact runtime interface

Write DESIGN.md and controller.py (plus local helper modules if needed). controller.py exports:

class Controller:
    def __init__(self, task: str, settings: dict): ...
    def step(self, observation: dict, ask_jev, perceive) -> dict: ...

observation is JSON-compatible except images/arrays:
{
  'native_step': int,
  'instruction': str,
  'remaining_steps': int,
  'cameras': {name: {'rgb': uint8 HWC, 'depth_m': float32 HW,
      'intrinsic': 3x3, 'camera_to_world_opengl':4x4}},
  'env_origin': xyz,
  'robot': {'states':14-vector (6 joints+gripper each arm),
      'eef_positions':2x3 link6 positions relative to env origin,
      'eef_quaternions_wxyz':2x4},
  'gripper_bias_m': [left,right],
  'previous_execution': dict or None
}
Nominal grasp center = eef_position + R(eef_quaternion)*[gripper_bias,0,0].
World-frame RGB-D lifting uses optical Z, OpenGL flip [1,-1,-1], then camera transform minus env_origin.

ask_jev(state: dict, questions: dict) returns the native raw response:
{'model':'jev-1.13.0','answers': {question_id: {'type':'choice','choice':str,
 'confidence':float,'probabilities':{choice:float}}}}.
Each question is {'type':'choice','instructions':str,'criteria':{choice:description}}.
Jev should receive structured numeric/symbolic visual observations, explicit subtask/stage, history,
visibility/uncertainty, robot feedback, constraints. You design at least two selectable schemas
(numeric geometry vs relational/uncertainty structured version), with identical observation permissions.
Jev chooses x/y/z negative/hold/positive; optional stage/gripper/arm decisions must be separate named
questions, not silently attributed to translation accuracy. NO translation computed purely from error
signs while bypassing Jev. External nonnegative per-axis amplitudes and deterministic phase scaffold
are allowed, but each must be documented and logged. Model hold stays zero; do not flip signs.

perceive(prompt: str, observation: dict) returns parsed JSON from a restricted GPT-6 vision call.
Use it only if required. Its prompt must request visible scene measurements, not action planning.
Define exact output JSON fields in your prompt. Never request or assume access to physical truth.

step returns:
{
  'stage': str,
  'arms': {'left' and/or 'right': {
       'delta_xyz_m':3-vector (nominal grasp-point DELTA relative to current observed grasp point),
       'quaternion_wxyz':4-vector (target world-frame orientation),
       'gripper_opening':float 0..1}},
  'ticks':int 1..15,
  'stop':bool,
  'reason':str,
  'debug': JSON-serializable dict (estimates, targets, provenance, uncertainties, state transitions,
      Jev signs, per-axis amplitudes, stale measurements, evidence for phase progress)
}
The runner executes bounded IK commands, leaves inactive arms fixed, saves all RGB-D/native metadata,
requests/responses/commands, and evaluator-only native result. Per action norm limit=40mm per arm,
native step budget unchanged, max 180 Jev calls per episode, per-run wall limit 20min/disk 800MB.
For rotation/gripper-only steps still log the external rule and evidence; do not claim Jev moved it.
Return stop if missing/ambiguous observations cannot be recovered; never declare native success yourself.

settings contains {'gpu': int, 'existing_root': path, 'schema_variant':'numeric'|'relational',
 'max_step_m':0.04,'position_tolerance_m':0.005,'seed':int,'run_dir':str}.
Your code must not read credentials; callbacks handle API transport. Never write external files.
Keep history bounded and use after-action observations to verify grasp/press/fold progress.
Rigid static-goal convergence assumptions do not apply to moving conveyors or cloth: document limits.

## Prior evidence to use critically

Old oracle stack success 20/20 is NOT visual evidence. Old RGB-D approach failed from IoU identity loss.
37/37 required-motion axes correct and 2 true-hold axes falsely moving, only 13 correlated visual steps.
Accuracy is not a calibrated model confidence or guarantee. Allow axis dead zones/uncertainty and
explicit finite-lived visual memory; do not call a predicted carried pose an observed grasp.
There is a candidate ReliabilityStep module, but choose and justify a simple stable baseline first.

Review the allowed interface files as needed, then implement all adapters. Prioritize general_pickup
and press_by_number for the first simulator debug. Provide a precise list of untested assumptions.
Do not create permanent test scripts; the supervisor will run inline checks and real integration tests.


REVISION BASED ON REAL PILOT AND CODE REVIEW
Read all reference-generated v1 source and DESIGN; write a complete v2 candidate retaining all five tasks and both schemas. Make focused fixes rather than redesign. Actual general_pickup public instruction: Pick up the mint green scissors by 10 cm. v1 hardcodes lift=.075m and finishes after verified lift; this is incompatible with the public requested 10cm. Parse public instruction lift heights/units, define target object displacement and a visual verification margin compatible with the request, and handle unsupported numeric language explicitly. Never read task success code or ground truth.
First real rollout ended before action: gpt-6-astra visual response claimed completed but had one missing JSON brace. Harness now enforces json_object and 8000 max output tokens, passes the public instruction, and accepts empty-arm hold. Do not silently fabricate missing measurement data. Review image prompt complexity and validity handling. We need practical bounded 200-native-step general_pickup control; external grasp orientation and amplitude rules must be explicit. Keep fresh Jev signs as the sole source of any nonzero XYZ direction. Controller methods may not call reward or hidden geometry.
The existing runtime source is allowed read-only via read_source. Output full controller.py, visual_evidence.py, __init__.py and concise DESIGN.md describing changes and limitations. No test scripts.

ADDITIONAL MEASURED RGB-D REPLAY FAILURE (no simulator truth): after strict JSON fix, v1 stays select: instruction does not uniquely identify visible candidates. Two camera views of the same mint green scissors produce visible-surface medians [0.3878405,-0.0328919,0.7739056] (right wrist) and [0.3949905,0.0272988,0.7738087] (head); both uncertainty estimates around3mm. They differ60mm along long scissors because cameras see different surface regions. Fixed25mm centroid association incorrectly splits the same object into two equally scored identities. Fix multi-view association or use an explicitly selected reference camera with secondary views for reacquisition; do not arbitrarily merge true duplicate instances. Object visible-surface centroid is not a viewpoint-invariant object pose. Allow task-language disambiguation and target-keypoint estimation robust to elongated shapes without hidden geometry. Test this logic mentally against the actual public scissors instruction and all five task families.

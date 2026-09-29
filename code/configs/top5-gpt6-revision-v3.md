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


TARGETED REVISION: START FROM STABLE top5_v1
Use copy_reference to copy the four v1 files into the NEW candidate root, then patch_generated for focused changes. Avoid rewriting the entire implementation. You have 32 rounds. Retain proven interface and camera flow. Do not add test scripts. Read original files.
Real public instructions from RGB-D environment capture, not reward/layout:
- general_pickup: Pick up the mint green scissors by 10 cm.
- fold_clothes: Fold the clothes neatly.
- press_by_number: Press the two red buttons the required number of times according to the number cards, then press the blue button to confirm.
- match_and_pick_from_conveyor: Remember the first object on the conveyor, then pick the matching object when it appears again.
- stack_bowls: Stack the three bowls together.
These task semantics MUST drive stages. Press is counts associated visually with two red buttons, followed by blue confirmation, NOT sorting numbered buttons. Conveyor requires temporal first-object memory and disappearance/reappearance, NOT choosing a reference picture; initial empty conveyor is normal and requires bounded hold/observe. Never use hidden answers. Keep all five adapters.
Measured failures:
1. First general pilot stopped at0 steps because visual JSON missed closing brace. Harness now text.format=json_object,max_output_tokens8000 and public instruction supplied; real replay returned valid JSON. Do not silently fabricate missing values; allow bounded observation recovery.
2. v1 replay split same scissors across head and wrist views into two tied identities. Their visible-surface medians were [0.38784,-0.03289,0.77391] and [0.39499,0.02730,0.77381], 60mm apart along long shape. Use one explicitly selected reference camera for identity/control, secondary views for documented reacquisition; avoid viewpoint-dependent centroid merging. Make sure the actual measurement loop ONLY processes chosen camera on refresh as well as flow steps. Preserve optical flow or reobserve; NEVER label stale image polygons on moving objects/cameras as fresh current measurements.
3. v1 lift75mm contradicts public100mm. Parse requested displacement units and set target with a measured-error margin; validate actual visual object displacement, not gripper alone. No complete claim on80mm when instruction100mm.
4. A rejected intermediate draft accidentally included mint green scissors in STOPWORDS. Keep all task-relevant nouns, colors and shapes available for semantic matching. Do not hardcode target words or object positions.
Maintain fresh actual Jev axis signs for every nonzeroXYZ; no compute-sign fallback. Native step budgets fixed, general200. Avoid spending entire phase32steps just rotating: bounded orientation and translation schedules with explicitly separate rotation control are permitted. Runtime GPT6 only visual measurements. Support missing visible required facts with logged hold/reobserve and bounded fail, not ground truth.
The supervisor will replay actual saved measurements and images before fresh rollouts. Your final DESIGN should clearly state what you cannot verify without live tests.

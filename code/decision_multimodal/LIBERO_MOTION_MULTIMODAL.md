# LIBERO multimodal retest with explicit motion descriptions

## Fixed conditions

User-authorized2026-10-17. Ten existing Goal tasks, first three paired initial
states in each frozen manifest:30 episodes per condition,90 in total.
Actor: du gpt-6-luna Decisions. Existing local Pro gpt-6.1-sol/high reviews the
input contract. No runtime planner actions, experience injection, privileged
object pose, contact, reward or success input. Native evaluation remains separate.

| Profile | XYZ feedback | Images | Camera matrices sent |
|---|---|---|---|
| libero-rgb-motion-full-v1 | Retained | Raw RGB | No |
| libero-rgb-motion-marker-v1 | Removed | White control ring + yellow phase-target cross | No |
| libero-rgb-motion-axes-v1 | Removed | Same markers + camera-oriented world-axis compass | No |

All conditions include the identical verified English motion description in
`libero_robot_actions_v1.txt`. This describes native world rotation-vector
channels with explicit yaw/pitch/roll aliases; it does not introduce a new
Euler controller. XYZ questions use the short original Jev template, replacing
only their evidence phrase. The full condition reads observed error and RGB;
both reduced conditions read RGB. Choice values/descriptions, latest stable
stage contracts, gripper/transition/rotation/candidate questions are common.

Reduced state removes `translation_axes`, named position errors, axis relations,
distance/progress-to-goal, and numeric world/coordinate/centre/bounds fields.
Executed robot feedback, phase contracts and other non-positional feedback are
retained. This is a positional-feedback ablation, not removal of all processing:
rotation residuals, stage booleans, candidate descriptions and internal motor
scaling still exist. Deleted fields are not reintroduced in axis questions.

Camera K/T is used only inside the frontend to project the original target and
control-point markers, and to orient a goal-independent world-axis compass.
No camera matrix, image path, hash or camera numerical pose is added to the
model context. The context carries named views and current robot position and
gripper joint positions. A recursive outgoing-request assertion rejects K/T
keys, including encoded JSON text parts. Every actual request is saved.

## Image treatment

Two synchronous current views: agentview fixed external; robot0_eye_in_hand
moving wrist. Native768x768 RGB pixels are preserved. All three conditions add
the same160px footer (768x928 total), preventing the axis condition from
covering scene content or changing scene scale relative to the marker control.
The axes condition draws a camera-oriented free-vector compass in this footer:
red+X, green+Y, blue+Z; a dot indicates mainly toward the camera and a cross
mainly away. It is an orientation legend, not a metric pixel-motion predictor,
not a target-dependent arrow, not a numerical error, and not a grasp permission.
No scene object state or target enters this compass calculation.

## Execution and record keeping

company-server-2 physicalGPUs4-7 only, existing native/vision environments.
All bulk assets remain under the existing project worktree's `code/runs/` on
its existing mount. No/tmp, installations, environment permission or driver
changes. Separate output roots for each condition; source hashes pin the new
module, motion text, adapters, runner and frozen task policies.

Run an initial bounded native wave to inspect real outgoing requests and
resource use, then resume that same frozen campaign to fill the remaining
paired cases. Do not rerun a normally failed answered episode. Transport/schema
errors remain separate; any authorized connection replacement needs explicit
source provenance and a new output root. Native and program completion are
reported separately. Do not compare a first-decision agreement with task success.

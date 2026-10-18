# Genuine RGB per-axis manipulation — 2026-10-19

## Boundary

Actor gpt-6-luna uses only the authorized du /v1/decisions API. Planning uses
local ChatGPT Pro gpt-6.1-sol/high. No Responses/Chat API use is authorized.
All actual model text and examples are English. Experience is collected, not injected.

The actor chooses positive/negative/hold for XYZ and world rotation-vector
components roll=X, pitch=Y, yaw=Z, plus gripper and coarse/fine scale. No
precomputed scene target, pose residual, ranked action, angle dial or correctness
label enters its input. No scene-pose/contact/reward reads are permitted in the
policy. Native evaluation is queried only after the rollout and never sent back.

RoboDawn-inspired examples pair real before/after camera endpoints with measured
own-robot action effects. Source is the six independent native LIBERO motion
demonstrations already collected on 2026-10-17. These are interface examples,
not same-task expert trajectories or an exact reproduction of RoboDawn.
Reference: https://github.com/Hugo-AGI/RoboDawn/blob/main/harness/README.md

Own-gripper world-axis overlays are permitted. All scene relations and desired
grasp orientation are chosen by the actor. Low-level OSC tracks the relative
pose selected by the actor; its feedback is own-robot target tracking, not an
object-goal oracle. A single world rotation vector executes all chosen axes.

## First development condition

LIBERO stove1383/init8, 512px external/wrist RGB, six measured action examples,
previous observation and last four executed action effects, Pro semantic plan.
No automatic stage predicates: actor decides whether visible exit is met.
Coarse20mm/10deg, fine4mm/2deg, norm caps30mm/0.25rad per decision.
Four physical feedback steps per movement, total600 including10 settling steps.
Maximum180 decisions and1800 seconds; no confidence-based resampling.

First one renderer on physical GPU4; require1400MiB free, measure before any
concurrency increase. GPUs4-7 only. Other users' processes are never interrupted.
No driver or environment changes. Source and assets remain on the existing
authorized project mount. Every attempt, including startup errors, is retained.

## Validation and next iteration

Development failures diagnose target interpretation, axis grounding, stage
transition, visible grasp and execution tracking separately. Improvements may
add actual demonstrations/crops, own geometry or nonprivileged perception, but
must not compute the desired action and have the model repeat it. Stable means
native success and completed program in all three predeclared initial states
under a frozen condition, not three selected successes from retries.

The user replaced stacking blocks with a medium pick-and-place task on
2026-10-19. The second task is LIBERO1458, wine bottle onto a sloped rack,
development init11 and fixed validation inits11/12/13. The knob development
init8 and validation inits8/9/10 remain. Do not launch RoboDojo stack_blocks.

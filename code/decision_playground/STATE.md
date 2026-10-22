# Playground continuation state

Updated:2026-10-22. Read AGENTS.md, EXP-2026W43-007 and real processes first.

## Ownership / phase

SSH company-server-2-ykj (JcbotIns), user ykj.
Remote repo /home/ykj/project/jev-rsi-roboicl/.worktrees/decisions-playground-20261022.
Baseline/interpreters /home/ykj/project/jev-rsi-roboicl/baseline/roboicl.
Native/worker code905403e6 committed, SSH-pushed and Git-bundle deployed.
No active owned native or policy worker after development review stops.
Latest i campaign: code/runs/playground-waypoints-policy-20261022i.
Native264069 / worker298786 verified exited, GPU4/RPC25404.
Ended episode8a593e50-7990-4391-b85b-1106c3362c1f, r000,3HTTP200/13native steps,
last command sequence0 stop. Never restore this episode or replay its requests.
Next: bounded zero-API runtime execution diagnosis, not more prompt variants.

## Transport

Owned local SSH ControlPath:
/home/ykj/project/gpt6/CVPR/jev-rsi/jev-RSI/code/runs/c2-proxy-20261022.ctl

Remote127.0.0.1:17897 -> local127.0.0.1:7897; remote original7897 untouched.
Upper/lower HTTP(S)/ALL proxy variables are process-scoped.
Only du /v1/decisions; no ordinary API, caz/z, or extra API probes.
Actual calls c30+e18+i3=51HTTP200; b failed initial request preserved separately.

## Execution correction

Playground bypassed baseline rollout installation of default IKContinuityGuard.
At e step89 raw targets near +2pi/+2pi/-2pi caused unintended motion; this is
adapter execution contamination, not a model-direction failure. Preserve
e/execution-contamination-audit.json and original targets/media.
Commit2d71f385 restores the original shared_harness guard, enabled/.15rad.
Observer remains one-call/transparent. Refusal dispatches neither arm nor gripper,
consumes no step, preserves accepted prefix and discards suffix without retry.
Worker immediately reviews; controller_event stays outer-only.

Condition tcp-slerp-waypoints-v1 (905403e6) predeclares five TCP-linear/shortest-arc
rotation subtargets from initial measurement to the same model final pose/gripper.
Each gets one native action and original guard. Same5-step budget, no extra
solve/retry/resampling. Full plan is in waypoints.jsonl. Distinct development
execution condition; do not pool with old repeated-target policy results.
launch.py resolves paths before native cwd changes. Offline guard fixtures and
1512 geometry paths passed; temporary scripts deleted. Local audits:
code/runs/company2-playground-20261022-deploy/*offline-validation.json.

## Real checks

g native172178 ended,0API: hold5 tracked; X+20mm needed.283rad joint increment,
guard rejected before dispatch. Ended at5; Y/Z not executed.
h native242081 ended,0API: hold/X+/Y+/Z+ each5 accepted,20steps.
XYZ achieved19.495/19.474/19.532mm, errors.506/.535/.475mm.
i actual calls selected rightY-/open, hold, rightZ-/open.
Y- achieved[-.193,-16.653,-11.482]mm, target error11.962mm; no2pi jump.
Z- executed3 waypoints then fourth IKFail, discarded2 suffix and reviewed at13.
Head/right-wrist reviewed at0 and13: target on table, no enclosure/stable grasp.
All three actual requests English, ten questions,3/6/9 images; no IK event in input.
See i/first-segment-input-audit.json and execution-tracking-audit.json.

First clear execution plateau is joint2 around-.2304rad: Y- final target-.292484,
actual-.230417; later Z- target-.325129, actual-.230495. This differs from prior
controlled e joint3 plateau near-.036rad. Successful i target FK matches requested
Cartesian pose within.000311mm; USD/URDF authored joint2 limits both about+-10rad.
Runtime limit/drive/self-collision cause is NOT yet proven. A hold from displaced
measured pose tracking does not solve the preceding missed motion.

## Next bounded work

Read existing baseline robot interfaces for runtime joint limits/velocities,
actual drive targets and effort limits. ImplicitActuator estimated torque is
not PhysX measured torque. Contact pairs/impulses, if needed, remain outer-only.
Use a new independently named zero-API diagnostic with a predeclared small
robot-motion plan and ownership/resource checks. Do not hot-edit a live source,
disable collisions, alter drives/limits/assets, or relax guard to force motion.
No more blind Z- continuation, repeated image examples or identical failed cards.
Resolve this execution question before another policy short segment.

## Boundaries / candidates

Old server02 and new b/c/d/e/f/g/h/i ended; do not resume them.
r001 feedback probe, r003 failed-motion summary and r004 action-image examples
have no verified grasp benefit; not promoted. r002 tracked one rotation/descent,
not stability. Controlled f retains one body-response history,0API.
Keep all negative text/provenance. No old experience bank or /tmp.
Model text/experience English; no K/T/calibration/projections/target truth/
contact/reward/success model input. Feedback only selected target vs robot state.
One representative image history per task/batch; other audits temporary.
Eight GPUs authorized, but foreign occupants recently on0/1/3: recheck, do not touch.
Require>=8GiB GPU/20GiB RAM per environment plus headroom,8GiB disk.
1000-step development budget=official200x5, original success predicates unchanged.
Freeze held-out5–14 and15–24, each>=9/10 before stability; local Pro planner/YPR later.
Pause/cancel immediately stops owned controls and disables supervision job.

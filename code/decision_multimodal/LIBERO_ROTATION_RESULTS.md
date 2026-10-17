# Three-task multimodal rotation results — 2026-10-18

## Scope of the successful condition

Version3 completed all nine predeclared native tasks, with native success and program completion both9/9. Each of the three tasks completed3/3, without selective replacements. The tested condition uses **algorithm-assisted angular feedback rendered as images plus numerical fine control**. It does not demonstrate raw-camera-only orientation inference or superiority over numerical text control.

The angular residual is still supplied: an algorithm derives it from the original permitted RGB-D task geometry and measured own-robot orientation, then renders its signed components as cyan target rays relative to a white reference. Luna classifies CCW/CW and the program maps these to positive/negative world rotation-vector components. Components are executed together, not as sequential Euler angles. Numerical XYZ, gripper/stage feedback and small-angle rotation feedback remain.

## Frozen version3 verification

Inference commit:c5377751. Diagnostics/export commits do not change inference. Source policies are the original frozen task-specific LIBERO-plus baselines. Initial states and the test condition were declared before these nine cases started.

| Task | Fixed initial states | Native / joint | Policy steps | Total steps, including setup and settling | Visual / motor calls |
|---|---|---|---|---|---|
|1383 Stove control|8,9,10|3/3 /3/3|330,360,345|340,370,355|57 /318|
|1458 Bottle onto rack|11,12,13|3/3 /3/3|507,549,516|517,559,526|88 /376|
|1335 Rectangular cream-cheese box into bowl|23,24,25|3/3 /3/3|336,303,303|381,348,349|12 /235|

Task1335 includes world rotation-vector setup offsets with alternating signs of[12,-12,25]degrees. This is own-robot test setup, not model-controlled success. Setup consumed35/35/36 native steps; original settling adds10. The version3 wrapper enforces the600-step total limit. All nine completed within it. Objects were not teleported or read through hidden simulator object state.

Actual provider audit:1086 responses =157 visual calls +929 motor calls;471 inline image blocks. Visual calls produced169 axis classifications,167 consistent with the permitted angular-residual sign and2 opposed. No visual HOLD is offered for components known by the outer algorithm to be outside the coarse region. Small components are handled numerically. There were no terminal API errors. Repeated decisions within one rollout are correlated;169 answers are not169 independent task trials.

Every camera pair in a visual request has the same native observation counter. Every final request passed the English/role-schema audit. Visual-role state contains only task, stage, current Pro stage goal, visual goal and source description. Numerical angular values are absent from its text, but deliberately encoded in the angular image. No experience is loaded.

## What changed and what failed

| Version | Actual test | Native / joint | Finding |
|---|---|---|---|
|v1,4b511398|One developer case per task|0/3 /0/3|Audit metadata keyword collision prevented every visual dispatch. Stove had56 numerical responses before the implementation fault.|
|v1r2,9dafe0ea|Same three developer cases in repaired code|1/3 /0/3|Detailed public finger-mesh candidate cards were unreliable. Box/rack exhausted approach orientation budget; stove reached native success but not its program target.|
|v2,f1019adc|One developer case per task|3/3 /3/3|Explicit angular relation images and parallel axis classifications enabled completion. A rack stage-goal compilation mismatch was then found.|
|v3,c5377751|Three fixed initial states per task|9/9 /9/9|Corrected rack phase goals, enforced combined setup budget, and preserved the same angular-feedback method.|

The v1r2 audit recorded348 responses, including146 visual calls. The visual whole-candidate selections included50 residual-sign-consistent choices,35 opposed and61 HOLD. This distinguishes perception/choice failures from an API transport or driver fault. Neither source nor axis mapping was changed to overwrite wrong model answers.

Version2 recorded359 responses =51 visual +308 numerical, with54/55 angular axis classifications sign-consistent. These are development successes, kept separate from the version3 nine-case result. Unstarted slots in developer campaigns were not silently counted as successful or failed tests; each developer invocation was explicitly capped at three cases.

## Planning and runtime ownership

The local ChatGPT Pro gpt-6.1-sol/high planner produced readable goals for all three tasks. Its actual English prompt and JSON are archived. Runtime compiles only the appropriate current stage name and goal; the old native control phase graph and exit predicates remain. The first Pro output describes candidate diagrams. The outer experiment subsequently replaced that feedback method with angular relation images; do not mistake the saved first proposal for an autonomous planner producing the final interface.

Version3 specifically maps bottle source approach/grasp stages to the Grasp goal, and held-bottle carry/orient_receiver stages to the rack Align goal. The previous compilation had used the rack goal prematurely. The internal visual model never receives experiment scheduling, trial counts or memory-management instructions.

## Limits and reusable findings

- The successful model reads an engineered angular-feedback image. The algorithm already knows the signed geometric residual; camera RGB's additional value has not been isolated.
- The earlier candidate-card failure and the successful dial condition change both the representation and the axis-output organization. They do not isolate a single causal factor.
- The tests cover only three tasks and three fixed initial states each. They are an operational check under this condition, not broad6DoF generalization.
- Tiny predicted pose differences and symmetric finger silhouettes were difficult for the model. A clear named visual relation, with fine feedback retained, was more reliable here.
- Keep the model goal, feedback reference and actual phase aligned. Never turn tool errors into model failure scores, or native-only success into joint success.

## Artifacts and review page

Remote root: `/root/yekangjie/project/jev_rsi/.worktrees/decision-multimodal-20261016/code/runs/` on company-server-2. Native roots: `2026-10-18-libero-rotation-candidates-v1`, `...-candidates-v1r2`, `...-dials-v2`, `...-dials-v3`. Every raw request/response, camera PNG, rendered feedback, execution mapping, setup and native result remains there. Final formal audit is `...-dials-v3/rotation-audit-final.json`.

Review route: `/rotation-evidence/`. It provides one complete policy snapshot replay per task, original actual input PNGs, raw request/response downloads, the saved Pro prompt/plan and per-case results. These are snapshot replays after setup, not wall-clock API recordings. The stove baseline saved only its full external camera sequence; absent wrist snapshots are explicitly blank. Actual wrist images sent to the model are separately retained in each visual call.

## Changed files

Under `code/decision_multimodal/`:

- `libero_rotation_images.py`, `libero_rotation_setup.py`, `libero_rotation_multimodal.py`, `libero_rotation_dials.py`
- `libero_entry.py`, `run_libero_campaign.py`, `plans/libero_rotation_three_v1.json`
- `audit_rotation.py`, `export_rotation_evidence.py`, `build_rotation_evidence.py`, `rotation_evidence.html`
- `LIBERO_ROTATION_PROTOCOL.md`, `LIBERO_ROTATION_RESULTS.md`

Other records: `code/experience/decision_multimodal_rotation_20261018.md`, `LOGS/2026-W42.md`, `LOGS/2026-W42-activity.md`, `Discussion.md`, `TIMELINE.md`. Generated native/evidence assets stay under ignored `code/runs/`. No environment or driver installation was performed.

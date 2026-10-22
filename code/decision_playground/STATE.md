# Playground continuation state

Updated:2026-10-23. Read AGENTS.md, EXP-2026W43-007 and real processes first.

## Ownership / phase

SSH company-server-2-ykj (JcbotIns), user ykj.
Remote repo /home/ykj/project/jev-rsi-roboicl/.worktrees/decisions-playground-20261022.
Baseline/interpreters /home/ykj/project/jev-rsi-roboicl/baseline/roboicl.
All owned native/policy processes exited; no curl/API in flight (verify real PIDs).
o interface check: native829592/runner838053 ended at8steps,0API; temporary script deleted.
Full5-step feedback agrees; partial3-step returned exactly the last actual target.
Full residual11.638mm vs sent-target error1.928mm. Zero dispatch offline-covered only.
p campaign code/runs/playground-feedback-policy-20261023p, GPU5/layout1/RPC25405:
native856266 / worker878945 ended after sequence1 stop, episodecf312b09-c1e4-48b9-9b15-f76382dfa3e0.
Six HTTP200/29native steps over two reviewed segments, r005 + new feedback.
Initial bilateral Z- did not track; model pitch- then rightY-19.438mm/.579mm error.
Then open/close/Z-; final4/5 dispatched, actualZ -27.203mm vs last target -16mm,
sent-target error11.344mm vs full-goal7.420mm. Final IK refusal correctly stopped.
No verified capture/lift/retention; candidate not promoted, not a full task failure.
Final partial feedback was never fed into a subsequent model call: no claim that
p validated model response to unequal full/prefix feedback or causal improvement.
Keep p representative image history and its three copied Lesson references.
Only current-task temporary audit copies may be cleaned by exact manifest.

Old server02 and b/c/d/e/f/g/h/i/j/k/l/m/n/o/p ended; never restore/replay.
Previous source96e47233 deployed; selected-gripper-command-v1 is now offline patched,
check latest commit/deployment before any new native start. r005 template previously ed1122d5.
feedback-selected-vs-dispatched-v1 offline+o real full/partial interface validated; policy benefit not yet tested.
n campaign code/runs/playground-lesson-transfer-20261022n:
GPU4/layout0 native720103/worker748068, episode42ba1791-c20a-4011-a0d8-eaeced448b48,
6HTTP200/30native steps. GPU5/layout1 native720372/worker748070,
episoded0d436f8-b2d4-4e98-9ed6-21e86582e284,2HTTP200/6steps.
Both explicitly stopped with command sequence1 after two reviewed segments, all4 PIDs absent.
r005 NOT promoted. Layout0 selected pitch- after Y- mismatch then Z- tracked19.502mm
with.503mm error, but ended with two holds/no enclosure or retention.
Layout1 Y-/Z- partial prefix then another ineffective Z-/refusal, no reorientation/recovery.
No native terminal scores: these are development interruptions, not0/2 full failures.
Only GPU4 representative full history and r005 three source lesson images retained;
other n review media removed after review/stop with hash manifests; text/requests retained.

## Transport

Owned local SSH ControlPath:
/home/ykj/project/gpt6/CVPR/jev-rsi/jev-RSI/code/runs/c2-proxy-20261022.ctl

Remote127.0.0.1:17897 -> local127.0.0.1:7897; remote original7897 untouched.
Upper/lower HTTP(S)/ALL proxy variables are process-scoped.
Only du /v1/decisions; no ordinary API, caz/z, or extra API probes.
Actual calls c30+e18+i3+n8+p6=65HTTP200; b failed initial request preserved separately.

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
Subsequent j runtime evidence: actual limits/targets match configuration; .4s extra
endpoint dwell leaves q2 plateau, return clears it. Estimated torque is not measured motor torque.
k reporting v1 had0callbacks, so unavailable. l reporting v2 had136callbacks/141headers:
131 base_link-link2 headers, sustained impulses during q2 plateau; reverse clears them.
Other10 startup finger headers have zero impulse. Protected physical attributes unchanged;
j/l endpoint measurements bit-identical. Real contact association, not exclusive causality proof.
Public cuRobo self-collision checks enabled but base_link-link2 pair ignored; no configuration changed.

m bounded zero-API test: pitch_negative -.10rad then Y-20mm then return,15native steps.
Rotation tracked .090mm/.002923rad; Y- achieved19.439mm, endpoint error.577mm.
No controlled report headers for the prior pair, callback pipeline healthy. Native646869 exited.
This is one controlled recovery, not policy-selected or a grasp. See m/reorientation-audit.json.

## Next bounded work

Offline clarify feedback-selected-vs-dispatched-v1 before more policy calls.
Existing execution_feedback remains full selected goal vs measurement. New
last_dispatched_target_feedback compares the actually sent Cartesian waypoint
with the same measured robot state (null if none sent). No IK/guard/contact
reason or internal dynamics enters model input. Adapter returns its last sent
Cartesian action, worker projects only command-vs-measurement fields.
210 rotation/translation/prefix fixtures plus no-dispatch/null and known measured
error checks passed; no API/native calls or temporary test script.
The layout1 full goal residual11.633mm includes the discarded suffix; delivered
prefix error was~1.935mm, so do not misclassify all residual as execution error.
Independent actual Playground.handle in-memory integration prefix0..5 passed,
including refusal/no-dispatch null and final target selection; no API/native.
p read-only closure/descent audit complete: close steps21..25 position-stable
(~.067mm); descent mismatch starts26 (1.390mm), q2 measured reaches~-.2306rad
while targets progress -.242945/-.270536/-.300144/-.332052. Errors grow to13.328mm
at28,11.344mm at29. Runtime targets match IK; accepted increments<=.101469rad,
no2pi jump or physical contact cause established. Original head/wrist20/25/29 reviewed.
Public localX finger extension/localY opening agree; TCP150.070mm is7.500mm behind
mesh maximum157.570mm, not a validated contact centre. No geometry/physics edit.
Confirmed separate keep semantics issue: p close sent0, normalized rate-limited
prev_control returned.045038, old keep sent.045038 instead of retained selected0.
New selected-gripper-command-v1: explicit per-episode final-goal ledger in worker;
positive dispatched prefix commits selection, zero prefix does not, reset rebuilds.
Model state explicitly uses runner_retained_goal, measured opening stays null.
Actual worker-loop fake integration close/keep/refusal/reset + pure prefix0..5,
drift/invalid-count/immutability fixtures and independent review PASS. No new API/native.
Next single minimal condition: new independent zero-API fixed-arm close/keep probe,
predeclared <=15native steps; compare final-goal ledger and sent actions against
raw low-level observations. First guard/refusal stops. No automatic policy API
or new hint/Skill until that interface check and first-failure evidence reviewed.
Do not restore p or replay requests. This repair is not proven to cause/fix p's
arm overshoot and is not a grasp benefit. All r001-r005 remain unpromoted.
Outer-only English audit lessons/p_closure_descent_audit.md; model r005 unchanged.
Keep original guard/drive/limit/collision parameters and fixed action budget.

## Boundaries / candidates

Old server02 and new b through p ended; do not resume them.
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

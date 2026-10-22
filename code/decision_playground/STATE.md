# Playground continuation state

Updated: 2026-10-22. Read AGENTS.md and EXP-2026W43-007 before acting.

## Active ownership

- SSH host: company-server-2-ykj (JcbotIns), user ykj.
- Remote repo: /home/ykj/project/jev-rsi-roboicl/.worktrees/decisions-playground-20261022.
- Baseline assets and interpreters: /home/ykj/project/jev-rsi-roboicl/baseline/roboicl.
- No active native/worker. g native172178 verified exited after bounded zero-API smoke.
- g hold5 tracked; next X+20mm required0.283rad joint increment and guard rejected it before dispatch.
- g stopped at5 steps; Y+/Z+ were not executed. This is an execution-contract result, not task failure.
- Next: offline/native test a predeclared five-waypoint trajectory to the same final TCP goal, preserving the original guard and5-step budget.
- Ended e: playground-ik-z-diagnostic-20261022e, native3894916 / worker4031664 verified exited.
- Model episode984becb0-bdac-452f-b32a-b7fddea6c6a7 ended incomplete at90/1000,18 Decisions HTTP200, r004.
- Last command sequence5, op stop; never resume this episode or replay requests.
- Critical finding: native adapter bypassed baseline rollout installation of default IK continuity guard.
- At step89 raw IK Success included ±2pi-equivalent joint targets, causing unintended motion.
- Restore and verify original guard before starting another policy episode. No source changes in running processes.

## Transport

Dedicated local SSH control socket:
/home/ykj/project/gpt6/CVPR/jev-rsi/jev-RSI/code/runs/c2-proxy-20261022.ctl

Remote127.0.0.1:17897 forwards to local127.0.0.1:7897. Remote7897 is untouched.
Policy processes inherit both HTTPS_PROXY and https_proxy=http://127.0.0.1:17897.
Verify actual tunnel/process ownership; never replay failed/unknown requests or
probe another OpenAI API. A failed tunnel must not cause duplicate workers.

## Evidence and stopped campaigns

- Original server02 campaigns stay ended.
- New b first call timed out at zero upload and zero model actions; ended.
- New c eight-card development:30 Decisions requests all HTTP200; GPU0 ended
  at45 steps, others15, explicitly stopped after review, not native task failures.
  r001 feedback-probing candidate did not improve its checked segment. Do not promote.
- Controlled d:hold/X+/X-/Y+ tracked; a later reset raised UnStableError and
  exited. Preserve reset-failure-audit.json. Never resume or replay it.
- Controlled e first episode: initial Z-20mm had IK Success but only about1.2mm
  TCP descent even after25 native steps. Solver target FK was correct; USD/URDF
  joint3 limits matched. Actual joint3 stalled. A subsequent pitch-0.1rad and
  new Z-20mm tracked, residual about0.074mm. This was zero-API outer diagnosis,
  not model performance, and its exact physical obstruction remains unresolved.
- e was explicitly reset once, successfully, before starting the active model
  episode. Controlled35-step episode and image provenance remain separate.

## Latest evidence and next bounded action

r003 retained the measured failed-motion summary after recent history lost it.
Its six calls at30–60 still rotated/held without useful approach; not promoted.
Controlled f made zero API calls: X+/Y+/Z+ each20mm tracked with target errors
0.0755/0.0814/0.0811mm. It ended at15 steps and retains one raw image history.
r004 selected three historical raw head images with English measured captions,
removed currently inapplicable earlier candidate text, and made six calls60–90.
First segment only closed/opened/held; next two Z- actions tracked about19.998mm.
The third Z- exposed four IK Fail calls followed by a ±2pi raw target jump.
TCP displacement[-80.316,-2.324,26.397]mm and error92.783mm are adapter execution
contamination, not evidence that the chosen Cartesian direction was wrong.
No grasp, stable hold or operational stability has been demonstrated.

Baseline shared_harness enables IKContinuityGuard with0.15rad increment cap.
Its rollout installation was bypassed by the Playground entry point. Restore
that original execution contract, preserve raw observer and refusal accounting,
and validate offline plus one bounded zero-API native check before policy calls.
Do not replay e actions or revive its ended episode. Do not repeat r004 examples
to fill GPUs. All candidates remain unpromoted. c30+e18=48 HTTP200 calls total,
plus b preserved failed initial request; controlled diagnostics are not policy.

Keep3-call segments and review actual head/wrist, IK and measurements before
continuation. Knowledge revisions are immutable and English; no K/T, target
truth/contact/reward/success model input, no old experience bank or /tmp.
Eight GPUs authorized, but parallelism requires distinct questions/review capacity.
Retain one representative task history, other audit frames temporary.
Freeze held-out layouts5–14 and15–24, each>=9/10 before stability; Pro planner
and YPR task remain downstream. Respect pause/cancel and close owned controls.

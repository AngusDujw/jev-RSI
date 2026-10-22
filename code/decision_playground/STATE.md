# Playground continuation state

Updated: 2026-10-22. Read AGENTS.md and EXP-2026W43-007 before acting.

## Active ownership

- SSH host: company-server-2-ykj (JcbotIns), user ykj.
- Remote repo: /home/ykj/project/jev-rsi-roboicl/.worktrees/decisions-playground-20261022.
- Baseline assets and interpreters: /home/ykj/project/jev-rsi-roboicl/baseline/roboicl.
- Active campaign: code/runs/playground-ik-z-diagnostic-20261022e.
- Native PID: 3894916, GPU0, loopback RPC25300, loaded native adapter69cfc899.
- Policy PID: 4031664, code7d091653, du Decisions only, no ordinary API.
- Model episode: 984becb0-bdac-452f-b32a-b7fddea6c6a7.
- Latest reviewed status: r002, six Decisions calls /30 native steps, segment1 awaiting_review.
- Last command sequence: 0 (continue). Inspect live files/PIDs before issuing another command.
- Development budget:1000, original200; success predicates unchanged.

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

## Current candidate check

r002 adds explicit measured motion differences in recent interactions plus
one unvalidated reorientation-after-nontracking lesson and two historical raw
frames. No K/T, target truth, contact, reward or success evidence enters the model.

Real policy first segment selected right Y-, then Z- plus pitch-, then hold.
The combined rotation/descent tracked to about0.070mm error, but images showed
no enclosure or grasp. The second segment selected Z-/close with zero motion (all five right-arm IK calls returned Fail),
then two holds. A close command is not a grasp. Six requests all HTTP200.
Do not declare the controller stable or the candidate a validated Skill.

## Next bounded action

Inspect current head/wrist images at30 steps. The latest Z-/close at steps15-20
was five IK Fail results, unlike the earlier accepted-but-untracked motion.
Translation feasibility and visible target alignment must be distinguished.
The two-entry history can also discard a failed motion after two holds; assess
what evidence is actually retained before adding another semantic instruction. Distinguish actual target alignment from improved motion tracking.
Use the recorded image/action effects to identify the first remaining failure;
do not simply append synonymous prompting or replay a fixed object route.
Keep each policy segment at3 calls and review before continuing/resetting.
Knowledge changes happen at barriers with immutable revisions and explicit
positive/negative evidence. Candidate procedures stay English and conditional.

Only one representative image history per task/batch is retained; other review
images are temporary. Preserve text and image references used by active lessons.
No old experience bank, no /tmp, no foreign processes or driver/Conda changes.
All eight cards are authorized, but expand only after a meaningful candidate
and adequate review capacity; do not fill idle cards with the same known failure.
Freeze independent held-out validation before claiming stability.

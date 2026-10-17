# LIBERO motion-description multimodal retest — 2026-10-17

## Result

Ten existing Goal tasks, three fixed paired initial states per condition.
All 93 native attempts have ended. The comparison contains90 effective episodes:
all 87 original normal outcomes plus three source-linked complete episodes for
unanswered HTTP 520 gateway interruptions. Normal task failures were not rerun.
No experience was injected into either runtime model.

| Input condition | Native success | Native + program completion | Nonzero-axis nominal agreement |
|---|---:|---:|---:|
| XYZ feedback + current RGB | 27/30 | 26/30 | 4577/4868 =94.02% |
| Remove explicit XYZ feedback; target/control markers | 1/30 | 0/30 | 1051/3871 =27.15% |
| Same markers plus world-axis compass | 0/30 | 0/30 | 957/3969 =24.11% |

The axis score compares actual choices with the original camera-derived residual
rule. It is not ground-truth object geometry, optimal physical action or task
success. Repeated decisions within one episode are correlated.

The original 30 episodes per condition remain separately recorded: full native26,
joint25; marker native1, joint0; axes native0, joint0. Each original condition
contains one HTTP 520 interruption. Its separate replacement returned no new API
error: full 1252/init5 succeeded; marker 1423/init11 and axes 1383/init9 normally
failed. The final audit retains primary, replacement and effective records.

## Per-task effective outcomes

Cells show native/joint successes out of three, not stage or view successes.

| Goal | Task | XYZ + RGB | Markers, no explicit XYZ | Markers + compass, no explicit XYZ |
|---|---|---:|---:|---:|
| 1098 | Open middle drawer | 3/3 | 0/0 | 0/0 |
| 1144 | Bowl to stove | 3/3 | 0/0 | 0/0 |
| 1163 | Bottle to cabinet top | 3/2 | 0/0 | 0/0 |
| 1202 | Open drawer and insert bowl | 1/1 | 0/0 | 0/0 |
| 1252 | Bowl to cabinet top | 3/3 | 0/0 | 0/0 |
| 1296 | Push plate to front stove | 3/3 | 0/0 | 0/0 |
| 1335 | Cheese to bowl | 3/3 | 0/0 | 0/0 |
| 1383 | Turn stove knob | 3/3 | 0/0 | 0/0 |
| 1423 | Bowl to plate | 2/2 | 1/0 | 0/0 |
| 1458 | Bottle to rack | 3/3 | 0/0 | 0/0 |

Seven tasks have 3/3 joint outcomes in the full condition; this small paired
sample is not a broad stability guarantee. Both reduced conditions ended 27/30
episodes in approach. The marker exceptions ended in descend, align and carry;
the carry case 1423/init12 reached native success but exhausted its 160-decision
program budget. The compass exceptions ended twice in align and once in descend.

Full-condition joint failures: 1163/init5 reached native success but chose STOP
in retreat; 1202/init4 and init5 exhausted the lower-stage budget; 1423/init11
exhausted the carry-stage budget. These differ from coarse direction failures.

## What changed and what remained

- Actor: authorized du `gpt-6-luna` Decisions; local Pro `gpt-6.1-sol/high`
  reviewed the input contract. Original task-specific stages, perception,
  thresholds, motor scaling, options and evaluation remained frozen.
- All conditions receive the same verified 369-word English native-motion
  description and short Jev-style XYZ questions. Each current image is labeled:
  `agentview` is fixed; `robot0_eye_in_hand` moves with the hand.
- No camera K/T, numerical camera pose, object ground-truth state, contact,
  reward or native success is sent to the actor. Camera calibration is used
  inside the frontend for markers and compass orientation only.
- All images preserve the 768x768 native scene and append the same 160px footer.
  The compass is a goal-independent orientation legend: red +X, green +Y, blue +Z.
  It is not a target arrow or metric pixel-displacement prediction.
- Non-XYZ questions and stage contracts are shared across these conditions.
  Reduced input removes explicit translation axes and named position errors;
  own EEF position, rotation feedback, stage booleans, some other geometry,
  candidate descriptions and action feedback remain. This is not pure RGB control.

The full contract lists the remaining geometric fields and a shared prompt
limitation: 1098/1202/1383 previously stated their 2mm hold constant only in the
old XYZ question. The short question says "within tolerance" without restating
that number. This interface ambiguity remains; no visual 2mm guarantee is claimed.
The knob's `visible_tab_world_xy_m` and drawer scalar gap evidence also remain;
"no XYZ" means the explicit axis feedback ablation, not removal of all geometry.

## One actual trajectory

For 1144/init5 the original offline residual starts at
`(+119.57,-0.84,-90.14)mm`. Full input chooses `(+/hold/-)` and completes in 89
decisions. Markers alone start `(+/+/hold)` and end approach after 45 decisions,
with residual `(+81.51,-1.20,-27.58)mm`. Compass input starts correctly, then
chooses positive Z on decision 0001 despite a nominal negative Z residual; its last
decision 0044 still chooses positive X at a nominal X residual of -221.02 mm.
These residuals are outer diagnostics; they were not sent to either reduced actor.
The website exposes each actual decision and the exact first input images.

## Audit and interpretation

All 93 attempts: 6469 actual requests,12938 exact PNG image blocks,6466 valid
responses and three unanswered HTTP 520 interruptions. Effective 90 episodes:
6350 valid responses, zero terminal API/startup faults. English text, no outgoing
K/T, motion-text equality, image bytes/hashes/dimensions, raw-to-normalized choices,
inference-source hashes and interrupted-source provenance passed audit. All 3210
actual reduced requests omit explicit translation_axes and the error-basis phrase.

The current marker/compass representation does not reliably replace explicit
XYZ feedback. A correct first visual decision does not establish sustained
closed-loop competence. The retained-feedback result is better than the earlier
20/30 joint RGB result, but motion text, questions, K/T exclusion and image layout
changed together; this does not isolate the benefit of any one change. The older
27/30 text reference was historical, not a newly run text control here. These
results do not establish the capability limit of all multimodal decision models.

The fixed experiment is complete. No additional same-version control episodes
are scheduled. Experience is collected only. A subsequent version should keep
explicit tolerances and isolate a smaller feedback reduction before expanding.

## Sources and reproduction

Inference source:`3b72ddad`; original runner also pinned in each campaign.
Gateway-only replacement eligibility:`deccf9e9`, with unchanged inference hashes.
Physical GPUs 4–7 on company-server-2; existing environments only.

Company worktree:

```text
/root/yekangjie/project/jev_rsi/.worktrees/decision-multimodal-20261016
```

Full native/request/image assets remain in the six company directories matching
`code/runs/2026-10-17-libero-rgb-motion-*-v1*`. Final audit:
`code/runs/2026-10-17-libero-motion-mm-final-audit.json`; compact local copy:
[final-audit.json](../runs/2026-10-17-libero-motion-mm-preparation/final-audit.json).
Source-linked reproduction commands are in EXP-2026W42-231/232.

The following audit command is a single line; run it from the company worktree:

```bash
python3 -B code/decision_multimodal/summarize_motion_multimodal.py --output code/runs/2026-10-17-libero-motion-mm-final-audit.json --include-transport-replacements --audit-inputs
```

Review page: [actual inputs and results](http://100.81.6.59:18944/motion-retest.html).
The original historical comparison remains at the service root. Bulk assets are
not copied to another mount; no/tmp, environment permission or driver changes.

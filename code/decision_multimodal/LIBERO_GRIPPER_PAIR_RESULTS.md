# Gripper-anchored arrows versus unmodified RGB — 2026-10-17

## Result

All 60 effective episodes have ended: ten frozen LIBERO tasks, three paired initial states in each of two conditions. Both groups used `gpt-6-luna`, the authorized du API, unchanged task-specific processing/stages/control, and no experience injection.

| Input | Native success | Native + program completion | Terminal stage |
|---|---:|---:|---|
| Current-gripper world-axis arrows | 0/30 | 0/30 | 29 approach; 1 align |
| Unmodified RGB | 0/30 | 0/30 | 30 approach |

Each task (1098, 1144, 1163, 1202, 1252, 1296, 1335, 1383, 1423, 1458) had native0/3 and joint0/3 in both groups. Arrows1252/init4 reached align but did not complete the task. An observation step, an executed motion or a phase switch is not a task success.

The completed comparison does not show a task-completion benefit from adding these arrows. It does not establish a general limit of multimodal models. Both inputs still depend on the original processed stage booleans, nonpositional feedback and controller-internal measurements; this is not pure RGB control.

An outer diagnostic compared axis choices outside the original deadband with the sign of the original camera-derived residual: arrows979/3554 (27.55%), raw786/3463 (22.70%) in the effective episodes. This apparent directional improvement did not yield a completed task. The reference is the original processing rule, not privileged physical truth or an optimal-action label; repeated choices within an episode are correlated. It is not a statistically established task-level gain.

## What changed in the actor input

Both groups received identical English motion descriptions, short XYZ questions, options, stage contracts and conditional arrow explanations at the same observation. Both received two current native768x768 RGB images. Neither received explicit goal-minus-current XYZ errors, measured EEF coordinates, camera matrices, numerical tolerances, target-point markers, a separate TCP dot, or an image footer.

The arrow group used the approved visual convention: external agentview shows only green+Y/blue+Z; the moving wrist view shows only red+X/green+Y. The anchor is recomputed from the current own gripper reference and current public camera calibration, never object state. The wrist glyph shows current world-axis projections, not future gripper pixel displacement. There is no arrow for an out-of-frame or behind-camera origin.

The existing phase graph, internal thresholds, action magnitudes, task processing and allowed transitions were frozen. The local Pro `gpt-6.1-sol/high` call reviewed this comparison contract; it did not generate replacement plans or concrete actions for these episodes. Its review accepted the contract with no blocking issue and explicitly noted the extra own-gripper/calibration information in the glyph.

## Original attempts and transport handling

- Two v1 startup probes stopped before network dispatch and before any native step because the audit metadata duplicated a dispatcher keyword. Both are retained as implementation faults (EXP236).
- V2 primary campaigns contain60 attempts. Raw1458/init11 received15 valid answers, then an unanswered HTTP520. Its full original trajectory remains preserved.
- One separately declared, source-linked complete replacement of that interrupted episode received46 valid answers and normally failed. No normally failed episode or received model answer was resampled.
- Thus there are61 API-backed native attempts,60 effective episodes, and two additional zero-step startup probes. All effective episodes ended without a terminal API error.
- Actual attempts contain2810 transmitted requests,2809 valid responses and5620 image blocks. The effective subset contains2794 requests,2794 valid responses and5588 image blocks. The one unanswered520 is not treated as a valid decision.

## Input and image checks

The preflight paired construction checked59 archived source snapshots from ten tasks: the nonimage payloads matched exactly and raw native pixels were unchanged. The actual first nonimage payloads also matched in all30 paired initial states. Later trajectories diverge after different actions, so later scene images naturally differ.

All actual request text and question contracts passed the English/removed-field checks. Both current image blocks in every transmitted request matched their recorded PNG bytes and SHA256, with native768x768 dimensions and synchronized frame counters. No camera matrices, numeric EEF coordinates or numeric tolerances entered the actor. The inference files matched the frozen campaign hashes. These checks audit data flow; they do not certify physical action correctness.

In the arrow group, the gripper origin was in frame for2610/2900 views (90.0%);5176 arrows were drawn. Remaining glyphs were omitted because the origin left the view or the projected direction/image margin could not support the glyph. The renderer never left an old arrow at a fixed screen location.

## One complete failed example

Task1144/init5, bowl to stove, used45 decisions in both conditions. Both ended in approach.

| Condition | First actual XYZ choice | Last actual XYZ choice |
|---|---|---|
| Arrows | positive / positive / hold | hold / positive / hold |
| Raw | positive / negative / negative | hold / hold / positive |

For outer diagnosis only, the original camera-derived stage errors at the first decision were X+119.57mm, Y−0.84mm, Z−90.14mm. The last recorded errors were X+176.50/Y−1.20/Z−290.63mm with arrows, and X+47.78/Y−1.24/Z−514.18mm without arrows. Neither actor received those errors. They describe the original processing chain, not privileged object truth. Correct initial X choices did not produce sustained closed-loop approach.

The arrow trajectory eventually moved the gripper out of agentview; its last external image therefore has no glyph. Target objects remained visible. This supports checking complete trajectories rather than only a correct first answer. Axis directions also do not identify the exact intermediate waypoint; target/stage-goal grounding remains a possible limitation, not a separately isolated causal result of this experiment.

## Reproduction and evidence

Protocol and paired states: [LIBERO_GRIPPER_PAIR_PROTOCOL.md](LIBERO_GRIPPER_PAIR_PROTOCOL.md).

Remote worktree: `/root/yekangjie/project/jev_rsi/.worktrees/decision-multimodal-20261016` on company-server-2. All native episodes ran on physical GPUs4–7; the main wave used two episodes per GPU. No driver, CUDA or environment installation changed. Inference implementation was frozen at7597593b; later commits changed collection/documentation only.

Primary roots under `code/runs/`:

- `2026-10-17-libero-gripper-pair-arrows-v2/`
- `2026-10-17-libero-gripper-pair-raw-v2/`
- `2026-10-17-libero-gripper-pair-raw-v2-transport/`

V1 startup faults remain in the corresponding `*-v1/` roots. Actual provider requests, provider responses, normalized choices, PNGs, native result files, launcher logs and manifests remain in their original episode folders.

Preparation/Pro review/local copies: `code/runs/2026-10-17-libero-gripper-pair-preparation/`. The final audit is `final-outcomes-audit-v2.json`; it keeps primary, replacement and effective rows separately. The first audit is retained rather than overwritten; the final version recognizes legacy `operation` stage labels and both deadband spelling variants for diagnostic summaries.

Actual task1144/init5 first/last request text, full requests, responses and exact image bytes: [HTTP evidence folder](http://100.81.6.59:18944/gripper-pair-evidence/). This is actual runtime evidence, not the previous preview. English experience remains collection-only in [EXPERIENCE.md](EXPERIENCE.md).

## Files changed for this comparison

Follow-up analysis without new inference or simulation: [LIBERO_GRIPPER_PAIR_DIAGNOSIS.md](LIBERO_GRIPPER_PAIR_DIAGNOSIS.md). It identifies the hidden-waypoint/visual-goal mismatch, missing temporal action context, and measured execution evidence. The original completion results above are unchanged.

Added: `libero_gripper_pair.py`, `libero_gripper_pair_description_v1.txt`, `audit_gripper_pair.py`, `collect_gripper_pair.py`, `LIBERO_GRIPPER_PAIR_PROTOCOL.md`, and this result report.

Updated: `libero_entry.py`, `run_libero_campaign.py`, `README.md`, `EXPERIENCE.md`, and the repository EXP/activity/Discussion/Timeline records. Bulk runtime evidence stays outside Git under `code/runs/`.

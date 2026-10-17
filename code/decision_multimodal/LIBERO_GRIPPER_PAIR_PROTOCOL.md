# Current-gripper arrows versus unmodified RGB

## Frozen comparison

Approved on 2026-10-17. Two groups use `gpt-6-luna` through the authorized du API. Local Pro `gpt-6.1-sol`, high reasoning, reviews the interface. No experience is injected. Earlier experiments and preview-only artifacts remain separate.

| Input | Arrows | Raw |
|---|---|---|
| Two fresh native 768x768 RGB views | Yes | Yes |
| Same English motion description, questions and stage contracts | Yes | Yes |
| Same conditional arrow explanation | Yes | Yes |
| Original stage/arrival/holding feedback, gripper state, nonpositional feedback | Yes | Yes |
| Numerical XYZ errors, EEF coordinates, camera matrices, numerical tolerances | Absent | Absent |
| Target point, separate TCP dot, footer | Absent | Absent |
| Gripper-anchored world axes | External Y/Z; wrist X/Y | Absent |

The renderer uses only the current public camera calibration and own measured gripper reference. It recomputes the anchor and world-axis projection after every action. No object state, contact, reward or native success enters the actor. Unmodified RGB is preserved byte-for-byte before transmission in the raw group. Actor text is identical for the same observation; image bytes are the only input difference.

Existing task processing, stage graph, internal thresholds, motor scaling and budgets remain frozen. Thus this compares actor inputs within the established controller; it is not pure RGB control. Removing explicit positional feedback and point markers can leave intermediate stage goals visually ambiguous. This limitation applies to both groups.

## Cases and execution

| Task | Initial states in each group |
|---|---|
| 1098 | 6, 7, 8 |
| 1144 | 5, 6, 7 |
| 1163 | 5, 6, 7 |
| 1202 | 3, 4, 5 |
| 1252 | 4, 5, 6 |
| 1296 | 12, 13, 14 |
| 1335 | 23, 24, 25 |
| 1383 | 8, 9, 10 |
| 1423 | 10, 11, 12 |
| 1458 | 11, 12, 13 |

Total: 60 effective episodes. Same frozen initial states and policy source hashes in both groups. Company-server-2 physical GPUs4/5 run arrows; GPUs6/7 run raw. A bounded first episode per group checks resources and outgoing inputs, then the same immutable campaign resumes for the remaining cases. Concurrency may change without changing the inference contract.

Profiles: `libero-rgb-gripper-pair-arrows-v1`, `libero-rgb-gripper-pair-raw-v1`.
Roots: `code/runs/2026-10-17-libero-gripper-pair-{arrows,raw}-v2`.
Preparation: `code/runs/2026-10-17-libero-gripper-pair-preparation`.
Archived-input audit: `code/runs/2026-10-17-libero-gripper-pair-input-audit`.

Ordinary answered failures remain failures. Never repeat sampling to obtain approval or success. Preserve all interrupted attempts; explicit no-response connection failures may receive complete source-linked replacements in separate roots. Schema/model errors are not transport replacements. Report all original attempts and the effective subset separately.

## Evaluation and records

Report native success and joint native-plus-program completion separately, overall and per task (n=3). Record terminal stage, decision count, API errors, frame counters, actual image hashes and actual outgoing text. Compare direction choices with the old camera-derived residual rule only as a diagnostic, not as privileged truth. Paired initial-state outcomes are descriptive with this small sample; do not infer a general model capability ceiling.

The initial v1 bounded startup probe for task1098/init6 in both groups stopped before network dispatch and before any native step: duplicate `experience_injection` dispatch metadata. Both original outcomes are retained as implementation faults, not model failures. V2 removes the duplicate audit keyword, without changing the actor input. Its full60 episodes are separate.

English experience is collected only after results, without loading it into either model. Protocol EXP, activity, Discussion and result artifacts retain both positive and negative outcomes. This finite comparison closes the current test rather than repeatedly rerunning a normally failed version.

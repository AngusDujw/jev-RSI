# Diagnosis of the paired RGB failures — 2026-10-18

This is an analysis of existing evidence, with zero new model calls and zero new simulator steps. The60-episode results and every previous attempt remain unchanged. No actor/planner prompt or control policy was modified.

## Findings and strength of evidence

### 1. The visual goal does not specify the waypoint tested by the controller

Confirmed for task1144/init5. The actual actor contract says:

```text
Approach above source with gripper open. Advance when the target is reached.
```

The frozen supervisor instead constructs a particular point: source XY and a height14cm above the higher of the measured source/destination upper surfaces. It tests arrival with a maximum axis error below8mm. The current actor receives neither that waypoint nor a visual target region defining its height. A false arrival boolean supplies no direction or distance. Many different poses satisfy the ordinary-language phrase "above source".

The old explicit goal-minus-current vector supplied the missing relative target. Removing it did not remove the original numerical waypoint or arrival gate. The experiment adaptation therefore left the visible goal and the internal contract insufficiently connected. This is a confirmed interface limitation; its isolated contribution to the zero success rate has not been measured.

Source: frozen task1144 `libero_jev_supervisor.py`, lines213,244,265 and290. The exact frozen source is under `code/runs/2026-10-16-decision-mm-preparation/frozen-baselines-complete/task-1144/`. Actor question replacement: [libero_inframe_axes.py](libero_inframe_axes.py), lines192–203.

### 2. The request cannot support comparison with the previous action

Confirmed in both complete1144 examples. Each request contains only the current external/wrist images. It contains no previous image pair, previous response or previous XYZ categorical choices. The last actual retained history is:

```json
[{"gripper":"open","transition":"continue_phase"}]
```

The original supervisor history stores gripper/transition plus numerical progress and displacement. The input reduction removes those numerical entries without adding categorical XYZ history. Consequently, the motion description asks the model to check subsequent images, but a subsequent request does not supply the previous observation/action needed for that comparison. Freshness of each image pair does not provide temporal feedback by itself.

Source: [libero_inframe_axes.py](libero_inframe_axes.py), `categorical_history` and `payload_from_views`; [libero_multimodal.py](libero_multimodal.py), `ObservationStream`; frozen supervisor line373.

### 3. Many direction distributions are weakly separated, and some confident choices are wrong

All effective existing responses were analyzed. The following subset includes only XYZ questions outside the original camera-derived deadband, excluding grasp/release phases:

| Diagnostic | Arrows | Raw |
|---|---:|---:|
| Axis choices | 3554 | 3463 |
| Sign agrees with original residual rule | 979 (27.55%) | 786 (22.70%) |
| Selected-option probability below0.5 | 1809 (50.90%) | 1770 (51.11%) |
| Top-two probability gap below0.1 | 1285 | 1157 |
| Median selected probability | 0.49 | 0.49 |
| Median reported confidence | 0.24 | 0.24 |
| HOLD outside original deadband | 1241 | 1414 |
| Selected choice below the maximum returned probability | 0 | 0 |

The executor consumes the selected categories without a confidence-based information-recovery branch. These probability summaries describe the returned distributions, not calibrated correctness probabilities. A higher threshold alone would not fix the interface: the last raw1144 Z-positive answer had probability0.69, yet increased a downward stage residual. Indefinite HOLD or repeated same-image sampling is not supported as a remedy.

### 4. The inspected controller does not reverse command signs

Confirmed in the two complete1144/init5 robot trajectories, not asserted for all possible configurations. For components with commanded increments at least2mm and measured displacements at least1mm, command/motion signs agreed54/54 times with arrows and61/61 without arrows. This filter excludes small coupled drift and does not prove exact magnitude tracking.

At arrow decision0001, the camera-derived Z residual was−87.91mm. The model chose Z-positive; the command increment was+20mm and the measured net Z displacement was+9.155mm. The robot followed the requested sign while moving away from the internal height target. This is a decision/goal-interpretation failure in that step, rather than a sign inversion in the executor.

Across the45 decisions, target-distance progress was negative in31 arrow steps and37 raw steps. The source-to-waypoint residual is the original permitted camera-processing reference, not privileged object truth.

The frozen controller repeats an increment for three native steps before the next model observation. Wrong choices can therefore accumulate displacement before another review. A one-step alternative is a proposed isolation test, not an observed fix. Historical full-feedback results also show the shared controller can complete tasks; they are not a newly randomized control for this diagnosis.

### 5. Arrow disappearance is an amplifier after the hand leaves view

The prior audit found the origin in frame for2610/2900 arrow views. The final external1144 arrow image shows the gripper outside the image, so the glyph is correctly omitted. This deprives later decisions of that view's directional cue, but it does not explain the initial errors while arrows were present.

## Recommended next isolation test

1. Define one simple, visible intermediate relation and make its arrival check agree with that relation. Explicitly identify the source and the part of the hand being compared. A full hidden3D waypoint should not be assumed to follow from "above source".
2. Supply the previous/current image pair and the last categorical XYZ choice, with clear camera/time labels. This does not require EEF coordinates, K/T matrices, numerical tolerances or numerical residuals in actor input.
3. Test a short approach on one translation axis before another complete benchmark batch. Check object identity, spatial relation, selected direction and measured motion separately. If visual relation/direction remains unreliable, add only the corresponding algorithm-derived evidence in a separately frozen condition.

These are outer experiment recommendations, not new internal-model instructions. They have not been deployed or claimed successful. Existing paired failure data is retained.

## Reproduction

Tool: [diagnose_gripper_pair.py](diagnose_gripper_pair.py).
Remote: company-server-2, existing project worktree. No GPU allocation or simulator/API execution is needed.

```bash
python3 -B code/decision_multimodal/diagnose_gripper_pair.py --audit code/runs/2026-10-17-libero-gripper-pair-input-audit-v2/final-outcomes-audit-v2.json --output code/runs/2026-10-18-libero-gripper-pair-diagnosis/analysis.json
```

The command is one line. Local artifact copy: `code/runs/2026-10-18-libero-gripper-pair-diagnosis/analysis.json`. It preserves the full45-step measured-motion diagnostics for both1144 examples, actual selected probabilities, and current retained history. The original source requests and images remain in the prior evidence folder.

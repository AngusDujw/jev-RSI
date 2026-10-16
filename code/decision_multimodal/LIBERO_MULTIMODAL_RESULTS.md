# LIBERO multimodal Decision comparison — 2026-10-16

## Main result

The current image input does not replace the removed XYZ feedback reliably.
All ten tasks have three effective paired episodes per condition. No experience
was injected. Native success and successful program completion are separate.

| Actor input | Native success | Native + program completion | Nominal nonzero-axis agreement |
|---|---:|---:|---:|
| Latest per-task historical text reference | 27/30 | 27/30 | Not recomputed |
| Structured text + named current RGB + public camera/robot context | 21/30 | 20/30 | 4524/4676 =96.75% |
| Remove XYZ feedback; retain projected goal/reference markers | 0/30 | 0/30 | 1016/3751 =27.09% |
| Remove XYZ feedback; raw RGB and semantic stage goal | 0/30 | 0/30 | 940/3645 =25.79% |

The text reference uses the same initial states from the latest fixed per-task
versions, not a fresh single-version text campaign. The old31/50 result is a
different denominator. Axis scores compare returned advice with the original
camera-derived nominal residual rule, not true object pose or physically optimal
action. Repeated decisions within an episode are correlated.

## Per-task result

Cells show native/program joint successes out of three unless stated otherwise.

| Goal | Task | Historical paired text | Full RGB input | No XYZ, markers | No XYZ, raw |
|---|---|---:|---:|---:|---:|
| 1098 | Middle drawer | 3 | 3 | 0 | 0 |
| 1144 | Bowl to stove | 3 | 2 | 0 | 0 |
| 1163 | Bottle to cabinet | 3 | 3 | 0 | 0 |
| 1202 | Open drawer and insert bowl | 0 | 0 | 0 | 0 |
| 1252 | Bowl to cabinet | 3 | 2 | 0 | 0 |
| 1296 | Plate to front stove | 3 | 3 | 0 | 0 |
| 1335 | Cheese to bowl | 3 | 3 | 0 | 0 |
| 1383 | Stove knob | 3 | 3 | 0 | 0 |
| 1423 | Bowl to plate | 3 | 1 | 0 | 0 |
| 1458 | Bottle to rack | 3 | 0 (native1) | 0 | 0 |

Full-input failures included exhausted reobservation in lift1144/1252, carry
budget or stop1423, stop1458, and the already unstable compound task1202.
The reduced-input runs mostly exhausted their approach/alignment budget or
failed to progress through drawer selection. A high per-axis score is therefore
insufficient to establish correct stage transitions or complete manipulation.

## What was sent

- Actor: du `gpt-6-luna` Decisions. Input text and all experience notes are English.
- Input design: local ChatGPT Pro `gpt-6.1-sol`, high reasoning. Runtime task
  stages remain the frozen LIBERO policies; no fresh planner action is inserted.
- Two fresh RGB images: `agentview` is a fixed external camera;
  `robot0_eye_in_hand` is attached to the wrist and moves with it. Each image
  has its own explicit text label and the shared observation counter.
- Current public camera K/T and measured robot state accompany the images.
  The actor receives no depth image, object ground-truth state, contact,
  reward or native success. Original frontend processing still uses RGB-D.
- The reduced inputs remove XYZ residuals, sign relations, absolute frontend
  target coordinates, equivalent numeric question text, geometric summaries
  and residual-scaled action history. Current-stage semantic goals replace
  geometry-bearing contracts. Extra candidate categories lose metric geometry
  and can lack a visible identity correspondence.
- Original completion/holding booleans, phase permissions, rotation feedback,
  frontend and controller-internal amplitude remain. Returned directions are
  never corrected; zero residual can still produce zero controller amplitude.

This is a declared actor-translation-input ablation. Several equivalent XYZ
representations are removed together; it is not a single-field causal test.
The marker condition supplies processed target evidence. The raw condition
can underdefine invisible intermediate waypoints. Neither is perception-free
control, and neither failure establishes that all multimodal models lack ability.

## Separate image diagnostics: zero robot actions

| Diagnostic | Result | Meaning |
|---|---|---|
| Two colored-shape layouts, four calls each | 8/8 | Basic image-dependent classification works; only two unique layouts |
| Small target/reference image relations | 36/66 judgments across24 observations | Current small markers are not read reliably |
| Single fixed-camera follow-up on six specified cases | 8/12 | Some errors remain with one image; not a matched27-case improvement |
| Marker input with identical wording, no ruler | 34/74 nonzero axes,27 observations | Paired coordinate probe baseline |
| Same observations plus public XYZ ruler | 35/74;5 whole XYZ choices changed | No material rescue from this ruler |
| Raw input with images removed | 0/65 nonzero axes,23 valid of25 attempts | Advice shifted to HOLD; two connection failures retained |
| Original image answers on those same23 cases | 33/65 | Images change advice, but do not make it reliable |

The ruler projects fixed0.05m positive world axes from measured EEF using
public current K/T. Its appearance never depends on the target or residual.
Both paired ruler conditions have identical text. Targets outside the image or
behind a camera are omitted, not clamped. A projected marker is not contact
or clearance evidence.

Selection was the first received nonzero-error observation per source episode:
27 eligible marker episodes and25 eligible raw episodes. Unavailable observations
are listed in the audit. No decision was repeatedly sampled until approved.

## Network faults and denominator

All174 native attempts are preserved:30 full-input,60 first reduced-input,
60 lower-concurrency network checks, and24 explicit connection replacements.
The first two reduced batches each had12 interrupted episodes. The later
network checks still had16/15 connection faults and remain separate results.

Only the first batches' connection-interrupted episodes received a new complete
episode. Original normal failures were retained. The effective comparison uses
18 original normal outcomes plus12 explicit replacements per reduced condition,
with zero terminal API failures in these selected90 comparison episodes. Every
case links to its original or replacement asset; no original outcome is hidden.

The174 attempts and117 read-only diagnostic calls are different populations.
The latter contain two connection failures and contribute zero native episodes.
All required foreground experiment processes have finished.

## Audit, assets and reproduction

Company workspace:

```text
/root/yekangjie/project/jev_rsi/.worktrees/decision-multimodal-20261016
```

Original full-input source: `f07f7ac4`; reduced-input inference source:
`8975ed69`; explicit replacement runner: `a58dca5a`, with inference hashes
checked against the original reduced-input campaigns. Physical GPUs4–7 only;
existing environments, no driver changes.

Final audits and compact local copies:

- [Effective comparison and case provenance](../runs/2026-10-16-libero-mm-preparation/effective-multimodal-audit.json)
- [All original comparison attempts](../runs/2026-10-16-libero-mm-preparation/original-multimodal-audit.json)
- [Independent network-check attempts](../runs/2026-10-16-libero-mm-preparation/network-check-audit.json)
- [Read-only probe audit](../runs/2026-10-16-libero-mm-preparation/visual-probe-audit.json)
- [Axis-ruler image preview](../runs/2026-10-16-libero-mm-preparation/axis-preview-agentview.png)

Full request/response/PNG assets remain in company `code/runs/2026-10-16-libero-*`.
Every real request saves original and revised legacy text, actual serialized
provider input, image hashes, received response and normalized categorical output.
Image bytes/base64/SHA, observation counters, English text, model identity and
raw answer mappings passed audit. Detailed reproduction commands are recorded
in EXP-2026W42-220 through224 and [the experiment contract](LIBERO_MULTIMODAL.md).

## Files added or changed for this comparison

- `libero_multimodal.py`: fresh public RGB/proprioception capture, camera labels,
  public calibration, exact serialized image audit, separate asset budget.
- `libero_visual_ablation.py`: explicit XYZ-input masking and waypoint overlays.
- `libero_visual_probe.py`: deterministic, read-only ruler/no-image probes.
- `libero_entry.py`, `libero_prompt_revision.py`: multimodal payload hooks and
  separately declared profiles; original action choices are preserved.
- `run_libero_campaign.py`: paired3-episode conditions, resource limits,
  foreground execution and explicit transport-only episode replacement provenance.
- `README.md`, `LIBERO_MULTIMODAL.md`, this result file, `EXPERIENCE.md`:
  contracts, results and short collection-only English findings.
- Repository `LOGS/2026-W42.md`, activity log, `Discussion.md`, `TIMELINE.md`:
  version-specific evidence and convergence. No method/primary-metric change.

## Next useful input change

Retain structured metric feedback for reliable current control. If testing
further removals, first improve goal/reference visual readability or remove
one axis/one processing product at a time. Keep hidden-waypoint ambiguity,
categorical identity, stage transitions and image interpretation as separate
failure sources. Do not repeat the unchanged three-condition batch to seek a
better sample, or describe the marker condition as raw-image autonomy.

## Inspected failure video: Goal1144 / init7

The user-requested evidence export uses the original normally failed episode,
not a new rollout:45 received decisions,135 native steps, always `approach`,
no API failure, ending `Stage/native budget: approach`.

The actual English stage goal was:

```text
Reach the predefined approach or clearance waypoint for the source or control named by the task.
```

The actual world-X question was:

```text
For world X, which existing categorical direction brings the measured control reference toward the current stage goal? Use the current camera evidence, public calibration and measured robot state. Keep the control point still in gripper-only stages. Image up/right is not a fixed world direction. Use the original tolerance and output categories; no numeric residual is supplied.
```

This input places substantial inference work on the actor. It removes metric
residuals, directional relations, absolute targets and action history together,
and gives a generic stage description plus small projected markers and camera
matrices. It does not provide an immediately usable per-axis image-motion guide.
The white circle is the robot control reference, not a finger contact point.
The yellow cross is the active waypoint, not necessarily an object-surface point.

At the first decision, the withheld frontend errors were
`(+116.10,+13.04,-69.43)mm`, but the actor selected `negative,negative,negative`,
with XYZ confidence `.31,.19,.24`. The first executed command was
`(-20.00,-6.52,-20.00)mm`, and measured X moved about`-9.22mm`.
X was negative in43/45 responses; Y was negative in45/45.
At the last decision, withheld X error was`+260.83mm`. From decision4/native
step9 onward, the wrist target marker was out of frame in42/45 inputs, while
the fixed-camera target remained in frame. The same categorical interface
continued issuing low-confidence directions without a specific lost-marker
recovery procedure. These are representation/execution-interface limitations,
not evidence that the task graph itself was successfully followed.

- [75-second complete decision review](../runs/2026-10-16-libero-video-evidence-1144-init7-v2/episode_with_actor_inputs.mp4)
- [Raw RGB snapshot playback](../runs/2026-10-16-libero-video-evidence-1144-init7-v2/raw_episode.mp4)
- [Actual first request text and response](../runs/2026-10-16-libero-video-evidence-1144-init7-v2/first_actual_prompt_and_response.txt)
- [All45 actual inputs/outputs, image bytes externalized](../runs/2026-10-16-libero-video-evidence-1144-init7-v2/all_45_actual_inputs_outputs.jsonl)

The review includes every saved decision observation, holds each for1.5s, omits
API waiting time, and finishes with saved raw RGB after step135. It is a
snapshot replay, not a continuous original screen recording. The two attached
first-input PNGs preserve original bytes; video is H264. Pink XYZ numbers in
the review are post hoc audit values and were not sent to the actor. Legacy
`decisions.jsonl` stores pre-ablation observations; the export instead uses the
actual serialized provider request so those legacy numbers cannot be mistaken
for model-visible input. All90 input image blocks passed PNG/base64/SHA checks;
both MP4s decoded without error. Renderer: `render_libero_episode.py`.

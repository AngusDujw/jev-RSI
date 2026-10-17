# World-axis arrows attached to the current gripper

Profile: `libero-rgb-gripper-axes-v1`. This supersedes the corner-anchor preview
for the user's next input review. It has not produced a new model response or
native task result. The archived episodes are evidence for rendering only.

## Actor-visible changes

- `agentview`: green +Y and blue +Z; no +X arrow.
- `robot0_eye_in_hand`: red +X and green +Y; no +Z arrow or depth symbol.
- Both axes start at the current measured own gripper control reference projected
  into that particular RGB image. No separate point circle or goal cross is drawn.
  Their shared origin deliberately supplies the requested visual gripper reference.
- The drawing code uses the latest public camera calibration and own measured
  gripper position internally on every capture. Numerical K/T and EEF coordinates
  remain excluded from actor text. Original numerical tolerance fields also remain
  excluded. Existing stage booleans, gripper feedback and internal control remain.
- Arrow direction is the local projection derivative for a positive world-axis
  displacement at the current gripper reference. Length is normalized for display;
  it is not a movement magnitude. If the origin is out of frame or behind the
  camera, no arrows are attached to an image edge.
- English model description: `libero_gripper_axes_description_v1.txt`. It explains
  the selected axes, negative directions, omitted channels and moving-wrist view.

## Motion-following audit

Actual archived full-input Goal1144/init5 decisions0000/0010/0020 correspond to
native observation counters10/40/70. No new robot actions were executed.

| Observation | External-camera origin(px) | Wrist-camera origin(px) |
|---|---|---|
| 10 | (377.77,180.80) | (384.00,641.96) |
| 40 | (377.20,317.92) | (384.00,642.14) |
| 70 | (415.34,369.06) | (384.02,642.56) |

The measured own gripper translation between the first and last frame is
194.695mm. The external-camera arrows move with it. A wrist camera moves with
the hand, so the origin remains near the same pixel while the scene moves.
All six images preserve original scene pixels outside the exact arrow/label mask.
Each shown arrow agrees with a5mm robot-only positive-axis projection check;
this is calibration self-consistency, not scene-object geometry validation.

## Sources and reproduction

Internal source/pose/camera provenance, three prepared request sets and
`tracking-audit.json` are in:

```text
code/runs/2026-10-17-libero-gripper-axes-preview/
```

All actual scene pixels come from the unmarked full-input archived PNGs. Only
their old160px footer is removed before drawing the new arrows. New request
files are explicitly named `NOT-SENT`; the six PNGs are newly prepared previews.
Final request sets are under `prepared-v2/`: a legacy descend phrase "when within
tolerance" is replaced by "when the current arrival check passes". The original
arrival boolean and internal controller are unchanged. Remaining tolerance wording
in actor text is rejected before sending. Images are byte-identical to the first
rendered preview sets.
No experience, new model call, simulator run, environment or driver change.

Single-line reproduction command; output must not already exist:

```bash
python3 -B code/decision_multimodal/libero_inframe_axes.py --gripper-axes --source code/runs/2026-10-17-libero-gripper-axes-preview/source/0020 --output code/runs/2026-10-17-libero-gripper-axes-preview/prepared/reproduce-0020
```

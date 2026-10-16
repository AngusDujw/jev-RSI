# LIBERO Decision multimodal input comparison

## Fixed tasks and paired states

Ten existing tasks, three episodes per condition, using the first three states
from each original frozen five-state manifest. This is paired evaluation, not
unseen-layout generalization. Task1202 is an unstable exploratory reference.

| Goal | Initial states | Text profile |
|---|---|---|
| 1098 | 6,7,8 | Original |
| 1144 | 5,6,7 | Clarity v2 |
| 1163 | 5,6,7 | Original |
| 1202 | 3,4,5 | Clarity v2 |
| 1252 | 4,5,6 | Clarity v2 |
| 1296 | 12,13,14 | Clarity v2 |
| 1335 | 23,24,25 | Original |
| 1383 | 8,9,10 | Original |
| 1423 | 10,11,12 | Clarity v3 |
| 1458 | 11,12,13 | Original |

## Predeclared conditions

1. `libero-rgb-full`: latest structured task text plus two current RGB images.
   Identify the fixed external `agentview` and moving wrist
   `robot0_eye_in_hand`, label their native observation counter, and provide
   public current K/camera-to-world transforms and measured robot state.
2. `libero-rgb-waypoint`: remove actor-visible translation residuals, axis
   relations, equivalent absolute frontend targets, diagnostic progress,
   residual-scaled command history and numeric copies in questions. Supply
   plain stage semantics instead. Render a fixed yellow cross for the original
   active positional waypoint and a white circle for the measured robot control
   reference in each current image. The markers are processed target evidence;
   this condition is not raw-image autonomy.
3. `libero-rgb-raw`: the same masked structured input and stage semantics,
   with raw current RGB instead of waypoint/reference annotations. Invisible
   intermediate targets can be underdetermined. Failure here does not establish
   that the model cannot understand images.

The original categorical values/order, native stage graph, frontend, controller
and evaluation remain unchanged. Original permissions, arrival/holding booleans
and rotation residuals are deliberately retained; they reveal some processed
information. Candidate categories without metric geometry may lack a visible
identity correspondence. These are translation-input ablations, not removal
of every visual processing result.

The original controller continues to use its private-to-the-actor residual to
scale a returned sign, including zero amplitude at zero error. Raw returned
choices are never corrected. Task success alone therefore cannot prove every
axis recommendation correct; report agreement against the original
camera-derived residual separately, especially on nonzero-error axes.

## Runtime and audit

All actor text is English; experience is collected but never injected. Use
du `gpt-6-luna` Decisions and local ChatGPT Pro `gpt-6.1-sol/high` for input
design. The saved Pro input contract is in
`code/runs/2026-10-16-libero-mm-preparation/pro-input-design/`.

The observer copies only RGB and robot sensor fields from public reset/step
returns. It does not read reward/done/info or scene object states. Public
camera calibration is refreshed at capture. No extra physics step is taken
to obtain an image. Both images belong to the same returned observation;
the counter includes ten neutral warmup steps and is not a wall-clock timestamp.

Image/API assets stay on the company project volume in each episode's
`multimodal/` folder, outside the historical recorder byte limit. An audit
symlink preserves old request counting without changing the control budget.
Save original text, actual masked text, serialized provider input, image paths
and hashes, received answer and normalized answer. Preserve all failures and
never resample an answered decision.

For marker images, do not clamp off-image or behind-camera points. Marker color,
size and shape never encode residual magnitude or preferred sign. The projected
annotation can lie behind a surface and does not prove visibility or clearance.

Read-only raw-image shadow comparisons may remove images from one deterministically
selected nonzero-error request per episode, preserving all its remaining text
and options. They execute no robot action and are not native episodes. Their
reference is the original frontend residual, not true object geometry.

The input image schema follows the official
[Decisions API reference](https://developers.openai.com/api/reference/resources/decisions/methods/create).
A saved two-image API probe judged the stove to the right of the bowl in the
fixed image and lower-left in the wrist image, matching inspected pixels. This
checks transport and a simple visual relation; it is not a task success.

## Execution

The first30 `rgb-full` episodes were launched atf07f7ac4 on physical GPUs4–7,
three foreground jobs per GPU. Masked variants are frozen separately after
that batch ends. Never replace an in-flight frozen adapter. Later conditions
can use disjoint GPU pairs with at most six jobs per GPU, based on observed
memory use and disk headroom. No driver/CUDA changes or new environments.

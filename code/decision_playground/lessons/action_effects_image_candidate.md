# Candidate evidence: raw images paired with measured robot translations

Status: robot-response evidence, not a validated object-manipulation Skill.

## Source

`playground-action-image-20261022f` is an outer-controlled diagnostic on GPU1,
layout1. It made zero model calls and did not attempt the object task. One episode
recorded three positive 20 mm world-axis translations of the right configured TCP,
with orientation held. There were no resets between these three probes.

| Requested axis | Measured right TCP displacement, mm | Target error, mm |
|---|---|---:|
| X+ | `[19.924731, 0.006477, 0.000225]` | 0.075548 |
| Y+ | `[-0.081270, 20.004298, 0.000834]` | 0.081388 |
| Z+ | `[-0.080832, 0.006449, 19.997943]` | 0.081115 |

The source retains raw head and wrist RGB at steps0/5/10/15 plus the text ledger.
No intrinsics, extrinsics, projection matrices, image-point coordinates, target
coordinates, object truth, contact, or task-result evidence is constructed.

## Selection for the current development check

Revision r004 selects the raw head frames at0/5/10: before X+, after X+, and after
Y+. Captions contain the recorded robot command and measured displacement. The
source scene is explicitly historical and different from the current layout.
These commands are past observations, not prescribed future actions or an object
route. The current images remain the source for the current manipulation geometry.

The prior reorientation candidate is not selected here: recent reorientations
tracked, while the old translation failure predates those reorientations. The
static r003 failure summary is also removed from selection. All earlier revisions
and their negative checks remain preserved. This is an applicability/selection
change in development, not a clean causal estimate of a single image's effect.

## Limits and required check

The example concerns one robot, view, and local response range. Do not treat it as
camera calibration or presume identical effects for another view/configuration.
The model must choose its own current action from current evidence. Validate
actual requested-versus-achieved motion and visible alignment toward a grasp
region, rather than counting non-hold choices. Closure, retention, complete task
performance and held-out transfer remain separate unproven claims.

After at most two reviewed segments without useful approach progress, record the
negative result instead of repeatedly presenting the same demonstration.

## Observed development check

Revision r004 made six Decisions calls. The first three only closed/opened/held.
The next two downward20mm commands tracked to approximately0.070mm error but did
not establish target alignment or a grasp. The last command encountered four IK
failures, then a raw joint target with equivalent angles near positive/negative
2pi. The Playground had bypassed the baseline continuity guard, causing a large
unintended motion. Stop at this execution defect: the contaminated final response
cannot be used to judge action understanding. This example is not promoted; the
implementation must pass its execution contract before further policy evaluation.

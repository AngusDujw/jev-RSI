# Generic Decisions grasp development

User-authorized priority on 2026-10-19: first establish generic grasping with the
actual OpenAI Decisions endpoint, then derive a local-Pro planner contract from
verified advancer requirements. Only after stable grasping, select an officially
high-performing task that plausibly needs orientation adjustment.

First condition: current three RGB images, measured robot state and the same
English generic manipulation prompt across objects/layouts. No object truth,
contact, reward, success flags, previous steps, experience or task-specific route
is supplied. Fourteen categorical answers control both arms. TCP is public X5
LINK6-local [0.15007, 0, 0] meters; world yaw/Z, pitch/X, roll/Y; per component
20 mm, 0.10 rad; at most one rotation per arm. Invalid outputs are retained and
rejected without repair, projection or resampling. Native IK and scoring remain
the original GPT-as-Policy adapter. Official general_pickup horizon is 200.

V1 ended incomplete at10 steps: its third actual Decisions answer selected two
right-arm rotations. Three requests were HTTP200, with fresh three-RGB input.
No response was repaired. On2026-10-19 the user approved V2: each arm's three
rotation questions become one seven-choice rotation question. Ten API questions
are decoded into the original fourteen directions; all49 legal dual-arm rotation
combinations map bijectively. The V1 prompt and observations otherwise stay fixed.
V2 fresh development episodes run at most two in parallel, one per GPU.

Pilot/development layouts: official eval group0 IDs0–4. Do not resume any ended
episode. A changed prompt/input is a named new condition. Retain all outcomes.
Before claiming stability freeze the prompt/input/action/execution condition,
then require at least9/10 native successes in each of two independent held-out
blocks (IDs5–14 and15–24), without tuning between them. Report actual object
coverage and all invalid/layout/service failures separately and conservatively.
This operational criterion does not establish performance on every possible
object or long-duration holding beyond the native task.

Images are encoded in memory for the Decisions request and are never written as
PNG/NPZ image files. Native duplicate frame/video recording is disabled. Keep
compact prompts, questions, image hashes, answers, measured actions and native
outcomes; no large request payload or video archive. Planner code has not yet
been introduced: it must be tested against successful advancer inputs rather
than assumed effective from a plausible prompt.

The separate original Pro comparison remains active. New pilot admission requires
8GiB free GPU memory,20GiB available host RAM and fewer than three total registered
policy/grasp simulator containers; no sharing with foreign GPU occupants.


2026-10-20 audit: the original joint-v2 layouts 0/1 ended incomplete at native
90/92 steps with server_close after interruption; do not resume either. The
fixed Pro comparison is now complete. Fresh development runs use a dedicated
local execution directory (server02-decision-grasp-20261020), the current owned
comparison SSH master, and a mandatory unique --run-tag. Native terminal JSON
is fetched from the remote campaign after the simulator exits. Optional
--save-images in the controller preserves current camera evidence for external
review, without adding image history or changing model inputs. The runner
enables this option. The generic prompt and joint-rotation condition stay fixed.
No planner has been introduced and no stable grasp performance is established.


The fresh 20261020a joint-v2 development batch ended at 200 steps in all three
layouts, with 0/3 native successes. No service or rotation-format failure
explains these complete outcomes. Do not resume them. A new optional
--geometry-overlay condition (rgb-calibrated-v3) provides current camera K/T
and projects only measured robot TCPs and +20mm world-axis segments into RGB.
The server wrapper reads camera/robot mounting geometry and environment origin,
never scene object poses/contact/reward/success for model input. Raw and actual
annotated model images are retained. These geometric markers can be occluded
and are not target annotations or grasp evidence. This is a visual-geometry
input package, not an isolated proof that annotations improve policy quality.
Prompt/task/action/physics/scoring remain otherwise unchanged. Validate actual
rendered projection agreement before claiming precise visual alignment.


2026-10-20 terminal override: calibrated-v3 layouts0/1 and the independent
layout2 b3 replacement all completed200 steps with native failure (0/3).
The earlier layout2 b155-step HTTP503 and b2 145-step TLS failures remain
separate infrastructure interruptions. No ended episode/request is resumed.
Raw and actual annotated input PNGs are retained for external review; this
supersedes the initial no-PNG policy above. The fixed comparison is complete.

New independent --alignment-guidance requires --geometry-overlay and joint
rotation and selects rgb-alignment-v4 / advancer_alignment_v2.md. Only the
English prompt changes: relate measured finger/jaw axes to visible support and
grasp-region clearance, choose orientation corrections before entering when
needed, and close only after visible enclosure. No object-specific path, target
coordinates, hidden evidence or deterministic action override is introduced.
The three images, K/T, action questions/scales and native scoring stay fixed.
This hypothesis follows v3's240 all-hold arm-rotation selections; selecting a
rotation or closing alone will not count as improvement. Development0/1/2
precedes the unchanged frozen held-out gate. If infrastructure interrupts again,
perform offline transport diagnosis before another episode; do not API-probe.


Alignment-v4 ended with three complete200-step native failures (0/3), all120
requests HTTP200, no close selections, and103/240 arm rotations non-hold.
All ended workers are gone. No same-condition repeats are scheduled.

The independent --rotation-effects flag requires alignment guidance and selects
rgb-effects-v5. It adds only rotation_effects_world and an English table legend
to the current input. For each arm and each of the seven unchanged choices,
R_candidate = R_world_increment @ R_measured; columns0/1 are the predicted
finger-extension/jaw-sliding directions. These are robot-only commanded effects,
not reached poses, target/obstacle estimates or collision/contact evidence.
All choices are enumerated without ranking or selecting. V4 prompt, cameras,
questions, action scale, physics and scoring otherwise stay fixed. Offline245
paired options matched the executor axes and invariant TCP within1e-12m.
No improved task performance is established. The original hold-out and planner
stability gates remain unchanged.

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

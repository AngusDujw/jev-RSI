# Decisions Playground

User-authorized on 2026-10-22 for `company-server-2-ykj`. Reuses only the existing
RoboICL simulator/environment builder; never launches its ordinary API policy.
Only the authorized du credential and `https://api.openai.com/v1/decisions` are used.

`native_server.py` keeps one simulator alive behind a loopback JSON RPC. Explicit
Playground reset starts a new attempt UUID and preserves the previous attempt's
classification. Native terminal success is separate from development stops. The
original evaluator's unconditional final score-writing path is bypassed; native
task predicates remain unchanged. User authorization later on 2026-10-22 expands
the development action limit to 5x: general_pickup 200 -> 1000 steps. Both limits,
the multiplier, and official-budget comparability are recorded in every status.
The launcher defaults to `--native-step-multiplier 5`; use 1 for a separately
declared official-budget condition. No upstream task source is edited. No camera calibration is
requested or exposed. The configured tool-local [0.15007,0,0] center is a control
reference, not a simulator-provided contact point or a measured grasp location.

`contract.py` selects ten categorical fields across two arms, losslessly encoding
one rotation per arm. Fixed increments are 0.020m and 0.10rad. Raw link-frame world
quaternion targets go directly to native world-mode IK; relative-mode robot
delta rotations must not be applied. The initial X5 delta was identity, so the
initial adapter's redundant multiplication had no numerical effect.
State gripper values are previous normalized commands, not measured apertures.

`worker.py` keeps the latest two completed interactions in memory, including
selected actions, before/after measured robot state, and optionally prior images.
Every three actual Decisions calls it stops dispatching and writes `review.json`.
The outer agent examines raw images and text, then writes `command.json` with a
strictly increasing `sequence` and `op=continue|reset|stop`; reset requires a reason.
Knowledge revisions are loaded only between segments, never midway through one.
The worker does not automatically reset, retry a failed API request, or replay an
uncertain native operation. Native-ended attempts require explicit reset or stop.

`launch.py --native-only` admits idle assigned GPUs and starts only native servers.
First validate readiness, raw RGB, current poses, and a zero-motion native step;
then explicitly start workers. Initial eight-card design pairs layouts0–3 with
recent text+images on GPUs0–3 versus recent text only on GPUs4–7. Current three
RGB and action semantics are identical. These are development attempts, not
held-out benchmark scores. Each worker starts empty memory; revised knowledge is
explicitly recorded. Additional same-GPU capacity is admitted only after measured
peak memory and review throughput justify it, never by killing foreign processes.

Only one preselected attempt per batch/task uses `--retain-history`. Other workers
keep current review PNGs temporarily and bounded image memory, with full text
ledgers retained. Do not delete the one retained history or images referenced by
active visual lessons. No old `experience/` bank is read. Model text and newly
authored skill/lesson content must be English; root review notes stay outside the
model payload. Images demonstrate conditional evidence, never a route to replay.

Stop a policy worker via SIGTERM or review `stop`; no additional model call is made
after it observes stop. For immediate cancellation of an in-flight curl, terminate
only that worker's owned process group and classify delivery unknown; never resend.
Native servers may be closed by RPC `close` or their owned process signal. Do not
restart an ended attempt as though it were a continuation.

The native adapter writes outer-only `ik.jsonl` diagnostics: original solver status,
target joints, and before/after robot measurements, keyed by attempt, request and
native step. The wrapper calls the original solver exactly once and preserves its
return or exception. It does not change IK tolerances, scoring, action selection,
or model inputs. A consumed native step does not establish successful IK or motion.

`lessons/feedback_probe_candidate.md` records the first image-backed development
candidate and its unsuccessful first check. It is not a promoted Skill. Knowledge
revisions are explicit and immutable in each campaign; avoid expanding a candidate
that has not improved the intended measurable behavior.

Recent interactions also carry `execution_feedback`, computed from the decoded
TCP target and measured post-action state: requested/achieved world translation,
position-target error, and SO(3) orientation error. This is a measurement-only
comparison; it neither changes actions nor infers collision, retention, or task
outcome. The reorientation-after-nontracking candidate records one controlled
tracking recovery and requires independent policy checks before promotion.

The Playground installs the existing baseline IKContinuityGuard from the shared
harness configuration (default enabled, maximum increment0.15rad). It preserves
raw solver diagnostics and lets the native guard normalize legal periodic joint
equivalents before dispatch. IK Fail or a discontinuous branch rejects the whole
dual-arm/gripper substep before its counter advances. The adapter returns the
accepted prefix length, discards the suffix without retry, and forces an immediate
outer review; guard diagnostics are never added to the model payload. A reset
starts fresh guard state. Earlier c/e runs lacked this installation and remain
diagnostic development evidence, not validated policy performance.

Execution condition `tcp-slerp-waypoints-v1` predeclares up to five waypoints
from the measured starting robot poses to the same selected final TCP targets.
TCP translation is linear and orientation follows the shortest quaternion arc;
the raw LINK6 poses are reconstructed using the fixed robot-local TCP offset.
The gripper command stays unchanged. Each waypoint receives exactly one native
action and the original IK guard; a refusal drops the unexecuted suffix and
requires review. There is no additional solve, physics budget or model retry.
This differs from earlier repeated absolute-target dispatch and must be recorded
as a distinct development execution condition, not pooled with old policy results.

Optional `launch.py --runtime-diagnostics` adds outer-only read-only articulation
snapshots to ik.jsonl. These include robot joint positions/velocities, target
buffers, runtime limits and PhysX drive settings/reactions. Every getter buffer
is copied immediately; missing/nonfinite readouts are marked unavailable and
do not change the solver/dispatch. ImplicitActuator torque estimates and
feedforward forces are explicitly distinguished from actual motor torque.
Original X5 contact reporting is not enabled; missing contact evidence means
unavailable, never zero contact. No diagnostic field is added to observe/model
input. All drives, limits, collisions and success predicates remain unchanged.

A new zero-API diagnostic may explicitly add `--contact-reports` alongside
`--runtime-diagnostics`. Startup wraps only the owned X5 spawn, adds reporting
API/zero threshold in the runtime USD session layer, and subscribes to copied
actor/collider/contact impulse reports. It does not use activate_contact_sensors
(which also changes sleep threshold in this installation). Shared asset files,
sleep, collisions and drives remain unchanged; metadata audits protected values,
enabled prims, subscription and failures. Inspect that audit before a probe.
This is a distinct observation condition, not policy input or a no-contact oracle.
Callbacks/metadata stay outer-only and are released at close.

The first pure-report startup check produced no callbacks because SimulationContext
defaults `/physics/disableContactProcessing` to true. Reporting condition v2
explicitly enables the same reporting gate used by ContactSensor, after simulation
configuration and before controlled probes, records its original/current value,
and restores the original at close. This is an observation-pipeline change;
physical limits/drives/collision/sleep properties stay audited. Require real
callbacks before using pair evidence; the v1 zero-callback run stays inconclusive.

Feedback condition `feedback-selected-vs-dispatched-v1` preserves the full
selected goal comparison in `execution_feedback` and adds
`last_dispatched_target_feedback` for the last Cartesian waypoint actually
sent, compared against the same measured robot pose. A partial prefix may
leave a full-goal residual despite tracking its dispatched waypoint. No
dispatch yields null, never a fabricated successful hold. Only command targets
and measured robot state enter this model-readable projection; guard/IK reasons
remain outer-only. This requires matching new native/worker sources in a fresh
attempt. It changes feedback interpretation, not action selection, execution
budget or physics. The r005 two-layout check remains under its original feedback
condition and is not relabeled or promoted.

Command condition `selected-gripper-command-v1` fixes keep semantics. Native
`ee_joint_state` is the inverse-normalized last rate-limited control target, not
necessarily the selected final command. The worker maintains a per-episode final
goal ledger and passes it explicitly to decode/permitted_state. At least one
actually dispatched substep commits selected goals; zero dispatch leaves them
unchanged. Fresh startup/reset initializes from the audited initial native target.
RPC uncertainty or inconsistent counts stop without replay. gripper_commands.jsonl
records provenance; model state labels runner_retained_goal, with measured opening
still null. Zero-API probes that use keep after an earlier command must likewise
retain explicit command_state, not feed low-level observations back as final goals.
No drive, collision, limit, step budget or action-choice change is made. The repair
is offline-validated and q2 native-runner-validated; this does not relabel historical p or prove policy/grasp benefit.

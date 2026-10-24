# GPT/Jev complete-method development

Status: r6 reached native success after three same-scene repairs. The first frozen
new-init probe r7 and appearance-growth comparison r8 failed. Spatial feature
budget comparison r9 succeeded with the unchanged method; a frozen unused-init
probe is running. This is not a stability or efficiency result. All model-facing
prompts, requests and lessons are English. This report describes outer-agent
experiment organization; it is not supplied as a task-solving prompt.

## Question and implementation

Can a task-independent prompt and capability manual make GPT deliver a complete
executable processing method, including Jev input/output cooperation, rather than
only a waypoint list? Actual Jev robot execution and native LIBERO success are
required to answer feasibility. Generalization and efficiency need separate tests.

The active files are the v2 builder, exact API and generic lessons under
`code/prompts/`; `code/scripts/run_gpt_jev_program.py` is the host and
`gpt_jev_program_worker.py` the separate restricted subprocess. The generated
`main(api)` owns measurements, geometry, phases, questions, control objectives,
effect checks and recovery. The host supplies public sensors and bounded numeric
operations; every physical update invokes real Jev. Exact GPT source patches are
assembled, validated and retained as complete methods. No task-specific robot
commands were handwritten into the fixed prompt or host.

The host cannot certify physical success from source validation, reached poses,
closure or patch registration. Native evaluation is read only at termination;
hidden object state and goal predicates are never sent to either model. A
post-policy simulator snapshot is diagnostic-only and is not used to restore a
convenient intermediate state for subsequent fresh-episode tests.

## Environment and routing

- Server: `company-server-2-ykj`, existing LIBERO-Plus environment, GPU 4 EGL.
- Python 3.10.12, NumPy 1.26.4, MuJoCo 2.3.7, robosuite 1.4.0, OpenCV 4.6.0.
- GPT: `gpt-6-astra`, `xhigh`, existing locally signed-in ChatGPT Pro transport.
- Jev: real `jev-1.13.0`, official TypeSafe `/v1/systemone`, separate authorized key.
- No OpenAI Platform, Decisions or `caz/z` credential was used.
- Repeated development case: `libero_goal/1335`, init 0, seed 0. This is one
  repeatedly observed development scene, not a held-out task or transfer sample.
- Ten initial settling steps per episode are reported separately from policy steps.

## Preserved development episodes

| Run | Actual host source | GPT calls | Jev calls | Policy steps | Elapsed seconds | Native success | Main failure |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| r1 | 250305d6 | 2 | 0 | 0 | 1137.32 | false | Global prerequisite and insufficient review measurement capacity |
| r2 | 2320f796 | 1 failed client call | 0 | 0 | 624.47 | false | Three failed upstream transport attempts before method delivery |
| r3 | 7fa785e2 | 6 | 33 | 99 | 1699.18 | false | Identical six-axis question text did not identify the axis |
| r4 | 9244c2b2 | 8 | 67 | 201 | 1702.60 | false | Closure occluded perimeter; later valid patch exceeded old source limit |
| r5 | f4de7617 | 3 | 32 | 96 | 1055.81 | false | Late texture initialization failed; host mishandled list evidence |
| r6 | 3bafd3a7 | 17 | 114 | 342 | 3119.04 | true | Three repairs: exact tracker key, mixed-depth rim samples, unattainable visibility gate |
| r7 | 3bafd3a7 | 4 | 52 | 156 | 313.05 | false | Frozen method on first unused init 1 lost transfer tracking |
| r8 | 6c57717a | 4 | 52 | 156 | 292.10 | false | Reference growth improved inliers but did not solve feature starvation |
| r9 | ea947a98 | 6 | 85 | 255 | 615.37 | true | Same init 1, complete unchanged method with spatial feature coverage |

All runs are under `code/runs/2026-10-24-gpt-jev-program/rN/`; complete requests,
responses, methods, RPC feedback, native receipts, depth/calibration and two camera
videos are retained. r5's 158-line method is source SHA
`6ca756923ff65cbc9692f3b6b2914da5fa81ce096f2a77c017bb53534c205e1b`.
An r4 late continuation recovered from its actual GPT patch is explicitly named
`unexecuted-method-02.json`; it was not executed or counted as a successful method.

An independent receipt audit of r3-r5 matched all 132 dispatched choice maps to
their real Jev responses and accounted for all 396 policy steps. It found no
opposite-sign command, nonzero held axis or violation of the documented vector
action limits. This is execution-consistency evidence, not perception accuracy,
grasp evidence or task success. The declared zero-magnitude deadband remains part
of the numerical controller and is not counted as substituting a Jev choice.
The same audit additionally passed all 114 r6 choices and 342 acknowledged steps.
Native success is read from `r6/summary.json`, independently of that audit.

r6's final source is `r6/method-03.py`, SHA
`afb42affc7d0f85d0fa1ff44b286ecd33783650a0688540099e0d6cd9e0857b8`.
Its scene-specific held-object recovery branch contains earlier public RGB-D
shape samples explicitly labelled historical. Those are GPT runtime output, not
a fixed prompt, shared skill or host policy. A fresh open-hand episode follows
the acquisition branch and remeasures its own scene. r7 freezes this exact source
and the actual r6 host on previously unused init 1, with zero method repairs.
That probe failed, so the source is preserved as a development-successful output,
not labelled stable. The exact unedited package is versioned under
`artifacts/gpt-jev-program-20261024/`, separately from shared prompts and skills.

## Costs, not efficiency claims

| Run | Known GPT input tokens | Known GPT output tokens | Reasoning subset of output |
| --- | ---: | ---: | ---: |
| r1 | 8755 | 30173 | 16424 |
| r2 | unknown | unknown | unknown |
| r3 | 69523 | 40616 | 25892 |
| r4 | 123152 | 44270 | 29183 |
| r5 | 22242 | 23698 | 16745 |
| r6 | 210286 | 70942 | 53667 |
| r7 | 37255 | 4994 | 3895 |
| r8 | 37236 | 5193 | 4098 |
| r9 | 57227 | 9831 | 7787 |

r2 has one client failure and three upstream attempts with unknown usage; they
are not zero-cost calls. Archived-method tests retain acquisition costs in their
originating runs instead of making them disappear. Raw bridge records preserve
Jev responses and reported usage independently. No matched-success baseline has
been run, so reduced call frequency is not evidence of token savings or speed.
r5's first complete method took 877.83 seconds to generate.

| Jev scope | Calls | Reported input tokens | Reported output tokens | Sum of service seconds |
| --- | ---: | ---: | ---: | ---: |
| r3 | 33 | 94178 | 8217 | 51.98 |
| r4 | 67 | 208313 | 16683 | 67.78 |
| r5 | 32 | 78805 | 7968 | 34.55 |
| r6 | 114 | 305465 | 28386 | 133.34 |
| r7 | 52 | 133763 | 12948 | 58.42 |
| r8 | 52 | 133653 | 12948 | 60.88 |
| r9 | 85 | 224705 | 21165 | 97.74 |
| Separate zero-motion diagnostics | 2 | 6083 | 498 | 3.60 |

These are distinct model token accounting streams, not interchangeable monetary
costs. Service-time sums exclude GPT waits, local simulation and other overhead.

Two additional real Jev diagnostics used the same stored r3 state and zero
physical actions. Original identical question text selected the same sign on all
six axes; explicit state selectors, including the compiler-prefix variant, each
matched all six supplied relation labels. These two calls are separate from
episode totals. The official Choice documentation confirms that Jev never sees a
question's dictionary ID: https://docs.typesafe.ai/primitives/choice.

## Changes supported by failures

1. Phase-local attainable prerequisites replace an implicit global clearance
   oracle. Missing swept-volume certification is not manufactured by prose.
2. Complete API capacity, accepted ranges and errors must be documented, including
   point/region counts, source limits, tolerances and region stride.
3. RGB-D boundary samples can hit adjacent surfaces. The program can fit a
   measured plane and explicitly derive ray intersections, retaining uncertainty
   and visible-landmark identity requirements.
4. Each Jev question must identify its subject and selector in content. The host
   now compiles explicit axis bindings; raw selected signs remain unchanged.
5. Camera-relative corner names do not establish persistent landmark identity.
   Reference annotations aid reviews but assume stationarity unless remeasured.
6. Closure can hide a perimeter while leaving texture. Generic SIFT/RGB-D rigid
   registration was checked on synthetic displacement/outliers and recorded r4
   views. It is a measurement primitive with an `unknown` result, not a grasp
   oracle. Retention requires comparing observed patch motion with actual hand
   motion, including rotation effects.
7. A textured reference should be initialized before occlusion when possible;
   geometry and tracking ROIs may need different cameras. r5 exposes this online
   gap despite successful recorded-view diagnostics.
8. List-shaped diagnostic evidence is valid. Host repair-context extraction now
   accepts objects, lists and absent evidence; r5's host crash is not relabelled as
   a model-schema failure.
9. The candidate host now supports bounded, provenance-labelled caller checkpoints
   across repairs in one episode. New episodes start empty; recalled values are
   historical assertions and require dependency/identity checks. Copy isolation,
   per-entry/total/count limits, atomic rejected writes, missing keys and the
   restricted worker RPC round trip passed without model or physical calls.
   This candidate was not hot-patched into r6 and has no online benefit claim yet.

## First native-successful development episode

r6 progressed from public geometry through actual Jev-controlled approach,
descent, closure and a retention lift. The hand rose 29.20 mm and the tracked
object 29.39 mm, with 2.98 mm rigid co-motion discrepancy. After a method repair
in the persistently closed scene, a fresh lift measured 18.425 mm hand motion,
18.426 mm object motion and 0.191 mm discrepancy. The repaired program executed
short elevated transfer segments, measuring retention between segments. It used
an explicit visible-obstruction question rather than requiring a fully visible
or certified swept volume. This is a bounded simulator policy, not a collision
avoidance guarantee for a physical deployment.

Before release, the inferred footprint radius was 45.36 mm and measured opening
radius 51.61 mm, with a 3.36 mm measurement allowance. The program opened the
gripper, withdrew, acquired a new view and then added nine physical settling
steps. Three corresponding print landmarks drifted 0.258 mm. These are public
effect measurements; only the isolated final LIBERO check established success.

The 52-minute development episode includes 17 GPT calls and 2933.90 GPT service
seconds. It demonstrates feasibility, not the requested eventual efficiency.
Candidate checkpoint/field-documentation/visibility-prompt changes made locally
during r6 were never hot-patched into it. Its success must be attributed to the
tested 3bafd3a7 host and the actual recorded GPT revisions, not later candidates.

## Frozen-method failures and feature-budget mechanism

r7's fresh open-hand execution remeasured the face, support and bowl; it did not
use the historical held-scene shape branch. Grasp and retention passed, but the
second lateral segment left only two matches per camera. The program correctly
stopped without release, and native evaluation was false. Four reviews and no
method repair were used. Its shorter elapsed time is not a speed gain because
the task failed and acquisition cost remains outside that execution.

r8 changed only `jev_rgbd_tracking.py` on an isolated branch from the tested host.
It retained the same full GPT method, fixed prompts, simulator init and all other
host code. Canonical appearance growth increased pre-transfer inliers to 120 and
first-segment inliers to 64, but the next segment still returned unknown. The final
images show the carton visibly between the fingers; qpos remained near
+0.02096/-0.02125 m. Unknown registration is not proof that the object was dropped.

The stored-image diagnostic exposed feature starvation. The same visible print
contained 172 selected points before the patterned destination entered more of
the image, but only 23 under a global 800-feature limit afterwards. Cropping the
same final print area yielded 168 points. OpenCV 4.6's
[official SIFT implementation](https://raw.githubusercontent.com/opencv/opencv/4.6.0/modules/features2d/src/sift.dispatch.cpp)
applies `retainBest` before `runByPixelsMask`; supplying a mask alone does not
prevent this competition. These are JPEG diagnostics, not original online RGB
frames or successful rollouts.

The next isolated source, `ea947a98`, removes the pre-mask global truncation and
then selects at most 128 features in each of 16 image cells. It retains 168 points
in the same final print area using 524 descriptors overall. No matching, rigid-fit,
depth-support, retention or action threshold was relaxed. Known canonical
translations/rotations, foreground-depth rejection, blank unknown, spatial caps
and bounded appearance-bank checks passed. r9 reuses the unchanged full method
on the now-seen development init 1 with no repairs. It reached native success:
at the former failing frame 156 it retained 120 inliers with 33.1 micrometre
internal registration RMS, then released and verified the placed object. This
residual is not true-pose accuracy. No method source or question text changed.
r10 freezes ea947a98 and the same full source on previously unused init 2.
GPT review outputs remain
stochastic; freezing simulator seed does not make visual interpretations identical.

## Evidence boundary

EXP-2026W43-055 through EXP-2026W43-063 preserve all outcomes in the weekly log.
The v1 contract adapter and its separate development failures remain unchanged.
The earlier source-grounded CaP/HexaShell/EmbodiedEvo comparison is in
`code/prompts/gpt_jev_program_design.md`; its candidate prompt is not the active
v2 prompt. No published result from those projects is treated as our result.

After a native-successful development method, freeze the prompt/manual/harness
and evaluate fresh initial states and held-out tasks. Stability needs repeated
native successes, and efficiency needs matched-success accounting that includes
generation, repairs, reviews, Jev, failures and acquisition costs.

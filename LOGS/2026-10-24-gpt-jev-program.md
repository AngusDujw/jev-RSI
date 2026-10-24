# GPT/Jev complete-method development

Status: active development, not a stability or efficiency result. All model-facing
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

## Costs, not efficiency claims

| Run | Known GPT input tokens | Known GPT output tokens | Reasoning subset of output |
| --- | ---: | ---: | ---: |
| r1 | 8755 | 30173 | 16424 |
| r2 | unknown | unknown | unknown |
| r3 | 69523 | 40616 | 25892 |
| r4 | 123152 | 44270 | 29183 |
| r5 | 22242 | 23698 | 16745 |

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

## Evidence boundary

EXP-2026W43-055 through EXP-2026W43-059 preserve all outcomes in the weekly log.
The v1 contract adapter and its separate development failures remain unchanged.
The earlier source-grounded CaP/HexaShell/EmbodiedEvo comparison is in
`code/prompts/gpt_jev_program_design.md`; its candidate prompt is not the active
v2 prompt. No published result from those projects is treated as our result.

After a native-successful development method, freeze the prompt/manual/harness
and evaluate fresh initial states and held-out tasks. Stability needs repeated
native successes, and efficiency needs matched-success accounting that includes
generation, repairs, reviews, Jev, failures and acquisition costs.

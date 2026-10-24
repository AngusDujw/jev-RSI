# From generated plans to validated GPT/Jev programs

Date: 2026-10-24. Status: source-grounded design proposal; no new robot rollout,
model call, or implementation claim. The candidate builder prompt is not connected
to the v1 runner. This is an outer-agent design document, not runtime experience.

## Recommendation

Let GPT build a complete program package with observable checks and recovery,
then validate and freeze reusable parts. Jev is the local decision service inside
that program, not a Python interpreter. Preserve a fixed task-independent runtime.
The benchmark's native checker remains the authoritative score.

The earlier contract design identified missing effect gates. The source comparison
adds a more substantial requirement: expose an actual observe/execute/inspect/repair
workspace, rather than expecting a larger static JSON waypoint list to express
all useful methods. A complete method includes how to obtain missing evidence and
how to recover; it need not predict the entire successful trajectory in advance.

## Source findings and their boundaries

The following are author claims or observations from official source, not results
reproduced in this repository. Retrieved 2026-10-24.

### Code as Policies

[Project](https://code-as-policies.github.io/) and
[official release](https://github.com/google-research/google-research/tree/master/code_as_policies).
Language-generated programs compose existing perception/control APIs and ordinary
program logic. Hierarchical function generation resolves helper implementations.
The transferable lesson is executable composition with an explicit API vocabulary;
it does not establish that arbitrary generated perception or manipulation works.
Its demonstration prompts contain task examples, so they should not be copied
unchanged into our recipe-free setting. The release provides notebooks rather than
a LIBERO/Jev runtime.

### HexaShell

[Paper](https://arxiv.org/html/2610.23479),
[release scope](https://github.com/HexaFuture/HexaShell#readme),
[tool API](https://github.com/HexaFuture/HexaShell/blob/main/interface/EpisodeAPI.md).
The paper separates fixed execution infrastructure from tools improved using
episode evidence. Its 46.9% RoboDojo success is a benchmark outcome, not a universal
reliability guarantee. Most tasks use task-specific tools; the Open profile uses
a shared library. Even the Open prompt includes a public task recipe, so that
setting is not identical to our recipe-free objective.

The public Apache-2.0 release includes frozen tools and interfaces but excludes
the harness server, executors, evolution loop, and optimizer tests. It is a useful
reference, not a turnkey reproduction.

The shared
[guarded grasp implementation](https://github.com/HexaFuture/HexaShell/blob/main/library/guarded_grasp/tool.py)
checks reached-pose errors and stops failed motion. It retains grasp_verified=false
and labels verification as motion-only. This is an important boundary: guarded
execution does not certify object retention. Its constants and robot conventions
must not be transplanted into LIBERO's OSC controller.

### EmbodiedEvo

[Paper](https://arxiv.org/html/2610.18867),
[execution protocol](https://github.com/Einsia/EmbodiedEvo/blob/main/docs/PROTOCOL.md),
[session client](https://github.com/Einsia/EmbodiedEvo/blob/main/orchestrator/session_client.md).
The core reusable representation is executable Skills plus diagnostic Lessons.
Python and physical state persist during program revisions. Playground allows
same-scene resets; Test freezes transferred knowledge and starts fresh scenes.
The principal transfer setting is the same task in new layouts, with additional
cross-task experiments. These scopes must remain distinct.

Against raw history, the paper reports 53.0% lower Test model expense, but 11.3%
fewer total tokens. This excludes acquisition and does not show lower cost than
the no-experience baseline. It does not demonstrate Jev substitution.

[Release provenance](https://github.com/Einsia/EmbodiedEvo/blob/main/docs/SOURCE.md)
excludes frozen learned harnesses and historical result artifacts; simulator
assets are separate. The README has no project-wide license selected. Therefore
we should reimplement the interface ideas rather than vendor its source as if it
were a permissively licensed complete reproduction.

Zotero: EmbodiedEvo was found as item 2173 under idea/gpt6时代/code as policy.
The two other exact-title searches returned no entries. The current public
sources above were used for version and release checks.

## What GPT should receive

Supply the following layers in the actual request, in English:

1. Builder role and deliverable specification.
2. A generated manual from the actual runtime API: signatures, numerical
   conventions, supported observations, errors, terminal behavior, and budgets.
3. Explicit observation/benchmark-feedback access policy.
4. A compact catalog of frozen skills and applicability conditions; load selected
   definitions on demand. Version references do not replace definitions.
5. The current instruction, actual observations, and evidence-tagged state summary.

Initial examples may teach units, observation expiry, bounded loops, gateway use,
and failure reporting using synthetic API fixtures. They should not prescribe
solutions for benchmark tasks. Every newly generated helper needs an implementation;
every external API needs a manifest entry. Unsupported capabilities are reported
before motion rather than filled with plausible names.

See [candidate builder prompt](gpt_jev_program_builder_candidate.txt). Its proposed
package fields and runtime gateway require implementation before use. It is not a
replacement for the existing submit_plan schema.

## Program package and runtime boundary

The proposed builder delivers program.py, interface.md, requirements.json, and
checks.json. The source implements parameterized measurements, finite-state logic,
bounded loops, and recovery. Requirements declare capability versions and Jev
decision sites. Checks are executable validation specifications only after their
fixture runner exists; generation itself is never a passing result.

Keep the trusted host process responsible for environment ownership, native
steps, observation filtering, request validation, timeouts, budgets, traces, and
the native evaluator. Run generated programs in a separate unprivileged process
with a narrow RPC interface. An AST check or restricted builtins alone is not
an isolation boundary. Do not give generated code the environment object,
simulator files, arbitrary host filesystem access, or model credentials.

The minimal public surface should support observation snapshots, measurement
requests, bounded Jev control leases, status, and completion proposals. Source
revision is a workspace operation. Reset is a development-only capability and
is unavailable during held-out tests. Observe/status must document whether they
consume physics, inference, or execution-request budget.

Numerical helpers cannot use hidden state. Any visual estimator must have an
implemented source, declared uncertainty, and appropriate validation. If it needs
another GPT image review, record that intervention and its cost explicitly.

## Proposed GPT/Jev division

| Owner | Produces | Must not silently assume |
| --- | --- | --- |
| GPT builder | Program, phase definitions, grounded features, finite decision choices, recoveries | A named predicate or generated function already works physically |
| Perception/geometry code | Measurements with source observation, frame, age, validity, uncertainty | A surface point is a complete object model |
| Jev | A legal local control or transition choice from current evidence | Source-code execution, hidden visual state, or persistent implicit memory |
| Controller | Bounded numerical command and measured execution receipt | Commanded closure establishes grasp |
| Evaluator | Official LIBERO outcome | Model confidence establishes task success |

At a Jev decision boundary, send the objective, observation identifiers, relevant
measured features, evidence status, recent action effects, finite action choices,
and the remaining lease. A useful effect status is supported, contradicted, or
unknown, with provenance; do not turn missing evidence into success.

Every action choice maps to an already implemented bounded controller. Validate
the returned choice against the current guards again before dispatch. If invalid,
record rejection and redecide; never silently substitute another sign or action.
Stage arrival and object-effect verification remain distinct events.

The current v1 request already tells Jev whether each axis should increase,
decrease, or hold. This is close to translating deterministic labels into choices;
it does not demonstrate that Jev contributes useful physical reasoning. Preserve
it as a baseline, then compare against the same deterministic controller and a
semantic local-decision variant. Any new variant is an explicit algorithm change,
not an already validated speed optimization.

Possible semantic choices concern whether to continue a bounded approach,
reobserve uncertain geometry, verify retention, or invoke an available recovery.
Jev can choose these only when its supplied features contain the relevant evidence.
Replacing GPT image judgement with Jev text decisions while omitting perception
would merely relocate the missing capability.

## Verification and promotion

Use distinct statuses: generated, interface_valid, simulation_checked, and frozen.
simulation_checked always includes the evaluated cases and outcomes; it is not
a claim of universal reliability. checks.json must not self-assign passing status.

1. Delivery checks: complete helper resolution, English requests, allowed imports,
   valid capability references, finite loops/leases, no motion bypass.
2. Interface/controller checks: units, quaternion convention, rotation frames,
   invalid or expired references, unreachable targets, clipped execution, exceptions,
   and episode termination. Use fixtures and no-motion checks where appropriate.
3. Physical checks: object effects under observable evidence, failure handling,
   perturbations of initial conditions, and full native task outcomes.
4. Regression checks: compare the candidate with the frozen version on fixed
   development cases. Retain failures and regressions; improve one diagnosed
   mechanism per candidate instead of editing a prompt until one rollout succeeds.
5. Freeze shared skills and lessons before held-out tasks/layouts. Do not carry
   test-specific repairs or transcripts into subsequent independent tests.

Local object-effect evidence can promote a local skill, but a full task method
requires native success evidence. Store task outcomes and local skill outcomes
separately. Reject task-ID dispatch, fixed layouts, and evaluator-specific formulas
from the shared library. Keep lessons in English with applicability, limitations,
failure evidence, and versioned code references.

## Evaluation and cost accounting

First validate one complete development episode, including a playable video and
full action/evidence trace. That is debugging, not generalization. Then evaluate
the frozen mechanism on held-out layouts and held-out task families where feasible.
Report both splits and the actual sample size.

Use three matched conditions: existing data-only GPT/Jev contract; program-capable
GPT/Jev runtime without inherited experience; the same runtime with frozen shared
skills/lessons. Add a no-Jev deterministic controller condition to measure Jev's
contribution. Hold observations, feedback access, models, and budgets fixed.

LIBERO native success is primary. Report false completion proposals, all failure
types, interventions, native steps, end-to-end time, and tokens for every model.
Include development/acquisition separately from Test cost, including failed trials,
retries, images, reasoning, and cache accounting. A cheaper failed episode is not
evidence of an efficiency improvement.

Benchmark feedback access is a declared condition. Native binary feedback exposed
by an existing benchmark interface differs from hidden object predicates. For a
blind LIBERO condition, the evaluator records scores outside policy inputs. If
binary feedback drives retries, make a separate matched feedback condition.

## Mapping onto this repository

- `gpt_jev_contract.py`: retain v1; add a versioned capability and decision registry
  for the new runtime, rather than accepting arbitrary generated sensor names.
- `run_gpt_jev_generic.py`: extract trusted environment ownership and logging;
  add a separate program runner with persistent physical state and explicit budgets.
- `gpt_jev_planner_v1.txt`: retain as the frozen current baseline. Activate the
  builder candidate only after the required program API and validator exist.
- Save exact source, loaded skill versions, model-visible requests, measurements,
  Jev choices, physical dispatches, videos, and official outcomes for every attempt.

The first implementation milestone is a functioning program execution boundary
and one evidence-checked local procedure. The next is a complete task scored by
LIBERO. Only then expand shared skill acquisition and held-out evaluation. This
converges the existing generic-vision investigation without changing its research
goals, declaring a new baseline result, or repeatedly tuning one task's prompt.

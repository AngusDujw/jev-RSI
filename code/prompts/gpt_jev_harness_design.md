# GPT-to-Jev reliability design

Status: proposed architecture, not an implemented capability or validated skill pack.

Follow-up: [source-grounded program design](gpt_jev_program_design.md) compares
Code as Policies, HexaShell, and EmbodiedEvo, and specifies a program-capable
GPT/Jev runtime and a candidate builder prompt. Both documents remain proposals.

## Evidence and objective

The existing generic runner completed 222 policy control steps through 74 Jev
decisions and seven GPT planning calls. Its execution audit found zero contract
violations, but GPT reported completion while LIBERO reported failure. See
`../../LOGS/2026-10-24-gpt-jev-generic.md` and EXP-2026W43-053.

LIBERO native success is the authoritative task score. Schema validity, target
arrival, a model completion claim, and a plausible final image are secondary
observations. No token or speed improvement has been established.

## Responsibility boundary

| Component | Responsibility |
| --- | --- |
| GPT planner | Compose grounded, bounded stages from available capabilities; request observation or revision when evidence is insufficient. |
| Runtime skill pack | Describe reusable parameterized procedures, assumptions, evidence requirements, and recovery conditions. |
| Harness | Resolve references, implement measurements, validate contracts, manage execution leases and transitions, and record evidence. |
| Jev | Select legal local control updates within the active validated stage. |
| Benchmark evaluator | Determine official success independently of model claims. |

A repository SKILL.md for the outer coding assistant does not automatically
reach the runtime planner. Planner skills must be explicitly loaded into the
actual GPT request, with versions and request hashes recorded.

## Planner input layers

1. A stable system contract describing responsibility, uncertainty, and output semantics.
2. A versioned capability manifest containing only implemented observations,
   predicates, controllers, units, frames, limits, and freshness requirements.
3. Selected runtime skill definitions with their preconditions and limitations.
4. Current task language, observations, uncertainty, and a bounded execution summary.

Keep all model-facing text in English. Do not inject task IDs, benchmark goal
predicates, hidden object states, task-specific coordinates, or canned task plans.
Skill identifiers alone are insufficient unless their definitions are already
present in the planner context.

## Required stage contract

Each stage should declare typed parameters, grounded observation references,
required capability versions, preconditions, an action target, controller limits,
expected effects, invariants, evidence expiry, execution budget, and recovery edges.
Every executable predicate must refer to a registered harness implementation.
Free-text intentions and visual checks remain annotations, not machine predicates.

Separate three events: a command was delivered, a local pose target was reached,
and the intended object effect was observed. A transition requiring an object
effect must not be enabled by pose convergence alone. Missing or stale evidence
produces an observation request or an explicit incomplete outcome.

The harness should reject unsupported contracts before any motion. It should
request GPT intervention on evidence loss, failed effects, stall, or a lease
boundary. Jev should receive only the current stage's relevant measured state,
legal actions, and implemented transition gates.

## Candidate runtime skills

These are proposals and must not appear as available until implemented and tested:

- Ground a visible region with depth validity, frame, timestamp, and uncertainty.
- Refresh a reference after motion or occlusion rather than reusing stale anchors.
- Assess object retention using observed object/tool relative motion across views.
- Assess placement using observed relative geometry and stability after release.
- Recover from a stalled local controller using bounded retreat or fresh observation.

These skills specify how to obtain and interpret evidence. They do not prescribe
a fixed task sequence. Vision-based retention or placement evidence is uncertain
and cannot replace LIBERO's authoritative success checker.

## Completion and evaluator isolation

Rename the planner's completion output conceptually to a completion proposal.
Always record the proposal and the native outcome separately. A false proposal
is a failure, never a successful episode or a reason to modify the checker.

For a blind evaluation, keep native success and privileged failure diagnostics
outside policy inputs. A completion proposal may terminate the rollout; the
evaluator then assigns its score. Runtime recovery must use permitted observations.

If native binary feedback is used to continue, retry, or terminate execution,
declare that as a separate feedback condition and apply it equally to baselines.
Do not silently turn the evaluator into a policy observation or provide its
task-specific predicates to GPT or Jev.

## Reusable planner contract excerpt

This excerpt describes the proposed interface; it is not a drop-in replacement
for the current v1 prompt and schema.

```text
Construct a bounded executable contract using only the supplied capabilities.
Ground every target in current observations and declare evidence freshness.
For each stage, distinguish command delivery, controller convergence, and the
intended object effect. Use only registered predicates for executable gates.
Specify preconditions, expected effects, invariants, and recovery transitions.
If required evidence or a capability is unavailable, request observation or
report the limitation instead of inventing a sensor or executable test.
Treat completion as a proposal supported by current observable evidence.
Compose reusable procedures from the supplied skill definitions; do not rely
on task identities, hidden benchmark predicates, or memorized task recipes.
```

## Implementation order and acceptance

First implement typed effect gates, observation freshness, and explicit completion
proposal bookkeeping. Then implement and validate a small evidence-oriented skill
pack. Finally optimize planner intervention frequency and context size.

Compare the frozen current interface, harness-only improvements, and harness plus
skills on matched task/initial-state splits. Separate development tasks from held-out
tasks and layouts. Freeze model versions, feedback access, and execution budgets.
Primary outcome: native LIBERO success rate. Secondary outcomes: false completion,
effect-gate errors, schema rejection, all-call token usage, and end-to-end latency.
Include unsuccessful attempts, retries, image inputs, and reasoning tokens in cost.
Do not claim generalization from repeated trials on one initial state, or efficiency
from a comparison with unequal success. No new rollout is authorized by this design
document alone.

# Incremental GPT/Jev implementation — offline validation

Implementation: `96e05891`. Scope: overall remaining-work plan, complete
current-stage processing method and Jev protocol, then evidence-triggered
supervision, local revision or plan revision. This is a task-independent harness
change, not a new task-specific trajectory or a frozen successful robot method.

## What changed

The planner no longer has to emit future-stage source. It first supplies 1–8
observable subgoals. Each active stage returns the existing four-string method
package. Supervision evaluates current images, public state, actual execution
receipts, stage outcome and the triggering condition. A failed stage is routed
to method revision or remaining-plan revision while physical state and episode
checkpoints persist. Stages cannot claim whole-task completion. Final native
LIBERO scoring stays outside all policy inputs.

Host triggers include stage returns and execution errors, repeated stalls,
non-improving pose updates, command mismatch, repeated measurement failures,
bounded Jev/step/RPC slices and worker silence. Rotation progress is preserved;
network/model waiting is excluded from worker silence. Defaults are engineering
choices, not empirically optimized thresholds. Semantic failures such as a lost
object still require evidence checks in the generated method.

See [the protocol](../../code/prompts/gpt_jev_hierarchical_v1.md) for exact
contracts, limits and invocation flags. Historical whole-method mode remains
available. No shared object recipe, task ID, coordinates or native-score hints
were inserted into model prompts. All new model text is English ASCII.

## Validation result

70 checks passed: 17 core orchestration checks; 51 assertions across six
actual-host/restricted-worker fixtures; 2 negative auditor checks. These are
overlapping software assertions, not 70 robot episodes or independent trials.

| Fixture | Checks | Verified behavior |
| --- | ---: | --- |
| Core callbacks | 17 | Recorded old/new blocked outcomes route to revision; evidence gates, bounded replanning, stalls, rotation progress, measurements and contracts |
| Host basic | 8 | Overall plan, stage methods, checkpoint handoff, supervisor and auditor |
| Host control slice | 10 | Interrupt a partially acknowledged drive, preserve receipts and revise from actual state |
| Host step slice | 10 | A requested three-step dispatch is capped at one remaining slice step; revision continues from that state |
| Host runtime error | 9 | Actual worker error routes to supervision and method revision |
| Host source rejection | 9 | Unsupported source construct is rejected, recorded, supervised and repaired |
| Legacy regression | 5 | One whole-method path, no stage prompts/journal, zero-dispatch audit without fabricated ledger |
| Auditor negative cases | 2 | Reject invented confirmation and an unsent supervisory decision |

The six host fixtures used the actual host, restricted Python worker, checkpoint
bank, dispatcher and saved-run auditor, with **mock model returns and mock
dynamics**. The physical evaluator was a false-valued fixture to verify that a
program proposal does not override it. No actual Pro, Jev or LIBERO physics call
ran in this experiment. There is no physical success rate, latency improvement,
token-saving measurement, or claim of reliable real-model replanning here.

The manifest records implementation/prompt hashes and individual check files.
Fixture subdirectories retain summaries, protocols, stage journals and audits.
Full request/response receipts remain under the project run directory
`code/runs/2026-10-30-gpt-jev-hierarchical`. Inline fixture drivers were not saved
as test scripts; generated fixture `.py` outputs were removed after validation.
Source text remains in JSON receipts for audit. Three modified/new Python
modules passed AST parsing; skill packaging and diff whitespace checks passed.

## Remaining validation

A real-model LIBERO batch must freeze this mode, account and inference settings,
declare old/new tasks and budgets, count every plan/method/review/revision call,
retain every admitted failure, and report native success separately from stage
and program claims. The two previous physical failures are evidence motivating
bounded recovery, not successes retroactively credited to this version.

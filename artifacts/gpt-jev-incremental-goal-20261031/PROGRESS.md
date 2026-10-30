# Incremental GPT-Jev reliability goal

Status: active, not achieved. User explicitly authorizes multiple GPT calls and incremental current-stage generation. Use signed-in local Pro gpt-6-astra/xhigh, authorized Jev, company-server-2-ykj and terminal isolated LIBERO scoring. No Platform/caz credentials.

Historical reference: artifacts/gpt-jev-cold-repro-20261027/method.py, 197 lines, 107 Jev / 321 policy steps, 14 GPT calls, no source repair, native success. This is a same-task/same-init result, not broad reliability. Preserve its local action/effect-observation feedback principles, not task coordinates or a universal package/bowl recipe.

Completed: dynamic plan stage-count schema based on at least two calls per stage, plus host validation and explicit planner budget context. Eleven budget/compatibility assertions and two AST checks passed; no new live calls. EXP-2026W44-046.

Next implementation: distinguish healthy control-slice continuation from source revision. Prefer preserving the live worker stack at a safe RPC boundary and supervising before unexecuted control; a continuation must never replay acknowledged physical calls. A fresh method process is not a general resume mechanism unless its own checkpoints are demonstrably idempotent. Cover partial drive progress, stop/revise, contract error, stagnant motion and call-budget exhaustion. Persist actual supervisor provenance for auditing. Existing supervise choices have no continue action; the current execute_method kills workers on StageYield. This requires coordinated host/protocol/prompt/auditor updates, not only a prompt edit.

Then compare generic prompt instructions to the successful source and exact historical prompts; define local observable evidence and bounded action trials without requiring future outcomes as prerequisites. Retain strict native scoring and observation provenance. Do not weaken geometric thresholds by hand or inject historical task commands into the generic framework.

Before live execution: finish software regression checks, commit and SSH push; read server skill, deploy isolated frozen worktree, explicitly pass existing proxy to relay, use native session delivery and owned systemd units. Recreate temporary authorized Jev relay key from its established keyring only; delete own copy after experiments. Prior services are stopped. Declare tasks, initial states, repeats, source repair policy and budgets before admission. Separate archive-assisted decomposition from cold generation. Keep all failures and costs. Stable completion is not yet established; select a concrete repeated/cross-initial-state criterion before claiming it.

Existing long-unresolved CIRCLE-1/3 warnings remain; no CIRCLE-2. Do not rewrite old failures or formal method/idea definitions. No subagents authorized. Do not write to /tmp or modify environments/drivers. All model input and experience text must be English.

## Continuation implementation checkpoint

Implemented normal control-slice live-stack continuation in StageWatchdog and
run_stages. The actual host execute_method and restricted worker were exercised
with a mock controller: one five-call drive survived two supervised continuations,
with one worker/source invocation and no repeated control. Six boundary scenarios
passed (revise, stop, invalid continue, GPT budget, update budget, stall). Saved
reports are live-stack-check.json and continuation-boundaries.json. Temporary mock
source was removed. Added generic local-observation/optional-tracker principles
from the historical successful builder to the current-stage prompt. No actual
model or robot trial yet. Next: freeze a declared live pilot, deploy and run with
real Pro/Jev; follow with declared repeated/cross-init validation if it completes.

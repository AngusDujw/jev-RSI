# Incremental GPT/Jev — two real execution trials

Status: running. Implementation and prompt hashes are frozen in manifest.json.

Order: task1335/init12, then task138/init0, seed0, one independent cold episode
each. Task138 was previously tested under whole-method mode; this batch is a
framework-version comparison, not an unseen-task claim. No archived method or
task-specific outer source edits are allowed. Model-authored stage revisions
and remaining-plan revisions are enabled under the declared count limits.

Planning uses the local ChatGPT Pro native-session adapter, gpt-6-astra/xhigh.
Jev is the official separately authorized jev-1.13.0 endpoint, with credentials
kept on the local workstation. Simulation uses the existing Python3.10 environment
on company-server-2-ykj, GPU4 EGL. No environment or driver changes were made.

There is no application request/episode time cutoff. Limits are24 GPT calls,
200 Jev calls,600 native steps,12 stage updates,3 local revisions and2 plan
revisions. Slice defaults remain24 Jev calls/72 steps. Every admitted failure
is retained; there are no replacement cases. Final isolated native LIBERO score,
program proposal, stage confirmations, actual Jev dispatches and all synthesis/
review/revision/retry costs are separate measurements.

Full commands and batch progress are saved locally under
code/runs/2026-10-30-gpt-jev-hierarchical-live/batch.json. Remote observations,
stage journals, method versions and dispatch receipts use the corresponding
project run directory in the manifest's remote_worktree. Final results will be
archived here after terminal summaries and source/dispatch/cost audits.

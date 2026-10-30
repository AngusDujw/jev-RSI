# Incremental GPT/Jev — two real execution trials

Status: running. Implementation and prompt hashes are frozen in manifest.json.
An additional known-task retry is declared in retry-manifest.json after a relay
proxy deployment defect; it does not replace the first admitted failure.

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

## First terminal result and infrastructure correction

Task1335 ended after2824.613 seconds with native=false,7 GPT requests,1 failed
Jev request,0 dispatches and0 policy steps. Two valid methods were delivered
(278/335 lines,1106.957/1154.7 seconds); the first blocked on a sampled
footprint margin, supervision requested revision, and the second acquired new
measurements and reached its first real Jev call. One unsupported While candidate
was rejected and automatically corrected in the same native request. All7 GPT
logical requests completed. The saved-run source/dispatch/cost audit passed.

The first Jev call returned HTTP451, region unavailable; the bridge surfaced it
as HTTP502 and the host terminated. The systemd relay had not inherited the
shell's configured proxy. Replaying that exact authorized Jev request through
the existing shell proxy returned valid choices in0.627 seconds, with no physical
dispatch. This diagnostic call is additional to episode counts and is not a
robot success. The original episode remains an admitted failed episode.

The owned relay was restarted with explicit existing HTTP_PROXY/HTTPS_PROXY and
NO_PROXY settings. The currently running task138 reattached under its existing
job/thread, adding a continuation turn rather than a fresh initial task. This
restart is an operator-induced transport recovery, not a natural stream failure.
After task138 terminates, one separately declared cold task1335 retry will use
the corrected proxy environment and its own ledger. No prompts, robot source or
count limits are changed to force a success.

The initial batch observer saw an inactive service between a pre-terminal file
probe and its next poll, so it marked the first episode unsummarized. The actual
terminal summary and failure receipts were subsequently recovered and audited;
the original observer record is retained alongside the reconciled report.

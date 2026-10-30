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

## Second terminal result and a separate host repair

Task138 ended after2121.745 seconds with native=false,7 GPT requests,0 Jev and0
policy steps. Six GPT requests completed. Its first165-line establish method
blocked on grasp-approach evidence; supervision requested revision and a113-line
revision was delivered. The next typed review declared note maxLength600, but
three candidates contained782/915/968 characters. The adapter rejected them
without coercion and exhausted its repair budget. The host exposed the terminal
HTTP502 instead of sending this observation failure to stage supervision. The
failed request's usage remains unknown; no physical control was evaluated.

A separate local repair converts only native submission-validation exhaustion
to PlannerSubmissionFailure (RuntimeError), which reaches the existing stage
execution-error supervisor. Relay failure receipts add at most three validation
errors without rejected candidate contents. Length errors now report actual and
allowed lengths. Authentication/region failures keep their separate terminal
classification; transient polling failures keep the same request ID. No schema
is relaxed and no reply is truncated or used as a valid observation.

Twenty offline checks passed:10 actual-host/restricted-worker checks replaying
the observed failure with mock models/dynamics,7 failure-boundary/relay checks,
and3 checks on the real rejected candidates. They are software evidence only.
One initial replay fixture failed because its mock health handler expected a
Request rather than a URL string; that fixture setup was corrected and retained
under a distinct run directory. No real model or task trial was repeated for
that mock failure. Test drivers were inline and generated mock .py files were
removed after checking.

The already running proxy-only cold retry remains on frozen a3f3ac3a and is not
silently upgraded to this host repair. Its eventual score cannot establish the
physical effectiveness of the new error-routing repair. The original two admitted
episodes remain0/2 native successes with0 dispatches; they demonstrate automatic
method revision but not successful manipulation or improved token/latency cost.

## Final adjudication (2026-10-31)

All four admitted episodes finished; none passed terminal LIBERO. Conditions remain separate. Both additional cases passed saved provenance/dispatch audits.

| Condition | Native success | Seconds | GPT | Jev dispatches / steps | Exit |
|---|---|---:|---:|---:|---|
| Original 1335/init12 | false | 2824.613 | 7 | 0 / 0 | Proxy omission: provider region rejection |
| Original 138/init0 | false | 2121.745 | 7 | 0 / 0 | Observation contract failure escaped supervision |
| Proxy-fixed 1335/init12, a3 | false | 7713.756 | 20 | 40 / 120 | Observation contract repair exhausted, HTTP502 |
| Contract-fixed 138/init0, f4 | false | 8159.331 | 24 | 40 / 120 | GPT call budget exhausted |

The a3 retry produced five accepted methods and two plans, but confirmed no stages. Its failed observation submission is a contract failure, not evidence of a network disconnect. The f4 case produced six methods and two plans, confirmed the observation stage, and routed two actual exhausted observation submissions into execution_error supervision and revise. It still did not establish task completion. Geometry/aperture evidence and sensing-motion consistency repeatedly blocked lift preparation.

GPT relay elapsed totals were 7627.461 and 8071.321 seconds for the additional cases; Jev request totals were 17.216 and 17.534 seconds. Relay elapsed includes inference, delivery, retries and waiting; pure inference/network time cannot be separated from these records. Known GPT token totals were 1345629/133247 and 1159759/135317 input/output, with 3 and 2 unknown-usage accounting records respectively. Do not interpret those record counts as provider HTTP attempts.

Generic design gaps observed, not yet repaired: a routine control-slice yield consumes a full method revision; revision-count exhaustion can label progress unproductive; remaining plans are not checked against minimum builder/supervisor call cost. No source was hand-edited to solve either task. Task138 was previously tested, so this batch is not unseen-task generalization evidence. No frozen successful method or token/latency benefit has been established.

See final-results.json and each case audit.json, stage-journal.json and summary.json. The original batch observer raced service completion; saved terminal summaries and audits provide the reconciled result without replacing the original batch record.

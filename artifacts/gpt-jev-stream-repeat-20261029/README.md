# Repeated stream-loss and continuation diagnostics — 2026-10-29

All three persistent native requests delivered complete new methods, including one and two controlled RPC process losses. The three independent historical HTTP requests did not deliver complete responses. This demonstrates conversation-level recovery for these cases, not exact inference-token resumption, robot success, or general reliability.

## Fixed conditions and complete accounting

Each initial request restored the same saved task183/init0 observation: “put the wine bottle on the rack table 1”. Instructions (32,308 characters), task text, tool contract and two JPEGs were unchanged. No old method, task execution feedback or task-specific repair was injected. All model text inputs were English.

Account/model: local ChatGPT Pro OAuth, gpt-6-astra/xhigh, Codex CLI 0.165.0. No Platform/caz key, robot SSH execution, Jev, simulation or GPU work. The CLI differs from the earlier 0.164.0 recovery example; we did not install or upgrade it this turn.

Initial compact-JSON payload SHA-256: 31e1a703d115605fe00dda98ef399743c2edd8a511752ecdc09a6c8b533e7b97. Historical diagnostic serialization SHA-256: 95bfc437efbe75e64a5a25c72f2c92a1198e554b54490269ae0f820da8cf8f1e. These are different serializations of the same restored object.

There was no application whole-generation or socket-read cutoff. User systemd units had RuntimeMaxSec=infinity and no restarts. Each raw trial made one upstream attempt without automatic resend. Native recovery retained finite limits: two RPC reconnections and three outer turns; SDK internal attempt counts are not fully exposed.

The original interleaved batch also had three native startup failures: systemd PATH omitted the NVM Codex directory. All had zero model turns and no thread ID; their receipts remain in startup-native-1/2/3. After a same-systemd-context ChatGPT account preflight passed with inherited PATH, three additional native trials were predeclared and run sequentially after the original batch. No model outcome was discarded or replaced.

## Results

| Path | Trial | Complete method | Seconds | Controlled RPC losses | Outer turns | Source lines |
|---|---:|---|---:|---:|---:|---:|
| Raw HTTP | 1 | No | 652.420 | 0 | N/A | N/A |
| Raw HTTP | 2 | No | 900.356 | 0 | N/A | N/A |
| Raw HTTP | 3 | No | 900.427 | 0 | N/A | N/A |
| Persistent native | 1 | Yes | 2256.991 | 0 | 1 | 205 |
| Persistent native | 2 | Yes | 2855.218 | 1 | 2 | 247 |
| Persistent native | 3 | Yes | 2463.406 | 2 | 3 | 211 |

All native sources are distinct, from three independent threads, and frozen unchanged after receipt. English/schema/AST checks passed, with zero invalid submission repairs. This does not prove runtime API correctness or physical success: Jev calls were zero and LIBERO was not evaluated.

## What failed

- Historical HTTP: all three initially returned HTTP 200, then incomplete chunked bodies with no response.completed. Failures at 652.420/900.356/900.427 seconds were not local TimeoutError or SIGTERM. Trials 2/3 began arguments at 775.622/794.150 seconds. [Exact phase times and partial character counts](raw-phase-summary.json) show output was lost before completion. No partial source was executed. Two near-900-second closures suggest a duration boundary somewhere in the response path; the 652-second failure and unavailable upstream logs prevent identifying a universal limit or closing layer.
- Transient TLS: native trials 1/2 recorded TLS handshake EOF and SDK reconnection. Out of 495 credentialless public HTTPS probes, two handshakes timed out. Their failure end times preceded native notices by 9.597/18.011 seconds. This repeated temporal association supports a transport disturbance, but does not isolate the local proxy, its route, edge or model service. HTTP 403 counts as reachability, not API health. Probe failure fraction is not a network-time percentage. Available old proxy logs did not cover this batch.
- Startup environment: explicit inherited PATH fixed test launches. The permanent client now detects a missing Codex executable before model invocation and resolves an available executable to an absolute path.

## What continuation means

Natural TLS losses in trials 1/2 were recovered by the SDK without changing the outer turn. Controlled RPC process losses instead reopened the same thread and appended a short English continuation turn. The initial task and images were not resent as new user input. A permanent guard rejects a changed thread ID during resume.

Each native audit checks stored history, exact initial text, two initial images, zero images in later user messages, and equality of stored dynamic-tool arguments, saved receipt and source. Trials 2/3 had respectively two/three user messages and outer turns in their original thread.

Trial 2 retained one completed pre-fault reasoning item ID. In trial 3 both early faults preceded any completed reasoning item: it proves original-context retention and eventual delivery, not preservation of partially running inference. The audit's applicability flag is false in that case; an empty set of item IDs must not be read as positive preservation evidence. [The documented thread/resume interface](https://learn.chatgpt.com/docs/app-server) reopens a thread for later turns; it does not guarantee token-level inference resumption or all transient JavaScript state.

## Why this remains slow

Native runs took 37.6/47.6/41.1 minutes and reported 29,060/32,909/26,533 reasoning tokens. Tool metadata shows 8/11/11 internal code-mode calls, including multiple draft checks before final submission. These are internal drafting steps, not external post-delivery robot-method repairs.

The native agent scaffolding and internal tools differ from raw forced-function output, so this is not a pure protocol-only speed comparison. Fixed initial task inputs do not make the complete internal processes identical. Client timings cannot partition pure inference, queueing and network seconds. During trial 3, two owned-socket samples showed 219,032 additional received bytes over about 64 seconds while a complete tool item was unavailable; interface silence was not a dead connection.

Known native thread accounting totals: 1,381,926 input tokens (1,334,272 cached), 121,797 output tokens, including 88,502 reasoning tokens. This is not exact upstream-attempt accounting. All three failed raw attempts have unknown usage; interrupted native segments may also have unreported usage. No token-saving or speedup claim follows.

## Evidence, limitations and cleanup

[Manifest](manifest.json), [startup amendment](startup-amendment.json), [startup guard/version boundary](startup-guard-amendment.json), [results](results.json), [12 final offline checks](offline-checks-final.json), and [cleanup receipts](cleanup.json).

Each native-1/2/3 folder contains the complete method.json, byte-identical method.py, result.json, audit.json, event metadata, tool/draft metadata and controlled-fault receipts when applicable. Public-control.jsonl contains the reachability probes. Raw-1/2/3 contain stream event and response-header metadata. No hidden reasoning text is included in this evidence.

EXP-2026W44-035/036/037/038 record this batch. These six logical model requests are same-observation delivery diagnostics, not cross-task robot trials. Three startup failures with no model turn are separately retained. Sample size and early fault timing limit stability claims. HTTP client disconnect/idempotent polling was not newly exercised here; these tests covered provider-stream and owned native RPC recovery.

The temporary diagnostic runner was removed after all trials and checks, as required. Its exact source remains at Git revision 1a7165bf, baseline/roboicl/reproduction/pro_recovery_repeat.py. Historical diagnostic dependency: 8b4bfdd6. Permanent client changes only reject silent thread replacement and detect/resolve the executable. All three owned transient services finished naturally with exit 0; the public probe stopped. No global proxy, driver, Conda permission, account settings, formal research objectives, mathematical assumptions or robot-method prompts were changed.

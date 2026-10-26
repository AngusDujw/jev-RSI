# GPT method-generation timeout diagnosis, 2026-10-26

The failure was a local deadline while waiting for GPT's complete method response. It was not a Jev execution timeout. The prior three design proposals had already returned. The next call requested explanation, a complete executable source defining main(api), interface, and Jev protocol as one submit_method tool call.

## Exact failed-input replay

One prior staged-bowl method request was replayed through the same local signed-in Pro transport with the same898-second deadline. Image data URLs were restored from the archived public JPEGs and their exact original URL hashes and lengths were verified. After restoring the images, the audited model-visible payload exactly matched the archived request in structure and content. This diagnostic bypassed the remote simulator, SSH forwarding and relay queue. No robot or Jev request occurred.

| Observation | Result |
|---|---|
| Upstream headers | 2.279 seconds |
| First SSE event | 2.280 seconds |
| Completed reasoning items | 22 |
| Last reasoning-item completion | 882.341 seconds |
| Keepalive events | 22 |
| Method argument characters | 0 |
| Completed method tool items | 0 |
| Terminal response.completed | Not received |
| Client deadline termination | 898.002 seconds |
| Actual replay attempts | 1 |
| Token usage | Unknown, not zero |

The interface continuously reported reasoning items. It never began delivering the method tool's arguments before the deadline. For this replay, the evidence narrows the delay to pre-method-output reasoning/acquisition. It does not support an already-delivered complete method being lost solely in transport. No reasoning text was collected or published; item metadata is sufficient for this phase diagnosis. Zero reasoning-text delta characters in the raw counters does not mean zero reasoning:22opaque reasoning items completed.

## Why the application displayed no progress

The production bridge reads upstream SSE but returns a result only on response.completed. It does not preserve intermediate reasoning or tool-argument progress in its normal ledger. Consequently, the host previously saw one long wait and thenHTTP504 even if upstream activity occurred. The504is emitted by our local handler for ProDeadlineError; it is not evidence that Jev or the upstream model explicitly declared failure.

Relevant unchanged code:
- [Per-call900/1800-second ceiling](../code/scripts/run_gpt_jev_program.py#L522).
- [Two-second bridge margin](../code/scripts/run_gpt_jev_program.py#L50).
- [Absolute deadline applied to each SSE read](../baseline/roboicl/reproduction/pro_oauth_bridge.py#L87).
- [Only response.completed returns the full result](../baseline/roboicl/reproduction/pro_oauth_bridge.py#L142).
- [Local deadline mapped toHTTP504](../baseline/roboicl/reproduction/pro_oauth_bridge.py#L353).

The episode's7200-second wall budget does not override this per-request ceiling. In staged mode, design and method requests each have900seconds; the relay receives898seconds. Receiving keepalives does not reset that absolute deadline.

The original single-request condition had1798seconds at the bridge, but drawer/push each encountered an upstream stream ending without a completed response around903seconds, then sent a new identical-payload request. That retry is not a continuation of the first response. Its remaining time expired. Bowl also suffered substantial relay queueing. These records must remain separate from the single diagnostic replay.

## Interpretation and limits

The accurate statement is: **GPT did not deliver a complete executable method within our local response deadline.** The three prior designs were not missing. This replay was still reporting reasoning shortly before cutoff and had not delivered method arguments.

The request contained44898instruction characters and7755input-text characters plus two images, with requested Astra/xhigh. This describes the workload; no controlled ablation establishes that prompt length or reasoning effort alone caused the delay. Old requests lacked streaming phase traces. The original903-second upstream EOF, and whether extending a request would complete, remain unresolved. No GPT planning-capability limit, Jev task failure rate or efficiency gain follows.

The next engineering target is observable and reliable complete-method acquisition, including generation budgets and delivery granularity, before more robot-performance comparisons. This diagnosis did not change a model-facing prompt, production runtime file, model/effort, or account. The metadata observer existed only in the diagnostic process, which exited. No temporary test script was created.

[Machine-readable findings](../artifacts/gpt-jev-timeout-diagnosis-20261026/FINDINGS.json), [exact-input manifest](../artifacts/gpt-jev-timeout-diagnosis-20261026/manifest.json), [SSE event metadata](../artifacts/gpt-jev-timeout-diagnosis-20261026/events.jsonl), [terminal diagnostic result](../artifacts/gpt-jev-timeout-diagnosis-20261026/result.json), and [original three-task results](../artifacts/gpt-jev-three-task-probe-20261026/README.md). Diagnostic costs are additional to that original report: one more upstream attempt with unknown usage.

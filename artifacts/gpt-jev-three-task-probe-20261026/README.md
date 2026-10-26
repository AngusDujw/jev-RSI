# Three-task GPT/Jev framework probe, 2026-10-26

The current framework did not deliver a complete executable method for these new tasks within the declared budgets. **No real Jev request or policy action occurred, so physical task success rates were not measured.**

| Task | LIBERO-Plus goal ID | Initial state | Staged design | Complete source | Real Jev | Policy steps |
|---|---:|---:|---|---|---:|---:|
| Open the middle drawer | 0 | 0 | Delivered | Timed out | 0 | 0 |
| Push the plate to the front of the stove | 75 | 0 | Delivered | Timed out | 0 | 0 |
| Put the bowl on the plate | 102 | 0 | Delivered | Timed out | 0 | 0 |

The fixed builder, API, generic lessons and302ff1ebruntime were retained. All requests used English, local signed-in Pro Astra/xhigh, empty episode memory and no archived task source. No task trajectory was hand-written. Each episode allowed24GPT,200Jev,600policy steps,7200seconds and zero source repairs. Only the existing optional synthesis mode and relay scheduling differed between conditions.

## Conditions and limits

1. **Original single-request synthesis:** all three logical requests returnedHTTP504 without source. Drawer and push each used the full1798-second relay limit with two upstream attempts. Bowl spent most of that deadline waiting for one of two relay slots and had only34.4seconds upstream; it is not an equal-budget generation test. Five attempt usages are unknown.
2. **First staged batch:** the bridge exitedSIGTERM143 after about290seconds. All three design requests disconnected. The cause and actual upstream attempt counts are unknown; no terminal ledger exists. Preserve these records separately.
3. **Independent staged supplement:** one foreground parent owned a three-slot bridge and the SSH children. All three designs returned: bowl261.23s, push356.20s, drawer409.62s. Each complete-source stage then hit its898-second relay deadline (900-second caller limit minus two seconds). No source was delivered. Per-episode elapsed times were1173.02/1267.84/1321.12seconds for bowl/push/drawer. These are not summed concurrent batch wall time.

A separate small Pro readiness request completed in3.12seconds,120input/13outputtokens. This establishes small-request availability, not reliable long synthesis, and does not distinguish slow inference from long-response delivery failure.

The supplement's three designs have28776known input/13172known outputtokens. Including the diagnostic gives28896/13185. Eight additional ledger attempts have unknown usage; three interrupted logical requests lack terminal ledgers and may involve further attempts. These are not complete total costs.

## Evidence

[Machine-readable outcomes and costs](RESULTS.json), [original declaration](manifest.json), [staged declaration](staged-manifest.json), [supplement declaration](staged-retry-manifest.json), [environment](environment.json), and [foreground lifecycle](staged-retry-orchestration.json).

- [Drawer design and records](staged-supplement/drawer/method-design.json)
- [Push design and records](staged-supplement/push/method-design.json)
- [Bowl design and records](staged-supplement/bowl/method-design.json)
- [Full experiment report](../../LOGS/2026-10-26-gpt-jev-three-tasks.md)

Original and supplement requests, English input, strict designs, source absence and zero-step/cost consistency passed the saved-run auditor. The interrupted batch cannot receive the same provenance audit because its terminal ledgers are missing. Audits do not certify design correctness or perception truth.

Terminal nativefalse outcomes are retained exactly. They were evaluated on settled initial scenes with zero policy actions, so reporting a Jev physical success rate of0/3 would be misleading. No executable method, reusable new-task policy or efficiency gain was established. Full source acquisition/transport must work before the intended physical generalization test can be completed. No current method was patched into success.

[Files added or updated](CHANGED-FILES.md). No executable runtime or model-facing prompt was edited.

A later [single-request phase diagnosis](../gpt-jev-timeout-diagnosis-20261026/README.md) found ongoing reasoning through882swith zero method-argument characters before the local898sdeadline. This does not change these original outcomes or costs, and cannot reconstruct their missing phase traces.

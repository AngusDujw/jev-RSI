# Jev routing protocol qualification

This is a text-contract qualification, not a robot success result or an efficiency claim.
The input normalizer computes simple public status facts (budget exhaustion,
execution equality, missing fields). It does not infer pixels or fabricate contacts.
Jev selects a route from these explicitly normalized facts. A deterministic program
could implement these same rules; the experiment must still test the value of delegation.

- V1 independent cases: 52/81 correct. Missing/stale evidence and some terminal
  states incorrectly produced `act`. V1 was rejected. These cases subsequently
  became development data; they are not independent V2 evidence.
- V2 development regression: 87/87, including missing wait/action branches.
  A local evaluator-edit failure accidentally repeated the 87 requests. Both full
  request batches remain in ledger-v2 and both count toward usage; the identical
  second result occupies heldout-results-v2.json. The filename is historical;
  these 87 cases are DEVELOPMENT, not held out from V2 development.
- Frozen V2 new combinations: 120/120 (87 observe, 23 stop, 10 wait).
- Additional frozen V2 positive cases: 40/40 (20 act, 20 wait).
- Total here: 415 real calls, 254985 input tokens, 18675 output tokens, no unknown
  usage. The earlier six-case smoke is separate and must also be included in
  total experiment-development costs.
- Five offline runner checks passed: exactly one selected native dispatch;
  rejection of an incompatible model choice; observe without execution;
  rejection of stale execution and mismatched observation directory.

The protocol was frozen before the 160 new cases. Exact cases, expected labels,
raw outputs and per-request IDs are preserved. Every request directory records
the exact normalized API request and raw response. Tests were synthetic and do
not establish calibrated real-world reliability. Runtime raw plans and candidate
source snapshots are separately saved by the workspace routing tool.

The first runtime supports one bounded stage per routing invocation. After that
execution it returns to GPT for new visual evidence; old evidence must not be
silently relabeled as fresh. All native submissions retain original accounting.
Temporary evaluator and fake-runner test scripts were removed after use.

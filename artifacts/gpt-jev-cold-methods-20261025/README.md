# GPT/Jev independent complete-method outputs

These exact model-generated outputs are separate from the
[generic prompt/API/harness](../../code/prompts/README.md). Each episode began
with empty memory, current public observations and no archived source. Every
control update used real Jev. No outer-agent task-source edits were made.

| Init | Native success | Program proposal | Source patches | GPT / Jev / steps |
|---|---|---|---|---|
| [9](init9/METHOD.md) | true | false | 5 | 24 / 92 / 276 |
| [10](init10/METHOD.md) | true | false | 4 | 24 / 138 / 414 |
| [11](init11/METHOD.md) | true | false | 5 | 24 / 99 / 297 |
| [12](init12/METHOD.md) | true | true | 0 | 13 / 109 / 327 |
| [13](init13/METHOD.md) | false | false | 4 | 24 / 80 / 240 |

Init9/10 are regression layouts; init11-13 were previously unused layouts at
admission. Init12 succeeded with its untouched initial complete method. Native
evaluation is authoritative; false program proposals and all costs remain
explicit in provenance and the [continuation report](../../LOGS/2026-10-25-gpt-jev-stability.md).

All five predeclared native trials completed: four successes and one failure.
The all-five criterion was falsified. The failed init13 remains alongside the
positive outputs; a later framework is a separate candidate, not a replacement
for this result. This is single-task evidence, not a universal guarantee.

These task-specific sources are retained outputs, not recipes to inject into
shared knowledge. They are not automatically loaded by the builder. Full
token/latency improvement remains unproven.

# GPT/Jev independent complete-method outputs

These are exact model-generated execution outputs, separate from the
[generic prompt/API/harness](../../code/prompts/README.md). Each episode began
with empty memory, current public observations and no archived source. The outer
agent did not edit the generated programs. Every control update used real Jev.

| Init | Native success | Program proposal | Source patches | GPT / Jev / steps |
|---|---|---|---|---|
| [9](init9/METHOD.md) | true | false | 5 | 24 / 92 / 276 |
| [10](init10/METHOD.md) | true | false | 4 | 24 / 138 / 414 |
| [12](init12/METHOD.md) | true | true | 0 | 13 / 109 / 327 |

Init9/10 are regression layouts; init12 is a previously unused layout and
succeeded with the initial complete method. Native evaluation is authoritative;
false completion reports and all costs remain explicit in provenance and the
[continuation report](../../LOGS/2026-10-25-gpt-jev-stability.md).

The original five-case cold criterion remains pending: init11/13 are running.
These task-specific sources are retained outputs, not recipes to inject into
shared knowledge. They are not automatically loaded by the builder. Multi-task
reliability and full token/latency improvement remain unproven.

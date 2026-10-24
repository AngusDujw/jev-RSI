# GPT/Jev independent complete-method outputs

These are exact GPT-generated execution outputs, separate from the
[generic prompt/API/harness](../../code/prompts/README.md). No outer-agent task
source edits were made. Each regression episode began without an archived method
or scene memory and used real Jev for every control update.

| Init | Native success | Program proposal | Source patches | GPT / Jev / steps |
|---|---|---|---|---|
| [9](init9/METHOD.md) | true | false | 5 | 24 / 92 / 276 |
| [10](init10/METHOD.md) | true | false | 4 | 24 / 138 / 414 |

Native evaluation is authoritative, as requested. Program verification defects
and all generation/recovery costs remain explicit in each provenance file and
the [continuation report](../../LOGS/2026-10-25-gpt-jev-stability.md).
Two regression successes do not establish the predeclared five-case cold criterion:
unused init11/12 are running and init13 is not admitted yet.

These task-specific sources are retained outputs, not task recipes to inject into
shared knowledge. They are not automatically loaded by the builder. Generality
across task families and full token/latency improvement remain unproven.

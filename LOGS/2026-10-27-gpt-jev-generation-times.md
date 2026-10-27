# Historical GPT/Jev method generation timings

Read-only audit of four saved successful method requests. No model or robot call was made.

| Method | Request kind | Generation request | Full acquisition episode |
|---|---|---:|---:|
| Final frozen235: archive-assisted model patch | submit_method_patch | 10m01s | 47m51s |
| Parent a18: archive-assisted model patch | submit_method_patch | 12m28s | 51m30s |
| Independent cold complete method, init12 | submit_method | 14m11s | 34m21s |
| Independent cold complete method, init14 | submit_method | 10m37s | 32m27s |

The final frozen235source used600.637seconds for one GPT patch request. Its2871.000-second episode also includes16GPTvisual reviews and88real Jev calls. This excludes earlier sources, failed candidates, research/development and later frozen validation.

The two cold requests supplied no archived task source. Both refer to the same cream-cheese-into-bowl task; these timings are not evidence of cold success on different tasks. The archive-assisted parent and final patch calls are separate from cold generation.

Generation-request elapsed time includes transport and waiting for the completed response. It is not an isolated measurement of model thinking. All four exact requests matched one completed relay record and one successful upstream attempt.

[Exact request hashes and second-level timing receipts](2026-10-27-gpt-jev-generation-times.json).

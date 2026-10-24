# GPT/Jev stability continuation

This is an outer-agent experiment record, not model-facing experience.

The user explicitly requested continued iteration until stable real GPT/Jev
execution. Prior evidence and all failures remain in the October 24 report.
No formal research goal, primary metric or theorem is changed here.

## Evaluation separation

1. Frozen-method execution: exact unedited GPT method source SHA256
   afb42affc7d0f85d0fa1ff44b286ecd33783650a0688540099e0d6cd9e0857b8,
   zero source repairs, current public observations, real GPT reviews and real
   Jev 1.13 choices. Start with unused init 4, then unused initial states.
   Five consecutive new-init native successes are a working regression target,
   not a statistical reliability guarantee or a multi-task result. If a mechanism
   changes, start a new frozen validation sequence and retain earlier failures.
2. Fresh builder: no archived method or scene memory; generate the complete
   package with the generic prompt/API. Any online repair and its cost are
   reported separately. Native evaluation remains isolated until termination.

Planner remains local signed-in Pro gpt-6-astra/xhigh; no Platform API, Decisions
credential or caz/z credential is used. Server is company-server-2-ykj, existing
LIBERO-Plus UV interpreter and EGL GPU 4. All work stays in project directories.

## Candidate numerical capability layer

`code/scripts/gpt_jev_geometry.py` provides rotation, rigid point transforms,
own pad-center computation, plane and XY circle fits, and measured rigid-motion
attachment discrepancy. All are pure mathematical functions on caller-selected
inputs. No task string, object dimensions, pixel region, trajectory, control
decision, semantic success test or API call is encoded in this layer.

The worker preloads `geo` before seccomp, and the exact API manual documents the
functions and limits. The fixed prompt requests their reuse. The complete
method still owns sensing requests, semantic choices, strategy, Jev questions,
uncertainty, phase transitions, effects and recovery.

Offline checks passed: independent analytic 90-degree quaternion orientation,
rigid inverse round trip, a tilted plane, a translated circle, pad offset,
zero/nonzero attachment discrepancy, five malformed/degenerate inputs, and
execution through the actual separate seccomp worker. No test script was saved.
This is not robot-success or cold-generation evidence. The running init 4 uses
the pre-change c669ed34 host/worker/prompt, so cannot be credited to this layer.

Official reasoning guidance was read from
https://developers.openai.com/api/docs/guides/reasoning . The model-specific
Markdown page could not be retrieved by the browser; the installed OpenAI Docs
prompting reference was used only as a fallback. No model, account, reasoning
effort or API route was changed on the basis of documentation.

## Native results

| Run | Source/harness | GPT | Real Jev | Policy steps | Seconds | Native |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| init4 | afb42aff / c669ed34, no repair | 6 | 86 | 258 | 638.73 | true |

Init4 is first use. All 86 dispatched choice maps match the original real Jev
responses; sign, norm and 258 acknowledged-step checks pass. GPT completed input
45400/output9226, six upstream attempts with known usage, relay423.48s. Jev
completed input192037/output21414; 87 upstream attempts include one failed attempt
with unknown usage, relay173.43s. These are not full Jev costs. Post-release
measured landmark drift was0.244mm, not ground-truth sensing accuracy.

Init5 frozen validation and init0 fresh candidate builder are running in separate
worktrees and simulators, sharing a two-slot Pro bridge after init4 terminated.
Both render on GPU4. Concurrent wall times will not be interpreted as a speed
comparison. The cold candidate has no archived method or scene checkpoints.
Every launched episode, including infrastructure failures, remains in the record.
No policy success is inferred from program validity or pose reach.

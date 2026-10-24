# GPT/Jev stability continuation

Current status: predeclared frozen init4–8 completed native5/5, no source repairs.
The first independent geo-assisted cold method failed after two GPT patches and
23 real Jev calls. A second independent builder and a separate GPT-led revision
are active. Earlier pending statements below describe intermediate checkpoints.

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
| init5 | afb42aff / c669ed34, no repair | 6 | 91 | 273 | 732.57 | true |
| init6 | afb42aff / c669ed34, no repair | 6 | 85 | 255 | 928.73 | true |

Init4 is first use. All 86 dispatched choice maps match the original real Jev
responses; sign, norm and 258 acknowledged-step checks pass. GPT completed input
45400/output9226, six upstream attempts with known usage, relay423.48s. Jev
completed input192037/output21414; 87 upstream attempts include one failed attempt
with unknown usage, relay173.43s. These are not full Jev costs. Post-release
measured landmark drift was0.244mm, not ground-truth sensing accuracy.

Init5 and init6 also passed unchanged-response, sign, norm, carried-gripper and
acknowledged-step checks; all three source hashes match the original package.
`code/runs/2026-10-25-gpt-jev-program/frozen-audit.json` retains per-run audit and
completed usage. Requests were matched to bridge records by canonical full-body
SHA256, including hashed image contents, rather than by completion ordering.
Init5 GPT completed input45944/output8798, Jev202509/22659; init6 GPT45911/10038,
Jev189932/21165. All of these upstream attempts have known usage. The prior init4
unknown Jev retry remains part of the batch cost and is not erased.

Init7/init8 frozen validation and init0 fresh candidate builder are running in
separate simulators, sharing a two-slot Pro bridge after init4 terminated. At most
two frozen simulators and one cold-builder simulator are active. All render on
GPU4. Concurrent wall times will not be interpreted as a speed comparison.
Every launched episode, including infrastructure failures, remains in the record.
No policy success is inferred from program validity or pose reach.

## Cold candidate at 18e9bede

The initial request was verified to have no previous_method, empty feedback and
checkpoint manifest, no method-file or reused source hash, frame0, and forced
submit_method. Generation completed in888.97s, one upstream attempt, input7476 /
output20631 tokens. The complete output is213 lines /24750 characters and uses
geo13 times. It explains the full strategy and Jev feature/question/choice/action
mapping. This is delivery evidence, not improved speed or task success.

The first execution stopped before any physical action: a requested depth point
was discontinuous and omitted from review.points, but the program indexed it.
The raw review already recorded measurement_errors. GPT's first exact-source
patch now uses available valid samples, preserves geometric adequacy checks,
records missing names and checkpoints source measurements. The original failure
is retained; no point was invented and the scene was not reset.

This exposed omissions in the exact manual: partial measurement/error behavior,
and before/after being TCP position lists from the last control update rather
than state dictionaries or whole-lease endpoints. Main commits30fae198/4e50afc6
clarify these existing semantics for future calls; they are NOT hot-applied to
this18e9bede episode. No hand edit was made to the generated source. Native
execution after its first patch remains pending.


## Completed frozen sequence and first cold outcome

Predeclared init4-8: native5/5, zero source repairs,30 GPT reviews,432 real Jev calls and1296 policy steps. Per-case steps258/273/255/264/246 and Jev86/91/85/88/82. All source/dispatch/sign/norm/carried-gripper/acknowledgement/English-request checks passed. Completed GPT228667 input /47907 output excludes one unknown-usage failed attempt; completed Jev963526/107568 excludes another unknown-usage attempt. Full costs are unknown; original method acquisition is not free. See EXP070 and frozen-audit.json.

The 18e9bede cold episode ended native=false/completion=false:7 GPT,23 real Jev,69 steps,1898.78s. GPT71909 input /39446 output; Jev47150/5727; all upstream attempts have known usage. Three complete methods and both exact patches remain retained. The last method acquired six valid samples, then exhausted a20-update high-approach lease and incorrectly indexed a position list as a state dict. This activated the previously diagnosed contract error; no object was grasped. EXP069 records the complete negative result.

The separate 7a640750 cold builder has no prior source. A new e0c93679 run asks GPT to revise its unedited0f4e1e7c generated method with the corrected contract and public failure receipts, beginning a fresh scene and empty checkpoints. It is revision/reuse, not cold generation; no privileged snapshot is restored.

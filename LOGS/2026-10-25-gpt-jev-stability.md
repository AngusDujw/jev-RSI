# GPT/Jev stability continuation

Current status: both frozen cold candidates failed their all-five criteria:
a8e6ea72 completed five cases, native4/5;618f559b completed three admitted cases,
native2/3, with16/17 unadmitted after regression13 failed. All failures, complete methods and
known costs are retained. Stable cold success is not established. Candidate0d15ab18 then stopped on a Jev transport502 before completion,
native0/1 admitted;16-19 remained unadmitted. Its policy effect is uncompleted.
Primary frozen2d710418 now runs an independent cold regression13 after fixing
real repair-context data loss (8offline checks, Native=N/A). Previous50432131
regression ended nativefalse/gpt_budget and is retained separately. A separate
archive-assisted portability revision is also running. Unused16-19
await primary regression success. Stable native success is still unestablished.

Earlier scoped positives remain distinct: one unchanged prior method passed
frozen init4-8 native5/5 with zero repairs; the a8e cohort included an untouched
cold method on unused init12 with native/proposal both true. These do not make
the failed cold cohort stable. Earlier pending statements below are historical
checkpoints. No net efficiency or cross-task reliability claim is established.

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

Step-count clarification: summary.settling_steps=10 describes the fixed initial
reset settling before the policy starts. native_steps counts policy-controlled
steps. Terminal evaluation reads the final state directly after policy termination;
it performs no additional settling, release or goal-completing action. Do not
interpret a native/proposal mismatch as a change produced by post-policy steps.

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


## Later completed episodes and typed candidate

| Run | Tested host | GPT | Real Jev | Steps | Seconds | Native |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| repair-geo-init0 | e0c93679 |9|98|294|1578.86|true|
| cold-contract-init0 |7a640750|8|53|159|2510.20|false|
| geo-init9, no source repair |e0c93679|3|17|51|407.57|false|
| geo-init10, no source repair |e0c93679|4|82|246|783.60|false|

The successful revision source is7e6c8e8e1d86476f6b18bcdd2e0c6858f46176e94330edc8f5d49d70ae9659f5. Its measured hand/object rise was22.507/22.626mm. All98 real choices and294 steps passed audits. GPT125249 input/34618 output; Jev202394/24402, all usage known. Original failed-method acquisition remains separately counted. EXP071 is revision/reuse, not independent cold generation.

The independent second cold method failed retention (hand23.879mm rise, object0.038mm rise and7.866mm lateral shift). After two GPT patches it stopped again on a free-JSON recovery-field mismatch. All53 real choices/159 steps passed audits; completed GPT101326/51023 excludes one unknown-usage upstream attempt, Jev108196/13197 is complete. All source versions and failures remain (EXP072).

The new7e6 source was predeclared for init9-13. Both admitted cases failed, so remaining init11-13 were not launched:0/2 admitted, not0/5. Init9 stopped on unresolved local rim/open-finger-envelope overlap, not a confirmed physical collision. Init10 failed a1.5mm pose gate at1.990mm residual after two24-update leases; this does not establish a global servo accuracy floor or a contact cause. All99 responses/297 steps passed audits, all usage known (GPT64056/19967, Jev204461/24651). See EXP073. The original afb42aff five-case evidence remains separate.

A read-only audit across all10 terminated episodes found705 real control calls and4935 axis/gripper choices, with zero mismatches against the supplied semantic goal labels. This validates label selection only, not whether the program targets or physical plans are feasible.

The next task-independent mechanism is api.review(..., fields=...). Compact type/enum/nested declarations become an actual strict function-tool parameters object. The host validates exact types without coercion and keeps legacy calls available. No task command or trajectory is encoded. Fourteen negative cases, nested/nullable positives and unchanged legacy schemas passed. A real Pro public-image probe returned typed booleans/enums/null in4.57s,1068 input/88 output;0 Jev and no native evaluation. It is not a task success (EXP074). Official schema guidance: https://developers.openai.com/api/docs/guides/function-calling .

At b0b53fe4, typed-cold-init0 has no previous method. typed-repair-init0 revises unedited316750b9 with old public failure receipts in a fresh scene with empty checkpoints. Both have20 GPT/200 Jev/600 steps/3 same-scene repairs/4800s budgets. The revised method has delivered source; its actual first review request has strict=true with declared parameters fields, rather than relying on free JSON. No typed native outcome yet.


## Typed native results and final fixed-framework cohort

| Run | Host | GPT | Real Jev | Steps | Seconds | Native | Source repairs after fresh/revised initial package |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: |
| typed-repair-init0 |b0b53fe4|11|106|318|1874.30|true|0|
| typed-cold-init0 |b0b53fe4|17|107|321|2524.77|true|1|

The revision uses c7ec4f4a source. All10 review calls used strict tools with fully validated returns; all106 choices/actions and318 steps passed audits. GPT141056 input/45012 output, Jev215865/26394; all usage known. It starts from the prior generated method and is not a cold result (EXP075).

The independent cold result starts without a prior method, feedback or checkpoint. Initial dcfd66ec source was205 lines/22586 characters and generated in723.66s. It stopped after63 policy steps because local visibility fallback shortened each leg without extending a five-iteration route bound. One model patch produced complete source52da6a44 and continued the same physical scene, reaching native success at321 steps. All15 strict review returns and107 real choices/actions/steps passed audits. GPT165648 input/61757 output and Jev223312/26643 are full episode known usage, with no unknown upstream attempts. No speedup or stable cold-generation claim follows from this42-minute development episode. EXP076 and [the preserved complete method/JeV protocol](../artifacts/gpt-jev-typed-method-20261025/METHOD.md) retain design, full source and exact patch provenance.

Subsequent92d8d481 keeps tool schema numeric constraints exact while data still uses six significant digits; offline boundary/immutability checks and17 real archived-request equality checks passed. Subsequent9a3e1f3d requires fields for generated/repaired methods, preserving legacy compatibility only for untouched selected archives; it adds generic finite-route budget coherence knowledge. Neither was hot-applied to the two b0b episodes.

The final framework is frozen at9a3e1f3d for predeclared init9/10/11/12/13. Every episode starts a fresh independent submit_method generation with no archive, feedback or checkpoint. Each has20 GPT/200 Jev/600 policy steps/3 same-scene GPT source repairs/4800s. Outer-agent task-source edits are forbidden. Init9/10 are previously failed-layout regression cases; init11-13 are unused. This tests the complete cooperation system, not zero-repair reuse of one program. Failed episodes remain; no substitute initial states will be selected. Init9 and init10 are admitted. Init9 initial source failed on an incorrect geo.plane return key before physical actions and is undergoing its own model repair; init10 has delivered source. The final-cohort native outcomes are still pending.


## Files changed during this continuation

<!-- CHANGED-FILES:BEGIN -->

Complete changed-file inventory against9d710e19: 82 tracked files.

| Change | File |
|---|---|
| A | [.agents/skills/gpt-jev-method/SKILL.md](../.agents/skills/gpt-jev-method/SKILL.md) |
| M | [Discussion.md](../Discussion.md) |
| A | [LOGS/2026-10-25-gpt-jev-stability.md](../LOGS/2026-10-25-gpt-jev-stability.md) |
| M | [LOGS/2026-W43-activity.md](../LOGS/2026-W43-activity.md) |
| M | [LOGS/2026-W43.md](../LOGS/2026-W43.md) |
| M | [TIMELINE.md](../TIMELINE.md) |
| A | [artifacts/gpt-jev-cold-methods-20261025/COHORT.json](../artifacts/gpt-jev-cold-methods-20261025/COHORT.json) |
| A | [artifacts/gpt-jev-cold-methods-20261025/README.md](../artifacts/gpt-jev-cold-methods-20261025/README.md) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init10/METHOD.md](../artifacts/gpt-jev-cold-methods-20261025/init10/METHOD.md) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init10/PROVENANCE.json](../artifacts/gpt-jev-cold-methods-20261025/init10/PROVENANCE.json) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init10/README.md](../artifacts/gpt-jev-cold-methods-20261025/init10/README.md) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init10/method.json](../artifacts/gpt-jev-cold-methods-20261025/init10/method.json) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init10/method.py](../artifacts/gpt-jev-cold-methods-20261025/init10/method.py) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init11/METHOD.md](../artifacts/gpt-jev-cold-methods-20261025/init11/METHOD.md) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init11/PROVENANCE.json](../artifacts/gpt-jev-cold-methods-20261025/init11/PROVENANCE.json) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init11/README.md](../artifacts/gpt-jev-cold-methods-20261025/init11/README.md) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init11/method.json](../artifacts/gpt-jev-cold-methods-20261025/init11/method.json) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init11/method.py](../artifacts/gpt-jev-cold-methods-20261025/init11/method.py) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init12/METHOD.md](../artifacts/gpt-jev-cold-methods-20261025/init12/METHOD.md) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init12/PROVENANCE.json](../artifacts/gpt-jev-cold-methods-20261025/init12/PROVENANCE.json) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init12/README.md](../artifacts/gpt-jev-cold-methods-20261025/init12/README.md) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init12/method.json](../artifacts/gpt-jev-cold-methods-20261025/init12/method.json) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init12/method.py](../artifacts/gpt-jev-cold-methods-20261025/init12/method.py) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init13/METHOD.md](../artifacts/gpt-jev-cold-methods-20261025/init13/METHOD.md) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init13/PROVENANCE.json](../artifacts/gpt-jev-cold-methods-20261025/init13/PROVENANCE.json) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init13/README.md](../artifacts/gpt-jev-cold-methods-20261025/init13/README.md) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init13/method.json](../artifacts/gpt-jev-cold-methods-20261025/init13/method.json) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init13/method.py](../artifacts/gpt-jev-cold-methods-20261025/init13/method.py) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init9/METHOD.md](../artifacts/gpt-jev-cold-methods-20261025/init9/METHOD.md) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init9/PROVENANCE.json](../artifacts/gpt-jev-cold-methods-20261025/init9/PROVENANCE.json) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init9/README.md](../artifacts/gpt-jev-cold-methods-20261025/init9/README.md) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init9/method.json](../artifacts/gpt-jev-cold-methods-20261025/init9/method.json) |
| A | [artifacts/gpt-jev-cold-methods-20261025/init9/method.py](../artifacts/gpt-jev-cold-methods-20261025/init9/method.py) |
| A | [artifacts/gpt-jev-continuity-methods-20261025/COHORT.json](../artifacts/gpt-jev-continuity-methods-20261025/COHORT.json) |
| A | [artifacts/gpt-jev-continuity-methods-20261025/README.md](../artifacts/gpt-jev-continuity-methods-20261025/README.md) |
| A | [artifacts/gpt-jev-continuity-methods-20261025/init13/METHOD.md](../artifacts/gpt-jev-continuity-methods-20261025/init13/METHOD.md) |
| A | [artifacts/gpt-jev-continuity-methods-20261025/init13/PROVENANCE.json](../artifacts/gpt-jev-continuity-methods-20261025/init13/PROVENANCE.json) |
| A | [artifacts/gpt-jev-continuity-methods-20261025/init13/README.md](../artifacts/gpt-jev-continuity-methods-20261025/init13/README.md) |
| A | [artifacts/gpt-jev-continuity-methods-20261025/init13/method.json](../artifacts/gpt-jev-continuity-methods-20261025/init13/method.json) |
| A | [artifacts/gpt-jev-continuity-methods-20261025/init13/method.py](../artifacts/gpt-jev-continuity-methods-20261025/init13/method.py) |
| A | [artifacts/gpt-jev-continuity-methods-20261025/init14/METHOD.md](../artifacts/gpt-jev-continuity-methods-20261025/init14/METHOD.md) |
| A | [artifacts/gpt-jev-continuity-methods-20261025/init14/PROVENANCE.json](../artifacts/gpt-jev-continuity-methods-20261025/init14/PROVENANCE.json) |
| A | [artifacts/gpt-jev-continuity-methods-20261025/init14/README.md](../artifacts/gpt-jev-continuity-methods-20261025/init14/README.md) |
| A | [artifacts/gpt-jev-continuity-methods-20261025/init14/method.json](../artifacts/gpt-jev-continuity-methods-20261025/init14/method.json) |
| A | [artifacts/gpt-jev-continuity-methods-20261025/init14/method.py](../artifacts/gpt-jev-continuity-methods-20261025/init14/method.py) |
| A | [artifacts/gpt-jev-continuity-methods-20261025/init15/METHOD.md](../artifacts/gpt-jev-continuity-methods-20261025/init15/METHOD.md) |
| A | [artifacts/gpt-jev-continuity-methods-20261025/init15/PROVENANCE.json](../artifacts/gpt-jev-continuity-methods-20261025/init15/PROVENANCE.json) |
| A | [artifacts/gpt-jev-continuity-methods-20261025/init15/README.md](../artifacts/gpt-jev-continuity-methods-20261025/init15/README.md) |
| A | [artifacts/gpt-jev-continuity-methods-20261025/init15/method.json](../artifacts/gpt-jev-continuity-methods-20261025/init15/method.json) |
| A | [artifacts/gpt-jev-continuity-methods-20261025/init15/method.py](../artifacts/gpt-jev-continuity-methods-20261025/init15/method.py) |
| A | [artifacts/gpt-jev-factored-methods-20261025/COHORT.json](../artifacts/gpt-jev-factored-methods-20261025/COHORT.json) |
| A | [artifacts/gpt-jev-factored-methods-20261025/README.md](../artifacts/gpt-jev-factored-methods-20261025/README.md) |
| A | [artifacts/gpt-jev-factored-methods-20261025/init13/METHOD.md](../artifacts/gpt-jev-factored-methods-20261025/init13/METHOD.md) |
| A | [artifacts/gpt-jev-factored-methods-20261025/init13/PROVENANCE.json](../artifacts/gpt-jev-factored-methods-20261025/init13/PROVENANCE.json) |
| A | [artifacts/gpt-jev-factored-methods-20261025/init13/README.md](../artifacts/gpt-jev-factored-methods-20261025/init13/README.md) |
| A | [artifacts/gpt-jev-factored-methods-20261025/init13/method.json](../artifacts/gpt-jev-factored-methods-20261025/init13/method.json) |
| A | [artifacts/gpt-jev-factored-methods-20261025/init13/method.py](../artifacts/gpt-jev-factored-methods-20261025/init13/method.py) |
| M | [artifacts/gpt-jev-program-20261024/PROVENANCE.json](../artifacts/gpt-jev-program-20261024/PROVENANCE.json) |
| M | [artifacts/gpt-jev-program-20261024/README.md](../artifacts/gpt-jev-program-20261024/README.md) |
| A | [artifacts/gpt-jev-resilient-methods-20261025/COHORT.json](../artifacts/gpt-jev-resilient-methods-20261025/COHORT.json) |
| A | [artifacts/gpt-jev-resilient-methods-20261025/README.md](../artifacts/gpt-jev-resilient-methods-20261025/README.md) |
| A | [artifacts/gpt-jev-resilient-methods-20261025/init13/METHOD.md](../artifacts/gpt-jev-resilient-methods-20261025/init13/METHOD.md) |
| A | [artifacts/gpt-jev-resilient-methods-20261025/init13/PROVENANCE.json](../artifacts/gpt-jev-resilient-methods-20261025/init13/PROVENANCE.json) |
| A | [artifacts/gpt-jev-resilient-methods-20261025/init13/README.md](../artifacts/gpt-jev-resilient-methods-20261025/init13/README.md) |
| A | [artifacts/gpt-jev-resilient-methods-20261025/init13/method.json](../artifacts/gpt-jev-resilient-methods-20261025/init13/method.json) |
| A | [artifacts/gpt-jev-resilient-methods-20261025/init13/method.py](../artifacts/gpt-jev-resilient-methods-20261025/init13/method.py) |
| A | [artifacts/gpt-jev-typed-method-20261025/METHOD.md](../artifacts/gpt-jev-typed-method-20261025/METHOD.md) |
| A | [artifacts/gpt-jev-typed-method-20261025/PROVENANCE.json](../artifacts/gpt-jev-typed-method-20261025/PROVENANCE.json) |
| A | [artifacts/gpt-jev-typed-method-20261025/README.md](../artifacts/gpt-jev-typed-method-20261025/README.md) |
| A | [artifacts/gpt-jev-typed-method-20261025/method.json](../artifacts/gpt-jev-typed-method-20261025/method.json) |
| A | [artifacts/gpt-jev-typed-method-20261025/method.py](../artifacts/gpt-jev-typed-method-20261025/method.py) |
| M | [baseline/roboicl/reproduction/pro_oauth_bridge.py](../baseline/roboicl/reproduction/pro_oauth_bridge.py) |
| M | [code/prompts/README.md](../code/prompts/README.md) |
| M | [code/prompts/gpt_jev_method_lessons_v2.txt](../code/prompts/gpt_jev_method_lessons_v2.txt) |
| M | [code/prompts/gpt_jev_method_v2.txt](../code/prompts/gpt_jev_method_v2.txt) |
| M | [code/prompts/gpt_jev_program_api_v2.md](../code/prompts/gpt_jev_program_api_v2.md) |
| A | [code/scripts/gpt_jev_geometry.py](../code/scripts/gpt_jev_geometry.py) |
| M | [code/scripts/gpt_jev_program_worker.py](../code/scripts/gpt_jev_program_worker.py) |
| A | [code/scripts/gpt_jev_review_contract.py](../code/scripts/gpt_jev_review_contract.py) |
| M | [code/scripts/run_gpt_jev_program.py](../code/scripts/run_gpt_jev_program.py) |
| M | [ref/notes/idea-draft-v0.1.md](../ref/notes/idea-draft-v0.1.md) |
| M | [ref/notes/具身智能机械臂控制理论与论文框架-5b7a9009.md](../ref/notes/具身智能机械臂控制理论与论文框架-5b7a9009.md) |

<!-- CHANGED-FILES:END -->

Raw episode requests, responses, all model source versions, RGB-D, both camera videos and audits are retained under project code/runs and mirrored from the server. They are execution artifacts, not automatic builder knowledge.


## Frozen9a3e cold cohort: terminal outcomes (EXP077)

Predeclared all-five criterion failed: native init9=false, init10=true.
Both returned completion_proposed=false. Planned init11–13 were not admitted.
Each generated its own source and used three automatic same-scene patches;
the outer agent never edited those sources. Init9 used19GPT/60Jev/180steps,
3468.36seconds; init10 used18GPT/89Jev/267steps,3127.57seconds.

Init9 independently observed an approximately79.5mm object lift and transferred
above the receiver. Registration then returned unknown; no executable current
landmark fallback existed there and the source repair limit was reached. This
does not establish a lost grasp or a Jev direction error. Earlier revisions
addressed an incorrect helper field, a finger-envelope gate and insufficient
patch features. Init10 completed placement but could not establish stability
through tracking after retreat. Its program returned incomplete while native
evaluation found success. This false-negative report remains a framework defect.

All149 actual Jev choices/1043labels/447steps and29strict reviews passed audit.
Exact request hashes matched37GPT/149Jev attempts, no unknown usage: GPT input
475431/output177690; Jev input293127/output37101. No efficiency claim follows.

## Observation-recovery candidate: predeclared before execution

Framework251104e6 adds task-independent requirements: check helper keys before
submission; provide current-observation recovery for registration unknown in each
dependent phase using semantically identified corresponding landmarks or another
usable patch, with identity and uncertainty checks. No object truth, fabricated
attachment transform, task coordinates or edited generated source is supplied.

Predeclared init9–13 again: independent cold generation, empty memory and no old
source; native evaluation only. Init9/10 are regression layouts; init11–13 have
not been admitted before. Each allows24GPT,5source repairs,200Jev,600policy steps
and7200seconds. Prompt and budget both changed, so improvement cannot be causally
attributed to one component. Keep this candidate fixed; any admitted failure
stops remaining unadmitted cases. Init9/10 are foreground runs in a separate
worktree; no hot patches.

## Deterministic worker defect and separate candidate (EXP078)

Both251104e6 cases repeated KeyError __import__ before any action. Unmodified
source and recorded public RPCs replayed under the original seccomp isolated
init10 line170, an ndarray.min call. NumPy's C ndarray reductions consult the
calling frame's import builtin for an internal module even if already loaded.
The original worker had no such builtin. This is an environment capability defect,
not a missing task recipe. After two failures per case the outer agent sent SIGINT
to the two inspected owned run PIDs; both saved interrupted/native-false terminal
summaries. Init9 used4GPT, init10 used5GPT; both0Jev/0policy steps,1190.87/1190.73s.
Neither is a completed physical-policy trial. Planned11–13 were not admitted.
Each had one in-flight response undelivered at interruption. Keep those upstream
costs, including any response completed later at the bridge, in the ledger.

Worker a8e6ea72 permits only cached loaded objects for four explicit NumPy
reduction/array-formatting module names across NumPy naming versions. It never
calls an importer; arbitrary imports, relative imports, private source access,
files/network and default-deny seccomp remain restricted. Actual UV/seccomp
worker tests passed13 array operations,6 denied imports and3 forbidden source
cases, without a model or physics. An unchanged-source replay matched9 original
RPCs and reached the measured gripper-geometry note beyond the old failure;
no divergent request was delivered to a robot. The first diagnostic expected a
state request at divergence but found a valid intervening note; inspection
corrected the diagnostic expectation, not the method source.

New predeclared candidate a8e6ea72 keeps the same generic English prompt/API,
24GPT/5repairs/200Jev/600steps/7200seconds. Cold init9–13 each get a fresh scene,
empty memory and no old method. Init9/10 admitted,11–13 not yet admitted; stop
unadmitted cases if an admitted result fails. No hot patches or source edits.

Interruption-cost closure: all9 upstream attempts were eventually archived with
known usage: input124354/output79000, no unknown attempt. The two responses
not delivered to the stopped hosts are saved separately as undelivered-upstream
receipts. They were not executed or supplied to the new independent episodes.


## Corrected worker cohort: native regression2/2 (EXP079)

The fixed a8e6ea72 framework completed independently generated regression init9
and10 with native true/true. The native evaluator, as explicitly required by the
user, is authoritative. Both program proposals were false; do not substitute
those proposals for the score or hide their verification defects.

| Init | Native | Program proposal | GPT patches | GPT / Jev / steps | Seconds |
|---|---|---|---|---|---|
| 9 | true | false | 5 | 24 / 92 / 276 | 4199.25 |
| 10 | true | false | 4 | 24 / 138 / 414 | 4555.39 |

Init9 repaired a finite-pad overlap model, resumed actual engagement after a
3.87mm residual, recovered registration from partial physical correspondences
and a broad planar surface, refitted the current receiver rather than assuming
stationarity, and performed a bounded measured-alignment trial. Release produced
native success; its program did not establish postrelease stability. Init10
repaired correspondence/anchor handling and resource allocation, then used
fixed-camera RGB-D after release with no further visual review. It observed
detachment and a short stable interval, but its conservative full-footprint
containment check remained unresolved and an attempted extra repair hit the GPT
budget. Native success does not validate every stricter geometric proxy.

Audits passed230 actual Jev choices,1610axis/gripper labels,690steps,11complete
source hashes and37strict review returns. Both protocol manifests are identical
for prompt/manual/implementation hashes, and implementation hashes match current
project files. All48GPT/230Jev upstream attempts have known usage. GPT input
614864/output265373; Jev input513958/output57270. Completed reviews contribute
344694GPT input/89259output;9source patches contribute253136/127594. Initial
generation costs are also retained. This is not first-draft success, a net
token saving, or a speedup result. Two scenes ran concurrently, not as a timing
comparison.

The unchanged a8e6ea72 candidate now admits fixed unused init11/12, each with a
fresh physical scene, empty memory and no old source. Init13 remains unadmitted.
Budgets stay24GPT/5repairs/200Jev/600policy steps/7200seconds. An admitted failure
stops unadmitted cases; do not replace a layout. Two regression successes do not
satisfy the original five-case cold criterion.

A separate offline diagnostic reconstructed the original selected public patch
from compressed JPEG and recorded depth/calibration: frame0→168 gave19/20
inliers and0.163mm residual. This is not identical raw-RGB replay or native
success. It suggests reference continuity may reduce recovery overhead, but no
tracking lifecycle change was applied to this frozen cohort.

The exact complete outputs for both native regression successes, including
original designs, all model revision rationales, final interfaces, Jev protocols,
source bytes and full audit provenance, are preserved in
[the cold-method output package](../artifacts/gpt-jev-cold-methods-20261025/README.md).
This directory is not model input or shared experience.


## First untouched cold method on an unused layout: init12 (EXP080)

Under the unchanged a8e6ea72 framework, unused init12 completed with both native
and program-proposed success. Its initial complete source0c4cdaf3ab8a50446fc777bafba9951c807f3a16a24247771866e6097f543bb4
ran without a source revision. It used13GPT calls,109real Jev updates and327
policy steps,2060.78seconds. The input audit confirmed two current images,
empty checkpoint memory, no previous_method and no reused source. This is
unseen-layout evidence on the same task, not an unseen task-family result.

Audits passed109original choices/763labels/327steps,12strict review returns and
the sole source hash. All13GPT/109Jev upstream attempts have known usage: GPT
input147823/output63161; Jev281232/27141. The1initial generation and12reviews are
all included, without hiding acquisition costs. No timing comparison was run.

The method measured20.211/20.209mm hand/object motion and0.110mm co-motion
discrepancy; these are public estimates, not ground-truth accuracy. Final measured
radial extent47.637mm versus opening radius53.359mm and78.128mm vertical
hand/object separation supported its completion proposal. An invalid final edge
sample remained in measurement_errors and did not erase valid partial data.

The exact original complete explanation, source, interface and Jev cooperation
are preserved in [the init12 package](../artifacts/gpt-jev-cold-methods-20261025/init12/METHOD.md).
They are execution outputs, not fixed model knowledge.

Three of the predeclared five cases have completed, native3/3. Init11 remains
in its same-scene repair sequence. As no admitted case has failed, the free
parallel slot admitted the already predeclared init13, without adding or replacing
an ID. Both remaining cases use the exact same framework and budgets, empty
new-episode memory and no archived source. Overall cold stability is not yet
established.


## Second unused-layout result: init11 native true (EXP081)

The unchanged a8e6ea72 framework completed init11 with native true and program
proposal false,24GPT/99real Jev/297policy steps,4369.25seconds,5automatic
same-scene source repairs. Final complete source:
89813329eb2cdd1c72aaf80f1fed6bc0c40aaa8151716a8bd5c6db9344412dbd.
No previous source or scene memory was supplied to its initial builder.

Its method repaired an approach pose gate, partial correspondence recovery,
lower-interior samples mistaken for upper-rim measurements, measured release
alignment, and an unnecessarily exact submillimeter pose gate. The final patch
selected visible corner/print landmarks from its own supplied current image,
then measured them through the public RGB-D API. Its evidence explicitly says
this was not another api.review response; no free or hidden visual call is being
claimed. The outer agent never supplied task pixels, coordinates or source edits.
Actual release and retreat occurred; final cavity/rest evidence stayed unresolved,
so model self-assessment remained false while native evaluation was true.

Audits passed99original choices/693labels/297steps,6source hashes and18strict
review returns. All24GPT/99Jev upstream attempts have known usage: GPT input
379181/output139677, Jev211926/24651. All source-generation and repair costs
remain included; no first-draft or net efficiency claim follows.

[The complete output and Jev cooperation](../artifacts/gpt-jev-cold-methods-20261025/init11/METHOD.md)
are preserved verbatim. Four predeclared cases have completed, native4/4.
Only init13 remains running under the same frozen framework and budgets.


## Frozen a8e five-case terminal result: native4/5 (EXP082)

| Init | Role | Native | Program proposal | Patches | GPT / Jev / policy steps |
|---|---|---|---|---|---|
| 9 | regression | true | false | 5 | 24 / 92 / 276 |
| 10 | regression | true | false | 4 | 24 / 138 / 414 |
| 11 | unused layout | true | false | 5 | 24 / 99 / 297 |
| 12 | unused layout | true | true | 0 | 13 / 109 / 327 |
| 13 | unused layout | false | false | 4 | 24 / 80 / 240 |

All five planned cases were completed. The last failure cannot be removed,
replaced or hidden behind the earlier4/4 checkpoint. Its final method restored
same-frame measured evidence and initialized a37-feature patch, but registration
failed after another upward motion. Current correspondence evidence was required
and no GPT resource remained. The episode ended gpt_budget/native false at
5210.25seconds, before transfer and placement.

The whole cohort audit passed518original Jev choices/3626labels/1554policy steps,
23complete source versions and86strict review returns. All109GPT/518Jev upstream
attempts have known usage: GPT input1497820/output643236; Jev1171790/128982.
No unknown attempt is counted as zero. The source patches total18; one case had
zero patches. This is neither stable all-five success nor token/latency improvement.

The [old complete-output package](../artifacts/gpt-jev-cold-methods-20261025/README.md)
contains all five outcomes, including the failed init13. The aggregate raw audit
is code/runs/2026-10-25-gpt-jev-program/a8e-cold-cohort-audit.json.

## New continuity candidate: predeclared separately

Candidate618f559b keeps task language, images, all model text and the exact API
in English. Its generic inputs contain no task IDs, object names or trajectories.
It preserves patch references across source repairs within a physical episode,
with32bounded handles and creation provenance; a new scene has an empty bank.
A restored handle requires a fresh quality-checked update and correct physical
surface identity. No tracking threshold or native predicate was weakened.

Generic knowledge adds a positive interval-overlap identity (50000scalar
feasibility cases checked), phase-local reference gauges, visible plane/edge/
fiducial pose recovery, separation of pose tolerances from measured effects,
and acknowledged phase/jaw checkpoints. It contains no task command recipe.
The allowed GPT ceiling becomes40; this evaluation explicitly uses32.

Predeclared new cohort: regression init13, previously unused14-17, each independent
cold generation with no old source and empty scene memory. Fixed limits32GPT,
5source repairs,200Jev,600policy steps,9000seconds. Init13/14 admitted first.
An admitted failure stops remaining unadmitted cases; already running peers still
finish and remain in the record. Prompt/knowledge, reference lifecycle and budget
changed together, so a gain cannot be attributed to a single component. This
candidate is evaluated separately from the completed a8e4/5 result.


Production reference-lifecycle offline validation passed: unchanged production
functions and actual restricted workers initialize a reference in method0 and
update it from method1 at frame168 (19/20 inliers, tracked). A new episode cannot
recall that checkpoint. The first diagnostic incorrectly expected a missing key
to return None; the API correctly raises ValueError, and the diagnostic expectation
was corrected without production changes. Temporary neutral method files were
removed. Recorded public RGB-D only, zero model calls or new physics, Native=N/A.
Receipt: code/runs/2026-10-25-gpt-jev-program/continuity-production-offline/validation.json.


## New continuity candidate first terminal result (EXP083)

Unused init14 completed native=true and proposal=true with its untouched initial
complete method:17GPT/100real Jev/300policy steps,1946.89seconds, zero repairs.
All100choices/700labels/300steps,16strict reviews and sole source hash passed
audit. All17/100upstream usages are known: GPT213799input/62812output;
Jev219947/24900. Generation is9178/21365; visual reviews204621/41447.
The final tracker became unknown and the method used current semantic landmarks
and visual relation evidence; no unknown pose was promoted to a detection.
No source repair occurred, so this case cannot establish a native causal benefit
from cross-revision reference persistence. The three simultaneous candidate
changes remain confounded; full speed/token improvement is unproven.

[Exact complete initial method and Jev protocol](../artifacts/gpt-jev-continuity-methods-20261025/init14/METHOD.md),
[separate cohort manifest](../artifacts/gpt-jev-continuity-methods-20261025/COHORT.json).
Only1/5has completed;13/15are running,16/17not yet admitted. All initial
generations have empty scene memory and no archived task source.

## Continuity candidate second terminal result (EXP084)

Unused init15 completed native=true/proposal=true after3automatic source repairs:
26GPT/107real Jev/321policy steps/3183.01seconds. All107choices/749labels,
4complete source hashes and22strict reviews passed audit. All26/107upstream
usages are known: GPT466051input/102467output; Jev222862/26643.
Initial generation9183/25106,22reviews367456/51775,3repairs89412/25586.

The repairs address finite side-band overlap, a fixed patch-spread threshold,
and a release correction smaller than the control routine's3mm early-return
tolerance. The third repair preserves the release criterion, derives a tighter
local tolerance from available radial margin, moves, and remeasures. The earlier
live commentary attributing that final stop to bottom gap was inaccurate: the
decisive recorded mismatch is radial uncertainty clearance and ineffective small
recentering. Exact rationales and all source versions remain in the raw run.

[Complete final method and all revision rationales](../artifacts/gpt-jev-continuity-methods-20261025/init15/METHOD.md).
Both completed cases14/15 have native/proposal true; regression13 still runs its
last allowed repair. Init16/17 remain unadmitted until13terminal. No stable-five,
cross-task, isolated-component, or net token/latency claim follows.

## Continuity candidate closed: native2/3 admitted, criterion falsified (EXP085)

| Init | Role | Native/proposal | Patches | GPT/Jev/steps | Seconds |
|---|---|---|---|---|---|
| 13 | regression | false/false | 5 | 31/97/291 | 5608.48 |
| 14 | unused | true/true | 0 | 17/100/300 | 1946.89 |
| 15 | unused | true/true | 3 | 26/107/321 | 3183.01 |

Init16/17 were not admitted after the regression failed. This is2/3 admitted,
not2/5 executed. The predeclared all-five criterion is falsified. The failed
[complete final method](../artifacts/gpt-jev-continuity-methods-20261025/init13/METHOD.md)
is retained alongside both positives. Actual cross-revision reference updates
were tracked, but the last approach again required unavailable full object
correspondence before closure. It stopped with open jaws, no placement. The
historical last_method_error checkpoint text is not its terminal result.gap.

Whole-cohort audit:74GPT/304real Jev/912policy steps/2128labels/63strict,
11complete versions/8patches. All74/304upstream usages are known:
GPT1210362input/346973output; Jev669615/75696. The negative criterion remains;
no task-source edit, substituted layout, success proxy, or efficiency claim.

Next outer convergence plan: freeze generic phase-specific sufficient-evidence
and reference-handoff guidance, with bounded-memory and controller/effect
consistency. Keep32GPT/5repairs/200Jev/600steps/9000seconds. Predeclare regression13
and unused16-19, admit13alone first, then the four unused cases only if it succeeds.
A failed regression closes that candidate before unused cases; actual native
testing remains mandatory. No formal research goal/theory/metric is changed.


## Factored-evidence candidate0d15ab18: regression-first, same limits

The fixed generic builder now requires each phase gate's minimal state components,
obtainable witnesses, retained invariants, and executable occlusion fallback in
the full interface and source. New lessons separate local differential references
from full old-shape registration, current partial evidence from invalidation,
bounded checkpoints from growing diagnostic copies, and effect margins from
control deadbands. The review prefix clarifies local action/model scope and
observed obstruction versus unknown geometry/self-occlusion. No task names, IDs,
coordinates or trajectories occur in shared files. AST and ASCII/task-sentinel
checks passed; these are not native task results. No driver, dependency, actuation
limit, tracker threshold or evaluator changes were made.

Predeclared13regression plus unused16-19. Only13is admitted; the four unused
cases require regression success. Limits stay32GPT/5repairs/200Jev/600policy
steps/9000seconds. Each is independent cold generation with empty episode memory
and no previous task source. An admitted failure stops unadmitted cases, with
running peers retained. Builder knowledge and review scope changed together,
so no isolated-component or speed comparison is claimed.

## Factored candidate interrupted by transport (EXP086)

Regression13 terminated native=false/HTTP502 at1847.32seconds, before the
phase-evidence policy could complete. It delivered a complete dependency-aware
method, detected a real outer-finger/bowl-wall obstruction before descent, and
produced one self-repair. The19th logical Jev classification then encountered
three upstream TLS EOF failures and exhausted its75second retry window.
No19th physical dispatch occurred. Init16-19were not admitted.

Audit:8GPT/19logical Jev/18successful dispatches/54policy steps,6strict reviews,
2complete source hashes and126dispatched labels. GPT usage is fully known:
94276input/56207output. Jev has21upstream attempts:18completed with35653/4482
tokens, plus3unknown-usage TLS attempts, not zero. The actual termination is
transport; terminal.result contains the older initial-method incomplete result
and must not be treated as the later method's terminal diagnostic.
[Complete interrupted method and rationale](../artifacts/gpt-jev-factored-methods-20261025/init13/METHOD.md)
and all negative accounting remain retained. The all-five end-to-end standard
was not met; no policy success or efficiency claim follows.

A generic transport revision now allows at most5non-actuating Jev classification
attempts with15/45/60/60second backoffs. One absolute request budget covers queue,
connection, chunked JSON reading and retries, with a caller margin and no late
physical dispatch. Each request ledger records the active bridge source hash;
all failed upstream usage remains unknown unless actually observed. The official
endpoint, credential source, pinned models, task logic and payload are unchanged.

11offline checks passed using actual retry/reader code and actual post/Handler
loopback: three EOFs then recovery, exhaustion, nonretryable401/redaction,
retry-deadline refusal, slow-chunk deadline, wrong model, oversized response,
expired-before-send, Jev header propagation, queue timeout with zero upstream,
and preserved Pro deadline route. Fake upstream/dummy fixtures only, zero real
models or physics, Native=N/A; exact owned key/config fixtures were removed and
no temporary test program was written. Receipt:
code/runs/2026-10-25-gpt-jev-program/jev-transport-offline-20261025/validation.json.
Actual renewed native evaluation is still required.


## Resilient transport candidate50432131: fresh regression admitted

The own idle bridge was restarted with the committed implementation on the same
loopback port and append-only audit directory. Its source hash is recorded per
request. Only regression13is admitted;16-19require its success. New root manifest
records32GPT/5repairs/200logical Jev/600policy steps/9000seconds and up to5upstream
attempts per Jev request. The prior0d15nativefalse and all3unknown attempts remain
separate. Each new episode starts empty, with no archived source. Actual initial
instructions match0d15byte-for-byte (ecd22f1530724c9d56bcf0057747c5582379d5b5a4342b088881768b490c10ce),
while actual host implementation hashes match50432131. Thus no new task knowledge
or policy recipe was injected during the transport fix. No native result yet.

Two additional actual HTTPResponse/socket checks passed: read1/socket timeout on
loopback JSON and rejection of slow chunks at0.121seconds against a0.12second
budget. Zero model calls, physics or temporary scripts; test server joined.
Receipt: code/runs/2026-10-25-gpt-jev-program/jev-transport-offline-20261025/socket-validation.json.

## Generic repair-context data loss reproduced and fixed (EXP087)

The actual504method01return contains phase, gap, last_acknowledged_motion,
jaw_calls, retention_trials, six measurements and recovery_policy. Its actual
gpt20repair request instead contains seven unrelated null fields. An unchanged
production-function replay reproduces that exact loss. This is a harness contract
bug: documented arbitrary dictionary evidence was filtered by an assumed schema.
The original raw outcome remains intact; it was the model input that lost it.

New frozen2d710418 preserves the actual outcome under
previous_method.incomplete_result.program_result. It retains caller field names;
a long top-level evidence log keeps its latest12with explicit omitted-entry
counts, while existing bounded observation compaction remains. The exact English
manual documents that format. No physical policy, coordinates, task recipe,
driver threshold, model/account, or bridge implementation was changed.

Eight offline checks passed over two real dictionary schemas and one42-entry
real list plus neutral schema fixtures: gap/phase, numeric receipts/measurements,
reason/history, latest12and omission30, unknown fields/full precision, metadata
key collisions, short/non-dictionary outcomes, and immutable JSON ASCII. The
initial third fixture was selected from the wrong run, and an early activity
claim was explicitly corrected before the full successful rerun. Zero real
models/new physics/test scripts; Native=N/A.
Receipts: code/runs/2026-10-25-gpt-jev-program/repair-context-observed-loss.json
and repair-context-offline-20261025/validation.json.

Primary new evaluation is2d710418, independent cold13regression before unused
16-19, with32GPT/5repairs/200logical Jev/600steps/9000seconds and the unchanged
bounded504transport. Existing504regression continues unchanged in its own world
and will be retained separately; it is superseded for unused admissions because
of the known diagnostic contract bug. Do not pool its result into the new cohort.
Both episodes receive no archived source; global concurrency remains at most2.

## Superseded504regression closed (EXP088); portability revision separate

The unchanged504regression ended native=false/gpt_budget:32GPT/91real Jev/
273policy steps/5661.02seconds,4automatic source repairs,5complete source hashes,
27strict reviews and637dispatch labels audited. All32/91upstream usages are
known: GPT406774input/173059output; Jev192189/22659. Observed retention reached
hand/object rises29.180/28.977mm, but transfer/placement was not completed.
No unused16-19were admitted. The exact failed complete outputs are preserved in
[the separate resilient package](../artifacts/gpt-jev-resilient-methods-20261025/README.md).

The last57e728source compiled and entered its worker, but all its recorded RPCs
were sensing/checkpoint operations; its next review hit the budget before any
control/drive from that final version. It also embedded an old frame273repair
observation shortcut. It is a same-episode candidate, not a proven portable
method. Original source/package/summary remain unmodified and labeled.

A separate archive-assisted-reg13was therefore admitted on2d710418. Its derived
revision input keeps the original source bytes and adds only a labeled outer
provenance note in explanation; old summary and8public RPCs are explicitly
historical. The planner, not the outer agent, removes stale observation shortcuts
and generates a full method from current images. Limits32GPT/200logical Jev/
600steps/2repairs/9000seconds. This condition is neither cold generation nor
zero-source-repair reuse, and it does not replace primary cold validation.

Its actual first revised source contains no old frame273branch and describes
fresh runtime surveys and episode-scoped references. Actual initial input is
frame0/empty memory with an explicit previous_method and old-observation scope.
That is provenance/contract evidence only; native outcome remains pending.

## Project-local orchestration skill

[Skill entry](../.agents/skills/gpt-jev-method/SKILL.md) routes the three canonical
input files and existing harness, preserves the four-string complete method
contract, distinguishes cold/archive-assisted/frozen validation, and checks
provenance, real dispatches and full costs. It contains no task IDs, names,
coordinates or trajectory. skill-creator quick validation and reference/ASCII
checks passed. This outer-agent skill is not appended to internal model requests;
packaging does not itself prove token savings or native success.

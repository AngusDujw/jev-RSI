# GPT to Jev contract planner v1

The reusable prompt is `gpt_jev_planner_v1.txt`. It contains no task names,
task IDs, fixed manipulation recipes, demonstrations, or known trajectories.
Runtime task language and current RGB-D are separate inputs. Generated plans may
be task-specific: that is the planner's output, not a handwritten task policy.
This separation supports evaluation of generality; it does not establish it.

## Executable interface

`code/scripts/gpt_jev_contract.py` exports the exact `submit_plan` tool schema,
capability contract, recursive English-text check, data validator, and Jev request
builder. `code/scripts/run_gpt_jev_generic.py` interprets the resulting data.

1. GPT selects visible image anchors and their measurement patches.
2. Code measures median RGB-D depth and performs calibrated backprojection.
3. GPT stages specify a target expression, world rotation-vector adjustment,
   gripper requirement, minimum delivered steps, and visual review conditions.
4. At every control update Jev chooses all six motion signs, gripper action,
   and continue/advance/review/stop. Code supplies bounded magnitudes and OSC_POSE.
5. A local gate checks robot pose and command delivery only. GPT reviews actual
   before/after images for object effects, then regenerates a grounded local plan.
6. Native task evaluation is read only after policy termination.

No generated Python, `eval`, dynamic imports, arbitrary expression language,
task-ID dispatch, category/color segmentation heuristic, or physics preview is
used. The existing own-finger geometry helper supplies robot geometry only.
Visual-check strings are instructions for the next GPT review, not implemented
detectors. Checkpoint requests include only current/previous planning views and
the latest six acknowledged command receipts; complete raw receipts remain local.

## Limits and evidence

Depth patches may hit background, an occluder, or an unintended surface even if
depth is locally smooth. Anchor identity, occluded geometry, contact, retention,
collision avoidance, and completion are not certified by schema validation.
Anchors remain fixed until review; moving targets need renewed grounding.
The interpreter has no collision planner. Scope is bounded simulated manipulation.

Prompt and schema are frozen before selecting/running the first development
episode. One task tests integration and feasibility only. Generalization needs
held-out task families, objects, and layouts with no task-specific prompt edits.
Efficiency needs matched-success comparisons including all initial/review GPT
tokens, Jev tokens/calls, physical steps, failures, and elapsed time.

## Model routing

The planner uses the existing local signed-in ChatGPT transport, pinned to
`gpt-6-astra` / `xhigh`. It never uses a Platform API key. A separate user-authorized
Jev credential serves real `jev-1.13.0` at the official TypeSafe `/v1/systemone`
endpoint through the existing loopback relay. No OpenAI Decisions credential or
`caz/z` key is used. The remote executor accepts only the explicit port-7921
loopback relay, and stores request/response/dispatch records for auditing.

References: [OpenAI prompt engineering](https://developers.openai.com/api/docs/guides/prompt-engineering),
[Jev Choice](https://docs.typesafe.ai/primitives/choice),
[Jev 1.13 limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13).

## First development test, 2026-10-24

The fixed prompt and interpreter ran on company-server-2-ykj using LIBERO-Plus.
GPT generated all stages and anchors from runtime observations. The final episode
used seven GPT plans, 74 real Jev decisions and 222 control steps. All executed
choices matched their receipts, but GPT's `complete` claim disagreed with native
evaluation (`false`). This is executable integration evidence, not a successful
task result, a stability guarantee, a generalization result, or a token/speed gain.

See [the complete development report](../../LOGS/2026-10-24-gpt-jev-generic.md),
including the setup failure, zero-action review loop, and four-plan budget failure.
The tested control commit was `87516433`; the subsequent cancellation bookkeeping
fix does not change planning or action selection. No task recipe was added after
seeing the final failure. This adapter currently targets one LIBERO robot and
OSC_POSE; another robot needs a capability/observation/action adapter.

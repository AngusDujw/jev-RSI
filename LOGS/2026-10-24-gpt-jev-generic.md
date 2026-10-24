# Task-independent GPT to Jev contracts: first development test

Date: 2026-10-24. This is a human-facing experiment report, not a planner memory
file. **The integration executes, but the complete task test failed native evaluation.**
No generalization, stable-success, token-saving, or acceleration result is claimed.

## Delivered framework

- Fixed English planner instructions: [gpt_jev_planner_v1.txt](../code/prompts/gpt_jev_planner_v1.txt).
- Data grammar, semantic relations, validation and Jev handoff: [gpt_jev_contract.py](../code/scripts/gpt_jev_contract.py).
- Observation grounding and bounded execution: [run_gpt_jev_generic.py](../code/scripts/run_gpt_jev_generic.py).
- Interface documentation: [README](../code/prompts/README.md).

The fixed instructions contain no task names, task IDs, stored manipulation
sequence, demonstration, or successful trajectory. The runtime supplies public
task language, current RGB-D, calibration, own-robot geometry/proprioception and
recent acknowledged actions. GPT selects image anchors, depth-patch processing
parameters, local targets, gripper requirements, stage order and visual reviews.
Generated plans are naturally specific to the current instruction; the framework
does not provide that task's answer in advance.

The interpreter computes depth backprojection, pose errors, semantic axis relations
and bounded action magnitudes. Jev chooses every dispatched XYZ/rotation sign,
gripper command and stage edge. Only pose/command-delivery evidence reaches the
local gate; object-effect checks go to a fresh GPT visual review. Generated data
cannot execute Python or introduce arbitrary sensors, feature names or actions.

This first adapter uses median RGB-D point patches and one LIBERO robot's OSC_POSE.
It has no object-centric collision certification, robust object-pose tracker,
force sensor, or independently implemented completion detector. A valid contract
does not establish correct grounding or task success.

## Routing and frozen inputs

- Server: `company-server-2-ykj`; project worktree:
  `/home/ykj/project/jev-rsi-roboicl/.worktrees/gpt-jev-generic-20261024`.
- Existing interpreter:
  `/home/ykj/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python`.
- Existing simulator source:
  `/home/ykj/yekangjie/project/embodied-jev/.sim/LIBERO-plus`.
- Environment: Python 3.10.12, NumPy 1.26.4, SciPy 1.15.3, MuJoCo 2.3.7,
  robosuite 1.4.0, PyTorch 2.2.2+cpu, OpenCV 4.6.0.66; MuJoCo EGL on GPU0.
- Planner: `gpt-6-astra`, `xhigh`, existing local signed-in ChatGPT transport.
  No OpenAI Platform credential, Decisions credential or caz/z key was used.
- Executor: real `jev-1.13.0`, official TypeSafe `/v1/systemone`, separate
  user-authorized Jev credential. The loopback relay used port 7921 over SSH.
- Selected task: `libero_goal/1335`, init0, seed0, public instruction
  `could you put the cream cheese into the bowl`.
- The task ID and native predicates did not enter either model's runtime request.
- Fixed planner prompt SHA256:
  `782b1e0c70008d669180cded07bab479aa51cb648e4b520d76791d2f8cc6f920`.
- Both post-interface-fix episodes used control source `87516433`. Their initial
  two camera JPEGs and fixed-prompt hashes match. They repeat one initial state;
  they are not independent held-out generalization samples.
- `a49e6355` subsequently fixes cancellation status bookkeeping only. It was not
  substituted into a running episode. No task-specific rule was added.

## Complete attempt ledger

All control counts below exclude ten separately reported settling steps per
constructed environment. The startup failure constructed no environment.

| Attempt | GPT requests | Jev requests | Control steps | Outcome |
|---|---:|---:|---:|---|
| Initial import | 0 | 0 | 0 | Dependency log path PermissionError; no environment |
| First contract interface | 4 | 3 | 0 | Three review decisions; Agent interrupted the loop |
| Fixed interface, four-plan budget | 4 | 61 | 183 | Budget exhausted before release; native false |
| Same interface, default eight-plan budget | 7 | 74 | 222 | GPT complete; native false |

Each constructed environment also executed ten open-gripper settling steps:
30 settling steps plus 405 policy control steps across the three development
episodes. The four-plan cap was an Agent-selected diagnostic limit, not a user
budget. The last run restored the documented default without changing the prompt,
stage grammar, controller or task strategy. No further physical attempts were run.

The interrupted run's original summary incorrectly retains `termination=running`;
its console records KeyboardInterrupt and process exit 130. The supplemental
`agent-interruption.json` explains this without changing the original record.
Three planner responses reached the executor; a fourth completed upstream after
the executor was interrupted. Its known 6,961 tokens remain in the cost ledger.
The native false check after interruption is diagnostic, not a completed rollout.

## Preflight findings and generic fixes

Eight temporary contract checks passed: valid grammar, extra-code rejection,
unknown anchors, nonfinite/boolean numbers, nested non-English text, gated edges,
real-model/option checks, and absence of a task recipe in the fixed prompt.
The temporary script was deleted after testing. Syntax and whitespace checks pass.

The first numeric-only positive-X Jev probe selected `negative`. Explicit semantic
axis relations computed in code produced correct positive/negative/hold choices
on all six tested axes. This establishes only this preflight, not a direction
accuracy estimate. On a later identical observed state, excluding a future GPT
visual-check instruction and clarifying current local evidence changed Jev's edge
from `review` to `continue_phase`. Both paired requests executed zero robot steps.
Three Jev preflight/diagnostic requests are counted separately from the episodes.
The local Pro transport probe used 131 input and 13 output tokens, zero robot steps.

The installed robosuite logger attempted a fixed global temporary path during
import. A process-local handler redirects that exact log to the episode directory;
Numba and plotting caches also stay in the project. Installed packages, environment
permissions, CUDA and drivers were not changed. GitHub TLS fetching failed on the
server; committed Git bundles transferred the same history into the isolated
worktree. All source commits were pushed from the workstation through SSH.

## Final episode and execution audit

| GPT-generated stage | Native control steps |
|---|---:|
| approach_carton | 60 |
| lower_to_sides | 24 |
| pinch_carton | 9 |
| test_lift | 24 |
| hover_over_bowl | 42 |
| lower_above_bowl | 24 |
| release_into_bowl | 18 |
| withdraw_and_inspect | 21 |
| Total | 222 |

The final GPT request claimed completion after withdrawal. Native evaluation
returned false. Wall time was 397.329 seconds including model/transport, setup and
simulation; this is not a controlled latency comparison.

All 74 Jev responses match their actual dispatched choices. All 222 steps have
acknowledgments, with no direction substitution, gripper substitution, unallowed
stage edge, action-limit violation or step-accounting gap. The four-plan run
likewise has 61 matched responses, 183 acknowledged steps and zero such violations.
These audits test execution integrity, not semantic correctness or collision safety.

The final images make the carton appear to be in or over the bowl. The native
failure must not be overwritten by that appearance or by the planner's claim.
After all episodes ended, a read-only inspection found the public task's native
goal is `On(cream_cheese_1, akita_black_bowl_1)`, evaluated through `check_ontop`.
The installed implementation requires the receiving object's reference height to
be no higher than the source reference height, actual object contact, and a world
XY reference-position distance strictly below 0.03 m. These are post-hoc diagnostic
facts, not the runtime success gate, and were never sent to either model.
Final object-state/contact snapshots were
not saved, so the exact failed geometric/contact condition is not established by
the current record. We do not assign it to a guessed placement or orientation
mechanism, and do not change the evaluator to fit the image.

## Full cost accounting

Reasoning tokens below are a subset of output tokens, not an additional charge.

| Scope | Input tokens | Output tokens | Reasoning subset |
|---|---:|---:|---:|
| Four-plan fixed-interface episode | 24,586 | 7,542 | 6,462 |
| Final default-budget episode | 45,290 | 8,367 | 6,803 |
| All 15 completed GPT planning inferences, including the unconsumed one | 89,926 | 22,665 | 18,308 |
| Separate Pro transport probe | 131 | 13 | 0 |
| All 141 real Jev inferences, including three diagnostics | 229,588 | 40,407 | 0 |

The bridge records 15 GPT and 141 Jev upstream attempts, all with known returned
usage; there were no unknown-usage attempts or extra upstream retries. Reported
cached input tokens were zero. A request completed upstream is not evidence its
plan was consumed by the executor; the interrupted fourth plan is counted anyway.

There is no matched-success GPT-only baseline in this experiment. Fewer calls than
control steps does not establish savings relative to another policy. Earlier
diagnostic/budget failures are not dropped from the cost record.

## Reproduction and artifacts

The following is the exact final simulator invocation from the remote worktree.
It requires the existing local Pro/Jev relay and SSH reverse forward on port 7921.
Use line breaks as shown; trailing backslashes continue the shell command. For a
new execution, supply a new output directory because overwriting is rejected.

```bash
cd /home/ykj/project/jev-rsi-roboicl/.worktrees/gpt-jev-generic-20261024
/home/ykj/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python -u -B \
  code/scripts/run_gpt_jev_generic.py \
  --output code/runs/gpt-jev-generic-20261024-1335-init0-default8 \
  --libero-root /home/ykj/yekangjie/project/embodied-jev/.sim/LIBERO-plus \
  --suite libero_goal --task-id 1335 --init-index 0 \
  --max-plans 8 --max-jev 160 --max-native-steps 600 --wall-seconds 2400
```

Local collected records are under `code/runs/2026-10-24-gpt-jev-generic/`:
`episode/`, `episode-interface2/`, `episode-default8/`, `bootstrap/`,
`bridge/`, `total-cost-audit.json`, and the three zero-action Jev diagnostics.
Request logs retain exact text and image data-URL hashes; diagnostic JPEG snapshots
use a different encoding quality from wire images, and are not identical wire
bytes. Full RGB-D arrays and privileged final object state are not archived.
Credentials remain outside version control and are not part of this report.

All experiment processes and their SSH forwards ended. The owned local port-7921
bridge was stopped. GPU memory returned to 4–6 MiB per card. No training was run.

## Evidence boundary and next convergence step

The useful positive result is automatic generation and faithful execution of a
data-only Jev contract without a handwritten task recipe. The negative result is
the mismatch between visual completion and native evaluation. Cross-task stability,
successful completion, token reduction and speed are still unproven.

The existing `libero-generic-vision` and `libero-goal-ten` circle warnings remain
unresolved. After this node, generic vision has CIRCLE-1 (seven rounds/ten unresolved
nodes) and CIRCLE-3; goal-ten has CIRCLE-1 (32 rounds/36 nodes) and CIRCLE-3. The
separate RoboICL bowl-speed topic retains CIRCLE-1 (three rounds/four nodes), outside
this experiment's scope. There is no CIRCLE-2. This task ends with the fixed development record, not more task-specific
patches. If future work is authorized, first add generic observable relative-object
geometry/support/stability checks and an independent completion check, then freeze
the interface and evaluate held-out task families/layouts. Do not pass native
predicates, historical task recipes or these experiment-management notes to the
planner as a shortcut. No research objective, formal assumption, metric or active
Discussion resolution was changed in this task.

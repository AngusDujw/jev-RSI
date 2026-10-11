# RoboDojo RGB Decisions pilot

This is a separate RoboDojo simulation pilot for the user authorized v4090 host. It reuses the already installed RoboDojo simulator and the existing GPT-as-Policy native bounded EEF/RPC adapter as read-only references. New code belongs in `~/ykj/project/jev-RSI/code/robodojo_decisions`; all run output, cache, raw RGB and private API credentials belong under `~/DataStorage/robodojo-decisions` on the data mount. Do not write them to the source checkout or `/tmp`.

## Task order

The [RoboProbe official 2,100-slot GPT-6 Astra result](https://github.com/RoboProbe/RoboProbe/blob/main/results/l3_inspect_eef_official_2100/astra_task_layouts.json) gives `stack_blocks` 43/50, `general_pickup` 42/50, `fold_clothes` 36/50, and `press_by_number` 35/50. Fifth place is tied: `stack_bowls` and `match_and_pick_from_conveyor` are both 31/50. This pilot selects `stack_bowls` first. These are task selection priors, not performance claims for the Decisions model or this controller. The original GPT-6 Astra [paper](https://arxiv.org/html/2609.24170) describes a different model and interface.

OpenAI [Decisions API documentation](https://developers.openai.com/api/docs/guides/decisions) specifies `POST /v1/decisions`, three typed answer kinds, image input, and currently `gpt-6-luna` as its only supported model. Here a local Pro-authenticated GPT-6.1 Sol high session drafts/revises each stage plan. The runtime sends the three fresh RoboDojo RGB views and measured robot state directly to Decisions. Each response selects stage, XYZ signs, bounded step, one optional orientation correction, and gripper commands. Simulator-provided object poses, layouts, contacts, reward and success labels are excluded from model input. The native evaluator is the sole success source.

## Run contract

- Existing Python and assets: `~/DataStorage/jev-router/sources` and the existing environment recorded in `~/DataStorage/jev-router/project/jev-router/ENVIRONMENT.json`. No environment, driver, or CUDA changes.
- Pilot is one foreground process and one native episode. Output names are unique and never overwritten.
- `--preflight-only` initializes and resets the native simulator, obtains three RGB frames, then records an incomplete preflight with zero model calls.
- A normal development pilot defaults to 30 decisions and at most 6,800 seconds. This is incomplete unless native termination and the native success criterion are recorded. Full frozen evaluation should use `--max-decisions 0` with the same under-two-hour wall guard only after pilot evidence supports it.
- API errors/refusals or invalid actions execute no robot step. A simulator mutation is never retried automatically after uncertain acknowledgement.
- Every model call records text, RGB file paths/hashes, typed answers, bounded target, usage and latency without recording the API key. The native result and full simulator logs remain on DataStorage.

## Remote commands

Each command below is one line. Run one at a time from the project checkout on v4090. `KEY_FILE` points to a mode-600 file on DataStorage containing the user supplied credential; do not put it in Git or terminal history.

```bash
python3 code/robodojo_decisions/run_episode.py --task stack_blocks --layout 0 --run-name 2026-10-12-stack-blocks-preflight --preflight-only
```

```bash
"$HOME/zjc/Gpt6Astra_Π0.5/envs/robodojo/bin/python" code/robodojo_decisions/run_episode.py --task stack_blocks --layout 0 --run-name 2026-10-12-stack-blocks-rgb-pilot-01 --key-file "$HOME/DataStorage/robodojo-decisions/secrets/openai.key" --max-decisions 30
```

This controller is an experimental categorical EEF policy, not the original RoboProbe GPT-6 Astra harness. Stability requires frozen code/plan and independent native episodes, including standard/random layouts where the official cell is paired.

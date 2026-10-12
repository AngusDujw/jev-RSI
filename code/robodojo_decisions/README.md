# RoboDojo RGB Decisions pilot

This is a separate RoboDojo simulation pilot for the user authorized v4090 host. It reuses the already installed RoboDojo simulator and the existing GPT-as-Policy native bounded EEF/RPC adapter as read-only references. New code belongs in `~/ykj/project/jev-RSI/code/robodojo_decisions`; all run output, cache, raw RGB and private API credentials belong under `~/DataStorage/robodojo-decisions` on the data mount. Do not write them to the source checkout or `/tmp`.

## Task order

The [RoboProbe official 2,100-slot GPT-6 Astra result](https://github.com/RoboProbe/RoboProbe/blob/main/results/l3_inspect_eef_official_2100/astra_task_layouts.json) gives `stack_blocks` 43/50, `general_pickup` 42/50, `fold_clothes` 36/50, and `press_by_number` 35/50. Fifth place is tied: `stack_bowls` and `match_and_pick_from_conveyor` are both 31/50. This pilot selects `stack_bowls` first. These are task selection priors, not performance claims for the Decisions model or this controller. The original GPT-6 Astra [paper](https://arxiv.org/html/2609.24170) describes a different model and interface.

OpenAI [Decisions API documentation](https://developers.openai.com/api/docs/guides/decisions) specifies `POST /v1/decisions`, typed answers, image input, and currently `gpt-6-luna` as its only supported model. A local Pro-authenticated GPT-6.1 Sol high session drafted the initial stage plan and reviewed the first failed pilot. The runtime sends three fresh RoboDojo RGB views and measured robot state directly to Decisions. Simulator-provided object poses, layouts, contacts, reward and success labels are excluded from model input. The native evaluator is the sole success source.

Version `v1` asks stage and both arms' action in one request. Its 30-decision RGB pilot stayed in `observe_blocks` for every call, so it only tested the input/action link. Version `v2` separates a visual stage gate from a second request for the locked active arm's bounded action. A fourth image supplies the initial high-camera block reference. The controller changes stage only when current visual evidence passes the gate; failure returns to a named recovery stage. The other arm is held. This retains Decisions as the visual reasoner and categorical motion policy.

Version `v2` reached `align` but returned hold on 9 of 13 motions. A Pro visual audit of initial/current high and right wrist RGB showed that the wrist view centered the yellow support, while the locked purple target remained left of the right gripper. Version `v3` keeps all raw camera images and adds a labeled initial high view plus RGB-only color boxes to clarify target identity. It removes the hold option during approach/alignment and supplies the measured high-camera X projection from the previous layout-0 pilot. These are fallible image-derived hints, recorded separately from model answers; the controller still needs native complete success evidence.

Version `v3` then spent 14 actions in alignment without a grasp: high RGB lost the purple target behind the right fingers while the wrist still showed yellow. A second local Pro visual review proposed a small lift and withdrawal before asking the Decisions model to distinguish the target, support, and fingers again. Version `v4` adds that bounded RGB visibility recovery. It requires fresh target and support detections plus the model's visual target/finger assessment before resuming alignment, and records an explicit incomplete status if visibility or alignment stays stalled. The color detections are fallible image hints; raw RGB remains in every model request.

The `v5_probe_y` diagnostic is intentionally an incomplete task episode for `stack_blocks` layout 0. Following local Pro's review of v4, it holds the initial right-hand X/Z position and open gripper while commanding world-Y offsets of +5 mm, -5 mm, and 0 mm in three native actions. Decisions inspects the current three raw RGB views, labeled initial high view, and previous high frame at each stop. Its categorical answers record whether the purple target remains visible and how the right gripper shifted in high-image coordinates. A later controller may use the observed mapping; this diagnostic itself makes no grasp or benchmark success claim.

## Run contract

- Existing Python and assets: `~/DataStorage/jev-router/sources` and the existing environment recorded in `~/DataStorage/jev-router/project/jev-router/ENVIRONMENT.json`. No environment, driver, or CUDA changes.
- Pilot is one foreground process and one native episode. Output names are unique and never overwritten.
- `--preflight-only` initializes and resets the native simulator, obtains three RGB frames, then records an incomplete preflight with zero model calls.
- A normal development pilot defaults to 30 native actions and at most 6,800 seconds. This is incomplete unless native termination and the native success criterion are recorded. Full frozen evaluation should use `--max-decisions 0` with the same under-two-hour wall guard only after pilot evidence supports it.
- API errors/refusals or invalid actions execute no robot step. A simulator mutation is never retried automatically after uncertain acknowledgement.
- Every model call records text, RGB file paths/hashes, typed answers, bounded target, usage and latency without recording the API key. The native result and full simulator logs remain on DataStorage.

## Remote commands

Each command below is one line. Run one at a time from the project checkout on v4090. `KEY_FILE` points to a mode-600 file on DataStorage containing the user supplied credential; do not put it in Git or terminal history.

```bash
"$HOME/zjc/Gpt6Astra_Π0.5/envs/robodojo/bin/python" -B code/robodojo_decisions/run_episode.py --task stack_blocks --layout 0 --run-name 2026-10-12-stack-blocks-preflight --preflight-only
```

```bash
HTTPS_PROXY=http://127.0.0.1:7897 HTTP_PROXY=http://127.0.0.1:7897 "$HOME/zjc/Gpt6Astra_Π0.5/envs/robodojo/bin/python" -B code/robodojo_decisions/run_episode.py --controller v4 --task stack_blocks --layout 0 --run-name 2026-10-12-stack-blocks-visibility-recovery-01 --key-file "$HOME/DataStorage/robodojo-decisions/secrets/openai.key" --max-decisions 40
```

```bash
HTTPS_PROXY=http://127.0.0.1:7897 HTTP_PROXY=http://127.0.0.1:7897 "$HOME/zjc/Gpt6Astra_Π0.5/envs/robodojo/bin/python" -B code/robodojo_decisions/run_episode.py --controller v5_probe_y --task stack_blocks --layout 0 --run-name 2026-10-12-stack-blocks-y-probe-01 --key-file "$HOME/DataStorage/robodojo-decisions/secrets/openai.key" --max-decisions 5 --max-wall-seconds 1200
```

This controller is an experimental categorical EEF policy, not the original RoboProbe GPT-6 Astra harness. Stability requires frozen code/plan and independent native episodes, including standard/random layouts where the official cell is paired.

# RoboDojo RGB Decisions pilot

## Current v4090 campaign (2026-10-13)

- Checkout: `/home/v4090-1/ykj/project/jev-RSI-gpt6-dec`, branch `codex/robodojo-gpt6-dec-v4090-20261012`. Reuse RoboDojo at `/home/v4090-1/DataStorage/jev-router/sources/RoboDojo` and its existing Python environment. All run RGB, native trajectories, plans, reviewed experiences, service logs and the mode-600 `du` Decisions key are under `/home/v4090-1/DataStorage/gpt6-dec`.
- Planner: `pro_plan.py` calls the local ChatGPT Pro bridge with `gpt-6.1-sol`, `reasoning_effort=high`. It loads `experience/global.md` and an optional `experience/<task>.md` as raw Markdown, then receives the current three RGB images, public camera calibration and measured robot state. It writes a stage plan and a short `experience` list under `plans/<run>/plan.json`. A live landmark refresh in `refresh_landmark.py` also reads the latest raw experience files.
- Pusher: `controller.py` calls `gpt-6-luna` Decisions using the separately authorized `du` direct key at `secrets/du-openai-direct.key`. It receives all three fresh RGB images, the Pro plan and distilled experience, current measured robot state, propagated wrist calibration, accepted camera-derived landmark checks, bounded action options and recent execution feedback. Object true poses, contacts and native reward/success are never sent to either model.
- The first three batches of five ranked tasks have each completed at least one Pro+Luna native control pilot on layout 0; **0/15 complete native successes so far**. Zero-action preflight is tracked separately. The broad `v1` stage plus independent XYZ Decisions input repeatedly held in the initial sensing stage, and should not be repeated for further tasks. The `general_pickup` diagnostic instead asks Luna to choose one complete camera-derived bounded action or a specific stop reason; the X5 public hand mesh supplies a conservative height bound relative to the visually triangulated hinge plane. Even a projected 40 px improvement from a small wrist rotation did not cause Luna to approve motion when the full swept corridor was uncertain. These geometric quantities are not collision certificates or grasp points.
- `refresh_landmark.py` now accepts a `landmark_spec` in the plan with `landmark_id`, `target_identity`, `physical_landmark`, and two `required_views`. It asks Pro to mark the *same current physical point* in those two RGB views and runs a positive-ray / ray-gap / reprojection check before any 3D hypothesis is accepted. The first `cover_blocks` test correctly returned uncertain for the left yellow cover because the left wrist did not see its outer rim; a visible red-block corner cannot stand in for the cover. The next sensing step must move the camera to acquire that source object, then rerun this gate before offering Luna complete approach candidates.
- Official task order is recorded in `plans/gpt6-astra-task-priority.json`. The official Astra rate ranks tasks for investigation; this Sol+Luna interface has its own native success record. Weekly experimental evidence and negative results are in `LOGS/2026-W42.md`, with the active issue in `Discussion.md`.

From this checkout, a planner run uses a preflight observation and its same-step public calibration. The `--output` directory must be new. This one-line example shows exactly where the experience is loaded:

```bash
"/home/v4090-1/zjc/Gpt6Astra_Π0.5/envs/robodojo/bin/python" -B code/robodojo_decisions/pro_plan.py --observation /home/v4090-1/DataStorage/gpt6-dec/runs/2026-10-12-gpt6-dec-classify_objects-preflight-01/controller/request_000.json --calibration /home/v4090-1/DataStorage/gpt6-dec/runs/2026-10-12-gpt6-dec-classify_objects-preflight-01/camera_calibration_initial.json --global-experience /home/v4090-1/DataStorage/gpt6-dec/experience/global.md --output /home/v4090-1/DataStorage/gpt6-dec/plans/your-new-run-name
```

The following older examples document the preceding pilot. Their old paths and controller assumptions are historical; use the current paths and run manifests above for v4090.

This is a separate RoboDojo simulation pilot for the user authorized v4090 host. It reuses the already installed RoboDojo simulator and the existing GPT-as-Policy native bounded EEF/RPC adapter as read-only references. The current checkout is `/home/v4090-1/ykj/project/jev-RSI-gpt6-dec`; all run output, cache, raw RGB and private API credentials belong under `/home/v4090-1/DataStorage/gpt6-dec` on the data mount. Do not write them to the source checkout or `/tmp`.

## Task order

The [RoboProbe official 2,100-slot GPT-6 Astra result](https://github.com/RoboProbe/RoboProbe/blob/main/results/l3_inspect_eef_official_2100/astra_task_layouts.json) gives `stack_blocks` 43/50, `general_pickup` 42/50, `fold_clothes` 36/50, and `press_by_number` 35/50. Fifth place is tied: `stack_bowls` and `match_and_pick_from_conveyor` are both 31/50. This pilot selects `stack_bowls` first. These are task selection priors, not performance claims for the Decisions model or this controller. The original GPT-6 Astra [paper](https://arxiv.org/html/2609.24170) describes a different model and interface.

OpenAI [Decisions API documentation](https://developers.openai.com/api/docs/guides/decisions) specifies `POST /v1/decisions`, typed answers, image input, and currently `gpt-6-luna` as its only supported model. A local Pro-authenticated GPT-6.1 Sol high session drafted the initial stage plan and reviewed the first failed pilot. The runtime sends three fresh RoboDojo RGB views and measured robot state directly to Decisions. Simulator-provided object poses, layouts, contacts, reward and success labels are excluded from model input. The native evaluator is the sole success source.

Version `v1` asks stage and both arms' action in one request. Its 30-decision RGB pilot stayed in `observe_blocks` for every call, so it only tested the input/action link. Version `v2` separates a visual stage gate from a second request for the locked active arm's bounded action. A fourth image supplies the initial high-camera block reference. The controller changes stage only when current visual evidence passes the gate; failure returns to a named recovery stage. The other arm is held. This retains Decisions as the visual reasoner and categorical motion policy.

Version `v2` reached `align` but returned hold on 9 of 13 motions. A Pro visual audit of initial/current high and right wrist RGB showed that the wrist view centered the yellow support, while the locked purple target remained left of the right gripper. Version `v3` keeps all raw camera images and adds a labeled initial high view plus RGB-only color boxes to clarify target identity. It removes the hold option during approach/alignment and supplies the measured high-camera X projection from the previous layout-0 pilot. These are fallible image-derived hints, recorded separately from model answers; the controller still needs native complete success evidence.

Version `v3` then spent 14 actions in alignment without a grasp: high RGB lost the purple target behind the right fingers while the wrist still showed yellow. A second local Pro visual review proposed a small lift and withdrawal before asking the Decisions model to distinguish the target, support, and fingers again. Version `v4` adds that bounded RGB visibility recovery. It requires fresh target and support detections plus the model's visual target/finger assessment before resuming alignment, and records an explicit incomplete status if visibility or alignment stays stalled. The color detections are fallible image hints; raw RGB remains in every model request.

The `v5_probe_y` diagnostic is intentionally an incomplete task episode for `stack_blocks` layout 0. Following local Pro's review of v4, it holds the initial right-hand X/Z position and open gripper while commanding world-Y offsets of +5 mm, -5 mm, and 0 mm in three native actions. Decisions inspects the current three raw RGB views, labeled initial high view, and previous high frame at each stop. Its categorical answers record whether the purple target remains visible and how the right gripper shifted in high-image coordinates. A later controller may use the observed mapping; this diagnostic itself makes no grasp or benchmark success claim.

That probe measured high-image right-gripper shifts of roughly 3 px for each 4–5 mm Y motion, with opposite directions for Y+ and Y−, while Decisions answered `none/left/none`. Version `v6` therefore reports a normalized RGB-only palm template match, approximate right-finger interval, purple target center and image-space error as supplemental text beside the raw images. It includes the measured local X/Y projection signs and limits. The model still selects target, stage, world-axis direction, magnitude, and rotation; a grasp-stage pass additionally requires visible target-in-finger geometry and a bounded hand height. These cues are calibrated only for layout 0 and do not use simulator object poses or labels.

In the first SOCKS trial, v6 reached 7 actions/35 native steps before a connection outage. The model chose three X-negative and four X-positive motions; in the high RGB, three X-positive moves enlarged the target-to-finger horizontal error from about 58 to 95 pixels. A local Pro review proposed a visual sign gate. Version `v7` still asks Decisions for stage, safe world-axis direction and step size, but removes X directions that would increase the currently measured horizontal error when it exceeds 5 px. If two permitted X actions fail to shrink that error, the pilot terminates incomplete and flags its image projection for review. This is a task-specific RGB constraint, not a grasp claim.

The v7 native pilot made horizontal progress but lost reliable RGB tracking after a 45 mm Z lift and two Y motions. Version `v8` separates horizontal alignment from Y/Z adjustment. While the target is visible and the fixed right-gripper RGB template scores at least 0.80, the model may choose only a sign-correct X motion or hold until horizontal error is at most 5 px in two fresh observations. When the target is occluded, the controller preserves horizontal progress and tries at most two 5 mm Z+ visibility probes. Y/Z choices are then capped at 5 mm and checked against measured EEF movement and fresh RGB error; low visual confidence or repeated lack of progress ends the pilot incomplete. This fixed-camera gate is calibrated only for `stack_blocks` layout 0.

In the v8 pilot, three X-negative motions reduced horizontal error from 69 to 47 px, then the purple target disappeared behind the right fingers in all views; two 5 mm lifts did not restore visibility. A local Pro RGB review considered occlusion more likely than a pushed block, while acknowledging that the images could not distinguish them. Version `v9` keeps the v8 stage gates but changes only visibility recovery: lift in at most three 10 mm increments, then retreat opposite the last X approach in at most three 10 mm increments. It resumes model-guided alignment only after fresh RGB shows the same target and support again, and otherwise terminates incomplete.

The v9 pilot recovered purple visibility after a 30 mm lift and 10 mm X retreat, then reduced horizontal error to 5–6 px while the target remained only partly visible under the palm. Its strict 5 px boundary led to two hold actions and an incomplete stop. Local Pro review recommends a diagnostic before any grasp: `v10_y_probe` accepts two fresh horizontal observations within 8 px, holds once for the second frame, then moves world Y− by 3 mm. It checks measured EEF displacement, vertical RGB error (at least 1 px improvement), fixed-camera target center (at most 2 px shift), and visible purple mask area (at least 70% retained). Only if all checks pass does it add another Y−2 mm, then ends incomplete for review. The probe never claims a benchmark success.

The v10 pilot ended before its Y probe: horizontal center error stopped at 8.5 px with two model hold choices. Its initial 27 px target width and the RGB finger interval imply about 7.5 px minimum lateral edge clearance. Local Pro review supports `v11_edge_probe` for **one** open-gripper Y−3 mm diagnostic when the conservative target-to-inner-finger margin is at least 3 px for two fresh frames with stable target center (within 2 px) and visible area (within 0.8–1.25 ratio). The same measured EEF and RGB acceptance applies, then the pilot terminates incomplete for inspection. The inferred full width remains uncertain under occlusion, so this condition never authorizes closing the gripper.

The v11 pilot exposed a mismatch: a recovering target with 8.5 px estimated edge clearance but gripper template score 0.7956 moved from `reobserve` to `align`, where the 0.80 action threshold raised an error. Local Pro inspected the images and advised a stationary confirmation frame. `v12_confirm_probe` performs one zero-motion observation when recovery score is 0.79–0.80 and the target is visible with margin at least 3 px. It proceeds to the same single Y−3 mm diagnostic only when the next RGB has score at least 0.80, target center drift at most 2 px, and at least 90% of the prior visible purple area; otherwise it records an explicit incomplete result.

The v12 diagnostic measured right EEF Y−2.987 mm and a 1 px improvement in target-to-finger vertical error, but visible purple area fell from 297 to 256 px while the right wrist still showed only yellow. Local Pro review advised against more purple-under-palm micro motions. Version `v13_yellow_first` constrains the initial Decisions selection to a right-arm yellow-block pickup candidate, because the initial high and right-wrist RGB both show the whole yellow block. Decisions still judges stages and chooses one world-axis action from fresh raw RGB; RGB-only color/hand tracking filters directions with the wrong local image sign and caps each approach translation at 10 mm. The support choice is provisional until a held yellow block is visually verified. This is a distinct task-specific pilot, not a stack success result.

## Run contract

- Existing Python and assets: `~/DataStorage/jev-router/sources` and the existing environment recorded in `~/DataStorage/jev-router/project/jev-router/ENVIRONMENT.json`. No environment, driver, or CUDA changes.
- Pilot is one foreground process and one native episode. Output names are unique and never overwritten.
- `--preflight-only` initializes and resets the native simulator, obtains three RGB frames, then records an incomplete preflight with zero model calls.
- A normal development pilot defaults to 30 native actions and at most 6,800 seconds. This is incomplete unless native termination and the native success criterion are recorded. Full frozen evaluation should use `--max-decisions 0` with the same under-two-hour wall guard only after pilot evidence supports it.
- API errors/refusals or invalid actions execute no robot step. Transient network failures on read-only Decisions queries may retry up to ten times with bounded exponential backoff and recorded attempts. A simulator mutation is never retried automatically after uncertain acknowledgement.
- For intermittent HTTP proxy protocol errors, `ROBODOJO_DECISION_TRANSPORT=curl_socks` sends Decisions requests through the same local reverse tunnel using SOCKS. The API key is passed to curl through an anonymous in-memory file descriptor; it is never placed in command arguments or a new disk file. Validate a four-image read-only request before running a simulator episode.
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

```bash
ROBODOJO_DECISION_TRANSPORT=curl_socks "$HOME/zjc/Gpt6Astra_Π0.5/envs/robodojo/bin/python" -B code/robodojo_decisions/run_episode.py --controller v6 --task stack_blocks --layout 0 --run-name 2026-10-12-stack-blocks-rgb-geometry-socks-01 --key-file "$HOME/DataStorage/robodojo-decisions/secrets/openai.key" --max-decisions 60 --max-wall-seconds 2400
```

```bash
ROBODOJO_DECISION_TRANSPORT=curl_socks "$HOME/zjc/Gpt6Astra_Π0.5/envs/robodojo/bin/python" -B code/robodojo_decisions/run_episode.py --controller v7 --task stack_blocks --layout 0 --run-name 2026-10-12-stack-blocks-rgb-sign-gate-01 --key-file "$HOME/DataStorage/robodojo-decisions/secrets/openai.key" --max-decisions 60 --max-wall-seconds 2400
```

```bash
ROBODOJO_DECISION_TRANSPORT=curl_socks "$HOME/zjc/Gpt6Astra_Π0.5/envs/robodojo/bin/python" -B code/robodojo_decisions/run_episode.py --controller v8 --task stack_blocks --layout 0 --run-name 2026-10-12-stack-blocks-staged-micro-01 --key-file "$HOME/DataStorage/robodojo-decisions/secrets/openai.key" --max-decisions 60 --max-wall-seconds 2400
```

```bash
ROBODOJO_DECISION_TRANSPORT=curl_socks "$HOME/zjc/Gpt6Astra_Π0.5/envs/robodojo/bin/python" -B code/robodojo_decisions/run_episode.py --controller v9 --task stack_blocks --layout 0 --run-name 2026-10-12-stack-blocks-recovery-sweep-01 --key-file "$HOME/DataStorage/robodojo-decisions/secrets/openai.key" --max-decisions 60 --max-wall-seconds 2400
```

```bash
ROBODOJO_DECISION_TRANSPORT=curl_socks "$HOME/zjc/Gpt6Astra_Π0.5/envs/robodojo/bin/python" -B code/robodojo_decisions/run_episode.py --controller v10_y_probe --task stack_blocks --layout 0 --run-name 2026-10-12-stack-blocks-y-micro-probe-01 --key-file "$HOME/DataStorage/robodojo-decisions/secrets/openai.key" --max-decisions 60 --max-wall-seconds 2400
```

```bash
ROBODOJO_DECISION_TRANSPORT=curl_socks "$HOME/zjc/Gpt6Astra_Π0.5/envs/robodojo/bin/python" -B code/robodojo_decisions/run_episode.py --controller v11_edge_probe --task stack_blocks --layout 0 --run-name 2026-10-12-stack-blocks-y-edge-probe-01 --key-file "$HOME/DataStorage/robodojo-decisions/secrets/openai.key" --max-decisions 60 --max-wall-seconds 2400
```

```bash
ROBODOJO_DECISION_TRANSPORT=curl_socks "$HOME/zjc/Gpt6Astra_Π0.5/envs/robodojo/bin/python" -B code/robodojo_decisions/run_episode.py --controller v12_confirm_probe --task stack_blocks --layout 0 --run-name 2026-10-12-stack-blocks-visibility-confirm-01 --key-file "$HOME/DataStorage/robodojo-decisions/secrets/openai.key" --max-decisions 60 --max-wall-seconds 2400
```

```bash
ROBODOJO_DECISION_TRANSPORT=curl_socks "$HOME/zjc/Gpt6Astra_Π0.5/envs/robodojo/bin/python" -B code/robodojo_decisions/run_episode.py --controller v13_yellow_first --task stack_blocks --layout 0 --run-name 2026-10-12-stack-blocks-yellow-first-01 --key-file "$HOME/DataStorage/robodojo-decisions/secrets/openai.key" --max-decisions 40 --max-wall-seconds 2400
```

This controller is an experimental categorical EEF policy, not the original RoboProbe GPT-6 Astra harness. Stability requires frozen code/plan and independent native episodes, including standard/random layouts where the official cell is paired.

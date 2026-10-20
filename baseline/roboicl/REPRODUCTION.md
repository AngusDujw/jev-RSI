# RoboICL reproduction and Jev action-reuse ablation

## Provenance

- Official repository: https://github.com/Mosi-AI/RoboICL
- Upstream commit: `07d6e1c5387710e2de9240724b0015bbf0c95c6e` (verified 2026-10-21).
- Paper: https://arxiv.org/html/2609.34261v1, section 4.5 and appendix C.2.
- The original source and MIT license are retained. The paper's Jev gate is not present in this release. Any gate added here is a documented reconstruction, not recovered author code.
- Four dependencies remain at `configs/upstream.lock.json` revisions. `setup/fetch_upstreams.py` installs clean detached repositories because this directory is vendored within a parent repository rather than installed as a top-level submodule checkout.

## User-authorized comparison

Use the previously selected official GPT top-five RoboDojo tasks: general_pickup, fold_clothes, press_by_number, match_and_pick_from_conveyor, stack_bowls. The historical official scores were 84, 72, 70, 62, 62; this selection excludes the previously studied stack_blocks task. These are progress/success labels from the original benchmark report, not new measurements.

Use official standard layouts 0–3 under layout-directory seed 0: four paired episodes per task per condition. Preserve the released simulator's initial seed 0 and reset seed equal to the selected layout ID; record these separately. Keep failures and service failures explicitly recorded. No scene alteration, task-specific rescue controller, demonstrations, or task-ground-truth input is added. Native evaluator outputs are scoring-only.

Conditions are pure GPT (replan every 5 actions), GPT plus Jev reuse, fixed mean reuse interval, and fixed maximum reuse interval. GPT predicts 20 actions in every condition. The paper gate may approve one extra 5-action segment, so a single GPT proposal executes at most 10 actions. Preserve the released tracking and IK guards in all conditions.

First complete pure and Jev conditions (40 episodes). Then derive each task's mean and maximum actually executed actions per GPT proposal from all four Jev episodes, including terminal and interrupted chunks. Round the mean to the nearest integer with half-up rounding and a minimum of one; cap both intervals at 20, the prediction horizon. Freeze these values before the remaining 40 episodes. Report uncensored and full nonterminal interval distributions to expose truncation effects. The working interpretation of "mean/max steps" is the number of robot actions between GPT requests, as stated to the user; a later user clarification takes precedence before the fixed-interval phase.

An interval is the robot-step difference from one completed GPT request to the next, with the last interval ending at episode termination. Zero-step correction requests therefore remain in the interval denominator; local safety-hold steps also remain in the physical-step count. Accepted tool-result intervals are reported separately. No extra calls or failed trials are silently removed.

The mean/max schedules are fitted on the same four Jev layouts and are development-set ablations. Report per-episode total robot steps as well as per-GPT intervals. Infrastructure interruptions remain explicit; their partial steps are not silently averaged into a complete-episode performance claim.

Use the local signed-in ChatGPT Pro account for GPT transport, never an OpenAI Platform API key. Target the paper's GPT-6 Astra/xhigh when the local Pro account supports it; record an incompatibility rather than silently changing model. Jev uses a separately authorized Jev provider and never substitutes for GPT.

Run on company-server-2-ykj under `/home/ykj/project/jev-rsi-roboicl`. Use at most four idle GPUs; measure one simulator's peak usage before choosing workers per GPU. Keep RGB in memory for policy input and do not persist frames, videos, image-bearing request payloads, or HDF5 trajectories. Save lightweight textual action/receipt/request audits with image content replaced by hashes, outcome, steps, calls, latency, usage and provenance.

Asset transport uses revision-pinned resolve URLs with SHA256 verification because the server's direct Hugging Face route and mirror LFS batch URLs failed. Existing readable assets may seed identical objects by content, with independent copies. The installation retains the complete non-layout asset tree and only the twenty selected layout JSON files; no physical USD/material/object dependency is pruned. `setup/install_selected_assets.py` uses the released launcher's existing `explicit-files` manifest scope and verifies every selected source file before materializing the original robot templates. Unrelated evaluation layouts are excluded to avoid thousands of unnecessary transfers.

The simulator adapter restores the process-owned RoboDojo `utils` namespace after Kit startup; a concrete SDK package otherwise shadows the two upstream namespace directories. It also calls RoboDojo's existing `add_zero_delay_kit_args` helper before startup, matching the native entrypoint's camera synchronization contract. Both changes apply identically to all conditions. Kit's writable portable roots stay in the project, and `ROBOICL_KIT_EXTENSION_PATH` can reuse the first resolved official extension cache without changing the shared simulator installation.

## Reproduction limits

The paper reports Jev results only for Align Blocks and General Pickup on development layouts 0–4. Applying the gate to the other selected tasks and using layouts 0–3 is a user-requested extension. The original gate prompt, threshold and full implementation are not published. A local Pro transport also differs from the release's API provider; any differences in model identity, prompt transport or usage counters must remain explicit. No success or speedup is claimed before actual execution.

The native ChatGPT Pro backend accepted an actual `gpt-6-astra` / `xhigh` function-call probe. A complete released-harness payload was rejected with HTTP 400 because `prompt_cache_options` is not supported on this model. The bridge therefore removes only provider cache hints (`prompt_cache_options` and nested `prompt_cache_breakpoint`), without flattening or deleting model-visible messages, images or tool definitions. Cache-efficiency equivalence to the paper is not asserted.

The released GPT prompt explicitly promises execution of at most `execute_horizon` actions. In the Jev condition only, its execution upper bound is changed from five to ten, while the first dispatch remains five and the prediction remains twenty. Pure GPT and fixed schedules retain their configured execution bound. The actual tool receipt covers all actions truly executed, including an approved suffix. This necessary scheduling-contract difference is an additional reconstruction choice; results compare complete policy conditions and cannot isolate Jev reasoning independently of the execution-bound wording.

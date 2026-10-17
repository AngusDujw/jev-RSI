# Planner–advancer RoboDojo campaign

New implementation for chat `01a12b86`, based on the contracts agreed on 2026-10-17/18. Retired task controllers and experience files are not used.

## Deployment

- Host: `company-server-2` (SSH configured alias).
- Native simulator: `/root/yekangjie/project/robodojo-jev/robodojo`.
- Native robot/recording adapter: the existing sibling `GPT-as-Policy/hybrid_rollout/robodojo/robodojo_server`; only native environment, public FK, stepping and independent evaluation are reused.
- Isolated checkout: `/root/yekangjie/project/jev_rsi/.worktrees/robodojo-planner-advancer-20261018`.
- Assets and logs: its `code/runs/company2-20261018` directory, on the same filesystem.
- Interpreter: `/root/miniconda3/envs/isaacsim5.1/bin/python`; missing pure dependencies are installed only in the checkout's `.deps`, listed in `requirements-overlay.txt`.
- Credentials: checkout `.private`, never versioned. Planner uses the user-authorized ai2robcowork key, decision uses the direct key labeled `du`, future Jev comparisons use the separately supplied Jev key. The `caz`/z key is not used.
- The remote's existing loopback HTTP proxy at port 7897 was verified for direct OpenAI requests; this campaign did not replace its listener. Do not kill or alter unrelated forwards.

## Baseline

One Sol 6.1 high plan per episode; Luna high advances from fresh three RGB images and current robot state. No previous-step records, object geometry, additional perception results, experience injection or in-episode replanning. Plans contain stages and advancer-facing input definitions, not processing/test manifests. Later processing must be designed and tested by the planner before final plan delivery.

Direction channels are fixed; per-channel increments are 20 mm and 0.10 rad. Translation may combine with at most one rotation. Advance dispatches no action. TCP is derived from public robot geometry. The IK solver uses robot-only multistart optimization and logs all five predicted waypoints; native tracking is separately recorded. It does not certify scene clearance. Native success is never a model input.

`campaign.json` freezes the official Astra top-ten task ranking and the development stability gate: at least 9/10 independent runs across five layouts with two repeats each after freezing prompts and implementation. This is not equivalent to the official full panel. All failures must be retained in the intended-run denominator; infrastructure failures are labeled separately, never reclassified as successes.

## Entry points

Run from the isolated remote checkout:

```bash
python3 code/planner_advancer/batch.py status
```

A fresh four-slot batch uses GPUs 2/5/6/7, stack_blocks and classify_objects, layouts 0/1. Batch names must be new. Resume only fills slots never started; it never replays a registered episode.

```bash
python3 code/planner_advancer/batch.py launch --name UNIQUE_BATCH_NAME
```

GPU sharing is opt-in and only permits existing registered campaign workers with at least 8 GiB free; foreign GPU processes are never stopped. At most three campaign occupants are admitted per GPU. Do not assume GPUs remain idle after the initial inspection.

```bash
python3 code/planner_advancer/batch.py launch --name UNIQUE_BATCH_NAME --layout-offset 2 --share-own-gpu
```

Check layout availability before using an offset: the installed official-group-0 stack_blocks cache contains only two layouts. A failed reset is not a policy result. Additional official layouts must be acquired separately, preserving installed assets and never exposing scene-layout contents to models.

`storage_guard.py` polls every 45 seconds. Below 20 GiB free it removes image/video/NPZ image content only from completed registered runs outside the batch's representative task, preserves non-image NPZ state in JSON, and appends deletion provenance. No unrelated files, code, prompts, plans or outcomes are removed. Batch manifests currently retain stack_blocks images.

## Progress and provenance

- EXP272–273: model interface probes passed; native startup dependencies/extensions required project-local fixes. Disabled optional cuRobo construction fails closed; the native task scorer is unchanged.
- EXP274: four valid plans; first stack directions revealed a singular-start single-initialization IK failure. Public URDF diagnostics found the same targets reachable after changing solver initialization. The temporary diagnostic script was deleted; `ik-audit.json` is retained.
- `raw-v1-batch03`: first real policy controls. Initial 5-step tracking was 0.662 mm / 0.001045 rad. Fixed cameras and moving wrist images changed as expected. No full task success had been established when writing this note.
- `raw-v1-batch04`: two extra classification layouts run; extra stack layouts 2/3 were missing and reset failed. Do not claim eight valid policy episodes.
- Luna output budgets of 1200 and later 4096 reasoning tokens caused truncation in some cases. Subsequent calls use 16384; Sol stays high, with 32768 maximum output tokens. Truncated responses are preserved and never executed.
- First-plan/motion progress does not prove grasping or task completion. Original RGB, all requests/responses, robot states, native actions, and independent outcomes are saved for later analysis. No experience files are distilled now.
- Later text-rich processing versions must test both Luna and a paired Jev no-image condition; Jev does not replace Luna. Jev API contract: https://docs.typesafe.ai/api .

Source ranking: https://github.com/RoboProbe/RoboProbe/blob/main/results/l3_inspect_eef_official_2100/astra_task_layouts.json .

Do not restore or modify the dirty primary remote checkout, its existing worktrees, system Python/Conda permissions, CUDA, drivers, or unrelated GPU jobs.

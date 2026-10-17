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

## Planner-authored processing variant

`--processing` enables tool-assisted initial planning. Sol designs, writes and tests an executable processor before returning the stage JSON. Code and verification stay outside that JSON. The processor receives fresh three RGB images, camera calibration and measured robot state, then supplies declared extra fields to the advancer. Its sandbox does not mount native scene layouts, secrets or simulator object state. Preparation allows 64 tool rounds; invalid stage interfaces are returned to the planner for correction.

`--prepared-from` reuses a delivered plan and processor only for the same task/layout/SHA, enabling a paired `--backend jev --omit-images` condition alongside Luna. Jev requests contain text only. The first actual Jev trial resolved to jev-1.13.0 and executed 20 native steps; a later multi-rotation response was rejected without execution. `--resume-processing-from` uses reference code in a new initial-planning trial; it does not resume a terminated simulation or enable in-episode replanning.

EXP275: raw stack layout0 completed 550 native steps without success. RGB supports lifting the purple block; placement alignment did not finish. The first processing preparations failed from tool budget exhaustion and an invalid initial-stage identifier. Neither is evidence that the generated perception method improves control. All failures and raw artifacts remain available; no experience files are used.

### EXP276 corrections and paired results

A classification preparation returned an explicitly non-executable diagnostic stage. Initial interface checks wrongly accepted it, causing repeated no-progress decisions. The outer agent stopped that owned worker after 122 requests and saved `oversight_stop.json`. Explicit blocker reports now end preparation; diagnostic plans are rejected before advancer calls.

The first stack processing plan has 18 stages and estimated positions, tolerances and TCP comparisons. Initial silhouette fit agreement does not establish ground-truth pose accuracy. Luna remains in its parking stage; Jev initially moved toward the parking target but subsequent rotation decisions failed. No full success is established. V4 asks the planner to explain per-channel error signs and tolerances and test their mathematical interpretation. The fixed questions and action interface remain unchanged.

New V3 trials export native `CameraManager.get_camera_intrinsics` and retain SDK intrinsics as diagnostics. The SDK vertical focal scale differed from the native manager and planner image fits. This source disagreement is not a certified recalibration; image consistency still needs validation. The existing V2 Luna/Jev pair uses the same SDK protocol through `ROBO_CAMERA_INTRINSICS=sdk`; avoid mixing camera protocols within a comparison.

### EXP277: direction interpretation versus execution

An early parking-stage audit found V4 Luna active rotation choices consistent with the supplied signs/tolerances in 66/66 cases, compared with 66/106 under V2. V4 Jev later ended at 185 native steps after a multi-rotation response; its final active-rotation consistency was 34/35. These are field-consistency checks on different trajectories, not task success or a causal estimate.

Several correct-direction V4 controls still had approximately 30 mm / 0.18 rad tracking errors. Joint5 stayed near 1.57 rad despite larger targets; public USD limits are approximately +/-10 rad, so the physical cause is unresolved. Seven measured wrist-camera/robot-FK checks agreed within 0.000292 mm / 0.000001654 rad. Do not treat these execution failures as wrong model directions or change the native robot asset to hide them.

New controls record target/measured joints, joint error, maximum planned joint waypoint increment, and a robot-only FK check. New launches preserve exact source copies and hashes in `framework_source/manifest.json`; credentials and experience files are excluded. V5 tests task-related stages without arbitrary parking or unnecessary orientation constraints. Fixed action questions, increments and single-plan semantics remain unchanged.

V6 adds opt-in `ROBO_TOOL_GEOMETRY_DETAILS=1` / `--tool-geometry-details` to both planner and advancer robot states. Public X5 finger meshes and prismatic joint geometry identify tool-local +X as finger extension and tool-local Y as jaw sliding. The fields report those axes in world coordinates and their alignment with world down. Previous plans incorrectly called the initial pose straight-down while preserving tool-Z vertical. This factual robot-frame clarification changes no action-axis definition or TCP position. Older paired conditions keep the option disabled; V6 pairs must enable it on both sides. `public-tool-axes-audit.json` preserves the public geometry evidence.

### EXP278: task-relative visual references and transport recovery

The user selected the separate conversation `sess_e68196f447054026` as a multimodal reference. Its relation/band/hybrid implementations motivate explicit named features, reference regions, annotated acceptance bands, and coarse visual versus numerical fine evidence. Optional examples are supplied in `planner_processing_references.md`. They do not replace the fixed eight action questions or introduce the earlier fixed image-direction mapping. The rotation example covers world yaw/Z, pitch/X and roll/Y, current calibration, and wrist-camera propagation. It is a reference calculation, not an implemented task pipeline or an action selector.

V7 enables `ROBO_EXECUTION_BUDGET_DETAILS=1`: the planner receives the native control limit and five-step action cost; the advancer receives remaining execution budget. Horizons and step sizes are unchanged. New prepared-plan pairs inherit `input_contract.json` from their source; older sources infer the same contract from saved observation metadata. Image omission remains the intended comparison variable.

Four Luna runs ended with empty TLS transport errors. New clients retry only empty network failures, at most four identical requests with 1/3/7 second backoff; valid, partial, and HTTP-error responses are not resampled. Every attempt is recorded. A real du probe succeeded after the incident; it is connectivity evidence, not task performance. Existing terminated episodes are preserved and not resumed or relabeled.

V5/V6 stack3 plans now have 27/26 task-related stages. At the recorded audit, Luna reached gray_close after 125 native steps and gray_descend after 110; maximum recorded TCP position errors were 0.909/0.914 mm. Stage labels do not prove grasping. Their paired Jev runs ended after 15/10 steps because responses selected multiple rotation axes; no action repair or resampling was performed. V7 classification remained blocked before control. V8 classification layout1 uses a fresh implementation and clarifies that implementation verification does not require initial images to satisfy every later contact condition. `v5-v6-task-manipulation-progress-audit.json` preserves the outer-only audit. No complete native success is established for this new framework.

EXP279: V6's nominal grasp interval was approximately 17.0–17.7 mm wide, while actual fixed-step TCP heights alternated around 0.78575/0.80519 m outside it. V5's closed-hand wrist RGB still showed gray between the fingers while its metric fit became unavailable. These are completion-region and evidence-availability failures, not automatically incorrect action signs. V9 independently prepares stack layouts 0 and 3 with variable guidance to test quantized reachability and missing-fit behavior, and to distinguish actuation, candidate containment, and observed lifting. It does not change the fixed action interface, certify grasp from aperture, reuse history, or replan during an episode. See `v5-v6-quantization-and-occlusion-audit.json` for outer-only evidence.

EXP280: V6 stack3 RGB comparisons support gray lifting clear of the table and moving with the fingers; at observation075 its image-derived bottom elevation was approximately 97.8 mm. It later entered gray_lower; this is manipulation evidence, not full tower success. `v6-gray-visible-lift-audit.json` records the permitted observation evidence separately from model inputs. V8 classification layout1 delivered 29 stages after 29 tool rounds; V6 stack layout1 delivered 17 after 38. Luna controls both. Their new same-plan Jev no-image pairs ended after 0/30 native steps because of multiple rotation channels, respectively. Source protocols were inherited automatically and responses were not repaired or resampled. Eighteen completed standalone test scripts were removed from the two sources and their paired copies; raw tool records and runtime processors remain intact.

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

V8 Luna subsequently also ended at 35 steps with simultaneous yaw/pitch output. This is not exclusively a Jev issue. V10 independently prepares classification layout1 using V8 processing code as reference and adds variable guidance to compare hold and six allowed single-axis rotation effects on common geometric objectives. The processor supplies comparisons, not selected actions. The fixed eight questions, output fields, increments and single-plan semantics remain unchanged; no invalid answer is repaired or resampled.

EXP281: V5 and V6 stack3 both ended at the native 550-step horizon with success=false and score0, in gray_close/gray_lower. V9 stack3 reported blocked after 31 tool rounds. V9 stack0 delivered 16 stages but its bounded pair fitter crashed after 10 steps because a coarse initializer was outside its bounds. The separate `prepared-v9-stack0-initializer-fix01` source retains the exact plan and changes only the initializer clipping, following the fitter's existing branches; objectives, bounds and acceptance gates are unchanged. The versioned patch is `processor_repairs/v9_stack0_initializer.patch`. Sandbox regression reproduced the original crash and passed the repaired initial/5/10-step inputs. A new Luna episode passed 35 steps; the paired Jev response again violated the single-rotation rule at step0. Original failures are preserved.

V11 stack3 initial preparation distinguishes executable-estimator verification from a guarantee of future task success, retaining actual tests, honest uncertainty and current-image evidence. V10 classification delivered 22 stages after 38 tool rounds and supplies common geometric effects for hold and six single-axis rotations. Luna controls it, with a new same-plan Jev no-image pair. No full native task success is established. Completed standalone preparation tests were removed with provenance; runtime processors and original tool evidence remain intact.

EXP282: V11 remained blocked after nine tool rounds because its inherited estimator lacked an occlusion-tolerant placement measurement. V6 stack1 ended incomplete at 450 native steps: the lift-stage target was unavailable and the final requested robot-only path failed its existing IK check. The thresholds were not relaxed.

V12 tests `ROBO_PROCESSING_GUIDANCE=compact` / `--processing-guidance compact`. It replaces only the variable processing-delivery guidance (421 words versus 1105), preserving the fixed planner role, action definitions, eight questions, schema, increments, tool interface and validation code. `detailed` remains the default. The compact guide is `code/contracts/planner_processing_compact.md`; it still requires implemented, tested, fresh-observation processing and explicit uncertainty/missing-data handling. Four independent preparations start from empty implementations for stack layouts0/3 and classification layouts0/1. Two actual English initial requests have been checked for the exact compact guide and absence of inherited code. This compares guidance plus fresh initialization with earlier variants; it is not a controlled single-variable causal estimate or a task-success claim.

## V13 optional current-RGB tools and transport (EXP283)

V12 preparations have ended: stack3/class1 were blocked, class0 returned a genuine server_error (correct model), and stack0 delivered a plan but its first Luna request failed with empty TLS35. The older repaired stack0 and V10 classification ended at445/330 native steps with the same transport failure, without native terminal success. Do not resume these episodes.

Opt-in ROBO_PERCEPTION_TOOLS=1 mounts CPU Kornia LoFTR indoor_new and SAM ViT-B packages, weights and one helper read-only at /perception. The optional tool instructions are in code/contracts/optional_perception_tools.md. The planner chooses and verifies processing; no task controller, saved observation or identity is supplied. Paired conditions inherit the four-field input_contract; older three-field contracts default this option to false. Project-local package overlays do not modify the native environment.

The isolated integration test produced75 LoFTR candidates and3 prompted/32 automatic SAM regions. Only9 LoFTR correspondences passed the tested positive-depth and1.5px reprojection check, mainly background. These are interface tests, not improved object localization or task success. The standalone test script was deleted; perception-verification retains outputs and source hashes.

ROBO_MODEL_PROXY_SOCKET optionally routes the unchanged HTTPS POST over an owned Unix HTTP proxy forwarded to the working local proxy. It validates the owned socket directory, TLS certificates and endpoint allowlist, preserves partial responses, and retries only empty transport failures under the existing bounded policy. Default curl is unchanged. No existing TCP listener is replaced. The proxy anchor and SSH master lifecycle are recorded in private-api-proxy-20261018. Actual authorized Sol6.1 high and Luna high readiness probes passed. No credentials enter logs or the sandbox.

V13 independent empty preparations are processing-v13-tools-stack3-r01 (GPU6, PID690063), processing-v13-tools-stack0-r01 (GPU2, PID695472), processing-v13-tools-class1-r01 (GPU7, PID691951), and processing-v13-tools-class0-r01 (GPU7, PID696020). All enable compact guidance and optional tools. Do not duplicate them. Native results are pending. V12 completed test scripts were removed after runtime-reference checks; v12-completed-test-cleanup.json retains source/hash evidence. Transport policy checks confirm no repeat for partial/valid/HTTP-error responses.

## V14 stage-specific processing evidence (EXP284)

V13 classification layout1 ended blocked after14 tool rounds and0 native steps. Its implementation passed17/18 checks, but four of six objects had no accepted features and two had only one distinct feature each. Do not resume it or call it a policy failure.

Optional ROBO_PROCESSING_GUIDANCE=progressive adds generic stage-specific evidence guidance to compact (676 versus421 words): distinguish coarse approach inputs from later manipulation evidence, start from an adequately observed source when order is free, and verify image-supported assumptions and missing-data behavior. The planner still chooses and implements methods; no task-specific controller, prior episode, experience or relaxed validation is supplied. Fixed roles, eight questions, action increments, schema, tool budget and default detailed/compact behavior remain unchanged. Exact prompt-assembly and English checks passed without real model calls. A new independent class1 preparation tests this guide; the other V13 preparations continue.

V13 stack3 also ended blocked after18 rounds and0 native steps: one-pixel boundary perturbations produced13.09mm vertical and14.06mm bottom-height spans; appearance candidates included robot parts. Low reprojection residuals did not certify object accuracy. V14 empty preparations use progressive guidance: classification1/GPU7 PID794815 and stack3/GPU6 PID801511. Both actual contexts passed English/exact-guide/no-inherited-code checks. V13 stack0/classification0 continue. Completed standalone checks.py files were removed with source/hash provenance after dependency checks; runtime helpers remain. Jev passed a separate transport-only probe through the owned Unix route, not a robot decision or success result.

V13 stack0 delivered13 stages after26 rounds and classification0 delivered15 after21. Luna entered prepare_white/pick_toy_1. At the snapshot they reached40/15 native steps, with maximum five-step endpoint TCP errors0.8814/0.7078mm; this does not establish all-step tracking, grasping or task success. Same-method no-image Jev pairs: processing-v13-stack0-jev-pair01 (GPU2, PID884379), processing-v13-class0-jev-pair01 (GPU7, PID885225). Four-field input contracts match; verify copied plan/processor/layout after reset. Luna remains active. Classification point IDs lack full semantic labels, so image omission also removes identity information; preserve this comparison limitation. Two completed independent delivered-source tests were removed after dependency checks; v13-delivered-completed-test-cleanup.json retains source/hash evidence. Runtime helpers remain.

EXP285: Classification Jev pair01 ended at20 steps (earlier15 was in flight) because a robot-only projection selfcheck subtracted a missing pixel. The separate prepared-v13-class0-projection-fix01 changes only that diagnostic to null when unavailable. The original failure is reproduced; repaired failure/initial/current Luna inputs pass, and initial additional JSON is identical. The plan, geometry algorithms, targets, thresholds and native evaluator are unchanged. processor_repairs/v13_class0_projection_null.patch records the change. Do not modify the original active Luna or resume the failed Jev.

batch.py --task selects an official campaign task independently of a GPU slot, requires explicit --gpus and forbids adoption. Default mapping and GPU admission are unchanged. This permits independent paired repair checks on available authorized cards; development remains stack/classification before expanding to other tasks.

Stack0 Luna's prepare_white now shows a two-height cycle coupled to table-constrained/free-estimator target changes. Targets around0.8958/0.8893m produce opposite errors around13mm outside the11mm completion band, with endpoint tracking around0.56mm. Do not attribute this solely to model signs. Classification Luna had an8.98mm endpoint error at step25, so earlier submillimetre snapshots do not describe the full trajectory. These original controls remain separate from the diagnostic repair.

EXP285 terminal correction: original classification Jev ended at20 native steps (the earlier15 was in flight); original Luna ended at60, both with the same projection diagnostic exception and incomplete native outcomes. The repaired processor also passes Luna's actual failed decision012. New repair controls are processing-v13-class0-projection-fix-luna01 (GPU6, PID1014381) and processing-v13-class0-projection-fix-jev01 (GPU7, PID1024265). Plan/processor hashes, case and four-field contracts match the repair source in both copies.

Outer-only RGB audit at original stack0 Luna step200 supports white lifting/carrying between the right fingers, with yellow/purple still on the table; no full stack or precise height is established. The stack0 Jev pair completed550 steps with native_success=false and score0. All110 responses passed fixed single-rotation validation, but no stage advance occurred; Z was positive55/negative55 and pitch negative21/positive20. Final target information was missing. This separates output validity from useful control and does not isolate modality from missing identity evidence or estimator effects. v13-native-evidence-audit.json and oversight-v13-stack0-carry01 retain the raw evidence; neither is a model input or experience file. V14 preparations and active controls continue; no new-framework full success yet.

## Frozen-input comparisons and gateway quota (EXP286)

V14 classification1 delivered25 stages after29 tool rounds. Luna continues and the same-case/SHA Jev no-image pair is processing-v14-class1-jev-pair01, GPU7 PID1241908. V14 stack3 ended after24 tool rounds and0 native steps because the authorized planner gateway returned its7-day10% utilization quota. Do not retry it as a transient network failure or switch keys. New Sol planning awaits restored quota or an explicitly authorized equivalent endpoint; existing controls continue.

Original V13 stack0 Luna carried white, but later fresh RGB shows it beside yellow on the table after release. The235-step image is partly occluded and does not independently establish stable placement;240/245/295 show the subsequent miss. The placement estimate had46/52/77mm XYZ uncertainty half-widths. Neither stage advancement nor this uncertain estimate establishes native success. Outer-only oversight-v13-stack0-after-white01 retains images without feeding history back to either model.

Optional --omit-additional-images (ROBO_OMIT_ADDITIONAL_IMAGES=1) keeps the original three RGB images and additional text while omitting generated images. It requires processing and Luna RGB, and cannot combine with --omit-images or Jev. The default remains unchanged. Independent stack0 Luna text-only and raw-RGB-plus-text comparisons use the frozen V13 plan/processor/case, alongside original RGB-plus-generated-image Luna and Jev text. These conditions can diverge in state; compare episode outcomes without claiming matched-state single-step causality. Fixed role, eight questions, action semantics, increments, validation and scoring remain unchanged.

Unix proxy now retains known HTTP error classification if body reading later fails, preserving partial content and preventing empty HTTP429/500 from entering network-only retries. Five mocked status/body cases and three modality assembly conditions passed without API calls. Completed classification repair Jev reached1005 steps before the existing robot-only five-step IK path gate rejected an action; it is incomplete, not a native failure terminal. No full task success is established.

EXP286 input audit: processing-v13-stack0-luna-text-pair01 (PID1360176) and processing-v13-stack0-luna-raw-rgb-pair01 (PID1362884), both GPU2, started independently from the exact V13 stack0 plan, processor, evaluation case and four-field contract. First actual requests are English and contain zero/exactly three original image keys. The snapshot is15/35 native steps in prepare_white, not a success claim. exp286-frozen-input-pair-audit.json records hashes and keys. Original Luna reached445 steps in carry_purple; classification1 Luna/Jev reached180/575 in white_pen_approach and repaired classification0 Luna170 in pick_toy_1. All are running snapshots. Four completed V14 source/pair tests were removed after checking executable dependencies; documentation references are historical only. Source/hash evidence is in v14-class1-completed-test-cleanup.json. The same-chat900-second supervision job includes the quota block and current six controls. No new planner calls are authorized through a different key.

## Current control evidence (EXP287)

The frozen-input controls continue without prompt, processor, action, validation or evaluator changes. Original overlay Luna's step460 RGB supports purple between the right fingers above the table, but white remains beside yellow. At step480 carry_purple requires white still resting on yellow, whereas the current estimated white-minus-yellow XY is[-40.37,-25.52]mm with6mm half-widths and negative footprint margins. The fixed next stage is place_purple; no explicit recovery stage is selectable. This is a lost-precondition problem, not evidence that repeated direction choices can complete the tower.

Raw-three-RGB Luna reaches carry_white: step140 high/wrist RGB supports white between the fingers above the table. Text-only Luna reaches approach_white at step110 with open fingers. Neither establishes placement or native success. Text Luna's preparation advance also means missing images alone do not explain the previous Jev preparation stall; independently controlled states differ, so this is not matched-state causal evidence.

Classification snapshot maximum five-step endpoint errors are21.26mm (layout1 Luna),35.51mm (layout1 Jev),45.67mm (repaired layout0 Luna) and41.43mm (ended repaired layout0 Jev). Robot FK checks pass. Two layout1 Luna paths exceed the configured5rad/s at a planned waypoint; some negative joint3 targets have measured angles near-0.035rad despite wider public limits. These observations do not establish collision, a hidden limit or a single causal mechanism; no limits, dynamics or runtime were changed. exp287-robot-tracking-audit.json preserves measured evidence. Six hypothetical rotation effects are supplied, but layout1 Luna still has an approximately89-degree finger-to-down angle after200 steps in white_pen_approach, so general YPR task competence is not demonstrated.

Outer-only snapshots and source/image hashes are in exp287-current-rgb-audit and exp287-stage-evidence-audit.json. These files never become model history or experience. All six controls remain supervised; no new Sol request is made while the gateway quota question is pending. No new standalone test script was created.

## Native terminals and text-condition coverage (EXP288)

Original V13 stack0 overlay Luna ended at550 native steps: complete=true, native_success=false, score0, final carry_purple. It produced119 answers including9 stage advances and110 continue actions. Visible lifting of white/purple did not yield a completed tower. V14 classification1 Jev ended at1100 steps: complete=true, native_success=false, score0, still white_pen_approach. All220 answers passed single-rotation validation; no advance or close occurred. Do not resume either episode.

Text-only Luna returned prepare_white advance at95 steps, with TCP XYZ residuals[-1.33,-5.31,-6.88]mm inside the nominal11mm band. The condition also explicitly requires current-image identity, visible opening and clearance, but the request contains no images. Correction to EXP287's broad wording: this establishes a returned stage advance and numerical alignment clauses, not independently verified completion of every visual clause. All13 stack and25 classification stages contain visual language in a keyword audit; this flags incomplete replacement evidence, not a proof that all stages are impossible. Current image-derived geometry may support some clauses. Jev-versus-Luna text and image ablations therefore do not isolate model quality from evidence coverage and divergent states.

exp288-quantized-input-diagnostic contains171 saved preparation samples, a CSV and a plot with a common full-range vertical axis. Estimated Z residuals range from-129.75 to21.22mm; they are estimator outputs, not object truth, and missing values remain missing. No model receives the plot, saved history or audits. No standalone test script was created.

Four controls remain at the snapshot: Luna text205 steps approach_white; Luna raw RGB210 place_white; classification1 Luna290 white_pen_approach; repaired classification0 Luna255 pick_toy_1. These are running snapshots, not native success. New Sol planning remains blocked by the gateway quota pending a user resource response. Existing controls continue unchanged.

EXP288 classification modality extension: keep original classification1 Luna active and add processing-v14-class1-luna-text-pair01/classify_objects-l1-gpu6 (PID1610318, --omit-images) and processing-v14-class1-luna-raw-rgb-pair01/classify_objects-l1-gpu7 (PID1612081, --omit-additional-images). Both are independently initialized, pass registered-worker GPU admission, and copy the exact plan/processor/case/input_contract. First actual requests are English with zero/exactly three original RGB image keys. Processor SHA is06b3476d1be73fe5fee058c10d2ee2af116a17f0160de60b0b9fedfae5455b53. exp288-class1-input-pair-audit.json records all four hashes. No Sol request is required or made. The original ended Jev is not replayed. This extends modality comparisons to both development tasks without changing fixed roles, interfaces or perception algorithms; missing visual-condition evidence remains a comparison limitation. Six controls are now active again, with55.2GiB free at the audit and no image pruning.

EXP288 raw-RGB placement evidence: native220/request050 and285/request063 high RGB show white remaining above/aligned with yellow after release; by285 the open hand has withdrawn, and the apparent two-block stack remains. This supports placement persisting across65 native control steps. It does not certify contact, precise height, long-term/cross-layout stability or the complete three-block task. white_over_yellow is null in both processed contexts, and the later wrist view clips the stack at its top. oversight-raw-stack0-after-release01/visual_assessment.json retains image hashes and source indices. This independent episode does not overwrite the original overlay failure or establish causal superiority of a modality.

## Current-robot IK input comparison (EXP289–290)

Stack0 Luna text ended at550 native steps with success=false/score0; the raw-RGB condition ended at550 with success=false/score0.15 in carry_purple. This is a nonzero native score, not a complete task success. Current source/support fits disappear in that phase: at410 both white/yellow are missing while purple is visible in the fingers. Classification0 repair Luna ended incomplete at495 because its chosen XY increment failed the original robot IK gate;480 RGB supports a carried toy near the white basket, not a completed placement. These episodes remain ended.

A new independent raw-RGB layout1 condition, processing-v6-stack1-luna-raw-rgb-pair01/stack_blocks-l1-gpu2 PID1836156, copies the already delivered V6 layout1 plan/processor/case and omits only generated images. The original450-step source is not resumed. Because that source predates input_contract.json, the protocol is inferred from its initial permitted observation: native intrinsics, public tool geometry enabled, execution-budget details and optional perception tools disabled. The actual protocol matches. See exp289-layout1-pair-audit.json. This is exploratory, not frozen-framework cross-layout validation.

--ik-comparison-details / ROBO_IK_COMPARISON_DETAILS=1 optionally adds common current-robot information to the advancer. robot_motion_inputs.py enumerates27 XYZ sign triples crossed with seven allowed rotation choices. Each boolean matrix entry evaluates the exact existing five-waypoint numerical IK gate from current measured joints and public FK/root/joint limits. It uses no task geometry, object state, contact, history or model call, and does not select or rank an action. Numerical passes do not certify physical tracking, speed, self-collision, scene clearance or holding. The unchanged controller still validates and executes the model's selected complete action; no response is repaired or resampled.

The input contract adds ik_comparison_details, defaulting false for legacy three/four-field contracts. Existing four protocol fields still inherit unchanged. Explicit opt-in from an old source creates input_contract_override.json for the independent condition; later pairs inherit the enabled flag automatically. Default behavior and fixed roles, questions, schema, increments, native scoring and original kinematics.py gate remain unchanged. Future initial planning with the option only receives an interface description in the variable input-mode section; the runtime field is not a custom processor output. Current frozen-source tests require no Sol call.

Offline validation evaluates all189 combinations, reproduces the recorded495-step gate rejection and finds a numerically passing coupled alternative; none was executed. Protocol inheritance/override/launch assembly and fixed-interface checks pass without native or model calls. Validation scripts are not left behind; JSON results are in exp289-ik-input-validation. Native effectiveness remains unproven until the new independent controls finish.

EXP290 first native integration ended before any model request or action (processing-v13-class0-ik-input-luna01, PID2037577): the guarded atomic dump requires its parent directory to exist. EXP291 creates robot_motion_comparisons once for enabled episodes, before the decision loop. The missing-directory error is reproduced offline and the actual initialization plus guarded dump passes with no partial files. Metadata, plan, processor, prompts, increments and IK thresholds are unchanged. Preserve luna01 as a zero-step engineering failure and use an independent luna02; no valid response is resampled.

EXP291 actual delivery: independent luna02 (processing-v13-class0-ik-input-luna02/classify_objects-l0-gpu6, PID2077718) receives the English27x7 matrix as Luna high/du and executes actual native actions. Its10-step endpoint error was20.23mm, so numerical IK information does not resolve physical tracking. Jev01 (processing-v13-class0-ik-input-jev01/classify_objects-l0-gpu2, PID2128035) automatically inherits the enabled fifth field from luna02; plan/processor/case/contract bytes and the initial robot IK matrix match.

Jev01 ended incomplete at85 native steps:17 answered combinations had provided numerical-pass=true, but answer017 selected Xpositive/Ynegative/Zpositive with all rotations hold, whose supplied matrix row20/column0 is false. The unchanged actual gate also rejected it at its final waypoint (rotation error0.025437rad>0.02). No invalid answer was repaired or resampled. This disproves any guarantee that providing the matrix alone enforces joint action feasibility; it does not identify the model's internal reason. Luna02 remains running; its17 audited answers selected true, without establishing task success or causal superiority. exp291-constraint-choice-audit.json records both conditions. Original classification1 Luna also ended incomplete at625 with an IK rejection and is not resumed.

IMPROVEMENTS.md IMP-009 queues an untested named-constraint representation comparison. It is outer experiment management, never model experience or prompt content. Fixed roles/eight questions/schema/increments/gates remain unchanged. No complete task success is established.

Final EXP291 supervision snapshot: the independent V6 layout1 raw-RGB condition ended incomplete at505 native steps with an IK rejection, last executed stage lift_purple. Do not resume it or report a550-step native failure. Three controls remain running: classification1 raw RGB around500 steps, classification1 text around915, and classification0 IK-input Luna02 around125. exp291-final-status.json records the PID/outcome audit. These counts are snapshots, not completion claims; no full task success is established.

## Named robot IK presentation comparison (EXP292)

Optional --ik-comparison-format named / ROBO_IK_COMPARISON_FORMAT=named presents exactly the same189 numerical checks as27 records with named x/y/z choices and seven named rotation feasibility fields. The default matrix format is unchanged. robot_motion_format.py does not compute task geometry, select/rank an action or repair a response. The numerical builder, original execution gate, fixed roles/eight questions/schema/increments remain unchanged. Named and matrix presentations may differ in input cost; an offline fixture is8257 versus3580 JSON bytes.

The sixth input-contract field ik_comparison_format defaults to matrix for legacy contracts. Explicit prepared-source format changes are recorded in input_representation_override.json, and later pairs inherit the format automatically. Named format requires enabled IK comparisons. Initial tests use frozen classification0 plan/processor/case, independent native episodes and no Sol request. Runtime observation history and experience are not added. The improvement queue is never model input. Offline validation is in exp292-named-validation/validation.json; native effectiveness remains unproven.

Actual classification0 named controls: Luna PID2307469 (GPU2) and Jev PID2319977 (GPU5). English request audits show identical plan/processor/case/six-field contract and initial named checks; Luna keeps three original and two generated images, Jev receives text only. The source matrix Luna02 remains running. EXP293 separately starts V6 stack1 named-IK Luna PID2335753 (GPU7) and Jev PID2360286 (GPU2): the former source had no common IK information, so this is an added-information test, not a matrix-versus-named-only comparison or cross-layout stability validation. All are independent native initializations, not resumed failed episodes.

EXP292–293 outcomes: classification0 named Jev ended incomplete at135 steps when answer027 selected yaw positive and roll negative. Stack1 named Jev ended incomplete at0 with yaw negative and pitch negative. Neither is repaired, resampled or resumed. Thus named feasibility information does not enforce valid joint output choices. Luna controls remain running. Separately, old classification1 text Luna completed1100 steps with native_success=false/score0, ending in white_pen_capture rather than remaining in the first stage.

The classification0 named Jev decision013 passed all five numerical IK checks but had141.18mm measured TCP error. Its joint waypoint jump is1.677799rad over the public0.04s control interval, requiring41.944968rad/s versus the public actuator configuration5rad/s. This is a numerical-versus-tracking incompatibility, not proof of a single cause or scene collision. No gate, joint limit or physics was changed. exp292-joint-waypoint-speed-audit.json preserves the evidence; IMP-010 queues a future additional-information test, not an adopted change or model memory.

## Public joint-path rate input (EXP294)

Optional --ik-comparison-format named_rates / ROBO_IK_COMPARISON_FORMAT=named_rates extends the same six-field contract with a third format value. All original189 numerical IK flags remain unchanged. Independent robot_motion_rates.py records each predicted waypoint joint change and reports the maximum required rate per complete motion, together with the public session control interval and X5 arm actuator velocity_limit_sim. Named rows also include a rate comparison flag: true/false for a complete five-waypoint path, null when numerical IK did not produce the full path. A tested partial-path maximum is only a lower bound on its unavailable full path.

This is additional current-robot information. It does not select/rank/repair an action, constrain the output schema, change the execution gate or modify physical limits/dynamics. Target-rate compatibility does not certify achieved tracking, acceleration, torque, collision clearance, holding or task completion. Original robot_motion_inputs.py, robot_motion_format.py and kinematics.py are unchanged; default matrix/named behavior remains available. Explicit prepared-source changes and automatic downstream pairing use the existing representation override/contract mechanism. Plan and task processor remain frozen; no Sol request, history or experience injection is required.

Offline tests on the recorded large-error frame preserve all189 flags and original numerical diagnostics, reproduce41.944968rad/s from the actual stored joint path, reject invalid public parameters and preserve null on incomplete IK paths. Actual runtime configuration/branch and launch assembly are checked without native/model calls. Evidence is in exp294-rate-validation; no standalone test script is retained. Task effectiveness awaits independent Luna and paired Jev native controls.

Independent actual controls are processing-v13-class0-ik-rates-luna01/classify_objects-l0-gpu5 (PID2526822) and processing-v13-class0-ik-rates-jev01/classify_objects-l0-gpu6 (PID2539649). English input audits verify the public0.04s interval/5rad/s configuration, identical plan/processor/case/contract and identical initial rate information. Luna retains original/generated RGB; Jev is text only. Initial six executed choices per model have predicted rates exactly equal to the actual commanded path calculation. Nevertheless Jev selected a provided rate-false5.04312rad/s choice, and Luna had20.23mm measured error with rate-true2.74665rad/s. These are running negative examples, not native task terminals or causal model rankings. The original gate/physics remain unchanged; no response is repaired or resampled.

Later terminal: rate-input Jev ended incomplete at170 steps. All35 answers passed single-rotation validation, but answer034 selected Xpositive/Ynegative/Zpositive with all rotations hold, whose supplied numerical IK flag is false and complete-path rate flag null. The original gate rejected it before execution. Maximum measured endpoint error over its executed trajectory is41.97mm. This episode is not repaired, resampled or resumed; longer survival than an independently diverging episode is not task success or causal improvement. Luna rate-input and four prior Luna controls continue. See exp294-jev-terminal-audit.json.


## Current entity evidence and TCP-reference audit (EXP295)

Five existing Luna controls remain active; exp295-final-status.json records850/475/290/410/145 native steps as a snapshot, not task completion. Current high/right-wrist RGB at stack1 step370 supports purple retained between fingers above the table, while its lift_purple input has invalid source fit, null goal/translation comparisons and empty observable relations. White-pen wrist RGB at815 still shows the pen on the tabletop. These are distinct entity/input failures; stage pointers and numerical IK flags do not certify capture or stacking.

V6 processor subtracts0.145m from public robot mesh X although both original and current runtime report TCP at0.15007m along LINK6 X. An independent prepared-v6-stack1-tcp-reference-fix01 copy corrects this5.07mm mismatch in two mesh transforms and descriptive text. No running processor or framework was changed. Three frozen-frame sandbox tests succeed and the tip-Z difference matches the analytic shift within1e-9m. The lifted source wrist-fit RMS decreases3.1012 to2.2202px, but remains invalid with null lift inputs. Thus the correction is an offline candidate, not a demonstrated control improvement or adopted replacement. exp295-tcp-reference.patch and exp295-tcp-reference-validation/comparison.json preserve the exact change/results; no new native/model call was made.

The current Sol quota block remains active. Do not probe429 again, change keys or start new planning without user resource authorization. Existing controls continue; ended episodes are never resumed. RGB/diagnostic audits remain outer-only, not model memory or distilled experience.


## Persistent phase-input coverage (EXP296)

A frozen stack1 lift_purple audit covers31 executed decisions067–097, ending325–475 native steps. All31 source fits are invalid and all31 goal/translation comparisons null. Outputs include19 positive-Z choices,11 all-motion-hold choices and one other non-all-hold choice with Zhold; there are zero advances. High/right-wrist RGB still supports purple retained above the table, with cream/dark on the table. This is actual lifting with unavailable phase completion measurements, not merely a refusal to move or full stacking success.

Current classification0 decision109 supplies18 unclassified stereo P points and public robot/tool effects, without an explicit semantic toy-to-finger residual or retention measurement. Classification1 decision186 supplies three unclassified feature proposals; holding/containment evidence remains null and wrist RGB shows the white pen on the tabletop. RGB is still required to infer these task relations. This audit does not establish a unique cause or rank models. See exp296-coverage-audit.json, exp296-input-coverage and exp296-stack-lift-evidence. Audits remain outer-only and are not model history or experience.

Latest five Luna snapshots are930/555/355/485/230 steps, all running with no new terminal or full success. No new model/native episode, source change or additional metadata condition was introduced. Sol quota restrictions remain active; storage is30.62GiB free, above the pruning threshold.


## Stack1 named-IK native terminal (EXP297)

processing-v6-stack1-ik-named-luna01 / PID2335753 ended at550 native steps: complete=true, native_success=false, score0. It produced113 answers with3 advances, and ended in lift_purple. Executed phases: approach16, engage47, secure1, lift46. This episode must not be resumed or resampled.

The complete lift segment has43/46 invalid source fits and null goal/translation inputs,20 positive-Z choices,20 all-motion-hold choices and no advance. Purple is visible between fingers before decision108; that output opens the gripper while choosing negative Z/pitch. Subsequent wrist/high RGB supports loss of retention and purple back on the tabletop, with an empty hand above. Only decisions110–112 restore a valid fit, now for the tabletop source; this is not retained-source progress. Their positive about81mm scalar Z goals and negative-Z choices cannot alone characterize a usable recovery policy. The last saved input images precede step550, at545; no postterminal image is claimed. exp297-stack-terminal contains raw images, SHA index, actual payloads, outputs and complete audit.

Four classification Luna controls continue at snapshot1060/690/490/350 steps, without a new full success. Storage remains28.63GiB free. No running source, prompt, gate, physics or processor was changed; no new Sol request or native episode was launched. Existing quota restrictions remain active. Terminal and RGB audits remain outer-only, not injected experience.


## Classification1 raw-RGB native terminal (EXP298)

processing-v14-class1-luna-raw-rgb-pair01 / PID1612081 ended at1100 native steps with complete=true, native_success=false and score0. It returned221 answers, one advance,14close and17open commands. Executed stages are43 white_pen_approach and177 white_pen_capture actions. This was not an absence of grasp attempts; it advanced approach but did not pass capture or complete sorting. Never resume or resample the ended episode.

All220 executed observations have null processor holding/containment evidence. Null means unmeasured, not a detector proving that no transient contact ever occurred. The last right-wrist input shows the white pen on the tabletop beside the red basket. That frame is before the final close/hold action, at1095 native steps, not a post1100 image. Native failure is established independently by the terminal result. exp298-class1-terminal retains actual payload, raw RGB/SHA and complete counts; the audit remains outer-only and is not injected experience.

Three class0 Luna controls continue at snapshot830/625/485 steps, all pick_toy_1, with26.08GiB free. No running source, prompt, gate, physics or processor was modified; no new Sol request or native episode was started. Sol quota authorization remains unresolved. Full task successes remain zero.


Ongoing supervision after EXP298 introduces no new condition or experiment. Three classification0 current-input snapshots are about960/760/615 steps, all pick_toy_1 with zero advances and23/16/8 close commands respectively. Current high/left-wrist views do not establish retained suspended grasp; occlusion and unreviewed earlier frames prevent stronger negative claims. oversight-class0-20261018-0700 preserves actual payloads, raw RGB/SHA, counts and the latest status.json. Existing native episodes continue unchanged; no new Sol call, native episode, prompt/source change or model memory is introduced. Do not resume ended classification1 or stack1 episodes.


## Classification0 matrix terminal and rate-stage transition audit (EXP299)

This is a retrospective audit of existing EXP291/294 conditions, not a new experimental condition or native episode. Matrix Luna PID2077718 ended at1100 steps, complete=true/native_success=false/score0. All220 answers stayed in pick_toy_1: zero advances,30close,24open. Last saved wrist input is at1095 steps, before the final action; it does not clearly establish retained suspension. Never resume or resample this terminal.

Existing rate-input Luna advances at decision125 with all axes hold/gripper keep and later reaches place_toy_1. Reviewed125 high/wrist images do not clearly establish suspended retention;150 high shows the hand near/above the blue basket, while the wrist shows its interior without an identifiable toy. Source/hand occlusion prevents certifying retention or loss. Thus phase advancement and robot movement are observed, but retained source transport and basket placement are not independently established. exp299-class0-audit retains actual payloads, raw RGB/SHA and counts. These are outer-only audits, not model history or experience.

Two controls remain active at snapshot: named PID2307469 at920 pick_toy_1; rate PID2526822 at755 place_toy_1. Storage23.11GiB free, full successes zero. No new Sol request, prompt/source/processor/gate/physics change or native episode was introduced. Sol resource authorization remains unresolved.


Unchanged-run supervision after EXP299: named Luna PID2307469 is around1055 steps in pick_toy_1, rate Luna PID2526822 around850 in place_toy_1. Rate decision171 active-wrist RGB shows no identifiable toy in the visible basket interior or clearly retained between the finger image regions. High-view arm/source occlusion prevents stronger loss/absence claims; completed placement is not established. oversight-class0-20261018-0730 retains payloads, raw RGB/SHA and status. No new condition, native episode, Sol request, source/prompt change or model memory was introduced.22.29GiB remains free; no pruning. Existing episodes continue, and ended episodes remain sealed.


Named classification0 Luna PID2307469 has now ended at1100 native steps with complete=true/native_success=false/score0. It returned220 answers, zero advances,20close and17open commands, all in pick_toy_1. Its last219 input image is preaction at1095 steps and does not establish retained suspension. Do not resume or resample this episode. This is the terminal of the existing EXP292 condition, not a new experiment. oversight-class0-20261018-0745/named_terminal preserves actual payload, raw RGB/SHA and terminal audit.

Only rate-input Luna PID2526822 remains running, around970 steps in place_toy_1. Current195 wrist RGB does not show an identifiable toy in the basket interior; placement remains unestablished.20.68GiB is free and no images were pruned at this audit. Existing storage_guard watcher PID3007137 is active with the20GiB threshold and skips active runs. Sol authorization restrictions and all frozen model/action/physics protocols remain unchanged.


## Existing control set fully terminated

The existing rate-input Luna PID2526822 ended at1100 native steps, complete=true/native_success=false/score0. It produced221 answers, one advance,9close and34open commands;125 executed pick_toy_1 actions and95 place_toy_1 actions. Last input220 is at1095 steps: two toys remain on the tabletop in front of the white basket, another is by the stationary right hand, and no identifiable toy is visible inside the blue basket. These preaction views and the independent native terminal do not establish successful placement or exclude earlier transient retention. Never resume or resample this episode.

| Existing classification0 Luna condition | Native steps | Native success | Score | Advance count | Final stage |
| --- | ---: | --- | ---: | ---: | --- |
| matrix |1100|false|0|0|pick_toy_1|
| named |1100|false|0|0|pick_toy_1|
| named_rates |1100|false|0|1|place_toy_1|

These independently diverging trajectories are not a causal model ranking or a stability demonstration. Registered-worker audit now finds no live native worker in this campaign. Full task success remains zero. oversight-class0-20261018-0800 holds terminal payload/RGB/SHA, status and retention accounting, all outer-only and never model memory or experience.

The existing storage guard pruned6151 image assets from ended classification tasks after crossing20GiB, releasing7178424765 bytes (about6.69GiB); text/native results remain. No additional manual pruning was performed; latest audited free space is26.08GiB. Sol6.1 high quota authorization remains unresolved and has been requested again now that all native controls have ended. Do not issue new Sol requests, probe429, change keys, replay ended episodes or produce repetitive no-change audits while awaiting the resource response. No running method, prompt, processor, gate or physics was modified.

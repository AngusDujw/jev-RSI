# Visual relation and hybrid control — 2026-10-18

## Native task1144: bowl onto stove

Frozen inference commit9751c2e9. Three predeclared initial states; no replacements. Native success and program completion both3/3. This is hybrid control, not pure RGB.

| Initial state | Visual X decisions | X residual before/after coarse phase, mm | Native steps | Actual API responses | Native/program |
|---|---:|---:|---:|---:|---|
|5|6|119.57 →37.67|276|98|true/true|
|6|6|107.03 →25.34|273|97|true/true|
|7|6|116.10 →36.35|258|92|true/true|

All18 visual directions agreed with the sign of the separately measured camera-derived X residual. The visual role did not receive that residual. It classified above/center/below in a current wrist crop; a fixed public-orientation map selected X. The independent motor role received numerical Y/Z during coarse approach, then XYZ during fine positioning and subsequent manipulation. The original controller still determined motion magnitude numerically. Therefore the useful contribution demonstrated here is coarse direction selection, not visual metric control.

The readiness gate is algorithm-derived X magnitude at most40mm or the visual classification center. Neither numerical tolerance, EEF coordinates nor K/T matrices enter the actor; the numerical role deliberately receives derived signed residuals and aligned booleans. The original phase graph, action scaling, budgets and final success predicates remain. Experience injection is disabled.

Actual input audit:287 responses,18 visual images,269 text motor responses, no terminal API errors. The audit checks raw saved requests, role-specific fields, English text and preserved execution maps. Source: remote `code/runs/2026-10-18-libero-hybrid-coarse-x-v1/role-audit.json`.

## Earlier native image-centering diagnostics

These are subtests, not native task success. All normal failures remain recorded.

| Version | Change | Result |
|---|---|---|
|v1|Visible target and direct motor choice|Current3/6, previous+current0/6|
|v2|Observable option descriptions|Development pilot0/2|
|v3|Additional fixed-center enlargement|Development pilot0/2|
|v4|Image relation output, fixed motor mapping|5/6; one reached10px but did not HOLD|
|v5|Visible fixed image midline|Development pilot0/1; reached10px but did not HOLD|
|v6|Visible acceptance band matching the existing evaluation|6/6;76 responses, all ended with model HOLD|

This supports separating coarse visual perception from precision stopping. It does not establish that temporal images or overlays cannot help other tasks.

Version6 instead makes the small accepted image region visible. It draws a fixed central cyan strip, not a source/TCP marker, and asks whether the bowl outline center is inside the strip. No numerical residual or numerical tolerance enters the request. The old evaluation remains unchanged. Final original-image errors were10,-13,13,-14,3.5,-13.5 pixels. This fixes the mismatch between asking for an exact line and evaluating a finite acceptable region in this small diagnostic. Independent vertical-direction validation is still needed.

Version7 vertical validation scored4/6 under the old interior-texture-point metric,105 responses. Two negative-offset cases ended at-23/-21 pixels. A read-only RGB rim fit in init5 gave outline center374.09 versus tracked texture point361: the outline center was actually inside the band. These scores cannot cleanly measure visual classification accuracy. Preserve4/6; version8 separately changes setup and evaluation to the RGB rim center, matching the stated visual target. This is a different evaluation reference.

Version8 aborted all six cases in evaluator setup before any model call. Version9 added long-arc coverage and rejection-image logging; four cases still aborted in setup and two during evaluation after model actions. Actual provider responses were8, not the6 completed trace entries. These are evaluator failures, not six scored model failures. Neither version establishes reliable vertical visual control. A stable feature definition/evaluator is required before removing further numerical feedback in full tasks.

## Native task1252: bowl onto cabinet

Frozen inference commite8c14f71. The same relation/motor interface is used with a separately generated task-specific Pro goal. All three fixed initial states completed native success and program completion. No replacements or API failures.

| Initial state | Visual X decisions | X residual before/after coarse phase, mm | Native steps | API responses | Native/program |
|---|---:|---:|---:|---:|---|
|4|7|117.60 →24.33|330|117|true/true|
|5|7|127.39 →33.20|333|118|true/true|
|6|6|112.09 →33.58|336|118|true/true|

Actual role audit:20 visual decisions,333 text motor decisions,20 images,353 total responses. All20 visual X directions agreed with the independently audited camera-derived residual sign. Together with task1144:6/6 complete native tasks,38 visual directions and602 numerical motor responses. The tasks share the same bowl appearance and fixed wrist orientation, so this is limited transfer evidence rather than general object/task robustness.

All six full-task coarse approaches started with positive X residuals. Their38 visual-role-sourced directions were all positive; these runs alone do not prove images were necessary relative to a constant positive-X policy. The separate horizontal image-centering diagnostic includes both offset signs. No improvement over the already successful numerical text baseline is established by these small samples.

## Files changed in this iteration

Implementation under `code/decision_multimodal/`:

- `libero_visual_servo.py`, `libero_visual_servo_grounded.py`, `libero_visual_relation_servo.py`
- `libero_visual_band_servo.py`, `libero_visual_band_x_servo.py`
- `libero_visual_outline_servo.py`, `libero_visual_outline_arc_servo.py`
- `libero_hybrid_vision.py`, `libero_hybrid_cabinet.py`
- `libero_entry.py`, `run_libero_campaign.py`
- `audit_hybrid.py`, `build_hybrid_evidence.py`
- `plans/libero_hybrid_coarse_x_v1.json`, `plans/libero_hybrid_cabinet_x_v2.json`
- `LIBERO_VISUAL_SERVO_PROTOCOL.md`, `LIBERO_HYBRID_PROTOCOL.md`, `LIBERO_HYBRID_RESULTS.md`

Records:

- `code/experience/decision_multimodal_visual_20261018.md` (collection only)
- `LOGS/2026-W42.md`, `LOGS/2026-W42-activity.md`, `Discussion.md`, `TIMELINE.md`

Generated evidence assets remain under ignored `code/runs/`; the published route is `/hybrid-evidence/`. No temporary test script was retained. Protocol lint and module syntax checks passed. HTTP page/data availability and page-script parsing were verified; UI browser verification was unavailable because the computer-use provider exposed no browser.

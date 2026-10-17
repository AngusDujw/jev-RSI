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

This supports separating coarse visual perception from precision stopping. It does not establish that temporal images or overlays cannot help other tasks. Task1252 transfer is the next independent three-case validation; it has not yet been counted here.

# Collected experience — not loaded into either runtime model

These notes are experiment records, not runtime prompts. Evidence is case-specific.

| Finding | Evidence | Reuse candidate |
|---|---|---|
| Unrelated future-stage checks can keep the actor in an already completed stage. | Stack dev004:325 steps without grasp. Dev005:stage-scoped inputs and explicit transition wording reached grasp/lift in149 steps. Two changes were combined, so individual effects are unknown. | Send current-stage fields and an explicit next-stage condition. |
| A captured object can hide its destination just before placement. | Stack dev006 reached carry/lower, then the current destination fit failed at step226. | Design partial-observation placement and destination memory before freezing a controller. |
| A strict contact margin can be impossible for a thin object. | Scissors:RGB material height about4.5mm; previous plan required3mm clearance plus3mm overlap. | Check inequalities before execution; distinguish a candidate grasp from visible capture testing. |
| Ordinary feature matching may fail across wrist/high-view perspective changes. | Four initial scenes each yielded only3 reciprocal geometrically consistent SIFT table matches. | Evaluate calibrated texture registration under a declared plane hypothesis. |
| A fixed-normal tracker can hide object tilt after grasp. | Geometry limitation identified by Pro, not yet a measured manipulation failure. | Fit unrestricted rigid pose and report conditional gain envelopes. |
| The fixed legacy interface can contain single-option questions. | Two Goal1202 text-baseline episodes hit the Decisions minimum-two-options constraint. | Audit interface compatibility separately; preserve these failures in the frozen comparison. |

Full formal LIBERO results: [PHASE1_RESULTS.md](PHASE1_RESULTS.md).

- A good current multiview fit can survive failure of a resting-plane tracker. Prefer the valid current estimate, rather than rejecting both. General pickup dev008: native success at108 steps; frozen v1:2/3 native successes, not stable.
- Closure can shift a thin object. Initialize candidate hand/object attachment after closure, then test successive co-motion during active lifting. A preclosure offset confounds settling with slip; validation episode2 also hit a6.357mm lift sensitivity against an overly strict6mm universal gate.
- Visible button depression/release is insufficient to establish electrical counts. Button dev004 completed11 proxy cycles at415 steps but native success was false. Preserve both results and improve stroke/release evidence before another full sequence.
- Green-handle features can all disappear during closure. Recorded scissors tracks went12 to5 to0. Whole-object SAM masks include visible blades, but the new geometric fit has not passed; segmentation confidence alone is insufficient.
- A nominal SDK camera can differ from the actual tiled RGB capture. Here SDK high-camera fy336.46 conflicts with the render projection fy288.13; actual render K matches the original primary K. The attempted SDK replacement failed same-image texture registration and was never used for control.
- Planner thresholds need measurement support. A proposed0.5mm precision gate is not justified by a2mm working halfwidth. Record rejected proposal details rather than silently treating them as implemented.

- A robot HOLD should retain a stored world reference when that is its contract; relatching a disturbed measured pose can change the task target. A numerical check does not establish loaded physical tracking.
- A body-return waypoint may stall even after a successful manipulation. The lateral unloaded-hand corridor completed both sleeve operations in fold dev005; full task still failed at346steps.
- Nearest silhouette vertices can select wrinkles instead of a garment hem corner. A strong convex-turn selector fixed the recorded13px seed ambiguity; this is an offline processing result, not a fold success.
- A partial RGB template cannot explain newly revealed current arcs. Match only a predefined visible correspondence domain; do not discard pixels based on residuals to manufacture acceptance.
- Better segmentation alone does not establish geometry. SAM improved the recorded held wood fit from4.619px to2.283px, while the purple support fit still failed.
- A planner process must be isolated before inference. One attempted repository-reading/Chinese call was rejected; later calls disabled tools and used explicit English inference instructions. Rejected plans were never deployed.

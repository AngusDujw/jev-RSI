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

- A future holding test must not block completing a closure trial. Keep axis questions about their own signed error and transition questions about the current phase. LIBERO clarity v1 had4/25 joint successes but regressed plate control; broad cross-stage additions are not a validated improvement. Experience remains collection-only.
- Stage-local questions improved the same LIBERO repair sample from3/25 to20/25 joint outcomes in v2;1144/1252/1296 each reached5/5. Preserve explicit task-specific bounded-trial exceptions when simplifying prompts. Three original1202 budget failures and two1423 program failures remain; do not turn partial improvement into a general guarantee.
- Preserve the original bounded-trial instruction when its current candidate flag is true; do not summarize away its exception to target arrival. LIBERO1423 v3 reached5/5 joint outcomes on the five paired states, after v2 had3/5 joint. This is a per-task validation, not a universal contact rule;1202 remains2/5.

- Adding labeled RGB did not automatically help the latest LIBERO text controller: native21/30 and joint20/30 versus a historical paired text reference27/30. Keep task success separate from axis advice accuracy.
- Small goal/reference markers were not read reliably:36/66 image-axis judgments. A public world-axis ruler changed nominal nonzero advice from34/74 to35/74. Improve visual target readability before assuming that camera matrices alone make XYZ decisions understandable.
- An invisible intermediate waypoint may be unidentifiable from raw RGB and a semantic stage name. A projected waypoint supplies processed target evidence; describe it honestly.
- Images affected decisions, but simple image recognition did not establish robot control competence: two colored-shape layouts gave8/8 correct responses, while removing robot images changed23/23 valid categorical answers toward HOLD.
- Preserve connection faults separately from normal task failures. Replace only interrupted complete episodes with explicit source provenance; never rerun an answered decision to obtain approval.

- Verify motion vocabulary against the installed controller before testing visual direction advice. In this LIBERO setup, forward is world+X and left is+Y; native rotation is a world rotation vector, not sequential Euler angles. Name any yaw/pitch/roll aliases explicitly.
- A controlled site and a finger-pad midpoint need not coincide. This open PandaGripper had a3.60mm offset. The body quaternion and controlled-site rotation also differed by90degrees; use a consistent frame for absolute tool orientation. Six independent50mm/30degree demonstrations passed endpoint checks below1mm/0.2degrees, but pitch transient pivot drift reached5.12mm. This is control calibration, not evidence of improved model decisions. Experience remains collection-only.

- Motion words and a camera-oriented XYZ compass did not replace explicit positional feedback in this LIBERO retest. Ten tasks, three paired states each: full native 27/joint 26 out of 30; markers 1/0; markers plus compass 0/0. Keep numeric translation support when using this input representation. This is a version-specific result, not a general multimodal capability limit.
- Check sustained visual control, not only the first answer. Compass 1144/init5 started with correct XYZ choices, then reversed Z on the next decision and continued positive X after a 221 mm overshoot. All residuals here are offline diagnostics; neither reduced actor received them.
- Preserve numeric tolerance definitions when shortening a question. In three legacy tasks the 2 mm constant existed only in the old XYZ question; "within tolerance" lost that number. Also inventory remaining geometry explicitly: removing translation_axes is not pure RGB control. These are interface maintenance findings, not a diagnosis of every failure. Collection only; no runtime injection.

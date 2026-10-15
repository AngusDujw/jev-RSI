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

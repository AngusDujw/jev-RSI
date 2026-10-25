# Actual complete GPT method: initial state13

The final source and final interface are authoritative. Model descriptions below are preserved verbatim. Earlier design/rationales are historical, not additional runtime instructions.

## Final interface

main(api) still returns JSON-compatible completion_proposed and evidence, using the existing episode checkpoints and saved tracker with fresh updates. Approach review adds bowl_profile (round_tapered, other, unknown) and action=model_check. That choice requests current named points o0 through o5 on the visible outer upper lip and authorizes only a conditional numerical local-envelope test. It is unavailable for unrelated hidden obstacles or non-tapered/non-circular geometry. Required support measurements remain unchanged.

Current actual pad enclosure is recorded numerically before closure. When called during possible_holding, approve_transfer additionally requests contact and probe using the existing explicit closure meanings. Its transfer permission remains conditional until observed object motion agrees with actual hand motion during the retention test. The normal path reserves three reviews after approach: one combined closure/conditional-transfer review and two released-outcome observations. Unknown registration retains executable landmark/edge recovery, but insufficient remaining evidence or budget still produces an explicit incomplete result without reopening a carried item.

## Final Jev input/output cooperation

The existing seven Jev control questions and exact choice keys are unchanged. Each world translation or rotation-vector question explicitly selects its own host goal_relation; positive means increase, negative means decrease, and hold means within_tolerance. The gripper question dispatches the requested open, close, or keep choice unchanged. Python computes pad-center targets, actual finger-envelope projections, circular-fit diagnostics, support residuals, pose allowances, and attachment errors. api.drive provides bounded pose feedback through real api.control; jaw transitions and settling intervals use api.control directly.

Image review distinguishes positively observed external interference, no observed interference without clearance certification, self-occlusion, and other unobserved space. model_check is a conditional branch supported by newly requested outer-lip measurements, not permission to assume hidden space empty. Transfer approval obtained at closure remains inactive until a fresh retention test passes and the remaining route is numerically revalidated. Delivered closure, observed retention, release, supported containment, and short-interval stability remain separate claims.

## Original complete model design (historical if revised)

This method interprets the episode request from current images and constructs a measured, top-down transfer for a rigid rectangular item and an open, approximately horizontal circular container. It does not use a stored trajectory or simulator object state. Source geometry comes from a visible top plane, calibrated boundary rays, visible side/support evidence, and persistent physical print landmarks. Destination geometry comes from measured rim samples and a separately observed interior surface.

The method aligns the actual gripper opening axis with the measured narrow dimension, uses pad_center rather than TCP for targeting, and intersects pad/side overlap with finger-envelope support clearance. Visual checks distinguish observed external obstacles, self-occlusion, and other unobserved space. They authorize only bounded local motion, not certified clearance of a future route.

A textured RGB-D reference is initialized before contact. Retention requires independently observed object motion consistent with measured hand motion during a small lift; closure and tracking alone are insufficient. Unknown tracking has an executable fallback using semantically identified print landmarks and a fresh face plane, optionally followed by one locally justified upward observation move. A recovered reference can seed a new persistent tracker without assuming attachment.

The retained item is carried above the measured rim, centered using fresh object observations, and released only when its measured horizontal envelope fits the opening and the fingers remain above the rim. Retraction and repeated, physically separated observations assess the final relation and settling. Checkpoints preserve reference provenance, acknowledged jaw transitions, and phase evidence across repairs. Failures return numerical diagnostics and do not trigger blind pushing, reopening during transfer, or uncertain regrasping after release. Completion is a proposal, not native evaluator success.

## Model revision1 rationale (historical)

The failure was an observed bowl-rim obstruction to the centered, fully open descent, not a failed grasp or lost reference. This repair preserves the open-jaw approach phase and the saved RGB-D reference. It constructs an off-center grasp near a measured package end, where a finite longitudinal pad band still overlaps both long sides. It first retracts upward, then translates above the rim, then performs separately reviewed local descents. The circular opening is only a numerical candidate-screening aid; current image review must still assess the actual external bowl and finger sweep. No blocked descent is retried unchanged.

The repair also preserves valid historical destination geometry when fresh distributed lip measurements and visual identity remain compatible, rather than demanding a new full fit through hand occlusion. Changed geometry still requires remeasurement. Approach references are refreshed after repositioning. Existing independent retention tests, tracker recovery, transfer, release, and final containment/stability assessment remain intact. A single bounded upward post-release retreat reduces review consumption while preserving the native control limits. Nothing in this patch asserts that the task has already succeeded.

## Model revision2 rationale (historical)

The failure was checkpoint growth, not a new physical failure. The last successful checkpoint still records an open-jaw approach, and the robot remains at its measured intermediate descent pose. This patch separates essential reference and phase measurements into bounded checkpoint components, independently bounds diagnostic history, preflights payload sizes, and prevents a secondary checkpoint error from masking the original failure. Legacy checkpoints remain readable; tracker handles, semantic landmarks, jaw acknowledgments, and measurement provenance are preserved.

Two directly coupled restart issues are repaired. Fresh, well-spread partial lip measurements can validate the stationary destination reference without requiring a new full rim reconstruction through hand occlusion. An already aligned approach resumes its locally reviewed descent instead of unnecessarily withdrawing and repeating the lateral approach. The budget gate reserves four remaining reviews for verification and recovery before ordinary motion. No historical review is treated as current permission, and no closure, retention, or task success is asserted by this patch.

## Model revision3 rationale (historical)

The stopped episode is still an open-jaw approach. The failure was a registration prerequisite: the old recovery required two printed landmarks even though one identified mark, the measured printed-face plane, and a visible segment of its identifiable short-end boundary can determine the pose. This patch implements that alternative with two tested direction hypotheses, finite-edge consistency, uncertainty reporting, and rejection of ambiguous correspondence. It does not require hidden corners, equate a track with retention, or undo the acknowledged withdrawal.

The directly coupled budget problem is also repaired. Registration reviews now collect the specific approach, enclosure, or post-closure evidence needed at that phase. A measured, locally reviewed descent is not reviewed again without a scene change. After independently measured retention, one structured review validates the stationary bowl reference and the numerically specified short elevated transfer. Each approved segment remains bounded and is followed by an independent object/hand motion comparison. Two final observation reviews remain available for released containment, separation, and settling. Unknown tracking still invokes current landmark/edge recovery; inadequate evidence or a stall stops the method without reopening a carried item.

## Model revision4 rationale (historical)

The stop conflated a change in registered object position with invalidation of the stationary tabletop and the package's measured rigid dimensions. This repair preserves those reference invariants but revalidates support using a current tabletop cloud, explicit visual support evidence, and the independently registered package base relative to the measured plane. It records the residuals and rejects inconsistent or unresolved support instead of rejecting any lateral displacement.

The approach is now planned before its review. A small, currently justified lift and lateral correction can replace the unnecessary large withdrawal; one review authorizes only the numerical local waypoints and checks support. Existing preclosure, post-closure, retention, transfer, and released-outcome checks remain. The routine path reserves five reviews after approach authorization, fitting the six-review budget when the saved tracker remains usable. Unknown tracking retains the existing current-landmark/identified-edge recovery and may still require an honest budget stop.

The saved package half-diagonal is close to the measured bowl radius, so the old release test also demanded more uncertainty clearance than the nominal fit supplies. The repair separates certified geometric fit from a bounded placement trial: a reviewed short drop requires fresh nominal containment and finger/rim separation, then the existing two post-release observations assess actual containment and settling. It never proposes success from the release command or from nominal geometry alone.

## Model revision5 rationale (historical)

The previous stop treated the hand-hidden bowl boundary as a need for full visual clearance, and its five-review reserve no longer fit the four-review budget. This patch asks a concrete new measurement question: can visible outer-lip samples and the visible tapered exterior support a local circular bowl-envelope model? Only an explicit model_check response permits that numerical alternative. The code fits the current samples, checks them against the independently measured opening, and compares the actual finger envelope over the short approach segments with that exterior model. Observed interference, an inadequate model, other unobserved space, and an explicit stop still forbid advancement. The model is local evidence, not a collision certificate.

The ordinary path now needs four reviews: approach/support, actual closure plus conditional transfer authorization, and two post-release observations. A separate preclosure review is replaced by checks of freshly registered object geometry against actual measured finger pose, aperture, pad overlap, and support separation. The combined closure/transfer review does not establish retention: the existing independently measured lift test must pass before its route permission can become usable. The permission is reused only if the actual lifted pose lies on its first vertical segment and the recomputed remaining waypoints agree within its measured allowance. Existing tracker provenance, semantic correspondence recovery, jaw checkpoints, stall handling, bounded release trial, and final containment/stability assessment remain intact. No success or grasp is asserted by this repair.

## Complete source

[method.py](method.py), [exact package](method.json), and [provenance/audit](PROVENANCE.json).

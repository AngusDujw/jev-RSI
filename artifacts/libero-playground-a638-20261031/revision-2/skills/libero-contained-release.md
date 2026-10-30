---
name: libero-contained-release
description: Establish opening geometry and intrinsic fit before designing a release with independent support and stability verification.
---

# Measured containment and release

## A. Semantic opening measurements and intrinsic-fit rejection

**Status:** scene-specific. Episode 1 repaired a lip measurement set and rejected one horizontal candidate without containment motion. No successful placement is demonstrated.

**Applicability:** A retained rigid object and a sufficiently visible, approximately horizontal circular inner opening. Other opening shapes need a justified different model.

**Inputs and frames/units:** Current depth-safe lip anchors and visible inner-boundary pixels with camera/frame IDs; interior support observations; conditional carried envelope and uncertainty in world meters; current attachment; measured hand geometry. Historical dimensions/underside assumptions are not fresh hidden-surface measurements.

**Jev versus program:** Reviewer distinguishes lip crest, lower interior, visible boundary and scoped routes. Program validates samples, fits geometry and computes full-envelope margins. Jev is unnecessary for a stationary fit and cannot certify containment.

1. Establish current retained identity before placement planning. Reidentify visible material details and exposed edges; retain explicit assumptions for hidden envelope parts.
2. Semantically validate spread lip anchors before fitting a plane. Invalid depth or a point on a different surface is a measurement-selection failure, not proof that the opening is unsuitable.
3. Replace invalid/misclassified samples with genuinely different depth-safe patches. Retain all valid replacement anchors; do not trim solely to obtain a favorable fit.
4. Validate visible inner-boundary identity and coverage separately. Project calibrated boundary rays onto the supported lip plane; outer silhouette and imagined hidden arcs are not substitutes.
5. Fit a circle only when arc coverage, residuals and model applicability justify it.
6. Evaluate the entire transformed object envelope. In lip-plane coordinates, a conservative radial margin is:
   - margin = r - max_i(norm(envelope_i_xy - center)) - u_object - u_opening.
   Reserve additional clearance, pose error and applicable rotational uncertainty inside this margin. Also evaluate vertical and whole-hand clearance.
7. If intrinsic fit fails, a center correction cannot manufacture slack. Consider a distinct justified orientation or better evidence, without reducing margins.

The first lip set included an invalid depth and a lower-interior sample roughly 35-37 mm below the other lip samples. Six semantically replaced anchors yielded about 0.218 mm plane RMS. The resulting horizontal candidate had reported radial slack of about 1.177 mm after uncertainty, but negative proposed pose tolerance under its retained margin rules. This rejects that candidate, not every possible placement.

**Failure/stopping conditions:** Block on ambiguous surface identity, inadequate arc/support, uncertain attachment or unresolved hidden-envelope dependencies. Reject inadequate fit before transit. Unknown space is neither observed obstruction nor permission to move.

**Evidence IDs:** E-M2, E-PLAN; N-J7, N-J8, N-RC, N-G, N-C. Most containment source and large reference checkpoints are omitted; do not infer their unreported numerical branches.

## B. Release, tilt and settled-support design

**Status:** hypothesis. Episode 0 exercised only entry and a preliminary upward hand move. Episode 1 obtained limited rise-and-rotation review but executed no containment motion. Neither establishes release, withdrawal or placement.

**Applicability:** An attached object with a measured feasible opening fit and observable interior support, with enough resources for transport and final-effect checks.

**Inputs and frames/units:** Fresh attachment and conditional envelope; opening/support geometry; actual closed and opened finger bounds plus whole wrist geometry; obstacle and swept-route observations; uncertainty/tolerances in meters and radians; actual native-step counters.

**Jev versus program:** Reviewer authorizes only observable local corridors and relations. Program generates and checks segments, transforms full envelopes, preserves acknowledgements and assesses release/support/stability. Jev delivers bounded segments and exact gripper requests.

Proposed sequence:
1. If clearance/visibility needs an upward move, review only that corridor, then refresh attachment and affected geometry. Reached does not prove improved visibility or retained carriage.
2. A distinct tilt may improve projected fit, but must preserve uncertainty and margin rules. Check full package, fingers and wrist through the rotation sweep, not just endpoints or fingertips.
3. A rise-and-fixed-TCP-rotation approval does not authorize transfer, entry or opening. Before rotating after a rise, require fresh attachment within the remaining swept-clearance allowance; missing intermediate evidence defers rotation.
4. Revalidate object/hand motion and bowl stationarity after transport. Stale lip samples cannot authorize release.
5. Consider a short-drop release only when the measured opened-hand sweep, package gap, lip clearance and visible interior drop-height scope permit it. Derive open-hand bounds from measured robot geometry.
6. Use one finite opening operation with actual finger-separation/progress checks. Delivered open is not observed object release.
7. Withdraw only on a fresh nonhooking route. If measured material follows the withdrawing hand, investigate continued attachment; do not repeat opening blindly.
8. After hand separation, require fresh footprint containment, interior support, no rim bridging and no hand support. For a tilted object, support of the lower end and protrusion need their own justified relation checks; reduced projected width does not prove a viable cavity/support path.
9. Compare the same physical surface features across bounded actual settling steps. Stability allowance must include two-sample uncertainty and fit within containment slack. Count acknowledged native steps, not images or summary settling counts.

**Failure/stopping conditions:** Stop on slip, bowl motion, insufficient swept clearance, inadequate fit, uncertain release, rim bridging, outside placement, continued hand support or depleted effect-review resources. Do not regrasp or push under self-occlusion. Stage completion requires the final effect, not this authored plan.

**Evidence IDs:** E-M2, E-PLAN, E-RP, E-P, E-SUM; N-M07 through N-M10, N-J8 through N-J10, N-RT, N-SUM. The final containment-prefix narrative remained unexecuted because persistence failed.

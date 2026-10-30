---
name: libero-differential-retention
description: Test rigid attachment by comparing persistent surface landmarks with actual full hand motion and visible support separation.
---

# Differential retention with independent landmarks

**Status:** scene-specific. One measured lift established retention. Same-frame placement-entry remeasurement is not a second independent lift trial.

**Applicability:** A suspected rigid grasp with an observable textured surface and a locally reviewed safe test corridor.

**Inputs and frames/units:** Corresponding object points before and after motion in world meters; persistent physical identities and frame IDs; full actual TCP poses with xyzw quaternions; uncertainty allowances in meters; current visible finger relation, support gap, and disturbance assessment. Optional tracker measurements need identity, reference frame, residual, inliers, and support extent.

**Jev versus program:** Review identifies and reidentifies physical features and visible relations. The program validates correspondences, commands a bounded test, computes actual hand transforms, and evaluates effect margins. Jev delivers the test motion and keep command; it does not infer retention from closure or pose convergence.

## Procedure
1. After bounded closure, obtain a baseline before the test. Distinguish opposed fingers and support contact from lifted retention.
2. Use either a quality-checked surface tracker or at least three well-separated, distinguishable physical landmarks on the same rigid object. Preserve physical identities, not screen-relative labels. Matching label strings alone are insufficient.
3. For tracking, check current/reference frames, identity provenance, inlier count and fraction, residual, uncertainty floor, and spatial spread relative to noise. Validate the actual subset of shared features, not only the full patch. An identity registration at initialization is not evidence of future tracking quality.
4. Make one bounded lift large enough to distinguish attachment from measurement error, but entirely within the reviewed corridor. Use actual measured before/after hand states, not commanded displacement.
5. For each baseline point x0, predict its attached position using actual hand poses:
   - x_pred = R1 * transpose(R0) * (x0 - t0) + t1.
   Compare with the freshly observed corresponding x1 using a documented residual aggregate, such as the supplied attachment-error helper.
6. Require residual below an explicit allowance, substantial actual hand displacement, substantial observed object rise, visible retention and support separation, and no observed disturbance. A candidate tolerance used here was max(error_floor, 2 * (u0 + u1)); test displacement must remain meaningfully larger than that tolerance.
7. If tracking is unavailable, independently identified landmarks can still support the test. Keep tracker and landmark results separate. Do not silently choose a favorable test when reliable measurements conflict; investigate identity, correspondence, registration, or slip.

## What was observed
The accepted landmark test measured about 53.88 mm object rise versus 53.87 mm actual TCP rise, with about 0.425 mm attachment error against an 8 mm acceptance allowance. Fresh review showed retention and a clear table gap.

The baseline tracker was available, but the stored post-lift track was null and only the manual-landmark test was accepted. Its exact failure cause is unknown. A tracker-versus-landmark disagreement recovery and an optional exposure lift were authored, but no successful execution of those recovery branches is demonstrated.

**Failure/stopping conditions:** Block if no trustworthy correspondence survives, motion is too small relative to error, or separation is obscured. Do not repeat a completed test blindly. Observed slip, continuing support contact, disturbance, or excessive residual requires replanning. If a baseline is missing, a small observation-producing action is only a hypothesis: require separate clearance approval and a finite attempt limit.

**Evidence IDs:** E-A, E-RA, E-JA, E-M1, E-RP, defined in [the evidence ledger](../lessons/libero-evidence.md). Detailed effect records, rather than the supervisor's unsupported tracker-corroboration wording, identify the accepted measurement channel.

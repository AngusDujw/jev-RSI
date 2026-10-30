---
name: libero-differential-retention
description: Verify local retention using persistent material correspondences, actual full hand motion and visible support separation.
---

# Differential retention

## A. Actual hand/material co-motion test

**Status:** verified narrowly for two observed acquisition lifts with corresponding material measurements and visible support separation. This is not general grasp reliability or a full hidden-envelope reconstruction.

**Applicability:** A suspected rigid grasp with observable material features and a separately reviewed test corridor.

**Inputs and frames/units:** Corresponding baseline/current object points in world meters, physical identities and frame IDs; full actual TCP positions and tool-to-world xyzw quaternions; endpoint allowances in meters; visible retention, support gap and disturbance findings.

**Jev versus program:** Reviewer reidentifies physical features and visible relations. Program selects the finite test, validates correspondences, computes full actual hand motion and tests margins. Jev delivers the bounded motion and keep command, not attachment judgments.

1. Obtain a baseline after bounded closure and before the test. Table support at baseline is allowed; closed fingers do not establish retention.
2. Select distinguishable, sufficiently separated material features or a quality-checked surface track. Matching labels or projected historical pixels are not detections.
3. Choose a test large enough relative to measurement error, entirely within independently reviewed clearance.
4. For baseline point x0 and actual hand poses (R0,t0), (R1,t1), predict:
   - x_pred = R1 * transpose(R0) * (x0 - t0) + t1.
5. Compare fresh x1 with the prediction using a declared residual aggregate, such as the documented attachment-error helper. Use full lease endpoints, not target motion or the final update.
6. Require residual below an explicit allowance, substantial actual hand displacement and material rise relative to that allowance, visible finger retention and support separation, and no observed disturbance.
7. Keep independent channels separate. A reliable failed comparison requires investigation/replanning, not replacement with a favorable channel. An unavailable channel is not a contradiction.

Observed evidence, not defaults:
- Episode 0: about 53.88 mm object rise versus 53.87 mm TCP rise; about 0.425 mm attachment error against an 8 mm allowance.
- Episode 1: about 49.26 mm TCP rise and at least 49.24 mm landmark rise; about 0.052 mm manual and 0.212 mm shared-feature residuals against an 8 mm allowance.

**Failure/stopping conditions:** Block on missing identities, insufficient effect-to-error margin or obscured separation. Replan on reliable excessive residual, slip, continuing support or disturbance. Do not blindly repeat a completed lift. Optional sensing motion requires separate clearance and a finite attempt limit.

**Evidence IDs:** E-A, E-RA, E-JA, E-M1; N-M06, N-A, N-P, N-RA.

## B. Match the observability gate to the quantity tested

**Status:** scene-specific. A revised post-close baseline supported one nearly translational test; changed features, tracker support and baseline timing were not isolated experiments.

**Applicability:** Local displacement verification when full object orientation or perimeter estimation is unnecessary.

**Inputs and frames/units:** Identified endpoint points, endpoint uncertainty, feature diameter/spread in meters, actual relative hand rotation in radians, and separately measured planes if contact geometry needs them.

**Jev versus program:** Program distinguishes plane/orientation observability from displacement observability. Reviewer supplies genuinely different material details when necessary. Jev executes only the separately justified test.

Plane estimation needs two-dimensional support. A nearly translational co-motion test can instead use directly measured separated features with diameter large relative to uncertainty and a bounded actual hand rotation; it does not infer an object plane or complete orientation from a narrow patch.

Episode 1 used an observable-diameter gate relative to endpoint allowance, actual hand rotation below a small prescribed bound, and explicit hand/material rise multiples of the discrepancy allowance. Its allowance was formed from an error floor and twice the summed endpoint allowances. These thresholds must be chosen for the new measurement/action, not copied.

The earlier rejected print sets remained rejected as baselines; they were not failed attachment tests. Fresh post-close top anchors still underwent the stronger plane-support check.

**Failure/stopping conditions:** Do not relax the plane gate when a plane is actually needed, or extend the displacement-only argument to large rotation or full shape. Missing baseline permits a bounded different measurement, not repeated equivalent sampling.

**Evidence IDs:** N-J5, N-RB, N-M06, N-J6, N-A, N-RA.

## C. Compare shared tracker features at the actual test baseline

**Status:** scene-specific. One lift had accepted tracker/manual agreement. Episode 0's post-lift tracker was unavailable; its cause remains unknown.

**Applicability:** A surface tracker whose initialization frame may precede closure or the actual test baseline.

**Inputs and frames/units:** Patch identity and ROI/camera; creation/reference/current frames; directly measured reference/current feature pairs; inlier count/fraction, RMS and uncertainty floor in meters; baseline hand state and the actual shared subset.

**Jev versus program:** Reviewer confirms patch identity, not registration accuracy. Program validates tracking quality and uniquely joins feature identities across endpoints; Jev has no tracking role.

- Save actual current feature positions at the test baseline, not just initialization positions or a transform translation column.
- After motion, intersect unique persistent reference identities and compare baseline-current with post-test-current coordinates.
- Validate the shared subset's extent and quality, not merely the full patch. New post-test features cannot substitute for missing baseline measurements.
- Coordinate matching used to look up frozen reference IDs is not a claim of equal sensing precision.
- Retain uncertainty floors even when registration RMS is tiny. Initialization identity registration is not future tracking evidence.
- Unknown tracking supplies no extrapolated pose; do not requery the same failed tracker indefinitely at an unchanged frame.

Episode 1 initialized before closure but tested from a post-close baseline. Thirty-two shared measured features supported the accepted comparison. Its reported 58 current inliers were not all automatically baseline correspondences. Nearly unchanged wrist pixels were corroborated by current depth/world motion and an external support-gap view.

**Failure/stopping conditions:** Block on wrong identity/frame, inadequate unique shared support or excessive uncertainty. Reliable tracker/manual conflict requires replanning; conflict recovery and optional exposure branches were authored but not demonstrated.

**Evidence IDs:** E-A, E-RA, E-M1; N-M06, N-A, N-RA. The omitted full N baseline is not reconstructed from the sampled effect arrays.

---
name: libero-differential-retention
description: Compare physical material correspondences with actual hand motion while preserving partial evidence and independent failures.
---

# Differential retention

For every finding, **inputs/frames** are physical feature identities/descriptions, baseline/current world-meter points with camera/frame provenance, full TCP positions and tool-to-world xyzw poses, uncertainty allowances, actual native steps and visible retention/support/disturbance relations. **Responsibilities:** reviewer reidentifies material/relations; program validates correspondences and computes effects; Jev delivers a separately reviewed finite test, not attachment judgments.

## A. Actual hand/material co-motion

**Status:** verified narrowly for two earlier accepted lifts with correspondence tests and support separation, not general grasp reliability.
**Applicability:** Suspected rigid grasp with observable material and independently reviewed test clearance.

Take baseline after bounded closing progress and before testing; baseline table support is allowed. Choose identifiable separated features, not historical pixels or matching labels alone. Size displacement relative to endpoint uncertainty within reviewed clearance, including tolerance and possible gripper evolution.

For point x0 and actual hand poses (R0,t0), (R1,t1):
x_pred = R1 * transpose(R0) * (x0-t0) + t1.
Compare fresh x1 using a declared residual aggregate, such as the documented attachment-error helper. Use whole-lease endpoints. Require low residual, substantial actual hand/material rise, bounded rotation/lateral motion where needed, visible retention and support separation. Assess disturbance separately.

E reported about 0.425 mm residual; N about 0.052 mm manual and 0.212 mm shared-feature residuals, each against historical 8 mm allowances. These are observations, not defaults. Two channels on one lift are not two trials.

**Stop:** absent identities, insufficient effect/error separation or obscured support relation blocks acceptance. Reliable residual failure, slip or disturbance requires replanning, not favorable-channel substitution. Missing evidence allows bounded different sensing, not a repeat lift.
**Evidence IDs:** E-A, E-RA, E-JA, E-M1; N-M06, N-A, N-P, N-RA.

## B. Match observability to the quantity

**Status:** scene-specific; changed features, tracker support and post-close timing were not isolated experiments.
**Applicability:** Nearly translational displacement tests that do not require complete plane/orientation recovery.
**Additional inputs:** feature diameter/spread and actual relative rotation.

A plane needs two-dimensional support. A displacement test can use directly measured separated features with diameter adequate relative to uncertainty and bounded actual rotation; this does not reconstruct orientation or hidden shape. N used uncertainty-relative spread/rise gates and an allowance floor plus summed endpoint allowances. Earlier rejected print sets remained rejected baselines, not failed attachment tests.
**Stop:** do not relax the plane gate when a plane is needed or extend translation-only reasoning to large rotation. Bound alternate selections.
**Evidence IDs:** N-J5, N-RB, N-M06, N-J6, N-A.

## C. Tracker baseline is not initialization

**Status:** scene-specific; one N lift had accepted tracker/manual agreement. E post-lift tracker unavailability has unknown cause; T has no accepted post-lift tracker result.
**Applicability:** Tracking initialized before the actual test baseline.
**Additional inputs:** ROI/identity, initialization/reference/current frames, reference-current pairs, inlier support/fraction, RMS and uncertainty floor in meters.

Save actual current points at test baseline. Join unique persistent reference identities across endpoints and validate the shared subset's extent/quality. New features cannot replace missing baseline measurements. Reference-coordinate lookup precision is not sensing precision. Keep uncertainty floors despite tiny RMS; same-frame identity registration is not differential evidence. N used 32 shared features, not all 58 current inliers.
**Stop:** wrong identity/frame, inadequate shared support or uncertainty blocks that channel. Unknown tracking supplies no extrapolated pose; avoid unchanged-frame requery loops. Reliable channel conflicts require replanning.
**Evidence IDs:** E-A, E-RA; N-M06, N-A, N-RA; T-C, T-A, T-M08.

## D. Positive co-motion can coexist with disturbance

**Status:** scene-specific partial effect, not a third accepted acquisition stage.
**Applicability:** Independent positive observations survive another failed stage predicate.
**Additional inputs:** exact review fields, source execution order, returned versus persisted evidence.

T's probe had fresh current-contact/corridor review and a full-finger/table check; it did not repair rejected hidden-side coverage. Changed models/allowances do not establish that bypassing uncertain contact is generally safe.

The supervisor reported about 99.08 mm TCP rise and 99.17-99.24 mm material rise, with retained=yes and support_separated=yes. disturbance=yes concerned bowl movement relative to plate/bottle; magnitude and cause were not measured. Full source shows this guard stopped before attachment(), post-lift tracking/manual residual, bowl fit or candidate selection. Final material world arrays are not supplied for independent recomputation.

Physical descriptions appeared in review prose, but persisted landmark_ids contained labels only. A bounded ID-to-description mapping is a proposed safeguard, not an exercised repair.

**Stop:** preserve actual lifted state/command; reconcile target movement before dependent action. Do not infer slipped grasp, undisturbed stage success, tracker corroboration or completed fit. Do not repeat closing/lift to recover evidence.
**Evidence IDs:** T-M08, T-J8, T-P, T-A, T-RBASE, T-RLIFT, T-CP.

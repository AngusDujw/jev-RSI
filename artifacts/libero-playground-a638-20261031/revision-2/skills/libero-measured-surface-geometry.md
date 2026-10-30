---
name: libero-measured-surface-geometry
description: Build conditional geometry from depth-safe anchors and visible boundaries with explicit uncertainty, camera agreement and freshness.
---

# Surface anchors and visible boundaries

**Status:** scene-specific. Repeated local top/table fits and validations were usable; this does not calibrate uncertainty or reveal hidden surfaces.

**Applicability:** A rigid visibly planar face above a locally planar support, with calibrated RGB-D views and sufficient visible extent.

**Inputs and frames/units:** Named world-meter samples with camera, pixel, frame, source and error metadata; visible boundary pixels in physical order; calibrated rays; current identity; tool geometry for clearance. Plane normals and coefficient normalization must be documented.

**Jev versus program:** Reviewer identifies physical surfaces, landmarks and scoped routes. Program checks sample validity, fits geometry, projects rays and propagates allowances. Jev is used only for a separately approved observation-producing movement.

## Procedure
1. Separate depth sampling from boundary localization. Use inset face/support patches, not mixed-depth edges, shadows or neighboring surfaces.
2. Check membership, measurement errors, finite coordinates and frame before fitting. Retain valid partial measurements and explicit gaps.
3. Require adequate two-dimensional spread relative to noise for plane estimation and extrapolation. Tiny residuals or three nearly collinear points do not establish a useful plane.
4. Fit each camera separately before comparing views. Check disagreement over the relevant surface region, pixel scale, slope and residual. Do not pool inconsistent views to hide bias.
5. A working allowance may use a floor, scaled plane residuals, metric pixel uncertainty and cross-view discrepancy. This is a design allowance, not a calibrated confidence interval. Boundary/model uncertainty can exceed plane-fit residual.
6. Intersect rays through genuinely visible boundary pixels with the supported plane. Do not use boundary pixels as depth-safe patches or invent hidden corners.
7. Check rectangle side lengths, opposite-side agreement and orthogonality before deriving center or closing direction. One exposed side does not establish a hidden opposite face.
8. Preserve original shape measurement, later local-plane measurement and validation frames separately. Support-derived underside/thickness remains conditional after lifting.
9. Refresh affected geometry after hand/contact motion. A copied footprint with a new validation frame is not a newly measured envelope.
10. Replace inadequate samples with genuinely different inset patches or another view within a finite budget. Same pixels after motion are not persistent physical identities.

## Evidence boundary
Episode 1's separate-camera comparison reported about 0.895 mm maximum disagreement without pooling. Later local geometry retained a 2 mm working floor. These are observed design choices, not sensor calibration or defaults. Initial poor support and later contact-interval rejections remain valid failures even though acquisition eventually succeeded.

**Failure/stopping conditions:** Block on invalid depth, inadequate spread, inconsistent cameras, ambiguous identity, unsupported shape or uncertainty exceeding available margins. Observed object/support movement invalidates stationary dependencies. Approval for sensing at height does not authorize descent or transport.

**Evidence IDs:** E-G, E-RG, E-M0, E-M1, E-P; N-G, N-J0, N-J2, N-J4, N-J5, N-RA. Lip semantic classification and its separate boundary fit are covered in the contained-release skill.

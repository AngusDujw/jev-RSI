---
name: libero-measured-surface-geometry
description: Build conditional geometry from depth-safe surface anchors and visible boundaries with explicit freshness and uncertainty.
---

# Surface anchors and visible boundaries

**Status:** scene-specific. Complementary top/table measurements and a later pregrasp validation were usable in this scene. This does not calibrate their uncertainty or validate hidden surfaces.

**Applicability:** A rigid, visibly planar object face above a locally planar support, with calibrated RGB-D cameras and sufficient visible surface extent.

**Inputs and frames/units:** Named surface samples in world meters with camera, pixel, frame, and measurement-error metadata; visible boundary pixels in cyclic physical order; camera rays; current object identity; tool geometry when evaluating clearance. Plane coefficients require a documented normalized normal convention.

**Jev versus program:** A visual reviewer identifies the object, visible surface, physical landmark identities, and scoped route relations. The program rejects invalid samples, fits and validates geometry, projects rays, and propagates allowances. Jev is used only if a separately approved observation-producing movement is needed.

## Procedure
1. Separate depth sampling from boundary localization. Choose inset depth patches on the face and exposed support, not mixed-depth edges, shadows, plates, or adjacent objects.
2. Fit planes only from sufficient, well-spread samples. Check residual, two-dimensional support, slope, and model applicability. Three nearly collinear points are not useful plane support.
3. A working allowance can take the form u = max(u_floor, k * top_rms, k * support_rms). It is a conservative design allowance, not a calibrated confidence bound. Tiny fit residuals do not eliminate boundary, calibration, depth, or model errors.
4. Intersect calibrated rays through genuinely visible boundary pixels with the fitted face plane. Do not treat boundary pixels themselves as reliable depth patches or invent occluded corners.
5. Validate the rectangle model with side lengths, opposite-side agreement, and approximate orthogonality before deriving a center or closing direction.
6. Complementary side samples can support a visible side-height interpretation. Samples on one exposed end face do not establish its hidden opposing face.
7. After hand motion, reobserve identity, stationarity, local route, and relevant planes. Store original shape measurement frame, latest validation frame, and actual contact-check frame separately.
8. Replace failed samples with different inset patches or another view within a finite review budget. Combine measurements only when their coordinate transforms and unchanged physical state are established. Never reuse camera pixels after motion as if their physical identity persisted.

**Failure/stopping conditions:** Block on inadequate spatial support, invalid depth, ambiguous identity, insufficient visible boundary, incompatible model, or uncertainty exceeding feasible margins. Observed object/support movement invalidates the stationary model. A safe high route does not authorize descent to contact or later transport.

**Evidence IDs:** E-G, E-RG, E-M0, E-M1, defined in [the evidence ledger](../lessons/libero-evidence.md). Repeated top/table observations supported the local model. E-P and E-M2 illustrate the need to keep support-derived hidden-envelope assumptions and original boundary provenance explicit rather than calling them fresh measurements.

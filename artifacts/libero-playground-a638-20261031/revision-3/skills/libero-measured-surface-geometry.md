---
name: libero-measured-surface-geometry
description: Build conditional geometry from depth-safe anchors and observed boundaries without inventing hidden support.
---

# Measured surface geometry

**Status:** scene-specific. Repeated local fits were usable; uncertainty calibration and hidden-surface recovery are not established.

**Applicability:** Rigid visibly planar faces and local planar support with calibrated RGB-D views and adequate extent.

**Inputs and frames/units:** Named world-meter samples with camera, pixel, frame, source and errors; physically ordered visible boundary pixels; calibrated rays; current identity and tool geometry. Document plane normalization and normal orientation.

**Jev versus program:** Reviewer selects semantic surfaces/features and local routes. Program validates, fits, projects and propagates allowances. Jev performs only separately approved sensing motion.

1. Separate inset depth-safe patches from boundary localization. Avoid mixed-depth edges, shadows and neighboring surfaces.
2. Validate membership, errors, finiteness and frames before fitting. Preserve valid partial data and explicit gaps.
3. Require two-dimensional spread relative to uncertainty and intended extrapolation. Tiny RMS or near-collinear samples do not establish a useful plane.
4. Fit cameras separately before comparing slope, relevant-region disagreement and metric pixel scale. Do not pool inconsistent views to hide bias.
5. Working allowances may include floors, scaled residuals, pixel localization and cross-view disagreement. They are design bounds, not calibrated confidence; boundary/model error may dominate RMS.
6. Project calibrated rays through actually visible boundaries onto the supported plane. Do not treat edge pixels as depth-safe patches or invent hidden corners.
7. Check rectangle side lengths, opposite-side agreement and orthogonality. A visible side does not measure its hidden opposite.
8. Check coverage where the model will be used, not just direction. Differentiate original shape, later local-plane measurements and validation frames.
9. Refresh affected geometry after contact/motion. Copied corners are not newly measured envelopes. Support-derived thickness/underside remains conditional after lifting.
10. Replace inadequate samples with genuinely different patches/views within a finite budget. Reused pixels after motion are not persistent material identities.

N's separate-camera comparison reported about 0.895 mm maximum disagreement without pooling. T retained about 1.683 mm contact allowance despite much smaller fit residuals. Neither is a default calibration. T's later probe used a different model/allowance; it does not validate reducing uncertainty to rescue rejected contact geometry. An authored obliquity-aware replacement failed before its review and remains untested.

**Failure/stopping conditions:** Invalid depth, insufficient spread/coverage, camera conflict, ambiguous identity or uncertainty exceeding margins blocks use. Observed object/support motion invalidates affected dependencies. Clearance for sensing at height is not descent/transport permission.

**Evidence IDs:** E-G, E-RG, E-M0, E-M1; N-G, N-J0, N-J2, N-J4, N-J5, N-RA; T-G, T-C, T-SIDE, T-M07, T-J7, T-M08.

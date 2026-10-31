---
name: libero-pad-band-pinch
description: Check thin-object pinches using full-finger clearance, robust overlap, supported tolerance and observed contact coverage.
---

# Robust pinch geometry

For both findings, **inputs/frames** are current top/support planes and conditional footprint in world meters; tool-frame pad center/extents and full finger envelope in meters; intended/actual xyzw poses; sensing, boundary, centering and angular allowances; required clearance/overlap and documented minimum tolerance. **Responsibilities:** program computes geometry; reviewer confirms identities, jaw/side premises and scoped sweeps; Jev delivers approved targets/commands, not feasibility judgments.

## A. Common pad band and action reserve

**Status:** scene-specific. Revised E/N candidates led to accepted retention, but geometry, sensing and controls changed together. T adds a rejected post-close continuation.
**Applicability:** Rigid thin objects on measured support with opposed near-top-down jaws; not established for deformable objects or hidden support.

Consider leveling/short-dimension closing only within reviewed sweeps. Evaluate transformed geometry, not yaw alone. For pad XY c and world-rotated finger vertices v relative to pad center:
- z_floor = max_v(table_z(c + v_xy) - v_z) + clearance + u.
- Construct common pad band [l,h] from transformed vertical pad edges: largest lower endpoint, smallest upper endpoint. Reject empty intersection.
- For pad height z and position tolerance e, require z-e >= z_floor and:
  min(z+h-e, top_min-u) - max(z+l+e, table_z(c)+u) >= overlap_required.

Include slope, angular and centering reserves. A raw feasible interval must contain the entire +/-e band, not merely positive slack. Never clamp an infeasible tolerance upward. Intersect intended/actual orientation constraints after alignment; refresh at standoff and recompute after descent and every closing delivery.

Present measured overlap and reserve for another action differ. With justified pose-error gain g, remaining margin must cover g*e plus other reserves. T's post-close overlap was about 3.318 mm against a 3 mm requirement: 0.318 mm reserve could not cover about 0.509 mm required pose reserve. Passing pose drift/reached did not clear this geometry gate. N likewise rejected positive intervals too narrow for supported +/- tolerance.

**Stop:** invalid planes, ambiguous bracketing, unsupported precision, drift, failed actual margins or exhausted closing deliveries. Preserve command without automatic reopening. Aperture progress/stabilization is not retention. Reject the candidate, not the acquisition objective.
**Evidence IDs:** E-J0, E-G, E-M0, E-M1, E-A; N-J0, N-J2, N-G, N-J5, N-J6; T-J2 through T-J4, T-C.

## B. Side-local overlap does not shrink collision bounds

**Status:** scene-specific. One N shifted strip was executed and later retained; T's later strip support failed.
**Applicability:** Observed straight opposed sides and parallel uniform inward pads, with separately reviewed offsets/sweeps.
**Additional inputs:** offset parameterized by measured object length, visible side segments, sweep membership uncertainty and angular bound theta in radians, all transformed to the evaluation frame.

Restrict only the overlap calculation to justified side crossings; retain the full finger collision envelope. Expand required strip membership for localization, centering, footprint and rotation uncertainty. Check direction and coverage separately through relevant aperture/sweep. Hidden continuation needs explicit justified bounds; it is not observation.

For vector v and unit projection normal n, v_n=dot(n,v), v_t=v-v_n*n, a directional small-angle reserve is:
norm(v_t)*sin(theta) + abs(v_n)*(1-cos(theta)).
Retain other reserves and recompute at actual shifted/contact pose. N's narrow forecast slack was model slack, not sensor accuracy or isolated proof of this bound's benefit.

T's preserved diagnostic had small slopes within its direction bound, but continuation fractions about 1.20/1.22 exceeded its declared 1.0 limit. This identifies recorded coverage failure, not failure of every possible anchor. The closer-anchor repair delivered no valid replacement review.

**Stop:** unsupported jaw premise, direction, coverage or uncertainty. Obtain genuinely different visible anchors if possible; never invent hidden extensions, revive the rejected full-band candidate or lower margins. The later probe did not validate the rejected strip.
**Evidence IDs:** N-M03 through N-M06, N-G acquire.contact/retain.geometry, N-J3 through N-J6, N-RA; T-J6, T-J7, T-SIDE, T-RSIDE, T-M07.

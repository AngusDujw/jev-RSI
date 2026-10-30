---
name: libero-pad-band-pinch
description: Evaluate thin-object pinches with transformed finger clearance, pad overlap and supported precision before bounded contact.
---

# Thin-object pinch with a common pad band

## A. Robust interval, not pad-center height alone

**Status:** scene-specific. Revised candidates led to retention in both episodes, but measurements, candidate geometry and control settings changed together. Individual causal contributions are not isolated.

**Applicability:** A rigid thin object on measured support, accessible to an opposed near-top-down pinch with known finger and pad geometry. Not established for deformable objects or hidden support.

**Inputs and frames/units:** Current top/support planes and conditional footprint in world meters; tool-frame pad center, pad extents and full finger envelope in meters; intended and actual xyzw orientations; sensing, boundary and angular allowances; required clearance/overlap and API minimum position tolerance.

**Jev versus program:** Program constructs and checks geometry. Reviewer confirms identity, open-finger bracketing and only the relevant corridor. Jev follows the checked target and gripper request, not the feasibility calculation.

1. Reject a failed candidate locally, not the entire acquisition goal. Obtain new information or a genuinely different candidate without lowering justified margins.
2. If the route permits, consider leveling a near-top-down pad and aligning closing with the short dimension. Evaluate transformed geometry, not yaw alone.
3. For pad XY c and full finger vertices v expressed relative to pad center and rotated to world, compute:
   - z_floor = max_v(table_z(c + v_xy) - v_z) + clearance + u.
4. Construct common pad band [l,h] relative to pad center. Transform each relevant vertical pad edge, select its lower/upper world endpoints, then take the largest lower and smallest upper endpoint. Reject an empty band.
5. For pad height z and position tolerance e, require:
   - z - e >= z_floor.
   - min(z + h - e, top_min - u) - max(z + l + e, table_z(c) + u) >= overlap_required.
   Include applicable angular, horizontal-centering and surface-slope reserves.
6. If the robust raw height interval is [L,U], it must contain the full +/-e band plus any remaining reserve. Positive slack alone is insufficient. Require supported e; never clamp a rejected sub-minimum tolerance upward.
7. Intersect intended/actual orientation constraints after high alignment. Refresh geometry at standoff, descend once, and recompute actual clearance and overlap before, during and after bounded closure.
8. Observe actual aperture progress and stabilization within a finite delivery count. Stabilization verifies closing progress, not retention; require a separate lift test.

Episode 0 rejected its initial center-height candidate before action. Its revision used about 1.89 mm slack and 0.63 mm position tolerance; actual checks reported about 7.46 mm clearance and 3.03 mm overlap. Episode 1 rejected intervals near 0.76 mm because they could not contain +/-0.5 mm supported tolerance, even though nominal overlap passed.

**Failure/stopping conditions:** Block on invalid planes, ambiguous bracketing, no supported interval or unreviewed orientation changes. Stop on insufficient actual margins, stalled contact or closure-limit exhaustion; preserve the actual command, without automatic reopening. Passing geometry permits bounded contact, not a friction or attachment claim.

**Evidence IDs:** E-J0, E-G, E-M0, E-M1, E-A; N-J0, N-J2, N-G, N-J5, N-J6, N-P.

## B. Distinct side-local strip with directional angular bounds

**Status:** scene-specific. One shifted-strip candidate was executed and later retained. It does not prove that every narrow forecast interval is physically robust.

**Applicability:** Known parallel inward jaws with vertically uniform pads, visible package-side crossings and an independently reviewed standoff shift.

**Inputs and frames/units:** The inputs above, plus longitudinal candidate offset parameterized by measured object length, observed side coordinates, pad-sweep membership uncertainty, and tolerated small rotation theta in radians.

**Jev versus program:** Reviewer checks the jaw premise and offset corridor. Program retains full-finger clearance while restricting only the overlap calculation to the justified package-side portion of the closing sweep. Jev executes the approved offset/contact segments.

- Do not narrow the collision envelope when narrowing contact overlap.
- Include side-location, centering, footprint and rotation uncertainty in the contact strip.
- A direction-specific projection bound can be less conservative than a full isotropic radius bound without reducing physical margins. For a world vector v and unit projection normal n, let v_n = dot(n,v) and v_t = v - v_n*n. For a small angular allowance theta, use:
  - projection reserve <= norm(v_t)*sin(theta) + abs(v_n)*(1-cos(theta)).
  Apply the bound in the relevant projection frame and retain other geometric reserves.
- Recompute after the shift and at actual contact. Do not revive an earlier rejected full-band candidate under a new name.

The forecast interval was about 1.10 mm at +/-0.5 mm tolerance, leaving only about 0.05 mm per-side residual reserve. That is model slack, not sensing accuracy. Actual contact later reported about 5.48 mm clearance and 3.11 mm overlap; post-close checks reported about 5.61 mm and 3.21 mm.

**Failure/stopping conditions:** Reject if jaw/sweep assumptions, side crossings or uncertainty support fail. No positive forecast authorizes unreviewed motion or a smaller safety requirement.

**Evidence IDs:** N-M03 through N-M06, N-G acquire.contact and retain.geometry, N-J3 through N-J6, N-RB, N-RA.

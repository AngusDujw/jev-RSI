---
name: libero-pad-band-pinch
description: Evaluate a thin-object pinch using transformed finger clearance and common pad overlap instead of pad-center height alone.
---

# Thin-object pinch with a common pad band

**Status:** scene-specific. One revised candidate led to retained acquisition. Leveling, new measurements, pad-band reasoning, and tighter control tolerance changed together, so no individual change has an isolated success claim.

**Applicability:** A rigid thin object on a measured support, accessible to a near-top-down opposed pinch, with known pad and finger extents. Not established for deformable packages, hidden support geometry, or arbitrary wrist orientations.

**Inputs and frames/units:** Fresh top/support planes and validated footprint in world meters; tool-frame finger bounds, pad center, and pad extents in meters; intended and actual xyzw tool quaternions; required support clearance, overlap, and uncertainty in meters; API minimum position tolerance.

**Jev versus program:** The program constructs and checks the candidate, including rotations and overlap intervals. Visual review confirms identity, open-finger bracketing, and the local descent corridor. Jev follows the checked pose and gripper requests, not the geometric feasibility test.

## Candidate construction
1. Treat failure of one geometric test as local rejection, not proof that the stage is impossible. Obtain complementary measurements without reducing justified margins.
2. If the tool is already near top-down and the route permits it, consider leveling the pad and aligning its closing direction with the object's short dimension. Check the transformed geometry, not just yaw.
3. Express each finger-envelope vertex relative to the pad center and rotate it into world coordinates. For intended pad XY c and world-relative finger vertices v, compute a floor:
   - z_floor = max_v(table_z(c + v_xy) - v_z) + clearance + u.
4. Compute a conservative common vertical pad band [l, h] relative to pad center. For the rectangular-pad construction used here, transform each vertical pad edge; l is the largest lower endpoint and h the smallest upper endpoint. Reject an empty band. Intersect constraints from the intended and actual orientations after high alignment.
5. For proposed pad height z and position tolerance e, require both:
   - z - e >= z_floor.
   - min(z + h - e, top_min - u) - max(z + l + e, table_z(c) + u) >= overlap_required.
   This tests side-contact overlap without demanding that the pad center itself lie below the top.
6. A preliminary upper bound is z_max = top_min - u - l - overlap_required. Let slack = z_max - z_floor. Choose e no larger than a bounded fraction of positive slack, then select an interior height and verify the full overlap inequality. If the required e is below the API minimum, reject instead of loosening margins.
7. Refit local geometry at standoff, descend once, and recompute actual projected finger clearance and pad overlap before closing. Recheck during bounded close-hold deliveries because actual pose and gripper geometry can change.

## Observed scale, not defaults
The rejected center-height candidate issued no physical actions. The revision retained a 6 mm finger/support margin with a 2 mm working allowance and required 2.5 mm overlap. Its measured slack was about 1.89 mm, leading to about 0.63 mm position tolerance. The recorded actual check gave about 7.46 mm finger clearance and 3.03 mm overlap. These are evidence of this candidate, not constants for another scene.

**Failure/stopping conditions:** Block on invalid planes, ambiguous bracketing, unsupported leveling, no robust interval, insufficient actual clearance/overlap, or stalled descent. Do not force a fit by reducing margins. A passed geometry check permits only bounded contact and an independent retention test; it does not establish friction or attachment. Preserve the actual gripper state if closing checks fail.

**Evidence IDs:** E-J0, E-G, E-M0, E-M1, E-A, defined in [the evidence ledger](../lessons/libero-evidence.md). The initial rejection remains part of the finding, and the later acquisition result does not establish global grasp feasibility.

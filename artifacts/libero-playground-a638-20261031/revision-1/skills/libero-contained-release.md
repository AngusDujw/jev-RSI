---
name: libero-contained-release
description: Design a measured container release with explicit opening clearance and post-release support verification.
---

# Measured contained-release design

**Status:** hypothesis for placement. Only its entry review and preliminary upward hand move were exercised; no opening fit, transit, release, withdrawal, or settled-placement effect is demonstrated.

**Applicability:** A retained rigid object above a container with a sufficiently visible opening. The circular-opening version applies only when current observations support a near-horizontal circular inner lip.

**Inputs and frames/units:** Fresh inner-lip depth anchors and visible boundary pixels with camera/frame IDs; observed interior support; conditional object envelope and thickness in world meters; current attachment measurements; current closed and opened finger envelopes from robot geometry; pose tolerances and uncertainty allowances in meters. Historical support-derived underside bounds are not current hidden-surface measurements.

**Jev versus program:** Review identifies the inner lip, visible support relations, and scoped clear routes. The program fits geometry, checks attachment, computes margins and bounded segments, and evaluates release effects. Jev delivers these segments and gripper requests, not containment or support judgments.

## Proposed design
1. Validate attachment and any carried shape model. If a local upward move is needed for clearance or visibility, authorize only that corridor, then obtain fresh post-move measurements. A reached upward pose does not itself validate continued attachment or improved visibility.
2. Fit a lip plane from spread, depth-safe anchors. Project rays through visible inner-boundary pixels onto that plane. Do not use the outer silhouette or invent occluded arcs.
3. Fit a circle only with adequate observed arc coverage and acceptable plane/circle residuals. Otherwise choose a justified different model or stop.
4. Evaluate the full transformed object envelope, not just its center. For circle center c and radius r, a conservative current margin is:
   - margin = r - max_i(norm(envelope_i_xy - c)) - u_object - u_opening.
   Leave additional safety and pose tolerance inside this margin. Also check object and whole-hand vertical clearance and the observed swept corridor.
5. Revalidate attachment and bowl stationarity after transport. Permit only a bounded measured correction when intrinsic fit still allows it. Stale rim samples cannot authorize release.
6. Consider a short-drop release above the opening when opened fingers cannot safely enter. Derive opened-hand bounds from measured robot geometry, not fixed constants. Check the actual package gap, opening sweep, lip clearance, and visible interior drop-height scope immediately before opening.
7. Verify actual finger separation after bounded opening. Withdraw only on a freshly reviewed clear route; an unknown release under self-occlusion is not permission to regrasp or push.
8. After withdrawal, combine fresh footprint containment and lower-envelope geometry with visible interior support, no rim bridging, and hand separation. Compare the same physical surface landmarks across a bounded number of actual settling steps. Use acknowledged native-step differences, not image count alone.

**Failure/stopping conditions:** Block on unknown opening/support, insufficient arc coverage, large uncertainty, missing attachment evidence, or exhausted measurement budget. Replan on slip, bowl movement, inadequate fit, rim contact/bridging, outside placement, or continued hand support. Do not repeat opening as a generic recovery. Whole-task completion requires the final effect, not merely this authored plan.

**Evidence IDs:** E-M2 and E-PLAN supply the design only; IDs are defined in [the evidence ledger](../lessons/libero-evidence.md). E-RP and E-P support the limited entry/upward-action prefix. E-SUM records interruption, and no placement result or measured final containment is supplied.

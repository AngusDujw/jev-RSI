# r005 development review (outer agent only)

Status: candidate, not promoted. Do not load this review as model knowledge.
The immutable model projection remains reorientation_tracking_r005.json.

## Controlled evidence

m used zero API calls: one right pitch-negative rotation of 0.10 rad, followed
by a 20 mm negative-Y translation. The translation achieved 19.439 mm along Y,
with 0.577 mm endpoint error. This establishes one local robot-response example,
not policy selection or a grasp. j provides the nontracking counterexample.

## All bounded policy checks

- n layout0, old feedback: six answers / 30 native steps. After negative-Y
  nontracking, the policy selected pitch-negative; a later negative-Z move
  achieved 19.502 mm with 0.503 mm endpoint error. It ended with two holds.
- n layout1, old feedback: two answers / six steps. Two partial refusals,
  no selected reorientation or recovery.
- p layout1, selected-vs-dispatched feedback: six answers / 29 steps.
  Initial bilateral negative-Z did not track (about 18.577 mm error). Right
  pitch-negative then tracked; subsequent negative-Y achieved 19.438 mm with
  0.579 mm error. The policy next opened, closed, then selected negative-Z.
  Only four of five waypoints were dispatched. Actual Z displacement was
  -27.203 mm, compared with the last dispatched target of -16 mm. The final
  waypoint was refused. There was no verified object retention or lift.

These are three independent development attempts under two feedback conditions,
not paired trials or a success-rate estimate. All were stopped early. No full
native failure/success denominator is claimed. A local recovery does not show
that enclosure, closure, lifting, or transport is reliable.

## Feedback interpretation

Let x_goal be the selected full endpoint, x_sent the last Cartesian waypoint
actually dispatched, and x_measured the measured TCP. Keep both norms:

    e_goal = ||x_measured - x_goal||
    e_sent = ||x_measured - x_sent||

Neither norm is guaranteed to exceed the other. The o zero-API interface check
had e_goal=11.638 mm and e_sent=1.928 mm after partial dispatch. The final p move
had e_goal=7.420 mm and e_sent=11.344 mm because motion overshot the dispatched
target. A smaller full-goal residual is not proof of better execution tracking.
Zero-dispatch feedback was covered offline, not in the real o probe.

All model-visible p histories before its final action were full dispatches.
The last partial feedback was logged after the final answer, then the attempt
was stopped. Thus p does not test how the policy responds to unequal goal/sent
feedback, and does not establish a causal policy benefit from the new field.

## Next evidence boundary

Review the accepted targets and measured trajectory around p closure/descent,
plus raw head/wrist images. Separate visible enclosure uncertainty from renewed
execution mismatch. Do not infer a contact cause, successful capture, or a useful
route from these data alone. No new synonym prompts or identical failed resets.
Keep the candidate unpromoted until independent useful task progress is verified.

Sources: remote n/all-request-audit.json, n/second-review-decision.json,
o/interface-audit.json, p/all-input-audit.json, p/second-review-decision.json,
and their original interaction / waypoint / native-step ledgers.

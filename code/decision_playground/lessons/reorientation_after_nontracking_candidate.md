# Candidate lesson: reorient after a translation does not track

Status: one controlled robot-execution example; not a validated grasp skill.

## Evidence

Source: company-server-2-ykj, playground-ik-z-diagnostic-20261022e.
This was an outer-agent controlled diagnostic with zero model calls. It is not
evidence that a Decisions policy selected these actions or completed the task.

At the initial robot configuration, a right-arm negative world-Z target 20 mm
below the configured TCP received IK Success throughout 25 native steps. The
actual TCP descended only about 1.2 mm and retained about 19.0 mm target error.
Retaining the identical target for longer did not remove that error.

The solver's target joints independently reconstructed the requested Link6 pose
to less than 0.0002 mm through the public URDF. Actual joint3 stalled near
-0.0361 rad while the target was about -0.0744 rad. The USD and URDF joint3 limits
both permit approximately +/-10 rad. Thus this example does not establish a
joint-limit mismatch, a singularity, collision, or contact as its cause.

A subsequent negative world-X rotation of 0.10 rad about the configured TCP
tracked. A new 20 mm downward request at that changed orientation then descended
about 19.998 mm, with about 0.074 mm target-position error. This establishes one
observed recovery condition for tracking, not a grasp or a universal direction.

## Candidate procedure

Prerequisites: a translation's measured effect remains inconsistent with the
requested motion; no current evidence establishes a grasp or calls for release.

1. Treat the measured current pose as the current state. An IK acceptance or
   increasing step counter does not establish that the motion was achieved.
2. Avoid assuming that further waiting or repeating the blocked translation will
   fix a persistent mismatch.
3. Use current images and robot configuration to consider a small reorientation
   that preserves a useful view and approach. Derive its axis and sign from the
   current situation; the historical rotation is not a route to replay.
4. Compare its measured effect with the intended effect, then test the needed
   translation again from the new measured pose.
5. Retain this procedure only if actual tracking improves without losing useful
   visual evidence. Grasp enclosure and object retention require separate checks.

## Validation still required

Test whether the model can identify nontracking, select a suitable reorientation,
and recover useful motion on independent development layouts. A rotation choice
alone is insufficient. Do not promote this candidate into a validated Skill from
the source diagnostic, and do not mix its expanded budget with official results.

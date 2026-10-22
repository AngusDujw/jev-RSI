# Candidate lesson: distinguish holding from corrective progress

Status: development candidate, not a validated grasp skill.

## Evidence and limits

Source: company-server-2-ykj, playground-20261022c, layout0, revision r000,
decisions 0-5, native steps 0-30. This is one development attempt, not held-out
evidence. Two reviewed segments show the intended object still on the support
surface, outside the gripping faces. No stable grasp is demonstrated.

The first right-arm command requested a 20 mm negative world-Y translation with
orientation held. Measured TCP displacement was approximately
[-0.333, -16.935, -12.941] mm, leaving 13.303 mm target-position error and 3.547
degrees orientation error. Subsequent holds changed TCP position by less than
0.074 mm per five-step segment. A later negative world-Z request produced no
measured TCP motion. The precise IK-versus-tracking cause is not yet established.

These observations establish neither a target location nor a transferable
motion direction. They only show that issued commands need measured and visual
verification, and that holding the newly measured pose does not correct a prior
tracking error. Do not replay coordinates, directions, or object-specific routes.

## Candidate procedure

Prerequisites: the intended object and relevant fingers are visible; the object
is not visibly enclosed; repeated poses are approximately stationary; no current
evidence requires a settling hold.

1. Compare the current visible grasp region with the space between gripping faces.
2. Choose one small informative motion to test the currently uncertain relation.
   Choose its axis and sign from current evidence, not from this example.
3. Compare measured and visible before/after effects with the intended effect.
   A command with negligible measured response is not achieved progress.
4. If the effect contradicts the intended relation, reconsider from the measured
   current pose. Repeated open-and-hold does not resolve a stationary mismatch.
5. Leave probing when current images support a useful approach or enclosure.
   Closure and lifting still require their own visible verification.

## Promotion test

Track nonzero informative motion, actual response, visible alignment/enclosure,
and stable retention separately. More motion or fewer holds alone cannot promote
this candidate. A transferable skill requires independent development evidence
and must not be certified from this source attempt or expanded-budget performance.

## First candidate check

Revision r001 added this procedure and two historical wrist images between
review barriers. Decisions 6-8 on the source attempt repeated a negative-Z
command with zero measured motion, followed by two holds. This did not improve
alignment or establish a grasp. Do not promote or expand this candidate based on
that check. The next diagnostic isolates IK acceptance and achieved tracking
before further prompt changes.

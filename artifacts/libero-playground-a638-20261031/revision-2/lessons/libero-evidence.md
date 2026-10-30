# Evidence ledger

IDs identify supplied historical evidence, not task selectors or reusable runtime state. Episode-0 findings below are retained from the previous revision; episode-1 findings use the new packet. Authored methods and handoff prose are not execution receipts.

## Episode 0: retained references
- E-SUM: summary; HTTP 502 termination after 243 native steps, 81 Jev calls and 16 GPT calls.
- E-M0, E-M1, E-M2: method-00.json, method-01.json and method-02.json; initial acquisition, revised acquisition and authored placement respectively.
- E-J0: stage-journal.json events[0]; initial geometric rejection before any action.
- E-JS: journal events[1:4]; live control-slice continuations at three boundaries.
- E-JA: journal events[4] and completed; acquisition completed, not the task.
- E-G: program-checkpoints.json acquire.geometry, acquire.supplement, acquire.pregrasp and acquire.revised_geometry.
- E-A: checkpoints acquire.reference and acquire.result; baseline, actual hand states and accepted lift effect.
- E-P: checkpoints place.reference, place.observation and place.progress; entry and acknowledged preliminary upward lease, with no opening or withdrawal.
- E-D: dispatch-000 through dispatch-003 and dispatch-073 through dispatch-080; 12 of 81 receipts, not a complete trajectory.
- E-RG: gpt-02, gpt-05 and gpt-07 parsed reviews; geometry and pregrasp.
- E-RA: gpt-09, gpt-10 and gpt-11 parsed reviews; closed baseline and lift.
- E-RP: gpt-14.parsed.json; placement entry and local upward corridor only.
- E-PLAN: gpt-00.parsed.json and journal plans.

## Episode 1: methods and execution
- N-SUM: summary; termination gpt_budget, 195 native steps, 65 Jev calls and 39 GPT calls. It does not supply a placement effect.
- N-M00 through N-M10: corresponding method-00.json through method-10.json. Full source is supplied only for methods 06 and 10. Other source is explicitly omitted; explanations, interfaces and protocols are design descriptions, not full implementations.
- N-J0: journal update 0; poor initial plane support, then negative contact slack, no action.
- N-J1: update 1; frame-0 entry gate blocked despite affirmative current identity, support and scoped noncontact-route findings; temporal comparison was unavailable.
- N-JS: update 2, control_slice_limit; live continuation during the observation approach.
- N-J2: update 2, stage_returned; approach acknowledged, two contact intervals near 0.76 mm rejected at supported precision.
- N-J3: update 3; distinct strip calculated, but a gate incorrectly described positive route/pad findings as unsupported. No offset had executed. A host override requested plan-level reconsideration.
- N-J4: update 4; offset acknowledged, then checkpoint write exceeded 16384 bytes. No descent yet.
- N-J5: update 5; descent acknowledged and actual contact margins passed; material-feature baseline rejected before closure.
- N-J6: update 6 and completed; four closing deliveries followed by one differential lift, with accepted manual and shared-feature channels.
- N-J7: update 7; mixed lip/interior samples and invalid depth blocked opening geometry.
- N-J8: update 8; replacement lip fit obtained; horizontal candidate rejected under retained uncertainty/margin rules.
- N-J9: update 9; second oversized review write. Limited rise-and-rotation approval existed, but no containment motion was acknowledged. Journal reports that the old review checkpoint was not replaced.
- N-J10: update 10; recovery failed with unknown encoding: unicode_escape. Baseline points and motion records were empty; no containment prefix executed.
- N-PLAN: journal plans; initial two-stage contract and revision from the actual open-hand standoff.

## Episode 1: measurements and reviews
- N-G: checkpoints acquire.initial_0, acquire.initial_1, acquire.geometry, acquire.supplement, acquire.revised_geometry, acquire.contact and retain.geometry.
- N-P: checkpoints acquire.progress and retain.progress; full acknowledged segment endpoints and bounded closing history.
- N-A: checkpoints retain.effect and retain.result, plus N-J6; accepted post-close-baseline lift measurements. Duplicate copies are one result.
- N-C: checkpoint acquire.result and journal updates 7-10; containment attempts and unchanged held state. The checkpoint includes historical outcome fields; its write provenance alone does not make every field a new result.
- N-RB: gpt-22 and gpt-23 parsed reviews; fixed-pose closure approval and rejected feature support.
- N-RA: gpt-25, gpt-26 and gpt-27 parsed reviews; fresh post-close baseline, lift effect and advance decision.
- N-RC: gpt-29, gpt-30, gpt-32 and gpt-33 parsed reviews; opening sampling, semantic replacement and horizontal-fit rejection.
- N-RT: gpt-35, gpt-36 and gpt-38 parsed reviews; limited whole-wrist corridor approval and persistence failures.
- N-D: dispatch-000 through dispatch-003 and dispatch-057 through dispatch-064; first four and last eight of 65 receipts, not a complete trajectory.

## Boundaries and failures retained
1. Episode 0's initial rejection was numerical, not a failed physical pinch. Its later success changed leveling, measurements, pad-band reasoning and tolerance together.
2. Episode 0 accepted independent landmarks after a lift. Its post-lift tracker record was null; exact unavailability/rejection cause is unknown. A supervisor's tracker-corroboration wording does not replace an accepted tracker test.
3. Episode 0 placement reached only a preliminary upward move. No fresh post-move attachment, opening fit, transit, release, withdrawal or final containment is supplied. The 502 is not a mechanical placement outcome.
4. Episode 1 retained the negative initial candidate and the later positive-but-too-narrow intervals as rejections. The changed strip, directional bounds, fresh geometry and revised evidence strategy were not isolated causal experiments.
5. Episode 1 had two erroneous review gates, two oversized checkpoint writes and a final unsupported-codec failure. The first storage repair proceeded to descent; the last repair did not persist its claimed recovery or execute its prefix.
6. Episode 1's old landmark sets failed a baseline support gate, not a measured attachment test. Later different landmarks, a broader tracker and a post-close baseline supported one nearly translational lift.
7. The initial lip set included an invalid depth and a point on lower interior support. Replacement anchors supported a lip plane, but the horizontal envelope still failed retained margin rules.
8. A tilted alternative received only local rise-and-rotation review. No containment rise, rotation, transfer, opening, withdrawal or settled placement was acknowledged in episode 1.
9. Each summary reports 10 settling steps, but neither supplies corresponding post-release support and stability evidence. A summary count is not a final-effect test.
10. Episode 0 omits acquire.progress and samples dispatches and reviews. Episode 1 explicitly omits acquire.observation, acquire.pregrasp, retain.observation and retain.baseline checkpoint contents; reviews are selected and most method source is omitted. Journal duplicate handoffs are omitted. Do not reconstruct missing branches or treat samples as complete trajectories.
11. Checkpoints are historical assertions. Original shape frames, later validation frames, tracker reference frames, test-baseline frames and latest-write provenance remain distinct. No stored coordinates or hidden evaluation state are needed to apply these skills.

# Evidence ledger

All IDs below refer to the supplied episode-0 packet. They are evidence references, not task selectors or reusable runtime state.

## IDs and scope
- E-SUM: episode summary. Termination was HTTP Error 502: Bad Gateway; native_success=false; 243 native steps, 81 Jev calls, and 16 GPT calls were reported.
- E-M0: method-00.json. Authored initial acquisition method, including branches that never ran.
- E-M1: method-01.json. Authored revised acquisition method; use checkpoints and journal to distinguish executed branches.
- E-M2: method-02.json. Authored placement method. Its later opening-fit, transit, release, withdrawal, and settling logic has no demonstrated execution here.
- E-J0: stage-journal.json, events[0]. Initial candidate blocked at frame 0, with no acknowledged robot action.
- E-JS: stage-journal.json, events[1:4]. Three control-slice boundaries at frames 72, 144, and 216; each had a live continuation and a continue decision.
- E-JA: stage-journal.json, events[4] and completed. Acquisition stage completed at frame 225; the overall task remained unsatisfied.
- E-G: program-checkpoints.json, acquire.geometry, acquire.supplement, acquire.pregrasp, and acquire.revised_geometry.
- E-A: program-checkpoints.json, acquire.reference and acquire.result. Baseline and post-lift measurements, actual hand states, and the accepted acquisition effect.
- E-P: program-checkpoints.json, place.reference, place.observation, and place.progress. Entry observation at frame 225 and acknowledged upward lease ending at frame 243; opened=false and withdrawn=false.
- E-D: dispatch-000.json through dispatch-003.json and dispatch-073.json through dispatch-080.json. Only 12 of 81 dispatch receipts: first four and last eight, not a complete trajectory.
- E-RG: gpt-02.parsed.json, gpt-05.parsed.json, gpt-07.parsed.json. Initial, complementary, and pregrasp geometry reviews.
- E-RA: gpt-09.parsed.json, gpt-10.parsed.json, gpt-11.parsed.json. Closed-hand baseline, intermediate lift review, and final acquisition review.
- E-RP: gpt-14.parsed.json. Placement entry review; only the local upward corridor was assessed.
- E-PLAN: gpt-00.parsed.json and stage-journal.json, plans. Proposed observable acquisition and placement stages.

## Boundaries and failures that remain visible
1. The initial geometric candidate was rejected before action. This was not an observed failed pinch and did not establish global grasp infeasibility.
2. Revised acquisition has one successful differential retention test. Leveling, pad-band reasoning, new measurements, and tighter numerical tolerance changed together; their individual causal contributions are not isolated.
3. The acquisition tracker was usable at initialization, but the post-lift accepted sample has track=null. The accepted test contains only independent physical landmarks. The exact rejection or unavailability cause is not supplied. A supervisor statement that tracking corroborated the lift does not supply a retained accepted tracker test.
4. Placement reached only its initial upward move in the supplied execution. A reached hand pose is not post-move attachment evidence. No fresh opening fit, transport, opening command, withdrawal, or final containment result is supplied. The 502 interruption is not evidence of a mechanical placement failure or success.
5. The summary's 10 settling steps do not establish post-release stability: no corresponding release and final support measurements are provided.
6. acquire.progress is explicitly omitted. Journal execution entries omit repeated full before/after states and duplicate handoffs. Reviews are selected, and the dispatch sample is incomplete. Do not reconstruct missing controls or assume unreported branches executed.
7. Checkpoints are historical records, not fresh observations. In particular, place.reference labels a shape frame later than the original boundary measurement retained in acquire.geometry. Preserve original measurement provenance separately from later validation; do not promote a copied envelope to newly observed geometry.

No stored coordinates or hidden evaluation state are needed to apply the skills.

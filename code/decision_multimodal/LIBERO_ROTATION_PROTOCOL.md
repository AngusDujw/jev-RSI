# Three-task multimodal rotation protocol

Tasks:1383 stove control,1458 wine bottle/rack,1335 rectangular cream-cheese box/bowl. Reuse the frozen native policies and original RGB-D target processing. This is hybrid visual orientation control, not raw-RGB pose inference.

The local Pro6.1-sol/high task plan supplies the current semantic stage goal. Only its current name/goal enters each internal model; no experience is loaded. Native phase gates and terminal predicates remain unchanged.

For coarse orientation adjustment (largest world rotation-vector residual at least0.12rad), Luna sees two fresh RGB and a robot-only orientation card. Orange candidate finger meshes and the cyan target are projected into three fixed world views. The target is reconstructed from the original permitted RGB-D/robot-derived task target; it is not an oracle object pose. Candidate previews apply one nominal world-axis increment to the measured own-robot orientation. They do not predict contacts or certify clearance. All available signed candidates and HOLD remain; no numerical ranking or signed residual is sent to the visual call. Card order is deterministically shuffled. One whole categorical choice maps to native rx/ry/rz signs.

An independent text motor call handles XYZ, gripper and native phase edges. For small angular residuals, it also receives signed orientation feedback and aligned booleans. This fallback and the original numerical actuator scaling are explicit. We are testing coarse visual candidate comparison, not claiming numerical geometry has disappeared.

Task1335 starts from a recorded own-robot orientation perturbation: alternating signs of world rotation vector[12,-12,25]degrees at the initial clearance pose. This setup uses no object state, is not model success, and its steps are reported separately from the frozen policy's internal count. Other tasks keep their fixed original initial states.

First development wave: one fixed case per task, concurrently on physical GPUs4–7. Then complete the same version's three predeclared paired initial states per task. Report native success, program completion, visual choice count, actual angular progress, model-generated signs and provider failures separately. Do not resample answered failures; modify a version only after recording its outcome. Require3/3 joint completion per task and actual nontrivial visual rotation before calling the condition operational. Full-task coarse directions may be one-sided; assess bidirectional discrimination separately using the box perturbations and explicit diagnostics. These small samples do not establish broad stability or image necessity.

Every model input is English; no scene object truth, simulator contacts, reward or success enters a model. All actual requests, responses, RGB, orientation cards, public target provenance and execution maps are archived. Experience is English collection-only.

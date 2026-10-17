# Coarse visual relation and fine numerical control, v1

This is a hybrid input ablation, not pure RGB control. Task1144 retains the frozen native phase graph, actuator scaling, initial states5/6/7, native limits and terminal predicates. The goal is a full bowl transfer, not camera-centering success.

During approach, while the camera-derived signed X residual exceeds40mm in magnitude, Luna classifies above/center/below from one current fixed-center wrist enlargement. A fixed independently verified public wrist orientation maps that relation to X. The separate text-only motor call receives signed Y/Z residuals and aligned booleans. Neither role sees EEF coordinates, K/T matrices, numerical tolerances or experience. Derived signed errors are deliberately restored only in the numerical role.

Fine entry is latched when the algorithm reports X within40mm or the visual model selects center. All XYZ directions then use signed residuals and aligned booleans in text-only calls. Original grasp, holding and phase checks remain. No evaluator success enters either role. The accepted local Pro6.1-sol/high task plan is archived; only its current task goal is compiled into the motor state. Its routing/evaluation notes are not actor instructions.

Three fixed initial states, no retries of answered failures. First bound one native episode to inspect actual transport and inputs, then resume the same immutable campaign. Combined provider budget160; no simulation stepping while obtaining the separate perception/motor decisions. Preserve raw visual response, deterministic mapping, numerical response and final merged action separately.

Report native success and program completion separately. Require3/3 joint completion before calling this task stable. Also report number of actual visual X actions and corresponding camera-derived residual changes: numerical rescue after an ineffective visual phase is not evidence of useful visual control. Never count the six image-centering diagnostics as full native successes.

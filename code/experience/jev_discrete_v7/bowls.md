# Rim grasp and visual verification
```json
{"id": "rim-grasp", "status": "active", "tasks": ["stack_bowls"], "stages": ["select", "approach", "contact", "close", "lift", "verify_grasp", "transport", "lower", "release", "retreat", "verify_release"], "rules": {"rim_circle": true, "rim_insertion_m": 0.008, "orient_before_approach": true, "approach_clearance_m": 0.085, "contact_anchor_ttl": 5, "grasp_depth_adjust_m": 0.0, "close_ticks": 8, "lift_clearance_m": 0.12}, "evidence": ["code/runs/wrist-stack_bowls-attempt04", "LOGS/wrist-campaign-results.md"]}
```
The visible inner bowl top is not a stable rim grasp point. Fit the rim from current RGB-D boundaries and choose the reachable edge relative to the robot. Verify that the bowl rises with the gripper; empty lift is not success. Store strategies, never layout coordinates.
Align orientation before descending. A short historical contact reference must be marked as historical, and grasp verification needs fresh measurements. Changes of the highest visible surface point are shape changes, not automatically sensor noise; keep identity and component consistency checks.

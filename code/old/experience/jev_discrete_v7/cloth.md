# Deformable cloth and stable references
```json
{"id": "cloth-reference", "status": "active", "tasks": ["fold_clothes"], "stages": ["select", "approach", "contact", "close", "lift", "verify_grasp", "transport", "lower", "release", "retreat", "verify_release"], "rules": {"cloth_keypoint_anchor": true, "orient_before_approach": true, "approach_clearance_m": 0.085, "contact_anchor_ttl": 5, "grasp_depth_adjust_m": 0.0, "close_ticks": 8, "lift_clearance_m": 0.12}, "evidence": ["code/runs/wrist-fold_clothes-attempt04", "LOGS/wrist-campaign-results.md"]}
```
Occlusion changes the visible outline without necessarily invalidating depth. Keep the same reference for fold points; re-numbered rectangle corners are not persistent landmarks. Old locations are historical references, never current measurements.
Check grasp and destination reachability for both arms using robot-relative workspace boundaries. Align orientation before descending and verify visible cloth rise after a lift probe. Shape changes and measurement uncertainty are separate quantities.

# Appearance memory and temporal observations
```json
{"id": "temporal-match", "status": "active", "tasks": ["match_and_pick_from_conveyor"], "stages": ["select", "conveyor_wait_first", "conveyor_wait_departure", "conveyor_wait_repeat", "approach", "contact", "close", "lift", "verify_grasp"], "rules": {"appearance_match": true, "wait_ticks": 10, "orient_before_approach": true, "approach_clearance_m": 0.085, "contact_anchor_ttl": 5, "grasp_depth_adjust_m": 0.0, "close_ticks": 2, "lift_clearance_m": 0.12}, "evidence": ["code/runs/wrist-match_and_pick_from_conveyor-attempt04", "LOGS/wrist-campaign-results.md"]}
```
First appearance, departure and return are distinct events. A generic object label does not establish unique identity; compare visible color and dimensions. Missed detection does not establish departure.
Use repeated absence plus previously observed motion toward the visible belt boundary; predictions must be labelled as predictions. Align the tool at the safe observation height before pursuing the returned object. Approach may use a coarse tracking band, but closure uses the current contact point. Do not interpret a change of camera surface as object velocity.

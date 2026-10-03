# Stationary button reference
```json
{"id":"press-visible-reference","status":"active","tasks":["press_by_number"],"stages":["select","press_approach","press_contact","press_stroke","press_verify","press_retract"],"rules":{"occluded_fixture_map":true,"approach_clearance_m":0.055},"evidence":["LOGS/press-focus-results.md"]}
```
An initial RGB-D button-face measurement may serve as a historical stationary fixture reference during occlusion. It generates bounded robot waypoints; it does not establish the current button displacement or activation. Jev owns gripper actions and transitions. Attempt counts do not certify activation.

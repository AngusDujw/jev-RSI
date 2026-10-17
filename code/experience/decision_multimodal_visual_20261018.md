# Visual decision experiments — collection only

Not loaded into planner or decision requests.

- **Make the goal visible.** A hidden3D hover waypoint cannot be recovered from “approach above the source” alone. Removing signed errors also requires a visible goal or a separate fine-positioning interface. Evidence: EXP238.
- **Separate perception from motion interpretation.** In the bowl Y-centering diagnostic, image-relation choices plus a fixed verified axis map passed5/6; direct motion questions passed3/6. This is a small diagnostic, not a general capability claim. Evidence: EXP239–240.
- **Keep precision feedback where needed.** The visual model sometimes reached near-center but failed to HOLD. Coarse visual X plus numerical fine control completed native bowl-to-stove3/3; visual X reduced the camera-derived residual by about80mm in each. Numerical actuator scaling remained. Evidence: EXP240–241.
- **More images are not automatically better.** The first fixed previous/current variant passed0/6 versus current-only3/6. Review each added input against measured behavior. Evidence: EXP239.
- **Test reuse separately.** The same coarse-X interface with a cabinet-specific Pro goal also completed task1252 in3/3 fixed cases. Both tasks use the same bowl and wrist orientation; other objects remain unvalidated. Evidence: EXP242.
- **Show the accepted visual region.** An exact center line did not communicate the finite stopping region. Replacing it with a fixed visible band, without numerical residuals, passed the same six horizontal-centering cases6/6 and all ended with model HOLD. Other directions remain separate tests. Evidence: EXP243.
- **Match the judged feature and evaluation feature.** A bowl-rim center and an interior texture patch differed by13 pixels vertically. The model's HOLD could satisfy the visible goal while failing the old patch metric. Keep the old score and validate a separately versioned evaluator. Evidence: EXP244–245.

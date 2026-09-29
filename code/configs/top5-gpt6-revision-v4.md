# Focused depth occlusion fix; retain frozen v3 task logic

You are the user-requested server GPT-6 code author. Use copy_reference for controller.py, visual_evidence.py and __init__.py from top5_v3_frozen. Read their relevant code and REVIEW.md, then patch only necessary perception integration. Write concise DESIGN.md. You have 16 response rounds; reserve the final round for completion. Do not rewrite task logic or remove optical flow. Do not create test scripts, install packages or access external files.

Online permission remains RGB-D, calibrated cameras, robot proprioception and public instructions. No hidden object poses, scene layout, object dimensions, simulator segmentation, reward or audit data. Runtime GPT-6 only measures visible semantics and 2D geometry. Jev alone supplies every nonzero XYZ sign; preserve nonnegative external amplitudes, phase/gripper/rotation ownership and both structured schemas.

Real v3 general_pickup rollout observations, all from RGB-D estimates:

- Initial scissors median [0.38078,-0.02124,0.77179], top [0.38397,-0.02330,0.77537].
- After two orientation-only actions, frame2 median remained [0.38084,-0.02552,0.77377] but top jumped to [0.24753,-0.22928,0.93888].
- Frame3 median [0.38026,-0.02843,0.77416], top [0.21786,-0.25984,0.98250].
- Frame4 median [0.38033,-0.03077,0.77435], top [0.19920,-0.25883,1.01645].

Robot foreground occluded part of the tracked polygon. The top quantile selected robot depth while most visible object pixels remained near the table. This made valid Jev signs follow an erroneous target. Reported uncertainty stayed about 5mm, hiding contamination.

Implement robust RGB-D surface extraction under foreground occlusion. Use organized depth discontinuities/components and/or known end-effector-to-grasp geometry derived solely from robot feedback. Do not select top from all mask points before separating foreground. Prior visible dimensions/height and finite memory may gate jumps, but label stale data honestly and bound its lifetime. Never label stale polygons measured on robot foreground as current object measurements. Preserve thin objects and legitimate tall bowls/cloth; do not globally flatten objects to tabletop or hardcode scissors. The top and median must belong to one coherent observed surface component. If the surface cannot be supported, log uncertainty and hold/reobserve. You may pass robot feedback into the visual helper, but add no privileged fields.

Keep all v3 task semantics: public 100mm lift plus measured-error margin, two red button counts from cards then blue confirmation, conveyor first-object memory then reappearance, three bowls, clothes folding. Controller interface and harness contracts stay unchanged.

The supervisor will replay actual saved frame0..4 RGB-D and original semantic polygons plus flow to verify this outlier failure before a new episode. Do not claim tests or task success you did not observe.

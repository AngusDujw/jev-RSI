# In-frame axes input — preview version

User-requested on2026-10-17. Profile:`libero-rgb-inframe-axes-v1`.
This version is implemented and previewed from archived real RGB. It has not
been sent to a model or run in a new native episode. Previous results remain
specific to their original profiles.

## Actor input

- Current fixed external and wrist RGB, native768x768, with no appended footer.
- Red+X, green+Y and blue+Z arrows drawn directly inside the image. Their common
  origin is the fixed pixel anchor(14.5%width,16%height). It uses neither robot
  position nor target position. A dot/cross shows toward/away for an axis close
  to the viewing direction. Current public camera rotation orients the arrows.
- No control-point circle, target cross, object centre or target arrow is added.
- No outgoing K/T, EEF/TCP coordinates, positional residuals, numerical tolerance
  keys or numerical motor/pose history. Old world_xy fields are also removed.
- The XYZ question uses: "Choose hold when no adjustment on this axis is
  visually needed." It contains no tolerance instruction or distance threshold.
- Task, semantic stage contract, gripper feedback, original non-XYZ questions,
  current-stage completion booleans and other non-positional feedback remain.
  The movement text keeps the verified world axes and rotation-vector semantics.
- Original internal controller thresholds, perception and motor scaling remain.
  This is a visual direction-input experiment, not a claim of pure RGB control.
  Experience remains collection-only; model text and labels are English.

## Preview provenance

Goal1144/init5/decision0000, current observation counter10. Source is the actual
unmarked full-condition archived input. The source PNG contains a160px footer;
the unchanged top768 scene rows are recovered and used. No point marks are
erased or inpainted. Exact source image bytes and crop provenance are saved.
The new overlay changes only the small upper-left annotation area.

Artifacts are under `code/runs/2026-10-17-libero-inframe-axes-preview/`.
The request/text files include `NOT-SENT` in their names. Internal dispatch
metadata may contain calibration for auditing; actor payloads exclude it.

The following is a single-line preparation command; output must not already exist:

```bash
python3 -B code/decision_multimodal/libero_inframe_axes.py --source code/runs/2026-10-17-libero-inframe-axes-preview/source --output code/runs/2026-10-17-libero-inframe-axes-preview/prepared-v2
```

No API key, simulator, GPU or network model call is needed for this preview.

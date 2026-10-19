# Outer experiment decisions

This is outer experiment management, not model input or an experience file.

## Confirmed on 2026-10-17

- The final planning JSON contains stages and advancer-facing input definitions, not processing implementation, test records or code references. The planner prepares and tests the processing separately, including runtime input bindings. No separate planner-environment discussion is needed: provide reference implementations and let the tool-enabled planner implement and test processing.
- Begin with one plan per episode, no previous-step advancer records, and no experience use. The planner assigns the controlled arm per stage.
- Translation and one rotation may execute together. At most one YPR channel is non-hold; the inactive arm preserves its target.
- Use fixed increments initially: 0.02 m per non-hold translation channel and 0.10 rad per non-hold rotation channel. These are selected from the caps in `code/scripts/libero_jev_recovery.py`, `run_recovery`, not a claim that its earlier scheduler was fixed. Do not transplant its error-dependent scaling, normalized action or repeated native-step blocks. Decision-level increments and native execution interpolation are separate.
- Advance dispatches no new action and changes the stage pointer; final-stage advance ends the plan. Native RoboDojo success is evaluated separately.
- Target the official GPT success-rate top ten RoboDojo tasks. First establish stable completion on stacking blocks and sorting, then all ten. Before execution verify the official ranking/model/version and actual sorting task identifier. Define the stability criterion before claiming stable completion.
- The outer agent may directly try changes outside the agreed fixed parts; changes to fixed parts need discussion. This does not authorize reusing retired RoboDojo methods or archived experience.
- Start with the raw-image baseline; open processing is a subsequent version. Settle the JSON and collection design before launching native experiments.
- Future comparisons: replanning-selected step sizes (IMP-007) and replanning-specific history (IMP-008).
- Update: do not create experience files or distill candidate experience now. Preserve complete raw prompts, plans, code versions, observations, model inputs/outputs, execution records and independent native outcomes so experience can be distilled later. Experience remains unused.
- User selected company-server-2 for future experiments. The remote project directory and asset mount must be confirmed before deployment or large writes; earlier server02/v4090 paths do not transfer automatically.

## Confirmed on 2026-10-19

- The user explicitly permits the new generic-grasp experiment to replace each
  arm's three independent YPR questions with one seven-choice rotation question:
  hold, yaw positive/negative, pitch positive/negative, roll positive/negative.
  This is ten API questions across both arms, decoded losslessly to the same
  fourteen XYZ/YPR/gripper directions. Legal action set, world axes, TCP reference,
  simultaneous dual-arm capability and 20mm/0.10rad increments remain unchanged.
- This approved encoding selects no axis on the model's behalf and does not
  repair an invalid response. All previous ended episodes remain ended. The
  new condition is independent of the older Pro/Decisions comparison schedule.

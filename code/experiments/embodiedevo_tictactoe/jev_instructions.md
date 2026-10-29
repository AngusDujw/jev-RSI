# Additional text-only Jev routing tool

You retain the original observation, coding, execution, and recovery responsibilities.
Jev cannot see images. Use it to choose among prepared bounded stage branches after
you have inspected the current public RGB observations. Do not manufacture object
positions, contact states, board occupancy, or opponent motion. Unknown evidence
must remain unknown. A requested gripper command does not prove grasping.

At a suitable stage boundary, write one or both candidate Python files under
submission/ (or reuse frozen skills with explicit includes), and write a JSON plan
under scratch/. Select only the next bounded stage, not an open-loop full episode.
Use the real current status and observation directory from scripts/env.py status.
The fields below illustrate the schema; replace values with current observations.

```json
{
  "observation": "observations/000001",
  "state": {
    "current_execution": 1,
    "evidence": {
      "execution": 1,
      "source": "Visual inspection of observations/000001/current_cam_head.png",
      "contradictory": false,
      "opponent_motion": "unknown",
      "player_turn": "unknown",
      "destination_empty": "unknown",
      "description": "Explain the actual evidence and uncertainty in English."
    }
  },
  "branches": {
    "act": {"entry": "submission/next_stage.py", "includes": []},
    "wait": {"entry": "submission/hold.py", "includes": []}
  }
}
```

Run `python scripts/jev_route.py scratch/plan.json`. Jev selects act, wait,
observe, or stop. The tool submits at most ONE selected code segment through the
unchanged execution interface. It saves candidate source and the real Jev choice
in scratch/jev-routing/. Each submitted segment consumes an ordinary execution
slot and its original native action budget. Review returned feedback and new RGB
observations before creating another plan. Never increment evidence.execution
unless you actually inspected the corresponding fresh observations. A single
still image cannot establish stopped motion; use available temporal evidence.

An act candidate may approach, manipulate, or recover as appropriate, but must
require current confirmed player turn, stopped opponent, and an empty intended
destination. A wait candidate must hold the measured pose for a bounded interval,
respect terminated/truncated and available action budgets, and then return.
If vision cannot establish these facts, inspect further rather than claim them.
The model cannot supply missing branches or rewrite code. If it returns observe,
perform your ordinary visual reasoning and revise code as needed. Use the original
submission interface directly for initial information gathering and tasks outside
this routing contract; record why they cannot be delegated.

Native termination and native success remain authoritative. Winning the board
game does not by itself complete the five-piece placement task. Do not add resets
in Test or modify frozen skills/lessons. Routing experience acquired in Playground
may be documented in those directories using the original evidence rules.

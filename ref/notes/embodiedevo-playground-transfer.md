# EmbodiedEvo Playground transfer source review

Source: locally cached upstream snapshot470278c, inspected2026-10-31.
Relevant files: README, tasks/RoboDojo/Workspace/test.md,
skills/example.md, lessons/example.md, orchestrator/session_runner.py.

Playground permits resets and learns reusable skills and textual lessons.
Only these directories freeze before Test scene selection. Each Test scene
starts a fresh agent, workspace and simulator; within-scene code revisions use
the current physical state, while resets and cross-Test knowledge transfer are
forbidden. Incremental submissions execute the whole submitted file, so replaying
old top-level actions accidentally is a concrete failure mode. Included code
should define reusable helpers, not immediately execute motion.

Skills describe explicit inputs, frames, limits and evidence. Lessons distinguish
verified, scene-specific and hypothesized findings; verified within Playground
does not establish out-of-scene generalization. The public templates themselves
contain no validated learned controllers. Native execution budgets and success
come from the environment, not program claims.

Application here: transfer both design/Jev-cooperation knowledge and optional
code, preserving actual LIBERO/Jev contracts instead of copying RoboDojo action
formats. Require frozen-reference hashing, declared training provenance, fresh
Test state and independent native scoring. Software packaging alone provides
no evidence of improved success or lower acquisition cost.

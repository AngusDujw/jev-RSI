---
name: gpt-jev-method
description: Build, repair, validate, and freeze complete GPT-authored robot methods and Jev input/output protocols using this repository's LIBERO harness. Use for reusable method generation or execution, rather than handwritten task trajectories.
---

# Complete GPT method with Jev

This project-local skill guides the outer orchestrator. It is not automatically
loaded into a remote planner request. Do not append this skill, experiment
management instructions, or benchmark outcome tables to either internal model.

## Construct the actual request

Use the canonical files without making task-specific copies of shared knowledge:

- [Builder instructions](../../../code/prompts/gpt_jev_method_v2.txt).
- [Exact runtime API](../../../code/prompts/gpt_jev_program_api_v2.md).
- [Generic lessons](../../../code/prompts/gpt_jev_method_lessons_v2.txt).

For explicitly selected staged fresh synthesis, the host first uses the
[bounded design contract](../../../code/prompts/gpt_jev_design_v1.txt) and saves
its proposal, then requests the complete method. The design is neither sensor
truth nor executable code. Count both requests and failed attempts. Keep this
condition separate from single-request synthesis and archive-assisted revision.
Do not stop at a design or return stubs as the final complete processing method.

Keep the runtime instruction, current public observations, own robot geometry,
and acknowledged execution separate from those fixed files. Inspect the final
serialized request, including nested JSON text, for English-only content and
scope. Record the actual fixed-file and implementation hashes.

The required result remains four strings: `explanation`, complete `source` with
`main(api)`, `interface`, and `jev_protocol`. The source owns task-specific
geometry, phase predicates, Jev questions/features, effect checks, and executable
recovery. Retain that task-specific output as an artifact; do not insert its
coordinates, trajectories, object names, or task dispatch into shared knowledge.

The interface must describe sufficient observation witnesses and unavailable
evidence for its gates. Follow actual helper return fields and structured review
schemas. Program-returned diagnostic keys must survive into repair inputs under
`incomplete_result.program_result`; verify real request files, not only templates.

Use the [saved-run auditor](../../../code/scripts/audit_gpt_jev_run.py) to check
actual source origins, relay returns, Jev dispatches and usage attempts. Its
guide command supports read-only inspection. A mechanical audit cannot establish
observation truth or replace the saved isolated native evaluator result.

## Execute through the existing harness

Read the [framework guide](../../../code/prompts/README.md) for the current tested
configuration and entry points. Use the [program host](../../../code/scripts/run_gpt_jev_program.py)
and its restricted worker, numerical helpers, public sensing, and bounded control.
The host must invoke real Jev before physical dispatch and retain raw decisions,
acknowledgments, source versions, observations, failures, and usage attempts.

Respect the session's authorized accounts and model settings. Planning uses the
signed-in local Pro path by default; the separately authorized Jev credential
serves its official classifier. Key presence or service connectivity does not
authorize another API purpose. Keep credentials out of model inputs and outputs.

Distinguish reached robot pose, jaw command, independent object effect, program
completion proposal, and terminal native LIBERO score. The evaluator score stays
outside policy input. Retain failed episodes and unknown upstream usage.

## Choose and label the validation unit

- **Independent cold generation:** each episode starts with empty memory and no
  archived source. Freeze shared instructions and runtime for the declared batch.
- **Archive-assisted revision:** explicitly supply an earlier generated method
  with old-episode provenance and current observations. Count its acquisition
  and repair costs; do not label it cold generation.
- **Frozen reuse:** validate one exact generated source hash in fresh episodes.
  Distinguish zero source repair from bounded automatic repair.

Use the unit requested by the user. If the goal is ambiguous, clarify without
blocking useful authorized work. Do not silently substitute reuse evidence for
cold-generation reliability or pool different frozen implementations.

Before reuse, inspect source-level observation shortcuts and frame assumptions.
A frame counter can recur in a new episode. Keep original outputs intact; ask
the planner to reacquire observations and produce a portable complete method
when an archive contains episode-bound pixels, templates, or pose assumptions.
Do not hand-edit task commands to make a failed candidate pass.

Declare initial states, limits, source-repair policy, and failure/admission rule
before a batch. A failed admitted case remains a failed case; unadmitted cases
are not executed failures or replacement successes. Assess success using actual
Jev execution and terminal native scoring. Report the evidence's task, layout,
and budget scope rather than a universal guarantee.

Skill packaging alone does not establish provider caching, lower token use, or
speedup. Preserve synthesis, repair, review, retry, and execution costs so reuse
amortization and latency can be evaluated from actual observations.

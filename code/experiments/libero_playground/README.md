# LIBERO Playground skill transfer

Status: software integration, not a learned or validated robot skill library.
Reference: local EmbodiedEvo snapshot `470278c`, especially its README,
`tasks/RoboDojo/Workspace/test.md` and skill/lesson format guides.

The transfer unit includes method design, observation processing, Jev question
and candidate construction, execution helpers, verification and recovery.
Code is optional inside a skill. The future planner synthesizes its own method
from live observations and applicable frozen knowledge. Jev remains the real
authorized Jev service; local ChatGPT Pro handles planning and distillation.

## Lifecycle

1. Create an empty revision with `skills/` and `lessons/`. Run the existing host
   with `--knowledge-phase playground --skill-memory <revision>` and a new output
   directory. Within each episode, the hierarchical host revises stage methods
   while preserving physical state. A new episode is an explicit reset attempt.
2. Run `libero_skill_memory.py refine` with the revision, terminal Playground
   episode directories, a fresh output revision and fresh refinement receipts.
   The local port7921 bridge must identify ChatGPT/native-session/Astra/xhigh.
   This produces English Markdown skills and lessons with evidence and limits.
   No manually fabricated successful skill is seeded.
3. Feed the new revision to the next declared Playground episode. Retain every
   attempt, including infrastructure failures, model failures and no-motion runs.
   Count refinement requests and their usage separately from episode requests.
4. Freeze only the resulting skills and lessons with `freeze --source ...
   --output ... --evidence ...`. Supply **all** contributing Playground episodes,
   including those contributing to earlier revisions. Refinement carries a
   cumulative lineage file, and freeze rejects omitted or changed contributing
   receipts. This checks recorded provenance, not the scientific validity of a claim.
5. Run fresh episodes with `--knowledge-phase test --skill-memory <frozen>`.
   Hash verification and an in-memory snapshot prevent later knowledge edits
   from altering a running episode. Overlapping Playground initial states and
   archived episode methods are rejected. Test refinement is forbidden.
   The same physical episode may revise its method; it cannot reset. Nothing
   learned in one Test episode is passed to another Test episode.

The host loads knowledge into plan, method, design and stage-supervision calls.
It does not inject the outer experiment protocol into Jev, nor treat old textual
observations as current visual measurements. Python knowledge files are reference
text, not imported or automatically executed. Existing source validation applies
to all generated methods. No environment permissions are changed to freeze files.

## Initial evaluation proposal

Use three Playground attempts as an initial small budget, then freeze. Before
running, declare the selected suite/task/initial-state tuples and existing model,
call and native-step budgets. Test on ten distinct initial states outside the
Playground set with matched empty-skill and frozen-skill conditions. Report
same-task/new-initial-state transfer separately from held-out-task transfer;
ten episodes do not establish broad high reliability. A practical pilot target
is at least8/10 native successes, with a confidence interval and all failures
retained. This target is a proposed engineering criterion, not a changed paper
metric or a current result. Further skill updates require a new version and a
new evaluation split; failed tests cannot silently become training data for the
same claimed held-out result.

Record native success, GPT/Jev calls, wall time, token usage including unknown
usage, refinement cost, retries, physical steps, resets and skill hashes. Compare
total acquisition plus evaluation costs as well as per-Test costs. Native terminal
evaluation remains outside policy inputs; a program's completion proposal is not
task success. Real JEV dispatch receipts establish whether collaboration occurred.

## Current limitations

The first implementation supplies file-level integrity and phase separation,
not an OS sandbox for the outer agent. Skill claims still need evidence review;
format validation cannot establish physical correctness. Distillation currently
receives method files, terminal summaries, stage journals and public checkpoints,
   sampled actual dispatches and recent parsed observations, not raw camera images.
   Add selected public observation receipts if diagnosing
perception failures requires them; never substitute hidden object states.

The local software check verified10 assertions without real model or physics
calls. Local `libero` Conda has MuJoCo/robosuite but no importable LIBERO package.
The user authorized v4090-t and5880-jump. The latter had an idle GPU and its
existing LIBERO-plus environment passed actual rendering, so acquisition runs
there in an independent snapshot. No reboot or driver changes were needed.
The reference chat route was denied403. Zotero's token note supplied the Jev
credential without printing it or transferring it to the server. Episode0 was
admitted with empty learned knowledge and has begun real Pro synthesis.
No physical success claim is made. See the campaign manifest and EXP-2026W44-049.

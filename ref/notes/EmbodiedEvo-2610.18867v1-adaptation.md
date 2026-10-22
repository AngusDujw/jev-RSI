# EmbodiedEvo v1: implementation notes for this project

Read on 2026-10-22. Scope: experience acquisition and reuse, not a benchmark reproduction.

Sources: https://arxiv.org/html/2610.18867v1 and https://github.com/Einsia/EmbodiedEvo at 470278c478bdb5e4b6f17dde1ea0393761f230f0. Upstream checkout is under the authorized DataStorage references directory. Zotero was queried first but its database was locked; the explicit arXiv source was used without modifying Zotero.

## What the paper and source establish

Paper sections 3.3–3.4 distinguish reusable procedures from diagnostic conditions. A failed complete task may still yield a useful local operation. Playground permits within-scene refinement and resets; Test receives only frozen Skills and Lessons, with fresh independent runtimes. Sections 4.5–4.6 and Appendix D show useful transfer and regressions; selected traces do not isolate causal contributions.

The source implements the boundary in orchestrator/frozen_source.py and docs/PROTOCOL.md. tasks/RoboDojo/Workspace/playground.md asks the coding agent to record a finding when it becomes useful, with preconditions, limitations and evidence. The native primitive interface is fixed. The upstream agent also sees configured success signals and some retained skills use contact-related checks: those privileges are NOT adopted here.

## Research judgment questions

1. Author thinking path: valid commands still fail to retain objects or respect readiness; fresh agents repeatedly rediscover operations. Retain an operation together with conditions and checks.
2. Core intuition: executable procedures preserve how; concise Lessons preserve when and how to detect failure. Neither implies that a new scene satisfies the conditions.
3. Most fragile assumption: source-scene operating conditions remain recognizable and applicable in a later scene. The paper itself includes pickup regression; success on one object does not establish transfer.
4. Minimal reproduction here: same bottle actor, initial states and physical budget; compare original, revised question skill, and the identical skill plus three frozen Lessons. Record full native outcome, purposeful phase progression, refusals, stalled actions and API cost. This is a development comparison, not an unseen-scene paper replication.
5. Strong counterexample: an ambiguous, occluded bottle looks retained or seated; incorrect historical advice raises confidence without improving physical support. Compare labels against fresh raw views and preserve failures.
6. Follow-up idea: learn the boundary where an input representation stops being sufficient, using paired changes in a single question contract; keep unknown distinct from an aligned hold. This is a proposed direction, not a proven contribution.
7. Open-source status: public source available; no project-wide license selected as of this checkout. Host tests/configuration/templates are present, but simulator/assets/credentials and private deployment/results are external. No pretrained controller weights are supplied as the contribution is a harness, not weight training. Overall partially reproducible; do not claim an out-of-box reproduction. No upstream code is copied into our implementation.

## Adaptation boundary

- Outer local Pro planner evolves input/question code and concise evidence-backed Lessons.
- OpenAI Decisions remains the sole categorical motor/phase decision maker; no skill emits a target pose, motor sign, scripted action sequence or oracle class.
- Native evaluator outputs stay in outer result accounting. Actor and planner see only permitted observations, own execution and historical qualified findings.
- All experience and model inputs are English. Frozen copies are content-hashed and verified before each request, without recursively changing permissions.
- Keep original task-specific guidance and demonstration conditions explicit. The old uncorrected task-example ablation is retained as contaminated, not silently replaced.

## Development update: 2026-10-23

- Frozen Skills remain input/question programs, not action generators. Pro29–31 actually received separately curated English lessons with recorded file hashes.
- One concise finding changed the phase contract: final seating-orientation readiness had blocked an already position-converged clearance phase. Pro30 narrowed that extra condition to lowering; an independent native episode then made an actor-selected handoff and real transport at490steps. This is partial progress, not task completion.
- Another finding changed a visual-feature question: directly comparing a line with one narrow wooden strip was clearer than mixing physical-feature identity with future support intent. Pro31 supplied the new header/question; full native benefit remains under test.
- Public-camera projections enlarge all current observed wood spans in two views. No target angle, angular correction, externally selected reference or motor sign is supplied.
- Long budget alone was insufficient: v59-r2 completed0/3 at2998steps; v60 completed0/2 plus one explicit provider refusal. Interrupted cases are kept outside complete-outcome denominators.
- Five short candidate Lessons pass the bounded retrieval schema but are not automatically injected into active frozen episodes. The current user target remains stable knob plus bottle performance, not the paper's benchmark score.

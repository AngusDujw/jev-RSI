# Evidence-backed Skills and Lessons

This is an EmbodiedEvo-inspired adaptation for the existing categorical Decisions actor, not a replacement coding policy.

## Acquisition

Keep raw observations and public execution traces immutable. `experience_harness.py facts` reads only execution.jsonl; it never reads native result.json. Store one short English Lesson per condition/finding/check, with evidence and observed/hypothesis/tested status. A failed episode may support a local finding; a successful episode does not certify a general procedure. Native outcomes are outer evaluation records, never model-facing memory.

## Reusable Skills

A Skill may improve observation processing or formal question construction. The first skill selects a provisional upper receiving surface and replaces numeric wording only in visual X/Y fallback questions. It cannot select a candidate or motor sign. Valid numeric-axis questions, rotation/gripper/phase categories and the native controller stay unchanged.

## Freeze and read

A working harness contains only skills/ and lessons/. Freeze makes a new independent copy with per-file SHA256 and a manifest hash. Neither permissions nor existing environments are altered. Runtime validates all hashes before every request, loads the actual pinned question_skill.py, and reads at most three task/stage-matching Lessons within150words. It records every read in api-events.jsonl and writes truthful experience metadata in manifest/dispatch. A skill-only condition executes the same code without Lesson text.

## Improvement loop

1. Diagnose one mismatch from actual input, answer, next observation and own execution; keep uncertainty explicit.
2. Add or revise a short Lesson and a parameterized input/question Skill. Pro planning uses the actual selected English findings; preserve the literal prompt and output.
3. Freeze before running a comparison. Do not update a snapshot during an episode or from another comparison episode.
4. Run paired development initial states with unchanged physical budget. Distinguish native success, normal program completion, infrastructure interruption and typed refusal.
5. Preserve all outcomes. Promote a candidate only after complete paired evidence; validate a frozen stable method on reserved states later. Do not consume reserved states while debugging or describe development results as unseen generalization.

Assets, Skills/Lessons snapshots, images, plans and raw logs live under /home/v4090-1/DataStorage/gpt6-dec/libero-decision-20261019. Repository code contains the mechanics and documentation; snapshots are pinned in campaign.json. Paper/source review: ../../ref/notes/EmbodiedEvo-2610.18867v1-adaptation.md.

## Evidence-scoped v59 source-reference skill

A v58 intermediate audit found selected receiver points but repeated unlabelled sources: the transport question required eventual load-bearing geometry. Pro24 reviewed synchronized real images. v59 changes the shared-key clearance-preparation and transport reference question and its matching image header to request a provisional visible-body XY anchor. The original three Lessons are identical; the new short finding remains a separate hypothesis, not an injected success rule. A static choice with confidence0.18 was only an interface observation. The frozen v2 hash and live development campaign are pinned in protocols/experience_v59_transport_reference.json. v58 snapshots and runtime processes are unchanged. Seating/contact checks, source candidates, rotation questions, motor categories and phase paths remain untouched.

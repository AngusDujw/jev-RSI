# Recorded GPT complete-method output

`method.json` is the unedited GPT output package: explanation, complete executable
source, interface and Jev input/output protocol. `method.py` is the identical source
in a readable file. `PROVENANCE.json` identifies the tested host and outcomes.

This is runtime output for one task, not a task recipe in the fixed prompt, a
shared robot skill, or an automatically loaded builder demonstration. No part of
this directory is supplied to GPT unless explicitly selected as an archived method.
The fixed task-independent framework is under `code/prompts/`.

The final method completed the development episode after three same-scene
repairs. Its held-object recovery branch contains earlier public RGB-D shape
samples labelled historical; these are not hidden object state. Fresh open-hand
runs use the acquisition branch and remeasure geometry. The first frozen new-init
probe failed during transfer tracking, and reference growth alone did not fix it.
A spatial feature-budget variant subsequently completed that same init with the
unchanged method and no repairs, then completed the first unused init 2 under the
same freeze. This is one task and one held-out initial state, not a general
reliability guarantee. A wire-compaction probe also completed init 1; see its
unknown-usage qualification in the provenance and report.
The final framework's separate from-scratch request timed out before delivering
another method. This directory is evidence for the actual generated method and
its repair/reuse, not proof that a prompt alone reliably generates a fresh success.

The executable expects the exact host API and a restricted worker. It is not a
standalone robot command script. Raw runs, both camera videos and native summaries
are retained under `code/runs/2026-10-24-gpt-jev-program/`; the development report
is [here](../../LOGS/2026-10-24-gpt-jev-program.md).

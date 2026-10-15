# Phase1: frozen LIBERO text-only Decision comparison

All50 predeclared paired episodes completed. Original task policy, processing, thresholds and question wording were frozen; only the transport/model changed to du gpt-6-luna. No RGB or experience was sent to the actor.

| Goal | Task | Native success | Native + program finished | Actual answers |
|---|---|---:|---:|---:|
| 1098 | Middle drawer | 5/5 | 5/5 | 497 |
| 1144 | Bowl to stove | 0/5 | 0/5 | 229 |
| 1163 | Bottle to cabinet | 5/5 | 5/5 | 505 |
| 1202 | Open drawer and insert bowl | 1/5 | 0/5 | 775 |
| 1252 | Bowl to cabinet | 0/5 | 0/5 | 230 |
| 1296 | Plate to front stove | 5/5 | 3/5 | 583 |
| 1335 | Cheese to bowl | 5/5 | 5/5 | 364 |
| 1383 | Stove knob | 5/5 | 5/5 | 508 |
| 1423 | Bowl to plate | 0/5 | 0/5 | 338 |
| 1458 | Bottle to rack | 5/5 | 5/5 | 621 |

Totals: native31/50; joint28/50; 4650 real provider answers. No answered episode was dropped or automatically resampled.

## Failure evidence

- Goals1144/1252: repeated visual reobservation or stop after the lift holding check failed. This alone does not distinguish a physical missed grasp from a failed visual holding estimator.
- Goal1423: stop or lift/alignment stage budget; keep these as observed control/perception failures.
- Goal1296: all five native successes; two program rollouts did not complete their final stage. Do not relabel them joint successes.
- Goal1202: two original questions reached a singleton option set, unsupported by Decisions minimum of two; one HTTP503; two native block budgets. One budget-censored program had native success. The prior Jev reference was unstable, so no prior five-success baseline is claimed.

## Scope and provenance

- Five initial states per task are paired with historical references, not unseen-state generalization.
- Frozen bundle:181 archived files plus150 same-commit lazy-import dependencies;331 SHA-checked files across ten task versions.
- First four deployment episodes are separately preserved: one drawer success and three setup faults. None are selectively inserted into this formal50-episode denominator.
- Execution: company-server-2 physical GPUs4–7, three foreground child processes per GPU. Existing environments only; no driver changes.
- Raw assets remain on the same project filesystem under code/runs/2026-10-16-libero-decision-text-complete (about4.9GiB).
- Planner/iteration: local ChatGPT Pro gpt-6.1-sol with high reasoning. Runtime actor prompts remain the frozen original English text.
- A transport failure is retained in the all-episode denominator and identified separately from actor judgment.

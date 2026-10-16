# LIBERO prompt/interface repair: clarity v1

## Predeclared comparison

The first 50 text-only episodes remain immutable. This is a separate repair
batch, authorized after their failure audit. No images or experience are sent
to the actor. Historical processing can use RGB-D exactly as before.

| Goal | Task | Paired initial states | Previous native / joint |
|---|---|---|---|
| 1144 | Bowl to stove | 5,6,7,8,9 | 0/5 / 0/5 |
| 1202 | Open drawer and insert bowl | 3,4,5,6,7 | 1/5 / 0/5 |
| 1252 | Bowl to cabinet | 4,5,6,7,8 | 0/5 / 0/5 |
| 1296 | Plate to front stove | 12,13,14,15,16 | 5/5 / 3/5 |
| 1423 | Bowl to plate | 10,11,12,13,14 | 0/5 / 0/5 |

All 25 outcomes stay in the new denominator. These are historical paired
states, not unseen-state tests. Goal1202 has no stable historical Jev baseline.
Native success and program completion remain separate. No successful task is
added merely to improve the aggregate. Physical GPUs4–7 only, up to three
foreground episodes per GPU, with the existing disk guard.

## Request changes

- Restore the pending-test protocol that historical focused-state reconstruction
  dropped. A not-yet-run co-motion check has `valid=null`, not `false`.
- Clarify the existing lift contract: move to the test point before judging the
  pending check. An actual failed check remains a failure. The original
  three-stall recovery condition and availability flag remain authoritative.
- Append each question's own signed goal-minus-current error and original
  tolerance. No missing tolerance is invented. The actor still selects signs;
  the adapter never replaces an incorrect returned sign with a computed one.
- Preserve task-specific gates and closure-trial exceptions. Clarify that a
  completed, permitted stage can advance rather than indefinitely holding.
- Extract singleton questions as schema constants. Their point distribution
  means there is exactly one legal value; it is not a model probability or
  evidence that the action will work. All other questions still use real Luna.
- Retry an explicit HTTP429/502/503/504 at most twice after the first attempt,
  only when its preserved body contains no answer field. A received answer,
  refusal, malformed answer or timeout is never resampled. No simulator action
  runs during the HTTP retry. Every HTTP failure remains audited, including a
  recovered one; separate HTTP-attempt counts from final episode failures.

The per-task source hashes, original options, phase graph, camera processing,
geometry, control law, tolerances, budgets and evaluator are unchanged. The
adapter records original, revised, provider and returned legacy JSON separately.
This is a combined prompt/interface repair, not a single-factor causal ablation.
It does not by itself exclude differences between historical and current hosts.

## Verification and assets

1054 historical requests were checked for unchanged originals/options and
valid conversion; 163 pending states were normalized. Local checks also cover
singleton handling, one transient503, an HTTP error carrying an answer, refusal
to resample invalid answers, and no invented missing tolerance. The temporary
test script was removed after verification.

Preparation artifacts: `code/runs/2026-10-16-libero-clarity-preparation/` locally.
Native batch assets: `code/runs/2026-10-16-libero-clarity-v1/` in the company
worktree. The campaign pins its four adapter/runner source hashes and refuses
to resume against a changed specification.

```bash
python3 -B code/decision_multimodal/run_libero_campaign.py --baselines code/runs/2026-10-16-decision-mm-preparation/frozen-baselines-complete --output-root code/runs/2026-10-16-libero-clarity-v1 --key-file .private/du-openai-direct.key --gpus 4 5 6 7 --jobs-per-gpu 3 --profile libero-clarity-v1 --tasks 1144 1202 1252 1296 1423
```

Run this single-line command from the company worktree, using its existing
Python3. No shell detachment or service is needed.

# Historical successful framework with persistent transport — 2026-10-30

Both independent cold runs failed before the first Jev dispatch. All complete-method and first-review requests returned successfully. The immediate failures were generated-program geometry admission gates, not observed transport failures or exhausted budgets.

## Frozen conditions

- Historical successful knowledge: a8e6ea72; unchanged builder/API/lessons hashes. Historical worker, geometry, review contract and RGB-D helper hashes also match.
- Host: 95f042f3 on branch codex/gpt-jev-native-historical-20261030, derived from 8b4bfdd6. Only post() and transport imports changed; the remaining historical AST matches. The local native relay implementation is frozen by runtime-versions.json.
- Planner: local signed-in ChatGPT Pro, gpt-6-astra/xhigh, CLI version recorded in manifest. No Platform/caz key. Official Jev1.13 credentials were configured locally but neither method requested Jev.
- Counts: 24 GPT logical calls, 200 Jev, 600 policy steps, zero source repair. Empty episode memory, no archived method/design/feedback. Known task then new task, one each, no replacement outcomes.
- Existing request/episode cutoff removal was retained: JSON-null native job deadlines and RuntimeMaxSec=infinity. Historical runtime time-budget display remains the fixed 1e12 compatibility sentinel, not an enforced cutoff. Jev classification retains its 900-second network budget.
- Server: company-server-2-ykj, existing project UV environment and LIBERO-plus, GPU4. No installation, driver or environment permission changes.

Actual initial instructions (32,308 characters), tools, model and effort match the historical request in both cases. The known run's two initial JPEGs match the previous known-task reproduction byte for byte. Runtime task observations differ for the new task. The removed deadline changes the time-budget display, and native Codex adds internal tools/framing; this is not byte-identical full model context or a pure TCP/protocol-only causal comparison.

The newly generated methods are different programs from the historically successful source. This tests fresh generation with the old configuration, not frozen reuse of the successful program.

## Results

| Case | Method delivery | Generation seconds | Episode seconds | GPT | Jev / policy steps | Native LIBERO |
|---|---|---:|---:|---:|---:|---|
| Known1335/init12: cream cheese into bowl | 206 lines | 1335.464 | 1492.790 | 2 | 0 / 0 | false |
| New138/init0: bowl on cabinet | 172 lines | 1859.957 | 2076.533 | 2 | 0 / 0 | false |

Both outcomes were method_incomplete with completion_proposed=false. Initial settling was 10 simulator steps per episode, separate from zero policy steps. Each episode used one complete-method generation and one strict visual review, with zero source repairs, zero invalid submissions and zero observed native recovery events. Both remote hosts and the local batch exited normally.

## Known-task rejection

[The generated source, line139](known-1335-init12/method-00.py) requires the measured box bounding radius plus its own margin to be below the fitted bowl opening radius:

- Box radius: 45.439685 mm.
- Selected margin: 7.321572 mm.
- Fitted opening radius: 52.285526 mm.
- Excess: 0.475731 mm.

The program stopped in its uninitialized phase immediately after that check, without acquiring more evidence or using the remaining control budget. This is a decision under this method's chosen measurements and uncertainty margin, not proof the physical task is impossible. The old task and initial images were preserved; no threshold was manually relaxed.

## New-task rejection

[The generated source, line128](new-138-init0/method-00.py) requires the selected visible landing patch's inradius to exceed bowl radius plus its chosen margin:

- Visible landing inradius: 64.368519 mm.
- Fitted bowl radius: 55.542231 mm.
- Required margin: 9 mm.
- Shortfall: 0.173712 mm.

The program stopped in its unstarted phase with 22 GPT calls, all 200 Jev calls and all 600 policy steps remaining. The review also reported one discontinuous surface-depth point (lip4) and non-unique floral landmarks. Those were additional evidence limitations, not the first stopping trigger. No counterfactual threshold relaxation was tested; merely changing that number is not established as sufficient to finish the task.

## Interpretation and limits

The connection path delivered 2/2 complete methods and 4/4 logical GPT results. The saved-run auditor verified actual model source origin, both strict reviews, exact relay matches, reported costs and zero dispatches. The empty Jev ledger was initialized for the zero-call audit and contains no fabricated decisions.

Native success was 0/2, and actual Jev dispatch was 0. Thus these runs do not measure Jev control quality, success rate or task execution efficiency. They do not support the claim that fixing delivery alone yields a reliably feasible GPT-authored method.

The shared observable failure pattern is an immediate first-observation rejection at a self-chosen geometry/margin boundary, without spending the remaining budget to reobserve or reconsider the plan. A future generic-method revision should test bounded evidence acquisition and replanning under such uncertainty. It should not hand-edit these task-specific thresholds and relabel the failed runs as successes. No robot prompt, generic lesson or task-source repair was changed in this batch.

Known native aggregates: 947,517 input tokens (880,128 cached), 76,794 output tokens, including 48,680 reasoning tokens. Native internal attempts are not exact HTTP-attempt accounting; no observed recovery means no recovery event was recorded, not proof about unexposed provider internals. No token-saving or speedup claim follows from zero physical actions.

New138 was absent from 83 available prior GPT-Jev task records on each machine. This is available-framework novelty, not model-training novelty. One run per group cannot estimate reliability or attribute latency to task novelty.

## Reproduction and evidence

[Manifest](manifest.json), [nine offline integration/hash checks](offline-checks.json), [initial contract checks](initial-contract-checks.json), [runtime versions](runtime-versions.json), [per-request native accounting](native-requests.json), [complete results](results.json), [cleanup](cleanup.json).

Each case folder retains the original complete method package and source, task/terminal summaries, scrubbed requests, parsed responses, client transport records, diagnosis and mechanical audit. The known case additionally has a byte-level initial-image check; raw observations remain in the saved run folders. No hidden reasoning text is included in this report.

Remote host checkout:

```text
/home/ykj/project/jev-rsi-roboicl/.worktrees/gpt-jev-native-historical-20261030
```

Existing interpreter:

```text
/home/ykj/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python
```

Existing dataset:

```text
/home/ykj/yekangjie/project/embodied-jev/.sim/LIBERO-plus
```

The exact host flags are in manifest and EXP-2026W44-039/040. The two host invocations used task1335/init12 and task138/init0 respectively, seed0, GPU4, max-gpt24, max-jev200, max-native-steps600, max-repairs0 and unlimited-time.

Direct server GitHub fetch hit TLS failure during deployment, so the identical already-pushed incremental Git commit was transferred as a Git bundle over existing SSH and fetched locally. This deployment event is separate from the four successful GPT requests. Both temporary bundle files were removed.

After both terminal summaries and saved-run audits, only our local bridge and reverse tunnel were stopped. Their cleanup signals are not task termination. Both remote task services and the local batch had already exited0; both7921 listeners are closed. No standalone verification script or credential copy was created. Formal research goals/theorems were not changed.

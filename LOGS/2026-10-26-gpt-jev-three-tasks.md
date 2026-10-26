# Three-task cold-generation probe

Predeclared before model or simulator execution.

```json
{
  "created_utc": "2026-10-26T07:42:33.736877+00:00",
  "condition": "independent cold generation; one complete-source submission, zero source repairs",
  "server": "company-server-2-ykj",
  "host_commit": "302ff1eb639fffc2cb8a4a51cd5364eb4ce1c15e",
  "suite": "libero_goal",
  "cases": [
    {
      "slug": "drawer",
      "task_id": 0,
      "name": "open_the_middle_drawer_of_the_cabinet_table_1",
      "init_index": 0,
      "seed": 0
    },
    {
      "slug": "push",
      "task_id": 75,
      "name": "push_the_plate_to_the_front_of_the_stove_table_12",
      "init_index": 0,
      "seed": 0
    },
    {
      "slug": "bowl",
      "task_id": 102,
      "name": "put_the_bowl_on_the_plate_table_1",
      "init_index": 0,
      "seed": 0
    }
  ],
  "budgets": {
    "max_gpt": 24,
    "max_jev": 200,
    "max_native_steps": 600,
    "max_repairs": 0,
    "wall_seconds": 7200
  },
  "planner": "local signed-in ChatGPT Pro gpt-6-astra/xhigh",
  "executor": "official Jev jev-1.13.0 /v1/systemone",
  "source_input": "no archived method, no demonstrations, empty episode memory",
  "runtime_recovery": "only bounded recovery already present in the initial GPT-generated source",
  "evaluation": "terminal native LIBERO score, isolated from policy",
  "admission": "all three declared cases run independently; no substitution after failures",
  "fixed_sha256": {
    "code/prompts/gpt_jev_method_v2.txt": "8575ff018f3f89e039a5728fdecd20c0398cbdcf9b5bfa0e4afa44e725ee1ee7",
    "code/prompts/gpt_jev_program_api_v2.md": "29ed69517c826ab8558f09dcd5dae8c26562598aa3069a2a05f6d99f0ad1635a",
    "code/prompts/gpt_jev_method_lessons_v2.txt": "02a783f6388a5ad00033f7063097e0fb5224a2a05bceb3aac3bf30e07931afb2",
    "code/scripts/run_gpt_jev_program.py": "b43427798eee163423c37f28ff037d51c3b8e81cc0e4999ae6b61b3ceeb3030f",
    "code/scripts/gpt_jev_program_worker.py": "1f70e1d39eea229942903604423593e2d1564d2c52c0e26f0f6a69ff37156b2f",
    "code/scripts/gpt_jev_geometry.py": "847c011a62da67ad00f2302963dd7a68583c864bdba888067086a230730d997c",
    "code/scripts/gpt_jev_review_contract.py": "e6bbb3c998f64d93220ac7a2aa9632e46d360eb888959c424d32b9648b5b082e",
    "code/scripts/jev_rgbd_tracking.py": "0783afa7b104b2648710e668186670493a4812e5a5e77847bf476a449bda3d67",
    "baseline/roboicl/reproduction/pro_oauth_bridge.py": "36d3470de72e088a38c8e171c5f86e4d5aba4ba00bb0f141f476083d653d53ed"
  },
  "scope": "three different tasks, one initial state each; exploratory cross-task probe, not a statistical reliability estimate",
  "cost": "count generation, reviews, real Jev attempts and unknown usage; no automatic repair condition in this batch"
}
```

## Results

Final acquisition outcomes are recorded below and in artifacts/gpt-jev-three-task-probe-20261026/README.md. No source or Jev dispatch was delivered.

## Original single-request outcomes

All three returned HTTP504 without executable source or Jev dispatches. This is a delivery/transport limitation, not a measured physical policy failure rate. The drawer/push requests each had two upstream attempts with unknown usage. Bowl waited for a relay slot and had only34.4seconds upstream; do not treat it as an equal-budget source test. A separate minimal pinned Pro request completed in3.12seconds,120input/13outputtokens.

## Separate staged condition

Predeclared before launch: same three tasks/init0/seed0, unchanged fixed builder/API/lessons/host, existing staged design then full-source mode, zero source repairs,3relay slots,900seconds per synthesis stage and same episode budgets. No old source or task-specific template. Final supplement: designs3/3, complete sources0/3, Jev0, policy steps0; see final outcomes.

## Staged infrastructure interruption and independent supplement

The first staged bridge exitedSIGTERM143 after about290seconds; all three design requests disconnected, no design/source/Jev actions were delivered. No terminal relay ledger exists, so actual upstream attempts and usage are unverifiable, not zero. Preserve this interruption separately. A predeclared same-condition supplement now runs under one foreground parent owning its bridge and SSH children; no fixed prompt, runtime code, task, initial state or source-repair budget changed.

## Final outcomes

# Three-task GPT/Jev framework probe, 2026-10-26

The current framework did not deliver a complete executable method for these new tasks within the declared budgets. **No real Jev request or policy action occurred, so physical task success rates were not measured.**

| Task | LIBERO-Plus goal ID | Initial state | Staged design | Complete source | Real Jev | Policy steps |
|---|---:|---:|---|---|---:|---:|
| Open the middle drawer | 0 | 0 | Delivered | Timed out | 0 | 0 |
| Push the plate to the front of the stove | 75 | 0 | Delivered | Timed out | 0 | 0 |
| Put the bowl on the plate | 102 | 0 | Delivered | Timed out | 0 | 0 |

The fixed builder, API, generic lessons and302ff1ebruntime were retained. All requests used English, local signed-in Pro Astra/xhigh, empty episode memory and no archived task source. No task trajectory was hand-written. Each episode allowed24GPT,200Jev,600policy steps,7200seconds and zero source repairs. Only the existing optional synthesis mode and relay scheduling differed between conditions.

## Conditions and limits

1. **Original single-request synthesis:** all three logical requests returnedHTTP504 without source. Drawer and push each used the full1798-second relay limit with two upstream attempts. Bowl spent most of that deadline waiting for one of two relay slots and had only34.4seconds upstream; it is not an equal-budget generation test. Five attempt usages are unknown.
2. **First staged batch:** the bridge exitedSIGTERM143 after about290seconds. All three design requests disconnected. The cause and actual upstream attempt counts are unknown; no terminal ledger exists. Preserve these records separately.
3. **Independent staged supplement:** one foreground parent owned a three-slot bridge and the SSH children. All three designs returned: bowl261.23s, push356.20s, drawer409.62s. Each complete-source stage then hit its898-second relay deadline (900-second caller limit minus two seconds). No source was delivered. Per-episode elapsed times were1173.02/1267.84/1321.12seconds for bowl/push/drawer. These are not summed concurrent batch wall time.

A separate small Pro readiness request completed in3.12seconds,120input/13outputtokens. This establishes small-request availability, not reliable long synthesis, and does not distinguish slow inference from long-response delivery failure.

The supplement's three designs have28776known input/13172known outputtokens. Including the diagnostic gives28896/13185. Eight additional ledger attempts have unknown usage; three interrupted logical requests lack terminal ledgers and may involve further attempts. These are not complete total costs.

## Evidence

[Machine-readable outcomes and costs](../artifacts/gpt-jev-three-task-probe-20261026/RESULTS.json), [original declaration](../artifacts/gpt-jev-three-task-probe-20261026/manifest.json), [staged declaration](../artifacts/gpt-jev-three-task-probe-20261026/staged-manifest.json), [supplement declaration](../artifacts/gpt-jev-three-task-probe-20261026/staged-retry-manifest.json), [environment](../artifacts/gpt-jev-three-task-probe-20261026/environment.json), and [foreground lifecycle](../artifacts/gpt-jev-three-task-probe-20261026/staged-retry-orchestration.json).

- [Drawer design and records](../artifacts/gpt-jev-three-task-probe-20261026/staged-supplement/drawer/method-design.json)
- [Push design and records](../artifacts/gpt-jev-three-task-probe-20261026/staged-supplement/push/method-design.json)
- [Bowl design and records](../artifacts/gpt-jev-three-task-probe-20261026/staged-supplement/bowl/method-design.json)
- [Full experiment report](2026-10-26-gpt-jev-three-tasks.md)

Original and supplement requests, English input, strict designs, source absence and zero-step/cost consistency passed the saved-run auditor. The interrupted batch cannot receive the same provenance audit because its terminal ledgers are missing. Audits do not certify design correctness or perception truth.

Terminal nativefalse outcomes are retained exactly. They were evaluated on settled initial scenes with zero policy actions, so reporting a Jev physical success rate of0/3 would be misleading. No executable method, reusable new-task policy or efficiency gain was established. Full source acquisition/transport must work before the intended physical generalization test can be completed. No current method was patched into success.

[Files added or updated](../artifacts/gpt-jev-three-task-probe-20261026/CHANGED-FILES.md). No executable runtime or model-facing prompt was edited.

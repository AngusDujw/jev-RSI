# Code-as-policy with local judgments

Upstream: HexaFuture/HexaShell, pinned at
`e0190ddb757955131578e9f9071f4ee8e7113f7a` (2026-11-03).
The checkout belongs under `baseline/HexaShell-runtime`; it is an independent
Git repository, not vendored source. No tracked upstream file is modified.

The upstream LIBERO-PRO simulator, generic RGB-D/SAM3 perception, motion tools,
persistent Python-cell worker and native task checker are retained. A worker
bootstrap adds `jev_proxy.py` to the package search path before confinement.
Generated cells have no credentials or network access. Their `robot.decide`
RPC is answered in the host, never in the simulator.

The planner uses only the local ChatGPT-authenticated native-session bridge.
No Platform API key is accepted by this adapter. The bridge's single validated
`submit_policy` function maps to one upstream Python cell or finish request.
The full retained transcript and requested images are submitted each turn;
the native bridge can recover an interrupted logical request before execution.
Formatting glyphs are normalized to ASCII; CJK input is refused. The
ChatGPT-authenticated account and JEV credentials remain on the workstation.

`robot.decide(question, options, context=None)` returns a branch receipt.
Every option set must include `unknown`. The host adds observations from real
API results: timestamped measurements, motion results, gripper feedback and
temporal position differences. Program context is explicitly not a sensor.
No raw images, hidden object poses, contact state or native success flag are
sent to JEV. Width-based holding remains labeled as a heuristic. Stale
measurements carry age in native steps. The selected branch is executed by
the generated Python policy; the adapter does not silently dispatch motion.

Use `--judgment-backend gpt` for the same text-evidence contract with Pro,
or `jev` for the real `jev-1.13.0` Choice endpoint. This is a backend
comparison under a shared harness; it does not reproduce upstream's original
model-provider setup. Geometry and low-level controls do not require model
direction choices.

The campaign refines English Markdown Skills/Lessons only from Playground
episodes, including useful helper definitions, evidence requirements,
questions/options and bounded recovery procedures. It hashes and freezes
them before fresh Test processes. Test seeds cannot overlap Playground,
Test records are refused by refinement, and modified frozen files are
refused by loading. Upstream task skills are disabled so they cannot leak
into the empty-memory condition. Native checks alone determine success.

Install project-local environments using `code/scripts/setup_hexashell_jev.sh`.
It follows upstream's pinned simulator installer and isolates SAM3 in its
officially required Python 3.12 environment. The policy uses Python 3.11.
Set TMPDIR and all installer caches under this project. No driver changes
are required or permitted. Start the upstream SAM3 service from its own
environment and the existing native-session bridge on the workstation.
Forward only their required loopback ports over SSH.

`code/scripts/serve_hexashell_sam3.sh GPU PORT OUTPUT` launches the unchanged
upstream SAM3 service with its ordinary CUDA caching allocator. The upstream
default enables expandable segments, which may be unsupported by a vGPU's
virtual-memory interface. Choose a GPU authorized for the task before launch;
the script does not select or evict another job. The 16-image CPU cache bounds
RAM use and does not change masks or model weights.

From the project root, each command below is one command; the shell joins
the explicitly backslash-continued lines:

```bash
.venv-hexashell/bin/python code/scripts/run_hexashell_jev.py \
  --task libero_goal_swap_t3 --seed 0 --phase playground \
  --judgment-backend jev --out code/runs/hexashell-jev/demo-0
```

```bash
.venv-hexashell/bin/python code/scripts/run_hexashell_jev_campaign.py \
  --tasks libero_goal_swap_t3 --playground-seeds 0 1 --test-seeds 20 21 \
  --out code/runs/hexashell-jev/campaign-0
```

The campaign records all attempted episodes and stops on infrastructure or
contract failures before refining them or admitting another episode. It does
not resume or replay interrupted physical episodes automatically. Inspect
the saved terminal record and use a new output folder for a new run.

Audit an episode directory using `code/scripts/audit_hexashell_jev.py`.
The audit checks real call/request/answer consistency. It does not establish
physical correctness independently, nor infer that a later motion was
causally selected just from a decision receipt. Assess that against the
saved policy code and native episode result. Keep network interruption,
contract failure, task failure and native success separate in reports.

#!/usr/bin/env python3
"""Small, explicit Playground campaign followed by fresh matched Test episodes."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code/hexashell_jev"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tasks", nargs="+", required=True)
    p.add_argument("--playground-seeds", nargs="+", type=int, default=[0, 1])
    p.add_argument("--test-seeds", nargs="+", type=int, default=[20, 21])
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--bridge", default="http://127.0.0.1:7951")
    p.add_argument("--gpu", default="0")
    p.add_argument("--max-turns", type=int, default=30)
    p.add_argument("--budget-seconds", type=int, default=7200)
    args = p.parse_args()
    if set(args.playground_seeds) & set(args.test_seeds):
        p.error("Playground and Test seeds must be disjoint")
    if any(not 0 <= seed < 50 for seed in args.playground_seeds + args.test_seeds):
        p.error("Use explicit initial-state indices 0..49, without modulo aliases")
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        p.error("Campaign output must be fresh; never overwrite or replay an interrupted physical episode")
    out.mkdir(parents=True, exist_ok=True)
    from runtime import Pro
    from memory import freeze, load, refine
    training, results, knowledge = [], [], None
    pro = Pro(args.bridge, out)

    def episode(task, seed, phase, backend, memory=None):
        folder = out / f"{phase}-{task}-s{seed}-{backend}" / ("learned" if memory else "empty")
        cmd = [sys.executable, str(ROOT / "code/scripts/run_hexashell_jev.py"),
               "--task", task, "--seed", str(seed), "--phase", phase,
               "--judgment-backend", backend, "--bridge", args.bridge, "--gpu", args.gpu,
               "--max-turns", str(args.max_turns), "--budget-seconds", str(args.budget_seconds),
               "--out", str(folder)]
        if memory:
            cmd += ["--memory", str(memory)]
        completed = subprocess.run(cmd, check=False)
        paths = sorted(folder.glob("*/result.json"))
        if len(paths) != 1:
            raise RuntimeError("Episode has no unique terminal record: " + str(folder))
        result = json.loads(paths[0].read_text())
        summary = dict(task=task, seed=seed, phase=phase, backend=backend, learned=bool(memory),
            record=str(paths[0].parent), exit_code=completed.returncode,
            success=result["success"], end=result["end"], step=result.get("step"),
            turns=result["turns"], errors=result["errors"])
        results.append(summary)
        (out / "campaign.json").write_text(json.dumps(dict(config=vars(args) | {"out": str(out)},
                                                          episodes=results), indent=2)+"\n")
        print(json.dumps(dict(event="episode", **summary)), flush=True)
        if result["end"] in ("error", "gateway_error"):
            raise RuntimeError("Infrastructure/contract failure recorded; campaign stopped before learning or admitting another episode")
        return paths[0].parent

    for task in args.tasks:
        for seed in args.playground_seeds:
            record = episode(task, seed, "playground", "jev", knowledge)
            training.append(record)
            knowledge = refine(pro, [record], out / f"revision-{len(training)}", previous=knowledge)
    frozen = out / "frozen"
    receipt = freeze(knowledge, frozen, training)
    print(json.dumps(dict(event="frozen", **receipt)), flush=True)
    for task in args.tasks:
        for seed in args.test_seeds:
            # Alternate order to reduce provider/time confounding; all processes start fresh.
            conditions = [("jev", None), ("jev", frozen), ("gpt", frozen)]
            if seed % 2:
                conditions.reverse()
            for backend, memory in conditions:
                load(frozen, require_frozen=True)
                episode(task, seed, "test", backend, memory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

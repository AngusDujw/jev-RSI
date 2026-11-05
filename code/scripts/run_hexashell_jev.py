#!/usr/bin/env python3
"""Run a real LIBERO-PRO code-policy episode through local Pro and JEV."""
from pathlib import Path
import argparse
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code/hexashell_jev"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--upstream", type=Path, default=ROOT / "baseline/HexaShell-runtime")
    p.add_argument("--sim-python", type=Path, default=ROOT / ".venv-libero-pro/bin/python")
    p.add_argument("--sim-env", type=Path, default=ROOT / "code/outputs/hexashell/libero-pro/env.sh")
    p.add_argument("--task", required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--gpu", default="0")
    p.add_argument("--bridge", default="http://127.0.0.1:7951")
    p.add_argument("--sam3-url", default="http://127.0.0.1:18350")
    p.add_argument("--judgment-backend", choices=("jev", "gpt"), default="jev")
    p.add_argument("--phase", choices=("development", "playground", "test"), default="development")
    p.add_argument("--max-turns", type=int, default=30)
    p.add_argument("--max-decisions", type=int, default=40)
    p.add_argument("--budget-seconds", type=float, default=7200)
    p.add_argument("--request-timeout", type=float, default=1800)
    p.add_argument("--memory", type=Path)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    args.out = args.out.resolve()
    if args.out.exists() and any(args.out.iterdir()):
        p.error("--out must be fresh; episodes cannot be replayed into an existing record")
    args.out.mkdir(parents=True, exist_ok=True)
    temp = args.out / "tmp"
    temp.mkdir()
    os.environ.update(TMPDIR=str(temp), TMP=str(temp), TEMP=str(temp))
    memory_text = ""
    if args.memory:
        from memory import load
        memory_text = load(args.memory, require_frozen=args.phase == "test")
    from runtime import run_episode
    path = run_episode(args, memory_text)
    result = json.loads((path / "result.json").read_text())
    print(json.dumps(dict(path=str(path), success=result["success"], end=result["end"],
                         steps=result.get("step"), turns=result["turns"], errors=result["errors"])), flush=True)
    return 0 if result["success"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

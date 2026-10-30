"""Foreground acquisition/refinement and matched frozen-memory evaluation.

Resume only terminal episodes with matching declared arguments. An incomplete
directory is never restarted automatically. All subprocesses stay foreground.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from libero_skill_memory import freeze, load, refine


def write(path, value):
    pending = path.with_suffix(".pending")
    pending.write_text(json.dumps(value, indent=2)+"\n")
    pending.replace(path)


def episode(args, root, name, initial, phase, memory):
    output = root / name
    expected = dict(suite=args.suite, task_id=args.task_id, init_index=initial,
        seed=0, gpu=args.gpu, max_gpt=40, max_jev=200, max_native_steps=600,
        hierarchical=True, max_stage_updates=24, max_plan_revisions=3,
        max_stage_revisions=3, stage_control_calls=24, stage_policy_steps=72,
        unlimited_time=True, no_video=True, knowledge_phase=phase)
    if output.exists():
        if not args.resume or not (output / "summary.json").exists():
            raise ValueError("Existing incomplete or unapproved episode: " + str(output))
        recorded = json.loads((output / "protocol.json").read_text())["arguments"]
        if any(recorded.get(key) != value for key, value in expected.items()):
            raise ValueError("Episode arguments changed: " + name)
        if memory is not None:
            _, metadata = load(memory, phase, suite=args.suite, task_id=args.task_id, init_index=initial)
            previous = json.loads((output / "skill-memory.json").read_text())
            if previous["snapshot_sha256"] != metadata["snapshot_sha256"]:
                raise ValueError("Episode knowledge changed: " + name)
        elif recorded.get("skill_memory") is not None:
            raise ValueError("Empty-memory baseline has unexpected knowledge")
    else:
        command = [sys.executable, "-u", "-B", str(Path(__file__).with_name("run_gpt_jev_program.py")),
                   "--output", str(output), "--libero-root", str(args.libero_root)]
        for key, value in expected.items():
            command.append("--"+key.replace("_", "-"))
            if value is not True:
                command.append(str(value))
        if memory is not None:
            command += ["--skill-memory", str(memory)]
        print(json.dumps(dict(event="episode_start", name=name, phase=phase)), flush=True)
        with (root / (name+".log")).open("x") as log:
            process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        write(root / (name+".process.json"), dict(returncode=process.returncode, command=command))
    summary = json.loads((output / "summary.json").read_text())
    print(json.dumps(dict(event="episode_end", name=name, success=summary["native_success"],
        gpt=summary["gpt_calls"], jev=summary["jev_calls"], steps=summary["native_steps"])), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--libero-root", type=Path, required=True)
    parser.add_argument("--suite", default="libero_goal")
    parser.add_argument("--task-id", type=int, default=1335)
    parser.add_argument("--gpu", default="0")
    parser.add_argument("--phase", choices=("acquire", "test"), required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    repo = Path(__file__).resolve().parents[2]
    if not root.is_relative_to(repo / "code/runs"):
        parser.error("Campaign output must be inside project code/runs")
    root.mkdir(parents=True, exist_ok=True)
    # Prevent two orchestrators from admitting the same next episode concurrently.
    import fcntl
    with (root / "campaign.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.phase == "acquire":
            for name in ("skills", "lessons"):
                (root / "revision-0" / name).mkdir(parents=True, exist_ok=True)
            results = []
            for index in range(3):
                memory = root / f"revision-{index}"
                results.append(episode(args, root, f"episode-{index}", index, "playground", memory))
                revision = root / f"revision-{index+1}"
                if revision.exists():
                    if not args.resume or not (revision / "lineage.json").exists():
                        raise ValueError("Untracked existing revision")
                else:
                    refine(memory, revision, [root / f"episode-{index}"], root / f"refine-{index}")
                write(root / "acquisition.json", dict(completed=index+1, summaries=results))
            frozen = root / "frozen"
            if not frozen.exists():
                freeze(root / "revision-3", frozen, [root / f"episode-{i}" for i in range(3)])
            else:
                load(frozen, "test")
            print(json.dumps(dict(event="frozen", training_successes=sum(s["native_success"] is True for s in results))), flush=True)
        else:
            acquisition = json.loads((root / "acquisition.json").read_text())
            if acquisition.get("completed") != 3:
                raise ValueError("Finish acquisition before matched Test")
            load(root / "frozen", "test")
            results = []
            for initial in range(3, 13):
                # Alternate order to reduce a systematic service-time confound.
                conditions = ["empty", "learned"] if initial % 2 else ["learned", "empty"]
                for condition in conditions:
                    summary = episode(args, root, f"test-{initial:02d}-{condition}", initial,
                        "test", root / "frozen" if condition == "learned" else None)
                    results.append(dict(initial=initial, condition=condition, summary=summary))
                    write(root / "evaluation.json", dict(episodes=results,
                        successes={c:sum(r["condition"] == c and r["summary"]["native_success"] is True for r in results)
                                   for c in ("empty", "learned")}))


if __name__ == "__main__":
    main()

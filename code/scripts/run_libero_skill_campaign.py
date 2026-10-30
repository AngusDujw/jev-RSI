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

from libero_skill_memory import file_hashes, freeze, load, read_files, refine


def write(path, value):
    pending = path.with_suffix(".pending")
    pending.write_text(json.dumps(value, indent=2)+"\n")
    pending.replace(path)


def episode(args, root, name, initial, phase, memory, task_id=None):
    output = root / name
    task_id = args.task_id if task_id is None else task_id
    expected = dict(suite=args.suite, task_id=task_id, init_index=initial,
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
            _, metadata = load(memory, phase, suite=args.suite, task_id=task_id, init_index=initial)
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
    parser.add_argument("--test-tasks", type=int, nargs="+", help="Explicit task IDs for separate cross-task Test cases")
    parser.add_argument("--test-inits", type=int, nargs="+", help="Explicit initial-state IDs; default3..12")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.phase != "test" and (args.test_tasks is not None or args.test_inits is not None):
        parser.error("Test selections cannot alter Playground acquisition")
    for values in (args.test_tasks, args.test_inits):
        if values is not None and (any(v < 0 for v in values) or len(set(values)) != len(values)):
            parser.error("Test selections must contain distinct nonnegative IDs")
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
                    receipt = root / f"refine-{index}" / "revision.json"
                    if not args.resume or not (revision / "lineage.json").exists() or not receipt.exists():
                        raise ValueError("Untracked existing revision")
                    if json.loads(receipt.read_text())["files"] != file_hashes(read_files(revision)):
                        raise ValueError("Refined knowledge changed before resume")
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
            tasks = args.test_tasks if args.test_tasks is not None else [args.task_id]
            initials = args.test_inits if args.test_inits is not None else list(range(3, 13))
            for task_id in tasks:
                for initial in initials:
                    load(root / "frozen", "test", suite=args.suite, task_id=task_id, init_index=initial)
            selection = dict(suite=args.suite, tasks=tasks, initial_states=initials,
                knowledge_sha256=load(root / "frozen", "test")[1]["snapshot_sha256"])
            # Each selection has its own report; previous task groups stay intact.
            import hashlib
            selection_id = hashlib.sha256(json.dumps(selection, sort_keys=True).encode()).hexdigest()[:12]
            selection_file = root / f"test-selection-{selection_id}.json"
            if not selection_file.exists():
                write(selection_file, selection)
            for task_id, initial in [(task, initial) for task in tasks for initial in initials]:
                # Alternate order to reduce a systematic service-time confound.
                conditions = ["empty", "learned"] if initial % 2 else ["learned", "empty"]
                for condition in conditions:
                    name = (f"test-{initial:02d}-{condition}" if args.test_tasks is None else
                            f"test-task{task_id}-init{initial:02d}-{condition}")
                    summary = episode(args, root, name, initial,
                        "test", root / "frozen" if condition == "learned" else None, task_id=task_id)
                    results.append(dict(task_id=task_id, initial=initial, condition=condition, summary=summary))
                    report = dict(selection=selection, episodes=results,
                        successes={c:sum(r["condition"] == c and r["summary"]["native_success"] is True for r in results)
                                   for c in ("empty", "learned")},
                        by_task={str(task): {c: dict(
                            successes=sum(r["task_id"] == task and r["condition"] == c and r["summary"]["native_success"] is True for r in results),
                            completed=sum(r["task_id"] == task and r["condition"] == c for r in results))
                            for c in ("empty", "learned")} for task in tasks})
                    write(root / f"evaluation-{selection_id}.json", report)


if __name__ == "__main__":
    main()

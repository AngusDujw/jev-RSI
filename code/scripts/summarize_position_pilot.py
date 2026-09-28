"""Audit raw artifacts and summarize development data without independence claims."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path


def load_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output
    out.mkdir(parents=True, exist_ok=False)
    stages, bins, amplitudes = defaultdict(list), defaultdict(list), defaultdict(list)
    checksums, best, models = {}, Counter(), Counter()
    all_decisions, all_branches = [], []
    for run in args.runs:
        summary = json.loads((run/"summary.json").read_text())
        assert summary["status"] == "completed", run
        protocol = json.loads((run/"protocol.json").read_text())
        assert protocol["protocol"] == "oracle-local-position-pilot-v2-settled", run
        decisions = load_lines(run/"decisions.jsonl")
        branches = load_lines(run/"branches.jsonl")
        assert len(decisions) == summary["decisions"]
        for path in run.rglob("*"):
            if path.is_file():
                checksums[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        for decision in decisions:
            if "metrics" not in decision:
                continue
            folder = run/decision["decision_id"]
            for name in ("request.json", "response.json", "decision.json", "sim_state.npz", "sim_metadata.json"):
                assert (folder/name).exists(), folder/name
            assert decision["preparation"]["stable"], folder
            models[decision["model"]] += 1
            stages[decision["stage"]].append(decision)
            error = decision["metrics"]["error_norm_m"]
            bin_name = "<2 mm" if error < .002 else "2–20 mm" if error < .02 else ">=20 mm"
            bins[bin_name].append(decision)
            group = [row for row in branches if row.get("decision_id") == decision["decision_id"]]
            assert len(group) == len(protocol["amplitudes_m"]), folder
            assert sorted(row["amplitude_m"] for row in group) == protocol["amplitudes_m"], folder
            assert all(row["reset_identical"] for row in group), folder
            assert len({tuple(row["before_position_m"]) for row in group}) == 1, folder
            successful = [row for row in group if "goal_error_after_m" in row]
            if successful:
                winner = min(successful, key=lambda row: row["goal_error_after_m"])
                best[str(winner["amplitude_m"])] += 1
            for row in group:
                row = dict(row, run=str(run), error_bin=bin_name)
                amplitudes[(bin_name, row["amplitude_m"])].append(row)
                all_branches.append(row)
            all_decisions.append(decision)
    def counts(ds):
        ms = [d["metrics"] for d in ds]
        cs = [m["cosine"] for m in ms if m["cosine"] is not None]
        return dict(decisions=len(ms), correct_axes=sum(sum(m["axis_correct"]) for m in ms),
                    axes=3*len(ms), positive_cosines=sum(c > 0 for c in cs), measurable_cosines=len(cs),
                    all_hold=sum(m["all_hold"] for m in ms))
    rows = []
    for (bucket, amplitude), group in sorted(amplitudes.items()):
        valid = [row for row in group if "goal_error_after_m" in row]
        rows.append(dict(error_bin=bucket, amplitude_mm=amplitude*1000, trials=len(group),
            progressed=sum(row["loss_decrease_m2"] > 0 for row in valid),
            worsened=sum(row["loss_decrease_m2"] < 0 for row in valid),
            stable=sum(bool(row["stable"]) for row in valid),
            mean_error_change_mm=(sum((row["goal_error_after_m"]-row["goal_error_before_m"])*1000
                                      for row in valid)/len(valid) if valid else None)))
    result = dict(total=counts(all_decisions), stages={k:counts(v) for k,v in stages.items()},
        descriptive_error_bins={k:counts(v) for k,v in bins.items()}, amplitudes=rows,
        hindsight_best_amplitude_counts=best, models=models, branch_count=len(all_branches),
        limitations=["development, oracle local goals, three correlated scaffold trajectories",
                     "error bins are descriptive post-hoc slices, not preregistered hypotheses",
                     "hindsight best amplitude is not an implementable optimizer or closed-loop gain",
                     "complete stacking by Jev and visual-input performance were not tested"])
    (out/"analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    (out/"sha256.json").write_text(json.dumps(checksums, indent=2)+"\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

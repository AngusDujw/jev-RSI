"""Freeze RoboDojo layout-0 cases and a staged task order from official scores."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def build(root: Path, reference: Path, output: Path, limit_base: int | None = None) -> dict:
    rates = json.loads(reference.read_text())['success_percent_by_runtime_task']
    base = sorted((name for name in rates if not name.endswith('_random')),
                  key=lambda name: (-rates[name], name))
    variants = sorted((name for name in rates if name.endswith('_random')),
                      key=lambda name: (-rates[name], name))
    cases = []
    missing = []
    selected = base[:limit_base] if limit_base is not None else base + variants
    for task in selected:
        relative = Path('Assets/Eval_Layout/RoboDojo/arx_x5/0') / f'{task}_0.json'
        layout = root / 'robodojo' / relative
        if not layout.is_file():
            missing.append(str(relative))
            continue
        cases.append(dict(task=task, runtime_task=task, layout_id=0,
                          eval_seed=0, layout=str(relative),
                          layout_sha256=hashlib.sha256(layout.read_bytes()).hexdigest(),
                          split='development'))
    if missing:
        raise FileNotFoundError('Missing RoboDojo layouts: ' + ', '.join(missing))
    manifest = dict(source='Official RoboDojo GPT-6 Astra sim leaderboard, 2026-10-09; ordering only',
                    reference_file=str(reference),
                    base_task_count=len(base), variant_task_count=len(variants),
                    batches=[base[i:i+5] for i in range(0, len(base), 5)],
                    variants=variants, cases=cases)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit-base', type=int,
                        help='Build only the first N base tasks, leaving later batches for expansion')
    args = parser.parse_args()
    result = build(args.root, args.reference, args.output, args.limit_base)
    print(json.dumps(dict(base_tasks=result['base_task_count'],
                          variants=result['variant_task_count'],
                          first_batch=result['batches'][0])))

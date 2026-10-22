"""Evidence-backed, English Skills/Lessons snapshots, independent of task scores."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from legacy_decisions import english


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def public_trace_facts(episode):
    """Read only executed commands and own-robot feedback, never native results."""
    path = Path(episode) / 'execution.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    stages = {}
    for index, row in enumerate(rows):
        stage = str(row['stage'])
        item = stages.setdefault(stage, dict(actions=0, physical_steps=0, six_axis_hold=0,
                                             rotation_actions=0, sign_reversals=0,
                                             low_measured_motion=0, max_consecutive_hold=0))
        item['actions'] += 1
        item['physical_steps'] += row['native_steps'] - (rows[index-1]['native_steps'] if index else 10)
        item['six_axis_hold'] += all(row['choices'].get(k) == 'hold'
                                     for k in ('x', 'y', 'z', 'rx', 'ry', 'rz'))
        item['rotation_actions'] += any(abs(x) > 1e-8 for x in row['commanded_rotation_world_deg'])
        if index and rows[index-1]['stage'] == row['stage']:
            for axis in ('x', 'y', 'z', 'rx', 'ry', 'rz'):
                previous = rows[index-1]['choices'].get(axis)
                current = row['choices'].get(axis)
                item['sign_reversals'] += {previous, current} == {'positive', 'negative'}
        distance = sum(x*x for x in row['measured_translation_mm']) ** 0.5
        angle = sum(x*x for x in row['measured_rotation_world_deg']) ** 0.5
        item['low_measured_motion'] += distance < 0.5 and angle < 0.5
    for stage, item in stages.items():
        streak = 0
        for row in rows:
            if str(row['stage']) == stage and all(row['choices'].get(k) == 'hold'
                                                for k in ('x', 'y', 'z', 'rx', 'ry', 'rz')):
                streak += 1
            else:
                streak = 0
            item['max_consecutive_hold'] = max(item['max_consecutive_hold'], streak)
    return dict(source=str(path), source_sha256=digest(path), stages=stages,
                scope='Own execution facts only; holding and task completion remain unverified.')


def file_table(root):
    root = Path(root)
    if root.is_symlink():
        raise ValueError('Experience root cannot be a symlink')
    table = {}
    if {p.name for p in root.iterdir()} != {'skills', 'lessons'}:
        raise ValueError('Only skills/ and lessons/ may transfer')
    for folder in ('skills', 'lessons'):
        if (root / folder).is_symlink() or not (root / folder).is_dir():
            raise ValueError('Experience directories must be ordinary directories')
        for path in sorted((root / folder).rglob('*')):
            if path.is_symlink():
                raise ValueError('Experience cannot contain symlinks')
            if not path.is_file():
                continue
            english(path.read_text())
            table[str(path.relative_to(root))] = digest(path)
    if not table:
        raise ValueError('Empty harness')
    return table


def freeze(source, destination):
    source, destination = Path(source), Path(destination)
    table = file_table(source)
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    shutil.copytree(source, destination / 'harness')
    if file_table(destination / 'harness') != table:
        raise ValueError('Experience changed while freezing')
    manifest = dict(version=1, files=table, transfer=['skills', 'lessons'],
                    forbidden_feedback='No native evaluator or simulator object state is transferred.')
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return digest(destination / 'manifest.json')


def validate(snapshot, expected_sha=None):
    snapshot = Path(snapshot)
    if expected_sha is not None and digest(snapshot / 'manifest.json') != expected_sha:
        raise ValueError('Frozen experience manifest changed')
    manifest = json.loads((snapshot / 'manifest.json').read_text())
    if file_table(snapshot / 'harness') != manifest['files']:
        raise ValueError('Frozen experience files changed')
    return manifest


def context(snapshot, task, stage, max_lessons=3, max_words=150):
    validate(snapshot)
    result = []
    for path in sorted((Path(snapshot) / 'harness/lessons').glob('*.json')):
        lesson = json.loads(path.read_text())
        if set(lesson) != {'id', 'task', 'stages', 'status', 'condition', 'finding', 'check', 'evidence'}:
            raise ValueError('Unexpected lesson schema')
        if lesson['task'] != task or stage not in lesson['stages']:
            continue
        if lesson['status'] not in ('observed', 'hypothesis', 'tested') or not lesson['evidence']:
            raise ValueError('Lesson requires evidence and epistemic status')
        text = f"{lesson['status']}: When {lesson['condition']} {lesson['finding']} Check: {lesson['check']}"
        if len(text.split()) > 65:
            raise ValueError('Lesson must remain short')
        result.append(text)
    selected = []
    for text in result:
        if len(selected) >= max_lessons or len(' '.join(selected + [text]).split()) > max_words:
            break
        selected.append(text)
    return selected


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('facts'); p.add_argument('episode', type=Path); p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('freeze'); p.add_argument('source', type=Path); p.add_argument('destination', type=Path)
    p = sub.add_parser('validate'); p.add_argument('snapshot', type=Path)
    args = parser.parse_args()
    if args.command == 'facts':
        args.output.write_text(json.dumps(public_trace_facts(args.episode), indent=2) + '\n')
    elif args.command == 'freeze':
        print(freeze(args.source, args.destination))
    else:
        print(json.dumps(validate(args.snapshot), indent=2))


if __name__ == '__main__':
    main()

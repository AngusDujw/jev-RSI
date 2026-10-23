"""Select frozen asset roots for standard stack_bowls layouts 0 and 1.

Scene/robot defaults and the exact layout objects select these complete roots.
The result still requires USD dependency and camera preflight before evaluation.
"""
import argparse
import json
from pathlib import Path


ROOTS = (
    'Assets/Robots/', 'Assets/Sensor/', 'Assets/Background/',
    'Assets/Room/Simple_Room_nolight/',
    'Assets/Material/material_0122/', 'Assets/Material/material_0564/',
    'Assets/Object/RoboDojo/Geometry/camera_stand/',
    'Assets/Object/RoboDojo/Rigid/bowl/00008/',
    'Assets/Object/RoboDojo/Rigid/bowl/00010/',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.source_manifest.read_text())
    layouts = {f'Assets/Eval_Layout/RoboDojo/arx_x5/0/stack_bowls_{i}.json' for i in (0, 1)}
    selected = [row for row in source['files'] if row['path'].startswith(ROOTS)
                or row['path'] in layouts]
    assert layouts <= {row['path'] for row in selected}
    # Every selected prefix must exist, rather than silently accepting a typo.
    for prefix in ROOTS:
        assert any(row['path'].startswith(prefix) for row in selected), prefix
    manifest = dict(source, files=selected, scope='explicit-files',
                    selection={'task': 'stack_bowls', 'layouts': [0, 1],
                               'roots': list(ROOTS), 'requires_dependency_preflight': True})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + '\n')
    args.output.with_suffix('.files.txt').write_text('\n'.join(row['path'] for row in selected) + '\n')
    print(json.dumps({'files': len(selected), 'bytes': sum(row['size'] for row in selected)}))


if __name__ == '__main__':
    main()

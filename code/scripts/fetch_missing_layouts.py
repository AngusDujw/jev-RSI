"""Add only missing official layout-0 JSONs on the existing /data asset mount."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import httpx


ROOT = Path('/data/ykj_robodojo/RoboLaya/robodojo/Assets/Eval_Layout/RoboDojo/arx_x5/0')
REFERENCE = Path('/home/user/ykj/project/gpt6/jev-RSI/code/config/official-priority.json')
BASE = 'https://huggingface.co/datasets/RoboDojo-Benchmark/RoboDojo/resolve/main/Assets/Eval_Layout/RoboDojo/arx_x5/0/'
PROXY = 'http://127.0.0.1:10408'
MAX_BYTES = 2_000_000


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=None)
    args = parser.parse_args()
    names = sorted(json.loads(REFERENCE.read_text())['success_percent_by_runtime_task'])
    missing = [name for name in names if not (ROOT / (name + '_0.json')).exists()]
    selected = missing[:args.limit] if args.limit is not None else missing
    records = []
    with httpx.Client(proxy=PROXY, follow_redirects=True, timeout=60) as client:
        for name in selected:
            target = ROOT / (name + '_0.json')
            response = client.get(BASE + quote(target.name))
            response.raise_for_status()
            content = response.content
            if len(content) > MAX_BYTES:
                raise ValueError(f'Layout exceeds {MAX_BYTES} bytes: {name}')
            document = json.loads(content)
            if not isinstance(document, dict) or not document:
                raise ValueError(f'Invalid layout JSON: {name}')
            if target.exists():
                raise FileExistsError(target)
            partial = target.with_suffix('.json.download-partial')
            partial.write_bytes(content)
            partial.replace(target)
            records.append(dict(task=name, bytes=len(content),
                                sha256=hashlib.sha256(content).hexdigest()))
            print(f'{name}: {len(content)} bytes', flush=True)
    print(json.dumps(dict(requested=len(names), missing_before=len(missing),
                          added=len(records), records=records), indent=2))


if __name__ == '__main__':
    main()

"""Serialize outcome recording and share the three-failure stop across workers."""
import fcntl
import json
from pathlib import Path


def stopped(folder):
    return folder is not None and (Path(folder)/'STOP').exists()


def record(folder, row, success):
    if folder is None: return
    root=Path(folder); root.mkdir(parents=True,exist_ok=True)
    with (root/'outcomes.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        path=root/'outcomes.jsonl'
        with path.open('a') as stream: stream.write(json.dumps(dict(row,guard_success=bool(success)))+'\n')
        rows=[json.loads(line) for line in path.read_text().splitlines()]
        if len(rows)>=3 and not any(r['guard_success'] for r in rows[-3:]):
            (root/'STOP').write_text('Three consecutive completed failures across workers; user escalation required.\n')

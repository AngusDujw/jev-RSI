"""Load bounded, reviewed lessons for both planning and decision calls."""
from __future__ import annotations

from pathlib import Path
import re


def load_notes(root, task):
    if not re.fullmatch(r'[A-Za-z0-9_]+', task):
        raise ValueError('Invalid task name for experience lookup')
    root = Path(root)
    notes = {}
    for name, path in (
        ('global', root / 'global.md'),
        ('task', root / 'tasks' / (task + '.md')),
    ):
        if path.exists():
            text = path.read_text()
            if len(text) > 12000:
                raise ValueError('Experience note is too long: ' + str(path))
            notes[name] = text
    return notes

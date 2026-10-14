"""English-only model text contract, checked before any network transmission.

English prose may contain mathematical symbols, units and public asset paths.
This deterministic guard rejects Han text, including nested JSON escapes. It
does not claim to identify every non-English language or OCR image contents.
"""
from __future__ import annotations

import json
import re


ENGLISH_ONLY = (
    "Use English for all instructions, descriptions, stage labels, experience "
    "notes and output text. Preserve numeric values, units and identifiers.")
_HAN = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\U00020000-\U0002ee5f\U0002f800-\U0002fa1f\U00030000-\U0003347f]")


class ModelInputLanguageError(ValueError):
    """A model-bound text field violates the English-only input contract."""


def require_english_model_input(value, context="model request", _path="$", _depth=0):
    """Reject Chinese text in the complete payload, never silently remove it.

    Input evidence is often a JSON document serialized inside a text block;
    parse those strings too so ensure_ascii=True cannot bypass this check.
    Error messages give a field path without echoing field contents.
    """
    if isinstance(value, str):
        if _HAN.search(value):
            safe_path = _path.encode("ascii", "backslashreplace").decode("ascii")
            raise ModelInputLanguageError(
                f"English-only model input required ({context}, {safe_path}); "
                "Chinese text detected. Translate the source before retrying.")
        if value.lstrip().startswith(("{", "[", '"')):
            try:
                decoded = json.loads(value)
            except (ValueError, RecursionError):
                return
            if _depth >= 16:
                raise ModelInputLanguageError("Model text JSON nesting exceeds language audit limit")
            require_english_model_input(decoded, context, _path + "<JSON>", _depth + 1)
    elif isinstance(value, dict):
        for key, item in value.items():
            require_english_model_input(str(key), context, _path + "<key>", _depth)
            require_english_model_input(item, context, _path + "[" + repr(key) + "]", _depth)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            require_english_model_input(item, context, f"{_path}[{index}]", _depth)


def select_task_experience(text, phase, limit=4):
    """Retrieve literal English lessons without depending on Chinese keywords."""
    require_english_model_input(text, "task experience")
    bullets=[line for line in text.splitlines() if line.startswith('- ')]
    tagged=[line for line in bullets if line.startswith('- [phase:'+phase+'] ')]
    if any(line.startswith('- [phase:') for line in bullets):
        return tagged[-limit:]
    tokens = {
        "identity": ("identity", "coordinate", "world", "material"),
        "alignment": ("finger", "facet", "pad", "xyz", "tool", "pose", "material point"),
        "contact": ("finger", "facet", "pad", "xyz", "tool", "pose", "material point"),
        "capture": ("capture", "closed", "closing", "grasp", "holding", "lift", "following", "empty"),
    }[phase]
    return [line for line in text.splitlines()
            if line.startswith("- ") and any(token in line.lower() for token in tokens)][-limit:]


def select_planner_experience(text):
    """Cover each explicitly tagged phase instead of only the last capture notes."""
    require_english_model_input(text, "planner task experience")
    bullets=[line for line in text.splitlines() if line.startswith('- ')]
    if any(line.startswith('- [phase:') for line in bullets):
        chosen=bullets[:1]
        for phase in ('identity','alignment','contact','capture'):
            chosen.extend(select_task_experience(text,phase,limit=1))
    else:
        chosen=bullets[:1]+bullets[-2:]
    return list(dict.fromkeys(chosen))

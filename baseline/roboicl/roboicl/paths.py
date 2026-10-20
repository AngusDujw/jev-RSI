"""Repository, data, result, and pinned upstream import paths."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import types
from importlib.machinery import ModuleSpec


CODE = Path(__file__).resolve().parents[1]
THIRD_PARTY = CODE / "third_party"
ROBODOJO = THIRD_PARTY / "RoboDojo"
XPOLICYLAB = THIRD_PARTY / "XPolicyLab"
ISAACLAB = THIRD_PARTY / "IsaacLab"
CUROBO = THIRD_PARTY / "curobo"


def data_root(value=None) -> Path:
    return Path(value or os.environ.get("ROBOICL_DATA_ROOT") or CODE / "data").expanduser().resolve()


def results_root(value=None) -> Path:
    return Path(value or os.environ.get("ROBOICL_RESULTS_ROOT") or CODE / "results").expanduser().resolve()


def python_paths(context: str = "policy") -> list[str]:
    """Paths needed to import owned code and the four clean submodules.

    RoboDojo and XPolicyLab both expose a historical top-level ``utils``
    package. Put the process owner first so Python resolves that namespace
    without copying or modifying either submodule.
    """
    if context not in ("policy", "sim"):
        raise ValueError("context must be policy or sim")
    owners = [XPOLICYLAB, ROBODOJO] if context == "policy" else [ROBODOJO, XPOLICYLAB]
    paths = [CODE, THIRD_PARTY, *owners, CUROBO]
    paths.extend(path for path in sorted((ISAACLAB / "source").glob("*")) if path.is_dir())
    return [str(path) for path in paths]


def configure_imports(context: str = "policy") -> None:
    paths = python_paths(context)
    sys.path[:] = paths + [path for path in sys.path if path not in paths]


def configure_utility_namespace(context: str = "sim") -> None:
    """Restore process-owned bare utils imports after Kit changes import paths.

    Both released repositories use namespace directories named utils. A
    concrete package loaded by Kit can otherwise shadow those directories.
    Preserve already initialized SDK attributes and add the owned search paths.
    """
    configure_imports(context)
    owners = [ROBODOJO, XPOLICYLAB] if context == "sim" else [XPOLICYLAB, ROBODOJO]
    roots = [str(owner/"utils") for owner in owners]
    namespace = sys.modules.get("utils")
    if namespace is None:
        namespace = types.ModuleType("utils")
        namespace.__package__ = "utils"
        namespace.__spec__ = ModuleSpec("utils", loader=None, is_package=True)
        sys.modules["utils"] = namespace
    namespace.__path__ = roots + [path for path in getattr(namespace, "__path__", []) if path not in roots]
    if namespace.__spec__ is not None:
        namespace.__spec__.submodule_search_locations = namespace.__path__
    for source in (owners[0]/"utils").glob("*.py"):
        name = "utils."+source.stem
        cached = sys.modules.get(name)
        if cached is not None and Path(getattr(cached, "__file__", "") or "").resolve() != source.resolve():
            del sys.modules[name]
            if getattr(namespace, source.stem, None) is cached:
                delattr(namespace, source.stem)

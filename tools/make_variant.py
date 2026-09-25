#!/usr/bin/env python3
"""把根目录的协议打包成 `variants/<name>/` —— 一个自包含、可整体拎走的「开新项目」初始化文件夹。

    python3 tools/make_variant.py                 # 生成 variants/research/ + variants/research.zip
    python3 tools/make_variant.py research --no-zip
    python3 tools/make_variant.py --force         # 目标目录不是本脚本生成的也照样重建

设计：**根目录是唯一来源，variants/<name>/ 是生成物**。协议要改就改根目录，然后重新跑本脚本，
不要在生成物里改——避免出现两份会漂移的协议正文。

生成时会把「项目状态」复位成崭新模板（这是它和 `cp -r` 的区别）：

    LOGS/ · Discussion/Archive/ · ref/ · ref/notes/ · code/ · baseline/   只保留 README.md
    Discussion.md   从 tools/templates/Discussion.template.md 重置
    TIMELINE.md     清空节点表并重画空图
    MODE.md         mode / updated_at / set_by / last_retro 复位为 unset

被排除：`.git/`、`variants/`、`__pycache__/`、`.DS_Store`、`.claude/settings.local.json`（本机私有）、
`*.pyc`、`*.zip`、虚拟环境与编辑器目录。md 里被
`<!-- upstream-only:begin -->` / `<!-- upstream-only:end -->` 包起来的段落（只在上游成立的说明，
比如指向 `variants/` 的链接）也会被整块删掉。

重建保护：生成目录里有 `.variant-manifest` 记录本次写出的文件清单。重建时只删清单里的文件，
清单外的文件会保留并提示；目标目录存在但没有清单（说明是手写的变体，如 `daily-pm`）则直接拒绝，
除非 `--force`。
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from session_check import REPO, now_cn, read  # noqa: E402

VARIANTS = REPO / "variants"
MANIFEST = ".variant-manifest"

SKIP_DIRS = {".git", "variants", "__pycache__", ".venv", "venv", "node_modules",
             ".idea", ".vscode", ".pytest_cache", ".ipynb_checkpoints"}
# settings.local.json 是每个人本机的权限/偏好，不该跟着模板走
SKIP_NAMES = {".DS_Store", MANIFEST, "settings.local.json"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".zip"}

# 这些目录只带 README（项目状态不进模板）
STATE_DIRS = ("LOGS", "Discussion/Archive", "ref", "ref/notes", "code", "baseline")
KEEP_IN_STATE_DIRS = {"README.md", ".gitkeep"}

# 只属于上游仓库的段落（比如指向 variants/ 的说明），打包时整块删掉
UPSTREAM_ONLY_RE = re.compile(
    r"[ \t]*<!-- upstream-only:begin -->.*?<!-- upstream-only:end -->[ \t]*\n?",
    re.DOTALL,
)

BANNER = """\
> 📦 **这是打包出来的「开新项目」初始化文件夹**，由上游仓库的 `python3 tools/make_variant.py` 生成于 {stamp}。
> 本目录**自包含、可整体拎走**：拷到别处 → `git init` → `bash tools/install_hooks.sh` → 用 Claude Code 打开，
> `bootstrap.md` 会带你走完初始化（选 A 新手 / B 老手）。
> 协议正文的唯一来源在上游根目录——**别在这里改协议**，改完上游重新生成即可。
"""


def iter_source_files() -> list[Path]:
    out: list[Path] = []
    for path in sorted(REPO.rglob("*")):
        rel = path.relative_to(REPO)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if not path.is_file():
            continue
        if path.name in SKIP_NAMES or path.suffix in SKIP_SUFFIXES:
            continue
        parent = rel.parent.as_posix()
        if parent in STATE_DIRS and path.name not in KEEP_IN_STATE_DIRS:
            continue
        out.append(rel)
    return out


def reset_mode(text: str) -> str:
    text = re.sub(r"^- `mode`: `.*`$", "- `mode`: `unset`", text, flags=re.MULTILINE)
    text = re.sub(r"^- `updated_at`: `.*`$", "- `updated_at`: `YYYY-MM-DD HH:MM`", text, flags=re.MULTILINE)
    text = re.sub(r"^- `set_by`: `.*`$", "- `set_by`: `bootstrap.md`", text, flags=re.MULTILINE)
    return re.sub(r"^- `last_retro`: `.*`$", "- `last_retro`: `unset`", text, flags=re.MULTILINE)


def reset_timeline() -> str:
    import timeline

    return timeline.rendered(timeline.TEMPLATE, [])


def banner_readme(text: str) -> str:
    banner = BANNER.format(stamp=now_cn().strftime("%Y-%m-%d %H:%M"))
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith("# "):
            return "".join(lines[: i + 1]) + "\n" + banner + "".join(lines[i + 1:])
    return banner + "\n" + text


def content_for(rel: Path) -> str | None:
    """返回要写出的内容；None = 原样复制。"""
    posix = rel.as_posix()
    if posix == "MODE.md":
        return reset_mode(read(REPO / rel))
    if posix == "TIMELINE.md":
        return reset_timeline()
    if posix == "Discussion.md":
        template = REPO / "tools" / "templates" / "Discussion.template.md"
        text = read(template) if template.exists() else read(REPO / rel)
        return UPSTREAM_ONLY_RE.sub("", text)
    if posix == "README.md":
        return UPSTREAM_ONLY_RE.sub("", banner_readme(read(REPO / rel)))
    if rel.suffix == ".md":
        text = read(REPO / rel)
        stripped = UPSTREAM_ONLY_RE.sub("", text)
        return stripped if stripped != text else None
    return None


def preflight() -> list[str]:
    """根仓库像不像"干净模板"——不干净只警告，不阻断。"""
    warns = []
    if not (REPO / "bootstrap.md").exists():
        warns.append("根目录没有 bootstrap.md（已初始化过？）→ 生成的变体缺少初始化向导，"
                     "先 `git checkout bootstrap.md` 再打包")
    mode = re.search(r"^- `mode`: `(\w+)`", read(REPO / "MODE.md"), re.MULTILINE)
    if mode and mode.group(1) != "unset":
        warns.append(f"根目录 MODE.md::mode = {mode.group(1)}（看起来正在做真实项目）→ "
                     "idea.md / method.md 里的项目内容会被一起打包进模板")
    return warns


def clean_target(target: Path, force: bool) -> tuple[bool, list[str]]:
    """按上次的清单清掉生成物。返回 (是否可继续, 保留下来的意外文件)。"""
    if not target.exists():
        return True, []
    manifest_path = target / MANIFEST
    if not manifest_path.exists():
        if not force:
            print(f"[err] {target.relative_to(REPO)} 已存在但不是本脚本生成的（没有 {MANIFEST}）。"
                  "手写的变体不要覆盖；确认要重建请加 --force。", file=sys.stderr)
            return False, []
        shutil.rmtree(target)
        return True, []

    try:
        previous = json.loads(manifest_path.read_text(encoding="utf-8")).get("files", [])
    except (OSError, ValueError):
        previous = []
    for rel in previous:
        path = target / rel
        if path.is_file():
            path.unlink()
    manifest_path.unlink(missing_ok=True)
    leftovers = [p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()]
    for directory in sorted((p for p in target.rglob("*") if p.is_dir()), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()
    return True, leftovers


def make_zip(name: str, target: Path) -> Path:
    dest = VARIANTS / f"{name}.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(target.rglob("*")):
            if path.is_file():
                z.write(path, f"{name}/{path.relative_to(target).as_posix()}")
    return dest


def main() -> int:
    args = sys.argv[1:]
    force = "--force" in args
    no_zip = "--no-zip" in args
    positional = [a for a in args if not a.startswith("--")]
    name = positional[0] if positional else "research"
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", name):
        print(f"[err] 变体名只允许小写字母/数字/-._，收到 {name!r}", file=sys.stderr)
        return 1

    for warn in preflight():
        print(f"[warn] {warn}")

    target = VARIANTS / name
    ok, leftovers = clean_target(target, force)
    if not ok:
        return 2

    files = iter_source_files()
    for rel in files:
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        override = content_for(rel)
        if override is None:
            shutil.copy2(REPO / rel, dest)
        else:
            dest.write_text(override, encoding="utf-8")

    written = sorted(rel.as_posix() for rel in files)
    (target / MANIFEST).write_text(
        json.dumps(
            {
                "generated_by": "tools/make_variant.py",
                "generated_at": now_cn().strftime("%Y-%m-%d %H:%M"),
                "source": "repo root",
                "files": written,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    print(f"[ok] {target.relative_to(REPO)}/  ← {len(written)} 个文件（项目状态已复位为空模板）")
    for rel in leftovers:
        print(f"[keep] {target.relative_to(REPO)}/{rel}（不在上次清单里，已保留）")
    if not no_zip:
        dest = make_zip(name, target)
        size = dest.stat().st_size / 1024
        print(f"[ok] {dest.relative_to(REPO)}（{size:.0f} KB，解压出来就是 {name}/）")
    print(f"[next] 开新项目：把 variants/{name}/ 整个拷走 → git init → "
          "bash tools/install_hooks.sh → 用 Claude Code 打开")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Lint protocol Markdown files.

Errors（任何状态下都报，exit 1）:
- 坏格式 EXP id（应为 EXP-YYYYWww-NNN）
- 坏格式 DISC id（应为 DISC-YYYYWww-NNN）
- Discussion 文件标记 Resolved 但 Decision 缺内容

Warnings（仅初始化后，即 bootstrap.md 已删除；默认 exit 0，--strict 时升级为 error）:
- 未填的 `[填写...]` 占位符
- 残留的 YYYY-MM-DD / YYYY-Www / NNN 字面占位
- LOGS 周文件中 EXP 块必填字段为空（假设 / 是否被驳斥 / 结论 / command / 关联议题）
- LOGS/YYYY-Www-activity.md 里不符合流水行格式的记录（§ 5.3）
- idea.md § 7 人话版与 § 1–5 脱节（§ 4.3，判定见 tools/eli5_sync.py）
- TIMELINE.md 的图与节点表不同步、或 tools/timeline.py 报出绕圈告警（§ 12）

永久模板文件（AGENTS.md、各 README、bootstrap.md、Discussion.md、tools/templates/）
豁免 warning；格式类 error 对所有文件生效。
含 `例：` / `示例` 的行跳过 warning 检查。

Usage:
    python tools/lint_protocol.py                     # lint all（warning 不阻塞）
    python tools/lint_protocol.py --strict LOGS/      # Reflect 后置：warning 也算失败
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

# 这些文件本身就是模板/协议文档，占位符是刻意保留的 —— 永久豁免 warning。
# Discussion.md 的生命周期包含"关闭后重置回模板态"，因此同样豁免占位 warning
# （格式 error 与 Resolved/Decision 检查仍然生效）。
ALWAYS_TEMPLATE = {
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "bootstrap.md",
    "Discussion.md",
    "tools/templates/Discussion.template.md",
    "LOGS/README.md",
    "tools/README.md",
    "ref/README.md",
    "ref/notes/README.md",
    "code/README.md",
    "baseline/README.md",
    "Discussion/Archive/README.md",
}

PLACEHOLDER_RE = re.compile(r"\\?\[填写[^\]]*\\?\]")
DATE_PLACEHOLDER_RE = re.compile(r"YYYY-MM-DD")
WEEK_PLACEHOLDER_RE = re.compile(r"YYYY-Www|YYYYWww")
NNN_RE = re.compile(r"\bNNN\b")
EXP_BAD_RE = re.compile(r"EXP-(?!\d{4}W\d{2}-\d{3})\S+")
DISC_BAD_RE = re.compile(r"DISC-(?!\d{4}W\d{2}-\d{3})\S+")
STUBS = ("YYYYWww", "YYYY-Www", "NNN", "...", "ID", "*")
EXAMPLE_MARKERS = ("例：", "例:", "示例")
WEEK_FILE_RE = re.compile(r"^LOGS/\d{4}-W\d{2}\.md$")
ACTIVITY_FILE_RE = re.compile(r"^LOGS/\d{4}-W\d{2}-activity\.md$")
TIMELINE_FILE = "TIMELINE.md"
# 流水行（§ 5.3）：- 【User|Agent】【YYYY-MM-DD HH:MM】[类型] 内容
ACTIVITY_LINE_RE = re.compile(
    r"^- 【(?:User|Agent)】【\d{4}-\d{2}-\d{2} \d{2}:\d{2}】"
    r"\[(?:prompt|intent|decision|op|run|result|stop|note)\] \S"
)
T_BAD_RE = re.compile(r"\bT-(?!\d{4}W\d{2}-\d{3})\S+")

EXP_REQUIRED = ("假设", "是否被驳斥", "结论", "command", "关联议题")
EMPTY_VALUES = {
    "",
    "Y / N / 部分",
    "Y / N / 部分 / Crashed",
    "DISC-NNN",
    "DISC-YYYYWww-NNN",
    "bash ...",
}


def relevant_md_files(roots: list[Path]) -> list[Path]:
    """收集待检查的 md。

    `variants/` 下的每个变体都是自包含仓库（各自带 bootstrap / 各自的 ID 规范），
    从根目录扫时跳过它们；显式传 `variants/<name>` 则照常检查。
    """
    files = []
    for root in roots:
        if root.is_file() and root.suffix == ".md":
            files.append(root)
        elif root.is_dir():
            for p in root.rglob("*.md"):
                rel = p.relative_to(root).parts
                if ".git" in p.parts or "variants" in rel:
                    continue
                files.append(p)
    return files


def format_errors(rel: str, text: str) -> list[str]:
    """坏格式 EXP / DISC id（占位 stub 除外）。"""
    issues = []
    for bad_re, expect in ((EXP_BAD_RE, "EXP-YYYYWww-NNN"), (DISC_BAD_RE, "DISC-YYYYWww-NNN")):
        for m in bad_re.finditer(text):
            token = m.group(0)
            if any(stub in token for stub in STUBS):
                continue
            issues.append(f"{rel}: 格式错误 {token!r}（应为 {expect}）")
    return issues


def resolved_errors(rel: str, text: str) -> list[str]:
    """Discussion 文件：Status=Resolved 但 Decision 没有实际内容。"""
    if not rel.startswith("Discussion"):
        return []
    status_m = re.search(r"\*\*状态 \(Status\)\*\*\s*\|([^|\n]*)\|", text)
    cell = status_m.group(1) if status_m else ""
    # 模板态的 Status 单元格同时含 Open / Resolved，跳过
    if "Resolved" not in cell or "Open" in cell:
        return []
    m = re.search(r"\*\*Decision\*\*[:：](.*)", text)
    value = m.group(1).strip() if m else ""
    if value and "一段话说明最终结论" not in value:
        return []
    return [f"{rel}: 状态为 Resolved 但 Decision 缺内容"]


def placeholder_warnings(rel: str, text: str) -> list[str]:
    """初始化后仍残留的占位符（每行最多报一条；示例行跳过）。"""
    warns = []
    checks = (
        (PLACEHOLDER_RE, "未填占位符 [填写...]"),
        (DATE_PLACEHOLDER_RE, "字面日期占位 YYYY-MM-DD"),
        (WEEK_PLACEHOLDER_RE, "字面周占位 YYYY-Www"),
        (NNN_RE, "未填序号占位 NNN"),
    )
    for i, line in enumerate(text.splitlines(), 1):
        if any(mark in line for mark in EXAMPLE_MARKERS):
            continue
        for regex, label in checks:
            if regex.search(line):
                warns.append(f"{rel}:{i}: {label}")
                break
    return warns


def exp_block_warnings(rel: str, text: str) -> list[str]:
    """LOGS 周文件：每个 EXP 块的必填字段非空（§ 5.2「所有字段必填」的机械防线）。"""
    warns = []
    blocks = re.split(r"(?=^### EXP-)", text, flags=re.MULTILINE)
    for block in blocks:
        if not block.startswith("### EXP-"):
            continue
        exp_id = block.splitlines()[0].removeprefix("### ").strip()
        for key in EXP_REQUIRED:
            line = next(
                (l for l in block.splitlines() if ":" in l and key in l.split(":", 1)[0]),
                None,
            )
            if line is None:
                warns.append(f"{rel}: {exp_id} 缺字段 '{key}'")
                continue
            value = line.split(":", 1)[1].strip().strip("`")
            if value in EMPTY_VALUES or value.startswith("<"):
                warns.append(f"{rel}: {exp_id} 字段 '{key}' 未填")
    return warns


def timeline_errors(rel: str, text: str) -> list[str]:
    """TIMELINE.md 里的坏格式节点 ID（只在这个文件里查，避免误伤正文里的 T-SNE 之类）。"""
    if rel != TIMELINE_FILE:
        return []
    issues = []
    for i, line in enumerate(text.splitlines(), 1):
        if any(mark in line for mark in EXAMPLE_MARKERS):
            continue
        for m in T_BAD_RE.finditer(line):
            token = m.group(0)
            if any(stub in token for stub in STUBS) or "<" in token:
                continue
            issues.append(f"{rel}:{i}: 格式错误 {token!r}（应为 T-YYYYWww-NNN）")
    return issues


def activity_warnings(rel: str, text: str) -> list[str]:
    """流水行格式（§ 5.3）——只增不改的文件，格式错了要当场看见。"""
    warns = []
    for i, line in enumerate(text.splitlines(), 1):
        if line.startswith("- ") and not ACTIVITY_LINE_RE.match(line):
            warns.append(
                f"{rel}:{i}: 流水行格式不对（应为 `- 【User|Agent】【YYYY-MM-DD HH:MM】[类型] 内容`，"
                "见 AGENTS.md § 5.3）"
            )
    return warns


def eli5_warnings(rel: str) -> list[str]:
    """idea.md § 7 人话版是否跟得上 § 1–5（§ 4.3）。"""
    if rel != "idea.md":
        return []
    try:
        import eli5_sync
    except Exception:
        return []
    try:
        code, msg = eli5_sync.status()
    except Exception:
        return []
    return [] if code in ("ok", "no-idea") else [f"{rel}: {msg}"]


def timeline_warnings(rel: str) -> list[str]:
    """图是否与节点表同步 + 绕圈告警（§ 12）。"""
    if rel != TIMELINE_FILE:
        return []
    try:
        import timeline
    except Exception:
        return []
    warns = []
    try:
        raw = timeline.read(timeline.TIMELINE)
        nodes = timeline.load(raw)
        if timeline.rendered(raw, nodes) != raw:
            warns.append(f"{rel}: 图与节点表不一致 → `python3 tools/timeline.py render`")
        for code, msg in timeline.check(nodes):
            warns.append(f"{rel}: {code} {msg}")
    except Exception as exc:  # 图/表解析失败不该让整个 lint 崩掉
        warns.append(f"{rel}: timeline 检查失败（{exc}）")
    return warns


def main() -> int:
    args = sys.argv[1:]
    strict = "--strict" in args
    paths = [a for a in args if a != "--strict"]
    roots = [REPO / p for p in paths] if paths else [REPO]
    initialized = not (REPO / "bootstrap.md").exists()

    files = relevant_md_files(roots)
    errors: list[str] = []
    warnings: list[str] = []
    for f in files:
        rel = f.relative_to(REPO).as_posix()
        text = f.read_text(encoding="utf-8", errors="replace")
        errors.extend(format_errors(rel, text))
        errors.extend(resolved_errors(rel, text))
        errors.extend(timeline_errors(rel, text))
        if ACTIVITY_FILE_RE.match(rel):
            # 流水是用户原话的逐字记录，不是待填模板：只查行格式，不查占位符。
            if initialized:
                warnings.extend(activity_warnings(rel, text))
            continue
        if initialized and rel not in ALWAYS_TEMPLATE:
            warnings.extend(placeholder_warnings(rel, text))
            if WEEK_FILE_RE.match(rel):
                warnings.extend(exp_block_warnings(rel, text))
            warnings.extend(eli5_warnings(rel))
            warnings.extend(timeline_warnings(rel))

    for line in errors:
        print(f"[err]  {line}")
    for line in warnings:
        print(f"[warn] {line}")

    failed = bool(errors) or (strict and bool(warnings))
    if not errors and not warnings:
        print(f"[ok] scanned {len(files)} file(s), no issues")
    else:
        tag = "fail" if failed else "ok-with-warnings"
        print(f"\n[{tag}] {len(errors)} error(s), {len(warnings)} warning(s) across {len(files)} file(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

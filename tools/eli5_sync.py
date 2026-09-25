#!/usr/bin/env python3
"""idea.md § 7「人话版 (ELI5)」的同步戳（AGENTS.md § 4.3）。

§ 1–5 是写给同行看的，§ 7 是写给外行（和三个月后的自己）看的。两边容易脱节——
本脚本给 § 1–5 算一个内容哈希盖在 § 7 上，改了正文没重写人话版就会被机械抓到。

    python3 tools/eli5_sync.py            # 看状态
    python3 tools/eli5_sync.py --check    # 不同步则 exit 1（lint / 会话自检用）
    python3 tools/eli5_sync.py --stamp    # 重写完人话版后盖戳

哈希只覆盖 § 1–5（§ 6 演进记录、§ 7 自身的变动不触发"过期"）。
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from session_check import REPO, now_cn, read  # noqa: E402

IDEA = REPO / "idea.md"
ELI5_HEADING_RE = re.compile(r"^## 7\.", re.MULTILINE)
SOURCE_START_RE = re.compile(r"^## 1\.", re.MULTILINE)
SOURCE_END_RE = re.compile(r"^## (?:6|7)\.", re.MULTILINE)
STAMP_RE = re.compile(r"^- \*\*同步戳[^*\n]*\*\*[:：]?\s*.*$", re.MULTILINE)
HASH_IN_STAMP_RE = re.compile(r"source-hash[:：]\s*`?([0-9a-f]{12}|未同步)`?")
UNSYNCED = "未同步"


def source_text(text: str) -> str | None:
    """§ 1–5 的正文（归一化后用于算哈希）。"""
    start = SOURCE_START_RE.search(text)
    if not start:
        return None
    rest = text[start.start():]
    end = SOURCE_END_RE.search(rest, 1)
    body = rest[: end.start()] if end else rest
    lines = [l.strip() for l in body.splitlines()]
    return "\n".join(l for l in lines if l)


def source_hash(text: str | None = None) -> str | None:
    text = read(IDEA) if text is None else text
    body = source_text(text)
    if body is None:
        return None
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:12]


def stamped_hash(text: str | None = None) -> str | None:
    text = read(IDEA) if text is None else text
    m = STAMP_RE.search(text)
    if not m:
        return None
    h = HASH_IN_STAMP_RE.search(m.group(0))
    return h.group(1) if h else None


def status() -> tuple[str, str]:
    """(code, message) —— code ∈ ok / stale / unsynced / missing-stamp / missing-section / no-idea"""
    text = read(IDEA)
    if not text:
        return "no-idea", "idea.md 不存在或读不出来"
    if not ELI5_HEADING_RE.search(text):
        return "missing-section", "idea.md 缺 § 7 人话版（ELI5）→ 从模板补上（AGENTS.md § 4.3）"
    current = source_hash(text)
    if current is None:
        return "missing-section", "idea.md 找不到 § 1（正文起点），无法计算同步戳"
    stamped = stamped_hash(text)
    if stamped is None:
        return "missing-stamp", "idea.md § 7 缺同步戳行 → 补 `- **同步戳 (Sync stamp):** ...` 后跑 `--stamp`"
    if stamped == UNSYNCED:
        return "unsynced", (
            "idea.md § 7 人话版从未同步过 → 跑 `/eli5-idea` 重写人话版，再 "
            "`python3 tools/eli5_sync.py --stamp`（AGENTS.md § 4.3）"
        )
    if stamped != current:
        return "stale", (
            f"idea.md § 1–5 改过但 § 7 人话版没跟上（戳 {stamped} ≠ 正文 {current}）→ "
            "跑 `/eli5-idea` 重写，再 `python3 tools/eli5_sync.py --stamp`"
        )
    return "ok", f"idea.md § 7 人话版与 § 1–5 同步（{current}）"


def stamp() -> int:
    text = read(IDEA)
    if not text:
        print("[err] idea.md 不存在", file=sys.stderr)
        return 2
    current = source_hash(text)
    if current is None or not ELI5_HEADING_RE.search(text):
        print("[err] idea.md 缺 § 1 正文或 § 7 人话版，先补齐结构（AGENTS.md § 4.3）", file=sys.stderr)
        return 2
    line = f"- **同步戳 (Sync stamp):** `source-hash: {current}` · 更新于 `{now_cn().strftime('%Y-%m-%d')}`"
    if STAMP_RE.search(text):
        text = STAMP_RE.sub(line.replace("\\", "\\\\"), text, count=1)
    else:
        idx = ELI5_HEADING_RE.search(text).end()
        eol = text.find("\n", idx)
        text = f"{text[:eol + 1]}\n{line}\n{text[eol + 1:]}"
    IDEA.write_text(text, encoding="utf-8")
    print(f"[ok] idea.md § 7 已盖戳：source-hash {current}")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if "--stamp" in args:
        return stamp()
    code, msg = status()
    tag = "ok" if code == "ok" else "warn"
    print(f"[{tag}] {msg}")
    if "--check" in args:
        return 0 if code == "ok" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

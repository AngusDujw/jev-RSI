#!/usr/bin/env python3
"""使用者 & Agent 流水（AGENTS.md § 5.3）—— LOGS/YYYY-Www-activity.md 的唯一写入口。

每周一份、只增不改。EXP 块记"实验"，TIMELINE 记"主线"，这里记"过程"：
半年后复盘时，前两者告诉你结论，流水告诉你**当时是怎么被一步步推到那个结论的**。

    python3 tools/log_activity.py "改 code/train.py：lr 3e-4 → 1e-4" --ref EXP-2026W10-003
    python3 tools/log_activity.py --actor User --type decision "主指标改成 AUC"
    python3 tools/log_activity.py --type stop "连续 3 次 Crashed，按 § 10 停下来问用户"
    python3 tools/log_activity.py --tail 10        # 回看最近 10 条
    python3 tools/log_activity.py --hook           # Claude Code UserPromptSubmit：静默记录用户原话

行格式：
    - 【User|Agent】【YYYY-MM-DD HH:MM】[类型] 内容 ↪ 关联ID

隐私：`--hook` 会原样保存用户输入（截断到 800 字）。不想记原话就
`export PROTOCOL_NO_PROMPT_LOG=1`；仓库公开前先过一遍流水文件。
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from session_check import LOGS_DIR, REPO, now_cn, read, week_str  # noqa: E402

ACTORS = ("User", "Agent")
TYPES = {
    "prompt": "用户原话（hook 自动记）",
    "intent": "用户意图归纳",
    "decision": "用户拍板（§ 9 的用户决策项）",
    "op": "Agent 实质操作",
    "run": "跑了有副作用的命令",
    "result": "关键结果",
    "stop": "触发 § 10 停下来",
    "note": "备注",
}
REF_RE = re.compile(r"(?:EXP|DISC|T)-\d{4}W\d{2}-\d{3}")
MAX_PROMPT_CHARS = 800

HEADER = """\
# 🧾 Activity · {week_id}（使用者 & Agent 流水 · 只增不改）

> 由 `python3 tools/log_activity.py` 追加（AGENTS.md § 5.3）；Claude Code 的
> `UserPromptSubmit` hook 会自动记下每条用户输入。人工操作也可照格式补记。
>
> 格式：`- 【User|Agent】【YYYY-MM-DD HH:MM】[类型] 内容 ↪ 关联ID`
"""


def target_path() -> Path:
    week = week_str(now_cn().date().isocalendar()[:2])
    return LOGS_DIR / f"{week}-activity.md"


def append(actor: str, kind: str, message: str, refs: list[str]) -> Path:
    path = target_path()
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        week = path.stem.replace("-activity", "")
        path.write_text(HEADER.format(week_id=week), encoding="utf-8")
    stamp = now_cn().strftime("%Y-%m-%d %H:%M")
    tail = f"  ↪ {', '.join(f'`{r}`' for r in refs)}" if refs else ""
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n- 【{actor}】【{stamp}】[{kind}] {message}{tail}")
    return path


def flatten(text: str, limit: int = MAX_PROMPT_CHARS) -> str:
    """一条流水必须是一行：换行折成 ⏎，超长截断（原话完整版在 transcript 里）。"""
    flat = " ⏎ ".join(line.strip() for line in text.strip().splitlines() if line.strip())
    flat = re.sub(r"\s{2,}", " ", flat)
    return flat[: limit - 1] + "…" if len(flat) > limit else flat


def hook_mode() -> int:
    """Claude Code UserPromptSubmit：绝不往 stdout 写东西（会被当成注入上下文），绝不失败。"""
    try:
        if os.environ.get("PROTOCOL_NO_PROMPT_LOG"):
            return 0
        if sys.stdin.isatty():
            return 0
        payload = json.loads(sys.stdin.read() or "{}")
        prompt = flatten(str(payload.get("prompt", "")))
        if prompt:
            append("User", "prompt", prompt, [])
    except Exception:
        pass
    return 0


def tail_mode(count: int) -> int:
    path = target_path()
    if not path.exists():
        print(f"[empty] {path.relative_to(REPO)} 还没有流水")
        return 0
    entries = [l.rstrip() for l in read(path).splitlines() if l.lstrip().startswith("- 【")]
    for line in entries[-count:]:
        print(line[2:].strip())
    return 0


def main() -> int:
    args = sys.argv[1:]
    if "--hook" in args:
        return hook_mode()
    if not args:
        print(__doc__)
        return 1

    def pop(flag: str) -> str | None:
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                print(f"[err] {flag} 后缺少值", file=sys.stderr)
                raise SystemExit(1)
            value = args[i + 1]
            del args[i : i + 2]
            return value
        return None

    tail = pop("--tail")
    if tail is not None:
        return tail_mode(int(tail) if tail.isdigit() else 10)

    actor = pop("--actor") or "Agent"
    kind = pop("--type") or ("prompt" if actor == "User" else "op")
    refs: list[str] = []
    while (ref := pop("--ref")) is not None:
        refs.append(ref)

    if actor not in ACTORS:
        print(f"[err] --actor 只能是 {'/'.join(ACTORS)}", file=sys.stderr)
        return 1
    if kind not in TYPES:
        print(f"[err] --type 只能是 {'/'.join(TYPES)}", file=sys.stderr)
        return 1
    bad = [r for r in refs if not REF_RE.fullmatch(r)]
    if bad:
        print(f"[err] --ref 需要 EXP-/DISC-/T-YYYYWww-NNN 格式，收到 {bad}", file=sys.stderr)
        return 1

    message = flatten(" ".join(a for a in args if not a.startswith("--")))
    if not message:
        print('usage: python3 tools/log_activity.py [--actor User|Agent] [--type <类型>] [--ref ID] "内容"',
              file=sys.stderr)
        return 1

    path = append(actor, kind, message, refs)
    print(f"[ok] logged to {path.relative_to(REPO)}  【{actor}】[{kind}] {message[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

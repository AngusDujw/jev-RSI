#!/usr/bin/env python3
"""研发主线时间线（AGENTS.md § 12）—— TIMELINE.md 的唯一写入口。

一行一个节点 = 主线上一次**状态改变**（不是每次操作，也不是每个实验）。
节点表 append-only：写错了补一个 kind=note 的节点说明，不回改历史行。

    python3 tools/timeline.py add --kind question --topic lr-schedule "学习率是不是瓶颈"
    python3 tools/timeline.py add --kind decision --topic lr-schedule "cosine 胜出" --ref DISC-2026W10-001
    python3 tools/timeline.py render            # 重画 § 1 的 mermaid 图（勿手改图）
    python3 tools/timeline.py render --check    # 图是否与节点表一致（lint 用）
    python3 tools/timeline.py check [--strict]  # 绕圈检测 CIRCLE-1/2/3
    python3 tools/timeline.py list

绕圈检测（§ 12.4）：
    CIRCLE-1  同一 topic 自上次 decision/pivot 起已尝试 >=3 轮仍无结论 —— 原地打转
              （轮数 = max(hypothesis 数, experiment 数)，所以"提问→假设→实验→拍板"不会误报）
    CIRCLE-2  同一 topic 已 decision，之后又冒出 question/hypothesis —— 旧问题被重开
    CIRCLE-3  同一 topic 的未决节点跨 >=3 个 ISO 周 —— 长期悬而未决
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from session_check import REPO, now_cn, read  # noqa: E402

TIMELINE = REPO / "TIMELINE.md"

GRAPH_BEGIN = "<!-- TIMELINE:GRAPH:BEGIN -->"
GRAPH_END = "<!-- TIMELINE:GRAPH:END -->"
TABLE_BEGIN = "<!-- TIMELINE:TABLE:BEGIN -->"
TABLE_END = "<!-- TIMELINE:TABLE:END -->"

NODE_ID_RE = re.compile(r"^T-(\d{4})W(\d{2})-(\d{3})$")
ROW_RE = re.compile(r"^\|\s*`?(T-\d{4}W\d{2}-\d{3})`?\s*\|")
REF_RE = re.compile(r"(?:EXP|DISC)-\d{4}W\d{2}-\d{3}")

# 类型 -> (图标, 中文, mermaid 填充色, 描边色)
KINDS: dict[str, tuple[str, str, str, str]] = {
    "question":   ("❓", "提问", "#fff3bf", "#b08900"),
    "hypothesis": ("🔬", "假设", "#e7f5ff", "#1971c2"),
    "experiment": ("📊", "实验", "#ebfbee", "#2f9e44"),
    "decision":   ("✅", "拍板", "#d3f9d8", "#0b7285"),
    "pivot":      ("🔀", "转向", "#ffe8cc", "#e8590c"),
    "blocker":    ("⛔", "卡点", "#ffe3e3", "#c92a2a"),
    "note":       ("📝", "备注", "#f1f3f5", "#868e96"),
}
# 未决类：这些节点只是"在推进"，没有结论
OPEN_KINDS = {"question", "hypothesis", "experiment", "blocker"}
# 主线（粗箭头）：只有拍板与转向才让主线前进一步
SPINE_KINDS = ("decision", "pivot")
# 重开旧问题的信号类型
REOPEN_KINDS = {"question", "hypothesis"}

MAX_LABEL = 22

TEMPLATE = """\
# 🧭 TIMELINE · 研发主线

> 本文件回答三个问题：**主线现在走到哪、怎么走到这里的、有没有在绕圈子。**
> 唯一写入口是 `python3 tools/timeline.py add`（AGENTS.md § 12），图由脚本生成，节点表只增不改。

- **当前主线一句话**：（Agent 每次追加 decision / pivot 节点后同步这一行）

---

## 1. 主线图（自动生成 · 勿手改）

<!-- TIMELINE:GRAPH:BEGIN -->
<!-- TIMELINE:GRAPH:END -->

**读法**：每个方框是一个 ISO 周，从左到右就是研发进度；粗箭头 `==>` 只连
`decision` / `pivot`——**它就是主线**，长时间不长一节 = 没有推进出结论；
细箭头是同一主题内的推进；虚线「重开」是已拍板的问题又被打开（绕圈的典型信号）。

---

## 2. 节点表（append-only）

<!-- TIMELINE:TABLE:BEGIN -->
| 节点 | 日期 | 类型 | 主题键 | 一句话 | 关联 | 上游 |
|---|---|---|---|---|---|---|
<!-- TIMELINE:TABLE:END -->

---

## 3. 怎么写

```bash
python3 tools/timeline.py add --kind question --topic lr-schedule "学习率是不是瓶颈"
python3 tools/timeline.py check      # 绕圈检测
```

- **节点 ID**：`T-<年><周>-<序号>`（例：`T-2026W10-001`），由脚本按周分配。
- **类型**：`question` 提问 / `hypothesis` 假设 / `experiment` 改变判断的实验 /
  `decision` 拍板 / `pivot` 方向转弯 / `blocker` 卡住升级 / `note` 事后补充。
- **主题键 (topic)**：绕圈检测的钥匙——**同一件事必须共用同一个 topic**
  （例：`lr-schedule`、`pgd-robustness`）。短、稳定、可复用。
- **关联**：`EXP-...` / `DISC-...`（例：`DISC-2026W10-001`），逗号分隔；没有写 `-`。
- **上游**：父节点 ID（例：`T-2026W10-001`）；留 `-` 时自动接到同 topic 的上一个节点。
"""


@dataclass
class Node:
    nid: str
    day: str
    kind: str
    topic: str
    text: str
    refs: str
    parents: list[str]

    @property
    def week(self) -> str:
        m = NODE_ID_RE.match(self.nid)
        return f"{m.group(1)}-W{m.group(2)}" if m else "unknown"

    @property
    def mid(self) -> str:
        """mermaid 节点 id（不能带减号）"""
        return self.nid.replace("-", "_")


# --------------------------------------------------------------------------- io


def load(text: str | None = None) -> list[Node]:
    """解析节点表（只认 TABLE 标记之间的行；无标记时退化为全文扫描）。"""
    text = read(TIMELINE) if text is None else text
    if not text:
        return []
    if TABLE_BEGIN in text and TABLE_END in text:
        body = text.split(TABLE_BEGIN, 1)[1].split(TABLE_END, 1)[0]
    else:
        body = text

    nodes: list[Node] = []
    for line in body.splitlines():
        if not ROW_RE.match(line.strip()):
            continue
        cells = [c.strip().strip("`").strip() for c in line.strip().strip("|").split("|")]
        cells += [""] * (7 - len(cells))
        parents = [p.strip().strip("`") for p in re.split(r"[,，]", cells[6]) if p.strip() not in ("", "-")]
        nodes.append(
            Node(
                nid=cells[0],
                day=cells[1],
                kind=cells[2].lower(),
                topic=cells[3],
                text=cells[4],
                refs=cells[5],
                parents=parents,
            )
        )
    nodes.sort(key=lambda n: (n.day or "9999-99-99", n.nid))
    return nodes


def slugify(raw: str) -> str:
    s = raw.strip().lower()
    s = re.sub(r"[\s_/]+", "-", s)
    s = re.sub(r"[^0-9a-z一-鿿-]+", "", s)
    return re.sub(r"-{2,}", "-", s).strip("-")


def ensure_file() -> str:
    if not TIMELINE.exists():
        TIMELINE.write_text(TEMPLATE, encoding="utf-8")
        print(f"[ok] created {TIMELINE.relative_to(REPO)}")
    return read(TIMELINE)


# ----------------------------------------------------------------------- render


def _label(node: Node) -> str:
    icon, _, _, _ = KINDS.get(node.kind, KINDS["note"])
    text = re.sub(r'["`\[\]{}|<>]', "", node.text).strip()
    if len(text) > MAX_LABEL:
        text = text[: MAX_LABEL - 1] + "…"
    topic = re.sub(r'["`\[\]{}|<>]', "", node.topic)
    return f"{icon} {topic}<br/>{text}" if topic else f"{icon} {text}"


def _edges(nodes: list[Node]) -> list[tuple[str, str, str]]:
    """(src, dst, style) —— style: spine / reopen / plain。优先级 spine > reopen > plain。"""
    rank = {"plain": 0, "reopen": 1, "spine": 2}
    best: dict[tuple[str, str], str] = {}
    known = {n.nid for n in nodes}

    def put(src: str, dst: str, style: str) -> None:
        if src not in known or dst not in known or src == dst:
            return
        key = (src, dst)
        if key not in best or rank[style] > rank[best[key]]:
            best[key] = style

    last_of_topic: dict[str, str] = {}
    last_decision: dict[str, str] = {}
    for n in nodes:
        for p in n.parents:
            put(p, n.nid, "plain")
        if not n.parents:
            prev = last_of_topic.get(n.topic)
            decided = last_decision.get(n.topic)
            if decided and n.kind in REOPEN_KINDS:
                put(decided, n.nid, "reopen")
                # 只有"重新打开"的那一下画虚线；之后的节点回到正常链条，
                # 否则一次重开会让整条支线都挂在旧结论上（与 check() 的复位规则一致）。
                last_decision.pop(n.topic, None)
            elif prev:
                put(prev, n.nid, "plain")
        last_of_topic[n.topic] = n.nid
        if n.kind == "decision":
            last_decision[n.topic] = n.nid
        elif n.kind == "pivot":
            # 明说了在转向：之后重开这条线是合法的，不再画"重开"虚线。
            last_decision.pop(n.topic, None)

    spine = [n for n in nodes if n.kind in SPINE_KINDS]
    for a, b in zip(spine, spine[1:]):
        put(a.nid, b.nid, "spine")

    return [(s, d, style) for (s, d), style in best.items()]


def mermaid(nodes: list[Node]) -> str:
    out = ["```mermaid", "graph LR"]
    for kind, (_, _, fill, stroke) in KINDS.items():
        out.append(f"  classDef {kind} fill:{fill},stroke:{stroke},color:#212529")
    out.append("  classDef empty fill:#f8f9fa,stroke:#adb5bd,color:#868e96")

    if not nodes:
        out.append('  EMPTY["（暂无节点 · tools/timeline.py add）"]:::empty')
        out.append("```")
        return "\n".join(out)

    weeks: list[str] = []
    for n in nodes:
        if n.week not in weeks:
            weeks.append(n.week)
    for week in weeks:
        # id 前缀 wk_：mermaid 的子图 id 不宜以数字开头
        out.append(f'  subgraph wk_{week.replace("-", "_")}["{week}"]')
        out.append("    direction TB")
        for n in nodes:
            if n.week == week:
                kind = n.kind if n.kind in KINDS else "note"
                out.append(f'    {n.mid}["{_label(n)}"]:::{kind}')
        out.append("  end")

    by_id = {n.nid: n for n in nodes}
    for src, dst, style in _edges(nodes):
        a, b = by_id[src].mid, by_id[dst].mid
        if style == "spine":
            out.append(f"  {a} ==> {b}")
        elif style == "reopen":
            out.append(f"  {a} -. 重开 .-> {b}")
        else:
            out.append(f"  {a} --> {b}")
    out.append("```")
    return "\n".join(out)


def rendered(text: str, nodes: list[Node]) -> str:
    """把 GRAPH 标记之间的内容替换为最新的 mermaid 图。"""
    graph = mermaid(nodes)
    if GRAPH_BEGIN not in text or GRAPH_END not in text:
        return text
    head, rest = text.split(GRAPH_BEGIN, 1)
    _, tail = rest.split(GRAPH_END, 1)
    return f"{head}{GRAPH_BEGIN}\n{graph}\n{GRAPH_END}{tail}"


# ------------------------------------------------------------------------ check


def check(nodes: list[Node] | None = None) -> list[tuple[str, str]]:
    """绕圈检测（§ 12.4）。返回 [(code, message)]。"""
    nodes = load() if nodes is None else nodes
    findings: list[tuple[str, str]] = []
    topics: dict[str, list[Node]] = {}
    for n in nodes:
        topics.setdefault(n.topic or "(无主题键)", []).append(n)

    for topic, seq in topics.items():
        decided: Node | None = None
        open_nodes: list[Node] = []
        for n in seq:
            if n.kind == "decision":
                decided, open_nodes = n, []
                continue
            if n.kind == "pivot":
                # 明说了在转向 —— 合法地重开这条线
                decided, open_nodes = None, []
                continue
            if decided is not None and n.kind in REOPEN_KINDS:
                findings.append((
                    "CIRCLE-2",
                    f"topic={topic}：{decided.nid}（decision · {decided.day}）之后又出现 "
                    f"{n.nid}（{n.kind} · {n.day}）——旧问题被重开。是真有新证据，还是在绕圈？"
                    "（§ 10：必须停下来问用户；确认是有意转向就先补一个 pivot 节点）",
                ))
                decided = None
            if n.kind in OPEN_KINDS:
                open_nodes.append(n)

        # 轮数取 max(假设数, 实验数)：一条健康的「提问→假设→实验→拍板」只算 1 轮，
        # 反复换假设重跑、或同一假设连跑多次都不收口，才算原地打转。
        rounds = max(
            sum(1 for n in open_nodes if n.kind == "hypothesis"),
            sum(1 for n in open_nodes if n.kind == "experiment"),
        )
        if rounds >= 3:
            findings.append((
                "CIRCLE-1",
                f"topic={topic}：{open_nodes[0].nid} 起已尝试 {rounds} 轮（共 {len(open_nodes)} 个未决节点）"
                "仍无 decision——原地打转，本次会话要给收敛方案（§ 12.4）",
            ))
        weeks = {n.week for n in open_nodes}
        if len(weeks) >= 3:
            findings.append((
                "CIRCLE-3",
                f"topic={topic}：未决节点已跨 {len(weeks)} 个周（{min(weeks)} → {max(weeks)}）"
                "——长期悬而未决，写进 Weekly Retro 要求收敛或明确挂起（§ 6）",
            ))
    return findings


def briefing_lines() -> list[str]:
    """给 session_check 的会话简报用。"""
    if not TIMELINE.exists():
        return ["- 主线 Timeline：TIMELINE.md 缺失 → `python3 tools/timeline.py render` 会按模板生成（§ 12）"]
    nodes = load()
    if not nodes:
        return [
            "- 主线 Timeline：暂无节点 → 开议题 / 拍板后由 `tools/timeline.py add` 落一个节点（§ 12.2）"
        ]
    last = nodes[-1]
    icon, cn, _, _ = KINDS.get(last.kind, KINDS["note"])
    lines = [
        f"- 主线 Timeline：{len(nodes)} 节点，最新 {last.nid} {icon}{cn} [{last.topic}] "
        f"{last.day} {last.text[:40]}"
    ]
    for code, msg in check(nodes)[:3]:
        lines.append(f"- ⚠ 绕圈告警 {code}：{msg}")
    return lines


# ---------------------------------------------------------------------- command


def cmd_add(kind: str, topic: str, text: str, refs: list[str], parents: list[str], day: str | None) -> int:
    if kind not in KINDS:
        print(f"[err] --kind 必须是 {'/'.join(KINDS)}，收到 {kind!r}", file=sys.stderr)
        return 1
    topic = slugify(topic)
    if not topic:
        print("[err] --topic 不能为空（它是绕圈检测的钥匙，同一件事复用同一个 topic）", file=sys.stderr)
        return 1
    text = " ".join(text.split()).replace("|", "/")
    if not text:
        print("[err] 一句话描述不能为空", file=sys.stderr)
        return 1

    raw = ensure_file()
    if TABLE_BEGIN not in raw or TABLE_END not in raw:
        print(f"[err] {TIMELINE.name} 缺少 {TABLE_BEGIN} / {TABLE_END} 标记，无法定位节点表。", file=sys.stderr)
        return 2

    day = day or now_cn().strftime("%Y-%m-%d")
    year, week, _ = now_cn().date().isocalendar()
    if day != now_cn().strftime("%Y-%m-%d"):
        try:
            from datetime import date as _date

            year, week, _ = _date.fromisoformat(day).isocalendar()
        except ValueError:
            print(f"[err] --date 需要 YYYY-MM-DD 格式，收到 {day!r}", file=sys.stderr)
            return 1
    week_short = f"{year}W{week:02d}"

    nodes = load(raw)
    used = [int(m.group(3)) for m in (NODE_ID_RE.match(n.nid) for n in nodes)
            if m and f"{m.group(1)}W{m.group(2)}" == week_short]
    nid = f"T-{week_short}-{max(used, default=0) + 1:03d}"

    bad_refs = [r for r in refs if not REF_RE.fullmatch(r)]
    if bad_refs:
        print(f"[err] --ref 需要 EXP-YYYYWww-NNN / DISC-YYYYWww-NNN 格式，收到 {bad_refs}", file=sys.stderr)
        return 1
    known = {n.nid for n in nodes}
    bad_parents = [p for p in parents if p not in known]
    if bad_parents:
        print(f"[err] --parent 不在节点表里：{bad_parents}", file=sys.stderr)
        return 1

    ref_cell = ", ".join(f"`{r}`" for r in refs) or "-"
    parent_cell = ", ".join(f"`{p}`" for p in parents) or "-"
    row = f"| `{nid}` | {day} | {kind} | {topic} | {text} | {ref_cell} | {parent_cell} |\n"

    head, tail = raw.split(TABLE_END, 1)
    if not head.endswith("\n"):
        head += "\n"
    updated = rendered(f"{head}{row}{TABLE_END}{tail}", load(f"{head}{row}{TABLE_END}{tail}"))
    TIMELINE.write_text(updated, encoding="utf-8")

    icon, cn, _, _ = KINDS[kind]
    print(f"[ok] {nid} {icon}{cn} [{topic}] {text}")
    findings = check(load(updated))
    for code, msg in findings:
        print(f"[circle] {code} {msg}")
    if kind in SPINE_KINDS:
        print("[next] 主线动了：同步 TIMELINE.md 顶部「当前主线一句话」。")
    return 0


def cmd_render(check_only: bool) -> int:
    raw = ensure_file()
    updated = rendered(raw, load(raw))
    if check_only:
        if updated != raw:
            print("[err] TIMELINE.md 的图与节点表不一致 → `python3 tools/timeline.py render`", file=sys.stderr)
            return 1
        print("[ok] 图与节点表一致")
        return 0
    if updated == raw:
        print("[skip] 图已是最新")
        return 0
    TIMELINE.write_text(updated, encoding="utf-8")
    print(f"[ok] re-rendered {TIMELINE.relative_to(REPO)}")
    return 0


def cmd_check(strict: bool) -> int:
    nodes = load()
    findings = check(nodes)
    topics = {n.topic for n in nodes}
    for code, msg in findings:
        print(f"[circle] {code} {msg}")
    if not findings:
        print(f"[ok] 无绕圈迹象（{len(nodes)} 个节点 / {len(topics)} 个主题）")
        return 0
    print(f"\n[{'fail' if strict else 'warn'}] {len(findings)} 条绕圈告警（AGENTS.md § 12.4 / § 10）")
    return 1 if strict else 0


def cmd_list() -> int:
    nodes = load()
    if not nodes:
        print("[empty] 还没有节点")
        return 0
    for n in nodes:
        icon, cn, _, _ = KINDS.get(n.kind, KINDS["note"])
        refs = f"  ↪ {n.refs}" if n.refs and n.refs != "-" else ""
        print(f"{n.nid}  {n.day}  {icon}{cn}  [{n.topic}]  {n.text}{refs}")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    cmd, rest = args[0], args[1:]

    def pop(flag: str) -> str | None:
        if flag in rest:
            i = rest.index(flag)
            if i + 1 >= len(rest):
                print(f"[err] {flag} 后缺少值", file=sys.stderr)
                raise SystemExit(1)
            value = rest[i + 1]
            del rest[i : i + 2]
            return value
        return None

    def pop_all(flag: str) -> list[str]:
        out = []
        while (v := pop(flag)) is not None:
            out.append(v)
        return out

    if cmd == "add":
        kind = pop("--kind") or "note"
        topic = pop("--topic") or ""
        day = pop("--date")
        refs = pop_all("--ref")
        parents = pop_all("--parent")
        free = [a for a in rest if not a.startswith("--")]
        if not free:
            print('usage: python3 tools/timeline.py add --kind <类型> --topic <主题键> "一句话"', file=sys.stderr)
            return 1
        return cmd_add(kind, topic, " ".join(free), refs, parents, day)
    if cmd == "render":
        return cmd_render("--check" in rest)
    if cmd == "check":
        return cmd_check("--strict" in rest)
    if cmd == "list":
        return cmd_list()
    print(f"[err] unknown subcommand: {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

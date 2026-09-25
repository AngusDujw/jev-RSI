# LOGS 说明（按周记录）

- `LOGS/` 采用周维度记录，一周两个文件：
  - **实验日志** `YYYY-Www.md`（例：`2026-W10.md`）——一周内所有 EXP 块追加在这里。
  - **流水** `YYYY-Www-activity.md`——使用者与 Agent 的操作明细（见下方「使用者 & Agent 流水」）。
- 三层记录各管一件事：**EXP 块记"实验"，`TIMELINE.md` 记"主线"（AGENTS.md § 12），流水记"过程"。**

## 实验 ID 格式（唯一标准）

- **`EXP-YYYYWww-NNN`**（例：`EXP-2026W10-001`，三位序号）。
- `YYYY` = 年（4 位），`ww` = ISO 周序（2 位），`NNN` = 当周内序号（3 位，从 001 起）。
- 全协议（`AGENTS.md`、`method.md`、`Discussion.md`、`LOGS/*`）统一使用此格式。

## 每条实验必填字段（强制）

```
### EXP-YYYYWww-NNN

- 源意图 (Original Vibe):
- 假设 (Hypothesis):
- 是否被驳斥 (Falsified?):   Y / N / 部分 / Crashed
- 驳斥/支持原因 (Why):
- Agent 动作 (What changed):
- 复现信息 (Repro):
  - commit:                 <git sha 或 dirty>
  - seed:                   <int 或 N/A>
  - dataset / version:
  - env:                    <python/cuda/key libs>
  - hardware:               <GPU/CPU>
  - command:                `bash ...`
- 关键指标 (Metrics):
- 日志路径 (Artifacts):     <wandb / 文件路径>
- 结论 (Conclusion, 1–3 句):
- 下一步 (Next):
- 关联议题 (Discussion):     DISC-YYYYWww-NNN
```

## 负结果原则

- `Falsified=Y` 的实验同样必须完整记录，**不允许悄悄删除或重命名**。
- 负结果与正结果同等重要——半年后回看，最有价值的往往是"我们当时验证了 X 不行"。
- **跑崩也要记**：跑崩 / 不收敛而中止的实验记 `Falsified=Crashed`，块内容可精简，但 `commit / command / Why（崩溃现象）` 必填。`AGENTS.md § 10` 的"连续 3 次跑崩"就以这里的连续 `Crashed` 记录机械计数。

## 使用者 & Agent 流水（`YYYY-Www-activity.md`）

只增不改，一行一条：

```
- 【User】【2026-03-02 10:31】[decision] 主指标改成 AUC
- 【Agent】【2026-03-02 10:33】[op] 改 code/train.py：lr 3e-4 → 1e-4  ↪ `EXP-2026W10-003`
```

- **类型**：`prompt`（用户原话，hook 自动记）/ `intent` / `decision`（用户拍板）/ `op`（Agent 实质操作）/ `run` / `result` / `stop`（§ 10 升级）/ `note`。
- **写入口**：`python3 tools/log_activity.py "内容" [--actor User] [--type decision] [--ref EXP-...]`；`--tail 10` 回看最近 10 条。
- **Claude Code 会自动记用户原话**（`UserPromptSubmit` hook）。不想记原话：`export PROTOCOL_NO_PROMPT_LOG=1`。仓库公开前先过一遍这个文件。
- **为什么值得**：EXP 块告诉你结论，流水告诉你**当时是怎么被一步步推到那个结论的**——包括没变成实验的判断、被否掉的方向、用户当场改的主意。每次会话开头 `session_check.py` 会回放最近 3 条，Agent 靠它接上上一轮的上下文。

## 新建周志 / 实验块

使用 `tools/` 下脚本：
- `python tools/new_week.py` — 新建当周 `LOGS/YYYY-Www.md`（如果不存在）。
- `python tools/new_exp.py "源意图"` — 在当周文件追加一个填好骨架的 EXP 块（自动写入下一个 `NNN`、commit hash、主机名、当前 active 议题号）。
- `python3 tools/log_activity.py "做了什么"` — 追加一条流水（自动署名 + 时间戳）。
- `python tools/lint_protocol.py --strict LOGS/` — 检查 EXP 块字段完整性、占位符与流水行格式（Reflect 后置要求清零，见 `AGENTS.md § 4.2`）。

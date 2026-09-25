# Agent-Centric Research Protocol

> 本文件是协议的 **single source of truth**。`CLAUDE.md` 仅是指向本文件的引用。

---

## 0. 核心哲学（必须保留）

- **Agent First**：除高阶科学决策外，重复执行任务由 Agent 主导。
- **Everything is Markdown**：研究过程即文档，关键状态必须落盘到 Markdown。
- **Vibe Alignment**：用户给意图与方向，Agent 负责把意图转成实现与实验。
- **Math-Guided Improvement**：优先让数学指导方法改进；至少要能数学描述与解释。

---

## 1. 核心锚点文件

- `idea.md`：研究问题、动机、目标、实验大图；**§ 7 是同一件事的人话版（ELI5）**，写给外行和三个月后的自己（§ 4.3）。
- `method.md`：方法的数学形式化（损失、假设、推论/定理、解释）+ 变更日志。
- `Discussion.md`：**当前唯一 active 议题**（多人协作主战场，一议题一主线）。
- `Discussion/Archive/`：已关闭议题归档（每议题一个 md）。
- `LOGS/`：按周记录实验（每周一个 `YYYY-Www.md`）+ **使用者 & Agent 流水**（`YYYY-Www-activity.md`，§ 5.3）。
- `TIMELINE.md`：**研发主线时间线**——一行一个节点、自动生成的进度图、机械绕圈检测（§ 12）。
- `MODE.md`：当前协作模式（newbie/expert）、策略与 `last_retro`（上次周回顾的 ISO 周）。
- `code/`：项目主代码目录。
- `baseline/`：Baseline 代码目录（可不存在）。
- `ref/`：论文/资料/笔记（默认不主动扫描；被显式引用时必读，读后笔记沉淀到 `ref/notes/`，详见 § 8）。
- `tools/`：协议辅助脚本（会话自检、新建周志/实验块/议题、流水、时间线、人话版同步戳、占位符 lint）。

---

## 2. 首次初始化（bootstrap 机制）

1. 若仓库存在 `bootstrap.md`，优先执行初始化向导：读取 `bootstrap.md` 并向用户完整呈现其 § 1–2。**引导文本以 `bootstrap.md` 为唯一来源**，hook / 脚本只负责触发，不另存一份文案。
2. 用户在向导中**仅回复 `A` 或 `B`** 选择模式：A=newbie，B=expert。
3. **初始化完成前的边界**：Agent 可以回答关于协议/仓库本身的元问题，但**不得执行任何 P-E-R 动作**（不创建议题、不改 `code/`、不写 LOGS）；每次回复末尾重复 A/B 选择引导，直到用户完成选择。
4. Agent 将选择结果写入 `MODE.md`（`mode / updated_at / set_by / last_retro`）。
5. 完成初始化后删除 `bootstrap.md`。
6. 删除后，后续策略以 `MODE.md` 为准。

### 2.1 跨 Agent 兼容触发规则

- **所有 Agent**（Claude Code / Codex / Cursor / 其他）在进入仓库后的第一条有效回复前，必须先运行并遵循：

  ```bash
  python3 tools/session_check.py
  ```

  该脚本是「会话开始检查」的**唯一实现**，输出三种之一：
  1. `bootstrap.md` 存在 → 初始化指引（读取 `bootstrap.md` 并要求用户仅回复 A 或 B）；
  2. 已初始化 → 会话简报：mode、active 议题、当周 LOGS 状态、是否欠 Weekly Retro（§ 6）；
  3. 协议异常（§ 2.2 第三行）→ 提示用户从模板重建 `bootstrap.md`。
- Claude Code 的 `SessionStart` hook（`.claude/settings.json`）调用的是**同一脚本**，因此不存在"hook 文案"与"手动检查文案"两份拷贝需要维护。
- 若环境没有 python3：退化为手动检查——`bootstrap.md` 存在则读取并向用户呈现其 § 1–2，要求仅回复 A 或 B。
- 用户完成模式选择前，不得进入 P-E-R 循环（允许回答元问题，边界见 § 2 第 3 条）。

### 2.2 模式状态判定（消歧）

| `bootstrap.md` | `MODE.md::mode` | 行为 |
|---|---|---|
| 存在 | 任意 | **未初始化**，必须先走 bootstrap |
| 不存在 | `newbie` 或 `expert` | 按该模式正常工作 |
| 不存在 | `unset` 或缺失 | 视为协议异常，提示用户从模板重建 `bootstrap.md` |

---

## 3. 模式策略（由 MODE.md 驱动）

### 3.1 科研新手模式（newbie）
- 交互：一步一引导，不一次抛太多选项。
- 执行：默认给出最小下一步（single next action）。
- 文档：每完成一步同步写入对应文件。
- 实验：先做小规模验证（Pilot），再扩展。

### 3.2 科研老手模式（expert）
- 交互：结论先行，少解释，多直接执行。
- 执行：以任务批次推进，减少确认轮次。
- 文档：只保留关键变更与结论，避免冗长。
- 实验：直接进入主实验/消融，不强制教学式拆解。

---

## 4. 日常工作循环（P-E-R）

### 4.1 三步循环

1. **Plan**：读取 `MODE.md` + `idea.md` + `Discussion.md`，明确当前唯一问题。
2. **Execute**：修改 `code/`（或 `baseline/` 对照），必要时更新 `method.md`。
3. **Reflect**：在当周 `LOGS/YYYY-Www.md` 追加实验块，并回写 `Discussion.md` 共识。

### 4.2 前置 / 后置检查

| 阶段 | 必须先做 / 必须后做 |
|---|---|
| **Plan 前置** | 先读会话简报里的**本周流水最近几条**与**主线 Timeline 最新节点**——上一轮走到哪、用户拍过什么板，不许凭空重来（§ 5.3 / § 12）；简报若有绕圈告警，按 § 12.4 先处理。若 `Discussion.md` 无 active 议题，先与用户对齐一个并按 § 7 创建；若 `idea.md` 关键字段（One-Sentence Summary / Primary Metric）为空，先按 § 4.3 走 Ideation 流程（含 grill-me 闸门）再继续。 |
| **Execute 后置** | 每次**实质操作**后追加一条流水：`python3 tools/log_activity.py "<做了什么>"`（§ 5.3）；若 `code/` 非空且存在测试入口，运行一次 lint + 单测；任何 method 公式/假设的实质改动必须同步进 `method.md` 并写入其 Changelog（§ 9）。 |
| **Reflect 后置** | 当周 `LOGS/YYYY-Www.md` 至少追加一条完整 EXP 块（按 § 5 字段全填）；运行 `python tools/lint_protocol.py --strict LOGS/<当周>.md`，error 与 warning 清零后 Reflect 才算完成；若该实验影响当前议题结论，必须在 `Discussion.md` 该议题下回帖；**若该实验改变了主线判断**（支持/驳斥了当前假设），追加一个 `experiment` 时间线节点并跑 `python3 tools/timeline.py check`（§ 12）。 |

### 4.3 Ideation 流程：grill-me 闸门（写之前）与人话闸门（写之后）

**适用范围**：任何对 `idea.md` 做**立项级写入**的场合——首次填写、补全 One-Sentence Summary / Primary Metric / Research Objectives、或对研究方向/范围/主指标做实质改写（其中 `idea.md § 2.3 研究目标` / `§ 4.3 主指标` 的改动仍受 § 9 / § 10 约束，需用户拍板，grill-me 闸门不替代用户拍板）。
**不适用**：`idea.md § 6 Agent 追踪专区` 的例行演进记录、错别字/排版修订——这些是日常回写，不触发闸门。

Ideation 流程（有序）：

1. **草拟（Draft）**：与用户对齐研究意图，在工作区/对话里拟出 idea 草稿（先不落盘）。
2. **质询闸门（grill-me gate，强制）**：**在把立项内容写入 `idea.md` 这一“最后写入”动作之前**，Agent 必须自动运行一次 **grill-me** 质询（`/grill-me`，其底层为 `grilling`，见 `.claude/skills/`），针对草稿逐条逼问：问题是否真问题、动机/SOTA gap 是否站得住、目标是否可证伪、主指标是否可测、与 `method.md` 假设是否自洽。一次只问一个问题、给出推荐答案、等用户反馈再继续。
3. **定稿写入（Finalize）**：仅当质询收敛、达成共识后，才执行对 `idea.md` 的最终写入。
4. **人话闸门（ELI5 gate，强制）**：立项内容落盘后、**本次会话结束前**，用 **eli5** 技能（仓库内为 `/eli5-idea`，见 `.claude/skills/`）把 § 1–5 重写成 `idea.md § 7` 的人话版，然后盖同步戳：

   ```bash
   python3 tools/eli5_sync.py --stamp
   ```

   人话版的四步（照 eli5 的方法）：**承重的一句话 → 锚在对方已有的东西上（具体类比）→ 把正式叫法交回去 → 说清类比在哪断**。写完自检：一个完全不做这个方向的人读完，能不能自己复述出"我们在解决什么、凭什么行"？不能就重写。
5. **留痕**：在 `idea.md § 6` 追加一行记录"本次立项已过 grill-me 闸门 + 人话闸门（日期）"，便于复盘。

**不变量**：
- 未经过 grill-me 闸门，不得完成立项级写入。
- 立项级写入之后，`idea.md § 7` 必须重写并盖戳——`§ 1–5` 改了而 § 7 没跟上，`tools/session_check.py` 与 `tools/lint_protocol.py` 会机械报「人话版过期」（判定：§ 1–5 的内容哈希 vs § 7 同步戳，见 `tools/eli5_sync.py`）。
- 若环境无法加载技能（非 Claude Code），降级为 Agent 手动执行等价动作：grill-me → 逐条逼问、单问单答；人话闸门 → 照上面四步手写 § 7 再盖戳。

---

## 5. LOGS 约定（周维度：实验块 + 流水）

### 5.1 命名 & 组织
- `LOGS/` 每周一个文件：`YYYY-Www.md`（例：`2026-W10.md`）。
- 同一周所有实验追加在该文件。
- 实验 ID 统一格式：**`EXP-YYYYWww-NNN`**（例：`EXP-2026W10-001`，三位序号）。

### 5.2 每条 EXP 块必填字段

```
### EXP-YYYYWww-NNN

- 源意图 (Original Vibe):
- 假设 (Hypothesis):
- 是否被驳斥 (Falsified?):      Y / N / 部分 / Crashed
- 驳斥/支持原因 (Why):
- Agent 动作 (What changed):
- 复现信息 (Repro):
  - commit:                   <git sha 或 dirty>
  - seed:                     <int 或 N/A>
  - dataset / version:
  - env:                      <python/cuda/key libs>
  - hardware:                 <GPU/CPU>
  - command:                  `bash ...`
- 关键指标 (Metrics):
- 日志路径 (Artifacts):       <wandb / 文件路径>
- 结论 (Conclusion, 1–3 句):
- 下一步 (Next):
- 关联议题 (Discussion):       DISC-YYYYWww-NNN
```

**负结果原则**：`Falsified=Y` 的实验同样需要完整记录，**不允许悄悄删除或重命名**。负结果与正结果同等重要。

**崩溃同样记录**：跑崩 / 不收敛而中止的实验记 `Falsified=Crashed`，块内容可精简，但 `commit / command / Why（崩溃现象）` 必填。§ 10 的"连续 3 次跑崩"以 LOGS 中同一意图下连续的 `Crashed` 记录为准——机械可数，不依赖 Agent 跨会话记忆。

### 5.3 使用者 & Agent 流水（Activity Log）

`LOGS/YYYY-Www-activity.md`：每周一份、**只增不改**的流水，回答"这一周用户说了什么、Agent 做了什么"。

- **行格式**：`- 【User|Agent】【YYYY-MM-DD HH:MM】[类型] 内容 ↪ 关联ID`
- **类型**：`prompt`（用户原话，hook 自动记）/ `intent`（用户意图归纳）/ `decision`（用户拍板）/ `op`（Agent 实质操作）/ `run`（跑了有副作用的命令）/ `result`（关键结果）/ `stop`（触发 § 10 升级）/ `note`。
- **唯一写入口**：`python3 tools/log_activity.py`（自动署名 + UTC+8 时间戳 + 落到当周文件）。

**必须记的四个时刻**：

| 时刻 | 类型 | 谁记 |
|---|---|---|
| 用户每一条输入 | `prompt` | Claude Code 由 `UserPromptSubmit` hook 自动记；其他 Agent 环境手动补 `--actor User --type prompt` |
| 用户每一次拍板（§ 9 的用户决策项） | `decision` | Agent 当场补记——这是"当时为什么这么定"的第一手证据 |
| Agent 每一次实质操作（改锚点文件 / 改 `code/` / 跑有副作用的命令 / 写 LOGS） | `op` / `run` | Agent（`new_disc.py` / `new_exp.py` 会自动记） |
| 每一次触发 § 10 停下来 | `stop` | Agent，写清触发的是哪一条 |

Agent 侧的纯阅读、纯检索不单独记 `op`——`op` 记的是**改变了世界状态的动作**；用户侧则一条不落（hook 全记）。

> 自动记原话靠 `.claude/settings.json` 里的 `UserPromptSubmit` hook（模板自带，首次会话需批准）；没有 hook 的环境（Codex / Cursor 等），由 Agent 在每轮开头手动补一条 `[prompt]` 或 `[intent]`。

**为什么要记这么细**：EXP 块记"实验"，`TIMELINE.md` 记"主线"，流水记"过程"。半年后复盘时，前两者告诉你结论，流水告诉你**当时是怎么被一步步推到那个结论的**——包括那些没能变成实验的判断、被否掉的方向、用户当场改的主意。它也是每次会话开头 Agent 恢复上下文的地方（`session_check.py` 会回放最近 3 条）。

**隐私**：`[prompt]` 行原样保存用户输入（超长截断到 800 字）。仓库公开前先过一遍流水；不想记原话就 `export PROTOCOL_NO_PROMPT_LOG=1`。

---

## 6. 周回顾（Weekly Retro）

- **触发**：机械判定，由 `tools/session_check.py` 在会话开始时给出——当 `MODE.md::last_retro` 早于当前 ISO 周、且存在更早一周的 `LOGS/YYYY-Www.md` 时，会话简报会标注"欠 Weekly Retro"，Agent 必须在该会话先完成回顾再进入其他工作。
- **动作**：
  1. 扫描上一周 `LOGS/YYYY-W(N-1).md` 所有 EXP；
  2. 按 `Falsified=Y / N / 部分` 分组汇总；
  3. 跑 `python3 tools/timeline.py check`，把 `CIRCLE-*` 告警逐条写进回顾——上周有没有在绕圈、哪个主题必须收敛（§ 12.4）；
  4. 扫一遍上周流水 `LOGS/YYYY-W(N-1)-activity.md`，汇总用户拍过的板（`[decision]`）与触发过的升级（`[stop]`）（§ 5.3）；
  5. 在 `Discussion.md` 当前 active 议题底部追加一条 `【Agent】【日期】Weekly Retro:` 回帖，列出 (a) 已驳斥假设 (b) 已支持假设 (c) 悬而未决问题 (d) 绕圈告警与收敛方案；
  6. 若发现与 `idea.md` / `method.md` 的冲突，必须在 retro 里明确指出并建议对齐方案；
  7. 完成后将 `MODE.md::last_retro` 更新为当前 ISO 周（如 `2026-W24`）。

---

## 7. Discussion.md 多人协作约定（主战场）

详细模板见 `Discussion.md` 本身，此处仅规定不变量：

- **一议题一主线**：根目录 `Discussion.md` 同一时刻只承载 **1 个 active 议题**。
- **议题号**：`DISC-YYYYWww-NNN`，可被 LOGS / method.md / idea.md 反向引用；由 `python tools/new_disc.py open "<标题>"` 统一分配，避免手工撞号。
- **主题键 (Topic)**：开题时由 `--topic` 写进 Issue Header（不给就从标题推）。**同一件事必须复用同一个主题键**——它是 § 12 绕圈检测认"这是同一个老问题"的唯一依据。
- **自动落时间线**：`open` 落一个 `question` 节点，`close` 落一个 `decision` 节点（§ 12.2）；两者都会同时写一条流水（§ 5.3）。
- **状态机**：`Open → Resolved`。无 `Decision` 段不得关闭。
- **角色化发言**：`【PI|Lead|Collab|Agent @名字】【YYYY-MM-DD HH:MM】`。
- **Agent 发言必带硬证据**：链接到 `LOGS/...#EXP-...` 并贴关键数字。
- **关闭流程**：用 `python tools/new_disc.py close "<slug>"` 执行——脚本校验 Resolution 非空后，归档到 `Discussion/Archive/DISC-YYYYWww-NNN-<slug>.md`（文件名含议题号，可反查），并从 `tools/templates/Discussion.template.md` 重置根目录 `Discussion.md`。
- **结论反哺**：议题 `Decision` 必须在 `Resolution.Propagated to` 字段列出反写到 `method.md §` / `idea.md §` / 哪些 `EXP-...`。

---

## 8. ref/ 使用规则

- 默认 **不主动扫描** `ref/`，避免污染上下文。
- **强制读取条件**：当 `idea.md` / `method.md` / `Discussion.md` 中出现 `ref/<path>` 形式的显式引用，Agent 必须读取被引用文件并在下一次发言里反映其内容。
- 用户口头要求时同样必须读。
- **读后沉淀**：每次因引用读取 `ref/<file>` 后，必须在 `ref/notes/<file>.md` 写入/更新要点笔记（核心结论、方法要点、与本项目的关联、可复用公式/数字）。同一文件再次被引用时**先读笔记**，笔记不足再回读原文——避免重复读全文污染上下文。

---

## 9. 决策边界：高阶 vs Agent 自治

| 类别 | 例子 | 谁拍板 |
|---|---|---|
| 修改 loss / 正则形式 | 加入 $\beta\|\nabla f\|^2$ | **用户** |
| 修改假设 / 定理陈述 | 改写 `method.md` § 2 / § 3 | **用户** |
| 引入新 baseline / 新数据集 | 加 NCFM-v2、换 ImageNet→CIFAR | **用户** |
| 改 `idea.md` 研究目标 | 改 Objective 1 | **用户** |
| 关闭 / 开启 Discussion 议题 | 任意 DISC-* | **用户**（Agent 可起草 Decision 草稿） |
| 在 `TIMELINE.md` 记 `decision` / `pivot` 节点 | 宣布主线改变或转向 | **用户**拍板，Agent 落盘 |
| 调超参 / lr / batch / 网格搜索 | 任意 sweep | Agent |
| 跑现有 baseline / 复现 | 复现 NCFM | Agent |
| 数据预处理脚本 | tokenizer、resize | Agent |
| 写 / 修单元测试 | `tests/*` | Agent |
| 整理日志、补 EXP 字段 | 任意 LOGS 编辑 | Agent |
| 记流水、补 `idea.md § 7` 人话版 | 任意 activity / ELI5 编辑 | Agent |
| 在 `TIMELINE.md` 记 `question`/`hypothesis`/`experiment`/`blocker` 节点 | 主线上的过程节点 | Agent |
| 起草 `method.md` Changelog 条目 | 待用户审核 | Agent |

---

## 10. Stop / Escalate 触发条件

满足任一条件时，Agent **必须停下来征求用户**，不得自行继续：

- 任一实验连续 3 次跑崩 / 不收敛（以当周 LOGS 中同一意图下连续的 `Falsified=Crashed` 记录计，见 § 5.2）。
- 与目标 SOTA 的关键指标差距超过用户在 `idea.md` 设定的阈值（若未设，按 ≥10% 触发）。
- 需要修改 `method.md § 2 形式化定义` 或 § 3 关键结论。
- 需要修改 `idea.md` § 2.3 研究目标 或 § 4.3 主指标。
- 单次实验预估开销超过当前预算（用户未设预算时，按"单跑 >2h GPU 或 >5GB 写盘"触发）。
- 涉及"删除已有 EXP 记录"或"重写已 Resolved 议题结论"。
- `python3 tools/timeline.py check` 报出 **`CIRCLE-2`**（已拍板的问题又被打开）——必须停下来问用户：是真有新证据，还是在绕圈？若确认是有意转向，先补一个 `pivot` 节点再继续（§ 12.4）。
- 报出 `CIRCLE-1` / `CIRCLE-3`（同一主题 ≥3 轮无结论 / 未决跨 ≥3 周）——不必停工，但必须在本次会话**显式**向用户报告并给出收敛方案。

---

## 11. 质量与边界

- 涉及定理/推导/SOTA 对比：给出处或推导过程，避免幻觉。
- 若 `idea.md`、`method.md`、`LOGS` 结论冲突：先指出冲突，再建议对齐方案。
- 默认不读取 `ref/`，除非 § 8 条件触发。
- 向用户解释研究本身时，先给 `idea.md § 7` 的人话口径，别把术语直接倒出来（§ 4.3）。

---

## 12. TIMELINE.md（研发主线与绕圈检测）

`TIMELINE.md` 回答三个问题：**主线现在走到哪、怎么走到这里的、有没有在绕圈子。**

### 12.1 一行一个节点

- 节点 = 主线上一次**状态改变**。不是每次操作（那是 § 5.3 流水），也不是每个实验（那是 § 5 LOGS）——只有"让主线往前/往旁边挪了一步"的事才配一个节点。
- 节点 ID：`T-YYYYWww-NNN`（例：`T-2026W10-001`），由 `tools/timeline.py` 按周分配。
- 七种类型：

| 类型 | 含义 | 谁写 |
|---|---|---|
| `question` | 提出一个要回答的问题（通常伴随开议题） | Agent |
| `hypothesis` | 提出一个可证伪的假设 | Agent |
| `experiment` | 一次**改变了主线判断**的实验结果 | Agent |
| `decision` | 拍板：结论确定、议题关闭 | 用户拍板，Agent 落盘 |
| `pivot` | 方向转弯（换问题 / 换指标 / 换路线） | 用户拍板，Agent 落盘 |
| `blocker` | 卡住并升级（§ 10） | Agent |
| `note` | 事后补充说明 | Agent |

- **主题键 (topic)** 是绕圈检测的钥匙：**"其实是同一件事"的节点必须共用同一个 topic**（例：`lr-schedule`、`pgd-robustness`）。短、稳定、可复用；议题的主题键写在 `Discussion.md` Issue Header（§ 7）。
- 节点表 **append-only**：写错了补一个 `note` 节点说明，**不删不改历史行**——理由同 § 5.2 的负结果原则。

### 12.2 什么时候写节点（触发点）

| 触发 | 类型 | 谁执行 |
|---|---|---|
| `python tools/new_disc.py open` 开议题 | `question` | 脚本自动 |
| `python tools/new_disc.py close` 关议题 | `decision` | 脚本自动 |
| 实验支持/驳斥了当前假设（Reflect 后置，§ 4.2） | `experiment` | Agent 手动 |
| 提出新的可证伪假设 | `hypothesis` | Agent 手动 |
| 用户改研究目标 / 主指标 / 换路线（§ 9 用户拍板项） | `pivot` | Agent 落盘 |
| 触发 § 10 停下来 | `blocker` | Agent 落盘 |

```bash
python3 tools/timeline.py add --kind experiment --topic lr-schedule "cosine +1.2% 但方差大" --ref EXP-2026W10-003
```

### 12.3 图（研发进度的可视化）

- `TIMELINE.md § 1` 的 mermaid 图由 `python3 tools/timeline.py render` 生成，落在 `<!-- TIMELINE:GRAPH:* -->` 标记之间——**不要手改**，改了 lint 会报"图与节点表不一致"。
- 怎么读：
  - **按周分组**：每个方框是一个 ISO 周，从左到右就是研发进度。
  - **粗箭头 `==>` 就是主线**：只连 `decision` / `pivot`。主线每前进一步才长一节；**长时间不长 = 这段时间没有推进出任何结论**，这就是"进度"最诚实的度量。
  - **细箭头**是同一主题内的推进（问题 → 假设 → 实验）。
  - **虚线「重开」**是已拍板的问题又被打开——绕圈的典型信号，一眼可见。

### 12.4 绕圈检测（机械判定，不依赖 Agent 记性）

`python3 tools/timeline.py check`（会话开始时 `session_check.py` 自动跑一次，告警直接出现在会话简报里）：

| 代码 | 判定 | 含义 | 动作 |
|---|---|---|---|
| `CIRCLE-1` | 同一 topic 自上次 `decision`/`pivot` 起已尝试 ≥3 轮（轮数 = max(假设数, 实验数)）仍无结论 | 原地打转 | 本次会话显式报告 + 给收敛方案（§ 10） |
| `CIRCLE-2` | 同一 topic 已有 `decision`，之后又出现 `question`/`hypothesis` | 旧问题被重开 | **停下来问用户**（§ 10） |
| `CIRCLE-3` | 同一 topic 的未决节点跨 ≥3 个 ISO 周 | 长期悬而未决 | 写进 Weekly Retro，要求收敛或明确挂起（§ 6） |

- 一条健康的主线是「提问 → 假设 → 实验 → 拍板」，只算 1 轮，不会误报；**反复换假设重跑、或同一个假设连跑三次都不收口**，才会触发。
- **`pivot` 是合法的转向**：先记 `pivot` 再重开同一主题，不判 `CIRCLE-2`。绕圈与转向的唯一区别是——**有没有人拍板承认自己在转**。

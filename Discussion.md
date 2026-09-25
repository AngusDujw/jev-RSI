# 💬 Discussion · 当前 Active 议题

> **协议要求**：本文件同一时刻只承载 **1 个 active 议题**。议题关闭后整体迁移到 `Discussion/Archive/DISC-YYYYWww-NNN-<slug>.md`，本文件从 `tools/templates/Discussion.template.md` 重置或立即承载下一个议题。

---

## Issue Header

| 字段 | 值 |
|---|---|
| **议题号 (ID)** | `DISC-2026W39-001` |
| **标题 (Title)** | 定性决策驱动关节控制的理论框架与论文定位 |
| **主题键 (Topic)** | `jev-control-formulation` |
| **状态 (Status)** | `Open` |
| **发起人 (Owner)** | `User（本轮共同起草）` |
| **开题时间 (Opened)** | `2026-09-24 22:21` |
| **关联 idea/method** | `idea.md §1–7` / `method.md §1–6`（2026-09-24 经用户批准首次写入） |
| **关联实验** | `EXP-2026W39-001`（材料审计）、`EXP-2026W39-002`（文档与公式审阅）、`EXP-2026W39-003`（纲领定位审阅）、`EXP-2026W39-004`（前置验证路线审阅）；均非机器人实验 |

---

## Open Questions（待决清单）

> 维护一组**收敛性问题**，每条带 owner 与到期，防止讨论绕圈。

- [x] Q1：用户已明确按关节控制建模，并希望用类似 optimizer 的函数 sample 具体动作；代码接口尚未核查。 (owner: `User + Agent`, confirmed: `2026-09-24`)
- [ ] Q1b：动作生成函数必须遵守模型方向符号，还是允许根据反馈修正方向？ (owner: `User + Agent`, due: `2026-09-25`，建议日期)
- [ ] Q2：在同等观测下 Jev 提供什么不可被简单反馈替代的价值？ (owner: `User + Agent`, due: `2026-09-25`，建议日期)
- [x] Q3a：静态可达目标、关节空间、每次动作稳定后再观测；经逐轮讨论，用户批准写入两个锚点文件。 (owner: `User + Agent`, confirmed: `2026-09-24`)
- [ ] Q3b：确认仿真验收、Jev 有效性与闭环 feasibility 的数值标准、样本量及资源，再确认主实验 optimizer 与评价阈值；进一步核对新颖性。 (owner: `User + Agent`, due: `下次讨论`)
- [x] Q4：首要目标为开坑型问题定义与理论框架论文；依据实验证据调整贡献层级，idea.md 采用独立严谨的纲领性表述。 (owner: `User + Agent`, confirmed: `2026-09-24`)

协作方式：先在对话中逐项讨论，由用户确认后写入；本次授权覆盖已讨论建模与实验方案，不视为授权自行运行实验、选择新数据集或将候选算法定型。

---

## Posts（回帖区）

> **格式**：每条以 `【角色@姓名】【YYYY-MM-DD HH:MM】` 开头。
> **角色**：`PI` / `Lead` / `Collab` / `Agent`。
> **Agent 发言必须**：(a) 链接到 `LOGS/...#EXP-...`；(b) 直接贴关键数字，不让读者跳页。

---

【Lead @User】【2026-09-24 22:19】
用户请求：阅读 ref 中录音转写，共同 draft idea，采用老手模式；本议题承载该起草工作，具体科学方案仍待讨论。

---

【Agent @Codex】【2026-09-24】
- 材料审计：[EXP-2026W39-001](LOGS/2026-W39.md#exp-2026w39-001)。通读 1 份、1673 行录音转写，分清 3 条候选路线，机器人实验次数为 0。
- 后半段主线为“模型方向＋外部定量校准”；VLA＋残差是备选。录音中 30% 为举例目标，不能写成结果。
- 已保存 [v0.1 草稿](ref/notes/idea-draft-v0.1.md) 与 [时间戳笔记](ref/notes/具身智能机械臂控制理论与论文框架-5b7a9009.md)。给出固定步长振荡反例与条件式下降推导；基础推导本身不是创新。
- 用户要求先解释末端控制和关节控制区别，尚未回答动作接口；不把推荐值当成用户确认。

【Lead @User】【2026-09-24】
解释后用户明确选择关节控制：“肩转多少、肘转多少、腕转多少”，并要求用一种函数具体 sample，类比 optimizer。

【Agent @Codex】【2026-09-24】
依据此澄清更新 [讨论稿](ref/notes/idea-draft-v0.1.md)：用关节角 q 表示更新变量，Q 表示动作生成函数，并区分确定性下降界和随机动作的期望进展；若沿用符号输出，函数能否改变符号仍待决定。[材料审计 EXP-2026W39-001](LOGS/2026-W39.md#exp-2026w39-001) 的机器人实验数量仍为 0，尚无新性能结果。

---

【Lead @User】【2026-09-24 22:46】
确认采用静态目标、动作稳定后再观测的起点，并明确要求：“好的，写入idea.md，还有method.md”。相关转写词 Drive/GV 等统一理解为 Jev。

【Agent @Codex】【2026-09-24】
已写入 [idea.md](idea.md) 与 [method.md](method.md)，记录 2 步实验方案，机器人实验次数仍为 0；证据见 [EXP-2026W39-002](LOGS/2026-W39.md#exp-2026w39-002)。前者说明研究目标、实验操作和评价口径，后者给出余弦测量与误差、条件式尝试次数界以及 step/执行误差边界。具体函数和阈值未定，议题保持 Open。

---

【Lead @User】【2026-09-24】
明确论文目标：优先开坑型 paper、提供理论框架，再根据实验结果退而求其次；idea.md 应为严谨的纲领性文件，不保留录音等来源转述。

【Agent @Codex】【2026-09-24】
已对齐首要定位及 3 个贡献层级，清理两个锚点文件的来源叙事，将实验任务与框架验证对应；机器人实验仍为 0 次，公式与控制边界保持一致。独立只读审阅未发现新增实质问题，详见 [EXP-2026W39-003](LOGS/2026-W39.md#exp-2026w39-003)。后续收缩贡献需有证据并经负责人确认，本轮不决定算法或运行实验。

---

【Lead @User】【2026-09-25】
指出 idea.md 未明确列出前置 Jev 有效性检验、feasibility 实验及仿真环境测试。

【Agent @Codex】【2026-09-25】
已补齐 3 项前置验证并与 2 个主实验明确分工，给出交付物、继续条件和失败解释；数值门槛、候选规则与资源仍待确认，控制实验运行次数为 0。设计审阅补严基础测量与系统性分析的依赖、前置数据隔离及消融可比性，记录见 [EXP-2026W39-004](LOGS/2026-W39.md#exp-2026w39-004)。理论框架优先的定位保持不变。

---

## Resolution（关闭议题时必填）

> Status 切到 `Resolved` 时，本节必须全部填好；否则不许关闭。

- **Decision**：(一段话说明最终结论)
- **Rationale**：(为什么这是结论，基于哪些 EXP / 哪些论证)
- **Propagated to**：
  - `method.md § X`（写明改了什么）
  - `idea.md § Y`（如有）
  - `EXP-YYYYWww-NNN`（受影响的实验）
- **Closed by**：`PI @姓名`
- **Closed at**：`YYYY-MM-DD HH:MM`

---

## 关闭流程（Agent 执行）

1. 确认 `Resolution` 各字段已填（Decision / Rationale / Propagated to / Closed by / Closed at），且 Status 已切到 `Resolved`。
2. 运行 `python tools/new_disc.py close "<slug>"`：脚本校验 Resolution → 归档为 `Discussion/Archive/DISC-YYYYWww-NNN-<slug>.md`（文件名含议题号，可反查）→ 从 `tools/templates/Discussion.template.md` 重置本文件。
3. 在 `method.md` / `idea.md` 受影响章节追加 changelog 条目，并反向链回归档路径。
4. 开启下一个议题：`python tools/new_disc.py open "<标题>"`（编号由脚本分配，避免撞号）。

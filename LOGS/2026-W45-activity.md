# 🧾 Activity · 2026-W45（使用者 & Agent 流水 · 只增不改）

> 由 `python3 tools/log_activity.py` 追加（AGENTS.md § 5.3）；Claude Code 的
> `UserPromptSubmit` hook 会自动记下每条用户输入。人工操作也可照格式补记。
>
> 格式：`- 【User|Agent】【YYYY-MM-DD HH:MM】[类型] 内容 ↪ 关联ID`

- 【User】【2026-11-02 12:02】[intent] 按每日北京时间12:00同步要求执行本轮审阅与SSH提交推送；只纳入明确审阅的项目文件，排除缓存、独立仓库、环境、密钥和大型产物，保留任务暂停与原有科学决策。
- 【Agent】【2026-11-02 12:02】[op] daily progress sync，2026-11-02轮次01：同步前main与SSH origin/main均为66516cb8、暂存为空。完成W44的55条EXP周回顾（N12/Y11/部分16/Crashed16），在Discussion追加有限结论、用户暂停与5条CIRCLE-1/3收敛建议，MODE.last_retro更新W45。仅拟提交Discussion、MODE及本周流水；缓存和独立baseline仓库不纳入，不启动实验。  ↪ `DISC-2026W39-001`
- 【User】【2026-11-04 12:30】[intent] 希望继续采用 code as policy；调研最新 RoboDojo agent 榜单领先方法，整体借鉴其框架，并把部分 GPT 判断职责交给 JEV。本轮仅调研与方案讨论，实验维持暂停。
- 【Agent】【2026-11-04 12:30】[note] RoboDojo 方法只读调研（2026-11-04；session sess_a638580288974596 research continuation 01）：官方 2026-11-03 agent 榜单前六 Score/SR：Q0-Preview 74.20/68.87%，GO-3 Nano Preview 61.90/56.42%，PyRUA-Lean 55.26/50.35%，HexaShell-Preview 53.18/46.85%，WorldScape-R2SI 46.58/39.35%，EmbodiedEvo 45.08/38.95%（https://robodojo-benchmark.com/leaderboard?bench=sim）。Q0 未查得可复现方法；GO-3 官方说明 WRAM、Genie Evolver/Master，不能推断为纯 code policy。实时 GitHub tree 核查：HexaShell e0190ddb757955131578e9f9071f4ee8e7113f7a（https://github.com/HexaFuture/HexaShell）2026-11-03 新版已提供完整通用工具/代码执行框架和 LIBERO 适配；14 通用工具，短任务技能，分析 agent 草拟后人工审阅。RoboDojo 85.0% 与 LIBERO-PRO 96.7% 为作者自测，不是官方同协议成绩；LIBERO skills 学习初态0-9，验证10-19并修改，测试20-29；部分技能含大量 probes，不能证明只需少数回合。旧 Preview 的任务工具/迭代方式保留在 v1.0。PyRUA-Lean e8f01dca744421d70684adbbc1713fd4d92f8aca（https://github.com…
- 【Agent】【2026-11-04 12:31】[note] 方法来源续：PyRUA-Lean e8f01dca744421d70684adbbc1713fd4d92f8aca，https://github.com/DAGroup-PKU/PyRUA-Lean ：持久 Python cell 组合动作、局部检查/重试与按需观测。其 PyRUA_RSI 每任务固定程序在 seed0 自测82.82%、held-out seed2自测80.73%；不是榜单同项，且含任务/资产常量。R2SI 3edfe6afa69978d9d50e59e91e115143a8b486a9，https://github.com/manifoldai-research/R2SI ：内层执行、外层收集/反思/候选/配对验证/启用，训练可选。
- 【Agent】【2026-11-04 12:31】[note] 建议而非已实施：以新版 HexaShell 通用执行底座结合 EmbodiedEvo Playground 冻结流程，在代码内让 JEV Choice 承担状态判别、候选选择、恢复/升级路由；不要求每个运动轴都调用 JEV。当前 run_gpt_jev_program.py:688 review 请求GPT，:716 choose已有通用JEV调用，:730 control主要残差选方向。JEV现有输入是结构化状态，不是图像；不让GPT先给最终判断再让JEV复述。下一步应在同底座同初态比较GPT/JEV判断及空/学习技能，统计全部调用、延时与接口中断。原生结果独立评分。保持实验与目标暂停，未改代码或科学锚点。
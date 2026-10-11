# 🧾 Activity · 2026-W42（使用者 & Agent 流水 · 只增不改）

> 由 `python3 tools/log_activity.py` 追加（AGENTS.md § 5.3）；Claude Code 的
> `UserPromptSubmit` hook 会自动记下每条用户输入。人工操作也可照格式补记。
>
> 格式：`- 【User|Agent】【YYYY-MM-DD HH:MM】[类型] 内容 ↪ 关联ID`

- 【User】【2026-10-12 00:05】[intent] 2026-10-12继续在v4090以本机Pro规划、OpenAI Decisions多模态推进RoboDojo官方成功率前五项，代码放项目盘，实验数据放DataStorage；不在流水保存用户API密钥。  ↪ `DISC-2026W39-001`
- 【Agent】【2026-10-12 00:05】[op] 完成2026-W41 Weekly Retro并更新MODE.last_retro；建立W42周志与v4090 Decisions试验代码、首个Pro阶段计划，待环境/API预检。  ↪ `DISC-2026W39-001`
- 【Agent】【2026-10-12 00:22】[op] 新建实验块 EXP-2026W42-001：v4090 RoboDojo stack_blocks 原生启动与三相机 RGB Decisions API 预检  ↪ `EXP-2026W42-001`
- 【Agent】【2026-10-12 00:22】[op] 新建实验块 EXP-2026W42-002：stack_blocks 三视角 RGB Decisions 直接分阶段控制 30 决策试跑  ↪ `EXP-2026W42-002`
- 【Agent】【2026-10-12 00:23】[result] v4090 stack_blocks 首轮三相机 Decisions pilot：30/30 均为 observe_blocks、150/550 原生步、success=false 且 complete=false；记录 EXP-2026W42-001/002，下一轮拆开视觉验收与动作。
- 【Agent】【2026-10-12 00:27】[op] 依据本机 Pro 复盘改为视觉验收与单活动臂动作两次 Decisions 调用，更新控制器和说明；为 EXP-2026W42-002 追加时间线实验节点与 Discussion 回帖。
- 【Agent】【2026-10-12 00:29】[run] 在 v4090 原生 RoboDojo 启动 stack_blocks 布局0 的 v2 视觉验收—单臂动作试跑，预算40个控制决策/3600秒；运行输出独立写入 DataStorage。
- 【Agent】【2026-10-12 00:30】[op] 新建实验块 EXP-2026W42-003：stack_blocks v2 视觉验收门初次接入与目标/基座一致性检查  ↪ `EXP-2026W42-003`
- 【Agent】【2026-10-12 00:30】[result] v2 首轮仅两次视觉门调用，观察门通过，但选臂门把目标与基座均选 initial_left；一致性校验在原生动作0时中止，记 EXP-2026W42-003。已将二者改成单个合法组合 Choice。
- 【Agent】【2026-10-12 00:37】[op] 新建实验块 EXP-2026W42-004：stack_blocks v2 联合选块后原生对齐闭环，核查目标视觉对应与连续保持动作  ↪ `EXP-2026W42-004`
- 【Agent】【2026-10-12 00:39】[op] 因 EXP-2026W42-004 的对齐停滞及本机 Pro 图像诊断，新增仅从 RGB 高图提取三色块框并标注目标/基座的 v3 辅助信息，保留三张原始 RGB；对齐/接近动作排除 hold。
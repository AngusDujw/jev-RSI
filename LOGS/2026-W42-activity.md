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
- 【Agent】【2026-10-12 00:40】[run] v4090 启动 stack_blocks 布局0 v3 RGB标注辅助的原生试跑，使用本机 Pro 离线诊断后的目标框与对齐动作约束；预算40动作/3600秒，输出仅在 DataStorage。
- 【Agent】【2026-10-12 00:41】[op] 新建实验块 EXP-2026W42-005：stack_blocks v3 原始三视角 RGB 加图像导出目标标注的单臂闭环  ↪ `EXP-2026W42-005`
- 【Agent】【2026-10-12 00:47】[stop] stack_blocks Decisions 分阶段同一意图 EXP-2026W42-003/004/005 连续三次 Crashed/不收敛：0动作字段冲突、65步对齐hold、70步仅X往返且无抓取；依 AGENTS.md §10 停止新增物理试跑，先完成日志/诊断并征求用户继续授权。
- 【Agent】【2026-10-12 00:48】[result] EXP-2026W42-005：v3 15门/14动作/70原生步，12次align continue，X−12/X+2且Y/Z基本不动；主动止损，无官方终局。本机 Pro 建议单因素改善取证视角；已记 blocker 和 Discussion，停止后续物理试跑。
- 【User】【2026-10-12 11:30】[prompt] 我现在已经在本机改了这个AGENTS.md了让它不会因为几次没跑通就停下来，你同步一下之后继续之前的任务目标
- 【Agent】【2026-10-12 11:30】[op] 同步用户更新后的 AGENTS.md 至 v4090-decisions 独立分支；取消连续失败导致的强制停工，恢复 RoboDojo 实验。
- 【Agent】【2026-10-12 11:35】[op] 本机 Pro 复核 v3 三张 RGB 后，实现 v4 遮挡恢复：紫块丢失时抬高手并后撤，重新让 Decisions 判别目标/支撑/手指；自动记视觉停滞终局。
- 【Agent】【2026-10-12 11:36】[run] v4090 前台启动 stack_blocks 布局0 v4 遮挡恢复原生试跑；40动作和3600秒上限，OpenAI Decisions 三视角 RGB，日志全部在 DataStorage。
- 【Agent】【2026-10-12 11:43】[op] 新建实验块 EXP-2026W42-006：--help  ↪ `EXP-2026W42-006`
- 【Agent】【2026-10-12 11:45】[result] EXP-2026W42-006：v4 21动作/105原生步、两轮遮挡恢复使紫块重新可见，但17次align仍未抓取；原生 success=false、complete=false、reason=visual_stall_incomplete。下一轮做Y轴像素投影探测。
- 【Agent】【2026-10-12 11:47】[op] 本机 Pro 基于 v4 前后 RGB 设计 Y 轴单因素小探测；新增 v5_probe_y：右臂开爪、世界Y +5/-5/0mm 三动作，Decisions 对新旧高图回答目标可见性与手指像素位移。
- 【Agent】【2026-10-12 11:48】[run] v4090 前台启动 stack_blocks 布局0 v5_probe_y 校准试跑；世界Y +5/-5/0mm 仅3动作、15原生步，Decisions 对每步新旧 RGB 判视觉位移，DataStorage 留存。
- 【Agent】【2026-10-12 11:50】[op] 新建实验块 EXP-2026W42-007：stack_blocks v5 三路RGB及Decisions模型参与的世界Y小位移视觉标定  ↪ `EXP-2026W42-007`
- 【Agent】【2026-10-12 11:52】[result] EXP-2026W42-007：v5 Y±5mm/3动作15步，图像匹配得+Y→高图上3px、−Y→下3px；Decisions视觉回答none/left/none误判微位移。原生预设不完整，下一轮附像素量化线索。
- 【Agent】【2026-10-12 11:57】[op] 基于 v5 本机 Pro 复盘和 RGB 模板匹配，新增 v6 右夹爪像素位移/目标相对指缝几何提示、经验X/Y投影符号和可证伪对齐门，保留 Decisions 多模态目标/阶段/方向/步长决策。
- 【Agent】【2026-10-12 11:57】[run] v4090 前台启动 stack_blocks 布局0 v6 多模态+RGB几何提示试跑；上限60动作/2400秒，目标/阶段/方向仍由 Decisions 选择，原生终局写 DataStorage。
- 【Agent】【2026-10-12 12:01】[result] v6 首次 API 动作调用在 0 原生动作处 HTTP400：rotation Choice 只有 hold 一个选项，Decisions 要求至少2个；修复为固定姿态时省略该问题并在控制器置 hold。
- 【Agent】【2026-10-12 12:01】[run] v4090 重跑 stack_blocks 布局0 v6 RGB几何提示；修复单选项API400后用新 run-name，最多60动作/2400秒。
- 【Agent】【2026-10-12 12:01】[op] 新建实验块 EXP-2026W42-008：stack_blocks v6 首次RGB几何提示请求的单选项API合同错误  ↪ `EXP-2026W42-008`
- 【Agent】【2026-10-12 12:04】[op] 新建实验块 EXP-2026W42-009：stack_blocks v6 几何提示首步后代理SSL中断  ↪ `EXP-2026W42-009`
- 【Agent】【2026-10-12 12:05】[op] Decisions 只读查询增加有限重试，保留瞬时错误与尝试次数；EXP008 记录单选项API400零动作，EXP009 记录 v6 首步X−long 后代理SSL EOF，均不算完整终局。
- 【Agent】【2026-10-12 12:05】[run] v4090 第三次独立 v6 run-name 试跑：已验证反向代理TLS连通，只读 Decisions 请求可重试，物理动作绝不重发；最多60动作/2400秒。
- 【Agent】【2026-10-12 12:08】[op] 新建实验块 EXP-2026W42-010：stack_blocks v6 多模态选臂请求代理连接三次瞬断  ↪ `EXP-2026W42-010`
- 【Agent】【2026-10-12 12:09】[op] v6 第三次选臂门3次短重试仍连接中断；相同请求随后离线重放成功。只读 Decisions 请求改为5次指数退避；EXP010 完整记录，物理动作不自动重发。
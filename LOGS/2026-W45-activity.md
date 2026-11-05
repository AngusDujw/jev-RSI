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
- 【Agent】【2026-11-04 12:31】[note] 代码定位复核：run_gpt_jev_program.py 的 review 定义在688行、choose在718行、control在733行；上条草记的716/730为邻近行，准确跳转以本条为准。调研记录已保存，未改实验实现。
- 【User】【2026-11-05 12:03】[decision] 明确授权实现上一轮提出的 code-as-policy 方案并测试：新版 HexaShell 通用工具底座、EmbodiedEvo Playground 冻结流程、代码内 JEV 状态与恢复判断；本轮恢复相关实施及实测，继续使用已授权服务器和本机 Pro。
- 【Agent】【2026-11-05 12:03】[op] 新建实验块 EXP-2026W45-001：实现并实测 HexaShell code-as-policy 与 JEV 程序内判断协作  ↪ `EXP-2026W45-001`
- 【User】【2026-11-05 12:05】[intent] 用户追问：为何分阶段后生成仍慢，是否仍传入长上下文；本轮仅检查已暂停EXP055请求与耗时，不恢复实验。
- 【Agent】【2026-11-05 12:05】[note] 只读复核EXP055：request1/19/22固定说明加文本分别32825/71197/94030字符（不含图片/schema），每次2图；stage builder每次附完整manual，repair附完整previous_method；耗时950.425/1304.116/925.144秒且重连0。分阶段输出没有同步压缩上下文，不能仅归因为网络或任务难。
- 【Agent】【2026-11-05 12:18】[op] 已实现并推送 HexaShell 代码策略集成：宿主直采带时标证据、JEV/GPT 同契约判断、沙箱 robot.decide RPC、本机原生 Pro 适配、Playground 修订与冻结、独立 Test、审计入口。内联证据/冻结检查及真实沙箱 RPC 通过；真实 JEV 返回 unknown，真实 Pro 动态工具调用通过。5880-jump GPU0 空闲；新工作区 hexashell-jev-20261105 正按上游安装三个项目内环境。网络 TLS 故障后改用 SSH 拉代码并临时转发代理；未动驱动。
- 【Agent】【2026-11-05 12:25】[result] EXP-2026W45-001：HexaShell上游运行时/沙箱16/16通过；内联时序证据、unknown、冻结完整性/Test来源隔离、沙箱RPC和会话图片转换检查通过；真实本机Pro1次、JEV1次接入通过，物理任务0次。初测缺离线key占位值已定位；首轮上游pytest漏设TMPDIR，已改项目内临时目录且未再次查看或清理默认临时目录。本机HF账号已获SAM3权限，官方固定版本权重正在流式传至服务器，凭据不迁移。
- 【Agent】【2026-11-05 12:29】[op] 新建实验块 EXP-2026W45-002：真实 LIBERO-PRO Playground 经验获取与冻结后 JEV/GPT 局部判断小样本对照  ↪ `EXP-2026W45-002`
- 【Agent】【2026-11-05 12:34】[decision] EXP-2026W45-002 固定小样本协议：libero_goal_swap_t6（官方注册指令 Put the cream cheese on the bowl）；Playground初态0/1，共2回合；冻结后Test初态20/21，各跑JEV空经验/JEV冻结经验/GPT同证据判断冻结经验，共6回合。每回合30规划回复/40局部判断/300原生步/7200秒agent预算。只有任务检查器判成功；接口异常单列并停止后续准入。此为实现pilot，不作整套benchmark或统计优势结论。GPU渲染与官方环境smoke已通过，SAM3权重双端官方SHA校验通过。
- 【Agent】【2026-11-05 12:40】[run] 5880-jump 图形双上下文渲染检查通过（bad_depth=0），但真实SAM3与最小torch.zeros(cuda)均报operation not supported；nvidia-smi -q显示vGPU License Status=Unlicensed。依用户此前明确授权重启5880进行恢复，未修改驱动/系统CUDA版本或许可证配置。此时真实策略回合尚未开始，模型权重/资产已完整落盘并校验。
- 【Agent】【2026-11-05 12:42】[result] 按既有授权重启5880后，torch.zeros(device=cuda)成功，识别RTX5880-Ada-24Q；未修改驱动或系统CUDA。重新建立本轮专用环回转发并启动SAM3，开始真实Playground前复核服务健康。原生图形环境smoke已完成，官方SAM3权重SHA256双端一致。
- 【Agent】【2026-11-05 12:51】[note] 当前资源等待：5880重启后自动恢复其他训练约5.6GB；v4090同机跳板可用但GPU已有其他任务约8GB/48GB。已通过异步问题请用户确认是否共享，未把等待视为同意，未启动占用繁忙GPU的SAM3重测或策略回合。关闭上游expandable_segments的启动器已实现，但尚未完整启动验证。源代码/依赖/权重/协议/软件测试与原生模型接入均已准备，实际Playground和Test仍各0。
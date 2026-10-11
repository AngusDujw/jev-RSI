# 🧾 Activity · 2026-W42（使用者 & Agent 流水 · 只增不改）

> 由 `python3 tools/log_activity.py` 追加（AGENTS.md § 5.3）；Claude Code 的
> `UserPromptSubmit` hook 会自动记下每条用户输入。人工操作也可照格式补记。
>
> 格式：`- 【User|Agent】【YYYY-MM-DD HH:MM】[类型] 内容 ↪ 关联ID`

- 【User】【2026-10-12 00:08】[intent] 用户要求按桌面PDF配置5880免密与反向跳板，克隆项目到指定目录并继续benchmark；本轮要求继续，具体凭据不记录在仓库。
- 【Agent】【2026-10-12 00:49】[op] 5880直连与跳板免密验证完成；用户级systemd反向隧道在跳板127.0.0.1:10022持久运行，Linger=yes，服务重启后连通。
- 【Agent】【2026-10-12 00:49】[op] 5880指定盘克隆jev-RSI十Goal分支、RoboDojo官方源码及锁定子模块、LIBERO-Plus官方源码；同步旧Goal总账SHA；创建独立LIBERO环境及可见模型缓存。
- 【Agent】【2026-10-12 00:49】[op] 5880迁移分支91b5632和2ecea30经SSH推送：可配置路径、单GPU选项、MuJoCo2.3.7 EGL探针修复；探针渲染64x64成功，模型worker离线加载ready。
- 【Agent】【2026-10-12 00:51】[result] 5880单GPU MuJoCo2.3.7 EGL探针与运行器预检通过，64x64 RGB；0 Jev、0任务预留，视觉worker独立ready。首次失败是探针close兼容性错误，已修复并保留在EXP。  ↪ `EXP-2026W42-001`
- 【User】【2026-10-12 01:24】[intent] 继续 5880 服务器部署、LIBERO-Plus 和 RoboDojo 环境配置，并推进十个任务的真实稳定性验证；本轮补充 AGENTS.md 约束。
- 【Agent】【2026-10-12 01:33】[op] 记录5880无计账Goal1383捕获的h5py与缺失官方资产两处启动故障、修复专用环境h5py；旧company-server-2的EGL仍超时且0任务预留；W42 EXP002-003严格lint通过。
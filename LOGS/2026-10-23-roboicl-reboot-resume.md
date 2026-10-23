# 5880 重启后续跑计划

用户授权：重启5880，重启后等待5分钟再继续此前实验，并新增规划5步/执行5步的未加速对照。此为服务器重启授权，不改变驱动、CUDA或系统Python。

保留旧批次fast_h5/layout0成功169步，不覆盖任何旧记录。新批次最多7个物理回合：default_h5/layout0、fast_h5/layout1、default_h5/layout1、default_h1/layout0、fast_h1/layout0、default_h1/layout1、fast_h1/layout1。两个原中断布局从初态重跑，其他为原未开始布局或新对照；明确与旧中断尝试分开计数。

- default_h5：预测5/最多执行5，原版提示词，30mm/0.15rad。
- fast_h5：预测5/最多执行5，既定英文效率提示，60mm/0.30rad。
- default_h1、fast_h1保持原定义；全部原生800步、零样本、seed0、同两个官方布局。
- 本机Pro OAuth，gpt-6-astra/xhigh；不使用Platform API、不调用Jev。所有模型输入英文。
- 实际并发最多2，保持每次启动7500MiB显存和7500MiB可用RAM准入，逐个初始化。
- 新批次目录：远端baseline/roboicl/results/speed-stack-bowls-20261023-reboot；资产与日志仍在用户确认的同一挂载盘。
- 入口：[resume_bowl_speed_20261023.sh](../baseline/roboicl/reproduction/resume_bowl_speed_20261023.sh)，只以前台执行；支持追加--dry-run及独立--output目录验收，不覆盖正式目录。

## 重启及调度状态

准备中。待部署和dry-run通过后重启，核对新boot_id及许可证；从确认服务器恢复时起等待5分钟，使用AgentsDock Jobs一次性续跑。许可证未恢复时不启动仿真，先报告状态。定时任务应保留现有成功、不自动重跑新原生结果，使用本机Pro桥与前台SSH隧道/执行，不使用nohup等脱管方式。执行后更新本文件和完整EXP记录。

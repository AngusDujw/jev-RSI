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

已部署运行源7f681b43；服务器使用实际续跑入口完成7个配置dry-run，全部returncode0。新增default_h5上限0.03m/0.15rad且completion_efficiency_guidance为空，模型Astra/xhigh、原IK保护保持。输出在远端.runtime/speed-reboot-dryrun-v1及同名日志，不调用模型或仿真控制。

重启暂未执行成功：`sudo -n /usr/sbin/reboot`返回需要密码；`systemctl reboot --no-ask-password`返回Interactive authentication required。已向用户请求该服务器sudo凭据或手动重启通知，未尝试猜密码，也未改系统权限。重启前boot_id为7f2cd1e9-e23f-4614-85ef-b3b8c4abd6a2。

下一步：获得系统认证后完成重启，核对新boot_id及许可证；从确认服务器恢复时起等待5分钟，使用AgentsDock Jobs一次性续跑。当前未创建或启用定时任务，以免重启前误启动。许可证未恢复时不启动仿真，先报告状态。定时任务应保留现有成功、不自动重跑新原生结果，使用本机Pro桥与前台SSH隧道/执行，不使用nohup等脱管方式。执行后更新本文件和完整EXP记录。

## 定时续跑任务应执行的范围

读取本计划及AGENTS.md，使用5880-jump服务器；确认重启boot_id已改变且恢复至少5分钟、GRID/vGPU License Status为Licensed。不得修改驱动/CUDA或使用API key替代本机Pro。

本机项目下启动已有pro_oauth_bridge.py，port7915、concurrency2、输出code/runs/2026-10-23-roboicl-speed-5880-reboot/bridge；再前台SSH反向转发127.0.0.1:7915，前台执行远端bash reproduction/resume_bowl_speed_20261023.sh。七回合已明确授权，无需再确认启动，正式输出目录存在时先读取状态，禁止覆盖或自动重跑。保留495次旧模型响应与3个旧尝试，不混为新批次成功率。若许可证或认证仍阻断，记录原因，不替换模型/账号或擅改配置。

执行期间及时检查实际HTTP回执与client.log，不把停顿直接推断为Pro延迟；有CUDA102时停止本人受影响批次并保留未评分记录。完成后回收原始日志、执行analyze_roboicl_speed.py离线审计、写完整EXP和报告，关闭本人桥/隧道；与旧fast_h5/layout0成功169步合并展示时明确来自前批次。

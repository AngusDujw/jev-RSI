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

首次无密码重启未成功：sudo返回需要密码，systemctl返回Interactive authentication required。用户随后提供认证信息，已通过交互sudo成功提交reboot，远端主动断开连接；未保存认证信息、未改系统权限。重启前boot_id为7f2cd1e9-e23f-4614-85ef-b3b8c4abd6a2。

2026-10-23 18:30:34北京时间确认SSH恢复，uptime35.09秒，新boot_id为3c15ba44-3dc1-4a09-870b-e289bd7908ae，已与旧值比较确认重启。许可证显示Unlicensed (Unrestricted)，并非永久修复；既有项目Torch2.7.0+cu128实际CUDA分配、同步及回读通过。官方说明未获得许可证的vGPU可能随时间限速并最终禁用CUDA，见[NVIDIA许可FAQ](https://docs.nvidia.com/vgpu/faq/latest/nls.html)，本次不修改许可或驱动配置。

已创建并启用AgentsDock Jobs一次性任务：job_42b38a995c6c47e9，标题“5880重启后续跑叠碗及未加速5步对照”，max_runs=1，首次运行2026-10-23 18:35:34 Asia/Shanghai（10:35:34 UTC），即确认恢复5分钟后。仅执行既定预检及7回合，不重复重启或覆盖原结果。当前正式实验尚未启动；任务触发后应先记录状态，再完成相机预检和正式续跑。定时任务使用本机Pro桥与前台SSH隧道/执行，不使用nohup等脱管方式。执行后更新本文件和完整EXP记录。

## 定时续跑任务应执行的范围

读取本计划及AGENTS.md，使用5880-jump服务器；确认新boot_id及uptime至少300秒，核对GRID/vGPU状态。Licensed或Unlicensed (Unrestricted)且实际CUDA、Isaac相机均通过时，可执行用户已授权测试；若变为受限、出现CUDA102或实际预检不通过，则记录具体阻断，不绕过许可保护。不得修改驱动/CUDA或使用API key替代本机Pro。

本机项目下启动已有pro_oauth_bridge.py，port7915、concurrency2、输出code/runs/2026-10-23-roboicl-speed-5880-reboot/bridge；再前台SSH反向转发127.0.0.1:7915，前台执行远端bash reproduction/resume_bowl_speed_20261023.sh。七回合已明确授权，无需再确认启动，正式输出目录存在时先读取状态，禁止覆盖或自动重跑。保留495次旧模型响应与3个旧尝试，不混为新批次成功率。若许可证或认证仍阻断，记录原因，不替换模型/账号或擅改配置。

执行期间及时检查实际HTTP回执与client.log，不把停顿直接推断为Pro延迟；有CUDA102时停止本人受影响批次并保留未评分记录。完成后回收原始日志、执行analyze_roboicl_speed.py离线审计、写完整EXP和报告，关闭本人桥/隧道；与旧fast_h5/layout0成功169步合并展示时明确来自前批次。

## 执行进展

一次性任务18:35:37触发，查询确认run_count=1且enabled=false，不会重复执行。启动检查uptime349秒、boot_id为重启后值，显存空闲21720MiB、可用内存23482348KiB。相机capture-only于128.018秒完成，明确状态capture_complete_no_api，30/30 RGB有效且无CUDA102，见[EXP040](2026-W43.md#exp-2026w43-040)。

正式7回合已进入前台协调器，先default_h5/layout0、fast_h5/layout1；本机Pro桥7915/concurrency2、反向SSH隧道及远端资源监测保持前台。当前记录只表示启动，尚无新原生结果。运行源仍7f681b43，未在运行中改策略源码。

服务器启动约20分钟后，许可证转为Unlicensed (Restricted)。依据本次定时续跑指令的Restricted准入限制，SIGSTOP暂停本人协调器的新回合准入；两路已经启动的仿真子进程保持运行，有真实新控制步和回执、无CUDA102。default_h5/layout0与fast_h5/layout1已启动，其余5个新回合未启动。暂停依据保存在新批次admission-suspended-license.json；未改策略或驱动，不能把限速后墙时当作公平动作速度比较。

已通过异步问题请用户选择是否明确允许受限状态下继续剩余5回合；在答复前不恢复新准入，继续收集已启动两组原生终局。另有1次Pro桥SSL EOF连接错误，经原有传输重试继续，需在最终模型尝试统计中保留，不混成物理重跑。

## 本轮最终状态

两个已启动回合均已原生评分：default_h5/layout0成功100分、191步/40完成响应；fast_h5/layout1在800步上限未成功、15分/173完成响应。见[EXP041](2026-W43.md#exp-2026w43-041)、[EXP042](2026-W43.md#exp-2026w43-042)及[完整审计报告](2026-10-23-roboicl-reboot-results.md)。共991控制步全部有回执，无policy_error/CUDA102；3个Pro桥失败HTTP请求经原有重试后继续，传输尝试与模型完成响应分列。

7回合目标尚未完成，以下5个本批新尝试未启动：default_h5/layout1、default_h1/layout0、fast_h1/layout0、default_h1/layout1、fast_h1/layout1。两个旧1/1布局0的196/185步基础设施中断仍在旧目录保留，不补算原生成绩，不表示它们从未被试过。

两个子进程均已退出后，才终止本人暂停的协调器以防新准入；完成元数据根据scored状态与原生文件重建，wall_seconds留空。已关闭本人Pro桥、SSH转发和资源监测，GPU回落50MiB，无本批后台实验。1417次采样显存峰值16227MiB、最低可用RAM9674MiB、swap峰值0；两端原始结果目录校验一致。

旧fast_h5/layout0成功169步不重跑；与新default_h5/layout0成功191步比较少22步=11.52%，响应多2次=5%。布局1没有未加速5/5对照，不能比较该布局的加速幅度。

下一步仅在用户明确选择允许Restricted状态继续、或许可状态恢复满足准入后，补齐上述5个未启动回合。使用现有speed_experiment.py的显式--case与独立新输出目录，不能再次运行含全部7个case的脚本覆盖已完成目录，也不自动重跑800步失败。当前一次性Jobs已触发1次并停用，不会再次自动执行；后续不再重启服务器。

## 用户新授权：以实际GPU可用为准继续

用户明确表示“gpu能用就继续实验就行”，因此解除上一轮仅因Restricted标签暂停新准入的限制。仍不绕过许可、不更改驱动；先重新验证真实CUDA和相机，实际失败则停止。当前同一boot_id，Torch2.7.0+cu128矩阵乘法/同步/回读512.0通过，GPU空闲21717MiB、RAM可用22790MiB。相机capture-only在独立.runtime/preflight-bowl-restricted-resume-v1运行，无模型调用。

通过后仅补default_h5:1、default_h1:0、fast_h1:0、default_h1:1、fast_h1:1到独立results/speed-stack-bowls-20261023-restricted-resume，不重跑既有评分结果。所有模型/提示/步长/800步预算/2并发与双7500MiB准入不变，使用本机Pro gpt-6-astra/xhigh。

实际相机预检106.016秒完成、30/30有效RGB，见EXP043。剩余5case协调器已启动，先default_h5/layout1和default_h1/layout0，首29完成响应均有回执。独立本机目录code/runs/2026-10-23-roboicl-speed-5880-restricted-resume；旧结果不覆盖。本轮不再因为Restricted标签单独停止，只在真实GPU/相机失败时中止本人批次。

未加速5/5布局1原生成功361步/75响应，完整审计见EXP044。之后fast_h1:0/default_h1:1/fast_h1:1启动器因18450端口EADDRINUSE在run目录创建前退出，三次均无仿真/模型。原记录完整保留，不是三个策略失败或新物理回合。协调器仅增加绑定端口等待，本机0ad759b4已推送，远端22189f0部署；roboicl控制模块与7f681b43无差异。空闲slot0 dry-run三配置3/3通过；新的results/speed-stack-bowls-20261023-startup-resume仅补这三项，slot1等原default_h1布局0退出，实际最多两路。

## 2026-10-24 跨日运行检查点（未完成）

用户GPU可用即继续的授权持续有效。未加速5/5布局1已完成361步/75响应的成功结果（EXP044）；两种1/1布局0当前分别370步/414响应和254步/296响应，均仍运行，默认组含1步本地hold，未回执规划按终局再审计；两个布局1尚待槽位，不把等待算物理尝试。旧169成功及重启后191成功、800失败均不重跑。

当前本机Pro桥和SSH反向转发持续前台；原协调器13906的SSH连接曾因跳板超时退出255，重连确认原进程与新协调器18656仍运行，已新增前台只读观察原进程直至summary，不重启任何物理回合。原资源监测及新批监测持续记录。一次Pro上游SSL EOF/RemoteDisconnected造成两路停顿时，实际CUDA复测32.0通过；短暂停止新协调器准入，两个原子回合继续原重试，恢复新成功响应后SIGCONT同一协调器。暂停/恢复证据在startup-resume/admission-suspended-pro.json与admission-resumed-pro.json。后续间歇同类传输错误均沿用原重试，失败推理消耗未知，不按0处理；客户端目前无CUDA102，不能误归因GPU许可。

原始日志已中途同步本机code/runs/2026-10-23-roboicl-speed-5880-restricted-resume/{remote-results,startup-remote-results}，这是未完成前缀备份，最终还需重新同步/校验。全部7个新回合目标尚未完成，后续继续同一批次至原生终局或明确基础设施中断，不自动重跑结果。

## 04:27后：三个未评分与最后回合

未加速1/1布局0在662步/725响应、加速1/1布局0在642步/712响应结束，均无原生评分；默认1/1布局1已初始化但首请求失败、0步/0响应。具体server.log为URLError/ConnectionResetError及PolicyServiceError。本机原Pro桥前台会话exit143(SIGTERM，来源未知)，7915无监听，原隧道仍在并报告connect_to失败；与之前17个上游失败HTTP区别记录，不归因CUDA。本轮无CUDA102，桥恢复后实测CUDA32.0及原隧道health200通过。EXP045–047与完整[续跑报告](2026-10-23-roboicl-restricted-resume-results.md)记录原始文件、动作尺度和未评分边界。

三个初始化后的中断均保留infrastructure-abort.json，不自动重跑；最后fast_h1/layout1通过同一协调器恢复并已产生模型响应和动作。7个新尝试仍有1个运行中。离线审计器现能处理首请求失败的零动作回合，并将三条harness前端口绑定失败单列，不混入物理尝试；本机修改d6a947e8已推送，仅为离线审计，不改变远端控制。末次桥恢复继续使用同一账号、端口7915、Astra/xhigh、2并发，当前前台会话与日志续写，账号/模型未更换。

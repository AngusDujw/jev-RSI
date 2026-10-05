# RoboDojo CUDA节点故障与恢复检查

2026-10-05，company-server-2；项目/root/yekangjie/project/jev_rsi。本页只记录故障诊断，不是任务评测。

## 已确认事实

- 06:56:27，GPU4（PCI0000:00:09.0）Xid79：GPU has fallen off the bus。
- 同时8卡全部Xid154：Node Reboot Required。
- GPU0/2/7整数选择失败；近空闲GPU0换UUID、直接系统libcuda调用cuInit仍999；内核与实际用户库均580.82.09。
- UVM清理异常；GPU7残留计算条目对应defunct进程。未终止其他作业；报告故障的进程名称不证明其导致故障。
- 预算仍1/30，剩29；本次只读检查不算新物理启动。

原始证据：code/runs/2026-10-05-cuda-fault-diagnosis/diagnosis.json；[EXP-2026W41-005](2026-W41.md#exp-2026w41-005)。

## 恢复边界

驱动明确要求节点重启。改控制算法、切设备编号、重启Python都不能绕过已复现的cuInit失败。掉线原因尚未确诊；重启后若继续掉线，应交服务器/宿主机维护检查硬件或直通状态，不能保证重启永久解决。

重启影响其他会话，只在用户明确允许本次重启后执行；不更新驱动/CUDA、不重装依赖、不终止未知进程、不自主卸载模块。server-operator安全边界明确禁止自主重启，用户明确授权可覆盖技能指南。

恢复判据：SSH恢复；8卡均可查询且无新的掉线/重启要求；现有环境在空闲卡分配CUDA张量并同步成功；恢复临时7898代理并验证认证响应；最后启动带守卫的下一物理回合。SSH或nvidia-smi成功单独不足以判定CUDA恢复。

依据：[NVIDIA Xid目录](https://docs.nvidia.com/deploy/xid-errors/analyzing-xid-catalog.html)说明Xid154记录恢复动作；[nvidia-smi文档](https://docs.nvidia.com/deploy/nvidia-smi/index.html)要求重置设备前没有CUDA、图形、监控应用使用设备。没有用有影响的重置试探替代维护。

会话：Codex opt30b第3轮。全部诊断只读，未启动新仿真。

## 2026-10-05无重启复核（EXP-2026W41-007）

用户明确不希望重启；本轮没有重启、重置设备、装依赖、卸载模块或停止其他作业。

逐卡实测GPU0/1/2/3/5/6/7：每卡均在独立进程按UUID选择，系统libcuda直接cuInit和既有RoboDojo torch入口全部失败（各0/7成功）。torch初始化先失败，因此没有成功执行显存分配、运算或同步，不能把预先写好的后续代码当作已执行测试。GPU4不可查询；实时其余7卡的gpu_recovery_action均为Reboot。

额外在仅测试子进程的私有mount namespace中，保留GPU0，将其余GPU设备节点映射为/dev/null；cuInit仍999。父命名空间与宿主/dev/nvidia节点未改变；子进程退出后隔离自动释放。普通与隔离进程两份strace都显示打开共享/dev/nvidia-uvm返回EIO（输入输出错误），定位到初始化阶段的共享接口阻塞，并非普通可见设备编号错误。

掉线原因的已知边界：06:56:27 GPU4 Xid79；GPU4 PCI配置含大量异常ff值，lspci报告rev ff/Unknown header，链路速度Unknown、宽度63为异常读值，不是真实63lane。健康GPU0 PCI配置正常。客体为Alibaba Cloud ECS虚拟机；现有内核记录在事件前未找到更具体AER/RPC/供电/温度前兆，该时间窗口的kernel journal为空。06:56:46渲染库段错误发生在掉线19秒后，不能倒置因果；nvidia-smi是报告时的进程，不证明它导致掉线。要区分硬件、宿主机直通或驱动原因，需要宿主机/云平台侧故障记录。

[NVIDIA Xid79说明](https://docs.nvidia.com/deploy/xid-errors/archive/index.html)列出PCIe链路、GPU硬件及驱动等可能原因，Xid本身不能唯一归因。[nvidia-smi恢复动作说明](https://docs.nvidia.com/deploy/nvidia-smi/index.html)将Reboot与可能不一致的系统状态关联，并明确应用无法通过重新启动恢复。这里仍以7卡实际初始化失败及UVM EIO作为可用性证据。

原始证据：code/runs/2026-10-05-cuda-no-reboot/；[EXP-2026W41-007](2026-W41.md#exp-2026w41-007)。未创建测试脚本，内联探针已退出；未新增仿真试次，仍1/30、余29。暂未找到保持当前系统驱动状态即可继续CUDA实验的路径，也不声称其余7卡物理损坏。

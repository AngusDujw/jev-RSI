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

# LIBERO-Plus恢复执行：冻结验证与五任务对应

用户在2026-10-05明确要求GPU恢复后继续，7901/7902/7903都不可用时允许本机7897转发。原奶酪5次DNS失败、全部开发结果与50/task总上限保留。

## 计划与冻结

- 奶酪Object1066：原冻结focused/pad_fit/adaptive配置，全部8源码SHA不变；新init15–34共20次，原累计27/50，完成后最多47/50。不根据评测失败改当前冻结策略。
- 汤罐Object1043：复用soup-final冻结feedback/observed_surfaces/lift_check配置；新init10–29共20次，原9/50。
- 盘旁碗Spatial1282：复用bowl-confirm冻结feedback/base配置；新init10–29共20次，原4/50。
- 烤碗旁碗Spatial1030、桌中央碗Spatial1062：各先将同一bowl-confirm策略迁移到init1/2/3做3次开发。需要修改时在本任务累计50和开发最多30的余量内推进；冻结后单独新init10–29做20次验证。
- 每组预算沿用冻结Jev/正式原生步/900秒，父进程960秒、600MiB/run、3GiB/batch；每次串行且启动6GiB/运行4GiB磁盘守卫。旧单回合约5分钟，20次约100分钟，不超单组2小时预估。只写原项目挂载盘。

阶段图与可见几何仍由外部代码提供；真实Jev负责方向、夹爪开合和阶段切换。仅公开语言、双RGB-D/标定和机器人自身反馈/几何进入策略，原生success只用于最后评价。成功属于整套系统，不能称模型独立发现策略或证明模型增益。

## 网络与资源

实际服务器起初7901–7903均无监听/拒绝连接；本机7897外网HTTP200。尝试远端7897回传时新sshd占用该口，未停止它；按已授权端口将7901/7902/7903分别直接SSH反向转到本机7897。前景SSH会话持续跟踪，sshd PID54037，三个入口均真实Jev认证及视觉/models HTTP200。原网络失败预检记录保留，不计物理试次。

项目盘启动前约143GiB可用；8卡恢复动作None，GPU0约4.8GiB、GPU1几乎空闲。未改变驱动、CUDA、系统网络或其它作业。当前奶酪前景batch已启动，Jev7901、视觉7902；GPU0 EGL、GPU1分割。

旧libero-generic-vision及libero-jev-ownership的CIRCLE-1保留；按冻结20和分任务有界开发收敛，不无界调参、不关闭议题或更改正式理论。

## 结果

正在执行；以真实result.json、响应审计和累计账本为准。本页启动记录不构成已完成20次或任务成功证据。

原始目录：code/runs/2026-10-04-libero-verify20-cheese-restored；网络证据：code/runs/2026-10-05-libero-resume-network、libero-resume-network-forwarded、libero-resume-network-direct-tunnels。

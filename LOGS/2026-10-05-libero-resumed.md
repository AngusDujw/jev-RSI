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

奶酪恢复批init15–25共11次已结束：1次完整成功（init24）、9次API断连/TLS EOF、1次为停止故障队列而主动中止（init25）。init15执行到test_lift后Jev第44请求断连；init16–23均在首个视觉请求断连，0正式动作。init25实际SIGINT/退出-2及runner_termination保存，不能误记为算法失败。原生成功及program_finished在init24均为true，单次抓取，无retry；95Jev/405正式原生步/3视觉/0DeepSeek，策略墙时105.27秒。

共183Jev请求尝试/182响应、17视觉尝试/8响应，762正式原生步；收到响应的usage为Jev338506输入/34534输出，视觉14521输入/1665输出token。未返回请求是否执行/计费未知，不能假定免费。11回合真实响应、执行方向、夹爪和阶段边、英文及禁止字段审计通过，0阶段合同违规。

本批完成11/20尝试，奶酪累计38/50。剩余计划init26–34共9次，全部完成后累计47/50；不能通过丢弃本次基础设施失败来重置计数，也不能声称已经得到20个完整物理结果。其它四任务尚未启动。

原首错匹配区分大小写且遗漏RemoteProtocolError文本，导致全部9次中断未拦截。新libero_failure.py统一识别错误文本及实际api事件类型，并区分主动中止；在这11个真实结果回放时全部分类正确，新规则会从init15首次断连就停止。验证入口及汇总均采用此分类，修复commit7daf5f2已SSH推送并Git同步服务器，冻结8策略源码未改。

完整EXP为[010](2026-W41.md#exp-2026w41-010)–[020](2026-W41.md#exp-2026w41-020)，其中成功为[019](2026-W41.md#exp-2026w41-019)。连续9次Crashed触发AGENTS§10；只对精确命令行核验的自有父runner发送SIGINT，父进程对子回合优雅停止，未动其它作业或代理监听。已请求恢复确认，当前不追加物理回合。源规则：AGENTS.md §10“任一实验连续3次跑崩 / 不收敛”。

证据：code/runs/2026-10-05-libero-resumed-summary/campaign.json、exp-ids.json、audit.json、actual-requests.json。成功双相机录像为同目录cheese-init24-dual-camera.mp4，左外部/右腕部，95个决策前采样帧按10FPS回放、9.5秒，非墙钟实时录像；原无损相机MKV及PNG恢复清单保留。

本批1010份原始文件共236884316字节本地/服务器逐文件SHA256一致，核验见同目录remote-sha256.json和sync-verification.json。派生汇总、审计及MP4另存，不修改原result、batch或冻结策略。没有创建临时测试脚本，真实错误回放及渲染/导出均采用现有工具或内联检查。

原始目录：code/runs/2026-10-04-libero-verify20-cheese-restored；网络证据：code/runs/2026-10-05-libero-resume-network、libero-resume-network-forwarded、libero-resume-network-direct-tunnels。

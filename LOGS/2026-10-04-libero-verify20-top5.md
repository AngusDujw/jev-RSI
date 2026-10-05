# LIBERO-Plus：冻结20次验证与五个最高成功任务族对应

用户要求奶酪任务测试20次，并完成其他GPT-6最高成功任务的Plus对应版本，沿用Jev选择夹爪与阶段、无特权信息的要求。本轮尚未取得新的物理测试结果：奶酪init10–14共5次在首次语义识别前因服务器DNS故障中断，均0Jev、0正式原生动作、1次未收到响应的视觉请求尝试。旧focused冻结init7/8/9的3/3仍只是旧小样本证据，不能写成20次成功。

## 冻结与计数

奶酪复用`2026-10-03-libero-recovery30-focused-v1/frozen`的全部8个源码文件及SHA256，策略commit为44b7898886513f81a4a6c74c2b37211ae800f6b1。pad_fit、preserve_source、focused、adaptive，768双相机、observed_surfaces，180Jev/550正式原生步/900秒；与原runner固定参数一致，没有在本批改策略。初始化10步张爪单列；官方success只在终局评价读取。

新入口建立独立验证ledger，同时继续追加原每任务50次总账。5个基础设施失败为奶酪累计attempt23–27，旧22次与这些失败全部保留。未自动重跑初态、未重置计数。原父batch.json只有前4个结果；中断后第5个子回合正常完成自己的finally，result.json和总账均存在。汇总读取它的真实结果，returncode保留null，不改写父batch或补造退出码。

证据：[新批manifest](../code/runs/2026-10-04-libero-verify20-cheese/manifest.json)、[5次完整结果](../code/runs/2026-10-04-libero-verify20-summary/campaign.json)、[EXP对应](../code/runs/2026-10-04-libero-verify20-summary/exp-ids.json)、[审计](../code/runs/2026-10-04-libero-verify20-cheese/audit.json)。完整EXP为[235](2026-W40.md#exp-2026w40-235)–[239](2026-W40.md#exp-2026w40-239)，全部Crashed。审计确认5回合没有控制决策或阶段边；这种空记录通过检查不构成控制能力证据。

## 来源与对应边界

[Harness VLA论文Table21](https://arxiv.org/html/2607.08448#A8.T21)及[RPent官方成绩页](https://rpent.readthedocs.io/en/latest/rst_source/leaderboard/performance.html)报告GPT-6 Astra作为规划器时，LIBERO-Pro Spatial-T和Object-T均100%。结合每组10任务×10种子，可推断这些任务各10/10，是并列最高，没有唯一“前五”顺序。该系统包含冻结VLA、记忆和解析动作原语，不能当GPT-6单独直接控制机器人的成绩。

[Pro官方任务映射](https://raw.githubusercontent.com/Zxy-MLlab/LIBERO-PRO/master/libero/libero/benchmark/libero_suite_task_map.py)给出原任务族索引。Pro-T会改语言和目标但保留原文件名，因此这里选的是原任务族的Plus对应，而不是声称Pro-T的扰动实例和Plus指令完全相同。策略以当前环境提供的公开语言为准。

| Plus任务 | 最高成功Pro任务族/原索引 | 本轮状态 | 先前符合Jev夹爪/阶段要求的证据 |
|---|---|---|---|
| Object1066 奶酪入篮 | Obj-T / 1 | 5次DNS阻断，无物理结果 | focused冻结新init7–9：3/3 |
| Object1043 汤罐入篮 | Obj-T / 0 | 等待网络升级处理 | soup-final冻结init1–3：3/3 |
| Spatial1030 烤碗旁黑碗放盘 | Spat-T / 1 | 需要迁移开发，尚未启动 | 未证明 |
| Spatial1062 桌中央黑碗放盘 | Spat-T / 2 | 需要迁移开发，尚未启动 | 旧自动阶段成绩不满足当前要求 |
| Spatial1282 盘旁黑碗放盘 | Spat-T / 8 | 等待网络升级处理 | bowl-confirm同版本init2–3：2/2 |

五项均有50个官方初态。仅检查数量和公开语言，没有读取物体坐标给策略。对应表及旧冻结参考见[配置](../code/configs/libero-supervisor/top5-correspondence.json)。汤罐和碗的旧5个成功记录重新校对了真实response.json与XYZ/旋转/夹爪/阶段/实际执行，均通过；这不替代新的20次验证。

## 中断与下一步

服务器无法解析GitHub和视觉API域名。Git代码通过SSH传Git bundle并快进同步，origin仍为SSH，不改系统DNS。实验入口最初缺少网络首错退出，后台父循环在监控期间继续启动后续初态；本轮实际留下5次基础设施失败，已中断唯一自有runner，所有本批子进程均结束。该批处理缺陷已修复：预留总账前检查服务DNS/TCP，首个网络错误写stopped并退出；用户/协议中断先给自己的子回合SIGINT并等待finally，保留真实结果。

根据AGENTS§10连续3次Crashed的升级规则，已征求是否允许排障后继续。远程7897端口已有监听，server-operator技能要求停止告知；没有换端口、杀该监听、修改sshd或系统网络。恢复依赖用户答复及网络预检通过。可在仍保留5次失败和原50上限的前提下，另测20个未开发初态15–34（奶酪累计将为47/50）；这是一项待授权恢复安排，尚未运行。其它四项先冻结已有候选或做有界迁移，再独立验证，不能把旧自动夹爪/阶段结果混入。

旧libero-generic-vision的CIRCLE-1仍未关闭。收敛方式是冻结奶酪20次新初态、五项分别报告、只在有证据的失败点做预算内开发；不继续无边界调参，不自行写decision或修改正式理论/主指标。

## 空间与数据保存

启动前根盘约5.5GiB，低于6GiB守卫。只归档本会话此前15个已结束且已完成本地SHA备份的奶酪回合：2,434张控制PNG共1,557,191,027字节，libx264rgb CRF0录像共361,026,561字节，净省1,196,164,466字节（约1.11GiB）。逐帧解码必须同时匹配像素SHA及OpenCV再编码后的原PNG字节SHA，才允许移除服务器冗余PNG；初始RGB、深度、标定、分割图、真实请求/响应均保留，本地旧PNG不删。少量归档预览由本轮创建，测试后已移除。

同期其他作业释放了更多空间，根盘检查约49.85GiB；不能把这个变化归功于本轮归档。未删除其它任务文件、未改驱动/环境、未写/tmp或其它挂载盘。旧7,022文件全量SHA报告保留原样，代表归档前原始布局；新归档布局另存清单和核验，原PNG字节可恢复。

本轮新增验证/汇总/归档工具均为可复用项目工具，没有遗留临时测试脚本。AST检查、真实旧回合归档、5个旧成功记录响应审计、5个DNS失败结果汇总和周志strict lint已执行；冻结20回合与其它四任务尚未完成，不能声称验证通过。

本轮5个已结束回合的108份原始文件共37,340,308字节两端SHA256一致，见[核验](../code/runs/2026-10-04-libero-verify20-summary/sync-verification.json)。旧控制帧的39份录像/恢复manifest共361,750,642字节同步一致，见[归档核验](../code/runs/2026-10-04-libero-verify20-summary/archive-sync-verification.json)。本地新生成的audit.json单独列为派生数据，不冒称服务器原始记录；旧本地PNG全量副本保留。

文件变更：新增code/scripts/libero_frame_archive.py、run_libero_frozen_validation.py、summarize_libero_validation.py、code/configs/libero-supervisor/top5-correspondence.json和本报告；修改code/scripts/audit_libero_supervisor.py、code/LIBERO_PLUS.md、LOGS/2026-W40.md、LOGS/2026-W40-activity.md、Discussion.md及TIMELINE.md。未修改冻结策略模块或其它会话文件。

## 2026-10-05授权恢复与代理预检

用户已明确授权验证7901/7902/7903外网并用可用端口继续测试，覆盖上文待授权的网络恢复安排。三端口均外网HTTP200、真实Jev认证成功及视觉/models HTTP200；正式入口的原API类代理包装另验证Jev走7901、视觉走7902。4次网络Jev请求均jev-1.13.0，共1500输入/152输出token；视觉生成0，不是物理控制实验。

用原冻结8源码及SHA、完整新init15–34和相同预算执行preflight-only：网络通过，仿真/grounding两个环境cuInit均999，入口保存not-started后退出2。没有追加任务总账，奶酪仍27/50；20次及其它四任务没有新增物理成绩。阻塞已从DNS变为节点CUDA故障，未改驱动或干预其他任务。

冻结策略和Jev夹爪/阶段所有权保持。新增显式传输包装，修改验证入口增加双环境GPU守卫，命令及证据见[代理说明](../code/PROXY_PORT_ALIASES.md)和[EXP-2026W41-006](2026-W41.md#exp-2026w41-006)。原5个DNS失败继续保留；CUDA恢复且守卫通过后才执行20次新初态验证，不能将这次API成功称为任务成功。

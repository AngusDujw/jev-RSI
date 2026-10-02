# 其余三任务：每任务10次开发结果

**本轮已结束：三任务各新增10次，共30次。只有传送带匹配拾取取得过原生成功；最后修正版也成功。叠碗、叠衣服仍未调通。**

| 任务 | 开发成功/尝试 | 最后回合 | 主要未解决问题 |
|---|---:|---|---|
| stack_bowls | 0/10 | controller_stop:unrecoverable observation ambiguity: target uncertainty too large | 能抓起并搬运，但遮挡、携带几何和放置阶段仍不稳定；第9次另有API超时。 |
| fold_clothes | 0/10 | controller_stop:phase budget exhausted without verified progress | 多数回合未建立有效双臂抓持；最后侧向夹取候选在接近阶段未收敛。 |
| match_and_pick_from_conveyor | 2/10 | 原生成功 | 第6次与第10次原生成功；原冻结确认经历接口错误和追踪失败，最终版本未再独立重复验证。 |

这里是**不同开发版本的尝试完成数**，不是冻结方法的正式成功率；没有挑选/删除失败，也没有把运行异常排除出10次预算。每个任务使用同一开发布局0/eval_seed0。

## 传送带成功证据

| 回合 | 原生步数 | Jev请求 | 本地视觉调用 | 实际版本 |
|---:|---:|---:|---:|---|
| 6 | 368 | 27 | 103 | 3aa9d561 |
| 10 | 479 | 19 | 94 | 45298434 |

最终成功回合：[structured_result.json](../code/runs/other-retry-match_and_pick_from_conveyor-10/structured_result.json)。复现锁定信息：[conveyor-final-manifest.json](conveyor-final-manifest.json)，包含精确commit、控制源码哈希、经验快照和命令。第10次成功版commit为4529843；任务完成479步/19Jev，原生success=true且terminated=true。

第6次使用较早版本成功（368步/27Jev）；第7次原冻结确认在接触时遇到内部数组被JSON化后的9维错误，第8次类型修复确认仍追赶失败。第9次改下游区域拦截但错过闭合；第10次将预测跟踪航点和当前接触事件分开，取得成功。不能将这些不同版本合并为最终策略20%的正式成功率。

## 对成功有依据的机制（尚无消融因果证明）

- **首物体的回合记忆**：记住可见颜色/尺寸与轨迹；“暂时没检测到”不能直接等于离开，加入相对观测带面边界的运动证据。
- **连续身份和速度**：修复通用object标签不能关联的问题，合并检测与颜色恢复的重叠候选，保持实际测得速度。
- **下游拦截**：根据当前可见运动方向，等待目标进入下游机械臂附近，不用左臂一直追到右侧。
- **跟踪与接触分离**：追踪用前馈预测航点；闭合时检查当前估计物体位置。第9次曾当前误差4.47mm但预测目标仍未收敛，第10次修正该事件判断。
- **观测辅助**：机器人自身几何掩码、头部/腕部RGB-D和原生反馈；没有使用物体真值或仿真分割ID。

这仍是外部阶段/姿态/夹爪＋Jev方向的控制系统，不是Jev自主完成全部规划，也不是已证明的跨任务通用策略。

## 失败经验与边界

叠碗曾有明确可见底面抬升，原纯平移验证会因碗的转动而误拒绝；改成底面离台、邻近夹爪和连续观测后可进入搬运。但其后遮挡、姿态可达性、携带偏移和目的碗观测仍未闭合。短期携带预测明确标记observed=false，只用于有限规划，不用它代替实际成功验证。

衣物试过姿态先行、自遮挡过滤、内缩可见关键点、开度预整形、接触静置及侧向夹持，但本轮没有完成原生折叠。全局轮廓重编号不应当作同一关键点，当前可见表面应与历史参考分开。最后版本仍是候选，不能作为有效经验自动推广。

接口调查仅核对机器人自身URDF/STL、通用控制和任务收尾要求。叠碗/衣物需要张爪回初始姿态，因此增加了从本体初始反馈定义的回位阶段，平移仍由Jev决定。未把隐藏对象坐标、奖励状态或原生答案给在线策略；未改变机器人/布料物理、摩擦或驱动。

## 预算、权限与保存

全部30次均计数，共531次Jev请求尝试；运行时GPT-6/DeepSeek均0。DeepSeek保持未启用，本轮没有以其他大模型替代它。接口失败与API超时均保留。

未启动正式off10/on10评测；本轮目标是按用户上限筛选能完成的任务。三任务均到10次，已停止新物理回合。CIRCLE-1按该明确预算收束，不无目标扩测，也不自行关闭研究议题。

全部原始数据位于code/runs/other-retry-<task>-01..10，保留逐帧RGB-D、经验快照、Jev请求/回应、执行命令和隔离真值审计。总账[other-retry-ledger.json](other-retry-ledger.json)含每回合EXP编号、commit、原因、阶段与命令。30个自有仿真进程均退出；24,235个原始文件两端SHA256校验，清单code/runs/other-retry-raw-sha256.json。

## 修改/新增文件

- code/controllers/other_retry/：共享多视角、内部数值类型、机器人自遮挡、阶段/抓持与回位候选。
- code/controllers/conveyor_frozen/、conveyor_frozen_fix/、conveyor_intercept/：保留成功原版、类型修复版和最终拦截版本。
- code/experience/other_retry/、conveyor_frozen/：经验与条件参数；code/experience/candidates/other-retry-*.md：本轮经验总结候选，不自动激活。
- code/configs/other-retry/：三任务独立设备/端口、确认与最终拦截配置。
- code/scripts/structured_task_runner.py：保留原异常、独立配置API超时；code/scripts/record_other_retry.py：已完成回合归档工具。
- LOGS/other-retry-plan.md、other-retry-results.md、other-retry-ledger.json、conveyor-final-manifest.json、周志、Discussion、Timeline和activity。

成功案例只能证明“能完成”，最终版本还需要冻结后在新初态和无经验对照中验证稳定性。

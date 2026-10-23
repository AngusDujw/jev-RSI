# RoboICL 叠碗速度对照（被vGPU许可证故障阻断）

本批用户授权3条件×2个官方布局，共6个物理回合。实际启动3个：1个原生成功、2个基础设施中断，另3个未启动；六回合比较尚未完成。已停止本批仿真、协调器、资源监测、Pro桥与隧道，未自动重跑。

| 条件 | 预测／最多执行 | 平移／旋转上限 | 效率提示 |
|---|---|---|---|
| fast_h5 | 5／5 | 60mm／0.30rad | 有 |
| default_h1 | 1／1 | 30mm／0.15rad | 原版，无新增 |
| fast_h1 | 1／1 | 60mm／0.30rad | 有 |

所有条件保持原生800控制步预算、零样本、seed0、官方layout0/1；模型为本机ChatGPT Pro OAuth的gpt-6-astra/xhigh。未使用Platform API凭据，Jev调用0。IK与跟踪保护保持原样，所以5步规划可能在执行过程中截断。

效率提示第一句按用户要求新增，第二句取自GPT-as-Policy的完成阶段预算说明；不能把整段称为原版逐字提示：

```text
Complete the task as quickly as possible, using as few control steps as necessary. After the object-level goal, release, safely retract and return, reserving steps for this finish.
```

这是同一段连续文本，复制时无需额外换行。

## 已完成结果

| 条件 | 布局 | 原生成功 | 得分 | 控制步 | 模型响应 | 墙时秒 |
|---|---:|---|---:|---:|---:|---:|
| fast_h5 | 0 | 是 | 100 | 169 | 42 | 1334.690 |
| default_h1 | 0 | 未评分：许可证中断 | — | 196（中断前） | 214 | 不作为完成时间 |
| fast_h1 | 0 | 未评分：许可证中断 | — | 185（中断前） | 239 | 不作为完成时间 |
| fast_h5 | 1 | 未启动 | — | — | — | — |
| default_h1 | 1 | 未启动 | — | — | — | — |
| fast_h1 | 1 | 未启动 | — | — | — | — |

fast_h5布局0的169步均有执行回执，终局无缺失回执；12次IK连续性拒绝事件，其中4次整段0步执行。338个已执行单臂动作中，非零平移中位数12mm、最大22.804mm；非零旋转中位数0.06rad、最大0.105095rad。420个有效预测单臂动作也没有达到60mm或0.30rad的90%。此回合没有用到原来30mm／0.15rad以上的有效动作，不能将成功归因于上限翻倍。

两个单步回合于17:37:52/55同时出现`cudaErrorDeviceNotLicensed`及渲染外部信号量等待失败；只读`nvidia-smi -q`确认`License Status: Unlicensed`。起初将停顿推断为Pro长响应是错误归因：495个模型响应均已完成，最后HTTP记录为completed，没有传输重试；最后规划在仿真环节停住。zenity显示警告本身不能单独用于判定许可证故障。基础设施中断不计为任务失败，许可证恢复前不继续启动。

default_h1前缀为195个有回执模型动作+1个本地安全保持，18次IK拒绝；fast_h1为183+2步，55次IK拒绝。两者各有1个最后规划未获得执行回执，不计入已执行动作；已记录原生步均有回执覆盖。默认组最大已执行平移28.705mm/旋转0.13rad，5个单臂平移达到30mm上限90%；加速单步组最大已执行45mm/0.140801rad，未达到60mm/0.30rad上限90%。三组均无有效动作达到对应上限。这里只分析未完成前缀，不能比较完成效率或成功率。

后续需要先恢复服务器GRID/vGPU许可证，再决定受中断回合的处理与剩余布局运行；未修改驱动、CUDA、系统Python或Conda权限。

## 复现和证据

- 冻结运行commit：fd7632ef4e1eb24616742cf30beba46cb3fe8178；官方RoboICL基线07d6e1c5387710e2de9240724b0015bbf0c95c6e。
- 运行入口：[speed_experiment.py](../baseline/roboicl/reproduction/speed_experiment.py)；提示字段：[dialogue_policy.py](../baseline/roboicl/roboicl/policy/dialogue_policy.py)。
- 只读审计：[analyze_roboicl_speed.py](../code/scripts/analyze_roboicl_speed.py)；本机结果与action-audit.json位于`code/runs/2026-10-23-roboicl-speed-5880/`。
- 完整实验块：[EXP036成功](2026-W43.md#exp-2026w43-036)、[EXP037默认单步中断](2026-W43.md#exp-2026w43-037)、[EXP038加速单步中断](2026-W43.md#exp-2026w43-038)；环境与资产准备：[准备记录](2026-10-23-roboicl-speed-5880-preparation.md)。
- 5880没有独立数据盘；用户确认使用当前系统盘后继续，资产和日志写入同一挂载盘的项目目录。
- 配置最大3路，但实际内存只能容纳2路仿真；第三路由GPU和MemAvailable准入保护排队。2078次资源采样：峰值显存16324MiB，最低MemAvailable1000MiB，峰值swap5525MiB。停止后显存50MiB。墙时包含初始化与Pro推理、网络等待，不能直接解释为动作速度；排队时间不含在单回合墙时中。
- 批次证据：summary.json、license-status.txt、infrastructure-stop.json、resources-summary.json，以及两中断回合infrastructure-abort.json。临时资产测试脚本已在测试完成后删除，资产哈希和USD依赖审计JSON保留。

远端批次目录如下，可复制；单行，无需换行：

```text
/home/user/ykj/project/gpt6/jev-RSI/.worktrees/roboicl-speed-20261023/baseline/roboicl/results/speed-stack-bowls-20261023
```

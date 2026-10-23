# RoboICL 叠碗速度对照（进行中）

本批用户授权3条件×2个官方布局，共6个物理回合。仅完成的回合进入下表；排队与进行中回合不是失败成绩。

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

fast_h5布局0的169步均有执行回执，终局无缺失回执；12次IK连续性拒绝事件，其中4次整段0步执行。338个已执行单臂动作中，非零平移中位数12mm、最大22.804mm；非零旋转中位数0.06rad、最大0.105095rad。420个有效预测单臂动作也没有达到60mm或0.30rad的90%。此回合没有用到原来30mm／0.15rad以上的有效动作，不能将成功归因于上限翻倍。

目前只支持该布局成功，不足以比较三条件效果。其余回合仍在运行或排队；不自动重跑原生结果。

## 复现和证据

- 冻结运行commit：fd7632ef4e1eb24616742cf30beba46cb3fe8178；官方RoboICL基线07d6e1c5387710e2de9240724b0015bbf0c95c6e。
- 运行入口：[speed_experiment.py](../baseline/roboicl/reproduction/speed_experiment.py)；提示字段：[dialogue_policy.py](../baseline/roboicl/roboicl/policy/dialogue_policy.py)。
- 只读审计：[analyze_roboicl_speed.py](../code/scripts/analyze_roboicl_speed.py)；本机结果与action-audit.json位于`code/runs/2026-10-23-roboicl-speed-5880/`。
- 完整实验块：[EXP-2026W43-036](2026-W43.md#exp-2026w43-036)；环境与资产准备：[准备记录](2026-10-23-roboicl-speed-5880-preparation.md)。
- 5880没有独立数据盘；用户确认使用当前系统盘后继续，资产和日志写入同一挂载盘的项目目录。
- 配置最大3路，但实际内存只能容纳2路仿真；第三路由GPU和MemAvailable准入保护排队。墙时包含初始化、排队之外的Pro推理和网络等待，不能直接解释为动作速度。运行中有一次两路Pro请求同时明显延迟，终局后再汇总错误与重试情况。

远端批次目录如下，可复制；单行，无需换行：

```text
/home/user/ykj/project/gpt6/jev-RSI/.worktrees/roboicl-speed-20261023/baseline/roboicl/results/speed-stack-bowls-20261023
```

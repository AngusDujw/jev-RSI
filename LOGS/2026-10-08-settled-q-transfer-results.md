# 共用 Q 在黑碗新初态与奶酪已见初态的局部闭环结果

日期：2026-10-08；关联运行前[冻结协议](LOGS/2026-10-08-settled-q-transfer-protocol.md)、`DISC-2026W39-001`。本轮检验一个**已有、未再调参**的固定目标步长规则：$Q(e,s)=\min(10\mathrm{mm},0.7\|e\|_2)s/\|s\|_2$。`0.7` 是现有 `distance_step` 默认值，10 mm 是上一轮测过的幅度上限。黑碗与奶酪共用同一 Q，不按任务名拟合增益。

## 实验边界

LIBERO-Plus 黑碗 `libero_spatial:988` 官方初态14–18是本轮未用于调参的5个新初态；奶酪 `libero_object:1066` 官方初态7–9已用于上轮单步实验，只作跨任务**已见状态诊断**。两任务目标均沿用旧任务专用 RGB-D 方法与旧动作前缀；固定 approach 阶段、目标和朝向，重放后判停稳。每条轨迹最多4次非零动作，动作3个20Hz原生步，之后重新停稳；到达半径黑碗4mm、奶酪2mm。三组为 Jev+Q、Jev+固定5mm、同坐标直接符号+Q（直接组逐轴零死区，避免上轮的阈值冲突）。全程用 Jev 1.13.0、`xyz-signs-v1`，模型仅决策方向；直接组模型请求0。

下表的“到达”只指固定局部位置目标；括号为动作数、终点位置误差 mm。四次后未到达者保留“未达”，不算完整任务失败率。

| 任务/官方初态 | 初始误差 mm | Jev+Q | Jev+固定5mm | 直接+Q |
|---|---:|---|---|---|
| 奶酪7（已见） | 6.442 | 到达(3, 1.676) | 到达(2, 1.759) | 到达(3, 1.676) |
| 奶酪8（已见） | 8.125 | 到达(4, 1.790) | 到达(4, 1.413) | 到达(4, 1.790) |
| 奶酪9（已见） | 6.258 | 到达(4, 1.620) | 到达(3, 1.477) | 到达(4, 1.620) |
| 黑碗14（新初态） | 14.763 | 未达(4, 5.298) | 未达(4, 9.087) | 未达(4, 5.298) |
| 黑碗15（新初态） | 12.290 | 到达(4, 3.283) | 未达(4, 4.152) | 到达(4, 3.283) |
| 黑碗16（新初态） | 12.022 | 到达(3, 2.985) | 到达(3, 3.547) | 到达(3, 2.985) |
| 黑碗17（新初态） | 11.778 | 到达(3, 3.585) | 到达(4, 3.024) | 到达(3, 3.585) |
| 黑碗18（新初态） | 14.805 | 未达(4, 4.887) | 未达(4, 9.185) | 未达(4, 4.887) |

黑碗新初态的局部到达是 Q 3/5、固定5mm 2/5；两组动作数分别18和19，初态15的固定组距门槛仅0.152mm，因此不把1例之差当作稳定优势。奶酪已见状态两组均3/3到达，但 Q 总动作11次、固定9次。五个黑碗和三个奶酪不能合并为一个独立样本成功率，也不能据此宣称 Q 跨任务胜出。两组 Jev 步长在不同中间状态重新请求模型，后续方向可能不同；这是整体控制策略比较，不是严格同方向的纯幅度效应。

**Jev 方向信息对照：**全部8例中 Jev+Q 的29次动作命令与零模型调用的直接+Q逐步相同；稳定后的XYZ最大绝对差仅 $3.34\times10^{-16}$ m（数值舍入），动作命令最大差 $1.32\times10^{-16}$ m。Jev+Q 的29次请求累计等待约497.00秒；固定5mm另28次请求。这里 Jev 正确复现了已给出的偏差符号，却未改变动作或局部结局。因此这批精确坐标输入依然不能证明 Jev 相对同信息反馈有增量价值。

全部8例按运行协议完成，86个实执行动作分支最终均停稳；无API解析错误或崩溃。总壁钟约1330.54秒，远低于预估2小时GPU开销；本机结果目录共约1.8MB。未触碰驱动或安装依赖。注意这既不是完整黑碗放盘/奶酪入篮原生任务成功，也没有重新验证 RGB-D 目标生成或阶段选择。

## 判断与收敛

已有标量 Q 在黑碗新初态的小样本中比5mm固定步长更常于4次内到达，但在奶酪已见近区没有减少尝试；不能说它已成为通用的步长控制器。更强的结论是：在当前把精确目标与当前位置直接交给 Jev 的接口中，29次方向请求未产生一条不同于直接偏差符号的 Q 轨迹。继续用同一输入增加试次数，主要会重复这个信息冗余。建议把此子问题记录为负结果；若要检验 Jev 本身，下一实验应在已定义信息权限下考察它处理目标/阶段不确定性的价值，并与能读取**相同**观测的直接方法比较。若仍研究 Q 的动作函数性质，应明确将其与标准比例位置反馈的比较独立于 Jev 价值主张。

## 复现与原始产物

- 入口：`code/scripts/run_libero_settled_closedloop.py`，借助 `run_libero_settled_step.py` 和 `run_libero_step_response.py` 重放。现有 Q 在 `code/scripts/reliability_step.py::distance_step`；运行入口SHA256 `8aa868f8213902ba14489871c78b372b5628299f73591ccc261437879de8e6fa`，本机/服务器相同，Git中已保存。运行环境为company-server-2既有 `.venv-libero-plus`、OSC_POSE 20Hz、EGL GPU1，服务器隔离worktree HEAD `b6104cf`，实际源码以SHA为准。
- 原始奶酪结果在本机/服务器 `code/runs/2026-10-08-settled-q-transfer-cheese/`，93文件的逐相对路径+内容集合SHA256 `624b8aeaece39c94b1b48ca49d69acf188f53a80fa9de1cab568f7b9f19833df`；黑碗结果在 `code/runs/2026-10-08-settled-q-heldout-bowl/`，166文件集合SHA256 `7fa6e314f2fc1fe4350defb6f0e022bdf6c9bc9be79aaee77694c26018fa323b`。两目录本机与服务器哈希逐项一致，保留所有请求、回复、步进与失败终点。
- 下列每条命令均为**一整行**；复跑时须将 `--output` 换成新路径，勿覆盖原始结果：

```bash
timeout 900 /root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python -B /root/yekangjie/project/jev_rsi/.worktrees/cross-task-step-20261008/code/scripts/run_libero_settled_closedloop.py --run-root /root/yekangjie/project/jev_rsi/code/runs --task cheese --init 7 --output /root/yekangjie/project/jev_rsi/code/runs/2026-10-08-settled-q-transfer-cheese/cheese-init-7-replay --egl-device 1 --direct-hold-tolerance-m 0
```

```bash
timeout 900 /root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python -B /root/yekangjie/project/jev_rsi/.worktrees/cross-task-step-20261008/code/scripts/run_libero_settled_closedloop.py --run-root /root/yekangjie/project/jev_rsi/code/runs --task bowl --init 14 --output /root/yekangjie/project/jev_rsi/code/runs/2026-10-08-settled-q-heldout-bowl/bowl-init-14-replay --egl-device 1 --direct-hold-tolerance-m 0
```

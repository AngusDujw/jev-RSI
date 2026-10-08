# 停稳固定目标局部闭环：共用误差比例步长与同信息方向

日期：2026-10-08；关联 `DISC-2026W39-001`、运行前[冻结协议](LOGS/2026-10-08-local-closedloop-protocol.md)。下述是局部 approach 位置到达，**不是**黑碗放盘原生任务完成，也不是跨任务控制器的独立验证。

## 冻结三组结果

在 company-server-2 的 LIBERO-Plus `libero_spatial:988` 官方初态 11–13，从旧可见 RGB-D 目标和旧动作前缀重建到停稳位置。每条轨迹从相同官方初态单独重放；位置目标和阶段固定，执行 3 个 20 Hz 原生控制步并再停稳后才继续。Jev 每次重新给 XYZ 正/负/保持方向，$Q(e,s)=\min(10\mathrm{mm},0.7\|e\|_2)s/\|s\|_2$；对照是 Jev 固定 5 mm 和按同一坐标逐轴 4 mm 保持的直接方向 + 同一 Q。每组最多 4 次非零动作，以三维总误差 ≤4 mm 为到达。0.7 是已有 `distance_step` 默认值，10 mm 是前一批的已测上限；未从三初态结果中调参。

| 官方初态 | 起始总误差 mm | Jev + Q：状态/动作/末误差 mm | Jev + 5 mm：状态/动作/末误差 mm | 原直接 + Q：状态/动作/末误差 mm |
|---|---:|---|---|---|
| 11 | 12.182 | 到达 / 3 / 3.884 | 到达 / 4 / 3.229 | 到达 / 3 / 3.712 |
| 12 | 11.340 | 到达 / 3 / 3.868 | 到达 / 4 / 3.070 | **全保持** / 2 / 5.480 |
| 13 | 22.871 | 4次预算耗尽 / 4 / 9.271 | 4次预算耗尽 / 4 / 18.108 | 4次预算耗尽 / 4 / 7.086 |

Jev+Q 和 Jev+5 mm 均 2/3 局部到达，前者在两次到达例各少 1 次动作，初态13均失败但前者更接近目标。二者分开请求 Jev 且进入不同中间状态，后续方向也不同，不能把这两例的尝试差直接归因于步长函数。三初态总计 22 次 Jev 请求（Q 10、固定 12）、请求时长约 375.21 秒，三例总壁钟约 460.98 秒；方向与实际动作逐步保存在原始记录。此处没有完整任务成功率或统计上可外推的平均收益。

## 对照阈值冲突与事后校正

原冻结协议有一处对照内部不一致：直接方向的**每轴**保持阈值为 4 mm，而到达用**三维范数** ≤4 mm。所有轴都低于 4 mm 时，三维范数仍可能高达 $4\sqrt3$ mm。初态12的直接组在 5.480 mm 进入这个死区，因此其失败不能算作 Jev 胜出。原结果原样保留。

见[事后诊断协议](LOGS/2026-10-08-local-closedloop-direct-correction.md)：只给直接方向组把逐轴死区设为 0，保持完全相同的三个官方初态、目标、Q、执行与 4 次/4 mm 终点；运行时模型请求 0。它在初态 11、12、13 的结局依次为 **到达/3次/3.884mm、到达/3次/3.868mm、预算耗尽/4次/9.271mm**。这三条轨迹与原 Jev+Q 的每步命令及停稳后 XYZ 位置逐值相同，记录的最大绝对差均为 0 m；Jev+Q 的 10 次方向请求仅请求等待就用了 186.68 秒。原因是这 10 次 Jev 选择恰好与非零坐标偏差的符号相同。此诊断是在看到原结果之后提出，不能称为独立未见验证，但足以说明原三例的 Jev 闭环没有产生额外的方向信息或更好的轨迹。

**判断：**停稳、固定精确坐标目标的近区里，共用仅依赖偏差的 Q 能形成局部闭环；三例没有证明 Jev 对同信息直接反馈有增量收益。若继续相同坐标输入的同类试次只会增加 CIRCLE-1 轮数，应先明确 Jev 需要解决直接偏差方向不能解决的观测/阶段问题，并在相同信息预算下另设对照。第一阶段方法理论仍可研究 $Q$ 对方向误差与执行响应的条件，但不能把直接反馈可完成的部分归功于 Jev。

## 产物与复现

- 原冻结入口：`code/scripts/run_libero_settled_closedloop.py`，运行时源码SHA256 `72be83652bc764c7946dfab3e226ba2a16d307a544e40205e908ed715c424dfb`，在 Git `0e972b2`；校正后入口仅新增可选策略/阈值参数，源码 SHA256 `8aa868f8213902ba14489871c78b372b5628299f73591ccc261437879de8e6fa`，Git `4bb7dcf`。两轮均用已有 `.venv-libero-plus`、Jev 1.13.0、OSC_POSE 20 Hz、EGL GPU1，没安装依赖或修改驱动；运行隔离worktree HEAD `b6104cf`，两个脚本实际内容以所列 SHA 为准。
- 冻结三组结果在本机/服务器 `code/runs/2026-10-08-settled-closedloop/`，99文件集合SHA256 `1c101b28cc2bb9074b6f7097fd2190a62bc9ac9c439ee6ef81d6df9f9a16940b`；事后直接零死区在 `code/runs/2026-10-08-settled-closedloop-direct-nohold/`，27文件集合SHA256 `fb9e8e20ca6c6b2d0c502ac9f4c9c1faf3ee9dd3e6b82844252b038128afa3e7`。两端逐相对路径/内容哈希一致。每目录含原协议、源轨迹SHA256、各步动作/实动、模型完整请求回复（直接组无模型请求）和结果。
- 两个示例命令各为**一整行**，复制时不要中途换行；如复跑请把 `--output` 换成新目录，避免覆盖原结果：

```bash
timeout 900 /root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python -B /root/yekangjie/project/jev_rsi/.worktrees/cross-task-step-20261008/code/scripts/run_libero_settled_closedloop.py --run-root /root/yekangjie/project/jev_rsi/code/runs --task bowl --init 11 --output /root/yekangjie/project/jev_rsi/code/runs/2026-10-08-settled-closedloop/bowl-init-11-replay --egl-device 1
```

```bash
timeout 900 /root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python -B /root/yekangjie/project/jev_rsi/.worktrees/cross-task-step-20261008/code/scripts/run_libero_settled_closedloop.py --run-root /root/yekangjie/project/jev_rsi/code/runs --task bowl --init 11 --output /root/yekangjie/project/jev_rsi/code/runs/2026-10-08-settled-closedloop-direct-nohold/bowl-init-11-replay --egl-device 1 --policies direct_adaptive --direct-hold-tolerance-m 0
```

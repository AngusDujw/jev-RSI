# 首批位置方向与幅度诊断

入口：`scripts/run_position_pilot.py`；固定配置：`configs/company-pilot.json`。
这是开发诊断，不是冻结任务成功率评测，也不是完整 Jev 叠方块策略。

## 数据边界

- Jev 输入：当前 XYZ、固定姿态、夹爪状态、人工指定的当前子任务与局部目标、单位与 0.5 mm 单轴保持容差。观测来自仿真真值，历史为空；不输入参考方向、奖励、未来执行结果。
- Jev 输出：XYZ 各自 negative/hold/positive；保留完整原生响应、概率、confidence 和实际返回模型。幅度、阶段拆解与夹爪动作不由本批 Jev 决定。
- MuJoCo 用规则控制收集 approach/descend/lift/carry/lower/withdraw 各阶段的实际状态。grasp/release/recover 的规则动作写事件日志，不冒充 Jev 判断。
- v1 从运动中段取快照，是探索数据。v2 先在快照处保持，满足线速度 ≤1 mm/s、角速度 ≤0.01 rad/s 持续 0.1 s 才调用 Jev；最长额外等待 2 s。未停稳样本有明确事件记录。
- 同一判断的 0/1/2/5/10 mm 分支使用完整 MuJoCo integration state 的一致 clone；方向归一化，零向量保持。0 mm 是基线漂移对照。恢复与试探仅供离线诊断，不能当免费闭环操作。
- 相邻阶段、同轨迹内快照相关，不作为独立任务样本。三个种子只是小批检查，不能宣称统计充分。
- RoboDojo 现有原生桥禁止重置/回滚。本批遵守单回合约束：7 项顺序执行器检查和最多 6 次人工局部目标的方向探测，保持另一臂。不会把顺序动作称为相同状态下的配对幅度实验，也不宣称完整堆叠成功。

## 原始记录

每次运行拒绝覆盖已存在的目录。

- `protocol.json` / `provenance.json`：冻结参数、实际命令、解释器、项目提交。
- `decision-NNNN/request.json`：实际发送的完整 model/state/questions，无凭据。
- `response.json`：实际服务返回 JSON；`decision.json`：解析结果、阶段、误差与独立评价。
- `decisions.jsonl`：一行一个实际模型请求；`events.jsonl`：API 耗时/状态/用量、规则阶段与停稳准备。
- `sim_state.npz` / `sim_metadata.json`：MuJoCo integration state 与控制/阶段辅助状态；RoboDojo 对应 `native_state.json` 与原生 ACK，不能宣称其可完整回滚。
- `branches.jsonl` / `branches.csv`：通过 decision_id 关联判断、命令幅度、实际位移、损失变化、姿态误差与稳定状态；失败分支保留。
- `summary.json` / `failure.json`：整次运行状态及失败；方向余弦只统计非零可测方向，所有零动作和错误请求保留在总样本。
- RoboDojo 另存 `simulator.log`、启动命令、布局哈希、原生任务信息与视频。物理成功只采用原生判据，模型或脚本完成不替代它。

## 运行

服务器 company-server-2。以下每行是独立命令，先切工作目录；每次更换输出目录名，不能复用已有目录。

```bash
cd /root/yekangjie/project/jev_rsi
mkdir -p code/runs/cache/tmp code/runs/cache/xdg
export TMPDIR="$PWD/code/runs/cache/tmp"
export XDG_CACHE_HOME="$PWD/code/runs/cache/xdg"
export PYTHONDONTWRITEBYTECODE=1
```

下面各是一整条命令，不需要手动换行。环境检查可省略 `--with-jev`；带此参数将发起真实模型请求。

```bash
/root/yekangjie/project/embodied-jev/.venv/bin/python -B code/scripts/run_position_pilot.py --config code/configs/company-pilot.json --output code/runs/NEW-embodied-s0 --with-jev --seed 0
```

```bash
/root/yekangjie/project/robodojo-jev/envs/robodojo-isaac51/bin/python -B code/scripts/run_position_pilot.py --config code/configs/company-pilot.json --output code/runs/NEW-robodojo --backend robodojo --with-jev --max-decisions 6
```

配置固定使用 GPU 4，启动前若显存占用超过 1 GiB 会拒绝；不抢占已有进程。应用日志和缓存写入本项目。RoboDojo 启动上限 20 min，单次程序墙钟预算 30 min，输出上限 500 MiB（外部 simulator 日志在轮询时核查）。实验退出回收本轮进程组。

临时验证采用内联断言，无测试脚本遗留；上述文件是可复用实验入口。语法检查之外，已实际执行验证符号反向、保持容差边界、请求/响应/状态关联和相同判断的分支初态一致性。

## 2026-09-29 扩展运行

`run_expansion.py` 与 `company-expansion.json` 固定使用 seed 10–39，每阶段在起点及 50/85/95/99.5% 轨迹位置采样，目标 900 次模型请求。它不保证五个误差区间均匀；按实际误差汇总。每种子复用原停稳与五幅度协议，子运行失败完整保留，连续三次失败停止。汇总入口 `summarize_expansion.py` 输出分阶段/误差混淆矩阵、全轴正确率、概率 Brier、按 seed 聚类 bootstrap 区间与原始文件哈希。

`company-stack.json` 启用 `robodojo_stack.py`：原生三块堆叠及回原位，550 步预算不变。显式 oracle 几何产生局部抓取中心目标，Jev 决定 XYZ 符号，外部函数幅度=min(40 mm,0.7×位置误差范数)。阶段、物体顺序、向下抓取姿态、夹爪及回原位由规则给出，不能把这些能力归于 Jev。阶段终止使用 2 mm 单轴容差，动作固定3个原生步，闭/开爪12步，尚未认证停稳。保留原生成功结果、物体几何、动作/IK/ACK、完整请求响应、阶段切换和抓取抬升证据；开发失败不删除，改动计划版本单独命名。

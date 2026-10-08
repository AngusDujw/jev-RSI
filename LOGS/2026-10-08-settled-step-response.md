# 停稳近目标的 Jev 与直接方向配对步长响应

日期：2026-10-08；关联 `DISC-2026W39-001`。这是固定阶段、固定位置目标的局部诊断，不是完整抓放任务或步长控制器的闭环成绩。

## 问题与方案

上一轮 LIBERO 近区分支的 0 mm 命令仍自行前进约 5–6 mm，不能当作停稳数据。本轮沿用已存非特权 RGB-D 生成的固定 approach 目标和官方初态，重放原 Jev 轨迹至目标附近，然后给零命令，要求末端线速度 ≤1 mm/s、角速度 ≤0.01 rad/s 连续 3 个 20 Hz 原生步。各分支从同一官方初态独立重放到数值相同的停稳位置；新鲜请求 Jev 1.13.0 一次，使用共同 `xyz-signs-v1` 输入，明确当前位置、目标坐标、世界系和逐轴保持容差。直接方向按同样坐标与容差逐轴取符号，二者的命令范数均取 0/1/2/5/10 mm；实际执行 3 原生步后再次停稳。

开发组：黑碗放盘 `libero_spatial:988` 的官方初态 1–3 和奶酪入篮 `libero_object:1066` 的初态 7–9，共 6 状态、54 分支。运行前冻结了黑碗初态 4–10 作为同一输入方案的独立初态组，共 7 状态、55 分支。方向相同的 2 个独立初态不重复执行直接方向分支，该组在相同步长下的结果按定义与 Jev 分支相等。合计 13 次新 Jev 请求、109 个实执行分支；所有分支最终都重新满足停稳判据。13 个源目标仍来自旧任务适配器，故“独立”只指本轮未据这些初态调输入或步长，不指全新目标生成或跨任务验证。

误差下降按 $\|x_0-x^*\|_2-\|x_1-x^*\|_2$；下表均为再减去该状态 0 mm 分支误差下降后的净值，单位 mm。方向相同者两列相等。

## 结果

| 组别 | 状态数 | 起始误差 mm | 0 mm 自然下降均值 mm | Jev/直接方向不一致 | 5 mm Jev/直接净下降 mm | 10 mm Jev/直接净下降 mm |
|---|---:|---:|---:|---:|---:|---:|
| 开发：黑碗 | 3 | 10.35–13.84 | +0.074 | 3/3 | 2.336 / 2.461 | 5.059 / 5.351 |
| 开发：奶酪 | 3 | 6.26–8.13 | −0.042 | 3/3 | 2.918 / 3.550 | 3.158 / 4.992 |
| 独立初态：黑碗 | 7 | 8.51–11.84 | +0.102 | 5/7 | 2.448 / 2.702 | 5.170 / 6.032 |

独立初态的 10 mm 配对中，直接方向在 4 个初态更好、1 个初态较差、2 个方向相同；平均净优势为 0.862 mm。1/2/5 mm 幅度下也都是 4 优、1 劣、2 同，均值直接方向分别多下降约 0.028/0.082/0.254 mm。Jev 错误主要是将小于逐轴保持容差的坐标轴也判成移动，而非整体朝相反方向。13 个请求的单次时间约 61 秒；在直接方向从同一输入算得的场景，这笔模型成本需要由额外信息价值来证明。样本小，独立组仅黑碗任务，不据此宣称一般统计显著性或所有 Jev 输入都无价值。

各 0 mm 分支误差下降的绝对值最大 0.195 mm，远小于上一轮未停稳近区的 4–8 mm；109 个分支起点重放误差均为数值零量级。这使当前局部步长响应可以用于下一次固定规则闭环 pilot。当前证据并不支持在**只给精确位置目标与当前位置**的接口下，Jev 方向优于直接偏差符号。若动作函数按已知偏差压掉这些轴，必须继续与同信息直接反馈比较，不能把它记成 Jev 的方向增益。

## 复现与限制

- 实验入口：`code/scripts/run_libero_settled_step.py`，借用 `code/scripts/run_libero_step_response.py` 的旧轨迹重建。源脚本在本机/服务器逐文件 SHA256 相同，分别是 `14af8377bd02b540e3967d9c5939d1d1974ab23f4c8e771e4abb531dcb14fbb5`、`46430d7339eb43d2a98a19a100285337634a7007be0cb73dff6397bd642b56ce`；已在 Git `0e972b2` 保存。服务器隔离 worktree 运行时 HEAD 为 `b6104cf`，源脚本为同内容的未提交文件，原始状态如实留在各结果目录。源数据见 `selected_state.json::source_sha256`。
- company-server-2，既有 `.venv-libero-plus`、MuJoCo/LIBERO-Plus，EGL GPU1；未安装库或修改驱动。开发组单初态最多 900 秒，实际每例约 100–116 秒；输出限 100 MB。一次例子如下，整行复制，换初态须同时换 `--init` 与全新 `--output` 路径：

```bash
timeout 900 /root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python -B /root/yekangjie/project/jev_rsi/.worktrees/cross-task-step-20261008/code/scripts/run_libero_settled_step.py --run-root /root/yekangjie/project/jev_rsi/code/runs --task bowl --init 4 --output /root/yekangjie/project/jev_rsi/code/runs/2026-10-08-settled-step-heldout/bowl-init-04-replay --egl-device 1
```

- 原始结果在本机及服务器项目同盘 `code/runs/2026-10-08-settled-step-paired/`、`code/runs/2026-10-08-settled-step-heldout/`；逐相对路径+文件内容的集合 SHA256 分别为 `d69b032d51421af3b881e68d8cbdbbdad71d30523aa0dd59dd789c6c291d69b1`（84 文件）与 `a7985c330efab0452b617cf8a2ae384ef6fb9c6603f8788b0f921867e5a9dac6`（98 文件），本机与服务器一致。
- 各例 `result.json::branch_count` 与 `paired_branches.json` 是实际分支数；`summary.json::branches=0` 只是复用 Recorder 未登记此脚本的分支计数，不能用于本次分支总数。阶段、目标、末端反馈权限固定；图像目标生成在此没有重新评估。静态位置到达亦不等于任务原生 success。

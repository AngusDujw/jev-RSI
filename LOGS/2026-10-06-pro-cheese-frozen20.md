# LIBERO-Plus 奶酪：GPT-6 Sol/xhigh 冻结新初态评测

2026-10-05 至 2026-10-06，任务为 `libero_object:1066`，公开指令为“collect the cream cheese and set it in the basket”。用户把该任务共享物理尝试上限由 50 提高到 59；此前总账已有 39 次，本轮官方 init27–46 各运行一次，共新增 20 次。init26 的完整成功是开发回合，**不计入本表**。

**结果：20 次尝试中 19 次官方 `success=true` 且 `program_finished=true`；init30 在第 12 次控制请求时因工作站至服务器的 7903 SSH 反向转发断开而中止，不能评价物理任务成败。完整可评估回合为 19/19 成功；这不是 20/20，也不是 LIBERO-Plus 全任务或 LIBERO-Pro 的分数。** init30 保留在共享总账的第 43 次，没有重跑。总账现为 59/59；若要得到第 20 个*完整可评估*新模型回合，需要另一个未用官方初态和新的上限授权。

| init | 共享次序 | 官方完整结果 | 原生步 | 控制请求/完整回复 | 视觉回复 | 墙时/秒 |
|---:|---:|:---:|---:|---:|---:|---:|
| 27 | 40 | 成功 | 405 | 95/95 | 3 | 2905.1 |
| 28 | 41 | 成功 | 402 | 94/94 | 3 | 2857.6 |
| 29 | 42 | 成功 | 405 | 95/95 | 3 | 2877.5 |
| 30 | 43 | 转发中断 | 48 | 12/11 | 2 | 680.4 |
| 31 | 44 | 成功 | 405 | 95/95 | 3 | 2315.8 |
| 32 | 45 | 成功 | 402 | 94/94 | 3 | 1782.7 |
| 33 | 46 | 成功 | 405 | 95/95 | 3 | 1607.4 |
| 34 | 47 | 成功 | 408 | 95/95 | 3 | 1431.1 |
| 35 | 48 | 成功 | 408 | 95/95 | 3 | 1384.6 |
| 36 | 49 | 成功 | 405 | 94/94 | 3 | 1388.2 |
| 37 | 50 | 成功 | 405 | 95/95 | 3 | 1455.0 |
| 38 | 51 | 成功 | 408 | 95/95 | 3 | 1377.1 |
| 39 | 52 | 成功 | 405 | 94/94 | 3 | 1371.9 |
| 40 | 53 | 成功 | 405 | 95/95 | 3 | 1403.3 |
| 41 | 54 | 成功 | 405 | 95/95 | 3 | 1442.3 |
| 42 | 55 | 成功 | 405 | 95/95 | 3 | 1431.6 |
| 43 | 56 | 成功 | 405 | 95/95 | 3 | 1568.5 |
| 44 | 57 | 成功 | 408 | 96/96 | 3 | 1558.7 |
| 45 | 58 | 成功 | 402 | 94/94 | 3 | 1522.4 |
| 46 | 59 | 成功 | 411 | 96/96 | 3 | 1575.9 |

本轮共 7752 原生步、1814 次控制请求，其中 1813 条完整控制回复；59 条视觉回复；DeepSeek 0。20 回合的真实响应/执行审计覆盖 1814 条决策记录、1813 次执行和 211 条阶段边，合同违规 0。已完成的全部控制与视觉回复均记录 `gpt-6-sol`、`xhigh`；这些是工作站 ChatGPT 登录的 Codex CLI 推理，不是旧 Jev、GPT-6 Astra 或 DeepSeek API。每个完整成功回合一次抓取，没有证据证明 retry 分支有效。无损视频归档覆盖双相机 3626 帧，20 回合均有 agentview 和 wrist MKV 及逐帧 PNG 哈希恢复清单。

## 冻结范围与权限

策略从 `code/runs/2026-10-05-pro-sol-cheese-dev-init26/frozen/` 原样复制，20 次评测 manifest 的 `source_sha256` 与开发回合完全一致，策略来源 commit 为 `92b5c24ddb3f76a88e2275e950d4735039ab95ee`。三个分批运行器 commit 分别是 `9443f250773bbbef00915b5b666d73f356932378`、`63df7dec771b696aa631169e4319a3c5e66f2780`、`da5cda998f66276f0466336456bb0f77e0a225e4`；运行器变更未改变冻结策略文件。

输入是公开任务、双 RGB-D/标定、语义分割后的可见几何、机器人自身 TCP/夹爪反馈及机器人自身指垫模型。外部程序生成抓取候选、阶段合同、容差和有界动作幅度；GPT-6 Sol/xhigh 选择方向、夹爪、候选与阶段边。审计检查真实回复是否与动作/阶段一致，拒绝隐藏对象位姿、ID、尺寸、reward、原生 success 等策略字段；官方 success 只在终局评价读取。因此成绩属于这套**模型加可见几何/阶段脚手架系统**，不能归因于模型独立控制能力或整个 benchmark 泛化。

## 复现与归档

服务器 `company-server-2` 项目目录为 `/root/yekangjie/project/jev_rsi`，SIM 环境为 `/root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python`。GPU0 用于 EGL 仿真，GPU4 用于可见图像分割；未改动 CUDA/驱动。每个命令为独立一行，无需人工换行；这些历史输出目录已存在，**不能重复执行**：

```bash
cd /root/yekangjie/project/jev_rsi
CUDA_VISIBLE_DEVICES=0,4 /root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python -B code/scripts/run_libero_pro_batch.py --profile cheese --suite libero_object --task-id 1066 --inits 31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46 --purpose evaluation --frozen-from code/runs/2026-10-05-pro-sol-cheese-dev-init26/frozen --output code/runs/2026-10-05-pro-sol-cheese-eval-31-46
```

三批根目录为 `code/runs/2026-10-05-pro-sol-cheese-eval-{27-46,28-46,31-46}/`；每个初态有 `result.json`、`audit.json`、`pro-model-audit.json`、`control-frame-archive.json`、两路视频、原始模型请求与回复。第 2 批的 `stopped.json` 标注 init30 网络故障，第 3 批 `finished.json` 标注 16/16 完整成功。服务器与本地的三批目录相对路径/内容树 SHA256 分别同为：

| 批目录后缀 | 双端树 SHA256 |
|---|---|
| `27-46` | `8103d23c188ed1a4839292d563f1663dbf77f491025b2b01a3445031984df3e3` |
| `28-46` | `e2e5236ea1d67f096eaa833247d65ec34a2865c4cc9bff6ccf6648d79a239455` |
| `31-46` | `32796aed47cb459045efbd4ad1f77155adfe555e47bbdab2dad7716c1f8feb87` |

三个独立账本与共享 `code/runs/libero-supervisor-ledger.jsonl` 的本地/服务器 SHA256 亦分别一致；共享账本 SHA256 为 `cef1178f265dfa62e9f5e1c35b4204664534e4add91885baff9cfe7aca77d1ef`。原始运行数据位于 `code/runs/`，不纳入 Git；本报告和协议 EXP 指向可复核路径。

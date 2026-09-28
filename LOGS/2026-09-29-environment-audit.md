# company-server-2 环境核查与首批测试计划

日期：2026-09-29；关联 DISC-2026W39-001 / EXP-2026W40-002。

## 本轮边界

用户指定工作目录 `/root/yekangjie/project/jev_rsi`，授权参考本地 embodied-jev，并复用远程既有 embodied-jev / RoboDojo。本轮完成源码与环境检查及最小 CPU 物理检查；没有启动 Isaac Sim、模型 API、训练或正式任务评测。没有安装依赖、修改底层驱动或远程已有文件，没有创建临时测试脚本。

目标目录当前为空且没有独立 Git 仓库；Git 向上解析会命中 `/root`，后续应先在指定目录建立项目自身的 checkout，不能在那里直接依赖父级 Git 状态操作。远程两套实际代码仓库检查时工作树干净。

## 可复用资源

| 项目 | 位置 / 版本 | 本轮证据 |
|---|---|---|
| embodied-jev 源码 | `/root/yekangjie/project/embodied-jev`，26e891beb50c8d5d9b07f166ef979efcda9c7a73 | 已核对源码和三场景初始化 |
| embodied 环境 | 同目录 `.venv/bin/python`；Python 3.12.13、MuJoCo 3.13.0、NumPy 2.5.3 | 实际导入及 6 次物理动作完成 |
| 本地 embodied 参考 | `/home/ykj/project/gpt6/benchmark/embodied-jev`，af0d0aa240d0fbf5a5ce0d3ccb8618c9077d4778 | 与远程提交不同，后续冻结实际运行版本，不自动拉取覆盖 |
| RoboDojo 源码 | `/root/yekangjie/project/robodojo-jev/robodojo`，726e9aabfaa642203722eb126f5eaf0f37f3e1ad | stack_blocks 代码、配置及现有布局已定位 |
| RoboDojo 控制器 | `/root/yekangjie/project/robodojo-jev/controller`，20ad8e7906598387bbcfe3f73c2def9992299b81 | company_policy 经配置 PYTHONPATH 可实际导入 |
| RoboDojo 环境 | `/root/yekangjie/project/robodojo-jev/envs/robodojo-isaac51/bin/python` | Python 3.11.15；Isaac Sim 包 5.1.0.0；实际导入 PyTorch 2.7.0+cu128、cuRobo、SciPy 1.15.3、msgpack 1.1.2 |

RoboDojo 环境没有安装 embodied_jev / MuJoCo，embodied 环境没有 Isaac Sim / PyTorch，这是两套独立环境，按各自解释器复用。控制器通过现有源码 PYTHONPATH 加载，不需要为检查重新安装。

资源快照：根挂载 `/dev/nvme0n1p3` 约剩 178 GiB；8 张 RTX 4090，每张约 24 GiB。GPU 0–3 各使用约 21 GiB，4–7 各约 4 MiB；正式启动前重新检查，不能视为资源预留。所有新输出和临时目录应显式指向 jev_rsi 同一挂载盘，现有代码/环境/资产只读复用。

## 本轮最小运行结果

执行位置：远程 jev_rsi；使用既有 embodied 虚拟环境，`PYTHONDONTWRITEBYTECODE=1`，内联 Python，无渲染、无文件输出。对 transfer / stack / barrier 各构造 `RobotWorld(task, seed=0)`；三者 qpos 均有限、初始 success 均为 false。

随后构造 stack seed=0，分别由同一 world 的 clone 出发，设置目标为当前 TCP 加单轴 ±0.002 m，耗尽 `motion(target=target, seconds=0.6, emit=False)` 生成器后读实际位置。底层已包含固定向下姿态 IK。

| 轴 | 命令 mm | 实际主轴位移 mm | 目标三维误差 mm |
|---|---:|---:|---:|
| X | -2 | -1.862981 | 0.139304 |
| X | +2 | 1.864493 | 0.136776 |
| Y | -2 | -1.906933 | 0.094321 |
| Y | +2 | 1.903902 | 0.096360 |
| Z | -2 | -1.875957 | 0.127674 |
| Z | +2 | 1.878757 | 0.122668 |

六方向符号均正确。此结果仅验证单起点、单尺度、单次运行；固定 0.6 s 不是经速度阈值确认的稳定等待。尚未测姿态误差、保持漂移、多次复位误差或抓取成功，不能宣布 0A 完整通过。完整状态 clone 的覆盖也需专门核查。

## 代码接口与必须注意的差异

- embodied `src/embodied_jev/physics.py:83` 定义 RobotWorld，`:198` 为保持 DOWN 朝向的 IK，`:221` 为 clone，`:265` 为 motion。内建 transfer / stack / barrier 分别是入盘、两块堆叠、越障；技能基线含预先设计的控制逻辑，只能作为环境正对照。
- RoboDojo `task/RoboDojo/tasks/stack_blocks.py` 定义三块堆叠，原生成功还要求机器人返回初始位置；两块部分堆叠仅属分阶段得分。原生步数上限 550；原生步与外层决策不可混用。
- RoboDojo bridge 的末端参考是 link6，抓取点另由 gripper_bias 定义；必须与 embodied TCP 区分。姿态用 wxyz 四元数/旋转操作表达，不能直接把三个旋转原子动作当作已核验的 ypr 增量接口。
- 现有 company 配置有粗细档及原子动作选择，和本项目“模型输出轴向符号、外部函数定幅度”的目标协议不完全一致；第一步绕过模型测执行器，后续需适配并冻结模型输入输出。
- 现有 `company_campaign.py:50–80` 将源码根、缓存、Kit 扩展、API 配置和工作目录绑定到旧项目；不能直接改 root 为 jev_rsi 后启动。后续本项目启动适配应把只读依赖路径与新输出路径分开。
- 现有 stack study 配置包含 oracle_geometry。oracle 可作环境/执行器诊断，但须显式标记权限，不能与视觉 Jev 结果混报。历史部署/结果说明不是本轮新测试证据。

## 下一批实验顺序（计划，尚未执行）

1. 在 jev_rsi 建立独立项目 checkout 与配置，冻结上述代码版本；新日志、缓存和输出位于该目录，复用既有解释器和资产。无需复制大型模型或安装依赖。
2. embodied：先跑三个场景的现成规则正对照（各 seed=0，一共 3 条），核验成功判据、接触和日志；随后只在 stack 做严格执行器诊断。
3. RoboDojo：单进程、单空闲 GPU 启动 stack_blocks 的一个既有布局，核验资产、相机、观测、reset、hold 和关停；再做单臂 XYZ ±2 mm 与保持，另一臂及姿态保持。先不调用 GPT/Jev。
4. 两环境分别做同协议多次测试：先单起点、6 个方向加 hold、3 次重复（21 条/环境）；可用后扩展 3 个安全空中起点 × 3 个幅度（1/2/5 mm）× 6 个方向 × 3 次重复（162 条/环境），另有 9 条 hold。各动作从完整复位状态开始，布局/随机种子/完整状态摘要留档。
5. 指标：命令与实际位移、串轴位移、姿态漂移、实际稳定等待、最终速度、IK/限幅/超时、复位偏差；输出逐动作 CSV/JSON 和响应曲线。先用开发检查确定位置、速度、姿态和复位容差，再冻结验收标准，避免看完评测结果才设门槛。
6. 最后检查叠方块的抓取、抬升、释放、支撑、撤离及原生成功条件。接触阶段的结果独立记录；空中位置控制分析不提供接触抓取保证。RoboDojo 若缺可靠正对照，明确报告，不能预设参考控制能完成堆叠。

优先完成 1–3 再扩展样本；Isaac 首次启动建议设 20 分钟诊断上限，单批物理检查控制在 30 分钟，累计单跑不超过 2 GPU 小时。先不保存连续视频，日志预算小于 500 MB；若需要超出预算，按协议升级。API 连通性、视觉模型和完整 RoboDojo 运行仍待验证，当前无需付费模型调用。

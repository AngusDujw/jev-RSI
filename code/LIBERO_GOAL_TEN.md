# LIBERO-Plus Goal 十任务实跑状态

## 2026-10-14 · 5880 十任务最新实跑

**已有 10/10 个不同 Goal 任务至少一次双终局成功；其中8项有同一固定版本五个未见初态5/5的证据。** 成功要求 `success=true` 且 `program_finished=true`；混合版本开发回合不能合并成稳定成功率。Goal1144、1252、1163、1335、1423各有同一固定版本五个未见初态5/5，Goal1383旧冻结init2–6为5/5，Goal1458固定CPU视觉版init11–15亦为5/5；这些均仅代表指定初态。旧服务器记录见下方历史段落，5880 原始正负结果及完整配置见[W42实验记录](../LOGS/2026-W42.md)。运行时 GPT-6/DeepSeek 调用仍为 0；Jev 依据公开任务、双 RGB-D/标定、机器人自身反馈与自身 mesh、真实动作历史选方向、夹爪、候选和阶段。官方成功只在最终评价读取一次。2026-10-12 用户已更新 `AGENTS.md §10` 并明确恢复实验；旧记录中“暂停”仅描述当时规则下的历史状态。

| Goal | 共享尝试 | 5880 新证据与当前判断 |
| ---: | ---: | --- |
| 1098 抽屉 | 55/80 | 正面双指夹持后，同已见init4第48次抽屉部分移动却早松爪，官方false/程序true；第49次真实拉开、官方true，却因固定180mm位置门未到而程序false；第50次用公开可见伸出+自有拉动/受阻有界门让Jev决定阶段，**官方true/程序true**，99 Jev/324步、9阶段边/0违规。[EXP166–168](../LOGS/2026-W42.md#exp-2026w42-168)。固定d117d332（控制源等同e9319db1）未见init6–10为**5/5双终局**，平均98.8 Jev/323.4步，494真实问答动作/45阶段边审计0违规。[EXP169](../LOGS/2026-W42.md#exp-2026w42-169)。 |
| 1144 碗放炉面 | 12/50 | 固定`ae8698ea`的未见init5–9 **5/5双终局**，平均265.8步/88.6 Jev；[EXP081–085](../LOGS/2026-W42.md#exp-2026w42-085)。 |
| 1163 酒瓶放柜顶 | 23/50 | 公开初始颜色+新鲜RGB-D持有后备修复init4遮挡；固定`5522a0d0`的未见init5–9 **5/5双终局**，平均390步/100.4 Jev；其中init5在Jev恢复后由新鲜可见柜顶证据结束，[EXP097–098](../LOGS/2026-W42.md#exp-2026w42-098)。 |
| 1202 开抽屉放碗 | 50/80 | init2开发回合首次完整双终局，585步/168 Jev；冻结版未见init3失败，碗未可靠落入抽屉。[EXP118](../LOGS/2026-W42.md#exp-2026w42-118)、[EXP119](../LOGS/2026-W42.md#exp-2026w42-119)。最后第50次新可见放置门尚未触达即服务断连，属崩溃而非算法验证；仍不稳定。用户2026-10-14已明确扩额到80次；下一回合验证第50次尚未触达的新可见放置门。 |
| 1252 碗放柜顶 | 14/50 | 固定`28856f5b`的未见init4–8 **5/5双终局**，平均338.4步/112.8 Jev；[EXP086](../LOGS/2026-W42.md#exp-2026w42-086)。 |
| 1296 推盘 | 50/80 | `19e00cd2`冻结新init6–8为2/3双终局；公开红盘滑移门`57057062`冻结新init9–10为1/2；末段余量版冻结新init11失败。[EXP145–150](../LOGS/2026-W42.md#exp-2026w42-150)。盘沿侧推第48–49次卡在第二段approach；第50次同init11放宽安全悬停自身位姿门后确实进入lower，但低位X还差约10.5mm、腕姿残差、盘沿未实际被推，579步双false。[EXP151–152](../LOGS/2026-W42.md#exp-2026w42-152)、[EXP162](../LOGS/2026-W42.md#exp-2026w42-162)。各版本不能合并稳定率；用户2026-10-14已明确扩额到80次，新可见接触试推门待物理验证。 |
| 1335 奶酪放碗 | 39/50 | 唯一紧凑同名视觉候选门0.30→0.25的init21配对双终局后，固定`1f80c6c7`在未见init23–27 **5/5双终局**，平均304.8步/76 Jev；原三个旧版五初态批各4/5，分开统计。[EXP109–110](../LOGS/2026-W42.md#exp-2026w42-110)。 |
| 1383 开炉灶旋钮 | 12/50 | 旧冻结 init2–6 为 5/5；5880 init7 再双终局成功，95/95 响应/动作、8/8 阶段边审计零违规。 |
| 1423 碗放盘上 | 37/50 | 旧`55d56ba7`的未见init5–9仅1/5；公开RGB-D支撑面受阻转段、释放与短退离修复后，同一冻结`cb400a42`的未见init10–14 **5/5双终局**，平均262.2步/87.4 Jev；已见失败init6–9的4/4配对单列。[EXP103](../LOGS/2026-W42.md#exp-2026w42-103)、[EXP106–108](../LOGS/2026-W42.md#exp-2026w42-108)。 |
| 1458 酒瓶入斜架 | 29/50 | 固定`448aad8`+CPU视觉在未见init11–15为**5/5双终局**，依次120/130/121/122/120 Jev、504/531/504/507/504步；均一次抓取、问答动作/阶段边审计0违规。[EXP137–138](../LOGS/2026-W42.md#exp-2026w42-138)。GPU旧版另计，5次不是整套benchmark成功率。 |

Goal1098 的 init0、init5 额外保存了仅 10 步张爪的初始双相机 RGB-D 与标定，均为 **0 Jev/0 任务控制**的开发采集，未占正式尝试。两幅公开图像均可见同一柜体、木架与瓶子前景；小幅布局变化不能证明现有侧腕姿路径在新初态可行。目录：`code/runs/2026-10-14-5880-goal1098-capture-init0/`、`code/runs/2026-10-14-5880-goal1098-capture-init5/`。所有本轮抽屉/推盘正式请求与实际动作审计 0 禁用特权字段、0 阶段/夹爪合同违规；相机估计误差和自身整臂可达性仍会导致失败。

第48次前用初态4的公开深度/标定和自体手网格筛查两条旧候选：[EXP164](../LOGS/2026-W42.md#exp-2026w42-164)。初始腕姿直接指尖钩杆需要自体手掌越过可见柜面约23.28mm；柜外侧50mm高位转腕的静态点云沿途名义间隙最小约1.4mm，不能证明安全或动态可达。随后采用正面双指夹持：[可见抽屉几何和阶段控制](scripts/libero_goal_drawer_control.py)在分支`codex/goal1098-down-20261013`提交`e9319db1`，先在柜外下降、再向把手插入，自身指垫包络与可见杆距离用于接触门；外拉≥140mm、距名义目标≤25mm、闭爪保持、抽屉公开可见伸出且连续三块命令受阻时，才向Jev开放试结束阶段边。第50次在自有外拉163.10mm时由Jev选择推进，最终双true。任务目标、RGB-D/标定、自体反馈/mesh及动作历史构成输入；官方成功只在终局读取。随后同控制版冻结未见init6–10达到5/5双终局，样本范围仅这五个初态。[EXP166–168](../LOGS/2026-W42.md#exp-2026w42-168)

Goal1296 的可选盘沿“可见接触试推”门已在独立分支 `0a981f68` 准备好：[EXP165](../LOGS/2026-W42.md#exp-2026w42-165)仅离线回放第50次保存的轨迹，65个第二段lower请求中52个满足自体指尖距公开盘包围盒<5mm、Z重叠、连续执行受阻和自身位姿有界；首次在decision-0099。这是给Jev选择阶段的候选证据，**不是盘已被推动的证明**，实际效果和新初态稳定性尚未测试。5880 GPU0 EGL与CPU视觉预检通过，此前账本50/50；用户已扩额到80次，原固定版本默认关闭新门。

LIBERO-Plus 官方 `assets.zip` SHA256 为 `96764a4bfbdaea98d4411598caeab235458318fe0f549611b93d1a323027b3cf`，ZIP 完整校验通过；解压在 5880 `/home/user/ykj/project/gpt6/LIBERO-plus/libero/libero/assets/`。源码 `/home/user/ykj/project/gpt6/jev-RSI` 依任务切换到上述冻结提交或对应SSH分支，环境是项目 `.venv-libero-plus`；复现前先核对 `git rev-parse HEAD` 与该实验记录。运行新回合需显式设置 `JEV_RSI_MODEL_CACHE`，否则旧配置会尝试访问旧服务器 root 路径。下面保持换行逐行执行；`init-index` 和输出目录须改成需要的新回合，输出目录必须不存在。

```bash
cd /home/user/ykj/project/gpt6/jev-RSI
export JEV_RSI_SIM_PYTHON=/home/user/ykj/project/gpt6/jev-RSI/.venv-libero-plus/bin/python JEV_RSI_LIBERO_ROOT=/home/user/ykj/project/gpt6/LIBERO-plus JEV_RSI_EXISTING_ROOT=/home/user/ykj/project/gpt6 JEV_RSI_API_CONFIG=/home/user/ykj/project/gpt6/controller/config/api.local.json JEV_RSI_VISION_PYTHON=/home/user/miniconda3/envs/isaaclab/bin/python JEV_RSI_MODEL_CACHE=/home/user/ykj/project/gpt6/.cache/models JEV_RSI_MODEL_BACKEND=jev HTTP_PROXY=http://127.0.0.1:7897 HTTPS_PROXY=http://127.0.0.1:7897
.venv-libero-plus/bin/python -B code/scripts/run_libero_goal_jev.py --task-id 1383 --init-index 8 --egl-device-id 0 --worker-device-id 0 --allow-shared-gpu --output code/runs/NEW-5880-goal1383-init8
```

RoboDojo 位于 5880 `/home/user/ykj/benchmark/robodojo`：源码与三个锁定子模块已克隆，`Assets` 的逐文件聚合 SHA256 `b4de896a86d5cdf0452ef65f37a6f00003d24a567c55ae00abe4ffddab4cd0e9` 与旧服务器一致。独立 `.venv-isaac51` 已安装 Isaac Sim 5.1、锁定 Isaac Lab 可编辑子模块及 CuRobo；CuRobo 关键模块可导入，任务清单 54/54 可解析。GPU0 Kit headless 启动并关闭成功。启动该环境时须把环境内 `lib` 放在 `LD_LIBRARY_PATH` 前面，以避开系统 libstdc++ 缺少 `CXXABI_1.3.15`；这仍只证明仿真核心可启动，**尚无 RoboDojo 任务级 Jev 成功率**。

## 2026-10-11 · 旧服务器历史状态

截至 2026-10-11。目标是每个官方任务都由离线确定的视觉处理、几何候选和阶段合同生成 Jev 输入；运行时 Jev 1.13 选择 XYZ/旋转方向、夹爪、候选、阶段和重试。运行时 GPT-6/DeepSeek 调用为 0。本地 GroundingDINO/SAM 只处理公开 RGB-D；策略可用相机标定、任务语言、机器人自身反馈与 mesh、历史真实动作，不能读取场景对象真位姿、奖励或官方成功谓词。`success=true` 与 `program_finished=true` **同时成立**才计完整成功。

| Goal ID | 任务 | 共享尝试 | 当前可核实结论 |
| ---: | --- | ---: | --- |
| 1098 | 开中层抽屉 | 16/50 | 仍无完整成功；俯视单指从上入把手受阻。第16次 `under_hook` 因 EGL 初始化卡住，0 Jev/0控制动作；此候选仍未被实测。 |
| 1144 | 碗放炉面 | 7/50 | 已有完整成功；混合版本开发结果，尚无本配置的冻结稳定率。 |
| 1163 | 酒瓶放柜顶 | 16/50 | init3 一次完整成功；init4 冻结复测与延长闭爪均滑脱失败，未稳定。 |
| 1202 | 开上抽屉再放碗 | 2/50 | 已接通Jev控制的上抽屉第一原语入口，但只通过已存RGB-D离线几何及命令核对；尚无控制回合，放碗逻辑待打开后重看内部。 |
| 1252 | 碗放柜顶 | 9/50 | 已有完整成功；尚无统一冻结稳定率。 |
| 1296 | 推盘到炉前 | 20/50 | 盘可见前移，仍无原生完整成功；需接触与目标关系重设计。 |
| 1335 | 奶酪放碗内 | 9/50 | 已有完整成功；尚无统一冻结稳定率。 |
| 1383 | 开炉灶旋钮 | 11/50 | 冻结 `0b9f2dc` 的 init2–6 为 5/5 双终局，其中 init3–6 为未调参初态 4/4；范围仅这些初态。 |
| 1423 | 碗放盘上 | 15/50 | 旧 init0 一次完整成功；init2 多种抓持/放置方式失败，未稳定。侧抓指垫高度候选尚未实跑。 |
| 1458 | 酒瓶入斜架 | 12/50 | 固定 `823df20` 在未见 init2 首次双终局成功，124 Jev/513 原生步；init3 冻结回合因视觉 GPU worker 启动超时、0控制动作而未评估。 |

当前至少一次双终局成功的是 **7/10 项**，只在 Goal1383 有数个未见初态的固定版本复测。以上各任务不能合并成“十项成功率”，也不能把单个初始化场景的成功写成稳定完成。详细逐回合正负记录在 [本周实验块](../LOGS/2026-W41.md) 的 EXP-2026W41-138～160 与原始 `code/runs/`；成功视频/图像可由保存的公开相机帧重建。

[Goal1383 与 Goal1458 交互式案例网页](reports/libero-goal-casebook/index.html)解释 task-id / init-index，并从两次成功回合嵌入全部 219 组真实 Jev 请求、回答、执行分支及选定相机帧；冻结样本范围与任务特定处理步骤分别列明。运行 `python3 code/scripts/build_libero_goal_casebook.py` 可由本地原始回合重新生成网页数据和图片。

Goal1458 的现行方法见 [可见斜架拟合](scripts/libero_goal_rack_geometry.py)、[Jev 阶段与可见释放证据](scripts/libero_jev_recovery.py)、[单回合计数入口](scripts/run_libero_goal_jev.py)。从已分割的酒架 RGB-D 中拟合承托斜率，瓶身被抓住后 Jev 在高处旋转；下降阻塞时用新鲜瓶体点云相对承托面的法向间隙估计落差。只有瓶仍被可见共运动检查通过、落差在 60 mm 内且投影位于可见架面时，才提供一次低处释放的阶段选项。释放后撤离、等待、重新测可见关系，由 Jev 决定是否结束；官方成功只在回合结束读取。init2 的低处落差 36.02 mm、释放后可见近架像素比例 0.9794，真实答案/执行/阶段边审计 0 违规，原始数据本机与服务器 SHA256 一致，见 [EXP160](../LOGS/2026-W41.md#exp-2026w41-160)。此前高处开爪、静等、横向撤离的负结果保留在 EXP154～159。

服务器为 `company-server-2`，隔离工作树 `/root/yekangjie/project/jev_rsi/.worktrees/ten-goal-20261008`。Goal1458 的一次完整成功来自冻结策略提交 `823df20`；此后工作树为其他任务的入口及抽屉候选更新过，严格复测1458须先将该空闲工作树切回 `823df20`。仿真环境 `/root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python`。init3 第12次的本地视觉 worker 超时已按基础设施崩溃归档。2026-10-11 定向 `nvidia-smi` 可查 GPU5/6，但最小 MuJoCo EGL 渲染仍超时，Goal1098 第16次于0决策处卡住；当前入口在记账前实际渲染一帧，失败时不消耗任务次数，见 [EXP175](../LOGS/2026-W41.md#exp-2026w41-175)。冻结 `823df20` 本身尚无这道预检；严格复测时须先在当前提交用 `--preflight-only` 单独验证 EGL，确认可渲染后再切回冻结代码。GPU 渲染恢复后若手动启动未见新初态，先执行下面两行预检，再逐行执行冻结回合的三行；每条命令本身均是一整行，把 `4` 和输出目录名同步改成实际未用的 init 索引。

```bash
cd /root/yekangjie/project/jev_rsi/.worktrees/ten-goal-20261008
/root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python -B code/scripts/run_libero_goal_jev.py --task-id 1458 --init-index 4 --output code/runs/UNUSED-goal-1458-preflight --preflight-only
```

```bash
cd /root/yekangjie/project/jev_rsi/.worktrees/ten-goal-20261008
git switch --detach 823df20
/root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python -B code/scripts/run_libero_goal_jev.py --task-id 1458 --init-index 4 --output code/runs/NEW-goal-1458-init4
```

当前单回合入口在预留账本前检查同盘至少 6 GiB 空闲、选定两张 GPU 的 NVML 查询以及最小 EGL 渲染；这些仍不能保证后续视觉 worker 启动。入口也支持 Goal1296 推盘的可见 RGB-D/Jev 两段流程，并冻结 `libero_push_control.py` 的 SHA256；这项此前的开发回合仍无官方成功，入口接通不算新的物理结果。正式启动后，setup 失败也计入每任务 50 次，不自动重跑。大文件只写本项目同挂载盘。本轮没有更改显卡、CUDA 或系统驱动，也没有使用本机受限的 API 密钥。

GPU 故障时尝试过现有 Mesa EGL：最小 MuJoCo 渲染可用，但 Robosuite 的 LIBERO 离屏相机不兼容，Goal1098 init2 两次均在场景帧前崩溃，见 [EXP162](../LOGS/2026-W41.md#exp-2026w41-162)、[EXP163](../LOGS/2026-W41.md#exp-2026w41-163)。可选 Mesa 代码已撤回，保留完整失败记录；未修改系统图形栈。

Goal1098 新增待实跑的 `under_hook`：从公开RGB-D选中层杆及相邻下层杆，以两杆世界Z中点作为选中指垫的入深高度；外倾腕姿的自身指垫偏移反解TCP，并检查自有指垫 mesh 的高度能否落入该间隙。初态0保存的可见杆距68.83mm，入深/最终TCP的Z约0.96505/0.99947m。其几何只在已存画面核对，**没有**新Jev/机器人接触或开抽屉结果，见 [EXP165](../LOGS/2026-W41.md#exp-2026w41-165)；只有GPU恢复后实跑才能判断可达性。启用需在单回合命令追加 `--drawer-contact-mode under_hook`，默认仍为旧`top_hook`。

Goal1296 新增待实跑的 `--plate-stage-turn-deg 9`：在可见桌面与无高起障碍的候选中，选择相对旧横向推动方向偏转不超过9°、最靠近炉前的首段路点。已存init0/1画面把首段结束后到公开目标的几何余量分别从77.9/79.3mm缩至43.7/44.5mm，候选偏转7.62°/7.42°，见 [EXP166](../LOGS/2026-W41.md#exp-2026w41-166)。**没有**新推盘动作或官方成功结果；默认0沿用旧首段。

Goal1202 新增待实跑的上抽屉第一原语：公开RGB-D选择顶层把手，自己指垫反解接触TCP；已存图像给出顶杆Z=1.096897m，候选先入深TCP的Z=1.16333m。Jev可决定把手接近、张爪钩住、外拉与阶段；只有该原语执行完才保存末帧双RGB-D/标定。控制器**不会**把它标作完整任务，结果固定注明还缺“重新测打开的内部→抓碗→放入”，见 [EXP167](../LOGS/2026-W41.md#exp-2026w41-167)。目前仍为0次完整控制测试。

Goal1163 增加待实跑的 `--lift-recheck-mm 30` 单次边界持有复核：首轮短抬仅在瓶体可见升高7–15mm、共运动误差<65mm、可见尺寸正常时标为 `ambiguous`，保持闭爪，把目标再提高30mm，并使用新鲜公开RGB-D及初始可见点云投影复核；二次核验使用更严格的30mm升高门槛，通过后才可由Jev决定推进，失败可由Jev重试。已存init3成功回合首轮升高15.17mm，不会触发；init4失败回合首轮11.31mm会触发，第二次是否真正持有**未知**，不能计成功。默认 `0` 不改变旧策略；GPU故障未恢复前无新增物理回合，见[独立诊断记录](../LOGS/2026-10-09-goal-1163-lift-recheck.md)与[EXP168](../LOGS/2026-W41.md#exp-2026w41-168)。

Goal1423 新增待实跑的 `--side-pad-overlap-mm 12`：旧init2侧抓第96步仅一侧指垫贴近可见碗，另一侧距离点云33.31mm，实际指垫高度与可见碗体重叠0mm，却被旧包围盒距离门槛视作可试抓。新候选用公开可见源界与自身指垫/指尖mesh反算侧抓TCP高度，只有执行后的自身指垫实际垂直重叠≥5mm才把未到名义中心时的闭爪试探选项提供给Jev。已存init1/2的计划TCP均下修约7.0mm、几何目标重叠12mm；**仍需真实动作与共运动验证**，默认0保留旧方法。未见init3的一次启动因GPU预检8秒超时而在账本预留前退出，不计入15/50；内核日志同时有`NVRM Xid 109 CTX SWITCH TIMEOUT`。详见[离线诊断及预检](../LOGS/2026-10-09-goal-1423-side-pad-diagnosis.md)与[EXP169–170](../LOGS/2026-W41.md#exp-2026w41-169)。

# LIBERO：可见抓取候选与Jev输入输出组织优化

本轮在company-server-2用15/30次新增尝试将原先未解决的奶酪入篮跑通；奶酪任务累计22/50。最终focused+adaptive配置冻结后在新init7/8/9均完整成功（3/3），一次抓取，无retry。开发各版本合计10次完整成功和5次失败（含setup/协议失败），累计1218Jev、36视觉、4380正式原生步、3234.53秒；混版本累计不是冻结成功率。

本批沿用2026-10-03批次前缀，实际时间以各events.jsonl为准。用户授权新增尝试最多30次；保留原每任务50次总上限。首要任务为libero_object/task1066奶油奶酪入篮。

## 范围与信息边界

策略只读取公开任务语言、双相机RGB-D/标定、机器人自身末端/夹爪反馈以及自身指垫和手指模型。场景物体真实位姿、对象ID、物体资产尺寸、隐藏任务谓词、奖励和官方success不进入模型。官方success只在终局评价读取一次。

新的recovery入口独立于已成功的旧supervisor；各回合冻结全部策略模块及SHA256。初始化10步张爪属于环境准备，不计作Jev决策或正式控制步。

新增回合含setup失败、协议失败及物理失败，都计入30，不自动重试、不替换失败。计数保存在code/runs/libero-recovery30-ledger.jsonl，同时追加原libero-supervisor-ledger.jsonl。每回合900秒/180Jev/550正式原生步/600MiB，每批3GiB。最早几个开发版本native守卫660，但180Jev的实际步数上限540，未超环境horizon600；v6起显式恢复550守卫。

## 算法与决策组织

- 视觉：最多initial、pregrasp、lift_check各1次语义识别；SAM掩膜与RGB-D给出可见几何。腕部仅见部分物体时保留最初完整可见范围，不把局部顶面当完整尺寸。此融合假设物体在抓前未明显移动，仍须关注陈旧位置问题。
- 抓取：从可见范围和支撑面，以及自有指垫/手指包络计算接触高度、预计重叠和桌面间隙；提供三个位置/深度候选。几何预测并非成功标签。
- Jev：选择XYZ方向、需要调整的旋转方向、夹爪开合、候选、阶段advance/retry/stop。候选题只在select询问，排除已失败候选。未请求旋转执行零命令，不冒称为模型输出。
- 阶段：select→approach→align→descend→grasp→test_lift→lift→carry→lower→release→retreat。可用retry进入recover_up→recover_open→select。所有实际阶段边由Jev响应触发，无距离自动推进。
- 输入：每个轴单独提供当前位置、目标、误差与相对关系，配合阶段合同、完成证据、夹爪实际开度/执行时长、最近三次动作及可恢复选项。local/evidence/contract组织候选均保留来源。新增focused只保留当前阶段相关证据：候选列表仅select给出，其他阶段只给当前候选的可见宽度、指垫重叠和桌面间隙；删除重复位置向量，抓持证据保留状态、观测时刻、上升量与共运动残差摘要，完整RGB-D测量仍存原始文件。
- 幅度：远处较大步幅、接触附近较小步幅；严格保留Jev符号，不悄悄反转方向。实际位移重新测量。

## 已有证据（持续追加，最终以campaign.json为准）

1. v1/v2为数组维度setup错误，均0Jev/0正式动作，仍计入上限；提取fit_candidates后以保存的自有机器人几何离线检查0/30/60/90度候选。重放中的名义水平面仅用于数学守卫测试，不当作物理成功。
2. v3输入默认candidate_0，同时又允许keep，Jev返回keep+advance，被接口拒绝。候选输出域改为仅在select给出未失败候选，其他阶段不询问。
3. v4只给误差数组时，Y目标低约119mm却多次选择positive，接近预算退出。该记录明确说明输入组织会影响方向判断。
4. v5逐轴输入取得186/186正确XYZ方向，接近15次完成；下降每次仍正常移动约4.7mm，但统一6mm动作参数与45次阶段预算不匹配，退出时尚差约50mm。v6改为粗到细幅度以匹配预算。

完整逐回合、冻结提交和配置由code/runs/2026-10-03-libero-recovery30-summary/campaign.json保存；EXP映射由同目录exp-ids.json保存。开发init1重复使用，不称独立评测。


## 完整成功与执行块配对比较

第6次（v6/init1）首次完整成功，135Jev/405原生步/3视觉/289.76秒。冻结v6的全部策略文件后，新init4/5/6分别137/136/135Jev、411/408/405步，均完整成功。后三个初态在运行前没有参与本批调参。

在相同init4/5/6改用adaptive：远离目标超过60mm，或纯夹爪等待阶段，每次决策执行6原生步、增益0.35；接触附近执行3步、增益0.5。分别95/92/96Jev、408/399/408步，仍3/3完整成功。平均Jev从136降至94.33（下降30.6%），原生步从408降至405，平均墙时从290.53秒降至272.86秒（下降6.1%）。3个配对初态已成为开发数据，不能再称未见验证。没有改变方向、夹爪或阶段决策的所有权。

成功回合均一次抓取、没有retry；本批尚未证明恢复分支有效。v6与确认批总4/4、自适应3/3各自保持配置，不能把混版本开发累计比例当冻结性能。

第1–12次真实响应和执行审计：935次决策、81条阶段边、0次提前advance/retry；XYZ实际响应、夹爪命令、询问旋转及阶段边均匹配，未询问旋转在容差内且执行零。输入根字段白名单与递归禁止字段检查通过；信息来源还经过策略源码审查。逐轴正确指标相对可见估计，不是场景真值准确率。

## 理论口径

Discussion显式引用的历史草稿及会议笔记已复核：它们旧版关节空间描述由2026-09-28末端XYZ/ypr纠正覆盖。方向质量、动作幅度、原生执行成本和完整抓取成功分别报告；局部下降关系不保证接触任务成功。本批是可见几何与阶段合同辅助的系统可行性比较，不证明Jev相对简单反馈控制的独立价值，不更改method正式定义或研究主指标。


## 实际输入与输出示例

focused/init7的[decision-0043完整请求](../code/runs/2026-10-03-libero-recovery30-focused-v1/libero_object-1066-init-7/decision-0043/request.json)与[完整响应](../code/runs/2026-10-03-libero-recovery30-focused-v1/libero_object-1066-init-7/decision-0043/response.json)保存全部state、问题文本、选项、概率和usage，不是重写prompt。这个时刻处于test_lift：X误差0.03mm、Y误差1.93mm，在2mm保持容差内；Z目标比当前位置高3.78mm。RGB-D观察源物体上升43.36mm，与TCP预测的共运动残差6.91mm，holding=passed。末端位置与姿态满足该阶段6mm/0.03rad容差，允许advance。

Jev真实输出x=hold、y=hold、z=positive、gripper=keep、transition=advance；旋转三个轴均在容差内，没有提问，不补造模型答案。执行器保留这些符号，先执行3原生步，再依据真实advance进入lift。提前推进违例为0。holding标签由公开RGB-D测量规则产生，不是原生抓取状态或任务成功标签。

常规阶段只询问XYZ、夹爪和阶段三个类别的一次批量请求；select额外问候选，旋转误差超容差时额外问对应轴。解析器要求返回题集等于询问题集且choice属于给定选项。非法输出保存后终止，不能由代码静默修正。


## 改进的适用范围与剩余问题

指垫拟合、可见范围保留、逐轴结构、阶段合同和接触附近缩短执行块均没有奶酪颜色、类别专用拟合或任务ID分支。当前仍是刚性物体入开放容器的pick/place任务族：外部程序定义阶段图、目标与容差，Jev在该图中选择动作和边；候选数量、夹爪等待时间与执行幅度仍由程序给出。不能据此声称已解决按钮、衣物或动态传送带。

source范围保留默认抓前物体静止；共运动和接收容器可见高面都是视觉代理，未在场景真值上单独定量验证。新回合官方终局成功才构成完整成功，位置容差/图结束不替代它。恢复分支虽然可由Jev选择，本批成功没有使用，不能宣称已验证失败后恢复。

旧topic libero-generic-vision仍有CIRCLE-1。收敛方案是最多30次有界比较，获得固定候选的新初态完整成功后封存，不为凑足预算继续改变参数，不自行关闭当前议题或写decision节点。


## 最终冻结结果与推荐

| 配置 | 初态 | 完整成功 | 平均Jev | 平均正式原生步 | 平均秒 | 每请求平均实际输入token |
|---|---|---:|---:|---:|---:|---:|
| local、3步执行基线 | 4/5/6 | 3/3 | 136.00 | 408.00 | 290.53 | 2863.74 |
| local、adaptive | 同4/5/6配对 | 3/3 | 94.33 | 405.00 | 272.86 | 2864.58 |
| focused、adaptive | 新7/8/9 | 3/3 | 94.33 | 404.00 | 271.09 | 1873.16 |

focused新初态7/8/9分别92/96/95Jev、396/411/405步、267.77/282.92/262.57秒，均3视觉、0DeepSeek、一次抓取，官方success与program_finished同时为true。此前本批调参未使用这三个初态，运行开始前一次性冻结全部策略模块；策略commit为44b7898，所有源码SHA256见manifest，报告/审计工具的后续提交不改变冻结策略。

input token由283个实际Jev响应的usage读取，全覆盖；focused每请求平均1873.16，对比local/adaptive观测到2864.58，低34.6%。两组是不同初态，不能把这两个均值当严格配对的输入精简因果增益。执行块30.6%的调用下降则来自同初态4/5/6配对，不宣称方向信息质量提高或物理步数减少30.6%。最终推荐pad_fit+preserve_source+focused+adaptive；其适用范围仍是本任务刚性抓放。

最终15回合审计1218次Jev决策、114条实际阶段边，0次contract违例；真实XYZ/旋转/夹爪/候选/阶段响应匹配执行与阶段事件，请求严格ASCII并经英文源文本复核，输入白名单和递归禁止字段通过。仅终局读官方成功，不进入策略。11个策略/入口/审计/汇总模块AST解析通过，真实闭环与报告工具验证完成；项目没有单元测试入口，未创建临时测试脚本。

全部15次的完整EXP为181–185及225–234；[逐次映射](../code/runs/2026-10-03-libero-recovery30-summary/exp-ids.json)、[汇总](../code/runs/2026-10-03-libero-recovery30-summary/campaign.json)、[执行审计](../code/runs/2026-10-03-libero-recovery30-summary/audit.json)和[冻结manifest](../code/runs/2026-10-03-libero-recovery30-focused-v1/manifest.json)均保存。测试命令见[LIBERO说明](../code/LIBERO_PLUS.md#可见指垫拟合与focused阶段输入)，候选配置中原UNSOLVED已更新，旧失败记录保留。

达到固定配置的新初态完整成功后，在15/30处封版；不为用完30次继续调参或追加实验。后续若检验其它任务，需要冻结同信息权限与输入结构并独立报告，不能把当前3/3移作泛化成功率。


## 完整性与保存

最终本地/服务器全部冻结批目录与两个ledger共7,022个文件、1,945,242,132字节逐文件SHA256一致，无缺失和差异。证据：[完整性结果](../code/runs/2026-10-03-libero-recovery30-summary/sync-verification.json)、[服务器清单](../code/runs/2026-10-03-libero-recovery30-summary/server-inventory.json)、[本地清单](../code/runs/2026-10-03-libero-recovery30-summary/local-inventory.json)。运行过程中复制的3份Torch瞬时生成模块在服务器正常退出时已自清理，本地副本保留移入summary/local-transient-cache-snapshot；没有删除实验数据或其它任务文件，旧差异检查也保留。

所有本批仿真与分割子进程已退出，最末批finished.json为3/3、returncode均0。数据仍在指定项目同一挂载盘；没有驱动/依赖改动、没有另盘大文件或/tmp写入。

文件变更：新增libero_robot_geometry.py、libero_jev_recovery.py、run_libero_recovery_batch.py、audit_libero_recovery.py、summarize_libero_recovery.py及本报告；修改libero_jev_rollout.py、code/configs/libero-supervisor/candidates.json、code/LIBERO_PLUS.md、LOGS/2026-W40.md、LOGS/2026-W40-activity.md、Discussion.md、TIMELINE.md以及两份被引用资料笔记（ref/notes/idea-draft-v0.1.md、ref/notes/具身智能机械臂控制理论与论文框架-5b7a9009.md）。原始请求/响应、图像、几何、manifest、ledger、审计、usage和哈希清单归档在code/runs的本批目录。

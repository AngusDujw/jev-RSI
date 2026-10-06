# LIBERO-Plus Jev 开发抓放

**2026-10-05 GPT-6 Sol/xhigh 对照入口：**用户将后续 LIBERO 的语义视觉、XYZ/旋转方向、夹爪、候选和阶段选择统一改为本机 ChatGPT 登录的 Codex CLI。见[运行器](scripts/run_libero_pro_batch.py)、[服务器桥接客户端](scripts/codex_pro_bridge.py)和[本机桥接服务](scripts/codex_pro_bridge_server.py)。新批仍使用同一公开任务、双相机 RGB-D、可见几何和本体反馈；模型未接收对象真值、奖励或隐藏成功谓词。旧 Jev 冻结结果保留为历史基线，不能与新模型试次合并计算成功率。当前新模型链路已通过双角色试调用和服务器非物理预检，物理成功率单列统计。

**2026-10-03批次更新（实际UTC+8事件为10月4日）：奶酪task1066的可见指垫拟合与focused输入使用独立的`--recovery-supervisor`入口。逐版正负结果和真实输入输出见[优化报告](../LOGS/2026-10-03-libero-recovery30.md)，候选配置见[配置表](configs/libero-supervisor/candidates.json)。**

**最新执行入口默认由Jev选择夹爪和阶段；旧自动流程须`--scripted-supervisor`显式复现。处理/输入比较及20回合结果见[控制权实验报告](../LOGS/2026-10-02-libero-jev-ownership.md)。**

**2026-10-02更新：入口默认启用通用语义视觉，不再调用下述历史碗专用前处理。新路径与失败开发结果见[通用视觉报告](../LOGS/2026-10-02-libero-generic-vision.md)。历史成绩必须显式使用`--legacy-vision`复现，不能移作通用版本成绩。**

入口：[scripts/libero_jev_rollout.py](scripts/libero_jev_rollout.py)。运行于 company-server-2。

选定 `libero_spatial` API 0-based task_id=988，classification ID=989，Language Instructions / difficulty=1。
完整任务：`pick_up_the_black_bowl_between_the_plate_and_the_ramekin_and_place_it_on_the_plate_language_5_view_0_0_100_0_0_initstate_0`。
它是Spatial任务族的Plus语言改写变体，不是已核实逐任务GPT-6得分的同一个Pro实例。Harness VLA Table21给出Spatial-T组100%，不能移作Plus成绩。

## 信息与职责

- 复用jev_rsi的Recorder/Jev和已有TypeSafe连接，实际返回jev-1.13.0。
- 策略输入仅RGB-D、相机标定、本体反馈和任务指令。真值物体位姿、分割ID、奖励及成功谓词不进入策略。
- 本地颜色/形状+深度前端有任务专用假设：红边盘、暗色碗；以距盘最近的碗实现between语义。这不是泛化语言理解。
- 外部代码决定抓放阶段、固定姿态、夹爪、几何目标与幅度；Jev只选XYZ负/保持/正。幅度为min(25mm,0.65×逐轴误差)。方向概率完整保留。
- 抓后一次RGB-D刷新估计碗-TCP偏移，再修正搬运/放置目标。抬升后的候选可能混入夹爪；仅通过离线过滤测试，未证明身份或偏移精度。
- DeepSeek调用0次，未在本入口配置或保存用户凭据。当前没有额外模型回退。
- 限制：900秒/120Jev/550原生步/400MiB；3tick不构成停稳认证。native success仅最终评价读取。

## 环境与运行

环境来自前一轮安装：Python3.10、MuJoCo2.3.7、Robosuite1.4.0、NumPy1.26.4、Torch2.2.2+cpu；本轮新增httpx0.28.1及其依赖。
源码资产位于embodied-jev目录，只作为独立仿真依赖；实验策略和日志仍在jev_rsi。

以下逐行执行，最后一行是一条完整命令，无需拆行。输出目录必须不存在。

```bash
cd /root/yekangjie/project/jev_rsi
/root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python -B code/scripts/libero_jev_rollout.py --legacy-vision --task-id 988 --seed 0 --output code/runs/NEW-libero-jev
```

脚本在导入仿真前设置专用LIBERO_CONFIG_PATH、EGL GPU0、项目缓存路径。运行前检查GPU0是否有其它作业。`--capture-only`不调用模型。
上面入口已按相同参数方式运行3次；当前最新的高度过滤修正版仅重放通过，需新鲜回合复验。

## 本轮结果

| 版本 | native success | Jev | 原生步 | 秒 | 失败说明 |
|---|---:|---:|---:|---:|---|
| v1 | false | 74 | 254 | 102.70 | 抓取搬运完成，碗偏在盘边 |
| v2 | false | 42 | 126 | 87.88 | 最后动作到达容差后循环仍报超时；未夹取 |
| v3 | false | 48 | 160 | 95.48 | 已抬升，抓后高度过滤拒绝碗轮廓 |

开发总0/3，不是冻结评测；同一任务、init0、seed0重复调试。v3失败帧重放估计offset_xy=(-0.01669,-0.03389)m，0新增动作/模型调用。下一轮只能检验此候选能否真实改善放置，不可当作成功结果。

证据：code/runs/2026-10-02-libero-jev-v1、v2、v3；完整Jev输入输出、原生步和阶段PNG均保存；v2/v3阶段另存深度。


## 2026-10-02 腕部版本：首次成功

新增 `held_rim()`：使用当前腕部RGB-D和动态相机标定，将可见黄/橄榄色碗沿投影到世界XY后拟圆；不是隐藏物体位姿。圆半径25–90mm、残差<5mm、弧长>0.7rad、中心距TCP<100mm为质量门槛。lift/carry各一次，若外部视角也通过则要求中心差<20mm。外部视角拒绝时只用腕部，不混入低质量估计。

此轮返回native success=true：1/1，77次Jev、263原生步、98.73秒，DeepSeek/GPT-6均0。抬升和搬运后的腕部偏移分别约(4.26,-49.26)mm与(4.78,-48.93)mm。已按上面的启动方式实际运行；成功版本代码提交0b86c91。

过程保存每步外部和腕部PNG，阶段另保存各自深度及动态标定。视频是保存观测帧回放，不包含API等待。此配置依赖碗沿外观和固定抓放阶段，仅证明单个开发初态可行性；不能声称通用视觉或稳定成功率。

## 固定20初态验证

2026-10-02：成功版本增加`--init-index`选择，`run_libero_batch.py`冻结源码后测试官方初态1–20，各1回合，16/20=80%。开发init0不计入；失败2/13/14/18均为lift后腕部拟合拒绝。共1244Jev、4308步、31.5分钟；无额外模型调用。详见[报告](../LOGS/2026-10-02-libero-frozen20-results.md)。

## 三任务迁移

新增`--relation near_ramekin|table_center|near_plate`显式外部目标选择，只影响选择此参数的回合。`run_libero_transfer.py`冻结源码测试1030/1062/1282各init1–3；分别0/3、0/3、3/3。详见[迁移报告](../LOGS/2026-10-02-libero-transfer-results.md)。原task988控制不传此参数，旧20次结果不变。

## 通用视觉首次成功（2026-10-02续测）

通用默认路径e07f259在task1062/init1成功：69Jev、2GPT视觉、239步、177.97秒。抓点沿夹指闭合轴取可见边缘，不再用碗颜色/圆形拟合；仍是单物体抓放几何启发式。同版task1030/init1下降恢复失败。详见[完整报告](../LOGS/2026-10-02-libero-generic-validation.md)；旧80%不属于此通用版本。

## 每版3次配对改进

新入口`run_libero_generic_triplet.py`冻结源码运行task1062/init2–4。基线3/3，执行响应补偿1/3（已否决），恢复基线幅度＋放置前源/目的RGB-D复测3/3（默认保留，但未证明比基线更优）。每回合语义模型均2次。详见[配对报告](../LOGS/2026-10-02-libero-generic-triplets.md)。新增复测不依赖具体物体类别；3个初态已成为开发集，后续必须新初态验证。

## 冻结通用流程跨任务

增加`--suite`选择与`run_libero_generic_cross_tasks.py`，策略保持不变。Spatial1282盘旁碗1/3、Object1066奶酪0/3、Object1043汤罐0/3；详见[跨任务报告](../LOGS/2026-10-02-libero-generic-cross-tasks.md)。未证实稳定类别泛化。


## 可见指垫拟合与focused阶段输入

`--recovery-supervisor`优先选择新入口，旧的碗/汤罐supervisor入口保持。处理链是公开任务和双相机RGB-D → 语义源/目标框与SAM分割 → 可见支撑面/物体范围 → 自有手指/指垫几何拟合的3个候选 → 当前阶段合同及逐轴坐标 → 一次Jev批量选择 → 保留模型符号的受限执行 → 重新测量。策略不读场景对象真位姿/ID/隐藏尺寸或任务谓词；官方success只在终局评价读取。

Jev实际选择XYZ、超旋转容差的轴、夹爪open/close/keep、候选以及continue_phase/advance/retry/stop。常规阶段不问候选；未询问的旋转轴必须在容差内且执行零。外部程序仍定义阶段图、几何目标、证据阈值与幅度，不代表模型自主发明抓取策略。

focused输入保留task、operation/next_operation、operation_contract、translation_axes（每轴current/goal/error/relation）、夹爪实际开度/命令时长、completion_evidence、holding_evidence摘要、allowed_transitions、最近3次真实动作和停滞计数。select给完整候选列表，其余阶段只给当前候选三个几何量。原始视觉测量与完整请求/响应都保留。

抓前腕部看到局部时，保留初始较完整的可见范围；指垫深度考虑可见物体与支撑面、自有指垫重叠和指尖桌面间隙，不使用碗颜色/圆形特定拟合。adaptive在远离目标>60mm或纯夹爪等待时每决策6原生步（gain=0.35），接触附近3步（gain=0.5）。位移符号严格来自Jev，代码不能静默反转。

视觉大模型固定initial/pregrasp/lift_check最多各1次，本批使用gpt-6-astra；DeepSeek闭环0次。每回合900秒/180Jev/550原生步/600MiB，每批3GiB；新回合前至少6GiB空闲、运行时至少4GiB，不清理其他任务。所有setup和物理失败计入新增30次与每任务累计50次，不自动重试。恢复分支本批未启用。

以下在company-server-2逐行执行；最后一行是完整命令，无需拆行。`NEW-libero-focused`换成尚不存在的输出目录名称，其余参数与本批实际运行一致。批入口仍会检查已有授权计数，不在此文档中自动追加回合。

```bash
cd /root/yekangjie/project/jev_rsi
/root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python -B code/scripts/run_libero_recovery_batch.py --input-organization focused --grasp-algorithm pad_fit --preserve-source --execution-profile adaptive --inits 7,8,9 --output code/runs/NEW-libero-focused
```

脚本默认任务为libero_object:1066。若需要严格复用归档策略，加`--frozen-from code/runs/2026-10-03-libero-recovery30-focused-v1/frozen`，入口逐文件验证SHA256后复制策略；完整配置和源码哈希以该批manifest为准。source版本与运行器版本分别保存在manifest，不以最后文档提交冒充历史实验代码。

本轮新增15/30次，奶酪累计22/50；最终focused+adaptive新init7/8/9完整成功3/3（92/96/95Jev），每回合3次语义识别。上述启动方式和参数已在company-server-2实际运行3回合、全部returncode0，最终配置和原始输入输出均已归档；不继续追加本轮回合。
## 冻结验证与录像归档（2026-10-04）

新的[`run_libero_frozen_validation.py`](scripts/run_libero_frozen_validation.py)原样复用既有frozen源码SHA及配置，验证ledger独立于开发ledger，原每任务50次总账继续生效。预留回合前做网络DNS/TCP预检，首次网络失败即中断，不自动重试；只对结束回合审计和归档。

[`libero_frame_archive.py`](scripts/libero_frame_archive.py)用CPU编码RGB无损录像，逐帧要求恢复后的PNG字节SHA与原文件一致，才移除本会话已备份的冗余控制PNG；完整原图仍在本地。[`summarize_libero_validation.py`](scripts/summarize_libero_validation.py)包含父进程中断时遗漏的真实子结果，不补造returncode，保留基础设施失败与物理结果的区别。

当前奶酪新批仅有5次DNS阻断、0正式动作，20次有效验证尚未完成。其它四项待恢复联网。任务来源与对应见[`top5-correspondence.json`](configs/libero-supervisor/top5-correspondence.json)，明确是Harness VLA中并列最高任务族的Plus对应，不是唯一前五排名或Pro-T相同扰动实例。详细状态见[本轮报告](../LOGS/2026-10-04-libero-verify20-top5.md)。

2026-10-05 后续实验已按用户决定统一迁移到 ChatGPT 登录的 GPT-6 Sol/xhigh。奶酪 task1066/init26 的新模型物理开发回合完整成功，399 原生步、93 次新模型控制、3 次新模型视觉；这是新模型证据，不能并入上段 Jev 冻结验证。启动方式、审计与目录见[Pro 模型实验说明](PRO_ACCOUNT_EXPERIMENTS.md)。

用户于2026-10-05进一步将奶酪task1066的共享总尝试上限从50提高到59：原总账39次后，以Pro账号GPT-6 Sol/xhigh和init26成功回合的冻结源码对官方新初态27–46做20次独立评测。其它LIBERO任务仍遵守每任务50次。旧Jev和新Pro各自的回合、模型调用与成功率必须单列。

2026-10-06结果：init27–46的20个新增新模型尝试已执行，19个官方完整成功；init30因7903反向转发中断而没有完整终局，保留为基础设施崩溃记录且没有重跑。故本轮是**19/19可评估成功、20次尝试中1次未评估**，共享总账已达59/59。第三批init31–46按同一冻结源码16/16完整成功。20回合真实动作/输入权限审计合同违规0、已完成模型回复均为`gpt-6-sol/xhigh`，双相机视频与全部账本已做本地/服务器哈希核对。逐初态结果和复现范围见[报告](../LOGS/2026-10-06-pro-cheese-frozen20.md)；它不构成其它四项对应任务或整个LIBERO-Plus/Pro的成功率。若要补足第20个完整可评估回合，需先获得超过59次的明确授权。

## 非抓放接触推送开发（2026-10-06，暂停）

`libero_goal:2404` 是官方 Plus 扰动任务 `push_the_plate_to_the_front_of_the_stove_light_1`。[`libero_push_control.py`](scripts/libero_push_control.py)以公开语言和双相机RGB-D定位盘子及可见空桌面目标小框，用自身夹指mesh与可见物体范围估计盘后接触位姿；模型给出XYZ/旋转方向、夹爪和阶段边，程序限定幅度。原生成功只在回合结束读取；没有读取BDDL目标区域坐标、场景物体真值或奖励作为策略输入。

`run_libero_pro_batch.py --profile push --suite libero_goal --task-id 2404`支持冻结源码、逐次总账与审计；EGL设备和分割GPU需使用两个在`CUDA_VISIBLE_DEVICES`中都可见的编号，既有分割worker固定选择可见设备`cuda:1`。目前官方init0只采集场景，init1–3连续三次在正式控制前崩溃：EGL设备可见性、worker设备相对索引、视觉桥接`source`/`destination`契约。三次失败原样保留，计入共享账本4/50；模型控制0、正式原生步0、完整成功0。第三项已把目标改成可见`destination`小框，但尚未实跑。依据[EXP-2026W41-048至050](../LOGS/2026-W41.md#exp-2026w41-048)和`AGENTS.md` §10，暂停新增物理初态，等待继续实验的用户决定。

2026-10-06续测（用户允许后）：init4视觉与SAM成功，但自有夹指高度字段错误，0控制；init5达到接近阶段却有222步X停滞，人工中断；init6在保持原始朝下姿态、提高接近净空后完成`prepare→approach→lower`两条模型阶段边，96步/20控制，但下降距接触183mm时模型依据停滞选择stop。所有回合官方success=false且program_finished=false，尚无一次真实推送；共享账本当前7/50，init4–6三连Crashed再次触发暂停。新静态版本将可见SAM掩码沿推送方向的后沿投影替代AABB估计（存档测得54.4mm对旧76.9mm），缩短盘后余量35→10mm，并在模型闭爪后重算机器人自身接触网格；离线重放目标接近点移动47.5mm且指尖高度仍与盘子相交。**新版本未做物理验证**，详细负结果见[EXP052–055](../LOGS/2026-W41.md#exp-2026w41-052)。只有再得到用户继续许可，才可用新初态测试，不能将奶酪19/19迁移成此任务成功率。

# LIBERO-Plus Jev 开发抓放

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

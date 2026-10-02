# 数字按钮集中调试：新增5回合

**状态：新增5次预算已用完，未取得原生成功；没有启动正式10＋10对照。**

| 回合 | 原生成功 | 步数 | Jev | 程序按压尝试 | 停止原因 |
|---:|---|---:|---:|---:|---|
| 1 | 否 | 84 | 17 | 0 | controller_stop:four Jev all-hold actions outside convergence zone |
| 2 | 否 | 79 | 16 | 0 | controller_stop:four Jev all-hold actions outside convergence zone |
| 3 | 否 | 478 | 100 | 11 | controller_stop:bounded press attempts completed; native outcome is evaluator-only |
| 4 | 否 | 650 | 99 | 11 | controller_stop:bounded press attempts completed; native outcome is evaluator-only |
| 5 | 否 | 664 | 121 | 10 | controller_stop:phase budget exhausted without verified progress |

共353次物理闭环Jev请求，另外2次保存状态的API重放；运行时GPT-6与DeepSeek均0。五回合版本不同、均为同一开发布局，不是冻结方法的独立成功率。

## 已定位的问题

1. 感知不确定性与机器人跟踪容差混用，以及固定夹具航点/不可见物体标记冲突，导致接近阶段Jev保持；精简为有界航点方向查询后能继续执行。完整感知仍保留在debug，参考明确标记历史来源。
2. 第3、4回合完成了9＋1＋蓝确认共11次程序循环，但原生未成功。程序尝试次数不等于实际按钮激活次数。RGB-D能看到表面按压/撤回约10mm的变化，但不能据此断言每次都被正确计数。
3. 第5回合按空间顺序完成10次红按钮程序尝试后，在蓝按钮接近阶段选了当前更近的左臂。末端还差约19mm X/12mm Y/11mm Z，但收到非零命令后实际位移0；阶段预算耗尽。最近距离不能代替可达性判断。

## 候选修复状态

[工作区选臂教训](../code/experience/candidates/press-focus-workspace.md)保存为candidate，不自动激活。代码准备了按初始双臂位置的本侧工作区启发式；离线重放能把蓝按钮分给右臂、左红按钮分给左臂。这不是完整IK可达性证明，也没有做第6个物理回合。

**不能说“只差蓝按钮就一定成功”**：第3、4次虽完成整段序列也未成功，仍可能有触发次数/接触稳定性问题。下一次需要同时核实选择机械臂和实际按钮事件，而不是只看程序计数。

## 方法与经验

参数、适用条件与负结果写入[按压经验](../code/experience/press_focus/press.md)，执行器见[控制器](../code/controllers/press_focus/controller.py)。当前是任务专用有界按压原语，未证明通用规划或经验增益。

经验驱动：18mm最大法向探测、跟踪容差2mm（仅press_stroke）、末端停留与转移高度；Jev始终提供非零XYZ方向，外部控制器提供幅度、姿态、夹爪和阶段切换。原生700步与成功谓词没有修改。

## 数据与复现

每回合code/runs/press-focus-dev01..05保留源码哈希、经验快照、RGB-D、Jev请求响应、实际动作及原生结果；精确commit与命令见[JSON](press-focus-results.json)。本地与服务器8,770个原始文件SHA256一致；5个自有仿真进程均已退出。接口重放和离线选臂检查不计物理回合。

## 修改/新增

- code/controllers/press_focus/：隔离的控制与经验加载候选，保留历史版本复现路径。
- code/experience/press_focus/press.md：按压经验及参数；code/experience/candidates/press-focus-workspace.md：未激活的选臂候选。
- code/configs/press-focus/dev.json：有界开发配置。
- LOGS/press-focus-plan.md、press-focus-results.md、press-focus-results.json、周志、Discussion、流水：计划、全部失败与停止记录。

本轮按用户新增5次预算停止，不追加试跑，不把离线检查或完成动作序列当任务成功。

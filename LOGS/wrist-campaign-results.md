# 腕部相机与通用拾取：20回合开发结果

**状态：本轮20回合已结束，无继续运行的实验。general_pickup已在两个布局原生成功；另外四任务尚未完成。**

## 结果口径

| 任务 | 成功/开发尝试 | 成功率 | 最后回合停止原因 |
|---|---:|---:|---|
| general_pickup | 2/4 | 50% | 两个布局均抓起并完成原生目标 |
| stack_bowls | 0/4 | 0% | 抬升后未验证到碗同步上升 |
| fold_clothes | 0/4 | 0% | 衣物观测不确定性超限 |
| press_by_number | 0/4 | 0% | 按压阶段未取得可验证进展，阶段预算耗尽 |
| match_and_pick_from_conveyor | 0/4 | 0% | 等待再次匹配直到700步；内部视觉刷新45次上限未及时部署修复 |

**这些是不同开发版本的尝试完成比例，不是冻结策略的正式基准成功率。** general_pickup前两版各失败1次，固定视觉抓取参考点后的layout0剪刀和layout1塑料铲各成功1次。不能将两个成功回合外推为总体100%成功率。

## 两个成功回合

| 布局/目标 | 原生结果 | 步数 | Jev | 本地视觉刷新 | 使用当前有效腕部观测的帧数 |
|---|---|---:|---:|---:|---:|
| Pick up the mint green scissors by 10 cm. | success=true | 126 | 22 | 49 | 11 |
| Pick up the lavender plastic shovel by 10 cm. | success=true | 160 | 30 | 55 | 28 |

成功回合原始数据：[剪刀](../code/runs/2026-10-02-wrist-attempt03/structured_result.json)、[塑料铲](../code/runs/wrist-confirmation-layout1/structured_result.json)。各目录simulator/sensors.mp4保留原生三视角录像。

## 实现与观测权限

- 头部视角先建立目标身份；三路相机分别做本地GroundingDINO/SAM2、光流和RGB-D表面测量，按类别与标定后的空间位置关联。腕部恢复不直接平均各视角中心。
- 接触阶段可选活动臂腕部；general_pickup固定初始视觉抓取参考点，并要求当前多视角证据，避免追逐随遮挡变化的表面top。其他任务版本将非活动物体留在头部视角。
- 阶段、姿态、夹爪和非负幅度为外部程序；所有非零XYZ方向由当次Jev响应给出。每阶段保留状态、误差、可见性、观测年龄、视角选择、Jev输入/输出、实际关节动作。
- 本轮运行时GPT-6调用为0。DeepSeek只做过1次离线图像预检，返回HTTP402 Payment Required；没有获得可用视觉响应，随后禁用重复请求，20回合中DeepSeek调用均为0。密钥只存在服务器.private，不进入Git或日志。
- 可选DeepSeek接口已实现：只有进入观测恢复、活动臂腕部本地检测仍不可信时才可调用，正常上限3次/回合；当前配置上限0，因为预检402。它只允许输出可见标签/轮廓/关键点，不输出动作或隐藏位置。该接口因402尚未通过成功响应验证。
- 线上没有物体真值、布局物体位置、奖励或原生答案。独立审计仅写盘，RPC返回记录成功标志；原生success只用于外部评估。

## 未完成与未验证内容

叠碗仍是物理抓取未抓牢；叠衣服缺少可靠的变形关键点/遮挡跟踪；按钮虽本地OCR读出卡片1和9，但按压触底与计数反馈未闭环；传送带有时序匹配与刷新预算缺陷。不能把这些都归因于Jev方向错误或DeepSeek不可用。

收尾审查发现：提高多视角内部视觉刷新上限到100的改动未进入最后传送带回合。最后回合仍在45次后停止刷新图像语义并等到原生700步失败。修复及逐视角拒绝诊断已经另行提交，但没有在本轮20次预算内重跑；最终源码不等于每个既有回合的运行源码，复现须使用各回合provenance和generated_provenance。

## 数据与复现

本轮20回合共295次Jev请求、969次本地视觉回调尝试。逐回合统计含commit、命令、阶段、步数、时间和成败，见[wrist-campaign-results.json](wrist-campaign-results.json)。

完整实验块为LOGS/2026-W40.md中的EXP-2026W40-025～044。全部回合（包括初始选择失败、零Jev和未收敛）均保留，不筛选成功案例。原始大文件在服务器和本地code/runs内，普通Git同步源码/配置/研究记录；哈希清单为code/runs/wrist-campaign-raw-sha256.json；11,473个原始文件本地与服务器SHA256一致，全部20个自有仿真进程均已退出。

成功的通用拾取控制器见[controller.py](../code/controllers/wrist_v1/controller.py)，其余任务版本见[controller.py](../code/controllers/wrist_other_v1/controller.py)。首次成功回合的代码commit为5169b56；后续确认回合及所有失败的确切commit见逐回合JSON。

## 修改/新增文件

- code/controllers/wrist_v1/：通用拾取多视角控制器、基类与视觉组件。
- code/controllers/wrist_other_v1/：其余四任务的多视角控制与阶段修复。
- code/scripts/local_rgbd_perception.py：目标提示、实例去重、本地OCR适配。
- code/scripts/local_digit_ocr.py：本地字体模板数字识别。
- code/scripts/deepseek_fallback.py：低频、可审计的可见事实兜底。
- code/scripts/structured_task_runner.py：兜底调度、调用计数、禁用GPT-6守卫。
- code/configs/company-general-wrist-v1.json、company-general-wrist-layout1.json、wrist-tasks/*.json：运行配置。
- LOGS/2026-W40.md、LOGS/2026-W40-activity.md、Discussion.md、TIMELINE.md、idea.md§6：实验和决策记录。
- LOGS/wrist-campaign-results.json、LOGS/wrist-campaign-results.md：汇总。

## 收敛与下一步

本轮按20次总尝试停止。保留general_pickup两个布局的可行性证据；不启动大量方向准确率统计或小时监视。其他任务应先分别解决抓取、柔性形变、按压反馈与时序观测预算，再做新一轮有界验证；本轮未修改正式研究目标或method.md§2/§3。

协议检查出现CIRCLE-1（同一主题3轮尚无用户正式decision）。已明确报告；本轮收敛方案是按20次预算停止、封存general_pickup有限可行性证据、其余任务按具体瓶颈单独立项验证，不能自行关闭Discussion或把未完成任务写成已完成。

# 有界按压：分开视觉误差、动作到位与按钮激活
```json
{"id":"bounded-press","status":"active","tasks":["press_by_number"],"stages":["select","press_approach","press_contact","press_stroke","press_verify","press_retract"],"rules":{"contact_endstop":true,"stroke_ticks":4,"occluded_fixture_map":true,"bounded_press_cycle":true,"press_depth_m":0.018,"tracking_tolerance_m":0.002,"retract_height_m":0.030},"evidence":["code/runs/memory-task-press_by_number-dev03","LOGS/memory-task-development-results.md"]}
```
历史按钮位置是定位参考，不是当前测量，不能用它验证是否被压下。视觉不确定性限制探测范围，不等于末端到位容差。本经验允许对初始可见固定按钮进行最多18mm法向探测；由Jev给方向，检测末端停止响应后撤回30mm，再执行下一次尝试。
每次循环只计按压尝试；不假定激活成功，不改变原生成功判据。数字次数从当前图像读取，不存布局答案。适用固定面板；对移动物体不适用。参数为开发候选，尚未证明通用。

第1次新增回合中，接近剩5mm但Jev选择保持；不应把按压精细容差套用到远离表面的接近/撤回阶段。仅press_stroke使用2mm跟踪容差；若本体测得法向已推进到计划探测深度的一半，可结束本次尝试并撤回，但仍不宣称按钮激活。

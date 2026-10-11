# 刚性物体拾取—抬升结构（经验，不是通用定理）
```json
{"id":"pick_lift","status":"active","stages":["select","approach","contact","close","lift","verify_grasp"],"kinds":["pick_lift"],"evidence":["LOGS/wrist-campaign-results.md","code/runs/pickup-improve-retry-3/structured_result.json"],"parameters":{"anchor_offset_m":0.004,"approach_clearance_m":0.055,"retry_depth_m":0.008,"retry_count":1}}
```
结构：语言目标消歧→新观测绑定抓取参考→接近→接触→闭合→抬升→检查物体是否随动。没有存放布局坐标、目标答案或隐藏几何。
初始视觉参考可避免局部表面中心漂移，但只适用于接触前近似静止的刚性物体；运动、明显位移或变形时必须重新绑定，不能沿用旧坐标。
4mm高度修正、55mm接近余量、一次8mm更深重抓是有限开发经验，明确隔离在本文件，不声称跨任务有效。Jev仍必须产生所有非零平移方向；文档不能直接生成平移。

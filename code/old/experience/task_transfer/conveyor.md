# 传送带：首物体记忆、再现与时序预算
```json
{"id":"temporal-match","status":"active","tasks":["match_and_pick_from_conveyor"],"stages":["select","conveyor_wait_first","conveyor_wait_departure","conveyor_wait_repeat","approach","contact","close","lift","verify_grasp"],"rules":{"appearance_match":true,"wait_ticks":10},"evidence":["code/runs/wrist-match_and_pick_from_conveyor-attempt04","LOGS/wrist-campaign-results.md"]}
```
首物体出现、离开、再次出现是三件事。通用object标签不足以提供唯一语义，需要颜色和可见尺寸联合核验；低分匹配宁可不抓。检测失败不等于物体已离开。保证整个原生时间预算内有新鲜视觉刷新，不能刷新耗尽后无观测地等待。

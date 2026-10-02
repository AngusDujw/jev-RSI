# 传送带：首物体记忆、再现与时序预算
```json
{"id": "temporal-match", "status": "active", "tasks": ["match_and_pick_from_conveyor"], "stages": ["select", "conveyor_wait_first", "conveyor_wait_departure", "conveyor_wait_repeat", "approach", "contact", "close", "lift", "verify_grasp"], "rules": {"appearance_match": true, "wait_ticks": 10, "orient_before_approach": true, "approach_clearance_m": 0.085, "contact_anchor_ttl": 5, "grasp_depth_adjust_m": 0.0}, "evidence": ["code/runs/wrist-match_and_pick_from_conveyor-attempt04", "LOGS/wrist-campaign-results.md"]}
```
首物体出现、离开、再次出现是三件事。通用object标签不足以提供唯一语义，需要颜色和可见尺寸联合核验；低分匹配宁可不抓。检测失败不等于物体已离开。保证整个原生时间预算内有新鲜视觉刷新，不能刷新耗尽后无观测地等待。

本轮经验候选：先在当前位置完成姿态调整，再向物体上方移动，避免边下降边转动带动物体。接触阶段允许短期历史参考，但明确标记非新观测，抓后必须重新验证。不是成功保证。

开发01错误地把同一物体的短暂检测丢失判为离开/再现。离开事件新增由最近可见速度外推越过观测带面边界的证据，外推明确标为非观测；等待期间在初始安全高度预置姿态，重复物进入当前机械臂附近才抓，避免边界外追赶。

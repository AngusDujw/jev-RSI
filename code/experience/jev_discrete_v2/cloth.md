# 衣物：可变形表面和关键点参考
```json
{"id": "cloth-reference", "status": "active", "tasks": ["fold_clothes"], "stages": ["select", "approach", "contact", "close", "lift", "verify_grasp", "transport", "lower", "release", "retreat", "verify_release"], "rules": {"cloth_keypoint_anchor": true, "orient_before_approach": true, "approach_clearance_m": 0.085, "contact_anchor_ttl": 5, "grasp_depth_adjust_m": 0.0, "close_ticks": 8, "lift_clearance_m": 0.12}, "evidence": ["code/runs/wrist-fold_clothes-attempt04", "LOGS/wrist-campaign-results.md"]}
```
整个衣物轮廓随遮挡变化不等于深度失准。折叠关键点应保持同一参考，不把每帧旋转矩形重新编号后的角点当原点。必须使用当前可见表面核对，旧位置只作为明确标记的参考，不作为当前观测；丢失时不得根据真值补点。

开发01的左臂目标超出本侧可达区，不能靠更多同向动作解决。选折叠边时同时检查两臂抓取点与放置点的本侧可达性；用当前机器人位置定义分界，不记录绝对布局坐标。

本轮经验候选：先在当前位置完成姿态调整，再向物体上方移动，避免边下降边转动带动物体。接触阶段允许短期历史参考，但明确标记非新观测，抓后必须重新验证。不是成功保证。

开发03发现最高点的横向位置在同一物体表面变化，被错误计入几何形变和测量噪声。改为分别记录形状变化与测量质量；保留中心位移/高度/组件一致性门。该修复两组共享，不是凭经验放宽成功条件。

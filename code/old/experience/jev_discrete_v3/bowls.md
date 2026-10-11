# 碗沿：边缘定位和抓后验证
```json
{"id": "rim-grasp", "status": "active", "tasks": ["stack_bowls"], "stages": ["select", "approach", "contact", "close", "lift", "verify_grasp", "transport", "lower", "release", "retreat", "verify_release"], "rules": {"rim_circle": true, "rim_insertion_m": 0.008, "orient_before_approach": true, "approach_clearance_m": 0.085, "contact_anchor_ttl": 5, "grasp_depth_adjust_m": 0.0, "close_ticks": 8, "lift_clearance_m": 0.12}, "evidence": ["code/runs/wrist-stack_bowls-attempt04", "LOGS/wrist-campaign-results.md"]}
```
可见碗内表面top不是稳定碗沿点。优先从RGB-D可见边界拟合碗沿，再根据当前机械臂方向选择边缘接触点。夹爪闭合后必须检查碗是否随动，不把空抬视为成功。记忆保存策略而非任何布局的坐标。

本轮经验候选：先在当前位置完成姿态调整，再向物体上方移动，避免边下降边转动带动物体。接触阶段允许短期历史参考，但明确标记非新观测，抓后必须重新验证。不是成功保证。

开发03发现最高点的横向位置在同一物体表面变化，被错误计入几何形变和测量噪声。改为分别记录形状变化与测量质量；保留中心位移/高度/组件一致性门。该修复两组共享，不是凭经验放宽成功条件。

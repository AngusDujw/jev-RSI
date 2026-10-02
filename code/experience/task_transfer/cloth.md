# 衣物：可变形表面和关键点参考
```json
{"id":"cloth-reference","status":"active","tasks":["fold_clothes"],"stages":["select","approach","contact","close","lift","verify_grasp","transport","lower","release","retreat","verify_release"],"rules":{"cloth_keypoint_anchor":true},"evidence":["code/runs/wrist-fold_clothes-attempt04","LOGS/wrist-campaign-results.md"]}
```
整个衣物轮廓随遮挡变化不等于深度失准。折叠关键点应保持同一参考，不把每帧旋转矩形重新编号后的角点当原点。必须使用当前可见表面核对，旧位置只作为明确标记的参考，不作为当前观测；丢失时不得根据真值补点。

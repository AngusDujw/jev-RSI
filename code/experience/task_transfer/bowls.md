# 碗沿：边缘定位和抓后验证
```json
{"id":"rim-grasp","status":"active","tasks":["stack_bowls"],"stages":["select","approach","contact","close","lift","verify_grasp","transport","lower","release","retreat","verify_release"],"rules":{"rim_circle":true,"rim_insertion_m":0.008},"evidence":["code/runs/wrist-stack_bowls-attempt04","LOGS/wrist-campaign-results.md"]}
```
可见碗内表面top不是稳定碗沿点。优先从RGB-D可见边界拟合碗沿，再根据当前机械臂方向选择边缘接触点。夹爪闭合后必须检查碗是否随动，不把空抬视为成功。记忆保存策略而非任何布局的坐标。

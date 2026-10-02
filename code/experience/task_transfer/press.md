# 按钮：读卡、触底和复位
```json
{"id":"press-feedback","status":"active","tasks":["press_by_number"],"stages":["select","press_approach","press_contact","press_stroke","press_verify","press_retract"],"rules":{"contact_endstop":true,"stroke_ticks":4,"occluded_fixture_map":true},"evidence":["code/runs/wrist-press_by_number-attempt04","LOGS/wrist-campaign-results.md"]}
```
卡片计数是当前任务读取的指令，保存它不会将历史布局答案带入新场景。重复按压要撤回至按钮上方，不能持续向下压而把调用次数当按压次数。
请求向下移动但实际法向位移连续很小，可能接触机械止挡；这不是按钮激活的证明。允许结束本次有界按压并撤回，最终成功仍以原生判据为准。不应为消除不可达误差无限追加动作。

固定按钮在同一回合的测量可作为被遮挡时的定位参考，但必须标记为历史坐标。此规则假设固定面板、不适用可移动目标；返回参考并不宣称按钮当前可见或已经激活。

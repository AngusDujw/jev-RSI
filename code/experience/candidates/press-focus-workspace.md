# 候选教训：当前距离近，不等于该机械臂能到达
```json
{"id":"press-workspace-candidate","status":"candidate","tasks":["press_by_number"],"stages":["select","press_approach"],"rules":{"workspace_side_selection":true},"evidence":["code/runs/press-focus-dev05"]}
```
第5回合完成10次红按钮程序尝试后，蓝按钮被选给距离更近的左臂。左臂剩约19mm X/12mm Y/11mm Z误差，连续收到方向命令但实际位置不动，最终阶段预算耗尽。这是选择机械臂时缺少可达性约束的证据，不是已证明Jev反向。
候选：按本回合初始双臂位置定义本侧工作区，偏离中线超过4cm时优先同侧机械臂；中线区域再按距离选择。该启发式不是完整IK可达性认证，正式方案应进一步使用机器人FK/关节限位检查。
仅完成代码准备及离线选择检查，不进入本轮active经验，不计为机器人成功；5次新增开发预算已用完，未进行第6回合。

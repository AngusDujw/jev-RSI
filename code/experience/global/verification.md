# 失败事实与验证
```json
{"id":"verification","status":"active","stages":["contact","close","lift","verify_grasp"],"kinds":["pick_lift"],"evidence":["LOGS/wrist-campaign-results.md"],"parameters":{}}
```
夹爪移动或闭合不代表抓住物体。必须比较物体与末端位移，禁止把控制器退出当成功。不确定、失去观测或缺少证据时应保持或停止。原生任务结果仅用于回合结束评估，不作在线方向输入。

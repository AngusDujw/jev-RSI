# 按钮固定表面参考
```json
{"id":"press-visible-reference","status":"active","tasks":["press_by_number"],"stages":["select","press_approach","press_contact","press_stroke","press_verify","press_retract"],"rules":{"occluded_fixture_map":true,"approach_clearance_m":0.055},"evidence":["LOGS/press-focus-results.md"]}
```
按钮面在本回合初始RGB-D建立静态参考，夹爪遮挡后明确标为历史参考。可用此参考生成有界机器人航点，但不能据此推断按钮当前位移或真实激活。开合和阶段是否切换由Jev决定。动作次数只记尝试；实际激活不可从次数推出。

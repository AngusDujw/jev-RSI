# RoboDojo 30试次优化进展

开发混版本；英文校验、程序阶段推进与独立native成功分别记录。启动/接口错误计入试次；native=None表示未取得任务评估，不能计算为物理控制失败率。未启动的资源或CUDA预检单列，不计试次。

|本轮|任务|累计序号|输入|native成功|步数|Jev请求|终止原因|
|---:|---|---:|---|---|---:|---:|---|
|1|general_pickup|24|compact_evidence|None|0|0|failed_without_native_result:Isaac startup exited with -15; see simulator.log|
|2|general_pickup|25|compact_evidence|None|0|0|failed_without_native_result:timed out|
|3|general_pickup|26|compact_evidence|True|75|51|native_episode_ended|
|4|stack_bowls|18|compact_evidence|False|0|1|controller_stop:controller error: ConnectError: [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1016)|
|5|general_pickup|27|compact_evidence|False|0|3|controller_stop:controller error: ConnectError: [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1016)|
|6|general_pickup|28|compact_evidence|None|0|0|failed_without_native_result:'NoneType' object has no attribute 'settimeout'|
|7|general_pickup|29|compact_evidence|None|0|0|startup_preflight_passed|
|8|general_pickup|30|compact_evidence|True|81|55|native_episode_ended|
|9|general_pickup|31|compact_evidence|False|200|133|native_episode_ended|
|10|general_pickup|32|compact_evidence|True|91|63|native_episode_ended|
|11|general_pickup|33|compact_evidence|False|12|6|controller_stop:external unavailable-observation budget exhausted (6 observations)|
|12|general_pickup|34|compact_evidence|False|23|18|controller_stop:controller error: ConnectError: curl exit 92: curl: (92) HTTP/2 stream 0 was not closed cleanly: PROTOCOL_ERROR (err 1)
|
|13|general_pickup|37|compact_evidence|True|75|51|native_episode_ended|
|14|general_pickup|38|compact_evidence|False|127|82|controller_stop:external unavailable-observation budget exhausted (6 observations)|
|15|stack_bowls|19|compact_evidence|False|122|81|controller_stop:external phase observation budget exhausted (40 decisions)|
|16|stack_bowls|20|compact_evidence|False|146|97|controller_stop:external phase observation budget exhausted (48 decisions)|
|17|fold_clothes|16|compact_evidence|False|32|21|controller_stop:external unavailable-observation budget exhausted (6 observations)|

|任务|完成试次|开发混版本成功|冻结验证成功/次数|
|---|---:|---:|---:|
|fold_clothes|1|0|0/0|
|general_pickup|13|4|1/3|
|stack_bowls|3|0|0/0|

本轮已预留 17/30 试次。非ASCII请求 0。

请求边界审计漏项 0；辅助禁止字段命中 0；方向/夹爪/阶段所有权违反 0。字段扫描仅辅助，不替代来源审阅。

每回合原始目录及阶段请求数量见JSON；全部request/response、RGB-D、动作、版本与原生结果保留。

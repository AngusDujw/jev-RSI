# RoboDojo 30试次优化进展

开发混版本；英文校验、程序阶段推进与独立native成功分别记录。接口错误计入试次。

|本轮|任务|累计序号|输入|native成功|步数|Jev请求|终止原因|
|---:|---|---:|---|---|---:|---:|---|
|1|general_pickup|18|english_full|True|117|78|native_episode_ended|
|2|stack_bowls|12|english_full|False|300|183|controller_stop:external phase observation budget exhausted (40 decisions)|
|3|fold_clothes|10|english_full|False|310|181|controller_stop:external phase observation budget exhausted (40 decisions)|
|4|press_by_number|10|english_full|False|246|154|controller_stop:controller error: RuntimeError: jev HTTP 520: non-JSON error body|
|5|match_and_pick_from_conveyor|10|english_full|False|628|232|controller_stop:external phase observation budget exhausted (40 decisions)|
|6|general_pickup|19|compact_evidence|True|120|80|native_episode_ended|
|7|stack_bowls|13|compact_evidence|False|354|219|controller_stop:external phase observation budget exhausted (40 decisions)|
|8|fold_clothes|11|compact_evidence|False|296|175|controller_stop:external phase observation budget exhausted (40 decisions)|
|9|press_by_number|11|compact_evidence|False|581|354|controller_stop:external phase observation budget exhausted (40 decisions)|
|10|match_and_pick_from_conveyor|11|compact_evidence|False|700|79|native_episode_ended|
|11|general_pickup|20|compact_evidence|True|117|79|native_episode_ended|
|12|match_and_pick_from_conveyor|12|compact_evidence|False|528|151|controller_stop:external motion safety veto: command would cross observed support surface|
|13|stack_bowls|14|compact_evidence|False|236|156|controller_stop:external phase observation budget exhausted (40 decisions)|
|14|fold_clothes|12|compact_evidence|False|255|168|controller_stop:external phase observation budget exhausted (40 decisions)|
|15|press_by_number|12|compact_evidence|False|584|356|controller_stop:external phase observation budget exhausted (40 decisions)|
|16|stack_bowls|15|compact_evidence|False|229|150|controller_stop:external unavailable-observation budget exhausted (6 observations)|
|17|fold_clothes|13|compact_evidence|False|251|151|controller_stop:external phase observation budget exhausted (40 decisions)|
|18|match_and_pick_from_conveyor|13|compact_evidence|True|517|127|native_episode_ended|
|19|general_pickup|21|compact_evidence|False|200|132|native_episode_ended|
|20|press_by_number|13|compact_evidence|False|572|348|controller_stop:external phase observation budget exhausted (40 decisions)|
|21|match_and_pick_from_conveyor|14|compact_evidence|False|596|203|controller_stop:external phase observation budget exhausted (40 decisions)|
|22|stack_bowls|16|compact_evidence|False|221|146|controller_stop:external unavailable-observation budget exhausted (6 observations)|
|23|fold_clothes|14|compact_evidence|False|182|119|controller_stop:external unavailable-observation budget exhausted (6 observations)|
|24|general_pickup|22|compact_evidence|False|12|6|controller_stop:external unavailable-observation budget exhausted (6 observations)|
|25|press_by_number|14|compact_evidence|False|170|98|controller_stop:external phase observation budget exhausted (40 decisions)|
|26|stack_bowls|17|compact_evidence|False|218|144|controller_stop:external unavailable-observation budget exhausted (6 observations)|
|27|fold_clothes|15|compact_evidence|False|288|189|controller_stop:external phase observation budget exhausted (40 decisions)|
|28|general_pickup|23|compact_evidence|True|91|61|native_episode_ended|
|29|match_and_pick_from_conveyor|15|compact_evidence|False|700|139|native_episode_ended|
|30|press_by_number|15|compact_evidence|False|598|378|controller_stop:Jev declared task complete; native evaluator remains independent|

|任务|完成试次|开发混版本成功|冻结验证成功/次数|
|---|---:|---:|---:|
|fold_clothes|6|0|0/0|
|general_pickup|6|4|1/2|
|match_and_pick_from_conveyor|6|1|0/2|
|press_by_number|6|0|0/0|
|stack_bowls|6|0|0/0|

本轮已预留 30/30 试次。非ASCII请求 0。

请求边界审计漏项 0；辅助禁止字段命中 0；方向/夹爪/阶段所有权违反 0。字段扫描仅辅助，不替代来源审阅。

每回合原始目录及阶段请求数量见JSON；全部request/response、RGB-D、动作、版本与原生结果保留。

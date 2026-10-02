# Jev夹爪/阶段联合决策开发记录

开发混版本，不能作为最终冻结成功率。GPU/接口失败也计入每任务50次预算。

|任务|尝试|输入/处理|布局|原生成功|步数|Jev请求/响应|终止原因|
|---|---:|---|---:|---|---:|---:|---|
|fold_clothes|1|{'input_variant': 'numeric', 'processing_variant': 'anchored'}|0|False|500|100/100|native_episode_ended|
|general_pickup|1|{'input_variant': 'numeric', 'processing_variant': 'anchored'}|0|None|0|0/0|[{'type': 'RuntimeError', 'error': 'Configured GPU is occupied; no process preemption allowed'}]|
|general_pickup|2|{'input_variant': 'numeric', 'processing_variant': 'anchored'}|0|False|200|40/40|native_episode_ended|
|match_and_pick_from_conveyor|1|{'input_variant': 'numeric', 'processing_variant': 'anchored'}|0|False|184|93/93|controller_stop:Jev abort from observed evidence|
|press_by_number|1|{'input_variant': 'numeric', 'processing_variant': 'anchored'}|0|False|700|140/140|native_episode_ended|
|stack_bowls|1|{'input_variant': 'numeric', 'processing_variant': 'anchored'}|0|None|0|0/0|[{'type': 'RuntimeError', 'error': 'Configured GPU is occupied; no process preemption allowed'}]|
|stack_bowls|2|{'input_variant': 'numeric', 'processing_variant': 'anchored'}|0|False|800|160/160|native_episode_ended|
|fold_clothes|2|{'input_variant': 'evidence', 'processing_variant': 'anchored'}|0|False|340|68/68|controller_stop:external phase observation budget exhausted (40 decisions)|
|general_pickup|3|{'input_variant': 'evidence', 'processing_variant': 'anchored'}|0|None|0|0/0|[{'type': 'RuntimeError', 'error': 'Configured GPU is occupied; no process preemption allowed'}]|
|general_pickup|4|{'input_variant': 'evidence', 'processing_variant': 'anchored'}|0|False|200|40/40|native_episode_ended|
|match_and_pick_from_conveyor|2|{'input_variant': 'evidence', 'processing_variant': 'anchored'}|0|False|80|40/40|controller_stop:external phase observation budget exhausted (40 decisions)|
|press_by_number|2|{'input_variant': 'evidence', 'processing_variant': 'anchored'}|0|False|200|40/40|controller_stop:external phase observation budget exhausted (40 decisions)|
|stack_bowls|3|{'input_variant': 'evidence', 'processing_variant': 'anchored'}|0|False|390|78/78|controller_stop:external phase observation budget exhausted (40 decisions)|

# RoboICL 历史动作幅度审计（2026-10-23）

服务器 company-server-2-ykj 上项目 `/home/ykj/project/jev-rsi-roboicl`、代码、环境解释器软链接及四阶段结果目录均仍存在。这里只读分析，不启动模型或仿真，也未验证环境能否完整启动。

## 来源核验补充

用户提出可能存在个人同名项目后，重新核验：论文 https://arxiv.org/abs/2609.34261 的Code链接直接指向 https://github.com/Mosi-AI/RoboICL 。本地干净上游检出 `.cache/roboicl-upstream-20261021` 的origin是该官方仓库，HEAD为07d6e1c5387710e2de9240724b0015bbf0c95c6e，官方GitHub可查该提交。当前baseline不是独立官方仓库，而是jev-RSI中的vendored复现扩展副本。

逐文件比较官方检出的96个普通文件，当前baseline中89个字节一致、7个有修改、0个缺失。README、dialogue_policy.py、astra_policy.py、shared_harness.json和叠方块/分拣任务配置均与官方固定提交一致。服务器当前840e7ed提交中的dialogue_policy.py、astra_policy.py、shared_harness.json也与干净官方检出的SHA256逐一一致。

因此前述增量定义和步长提示词确实来自论文官方发布代码。新增的Jev复用门控、Pro转发和四条件五任务实验属于本项目复现扩展；125次尝试的结果不能称为论文作者的原始实验，也不代表整套论文协议已复现。未据此认定用户另一个同名项目的身份。

## 口径

- 按既有 first-native-panel.json 选取每条件/任务/布局的首个原生结果，共79回合；不挑最佳回合。不含46次无原生评分的物理尝试。
- 统计 accepted decisions 中每臂平移/旋转增量的L2范数；有效输出与被拒绝的输出分开。
- 全部79回合的真实harness.json均为平移上限0.03m、旋转上限0.15rad。
- 达上限定义为 norm/limit >= 0.9999；接近上限定义为 >=0.90。
- 纯GPT组的已执行前缀通过tool_results的执行区间/步数与decisions逐条配对；19回合共5208个双臂控制步。叠碗layout1另有1个原生步没有已提交回执，明确排除，未推断它的增量。
- “移动中位数/P90”排除该臂对应通道的零动作，避免静止手臂稀释统计。下面的位移是模型发出的请求增量，不是实测末端位移。

## 结果

全部79回合共61220个已接受的双臂预测行，即122440个单臂样本。平移和旋转达到上限、达到90%上限的数量均为0。最大预测平移为22.472mm（上限74.91%），最大预测旋转为0.116185rad（上限77.46%）。其中包含未执行的20步预测尾段，不能当作实际执行量。

纯GPT19回合已提交执行回执覆盖5208个双臂控制步、10416个单臂样本，平移非零5588个、旋转非零2708个：

| 通道 | 非零中位数 | 非零P90 | 最大请求增量 | 上限 | >=90%上限 |
|---|---:|---:|---:|---:|---:|
| 平移 | 8.00mm | 13.34mm | 21.47mm | 30mm | 0 |
| 旋转 | 0.048rad | 0.070rad | 0.116185rad | 0.15rad | 0 |

| 纯GPT任务 | 执行回执控制步 | 非零平移中位数 | 最大平移 |
|---|---:|---:|---:|
| general_pickup | 305 | 6.18mm | 14.59mm |
| fold_clothes | 1052 | 9.43mm | 20.88mm |
| press_by_number | 677 | 8.00mm | 20.50mm |
| match_and_pick_from_conveyor | 1657 | 7.21mm | 17.32mm |
| stack_bowls | 1517 | 7.87mm | 21.47mm |

另查到79回合里50次输出张量拒绝：4次夹爪数值非法，45次日志首先报出旋转1rad超限，1次首先报出平移1m超限。校验在首个错误处停止，不能据此断言张量其他位置均合法；这些被拒绝请求未作为有效动作计入。记录的异常大数不代表有效策略在频繁使用30mm上限。

## 改成一步及调整上限的入口

- 纯GPT零样本直接支持 `--action-horizon 1`，同时把预测与执行长度设为1。若继承的环境变量仍指定20/5，它们会再次覆盖CLI值，必须同步清除或改成1。见 baseline/roboicl/roboicl/run.py:302–309。
- `fixed_predict_horizon=true` 时将要求恰好1行，而非仅执行20行预测中的首行。
- 不能用 reproduction/experiment.py 原封不动启动一步实验，它硬编码预测20、纯GPT执行5。
- Jev复用模式在reuse_policy.py:64要求20步预测/5+5执行，不能只改长度后继续称原5+5对照。
- 上限字段为 `max_translation_m` / `max_rotation_rad`；任务覆盖晚于profile，分拣classify_objects的0.034m覆盖需要单独核对。改字段会同时改变模型提示词及数值校验，不是把输出动作乘倍率。
- 当前数据未显示有效请求被30mm上限卡住。提高上限不保证模型会加大动作；一步输入反馈节奏与20步预测不同，旧统计不能代替一步实测。

## 可复现证据

- 脚本：code/scripts/analyze_roboicl_action_scale.py（标准库；远端只读）。
- 完整统计与每回合限幅/执行覆盖审计：code/runs/2026-10-21-roboicl-pro-evaluation/action-scale-audit-20261023.json。
- 来源：code/runs/2026-10-21-roboicl-pro-evaluation/first-native-panel.json，以及服务器各回合harness.json、decisions.jsonl、tool_results.jsonl和action_rejections.jsonl。

## 回合总控制步数上限（另一个指标）

用户随后询问最大步数，按原生episode控制步预算另行核对，与上文单步位移/旋转幅度分开。任务源码的step_lim依次为：general_pickup=200、fold_clothes=500、press_by_number=700、match_and_pick_from_conveyor=700、stack_bowls=800。EvalEnv.is_episode_end在take_action_cnt >= step_lim时进行终局检查。

79个首原生评分回合里9个达到回合上限（11.39%），9个均未成功。纯GPT为3/19，Jev为0/20，固定平均为3/20，固定最大为3/20；固定最大指两次GPT规划之间执行10步，不是把整个回合上限改成10步。未达到上限不等于成功，部分失败会提前结束。46次无原生评分的尝试未纳入本统计。

| 条件 | 任务 | 布局 | 原生步数/上限 |
|---|---|---:|---:|
| pure | fold_clothes | 3 | 500/500 |
| pure | match_and_pick_from_conveyor | 2 | 700/700 |
| pure | stack_bowls | 1 | 800/800 |
| maximum | fold_clothes | 0 | 500/500 |
| maximum | press_by_number | 0 | 700/700 |
| maximum | stack_bowls | 1 | 800/800 |
| mean | fold_clothes | 0 | 500/500 |
| mean | fold_clothes | 1 | 500/500 |
| mean | stack_bowls | 2 | 800/800 |

逐回合来源与统计保存于code/runs/2026-10-21-roboicl-pro-evaluation/episode-step-limit-audit-20261023.json。此统计是历史日志复核，不改变任何运行预算，也未新增实验。

# 🧾 Activity · 2026-W44（使用者 & Agent 流水 · 只增不改）

> 由 `python3 tools/log_activity.py` 追加（AGENTS.md § 5.3）；Claude Code 的
> `UserPromptSubmit` hook 会自动记下每条用户输入。人工操作也可照格式补记。
>
> 格式：`- 【User|Agent】【YYYY-MM-DD HH:MM】[类型] 内容 ↪ 关联ID`

- 【Agent】【2026-10-26 12:55】[intent] 用户继续唯一v29同版巡检，跨周先完成W43回顾，禁止重跑旧回合与API/子代理。
- 【Agent】【2026-10-26 12:55】[op] 完成W43全部43EXP分组及decision/stop回顾，Discussion追加Weekly Retro与5条CIRCLE-1收敛方案，MODE last_retro更新W44，未改正式idea/method或议题状态。
- 【Agent】【2026-10-26 12:57】[result] v29全6已终止：3有效完整失败/3无效中断/成功0/3；r1原生490无效原字节SHA已存，旧native均退出GPU46MiB。保存全批终局/3+16真实提交及代表首释放原图audit；不重跑旧样本。
- 【Agent】【2026-10-26 12:57】[op] 新建实验块 EXP-2026W44-001：继续同版独立单次；v29释放旁落证据后冻结唯一v30支撑诊断提示  ↪ `EXP-2026W44-001`
- 【Agent】【2026-10-26 12:57】[op] 冻结唯一v30英文提示和六单次manifest，针对v29原图旁落及跨抓取漂移复用；16附件/runtime/原550评分不变，未启动，所有当前动作actor选。
- 【Agent】【2026-10-26 12:58】[op] v30提示英文3304词/SHAfae065a21de99a93ba7d08044535ffeb488013239fe359be5f6160621fb7a77c，10原测试与严格协议lint通过，六新本地名不存在；准备提交SSH推送后单次启动。
- 【Agent】【2026-10-26 13:00】[run] v30 r1单次前台启动session35689，隔离源码rsync仍推进（620KiB至1.2MiB），未到attempt-started/ready/actor；r2–r6未启动。启动前native全退/端口空闲/free48463MiB，真实launch Pro Luna/high/fallbackfalse/evaluator反馈false/550。监控已切v30，保持单条准备不重跑。
- 【Agent】【2026-10-26 16:29】[intent] 用户@提前规划好的decision robodojo v4090，授权查找Astra完成任务的原图历史、参考其历史利用方式，选关键图/英文总结作为Luna high额外经验输入；不改已启动冻结回合。
- 【Agent】【2026-10-26 16:29】[op] 通过run-bound Chats向指定会话发送已有Astra终局/关键原图/历史输入方式查找请求，已接受尚未读，未重复发送；独立核查本地旧baseline发现原Astra high回合失败、另有Sol成功，不能将Sol冒称Astra。
- 【Agent】【2026-10-26 16:31】[note] Astra示范查找当前等待指定会话读取/答复；经验选择拟采用关键动作前后原图+简短英文可见关系，不把完整成功标签/评分或动作坐标输入actor。当前v30 r1准备进程未观察到且无attempt-started/仿真/actor，不重启；后续核验来源再形成单一下一版。
- 【Agent】【2026-10-26 16:39】[result] 已直接SSH核验Astra Pro/high旧布局成功403步/81决策、上限2200，原终局/结果/动作history SHA与对端一致，原媒体实际0文件；完整结果配置存outer-audit，不输入actor。参考对端真实历史机制：持续上下文；后续LIBERO例图实际SHA校验/base64输入和历史结束边界，不能冒充RoboDojo图。创建英文文本经验与manifest候选，历史判断标不确定、无真值/当前目标；尚未注入任何冻结版本。
- 【Agent】【2026-10-26 16:39】[op] 将Astra已核验无图结论和278词英文经验SHA接入既有巡检后续要求：下一单一冻结提示精确拼入并审计真实提交，当前只准备候选，不改活版；不再等待不存在的原图。
- 【Agent】【2026-10-26 16:43】[intent] 用户明确授权本机Pro ordinary Astra high做一次当前任务，完整保留历史，选关键原图/英文总结供Luna经验；只一次不自动重跑。
- 【Agent】【2026-10-26 16:43】[op] runner新增显式policy-model仅允许Luna/Astra high，默认Luna不变；模型仅改新本地副本settings/身份context/Pro配置与manifest，prepared模型一致校验，原entry/550/评分不改。
- 【Agent】【2026-10-26 16:43】[op] 新建实验块 EXP-2026W44-002：Astra high独立单次保存当前layout0真实历史，提取Luna经验  ↪ `EXP-2026W44-002`
- 【Agent】【2026-10-26 16:44】[op] Astra单次目录prepare-only验收：实际settings/隔离Pro配置均gpt-6-astra/high，auth仅bool验收/fallbackfalse/评价不输入/历史图0/550，上游Luna settings未改，prepared-policy-audit保存；尚未启动仿真或模型，10原测试通过。
- 【Agent】【2026-10-26 16:46】[run] 27335d3d SSH推送后Astra唯一单次前台session55744实际启动，native ready原550，worker实测gpt-6-astra/high/gpt_only；三RGB首观测待工具调用，媒体保留审计已落。旧Luna无运行，现监督只跟踪Astra并提取真实图像经验，不重试。
# Pro 完整方法交付：自动恢复验证（2026-10-28）

本轮修复并验证的是完整方案的生成、恢复和交付链路。原失败输入在主动断开本地原生 RPC 后，自动恢复同一 Codex 线程，最终交付通过静态校验的完整四字段方法。没有执行 Jev 或机器人，不能把本轮算作 LIBERO 任务成功。

## 原因与修复

此前捕获的是响应流中途截断 / IncompleteRead，不只是本地等待时间设置太短。旧桥接在没有收到完整 response.completed 时，把该次请求判为失败；重试重发原输入，未恢复原生会话。上下文可恢复不代表断开的那次推理能够无条件逐 token 续传。

现在使用本机 ChatGPT 登录的 Codex app-server（0.164.0），固定 gpt-6-astra / xhigh。外层 POST 提交幂等任务，GET 轮询；HTTP 断开不会取消生成任务。相同请求 ID 重挂同一任务，桥接重启后也可重新附上原输入并恢复同一线程。Codex 先处理自身的流重连；终止性传输失败再触发有界同线程继续。最多三轮、两次 RPC 重连，排队、重试和继续共享原总时限。

仅完整动态工具参数通过英文、JSON 字段及源码静态校验后，才交付给现有主机。丢失最终确认但已有完整有效回执时，恢复该回执，不重新生成源码。输出明确标记为原生工具回执的兼容封装，不伪装成原始 Responses 响应。

本机使用 bwrap 子进程挂载命名空间隔离全局规则、技能、插件和配置，原文件保持原状，账号仍使用原生登录。没有使用 Platform / caz key。原生线程正常持久化会话历史，包括观测；本项目的请求账本继续将图片替换为哈希。固定机器人知识和任务提示词文件没有改动。

## 实测结果

| 项目 | 结果 |
|---|---|
| 输入 | 原任务1335/init12/seed0已存观测；无机器人启动 |
| 原请求规范哈希 | b8c819c18e8e8a788a8a1566fb8f73ccec3528a043942a004dc36548004a23ee |
| 故障注入 | 首轮开始45秒后终止本测试自己的原生 RPC 进程 |
| 恢复 | 自动 thread/resume，同一线程 ID；一轮初始、一轮继续 |
| 新增传输错误 | 注入故障之后未观察到 |
| 完整交付 | 1/1；1702.824秒，约28分23秒 |
| 方法 | 247行；source SHA256 381dda9c7a573c4432c466d572ed503cc0ac347c6dc59fa6330c4514b5274ff8 |
| 验收 | 四字段、英文、AST、真实动态工具回执来源、响应一致性通过 |
| 请求去重 | 一个逻辑任务、一条最终账本回执 |
| Jev / 物理执行 | 0 / 0；LIBERO评分未测 |
| 最终离线检查 | 10项通过 |

报告的线程累计用量为254603输入、39710输出，其中252288输入标记为缓存，29157输出标记为推理。故障前未完成段的用量仍未知，不能计零。原生内部 HTTP 重试次数也未知，线程汇总不能记作一次上游 HTTP 尝试。本次包含模型自行进行的四次内存源码构造/检查、一份最终工具提交及后续收尾；这些工作解释了部分额外时间，但本轮没有延迟分解对照，不能据此精确分摊耗时。

这证明本例故障后能够自动完成交付；不证明长期稳定成功率、物理任务成功或省 token / 加速。新的原生 harness 会加入自己的英文工具框架，与历史原始 HTTP 条件分开记录。长测试在最后的兼容性与边界加固前启动；最终生产版本另通过小型真实 Pro 请求及全部离线检查，版本与哈希见 manifest。

## 检查范围与保留的负结果

十项离线检查覆盖：桥接重启重挂、完整返回与缓存回执、账号/模型/额外规则/非法返回拒绝、HTTP 提交响应与轮询同时丢失后只生成一次、原生重试不重复开轮、终止性流错误同线程继续、RPC 断开恢复、完整回执恢复、回执来源篡改拒绝、半截源码拒绝。

最初 HTTP 故障夹具等待过短，任务在 GET 断开注入前完成，导致“两个故障均已注入”的断言失败。延长夹具执行时间后通过；这条失败记录也保留在 offline-checks.json。初次原生探针发现自动注入中文技能说明，隔离后重新核查实际请求通过；这次不合格探针未作为最终英文条件正例。另一个关闭 code-mode host 的探针无法提交工具，三轮未成功，报告用量33575/176；因此最终保留原生工具 host，通过只读配置、输入隔离和最终回执验收运行。四份探针记录均保留在 manifest 中，未以零成本删除失败。

自建检查脚本已按要求删除，保留哈希和结果；原始工作产物位于项目 code/runs/2026-10-28-pro-session-recovery。未改代理、账号全局配置、显卡或驱动。

## 证据

- [完整四字段方法](method.json)：本次 GPT 实际返回，尚未执行。
- [交付结果](result.json)、[原请求（图片哈希）](request.json)、[兼容响应](response.json)。
- [原生线程回执](native-session.json)、[桥接账本回执](receipt.json)、[故障注入](injected-fault.json)。
- [输入隔离、探针与版本清单](manifest.json)、[离线检查记录](offline-checks.json)。

## 修改 / 新增文件

- baseline/roboicl/reproduction/pro_session_client.py（新增原生会话适配器）
- baseline/roboicl/reproduction/pro_session_jobs.py（新增幂等异步任务）
- baseline/roboicl/reproduction/pro_oauth_bridge.py
- code/scripts/run_gpt_jev_program.py
- code/scripts/audit_gpt_jev_run.py
- code/prompts/README.md
- .agents/skills/gpt-jev-method/SKILL.md
- LOGS/2026-W44.md、LOGS/2026-W44-activity.md
- Discussion.md、TIMELINE.md
- artifacts/gpt-jev-pro-session-recovery-20261028/：README.md、method.json、result.json、request.json、response.json、native-session.json、receipt.json、injected-fault.json、manifest.json、offline-checks.json、cleanup.json。

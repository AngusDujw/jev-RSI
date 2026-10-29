# 无时间截止诊断：生成慢、传输失败与执行停止

2026-10-29。用户要求取消时间限制，确认长等待是否全部来自GPT推理，以及生成方法后为何提前结束。

**结论：有三类不同问题。** 方法输出前确实有长处理；HTTP/TLS中断会让同一输入重新生成；原样执行的物理任务本次已经成功，而程序在最终两帧验证的参考初始化上存在协议矛盾，导致自报未完成。上轮SIGTERM发送方仍未查明，空载对照未复现固定40分钟终止。

## 实验条件

保留10月27日成功版固定提示词、经验、API及模型：历史基线 `a8e6ea72`，本机ChatGPT Pro `gpt-6-astra/xhigh`、官方Jev `jev-1.13.0/systemone`。诊断分支 `8b4bfdd6` 只增加取消截止和观测代码，没有修改机器人策略或固定模型提示词，没有Platform/caz key调用。

- 生成诊断：本地精确重放上次新183的失败首请求及校验哈希的两幅图，无SSH、仿真或Jev。最多三次传输尝试。
- 执行诊断：原样复用上次已生成但被中断的205行源 `d4727784…`，1335/init12/seed0/GPU4，空memory重新观察，0源码修补。这不是一次新的冷生成成功；原获取738.913秒和历史失败费用另保留。
- GPT请求、socket读取及整回合没有应用时间截止；用户systemd服务 `RuntimeMaxSec=infinity`。Jev自身网络尝试超时及24GPT/200Jev/600策略步的次数上限保留。旧API时间字段用固定 `1e12` 兼容占位，不对应实际计时截止；这是执行审查输入中的已声明差异。
- 双端服务脱离临时工具会话。信号、模型调用、SSE事件类型/数量/时间、参数字符及最终用量落盘；不记录隐藏推理文本，不执行半截参数。

预声明及哈希见 [manifest.json](manifest.json)，无模型/机器人进程对照见 [probe-addendum.json](probe-addendum.json)。

## 1. 生成诊断：去掉本地截止仍然断流

| 尝试 | 耗时 | 首方法参数 | 收到参数字符 | 结束原因 |
|---|---:|---:|---:|---|
| 1 | 900.868秒 | 853.042秒 | 4689 | HTTP chunk `IncompleteRead`，无completed |
| 2 | 338.805秒 | 无 | 0 | HTTP chunk `IncompleteRead`，无completed |
| 3 | 3.581秒 | 无 | 0 | TLS `UNEXPECTED_EOF_WHILE_READING` |

总计1303.256秒（21.72分钟），含15+45=60秒退避，0完整方法，3次用量均未知。第一尝试首SSE2.100秒、首reasoning条目43.929秒、22个reasoning条目结束；第二有7个reasoning条目结束。第一尝试参数输出窗口约47.826秒，之后连接不完整结束。

因此旧1798秒应用截止不是中断的必要原因。900秒附近中断可复现，但另一次339秒中断及TLS握手失败说明不能只推断成固定服务器寿命；具体服务/网关/代理/网络关闭层尚未定位。重复请求重新发送相同payload，不能认定是接续同一未完成推理。

“首参数前等待”包括服务排队、预处理、推理与网络；流式事件和推理token数量不能给出纯GPU计算秒数。事件分类参照[官方Responses流式事件定义](https://developers.openai.com/api/reference/resources/responses/streaming-events)；本项目实际使用ChatGPT后台复现链路，不能把Platform API的行为保证直接移植过来。

证据：[逐尝试汇总](generation-attempts.json)、[错误与重试回执](generation-result.json)、[首尝试事件](generation-attempt1-events.jsonl)、[自然退出生命周期](generation-lifecycle.jsonl)。

## 2. 执行诊断：物理成功，程序验证提前停止

**原生LIBERO=true；程序proposal=false，termination=method_incomplete，phase=verify。** 19次GPT审查、92次真实Jev、276策略步、174RPC，3997.658秒（66.63分钟），源代码完全未改。

手实际抬升38.880毫米，程序独立观测包裹抬升38.897毫米，附着误差1.234毫米；随后执行搬运、释放和撤手。这些是程序的测量证据，正式成功取终局隔离LIBERO评分。

最后一份GPT审查整体状态为 `complete`，参数为 `relation=inside_supported`、`released=yes`、`correspondence=unknown`。它明确解释：没有提供前一参考点定义，因此对应关系未知。

生成源码的[第190行](method-used.py#L190)初始化 `definition=None`，第一次调用便把它作为previous_definition；[第196行](method-used.py#L196)却在两次采样中都无条件要求 `correspondence=certain`，而保存首次定义的代码在第197行，永远来不及执行到。这是首帧建立参考与次帧匹配要求不一致，在本次正确的unknown回答下导致程序退出；不是夹爪或Jev没有完成目标，也不是时间/次数耗尽。

修复方向应是通用的时序验证契约：首帧建立可观测参考，次帧才检查对应和稳定性，并对不可观测证据设计有界替代路径。本轮为了保留因果证据，没有手改该任务源码，也没有把unknown强行改成certain。

证据：[终局](execution-summary.json)、[完整审计](execution-audit.json)、[原样四字段方法](method-used.json)、[原样205行源码](method-used.py)、[最终审查](final-review.json)、[验证契约诊断](verification-contract-diagnosis.json)。19份strict审查、源码来源、92次原始选择/动作/夹爪/确认步数均通过机械审计；审计不重判图像事实。

## 3. 执行时间到底花在哪里

| 统计范围 | 秒 | 分钟 | 含义 |
|---|---:|---:|---|
| 主机端19次GPT等待 | 3741.181 | 62.35 | 包含完整往返、桥接、服务、解析与落盘 |
| 其中桥端GPT链路 | 3637.491 | 60.62 | 并非纯推理时间 |
| 其中首参数前合计 | 3065.026 | 51.08 | 服务排队/处理/推理/网络混合 |
| 参数开始至尝试完成 | 563.464 | 9.39 | 并非纯网络传输时间 |
| 主机端92次Jev等待 | 230.396 | 3.84 | 含重试及往返 |
| 其中桥端Jev链路 | 203.024 | 3.38 | 中位单次0.680秒 |
| 主机剩余墙钟 | 26.081 | 0.43 | 仿真、图像、几何、RPC等未归入post计时部分 |
| 整回合 | 3997.658 | 66.63 | 复用执行时间，不含原方案获取 |

GPT19个尝试全部完整完成、0重试、216299输入/68868输出token，其中50814推理token。大量推理token与输出前等待确实存在，但不能换算成精确纯计算时长。Jev92逻辑请求共94上游尝试，已知192397输入/22908输出，另2未知失败用量；一次请求用105.731秒，包含两次网络失败、60秒退避及成功重试。所有92次逻辑请求最终成功返回。

主机端减桥端约131.062秒，是额外往返、序列化、解析和I/O等混合开销，不能全部叫网络时间。没有测得精确“多少百分比由网络造成”。见 [总计](timing-totals.json)、[逐GPT请求时间](execution-request-timings.json)、[主机调用日志](host-model-timing.jsonl)、[Jev恢复记录](jev-recovered-failures.json)。

## 4. SIGTERM结论与进程隔离

用户systemd生命周期测试中，启动工具退出后子服务继续存活；主动stop时记录到了发送PID/UID。正式host自然exit0，运行3997.658秒期间未收到信号；桥和转发直到终局之后才被主动停止，转发重启0次。

另外按旧plain-exec方式启动空载Python对照，无模型/网络/机器人。它运行2484.388秒（41.41分钟），越过原2398.539秒中断位置仍没有SIGTERM；之后由本次Agent主动终止，发送PID640221被日志记录。故没有复现固定40分钟机制，上轮究竟谁发信号仍无法追溯，不能宣称已确定原因。

证据：[空载结果](tool-lifetime-control.json)、[空载生命周期](tool-lifetime-lifecycle.jsonl)、[host生命周期](host-lifecycle.jsonl)、[桥生命周期](bridge-lifecycle.jsonl)。桥日志末尾SIGTERM是本轮终局后的主动清理，不能混入运行故障。

## 保存、检查及修改范围

已停止本次自有桥接、转发及空载对照；远端host退出、双端7921无监听。验证假凭据已删除，没有创建独立测试脚本；九项离线边界检查通过。见 [检查](offline-checks.json)、[清理](cleanup.json)，实验为 [EXP033–034](../../LOGS/2026-W44.md#exp-2026w44-033)。本轮不增加替代任务，不将同源复用计为冷生成泛化，也未证明净省token或提速。

原始公开请求/响应和元数据保留在 `code/runs/2026-10-29-gpt-jev-unlimited/`；隐藏模拟状态未提供给模型。代码在已推送分支 `codex/gpt-jev-timing-unlimited-20261029`，提交 `8b4bfdd6`：

- [host的无时限与逐调用计时](../../.worktrees/gpt-jev-timing-unlimited-20261029/code/scripts/run_gpt_jev_program.py)。
- [SSE、重放、桥接和信号诊断工具](../../.worktrees/gpt-jev-timing-unlimited-20261029/baseline/roboicl/reproduction/pro_timing_diagnostic.py)。

其余修改/新增为本结果目录、LOGS、Discussion、TIMELINE及两份引用笔记；固定模型提示词、Jev动作层、正式研究目标和理论均未修改。

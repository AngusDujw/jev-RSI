# RoboDojo 初始化与连接修复（2026-10-05）

本轮授权是修复并调查原因；保持原30次总预算、每任务50次上限及失败记录。初始化预检也计试次；GPT6运行时仍禁用，Jev负责原定决策。

## 原因与证据

1. **仿真资源读取阻塞。** 拾取28/layout4的reset600秒超时；日志在570秒附近报告Aluminum_Cast在线纹理无法解析，伴随反复zenity无显示警告。此前拾取27也要约594秒才能完成reset。下载同一NVIDIA公开资源的curl成功，表明资源可获得。仅传入代理和增加reset期限不足以恢复Kit的资源读取。
2. **独立的Jev TLS连接问题。** 相同凭证、payload和7901–7903代理，HTTPX全部报SSL UNEXPECTED_EOF_WHILE_READING，curl全部HTTP200、实际jev-1.13.0。失败发生在TLS层，未收到模型响应；这支持传输实现/代理路径问题，不能据此断言具体TLS指纹、密码套件或代理规则，也不是GPT6 Pro账户失败。原始对照见`code/runs/2026-10-05-socks-transport-dependency/{jev-network,curl-network}.json`。
3. **已修正的错误掩盖。** RPC失败会关闭并清空socket；原finally恢复期限时二次AttributeError遮盖了原TimeoutError。此前b2c1df9已加None守卫，原始失败保留。

## 修复

- `code/scripts/nvidia_material_cache.py`缓存Aluminum_Cast、Aluminum_Anodized和Plastic_ABS及相对纹理依赖，共9文件/15892492字节，保留官方原始字节；路径/依赖/SHA256验证，不编辑USD或物理参数。缓存位于远程项目同挂载盘的`code/runs/cache/nvidia-materials-2023_1/`。
- `rgbd_bridge.py`在Kit初始化后安装原生`omni.client.set_alias`并通过真实原生客户端读回全部文件验证；reset增加60秒栈诊断及耗时日志。
- `robodojo_position.py`把镜像限制在当前仿真进程；未缓存HTTP资源超时10秒、重试1次，保留TLS校验。启动-only检查RGB-D后正常结束，不执行控制动作。
- 5个measured任务配置指向同一镜像。控制器v13、布局SHA、观测权限、阶段/方向/夹爪所有权不变。
- 先前curl/SOCKS的Jev后端继续发送已保存的完全相同请求；每次传输尝试独立记账，无隐式策略重采样。

NVIDIA官方支持运行时URL别名及HTTP超时/重试配置：[Client Library](https://docs.omniverse.nvidia.com/kit/docs/client_library/latest/index.html)。官方默认HTTP重试8次；这里的主要证据仍是实际日志与同布局修复对照。

## 验证与边界

- 本地5项检查通过：完整缓存、原生别名调用、损坏文件、路径逃逸、缺纹理；测试数据已删除。AST/JSON通过。
- **拾取29/layout4，第7/30：初始化预检通过。** Kit原生客户端9/9文件SHA一致，启动12.002秒，reset14.474秒，总29.837秒。三路640×480 RGB-D各307200/307200有效深度，RGB图人工检查有效；0Jev、0GPT6、0策略动作，仿真退出0。未取得任务成功评价，不计作任务成功。
- 裸导入omni.client的独立探针缺少完整Kit初始化，分别出现缺libcarb与段错误；不是有效资源读取对照，未作为上述结论依据。实际Kit进程内验证已通过。
- 当前结论强支持在线材质读取是本次reset阻塞主因；不把一次初始化通过当作多布局稳定成功。

## GPT6通道

本机`codex login status`为ChatGPT登录；默认配置已设`gpt-6-sol`、`xhigh`及`forced_login_method=chatgpt`，后续Codex进程使用该默认。当前已运行会话不能靠修改默认配置即时换模。此次RoboDojo运行时GPT6调用为0，未启动任何GPT6 API请求。历史API脚本/旧实验配置不是Pro接入证明，不据此声称整个仓库的历史调用已改写。

OpenAI官方区分ChatGPT订阅登录与API key登录，并支持限制登录方式：[Authentication](https://developers.openai.com/codex/auth)、[Configuration Reference](https://developers.openai.com/codex/config-reference)。


### 联合修复的真实控制验证

拾取30/layout4第8/30成功：reset32.435秒，总267.119秒；原生success=true、81步、29动作，55/55 Jev响应全部HTTP200，32本地视觉、0DeepSeek、0GPT6；非ASCII/审计漏项/禁字段/所有权违规均0。进程正常退出，未换v13策略。与拾取29预检一起验证本次修复；两次验证保留原失败，本轮剩22次，冻结新布局验证尚未运行。见[EXP027](2026-W41.md#exp-2026w41-027)。

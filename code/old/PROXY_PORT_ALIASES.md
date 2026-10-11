# company-server-2的7897代理别名端口

已开启仅限服务器本机的7901、7902、7903，均通过项目内TCP进程转到127.0.0.1:7897。原Mihomo服务和已有7898 SSH隧道保持运行。HTTP CONNECT与SOCKS5h共6个并发探测均返回HTTP200；测试进程正常停止后端口全部释放，正式进程重启后的环境变量用法也验证通过。

这些是同一个代理的多个入口，使用同一线路与带宽。不同程序本来也可以共用7897；新端口便于给每个任务单独配置。当前正式转发进程PID3910099，运行于本次受控前台SSH会话，需要保持该进程运行，不是开机自动启动服务。

## 给服务器进程使用

HTTP代理可任选一行填入应用的代理设置，三行是三个备选地址，不是执行命令：

```text
http://127.0.0.1:7901
http://127.0.0.1:7902
http://127.0.0.1:7903
```

支持SOCKS的程序可对应使用，socks5h让域名由代理解析：

```text
socks5h://127.0.0.1:7901
socks5h://127.0.0.1:7902
socks5h://127.0.0.1:7903
```

对于读取代理环境变量的程序，以下三条按行执行，用7901作为示例。程序若设置trust_env=False，应使用程序自己的proxy_url参数；不能假定它会读这些变量。

```bash
export HTTP_PROXY=http://127.0.0.1:7901
export HTTPS_PROXY=http://127.0.0.1:7901
export ALL_PROXY=socks5h://127.0.0.1:7901
```

本次已验证的前台启动命令如下，两条命令按行执行。当前已在运行，无需重复启动；新建进程时先停止自己的旧别名进程并更换state-file目录，已有状态文件不会覆盖。脚本只占用新端口，任一端口绑定失败会释放此前已绑定的自有端口。

```bash
cd /root/yekangjie/project/jev_rsi
python3 -B code/scripts/loopback_port_alias.py --ports 7901 7902 7903 --target-port 7897 --state-file code/runs/2026-10-05-proxy-aliases-active/status.json
```

前台Ctrl+C或对该转发进程发送SIGTERM可正常停止。验证记录在code/runs/2026-10-05-proxy-aliases-7901-7903及code/runs/2026-10-05-proxy-aliases-active；实验记录为LOGS/2026-W41.md的EXP-2026W41-004，本次没有模型调用或物理回合。

## 2026-10-05真实API及LIBERO启动预检

用户授权用这些端口恢复测试后，三端口分别通过example.com HTTP200、Jev认证/systemone POST200及视觉API/models HTTP200，均返回jev-1.13.0，模型列表含gpt-6-astra。视觉没有生成请求，此结果只证明该接口可达及返回所需模型。三个端口仍共用原7897上游，不是三个独立线路。

原realman_jev API使用trust_env=False，但支持构造配置proxy字段。因此新增libero_proxy_transport.py，只在原API类构造时给jev/semantic_vision指定代理，不改变任何策略输入输出或冻结源码。真实包装初始化预检验证了Jev使用7901、视觉使用7902；另7903可作备用。4次Jev网络请求共1500输入/152输出token，均单列，不计任务结果；没有DeepSeek调用。

以下两条按行执行的命令已在服务器用完整20个init实际验证。它是preflight-only模式，不执行机器人；输出目录已存在，重新验证须更换output，不能覆盖旧记录。

```bash
cd /root/yekangjie/project/jev_rsi
/root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python -B code/scripts/run_libero_frozen_validation.py --frozen-from code/runs/2026-10-03-libero-recovery30-focused-v1/frozen --output code/runs/2026-10-04-libero-verify20-cheese-restored-preflight --campaign 2026-10-04-libero-verify20-cheese-restored --inits 15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34 --jev-proxy http://127.0.0.1:7901 --vision-proxy http://127.0.0.1:7902 --preflight-only
```

网络通过，但仿真和grounding两个既有环境均cuInit=999，cuDeviceGetCount=3，入口退出2并保存not-started.json，未预留任何任务试次。原总账40行、奶酪27/50，前后文件SHA相同。原8个冻结策略源码SHA全部验证并保留，包装和外部API源码SHA另存manifest，不混称新策略。

CUDA可用后，正式启动应去掉preflight-only并使用新的output目录；入口仍会先检查网络和CUDA，再预留试次，沿用50/task上限。当前没有完成20次验证或其它四任务的新物理实验。证据为[EXP-2026W41-006](../LOGS/2026-W41.md#exp-2026w41-006)及code/runs/2026-10-05-libero-proxy-api-preflight、2026-10-04-libero-verify20-cheese-restored-preflight。

## 2026-10-05 11:14状态复核

服务器已重新启动：8卡CUDA实际计算/同步通过，LIBERO768×768 RGB-D EGL通过，见[EXP-2026W41-008](../LOGS/2026-W41.md#exp-2026w41-008)。当前7897/7898/7901/7902/7903均无监听，先前PID及ready状态文件属于重启前历史，不能当作当前在线证据。继续实验前需要恢复上游和别名进程，再验证API。本次只检查GPU，没有重新创建代理或启动任务回合。

## 2026-10-05恢复运行时的连接

用户允许全部端口不可用时转发本机7897。重新检查服务器7901–7903无监听；远端7897随后出现其它sshd监听，未停止它。本轮改为7901/7902/7903分别直接SSH反向转到本机7897，sshd PID54037，前景SSH会话跟踪。三端口example.com、真实Jev POST与视觉/models均通过；但完整运行中仍有间歇断连/TLS EOF，不能用短探针成功保证长回合稳定。

仅在7901–7903都空闲时可重建本轮转发。以下已实际测试的一行命令保持前台运行；当前在运行，无需重复启动，不是永久或开机服务。

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -R 127.0.0.1:7901:127.0.0.1:7897 -R 127.0.0.1:7902:127.0.0.1:7897 -R 127.0.0.1:7903:127.0.0.1:7897 -- 'company-server-2'
```

奶酪完成一次真实全流程成功后，因9次链路中断及AGENTS§10升级已停止物理队列；首错守卫修复7daf5f2，详情见[恢复报告](../LOGS/2026-10-05-libero-resumed.md)。此处三个入口仍共用本机7897线路，不提供三份独立带宽或模型额度。

## 2026-10-05 GPT-6 Sol/xhigh 实验端口更新

上文为历史 Jev/API 端口记录。用户已要求后续实验全部改用 ChatGPT 登录的 GPT-6 Sol/xhigh。现有前台 SSH 隧道把服务器 7901、7902 转给本机 7897 代理；**服务器 7903 当前转给本机 7903 的 Codex 桥接服务，不再是 HTTP/SOCKS 代理**。本机桥接只监听 127.0.0.1，服务器的同号端口也只监听 127.0.0.1。Jev 和旧视觉 API 不用于新批；7901/7902 保留给资产等普通网络访问。

当前实际运行的隧道命令如下。单行命令保持前台运行；端口已占用时不要重复执行或停止无关进程。

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -R 127.0.0.1:7901:127.0.0.1:7897 -R 127.0.0.1:7902:127.0.0.1:7897 -R 127.0.0.1:7903:127.0.0.1:7903 -- 'company-server-2'
```

服务器对 `http://127.0.0.1:7903/health` 的实测返回 `ok=true, model=gpt-6-sol, reasoning_effort=xhigh, auth=ChatGPT`。这只验证登录和桥接；正式入口还会在预留物理试次前做一次真实模型选择题。模型曾有一次明确的容量拒绝，新桥接仅在此种失败时最多重试原请求三次，不换模型；每次 CLI 事件都保存在本机 `code/runs/pro-runtime/bridge/`。

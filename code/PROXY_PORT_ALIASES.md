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

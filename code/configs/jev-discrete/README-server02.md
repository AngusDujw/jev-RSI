# server02 RoboDojo 配置

本组 `*-server02.json` 配置使用 `/home/user/ykj/project/RoboLaya` 已有的 RoboDojo、Isaac Sim 5.1 Docker 镜像、项目 `.conda` 环境与布局文件，项目部署在 `/home/user/ykj/project/gpt6/jev-RSI`。仿真子进程通过 `code/scripts/server02_isaac_python.sh` 挂载两个项目；控制器父进程使用 RoboLaya 的 `.conda/bin/python`。五个任务均固定为 layout 0，布局 SHA-256 见 `../robodojo/server02-top5-layout0.json`。运行时的决策和语义视觉使用本机已登录 ChatGPT 的 GPT-6 Sol/xhigh 桥接；不需要在服务器上安装模型权重或配置 OpenAI API key。

本机启动桥接服务（保持进程运行）：

```bash
cd /home/ykj/project/gpt6/CVPR/jev-rsi/jev-RSI
python3 -B code/scripts/codex_pro_bridge_server.py --work-root code/runs/pro-bridge-server02 --port 7903 --max-inflight 2
```

本机另开终端，建立到 server02 的反向端口转发（保持连接）：

```bash
ssh -N -R 7903:127.0.0.1:7903 server02
```

在 server02 上运行单任务；`--auto-gpu` 会在两张卡中选空闲卡：

```bash
cd /home/user/ykj/project/gpt6/jev-RSI
/home/user/ykj/project/RoboLaya/.conda/bin/python -B code/scripts/run_discrete_batch.py --tasks general_pickup --variant server02 --processing precision --layout 0 --auto-gpu --model-backend codex_pro --batch-views
```

其余任务名为 `stack_bowls`、`fold_clothes`、`press_by_number`、`match_and_pick_from_conveyor`。磁盘剩余空间不足 8 GiB 或显卡忙时，批处理入口拒绝启动。完整任务会占用原定任务试验次数；仅做 Isaac Sim / RGB-D 启动检查时可直接给 `run_position_pilot.py` 传入带 `startup_only: true` 的配置，输出到 `code/runs/` 下独立目录。

# RoboDojo 实验证据台

只读网站，按任务列出所有已落盘回合，默认各选一个控制回合；没有控制记录的任务明确标记仅预检。

逐步显示原始三RGB、实际 input_text、实际保存的 questions、模型原始/解码输出、规划阶段与运行阶段、完整执行目标、实测跟踪、录像与原生终局。老日志缺失 questions 不从当前源码重建。complete 不当作 success。

使用 Python 标准库，不安装环境依赖。资产仍只读自 v4090 DataStorage；不能访问 secrets 或任务资产目录之外的路径。支持 MP4 Range 请求。

启动命令独立一行，无需换行：

```bash
python3 code/robodojo_decisions/review_site/server.py --root /home/v4090-1/DataStorage/gpt6-dec --bind 127.0.0.1 --port 18942
```

持久服务由 user systemd 管理；本机 SSH 转发通过独立 user systemd 服务运行，日志落在指定 DataStorage 下。网页“刷新”重新扫描实际落盘数据。网站不启动实验、不调用模型，不读取密钥。

新版本回合还显示推进器实际收到的当前RGB局部裁图。完整经验原文快照、阶段原文检索片段与未精简几何快照提供单独链接；实际模型输入仍以保存的input_text为准，未精简快照不假称已经送入模型。

# 一次决策的真实输入对照

网页入口（同一Tailscale网络）：

```text
http://100.81.6.59:18944/
```

固定LIBERO-Plus Goal1144、init5、decision0000、approach。同一任务一次决策，
展示原Jev纯文本，以及Luna保留误差加RGB、删除XYZ加标记图、删除XYZ加原图三组实际请求。
默认原Jev在左、标记图在右，手机小屏上下排列。可切换条件与五个问题，放大图像、
看措辞差异、真实回答/概率、字段删改、完整输入文本及下载原始provider请求。

原Jev记录来自既有libero-ten-workflows归档，非新生成输入；下载JSON按原值重新排版。
三组provider请求/回答按原始字节复制，六个实际图像块校验SHA256、四个唯一PNG。
起始XYZ误差与机器人位置逐项一致，比较不是跨初态拼接。首轮回答均实际收到，
旧消融后续部分有SSL中断，页面不将其冒充正常模型任务失败，也不作成功率推断。
中文说明只用于阅读，没有作为历史模型输入。最新未运行运动草案不在真实请求中。

## 文件与复现

- 本目录：HTML/CSS/JS阅读界面模板，无外部依赖。
- `code/decision_multimodal/build_libero_input_comparison.py`：只读导出和构建器。
- `code/runs/2026-10-17-libero-input-comparison-evidence/`：真实输入证据，小资产约数MB。
- `code/runs/2026-10-17-libero-input-site/dist/`：本机实际服务目录，4.9MiB。
- 同目录上层：浏览器QA摘要、桌面及手机截图；不纳入项目源码Git。

在company-server-2项目worktree中导出既有记录（下面是一行命令，不需换行；输出目录必须尚不存在）：

```bash
python3 -B code/decision_multimodal/build_libero_input_comparison.py --collect --output code/runs/2026-10-17-libero-input-comparison-evidence
```

把证据目录通过SSH复制到本机项目worktree后构建（下面是一行命令，不需换行；输出目录必须尚不存在）：

```bash
python3 -B code/decision_multimodal/build_libero_input_comparison.py --evidence code/runs/2026-10-17-libero-input-comparison-evidence --output code/runs/2026-10-17-libero-input-site/dist
```

预览服务只绑定本机Tailscale地址，不修改旧网站。服务以受工具跟踪的前台进程运行。
若该端口已有本页服务，直接访问，不重复启动。否则在本机worktree运行下面一行：

```bash
python3 -m http.server 18944 --bind 100.81.6.59 --directory code/runs/2026-10-17-libero-input-site/dist
```

Sites注册保持私有、未发布；其源推送仅支持HTTPS，与项目要求SSH推送冲突，
所以最终交付使用现有Tailscale网络服务。项目代码已通过Git SSH保存。
不安装环境、不写/tmp、不触碰GPU/驱动；本轮0模型调用、0仿真步。

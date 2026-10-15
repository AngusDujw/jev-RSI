# 十任务处理与 Jev 输入输出档案

入口：[index.html](index.html)。包含十个成功回合全部 1054 组原始请求/回答，及逐决策匹配的 `branches.jsonl` 执行记录。按任务、阶段或决策切换；原始 JSON 可下载，处理证据可展开。

中文计划是依据最终实施方案整理，不是 GPT 原始计划的逐字摘录。源回合固定 commit、输入/输出 SHA256、任务先验和单次成功/五未见初态证据分别标明。Goal1202 尚未稳定，不能用该成功回合宣称稳定成功率。

页面、数据与四十张原始观测图无 CDN 或外部依赖，可直接打开本地 HTML。视频和原始文件链接依赖本机 `code/runs/` 已有实验材料；它们不在普通 Git 内，单独 clone 代码后仍可阅读页面内置的计划、1054 组决策和几何证据，但不能自动获得视频与完整 raw 目录。

如需用浏览器 HTTP 访问，在项目根目录执行下面一行（无需换行）：

```bash
python3 -m http.server 8768 --bind 127.0.0.1 --directory code
```

访问 [本机网页](http://127.0.0.1:8768/reports/libero-ten-workflows/)。仅监听本机；本次已启动并完成浏览器检查。

根据本机已有原始材料重新构建数据和观测图，在项目根目录执行下面一行：

```bash
python3 -B code/scripts/build_libero_ten_workflows.py
```

生成器仅使用 Python 标准库；不运行仿真、不调用模型、不改原始回合。保留已有双任务档案及其生成器。

验证：十任务加载、阶段选择、原始回答一致性、实际执行切换、视频元数据、桌面与390像素手机布局通过；1054/1054决策匹配实际执行。截图在 `code/runs/2026-10-15-libero-ten-success-videos/web-{desktop,mobile}.png`。

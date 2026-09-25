# tools/ · 协议辅助脚本

零依赖，纯 Python 3.9+。

| 脚本 | 作用 | 用法 |
|---|---|---|
| `session_check.py` | **会话开始自检（唯一实现）+ 共享底座**：未初始化 → 输出 bootstrap 指引；已初始化 → 输出 mode / active 议题 / 当周日志 / **最近 3 条流水** / **主线最新节点与绕圈告警** / **人话版是否过期** / 是否欠 Weekly Retro。其余脚本从这里 import `REPO / LOGS_DIR / now_cn / read`（时间戳统一 UTC+8） | `python tools/session_check.py`（`--hook` 输出 Claude Code hook 的 JSON 信封） |
| `new_week.py` | 新建当周 `LOGS/YYYY-Www.md`（已存在则跳过） | `python tools/new_week.py` 或 `python tools/new_week.py 2026-W11` |
| `new_exp.py` | 往当周 LOGS 追加一个 EXP 骨架（自动算 NNN / commit hash / 主机名 / 当前 active 议题号），并自动记一条流水 | `python tools/new_exp.py "源意图一句话"` |
| `log_activity.py` | **使用者 & Agent 流水（§ 5.3）**：往 `LOGS/YYYY-Www-activity.md` 追加一行（自动署名 + 时间戳）。`--hook` 供 Claude Code `UserPromptSubmit` 静默记录用户原话；`PROTOCOL_NO_PROMPT_LOG=1` 可关掉原话记录 | `python3 tools/log_activity.py "改了什么" [--actor User] [--type decision] [--ref EXP-...]` / `--tail 10` |
| `timeline.py` | **研发主线（§ 12）**：`add` 追加节点并重画图、`render` 重画 mermaid 图、`check` 机械绕圈检测（CIRCLE-1/2/3）、`list` 列节点 | `python3 tools/timeline.py add --kind decision --topic lr-schedule "一句话"` / `check [--strict]` |
| `eli5_sync.py` | **人话版同步戳（§ 4.3）**：给 `idea.md § 1–5` 算内容哈希盖在 § 7 上，正文改了而人话版没跟上就机械报过期 | `python3 tools/eli5_sync.py [--check\|--stamp]` |
| `new_disc.py` | 开启/关闭 Discussion 议题：自动分配 `DISC-YYYYWww-NNN`（扫描 Archive 取 max+1，避免撞号）；close 时校验 Resolution → 归档为 `Archive/DISC-YYYYWww-NNN-<slug>.md` → 从模板重置。开/关都会自动落时间线节点（question / decision）与流水 | `python tools/new_disc.py open "<标题>" [--owner "PI @张三"] [--topic lr-schedule]` / `close "<slug>"` / `next` |
| `lint_protocol.py` | **error**（始终阻塞）：坏格式 EXP/DISC/T ID、Resolved 议题缺 Decision；**warning**（仅初始化后）：未填占位符、EXP 块必填字段为空、流水行格式不对、人话版过期、时间线图与节点表不同步、绕圈告警。`--strict` 把 warning 升级为 error | `python tools/lint_protocol.py [--strict] [路径]` |
| `make_variant.py` | **打包初始化文件夹**：把根目录协议复制到 `variants/<name>/` 并复位项目状态（LOGS/Discussion/TIMELINE/MODE 清空），再打成 `variants/<name>.zip`。根目录是唯一来源，生成物不要手改 | `python3 tools/make_variant.py [name] [--no-zip] [--force]` |
| `install_hooks.sh` | 把 git 指向 `.githooks/`，启用 pre-commit 自动 lint（每个新 clone 跑一次即可） | `bash tools/install_hooks.sh` |

`templates/` 存放协议文件的标准模板（当前为 `Discussion.template.md`，议题关闭后由 `new_disc.py` 用其重置根目录 `Discussion.md`）。

## Claude Code hooks（`.claude/settings.json`）

模板自带两个 hook，都只是"触发器"，逻辑仍活在 `tools/` 脚本里：

| Hook | 调用 | 作用 |
|---|---|---|
| `SessionStart` | `session_check.py --hook` | 会话开头把简报（mode / 议题 / 流水 / 主线 / 绕圈 / 人话版 / 周回顾）注入上下文 |
| `UserPromptSubmit` | `log_activity.py --hook` | 把用户每条输入静默记进当周流水（不向 stdout 输出，永远 exit 0） |

首次在新 repo 里打开 Claude Code 时需要批准这两个 hook。其他 Agent（Codex / Cursor）没有 hook 机制，按 `AGENTS.md § 2.1` 手动跑 `session_check.py`，并手动补流水。

## pre-commit 行为

装上后每次 `git commit` 会自动跑 `lint_protocol.py`（默认模式）：
- 只有 warning → 打印提醒，commit 正常进行（允许提交进行中的实验骨架）
- 存在 error → commit 被中止，必须先修复坏 ID / 议题 Decision
- Reflect 后置（`AGENTS.md § 4.2`）要求 Agent 对当周日志跑 `--strict`，warning 也要清零
- 紧急绕过：`git commit --no-verify`（不推荐）

## 设计原则

- **零依赖**：只用标准库，避免污染科研项目自身的环境。
- **不破坏现有文件**：`new_week.py` 已存在则跳过；`new_exp.py` 只追加不重写；`new_disc.py` 归档前先校验。
- **可被 Agent 直接调用**：所有脚本以非零退出码报错，便于 Agent 检测。
- **一份逻辑，多处复用**：会话检查只活在 `session_check.py`，hook 与跨 Agent 约定都指向它；引导文案只活在 `bootstrap.md`；时间线的绕圈判定只活在 `timeline.check()`，会话简报与 lint 都调它。
- **联动脚本失败不阻断主动作**：`new_disc.py` / `new_exp.py` 写时间线或流水失败时只打 `[warn]`，议题与实验块照常落盘。

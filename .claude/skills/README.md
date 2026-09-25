# 内置技能（Vendored Skills）

这些技能随协议模板一起分发（**内置安装**），任何从模板实例化出的研究 repo 都自带，
无需额外安装外部插件。Claude Code 会自动发现 `.claude/skills/` 下的技能。

| 技能 | 来源 | 在本协议中的用途 |
|---|---|---|
| `grill-me` | mattpocock/skills | **Ideation 闸门**：立项内容写入 `idea.md` 前的强制质询入口 |
| `grilling` | mattpocock/skills | `grill-me` 的底层引擎（relentless interview） |
| `eli5-idea` | 本协议自带 | **人话闸门**：立项写入后把 `idea.md § 1–5` 重写成 § 7 人话版并盖同步戳 |

- 上游：https://github.com/mattpocock/skills （MIT License，© 2026 Matt Pocock）
- 固定版本（pinned commit）：`43ea0884b07a3e67a5a07f025ce92aefa983177b`
- `grill-me` 仅是薄封装，正文为「Run a `/grilling` session.」，真正的质询逻辑在 `grilling`。
- 协议如何在立项流程中自动调用它们，见 `AGENTS.md § 4.3`（写之前 grill-me，写之后人话闸门）。
- `eli5-idea` 是本协议自带的（非 vendored）：若环境里另有通用的 `eli5` 技能，它会优先按那套方法写，本文件负责规定"写进哪、验收标准、怎么盖戳"。

> 升级方式：从上游拉取对应 `SKILL.md` 覆盖，并更新本文件的 pinned commit。

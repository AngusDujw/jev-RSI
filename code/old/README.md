# code/ · 主代码

项目主代码目录。

## 建议结构（按需调整）

```
code/
├── src/         核心模块（库代码、模型、损失、数据加载等）
├── scripts/     可执行入口（train.py / eval.py / sweep.sh ...）
├── configs/     配置文件（yaml / json / hydra）
├── tests/       单元测试（建议 80%+ 覆盖率，见 AGENTS.md § 4.2）
└── README.md    本文件（按你项目需要可重写）
```

## 与协议的对接

- **Execute 阶段** 改动这里的代码（见 `AGENTS.md § 4`）。
- **每条 EXP 的 `command` 字段**应当指向 `code/scripts/*` 下的可执行入口，方便复现。
- **实验产物**（`runs/` `outputs/` `checkpoints/` `wandb/` `lightning_logs/`）已在仓库根 `.gitignore` 中忽略，不会污染 git 历史。

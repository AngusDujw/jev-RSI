# Goal1163 可见短抬边界复核（待实跑）

源码冻结点：`cd176c7`（session ten-goal-stable, turn continuation3）。本记录仅比较已存官方init3/4回合并核对入口；没有新增物理回合，也没有证明酒瓶抓持改善。共享Goal1163计数仍为16/50。

| 已存回合 | 第一候选短抬可见升高 | 共运动误差 | 闭爪后指间距 | 真实终局 |
|---|---:|---:|---:|---|
| init3，开发成功 | 15.17 mm | 36.26 mm | 约14.28 mm | 程序/官方均true |
| init4，冻结失败 | 约10.88 mm | 40.29 mm | 近14 mm | 程序/官方均false |
| init4，闭爪30步失败 | 11.31 mm | 39.65 mm | 约14.29 mm | 程序/官方均false |

第一轮下降均因物理阻挡而在目标瓶身中段上方约40 mm使用一次可见指垫重叠闭爪试探。指间距相近，不能凭夹爪位置宣布抓稳。init4闭爪30步仍滑脱，排除单纯闭爪保持时间不足作为充分解释。原始依据分别是`code/runs/2026-10-08-goal-1163-local-init3-visual-finish/episode/holding-0198.json`、`code/runs/2026-10-09-goal-1163-local-init4-frozen-visual-finish/episode/holding-0198.json`、`code/runs/2026-10-09-goal-1163-local-init4-hold30/episode/holding-0210.json`及相应真实Jev请求和执行分支。

新增选项`--lift-recheck-mm 30`只在第一次持有检查升高7–15 mm、误差小于65 mm、可见尺寸比正常时，把状态标为`ambiguous`。Jev仍控制XYZ、旋转、夹爪和阶段，保持闭爪并完成额外30 mm短抬后，以新RGB-D和初始公开可见点云投影重新检查；第二次需要升高超过30 mm且共运动/尺寸约束通过。旧init3第一检查不会触发，旧init4首候选会触发；后者的二次结果未知。默认0沿用旧策略。代码见`code/scripts/libero_jev_recovery.py`、`code/scripts/libero_jev_rollout.py`、`code/scripts/run_libero_goal_jev.py`。

验证：三文件Python编译与`git diff --check`通过；本机及服务器`--dry-run`均生成含`--lift-recheck-mm 30`的Goal1163命令，Goal1458误用该开关被拒绝。服务器GPU相关进程仍处D态，故未预留init5；下一步是GPU健康后在未见init5执行一次冻结回合，审计真实二次RGB-D、Jev边和程序/官方双终局。完整协议块见本地当周周志`EXP-2026W41-168`。

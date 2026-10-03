# RoboDojo 英文输入与联合决策优化（2026-10-04）

- 授权：用户要求继续优化处理算法及Jev输入输出组织，最多30次优化。
- 计数：本轮五任务合计最多30个完整物理试次；启动失败计入，GPU延期单列；沿用每任务累计50次上限。无免费失败重试。
- 观测：公开任务指令、头部/腕部RGB-D、标定、机器人自身反馈与几何。禁止对象真值、隐藏接触/附着、奖励、分割ID和在线native成功判据。GPT-6/DeepSeek闭环调用0。
- Jev职责：XYZ符号、夹爪、阶段推进/复看/重试/终止；外部负责候选几何、姿态、非负幅度、IK与安全限幅。
- 版本：v7从v6隔离复制，旧冻结v3/v6保持不变。经验另建英文副本；完整状态/问题在最终发送前递归ASCII校验。
- 首批：english_full，五任务各1回合layout0；排除中文因素并建立新版本起点。
- 第二候选：compact_evidence，去重复计划/机器人关节细节，补四类证据状态并保持数值/来源/参照；先比较具体失败，再增加几何/恢复候选。
- 成功条件：独立native结果与Jev阶段流程分别记录；Jev宣称完成不等于成功。开发混版本成功率不作为最终成绩，成功候选需固定版本布局验证。
- 资源：company-server-2，项目根/root/yekangjie/project/jev_rsi，既有Isaac5.1环境；每回合≤1200秒、≤2GB，不换驱动/依赖。磁盘不足8GiB延期。
- 原始材料：code/runs/jev-discrete-TASK-NN，包括每请求request/response、RGB-D、命令、阶段边、版本SHA、独立结果；本轮账本code/runs/2026-10-04-robodojo-opt30.jsonl。
- 记录：LOGS/2026-W40.md、LOGS/jev-discrete-results.md与本轮进展文档；所有实质代码批次commit/push ykj。

# Jev Choice接口核查（2026-10-02会话）

一手来源：`https://docs.typesafe.ai/primitives/choice`、`https://docs.typesafe.ai/primitives`、`https://docs.typesafe.ai/api`。

- `instructions`是有效字段，不能把当前失败归因为“该字段未生效”。
- 问题ID只供代码匹配，不进入模型；完整问题要写进instructions。选项名和描述会进入模型。
- 同批问题独立读取相同state，不会读到彼此答案。不能把本轮失败归因于题目相互干扰；实际修改过state/问题的重放也不能证明这种干扰。
- 通常应批量提问。第二次请求只有在需要第一个答案作为新输入或决定新的问题/状态时才有明确意义。本项目v3研究的是先确定阶段动作分支、再给当前动作裁剪输入；需计入额外调用，不能宣称拆请求本身提升模型质量。
- instructions与criteria的描述支持对象/数组。可明确focus字段、适用/不适用条件与例子。v3据此尝试结构化rubric。
- confidence描述输出分布集中程度，不是物理正确率。

本轮所有坐标/到位比较仍来自RGB-D估计与机器人反馈；结构化rubric不读取仿真物体真值。模型仍可判断错误，控制器不伪造其输出。

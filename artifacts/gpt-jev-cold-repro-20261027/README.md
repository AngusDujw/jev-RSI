# 历史冷生成复现：本次成功

- 任务：LIBERO-plus goal1335，奶油奶酪放入碗，init12/seed0；company-server-2-ykj GPU4。
- 以历史成功配置a8e6ea72的一阶段提示词、API及host/helper重新生成；旧方法、旧设计、反馈和回合经验均未输入。新源197行，SHA6ddc1bca…，与历史0c4cdaf3…不同。
- 完整方法生成721.191秒（12分1秒）；整回合2585.398秒（43分5秒）。
- 真实Jev107次、321个策略仿真步、额外10步终局settling；GPT14次=1次源码生成+13次结构化视觉审查。源码修复0次。
- 终局native_success=true，completion_proposed=true。原生评估隔离在终局，不输入策略。
- 审计通过：源码来自实际模型输出；全部实际请求唯一账本匹配；107次原始Jev选择与动作方向、动作幅度、夹爪携带状态及确认步数一致；13次strict视觉返回结构合法。机械审计不重判图像事实。
- 抬升测试：手升33.8216mm、观测物体升33.8224mm，附着误差0.2981mm；释放后测得漂移0.1213mm，程序终局关系inside_resting。以上是程序证据，正式结果取终局LIBERO。
- GPT已知146835输入/55469输出，另1次审查重试用量未知；Jev已知224323输入/26643输出，另1次重试未知。未知费用不计为零。
- 原始成功记录配置max_repairs5但实际0；本次预声明max_repairs0。当前Pro权重并未独立冻结；历史加载的bridge哈希未记录，本次使用匹配commit桥文件254afc95…，不能证明历史加载二进制完全相同。
- 实际初始请求的instructions、tool schema、model/effort、任务语言、相机标定及两幅新渲染图像均与历史一致；状态仅初始化后的剩余墙钟时间不同。
- 本次证明原配置在同任务同初态可再次从零生成成功，不证明跨任务或跨初态冷生成稳定，也未证明省token或加速。较新两阶段配置的既有失败保留，不混为同一实验。
- 自有前台父进程、bridge、SSH隧道、远端case均已退出；双端7921关闭。未动其他进程、环境或驱动。

## 证据

- [原样完整方法](method.py)、[四字段输出](method.json)、[方法及Jev输入输出](METHOD.md)
- [结构化结果](RESULTS.json)、[终局摘要](summary.json)、[请求/动作审计](audit.json)
- [实际初始输入对齐](initial-input-comparison.json)、[原配置及预声明](manifest.json)
- [服务生命周期](lifecycle.json)、[本机清理](cleanup-local.json)、[远端清理](cleanup-remote.json)
- 完整原始请求/响应/动作账本保留于项目code/runs/2026-10-27-gpt-jev-cold-repro/，未将大体积媒体提交git。

# LIBERO：可见抓取候选与Jev输入输出组织优化

本批沿用2026-10-03批次前缀，实际时间以各events.jsonl为准。用户授权新增尝试最多30次；保留原每任务50次总上限。首要任务为libero_object/task1066奶油奶酪入篮。

## 范围与信息边界

策略只读取公开任务语言、双相机RGB-D/标定、机器人自身末端/夹爪反馈以及自身指垫和手指模型。场景物体真实位姿、对象ID、物体资产尺寸、隐藏任务谓词、奖励和官方success不进入模型。官方success只在终局评价读取一次。

新的recovery入口独立于已成功的旧supervisor；各回合冻结全部策略模块及SHA256。初始化10步张爪属于环境准备，不计作Jev决策或正式控制步。

新增回合含setup失败、协议失败及物理失败，都计入30，不自动重试、不替换失败。计数保存在code/runs/libero-recovery30-ledger.jsonl，同时追加原libero-supervisor-ledger.jsonl。每回合900秒/180Jev/550正式原生步/600MiB，每批3GiB。最早几个开发版本native守卫660，但180Jev的实际步数上限540，未超环境horizon600；v6起显式恢复550守卫。

## 算法与决策组织

- 视觉：最多initial、pregrasp、lift_check各1次语义识别；SAM掩膜与RGB-D给出可见几何。腕部仅见部分物体时保留最初完整可见范围，不把局部顶面当完整尺寸。此融合假设物体在抓前未明显移动，仍须关注陈旧位置问题。
- 抓取：从可见范围和支撑面，以及自有指垫/手指包络计算接触高度、预计重叠和桌面间隙；提供三个位置/深度候选。几何预测并非成功标签。
- Jev：选择XYZ方向、需要调整的旋转方向、夹爪开合、候选、阶段advance/retry/stop。候选题只在select询问，排除已失败候选。未请求旋转执行零命令，不冒称为模型输出。
- 阶段：select→approach→align→descend→grasp→test_lift→lift→carry→lower→release→retreat。可用retry进入recover_up→recover_open→select。所有实际阶段边由Jev响应触发，无距离自动推进。
- 输入：每个轴单独提供当前位置、目标、误差与相对关系，配合阶段合同、完成证据、夹爪实际开度/执行时长、最近三次动作及可恢复选项。local/evidence/contract组织候选均保留来源。
- 幅度：远处较大步幅、接触附近较小步幅；严格保留Jev符号，不悄悄反转方向。实际位移重新测量。

## 已有证据（持续追加，最终以campaign.json为准）

1. v1/v2为数组维度setup错误，均0Jev/0正式动作，仍计入上限；提取fit_candidates后以保存的自有机器人几何离线检查0/30/60/90度候选。重放中的名义水平面仅用于数学守卫测试，不当作物理成功。
2. v3输入默认candidate_0，同时又允许keep，Jev返回keep+advance，被接口拒绝。候选输出域改为仅在select给出未失败候选，其他阶段不询问。
3. v4只给误差数组时，Y目标低约119mm却多次选择positive，接近预算退出。该记录明确说明输入组织会影响方向判断。
4. v5逐轴输入取得186/186正确XYZ方向，接近15次完成；下降每次仍正常移动约4.7mm，但统一6mm动作参数与45次阶段预算不匹配，退出时尚差约50mm。v6改为粗到细幅度以匹配预算。

完整逐回合、冻结提交和配置由code/runs/2026-10-03-libero-recovery30-summary/campaign.json保存；EXP映射由同目录exp-ids.json保存。开发init1重复使用，不称独立评测。

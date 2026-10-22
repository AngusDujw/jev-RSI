# 规划器—推进器初始迭代方案与经验形成规范

日期：2026-10-22。用途：用户审阅的完整设计文件；不是模型输入、不是经验库、不是已实现配置。

**当前执行状态：暂停。本文不启动实验、不启用监督 job、不调用模型、不恢复旧 episode。**

## 0. 怎样读这份文件

- **已确定**：此前用户明确拍板，或当前代码和原始记录可以核实的事实。
- **本次建议**：我准备如何设计和测试；没有因为写进本文而变成已实现、已验证或启动授权。
- **后置候选**：保留在路线图中，不与初始条件捆绑启用。
- 中文正文给外层 Agent 和用户阅读；所有可发送给内部模型的模板、JSON 文本、Skill/Lesson 模板均用英文。不能把整份中文文件直接拼入模型请求。
- 本轮只设计新的经验形成机制，没有读取旧 `experience/`，没有创建可用经验条目，没有把历史失败解释升级为已验证知识。
- 本文不改 `idea.md` 的研究目标、`method.md` 的形式化定义和结论，不关闭或重开议题。当前方案是工程迭代设计，不是理论收敛保证。

### 阅读导航

1. §1–3：旧约定、当前证据、系统职责。
2. §4–7：完整输入输出、英文提示、执行语义。
3. §8–10：怎样形成 Skill/Lesson、每轮修改什么、怎样防止越改越散。
4. §11–14：测试顺序、验收标准、运行证据与实现清单。
5. §15–16：历史文件索引、参考项目及审阅事项。

## 1. 既有拍板及本次建议的边界

| 项目 | 初始设计采用的约定 | 状态 / 依据 |
|---|---|---|
| 架构 | 规划器分阶段并设计推进器需要的信息；推进器选择离散动作 | 已确定，`framework_decisions.md`、2026-10-16/17 流水 |
| 规划频率 | 每回合起点只规划一次；可有工具执行和检查，但不在控制中重新规划 | 已确定；重规划另测 |
| 规划账号 | 本机 Pro，不以普通 OpenAI API 替代 | 已确定；2026-10-18曾显式指定Sol6.1 high。初始建议沿用 `gpt-6.1-sol` / `high`，启动前核对用户最新选择和Pro实际可用项；不能把对照组Luna high自动当规划器配置，不可用就报告阻塞、不替换接口 |
| 推进接口 | 真正 `/v1/decisions`，现有实现请求 `gpt-6-luna` | 已确定；实际请求/响应再次核对。不虚构 Decisions 的 high 参数 |
| 凭据 | 仅已授权 du 凭据用于 Decisions；不用 caz/z，不用其他 OpenAI API 做规划/评审/探测 | 已确定 |
| 初始历史 | 不提供上一步图像、动作结果或历史摘要；当前实测状态与当前命令是当前状态，不是历史回放 | 已确定；历史是独立候选 |
| 原始基线 | 当前三 RGB + 当前机器人状态；处理信息为后续独立条件 | 已确定；后来 v3/v4/v5 已各自形成独立条件，不回写为原始基线 |
| 输出所有权 | 固定问题/选项由框架定义，不由规划器生成 | 已确定 |
| 分阶段控臂 | 规划器逐阶段指定 left 或 right；非控臂保持目标与夹爪命令 | 已确定；与近期十问双臂推进器分开标记 |
| 动作 | 世界 XYZ 各正/负/保持，YPR 每次最多一个非 hold；平移可与该旋转同时执行 | 已确定 |
| 增量 | 每非 hold 平移通道 0.02m，每非 hold 旋转通道 0.10rad | 已确定；不静默调幅 |
| 阶段推进 | `advance` 不下发新机器人动作，最后阶段 advance 仅结束计划，不认证任务成功 | 已确定 |
| 最终规划 JSON | 只含阶段及推进器输入定义；处理实现、测试、安装和审计单独交付 | 已确定 |
| 处理能力 | 规划器按任务决定方法和所需数据，可用受限程序实现并检查；不把示例当唯一算法 | 已确定 |
| 经验 | 之前先保原始记录、不使用经验；本次用户要求设计总结与 Skill 机制 | 新要求允许设计；不据此开启旧经验读取或默认注入 |
| 泛化 | 不提供物体专用路线、隐藏物体真值；按当前任务和图像做语义绑定，不要求所有任务同一个感知流程 | 已确定 |
| 优先次序 | 先证明通用抓取推进器稳定，再反推并验证 Pro 规划器合同，之后需要 YPR 的官方任务 | 最近明确要求优先；覆盖更早先堆叠/分类的执行次序 |
| 稳定门 | 冻结后 held-out 5–14、15–24 各10布局，分别至少9/10原生成功 | 已确定；不是任意物体的普适保证 |
| 停止与资源 | 用户暂停优先；server02 GPU0/1、总环境至多3，初始建议单环境；启动需8GiB空闲显存/20GiB可用RAM，另有磁盘门 | 已确定边界；当前暂停不改变 |

**协议差异不能藏起来：**

- 早期分阶段草案：单控臂，XYZ/YPR/夹爪/阶段推进共 **8问**。
- 近期通用抓取：双臂各 XYZ/七选一旋转/夹爪，共 **10问**，没有阶段推进问题，解码为14个方向/夹爪通道。
- 10问编码的授权不是分阶段8问自动改成6问的授权。本文 §6 保留8问初始合同，§12单列6问等价编码候选。不能把两者成绩直接归为“只换模型”。

## 2. 已有结果能支持什么

| 条件 | 已知结果 | 可以得到的判断 | 不能得到的判断 |
|---|---|---|---|
| 原6+10对照 | Pro普通Luna high任务成功0/6；Decisions槽级0/10，其中9完整失败、1策略拒绝 | 两套条件均未成功 | 由于工具/历史/动作有差异，不能断言某模型能力更差 |
| v2 current RGB + joint rotation | 布局0/1/2各200步，完整0/3 | 解决合法编码不等于能抓取 | 不能把失败唯一归因为缺旋转 |
| v3 + K/T/TCP投影 | 三布局完整0/3；240个旋转选择全hold | 该输入包未证明抓取改善 | 投影标记不等于目标、接触或精确几何 |
| v4 + alignment guidance | 三布局完整0/3；120 HTTP200；close0，103/240旋转非hold | 选择发生变化，仍没有成功 | 非hold增多不等于正确旋转或有效对齐 |
| v5 + rotation effects | d两路175/190步不完整，e布局2在55步不完整；没有完整有效终局 | 可以审查已执行前缀和传输故障 | 不能报0/3能力失败，不能声称有效或无效 |

原始证据见 `../../LOGS/2026-W43.md` 的 EXP001–006、`../../LOGS/2026-W42.md` 的 EXP300，以及当前 campaign 的输入/执行/原生终局审计。用户暂停后的事实以文件与真实 PID 为准，不能把这里的历史快照当实时监控。

已定位的最近传输证据是本机代理上游 TCP 超时与 TLS 前失败时间吻合；不是已收到 OpenAI HTTP 错误，也没有证明链路已修复。本文不通过额外 API 探测验证它。

**因此，初始迭代的第一步是找首个可证实的失效环节，不是再追加一段“请注意抓取”的提示。**

## 3. 借鉴 EmbodiedEvo，但保持我们的动作决策架构

EmbodiedEvo把经验落成可执行控制程序和使用边界。我们不让内部模型生成或执行机器人动作代码，借鉴的是“证据 → 解释 → 可检验修改 → 有边界的复用”这一流程。

| 角色 | 输入 | 输出 / 权限 | 不承担的职责 |
|---|---|---|---|
| 外层整体 Agent | 开发集原始记录、模型请求/回答、执行测量、外层原生结果 | 诊断、候选变更、Skill/Lesson整理、程序修复与实验管理 | 不把管理指令混入内部提示，不在线改模型回答 |
| 规划器（本机Pro） | 任务、初始三图/实测状态、动作合同、实际可用处理能力；后续版本可附筛选的英文Skill | 阶段、控臂、可观测完成条件、额外输入定义；处理实现与测试另交 | 不生成动作序列、不改问题/选项，不控制中重新规划 |
| 处理器 | 当前允许观测、当前阶段及已冻结参数 | 当前视觉关系、估计几何、有效性/不确定性、解释清楚的图像 | 不读隐藏物体状态，不返回动作方向/排名/建议动作 |
| 推进器（Decisions） | 当前任务、当前阶段、当前实测状态、三图、声明的附加信息 | 固定分类问题的选择 | 不写Skill、不改处理程序、不输出代码、不自定步长 |
| 执行器 | 原始合法选择、当前测量、固定增量 | 确定性目标解码、原生执行及审计 | 不替模型选方向，不将非法回答投影到合法动作 |
| 评估器 | 原生结果、外层图像/轨迹审查 | 成功率、完整性、失效阶段、成本 | 不把reward/success/contact等塞回模型输入 |

### 3.1 我们的 Skill 定义

**Skill = 可复用的阶段/证据合同 + 明确使用边界 + 对应测试证据。** 可附不选择动作的观测处理程序；不是固定动作脚本，也不是一句泛泛的操作建议。

例如“抬升后检查是否持物”的候选Skill应规定：何时需要这个检查、需要看到哪些关系、遮挡时不能推断什么、支持进入下一阶段的证据是什么、未满足时留在哪个阶段。不能硬编码“右臂Z+五次就视作抓住”。

职责细分：

- 规划器可复用阶段组织、所需信息和完成条件。
- 处理器可复用坐标转换、投影、观测一致性与缺失处理实现。
- 推进器只接收本阶段必要的简短合同、当前信息及字段说明；不默认接收整个经验库。
- 外层 Lesson 可记录终局失败、成本和根因分析；模型可读版本必须重新筛选，仅留下允许观测下可用的信息。
- 外层修复执行器/传输属于工程变更；即使有效也不升级为抓取Skill。

## 4. 初始输入合同与观测权限

### 4.1 所有内部模型的共同边界

允许：当前 RGB、当前机器人实测关节/姿态、当前夹爪命令、经核实可获取的实际开度、公开机器人几何、公开相机K和当前实测安装T、由这些信息计算的估计。

禁止：仿真物体真位姿、隐藏几何、接触/碰撞报告、附着标志、奖励、分数、success、含这些内容的摘要，以及暗藏场景答案的文件名/布局ID/目录。任务自然语言和当前图像中的物体身份是允许的信息，私有配置表不是。

如果处理代码发现了禁用字段，不能只是改字段名；应拒绝构造请求并记录输入边界错误。最终请求要检查嵌套JSON、图像标签、自动拼接说明中的非英文文字。

### 4.2 当前机器人状态必须纠正命名歧义

`controller.py:permitted_state` 当前把来源 `gripper_opening_command` 放进 `gripper_opening_measured`。**在核实原生来源前不能称它是真实测量开度。** 建议未来合同将其改名 `gripper_command`，真正测量另设可空字段，并以独立输入修正记录。这是语义修正提议，本文没有改运行代码。

`keep` 表示保留执行器当前保存的夹爪命令；不能拿测量开度替代当前命令，也不能从close命令推出持物。单步决策的目标应从当前实测TCP计算，而非在旧目标上累加。

### 4.3 规划器准备时的输入

| 字段 / 内容块 | 内容 |
|---|---|
| task_instruction | 原生任务英文说明，不附评分器内部条件 |
| initial_observation | 三张当前原图、当前机器人状态、相机标识与时间戳 |
| fixed_action_contract | §6的轴/增量/夹爪/推进语义及固定问题全文 |
| available_capabilities | 经现场核实的工具、库、公开机器人/相机资产与资源限制；未装好的工具不能写成可用 |
| reference_implementations | 实际使用的参考说明全文；只给路径不算已提供内容 |
| transferable_knowledge | 初始为空；将来仅附冻结的精选英文Skill及可用证据摘要，单独建条件 |
| delivery_contract | §5的最终JSON与单独处理实现/测试交付规则 |

准备过程不移动机器人、不消耗额外机器人试探动作；需额外测量或主动观察才能实现的处理能力，必须标记为后置条件，不能谎称已验证。准备期间状态若失效，应终止准备或重新取得同一未动作场景的当前观测并记录，不把旧图当当前图。

### 4.4 推进器每次的输入外壳（拟定）

下面是结构示例，JSON里的 null/空对象表示尚未采样的值，不是可以直接发给真实推进器的有效观测。初始 raw 条件的 `additional_inputs` 为空。

```json
{
  "contract_version": "staged-axes-v1",
  "observation_id": "current-observation-id",
  "observation_time": "current-observation-time",
  "task_instruction": "The current native task instruction.",
  "current_stage": {
    "id": "current-stage-id",
    "goal": "The current observable goal.",
    "controlled_arm": "left",
    "target_description": "The task-relevant visible target.",
    "completion_condition": "The evidence required before advancing.",
    "additional_inputs": []
  },
  "robot": {
    "left": {
      "tcp_position_world_m": null,
      "tool_rotation_world_from_local": null,
      "gripper_command": "open",
      "gripper_opening_measured": null
    },
    "right": {
      "tcp_position_world_m": null,
      "tool_rotation_world_from_local": null,
      "gripper_command": "open",
      "gripper_opening_measured": null
    }
  },
  "action_config": {
    "translation_increment_per_axis_m": 0.02,
    "rotation_increment_rad": 0.1,
    "native_steps_per_action": 5,
    "frame": "environment_origin_world",
    "maximum_nonhold_rotation_channels": 1
  },
  "camera_order": ["cam_high", "cam_left_wrist", "cam_right_wrist"],
  "camera_calibration": null,
  "additional_inputs": {}
}
```

机器人坐标/矩阵缺失或过期时，实际运行应在发模型前中止该动作请求；可空的感知信息则明确无效，不伪造零误差。时间戳、ID用于当前状态配对，不携带历史解释。三图是后续独立 `input_image` 块，不是仅提供本机路径。K/T只在相应命名条件启用，不能默默进入raw基线。

初始不输入剩余native预算来诱导策略；外层运行器负责硬预算。以后如测试预算信息，作为单独条件记录。当前阶段指针是控制状态，不是“上一动作已成功”的证据。

## 5. 规划器：英文提示、最终输出与处理交付

### 5.1 初始英文角色提示（建议稿）

该块与固定动作说明、固定八问、任务/观测、交付Schema和真实能力说明一起构成同一规划准备上下文。额外参考内容是可选参考，不是当前任务的预计算答案。

```text
You are the planner in a planner-advancer robot control system.
Prepare one executable plan before robot control begins. The advancer receives
fresh observations and answers a fixed set of categorical action and stage
progress questions. It does not write or execute robot-control programs.

Divide the task into understandable stages. For each stage, specify its goal,
controlled arm, visible target description, and observable completion condition.
Choose stages from the task and evidence rather than copying a fixed object route.
Do not prescribe a sequence of action directions or select the advancer's actions.

Determine what information the advancer needs. Start from current RGB and measured
robot state. When additional information is necessary, design, implement, and
test processing that computes it from permitted fresh observations. Reference
methods are optional examples, not an exhaustive list or a required pipeline.
Explain meanings, units, frames, uncertainty, and missing-data behavior.

Keep task goals, action definitions, increments, questions, choices, and native
limits unchanged. Use no hidden object state, contact reports, rewards, scores,
or task-success signals. Do not use past episodes or observation history unless
the supplied input contract explicitly includes them.

Complete the processing implementation and its input-binding checks before the
final plan. Preparation tools cannot move the robot. Do not claim that a test was
run unless an actual tool record exists. State accuracy and visibility limits.
Successful execution of a processor alone does not validate its measurements.

Return only the final JSON matching the supplied plan schema. It describes stages
and advancer input definitions, not code, commands, test reports, or dependencies.
Deliver processing and verification artifacts separately through the available
tools. If a required component cannot be implemented or checked, return the
separate blocked response instead of presenting an executable plan.

The runtime will use this plan throughout one episode without replanning.
The advancer owns motion, gripper choices, and stage-progress decisions.
Advancing a stage does not execute an action or certify native task success.
```

### 5.2 最终计划 JSON Schema（建议的具体键名）

旧约定确定了语义，没有完全冻结这些键名。本Schema是本次提出的可实现合同；不冒称现有运行器已经支持。阶段数不强制为固定4–12个，避免为了格式硬拆阶段；数目与零动作推进上限在外层配置中预注册。

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["stages"],
  "properties": {
    "stages": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["id", "goal", "controlled_arm", "target_description", "completion_condition", "additional_inputs"],
        "properties": {
          "id": {"type": "string", "minLength": 1},
          "goal": {"type": "string", "minLength": 1},
          "controlled_arm": {"enum": ["left", "right"]},
          "target_description": {"type": "string", "minLength": 1},
          "completion_condition": {"type": "string", "minLength": 1},
          "additional_inputs": {
            "type": "array",
            "items": {
              "type": "object",
              "additionalProperties": false,
              "required": ["name", "description"],
              "properties": {
                "name": {"type": "string", "minLength": 1},
                "description": {"type": "string", "minLength": 1}
              }
            }
          }
        }
      }
    }
  }
}
```

外层验证还需：阶段ID唯一且顺序即数组顺序；每阶段附加输入名唯一；全部文本英文；无预定动作列表/禁用字段/未实现依赖；完成条件能由允许观测判断。不是任意字符串通过Schema就能启动。

初始指针取第一阶段，不要求内部模型重复返回task、模型名、测试记录或“ready=true”。所需任务/运行元数据保存外层manifest。

下面给出满足Schema的完整结构样例。它只用于接口检查，**不是实际任务的规划结果、不是预置阶段路线**。真正阶段/控臂/目标由规划器依据当前任务与图像生成，不把本例自动送入原生执行。

```json
{
  "stages": [
    {
      "id": "candidate_grasp",
      "goal": "Establish visible enclosure of a task-relevant grasp region.",
      "controlled_arm": "left",
      "target_description": "The visible object required by the current task.",
      "completion_condition": "Current views support enclosure by the opposing fingers with a closed gripper command. This alone does not establish retention.",
      "additional_inputs": []
    },
    {
      "id": "retention_check",
      "goal": "Establish visible object retention away from its support.",
      "controlled_arm": "left",
      "target_description": "The same task-relevant object visible between the fingers.",
      "completion_condition": "Current views show the object enclosed by the fingers and separated from its visible support. Ambiguous or occluded evidence does not satisfy this condition.",
      "additional_inputs": []
    }
  ]
}
```

这个raw示例不暗示单当前图可以证明“持续随动”，后者需要外层跨帧审查或后续明确增加历史的条件；也不声称两个示例阶段足够覆盖所有任务要求。

准备失败的单独输出：

```json
{
  "status": "blocked",
  "reason": "A required observation-processing component could not be verified."
}
```

这是准备期协议，不新增推进器“信息不足”选项；blocked意味着不进入原生控制，不自动重问直到得到可运行计划。

### 5.3 处理程序的单独合同（open-processing条件）

建议维持已有处理草案的独立进程形式：

```text
/work/processor /input/observation.json /output/additional.json
```

上面命令为单行。它是拟定沙箱内部接口，不是让用户现在启动的命令。

输入包含当前 task、current_stage、robot_state、cameras、images；输出只映射本阶段声明的附加输入名。程序每次重算，不缓存过去物体位置当当前值。

输出结构示例（无测量时必须无效，不得把null改成0）：

```json
{
  "grasp_region_relation": {
    "valid": false,
    "value": null,
    "units": "dimensionless",
    "frame": "current_camera",
    "source_cameras": ["cam_high", "cam_right_wrist"],
    "observation_id": "current-observation-id",
    "uncertainty": "The opposing finger region is occluded.",
    "missing_reason": "Visible evidence is insufficient for this relation."
  }
}
```

`grasp_region_relation`只是输入命名示例，不强制所有阶段使用。额外图像可返回 `/output` 内PNG的 `image_path` 及英文描述；运行器验证路径、图像存在和当前观测关联后编码成图像块发送。不得把路径当作模型已看图。

单独产物：处理源码/依赖锁定、输入输出映射、实际测试输出、图像检查、坐标/单位/缺失测试、能力限制、代码与prompt哈希。**这些不进入最终规划JSON，但必须真实存在。**

处理准备时只能读取受限当前观测、公开机器人/相机资料及核实过的依赖，不能挂载密钥、仿真私有配置、其他实验或旧经验目录。安装需在项目环境且不改Conda权限；工具可用性不能照抄旧服务器说明。

## 6. 推进器：固定动作说明、提示与完整问题

### 6.1 共享英文动作说明

```text
Control the TCP, the center between the gripping faces. Both arms use the same
world frame: standing behind the bases facing the workspace, +X is right, +Y is
forward, and +Z is up. Image directions depend on the camera; wrist cameras move.

Choose negative, hold, or positive for world X/Y/Z translation and for rotation.
Yaw is an increment about world Z, pitch about world X, and roll about world Y.
Positive rotations follow the right-hand rule. These are not absolute Euler angles.
Rotation is about the TCP and alone keeps its target position fixed.
At most one of yaw, pitch, and roll may be non-hold. Translation may accompany it.
Each non-hold translation component is 0.02 meters; rotation is 0.10 radians.
Only the stage's controlled arm receives these choices; the other arm preserves
its current targets and gripper command.

Open and close set the controlled gripper command; keep preserves that command.
A close command or a measured aperture alone does not establish a grasp.
Advance means the stage condition is already satisfied by current evidence.
For advance, all motion choices must be hold and the gripper choice must be keep.
The runtime changes the stage pointer without executing a new action.
```

轴名称沿用已核实的world约定，不改成通常机器人文献中另一套pitch/roll。实际动作计算规则见§7；法兰偏移是执行器内部实现细节，不向模型堆入无关说明。

### 6.2 初始英文角色提示（分阶段raw版建议稿）

```text
You are the advancer in a planner-advancer robot control system.
Use the current task, stage, completion condition, controlled arm, current robot
state, and three current camera images to choose one coherent action.
Use any additional input only with its supplied meaning, validity, and limits.

Choose actions that make observable progress toward the current stage goal.
Do not assume that an earlier action succeeded. The stage pointer and a robot
command are not evidence that an object moved, was enclosed, or is being held.
Distinguish visible object evidence from robot projections and estimates.
Do not invent hidden geometry or interpret missing measurements as zero error.

If the stage condition is already supported by the current observations, select
advance, hold all motion channels, and keep the gripper command. Otherwise select
continue and choose the action justified by the current evidence. Hold channels
whose change is not justified. Do not claim completion from uncertainty.

All question answers describe the same action. Select at most one non-hold
rotation channel. Return the categorical answers through the supplied questions;
do not add a plan, code, explanation, or new choices.
```

这是初始最小职责提示，不默认拼入v4全部对齐长提示或v5候选表。是否采用某项输入由§11证据诊断决定，一次只作为命名条件比较。机器人轴/夹爪/当前图说明属于接口事实，不应每轮重写。

### 6.3 分阶段八问的 Decisions `questions` 定义

八问共享同一次多模态请求，不是八次API调用。以下为完整定义，`stage_progress`是本次合同拟定键名；不由规划器改写这些选项。

```json
[
  {
    "type": "choice", "name": "x",
    "instructions": "Choose the controlled TCP world-X translation direction for the current stage.",
    "choices": [
      {"value": "negative", "description": "Apply minus 0.02 meters on world X."},
      {"value": "hold", "description": "Apply no world-X translation."},
      {"value": "positive", "description": "Apply plus 0.02 meters on world X."}
    ]
  },
  {
    "type": "choice", "name": "y",
    "instructions": "Choose the controlled TCP world-Y translation direction for the current stage.",
    "choices": [
      {"value": "negative", "description": "Apply minus 0.02 meters on world Y."},
      {"value": "hold", "description": "Apply no world-Y translation."},
      {"value": "positive", "description": "Apply plus 0.02 meters on world Y."}
    ]
  },
  {
    "type": "choice", "name": "z",
    "instructions": "Choose the controlled TCP world-Z translation direction for the current stage.",
    "choices": [
      {"value": "negative", "description": "Apply minus 0.02 meters on world Z."},
      {"value": "hold", "description": "Apply no world-Z translation."},
      {"value": "positive", "description": "Apply plus 0.02 meters on world Z."}
    ]
  },
  {
    "type": "choice", "name": "yaw",
    "instructions": "Choose the rotation increment about world Z at the controlled TCP. At most one rotation channel may be non-hold.",
    "choices": [
      {"value": "negative", "description": "Rotate minus 0.10 radians about world Z."},
      {"value": "hold", "description": "Apply no yaw increment."},
      {"value": "positive", "description": "Rotate plus 0.10 radians about world Z."}
    ]
  },
  {
    "type": "choice", "name": "pitch",
    "instructions": "Choose the rotation increment about world X at the controlled TCP. At most one rotation channel may be non-hold.",
    "choices": [
      {"value": "negative", "description": "Rotate minus 0.10 radians about world X."},
      {"value": "hold", "description": "Apply no pitch increment."},
      {"value": "positive", "description": "Rotate plus 0.10 radians about world X."}
    ]
  },
  {
    "type": "choice", "name": "roll",
    "instructions": "Choose the rotation increment about world Y at the controlled TCP. At most one rotation channel may be non-hold.",
    "choices": [
      {"value": "negative", "description": "Rotate minus 0.10 radians about world Y."},
      {"value": "hold", "description": "Apply no roll increment."},
      {"value": "positive", "description": "Rotate plus 0.10 radians about world Y."}
    ]
  },
  {
    "type": "choice", "name": "gripper",
    "instructions": "Choose the controlled gripper command for the current stage.",
    "choices": [
      {"value": "open", "description": "Command the gripper to open."},
      {"value": "close", "description": "Command the gripper to close."},
      {"value": "keep", "description": "Preserve the current commanded gripper target."}
    ]
  },
  {
    "type": "choice", "name": "stage_progress",
    "instructions": "Is the stage completion condition already supported by the current observations? Advance requires all motion channels hold and gripper keep.",
    "choices": [
      {"value": "continue", "description": "The condition is not established. Choose the next justified action."},
      {"value": "advance", "description": "The condition is established. Advance without executing an action."}
    ]
  }
]
```

API外壳仍为当前已使用的 `model`、`input`、`questions` 三部分；model按实际授权配置核对。`input`包含角色/动作说明、英文当前状态JSON及三个真实图像块。本文没有伪造endpoint之外的接口字段，也不把普通Responses的JSON schema调用当成Decisions。

原生回答通常在 `answers` 数组中携带name/choice；以下只是执行器提取后的合同示例，不要求接口返回这个顶层JSON：

```json
{
  "x": "hold", "y": "hold", "z": "hold",
  "yaw": "hold", "pitch": "hold", "roll": "hold",
  "gripper": "keep", "stage_progress": "advance"
}
```

保存原始返回，再做无损提取。缺键、重键、越界选项、多非hold旋转、advance与动作冲突均记为非法输出并停止本回合；不修答、不选其中一个轴、不静默忽略动作、不重采样。初始没有“信息不足”输出；证据不足时continue不等于强制乱动，全部hold也可以，外层按停滞规则结束而非无限空转。

## 7. 执行、阶段转换与评分

### 7.1 动作解码

以当前实测工具姿态R和TCP位置p为起点，令XYZ选择的符号为s：

`p_target = p_measured + 0.02 * [s_x, s_y, s_z]`。

单旋转用固定world轴左乘：yaw→Z、pitch→X、roll→Y，`R_target = R_increment @ R_measured`；全hold保持姿态。工具参考点与TCP偏移按已核实的公开机器人定义内部换算。禁止逐分量累加Euler角、反转未声明的符号或从旧目标累计位移。

当前实现每个动作执行5个native步，因此general_pickup的200步最多容纳40个这种动作。**20mm是每通道，不是合成向量长度上限**；XYZ同时非hold时长度为 `sqrt(3)*20mm`，不自动归一化。原生插值、IK与物理/成功判据不因Skill或阶段而改变。

对每个动作分别保存原始选择、解码目标、执行步数、实测到达值、跟踪误差。合法输出、可解码目标、IK可行、实际跟上、物体有效操作是五个不同判断。

### 7.2 阶段转换

1. 原生终止事件优先：停止继续请求，记录外层结果，不发送success给模型。
2. `continue`：通过输出合法性后执行动作；全hold也按已声明执行语义消耗native步，不偷偷变成免费等待。
3. `advance`：验证全hold/keep，阶段指针前移；不执行、不消耗native动作步，但消耗一次模型调用。
4. 下一阶段可用同一当前观测，但须更新阶段并重新运行所需处理，不能重用前阶段附加输入。
5. 最后阶段advance只得到 `plan_finished`。外层读取独立native结果，可能仍是失败；不通过延长horizon或偷偷回位补成成功。
6. 防零动作循环：推进总次数不超过计划阶段数；另设并记录模型调用硬预算，不能因advance免费而无限调用。

建议首个分阶段配置模型调用上限64（最多40次五步动作，另留阶段推进余量），这是外层待测参数，不是已实现或模型输入；计划阶段过多无法适配预算时在启动前拒绝，不能临时扩预算。

### 7.3 停滞与恢复边界

初始无重规划/历史，也不预装任务专用恢复路线。建议外层在**连续5次continue全hold/keep**后记录 `policy_stall` 并结束，计入策略未完成，不算基础设施中断。其他“没有物体进展”的判断若不能可靠测量，只供离线诊断，不自动覆盖动作。

这些阈值在首个新条件启动前冻结；外层停止不等于模型新增STOP选项。今后Skill的恢复策略先表示为阶段条件与当前可观测证据，不能偷偷让执行器执行额外动作。若需要回跳、重规划或动态改计划，列为后置架构变更。

## 8. 从原始证据到 Lesson、Skill 的完整流程

### 8.1 三种记录不能混为一谈

| 记录 | 内容 | 可以何时写 | 是否默认进入模型 |
|---|---|---|---|
| Evidence | 实际请求、图像、回答、目标、实测状态、原生终局、故障 | 事件发生即保存 | 否；模型仅得允许的当前观测 |
| Lesson | 失败特征、候选解释、下一项验证和适用边界 | 有重要事实即记录，允许明确标hypothesis | 否 |
| Skill | 有证据支撑的可复用阶段/输入/完成/失败合同，可附测量程序 | 控制过程及边界经过验证后版本化 | 仅后续命名条件可筛选注入 |

不要求失败必须产出Skill；“不知道根因”是合法结论。不因计划写得顺、程序能运行或某次close而升级。

### 8.2 每个重要事件之后怎样总结

1. **确定事实**：先配对动作前图、原回答、解码目标、动作后图/实测状态；区分“模型当时看到的图”和“事后审图”。
2. **找首个失效环节**：目标/可见抓区→方向选择→实际跟踪→可见包围→闭爪→抬升持物→原生终局。后面的失败不能自动解释前面的原因。
3. **列竞争解释**：例如旋转方向错、测量歧义、跟踪不足、抓区不可见，不能只挑最顺手的解释。
4. **选择最小可辨别验证**：优先离线重算投影/轴/时序，能排除实现错误就不先跑整回合。
5. **确定修改归属**：字段坏了修字段；阶段完成条件不成立修阶段合同；输入不足改输入/处理；方向理解问题才改对应提示；接口数学错误修执行器并单列工程条件。
6. **预注册变化与判据**：写清保留什么、只改什么、预期在哪个环节发生何种变化，失败时如何解释。
7. **验证后回写**：保留旧版、失败和反例，记录支持范围。没有新事实则不新建EXP或新Skill。

初始外层Agent可以在回合中做只读标记，但prompt/Skill/代码不在运行中改变；实质修订等本批全部退出后进行。不会照搬EmbodiedEvo的reset和回合内代码改写权限。

### 8.3 Lesson 英文模板（设计模板，不是经验事实）

```text
ID: LESSON-CANDIDATE-001
Title: A concise failure or recovery finding.
Status: hypothesis
Scope: outer-review-only
Signature: What the paired images, raw choices, and measurements actually show.
Evidence: Exact run, observation, request, and execution identifiers.
Interpretation: A proposed explanation, separated from the observed facts.
Alternatives: Other explanations not yet excluded.
Instead: One specific change to test next.
Test: The comparison and observable result that could support or reject it.
Applicability: Required visible conditions, robot, frame, and action contract.
Limitations: Missing views, uncertainty, and untested transfer.
Counterevidence: Recorded failures or conflicting observations.
Next status: Remain a hypothesis until the stated test is completed.
```

状态建议：`hypothesis`、`verified_in_development`、`scene_specific`、`contradicted`、`retired`。verified要列实际支持次数/总尝试数、布局/物体覆盖；不能只写形容词。基础设施记录使用独立类型，不归入抓取因果结论。

### 8.4 非 code-as-policy Skill 英文模板

```text
ID: SKILL-CANDIDATE-001
Version: 0.1.0
Status: candidate
Purpose: The reusable observable behavior this contract supports.
Consumers: planner, processor, or advancer; list only intended consumers.
Action contract: The exact fixed interface version; no new action primitives.
Applicability: Robot type and visible geometric conditions, not a layout ID.
Preconditions: Evidence required before using this skill.
Required observations: Current cameras and measured robot fields.
Derived inputs: Names, meanings, units, frames, validity, and uncertainty.
Stage goal: The relation to establish, without prescribed action directions.
Completion evidence: What must be visible or measured before advancing.
Failure evidence: What contradicts the goal or makes the input unusable.
Recovery boundary: What the current fixed plan can handle and when to stop.
Processing artifact: Optional measurement-only code and immutable version hash.
Parameters: Explicit tolerances and their development evidence.
Evidence: All supporting and unsuccessful development attempts.
Counterexamples: Observed limits and configurations not covered.
Transfer status: Not established until evaluated under a frozen manifest.
Model-facing excerpt: The minimal English content needed by each consumer.
Supersedes: Earlier versions and the evidence motivating this revision.
```

Skill可以复用“如何表示/判断某个关系”，但不把外层已挑好的动作藏在 `recommended_direction`、已排名候选、固定世界坐标或“物体名→路线”查表中。运行时目标和身份必须来自当前任务与允许观测。

### 8.5 升级、回退与冻结

建议用以下具体门槛管理开发，不把它们当统计稳定证明：

- 一次现象仅能建立候选Lesson；一次子过程成功仅能建立candidate Skill。
- `verified_in_development`：至少两个独立开发回合支持同一可观察过程，包含全部失败分母；还必须通过输入绑定、缺失/遮挡不误判、边界与坐标检查。两个回合都来自同物体时标清范围，不能写跨物体。
- 对泛化候选，必须覆盖预先登记的不同开发物体/可见几何；当前0/1/2布局的物体覆盖按真实资产审计，不能从layout数直接推对象数。
- 未被覆盖的条件保持不确定，反例出现则缩小适用范围或retire；不删除旧条目、不用“再加一句例外”无限扩大规则。
- 真正使用某个Skill时冻结内容、处理代码、版本与筛选规则；本条件中后续不改。新发现留给下一开发条件。
- held-out只能使用冻结前选定的条目；第一块结果出来后也不修改，再跑第二块。若已用第一块调参，该块降为开发数据，不能继续算held-out。

两个独立开发回合不是授权无限复跑；只使用预登记的有限新条件回合，完整失败不原样重跑填卡。若没有足够合法证据，就保持candidate，不为了升级补同条件次数。

### 8.6 注入不是“把总结全塞给模型”

先记录但不使用的E0条件，和使用冻结Skill的E1条件必须区分。未来检索按当前阶段和可见适用条件，初次建议至多2条，完整记录筛选规则、命中的ID、实际英文片段与哈希；不靠目录关键词相似就自动灌入。

- 规划器拿阶段设计/信息需求/适用边界。
- 推进器拿当前阶段的目标、所需关系和完成/失败判据。
- 处理器拿已验证算法与参数，不拿动作建议。
- 外层故障分析、数据划分、调参安排不发送内部模型。

本轮不创建这些真实条目。未来授权形成新经验时也新建独立版本库，不默认迁入旧 `experience/`。可在独立campaign下使用 `knowledge/candidates/`、`knowledge/skills/`、`knowledge/lessons/`、`knowledge/frozen/`；目录创建与内容注入均需对应后续实施条件。

## 9. 外层迭代的英文工作指令草案

这是给外层实验Agent使用的流程提示，**不放进规划器或推进器请求**。

```text
Review the immutable evidence before proposing a change. Separate observed facts,
causal hypotheses, and proposed interventions. Identify the earliest supported
failure in perception, direction selection, execution tracking, enclosure,
closure, retention, stage transition, or native completion.

For each intervention, specify the evidence identifiers, competing explanations,
the single change class, fixed components, expected observable improvement,
rejection criterion, finite development allocation, and rollback condition.
Prefer offline checks when they can answer the question. Do not use an additional
model API for diagnosis unless that exact use is authorized.

Write useful findings promptly as hypotheses with evidence. Promote a reusable
contract only after its preconditions, completion and failure evidence, interface
bindings, and declared development checks are supported. Include failures and
counterexamples. Do not label a raw trajectory or an untested prompt as a skill.

Keep control interfaces and evaluation rules fixed. Do not repair model answers,
resample failed decisions, revive ended episodes, or silently replace a model.
Never change source or model-readable knowledge during a running condition.
Freeze the selected knowledge before held-out evaluation and do not learn across
held-out episodes. Respect user pause and unresolved infrastructure stops.
```

## 10. 每轮到底允许改哪些东西

| 证据问题 | 优先修改对象 | 这一轮不一起改 | 需要的检查 |
|---|---|---|---|
| 字段含义/坐标/时序错误 | 输入适配与命名 | 不同时加Skill或改阶段 | 来源追踪、单位/帧/时间、真实序列化请求 |
| 当前图不足以支撑某判定 | 观测处理/输入表示 | 不同时改动作增量 | 当前图一致性、有效/缺失、方向无泄漏 |
| 规划阶段退出条件不可观测 | 规划提示或Skill的完成合同 | 不让运行器硬判advance | 同一观测下的可判定性及阶段误推进审查 |
| 目标关系已清楚但选择反复错误 | 对应问题说明或最小推进提示 | 不堆入处理算法细节 | 原始选择→目标→实测关系，包含反例 |
| 合法动作未实际跟上 | 执行/IK/稳定时序诊断 | 不把跟踪误差叫模型推理失败 | 原生执行与误差；修改执行规则要独立标条件 |
| 闭爪但没有持物证据 | 包围/持物的输入或阶段合同 | 不把close或TCP到位当成功 | 多视角可见关系、抬离支撑、原生终局 |
| 传输/磁盘/调度失败 | 自有基础设施 | 不改科学条件、不产生任务经验 | PID/容器/字节/回执、停止语义、独立故障记录 |

同一类别内部可做必要的一致性修复；若一项修复必须同时改变多个类别，先说明不可分割原因，把它作为新组合条件，不能声称隔离了某个因果因素。

候选变更单必须填：证据、最早失效环节、竞争解释、改动文件/模型消费者、保持不变部分、验收指标、开发样本预算、失败后下一步。没有这些就不发起新完整回合。

## 11. 初始迭代顺序：先补足证据，再接规划器

### D0：暂停期间的离线审查，优先做

**输入**：当前campaign已有原图/模型实际图、请求、回答、实测运动及外层终局；不读旧经验，不发模型调用，不控制机器人。

**交付**：每个布局一份最早失效阶段表，逐项注明confirmed/possible/unknown，列动作前后证据和反例；另有输入语义清单与处理可信度清单。

先检查四件事：

1. `gripper_opening_measured`真实来源；几何投影与实际图像/相机运动是否一致。
2. v3/v4/v5的选择是否转换成预期世界方向；实际运动是否跟上；不能只重算命令。
3. 模型最后一次还能可靠看到目标/夹爪是什么时刻，包围/闭爪的可判定条件何时丢失。
4. 是否有足够证据把“定位差、朝向差、跟踪差、闭爪判断差”分开；没有就保持未知。

**通过标准**：至少能定位一个值得独立验证的环节，或明确说明现有记录不能识别根因以及缺哪项合法观测。不要求强行选一个解释。

### D1：推进器单项输入/语义修正，尚不接在线规划器

仍用完整任务目标及现有十问joint接口，不预写物体专用阶段/轨迹。根据D0仅选择一个首要瓶颈，例如字段语义修正、可见抓区关系表示或保留/去除候选表；**这些是互斥首选，不一次全部加上**。

规划器暂不参与原生回合；外层只准备可核查的通用输入合同，作为未来规划器必须能交付的信息目标。任何目标/区域都由当前RGB与公开几何推断，不能外层人工提供真值坐标充当基线。

未来用户恢复运行、传输/资源准入成立后才可执行：一批最多development0/1/2三个新独立回合，初始单环境串行，完整200步原生horizon；科学条件固定。完整失败保留，不在同条件重复补次数。任何基础设施中断停止后续派发，先离线收敛，不自动新开或重发。

**候选判断**：请求合规且实际在预注册环节有可核实改善，并审查是否造成新退化；最终仍看原生成功。若原生全部失败，最多支持该局部环节改善，不称推进器稳定。

### D2：形成第一个有证据的 Skill 合同

从D1得到的实际有效过程总结输入需求、适用条件、完成/失败证据；没有成功过程时先修Lesson，不生成“万能抓取Skill”。将实现修复、子过程有效和整个任务成功分别标记。

每一新科学条件最多一次三布局开发批次，之后必须书面归因/反例审查；同主题连续两次候选没有改善预定环节时停止加提示，重审“当前信息是否足以完成这个判定”，必要时把问题交用户选择，避免CIRCLE-1循环。

### D3：推进器冻结验证

只有开发中已支持完整抓取才投入held-out。冻结prompt、输入、问题、增量、原生执行、可用Skill与筛选规则；运行5–14及15–24两个块，每块10布局分别至少9个原生成功。

固定每块10个预分配槽。报告成功/完整失败/策略不完整/基础设施不完整；基础设施槽不自动替换，不把缺失算模型能力失败，也不能通过缩小分母达标。比如9成功+1基础设施缺失，应报至少9/10槽已成功但完整评估不足，暂不认证稳定；若明确批准独立补缺，原中断与新回合均保留且只按预声明补缺政策判断。

### P0：反推并验证规划器合同

推进器有验证过的信息需求后，才让本机Pro按§5生成这些信息和阶段。先离线检查规划/处理交付，不能只看JSON漂亮或处理脚本退出0。

先在开发集执行分阶段raw八问基线A0，记录接口从十问到八问、控臂/阶段语义变化；它不是与D条件单因素的模型比较。再逐项比较：A1开放处理但不注入经验；A2冻结Skill给规划器；A3在A2基础上给推进器必要片段。样本配置每次冻结，不能三项一起上而归因Skill。

规划器是否能成功复现已验证信息、阶段是否可观测、推进器是否实际完成、原生是否成功是四个验收层。即使D3通过，组合系统也需独立冻结验证，不继承推进器单独的稳定称号。

### P1：组合冻结及后续任务

组合系统冻结后，按相同两块标准验收；已看过用于诊断/调参的布局不再冒称新held-out，可在无信息泄漏与预登记规则下另选独立布局，或明确仅报告配对回归。

之后才选择官方高成功率且确实有姿态调整需求的任务：核对官方榜单模型/版本/场景，记录选择依据，不凭名称断言必须YPR。优先验证单项姿态与真实跟踪，再做完整任务。更早stack_blocks/classify_objects和官方前十扩展仍保留，但不越过当前稳定闸门。

## 12. 拟测试清单：不全部塞进初始版本

| 编号 | 要回答的问题 | 最小比较 / 检查 | 优先级与边界 |
|---|---|---|---|
| T00 | 输入含义正确吗 | 当前命令/实际测量分开，真实请求英文/允许字段/三图哈希一致 | 离线最先做 |
| T01 | 原因是选择还是跟踪 | 原始方向、解码目标、动作后实测及可见关系分开 | 离线最先做 |
| T02 | 几何包是否真的可用 | 原图/投影对齐、K/T更新、腕相机动、轴符号、遮挡 | 先离线，必要再单项条件 |
| T03 | 信息增加是否改善关键环节 | 选定一个派生输入，对照既有条件；其余固定 | D1首选由证据决定 |
| T04 | Skill是否有独立价值 | 处理/动作一致时，无Skill vs规划器Skill，再测推进器片段 | 有验证Skill后 |
| T05 | 阶段是否被正确推进 | 完成/未完成/遮挡观测对；advance无动作及终局分离 | P0前离线与开发审查 |
| T06 | 七选一能否保留分阶段语义 | 单臂XYZ+rotation+gripper+progress六问，与8问合法动作集合核对 | 后置；需讨论替换固定8问，不默认启用 |
| T07 | 历史有用吗 | 无历史 vs一步结构化历史，之后才加前后图 | IMP-001，独立条件，不能偷加进初始输入 |
| T08 | 控臂由谁选 | 规划器固定控臂 vs推进器控臂 | IMP-002，独立架构变化 |
| T09 | 问句/指令与长短提示 | 固定语义/数据下对照文字形式，保留完整接口初始版本 | IMP-003/006，瓶颈明确后 |
| T10 | 规划器开放处理是否必要 | raw、开放处理；附加信息的真实性与作用都检查 | IMP-004，算法不限定示例名单 |
| T11 | 卡住后是否重规划 | 先定触发/预算/历史，再测，不在首版循环调用Pro | IMP-005/008，待讨论 |
| T12 | 固定20mm/.10rad是否过粗 | 保持方向与其他规则，仅在另一个批准条件改增量 | IMP-007相关；首版不靠Skill偷偷调幅 |
| T13 | 文字信息充分时图像价值 | 相同冻结规划/文本，带图 vs不带图 | 后置；Jev需另行授权，不自动替换Decisions |
| T14 | 真实任务迁移与YPR | 冻结技能，在新几何/官方任务完整终局评估 | 最后；不是看一次rotate/close |

当前v5的K/T、TCP标记、旋转效果表均保留为候选组件，不因写过或离线数学正确就默认全纳入新初始版本。没有证据支持的输入可回退，但回退也记录为新条件，不覆盖历史。

精确目标误差如果已由处理器给出，方向问题可能被处理器简化。应如实记录信息来源，不能把感知/数值处理贡献都归于Decisions。未来“同等观测的简单反馈控制”是科学比较候选，新增baseline需按项目决策边界讨论，不由本文启动。

## 13. 验证与指标：怎样知道修改有效

### 13.1 实施前离线验收

1. JSON与接口：计划键名、阶段顺序、输入绑定、八问名称/选项、原答完整性、联合旋转限制；非法回答不得执行。
2. 动作：正负XYZ、world左乘旋转、TCP不漂移、非控臂不动、keep保命令、advance无动作；单项诊断不算任务成功。
3. 数据：原图与实际模型图配对，时间戳/观测ID一致，腕相机更新，单位/帧、英文与禁用字段检查。
4. 处理：输出存在与语义检查分开；错误对象/空mask/遮挡/投影在背后/外参失效/null等要显式无效，不能让模型收到伪精确值。
5. 知识：模型可读片段不含外层评分/实验管理/隐藏场景答案；版本与消费者正确；测试布局未进入开发材料。
6. 调度：一个worker错误仅停后续派发；用户停止立即结束自有活动；失败/未知交付不重发；暂停状态阻止启动。

测试使用项目既有环境和内存夹具即可；若创建临时测试脚本，完成后删除。文档通过检查不代表这些未来运行器功能已经实现。

### 13.2 每个条件统一报告

| 层次 | 记录指标 | 解释限制 |
|---|---|---|
| 请求 | HTTP状态、时延、上传、模型/端点、原回答完整性 | HTTP200不是操作成功 |
| 策略 | 合法率、全hold停滞、旋转/夹爪次数、阶段误推进 | 频次只诊断，不当主指标 |
| 执行 | 每轴命令、目标/实测位移和角误差、实际native步 | 命令到位不是抓住 |
| 感知/关系 | 当前目标可见性、可判定包围/对齐、有无矛盾 | 不可见记unknown，不用真值补上 |
| 操作 | 可见抬离支撑、夹爪间持物、跨检查点持续持物、掉落 | 无历史输入条件只能外层做跨帧审查 |
| 阶段 | advance时证据是否成立、次数、plan_finished与native差异 | 阶段结束不是任务成功 |
| 原生 | 完整性、valid、success、原生score（若有） | 只供外层评估，不回灌模型 |
| 成本 | 规划工具/模型调用、推进调用、native步、墙钟、媒体/磁盘 | 8问不算8请求，工具测试另计 |

主要结论仍以完整原生任务成功及预注册稳定门为准。比例报告显式给分子/分母，小样本不宣称泛化；原生成功和外层持物证据冲突时并列报告与核查，不改评分器。

## 14. 版本、证据、文件与运行边界

### 14.1 每次运行的外层manifest建议

保存：commit及dirty diff、condition ID、run/episode ID、任务/布局（外层私有）、分集、真实模型与账号来源标签（不存key）、端点、完整prompt/question/plan/processor/Skill哈希、输入权限、历史开关、动作参数、native版本/horizon、API/动作预算、资源准入、媒体策略、状态与停止原因。

每次请求保存：实际prompt与状态、原图及实际送模型图的内容哈希/允许位置、字段来源、原始返回、提取值、解码目标、动作前后实测、native步、传输回执。请求或回执缺失明确标unknown，不能根据文件编号猜测交付成功。

版本保存不等于复制整个campaign。文本足以重建请求结构；图像保存原图和实际模型图并以哈希引用，不重复保存大量base64历史。当前用户要求保留的媒体不清理，后续保留策略另行明确；不拿旧终局清理要求覆盖最新保留指令。

### 14.2 已授权资产位置（复制时每个路径独立一行）

本机工作树：

```text
/home/ykj/project/gpt6/CVPR/jev-rsi/jev-RSI/.worktrees/robodojo-review-site-20261013
```

本机已有抓取资产：

```text
/home/ykj/project/gpt6/benchmark/gpt_as_policy_robodojo/runs/server02-decision-grasp-20261020
```

server02已有远端资产：

```text
/home/user/ykj/project/gpt6/jev-RSI/code/runs/server02-decision-grasp-20261019
```

本机自有SSH控制socket：

```text
/home/ykj/.ssh/s2-comparison-20261019d.ctl
```

不向其他挂载盘写大文件；新运行目录必须在授权资产同挂载盘下，不能自动转去company-server-2或早期/data路径。现有socket/远端资产不能证明进程存在或授权重启。

### 14.3 恢复实验前的必要状态

- 用户明确恢复；本次只写方案不满足此项。建议规划器沿用历史显式Sol6.1 high，但Pro实际配置必须在启动时核实，不借用早期Responses客户端；推进器保持真正Decisions。
- 核对真实PID、systemd服务、容器、在途curl与native步骤，不能仅看status。
- 当前传输阻塞有可用路线信息或授权的处理方案；不改共享代理、不另发OpenAI探测。
- GPU0/1及最多总3环境限制；初始单环境，启动空闲显存>=8GiB、可用RAM>=20GiB；本机磁盘至少过既有8GiB门并有本批产物余量。
- 不动外人进程/驱动/Conda权限，不写/tmp，不读旧experience。
- 全部源/模型可读知识在条件运行期间冻结。用户暂停优先于等待批次完成。
- 不恢复旧episode，不重发失败/未知请求，不把修复调度当任务性能改善。基础设施再中断先停派发与离线诊断，不无限补槽。

## 15. 后续实现应改哪里：本轮未实施

| 模块 | 现有位置 | 将来最小变更 |
|---|---|---|
| 当前输入允许集/字段来源 | `../decision_grasp/controller.py` | 命令与测量命名核实；当前观测绑定；命名条件附加信息 |
| 当前通用提示 | `../decision_grasp/advancer_v1.md`、`advancer_alignment_v2.md` | 不直接覆盖；保存新版本及具体改动原因 |
| 七选一编码 | `../decision_grasp/joint_rotation.py` | 继续用于现有十问；分阶段6问另列提议 |
| 机器人候选表与投影 | `../decision_grasp/rotation_effects.py`、`camera_overlay.py` | 验证其信息边界和当前图一致性，按条件选用 |
| 端点/动作/传输 | `../policy_comparison/decisions_policy.py` | 不换端点/凭据；新分阶段适配单独实现，保原始回答 |
| 派发与停止 | `../decision_grasp/run.py` | 维持STOP与DISPATCH_STOP分离，暂停守卫与有限队列 |
| 规划器及阶段接线 | 目前是 `code/contracts/` 草案 | 新建独立受限适配，不恢复旧任务专用controller |
| Skill/Lesson保存 | 当前未实施新库 | 仅在后续实施条件下建立英文版本与证据清单，不迁入旧experience |

历史合同索引：

- `framework_decisions.md`：2026-10-17/19拍板。
- `planner_prompt.draft.md`：开放式处理职责、最终JSON与另行验证。
- `advancer_baseline.draft.md`：单臂八问、advance语义、夹爪待定项。
- `tcp_action_interface.draft.md`：已核实world轴/TCP动作说明。
- `planner_processing_references.md`：观测到附加信息的参考摘录，不直接移植旧任务路线/阈值。
- `planner_processing_compact.md`、`planner_processing_progressive.md`：历史候选指导方式，不能同时拼入形成重复冲突指令。
- `optional_perception_tools.md`：历史可用工具说明，新位置需重新核实，不是已准备好的当前处理流程。
- `../../IMPROVEMENTS.md`：历史/控臂/问题表达/开放处理/重规划/步长候选。
- `../../ref/notes/idea-draft-v0.1.md` 与会议笔记：早期研究口径仅作历史；当前末端XYZ/YPR口径以idea/method后续纠正为准。固定步长振荡、测量误差与成本区分仍提醒我们不要把局部行为解释成完整任务保证。

## 16. 参考依据及本次审阅点

### 16.1 EmbodiedEvo中直接借鉴的规范

核查日期2026-10-22。以下是官方源码/论文来源，不表示我们已经复制其实现或运行其系统：

- [Playground指令](https://github.com/Einsia/EmbodiedEvo/blob/main/tasks/RoboDojo/Workspace/playground.md)：按反馈增量修订，有用知识及时记录，场景细节与复用知识分离。
- [Skill模板](https://github.com/Einsia/EmbodiedEvo/blob/main/tasks/RoboDojo/Workspace/skills/example.md)：参数、前置条件、边界、执行证据；我们将其转换为阶段/证据合同，不生成机器人动作代码。
- [Lesson模板](https://github.com/Einsia/EmbodiedEvo/blob/main/tasks/RoboDojo/Workspace/lessons/example.md)：现象/替代做法/证据/状态，开发验证不等于迁移。
- [文件变更记录](https://github.com/Einsia/EmbodiedEvo/blob/main/orchestrator/files.py)：保存修改和哈希，不负责证明经验正确。
- [评估协议](https://github.com/Einsia/EmbodiedEvo/blob/main/docs/PROTOCOL.md)：冻结知识、测试隔离、保留失败。我们不照搬其开发reset权限。
- [论文v1](https://arxiv.org/html/2610.18867v1)：使用前提、分阶段过程、持物验证和失败迁移反例；选例不能证明一条规则单独产生收益。

### 16.2 本次建议的核心与尚未采用项

**建议初始采用**：已有动作/账号/观测边界；先离线诊断；每项修改绑定首个失败环节；有限开发批次；英文证据型Lesson/Skill规范；经验记录与经验注入分条件；稳定推进器后再接一次性Pro规划器；独立native终局。

**需要实施前定稿的新增细节**：本文具体JSON键名/Schema，夹爪命令与实测字段拆分，八问适配、64调用预算/5次空转停止建议，Skill开发升级门及模型片段筛选上限。文档中有完整建议，不把它们标成用户已拍板。

**保持后置**：历史、重规划、动态步长、控臂所有权变化、分阶段6问、额外Jev/无图比较、新baseline、任务扩展。未来选择后各自命名与验证，不一并接入初版。

**CIRCLE-1收敛方式**：不以条件数、EXP编号、rotation/close频次衡量进展；下一个有效结论必须能回答某个可观察环节是否改善、为什么仍未成功、或为何现有信息不足。没有支持证据时保留失败并停止添加同义提示。

本文件交付的是可审阅的设计基线；下一步仍是暂停状态下的D0证据审查。后续恢复原生实验必须以用户新的恢复指令为准。

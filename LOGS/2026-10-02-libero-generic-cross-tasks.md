# 同一通用流程跨任务冻结验证（2026-10-02）

**9回合总1/9成功：Spatial盘旁碗1/3、Object奶酪0/3、Object汤罐0/3。**

冻结当前通用语义识别+SAM/RGB-D+Jev方向+抓前复核+放置前复测，未增加类别/颜色/任务专用抓取规则。仅新增--suite参数，以原样接入Object套件。每任务初态1/2/3各1次，seed0，无重试或中途调参。Spatial任务此前用于其他版本开发，Object两任务本轮未预调；不称整个LIBERO-Plus评测。

代码fb7f069，manifest及frozen保存源码SHA256。三个任务按用户单物体抓放范围预先选定；并非根据成功率事后筛选。每项跑完3回合停止，没有失败后扩大或替换。

| 任务 | suite/id | 成功 | 失败阶段 |
|---|---|---:|---|
| 盘旁黑碗放盘子 | libero_spatial/1282 | 1/3 | 两次carry后源物体重新关联不一致 |
| 奶油奶酪入篮 | libero_object/1066 | 0/3 | 三次descend_recovery停滞 |
| 字母汤罐入篮 | libero_object/1043 | 0/3 | 两次终局false，一次carry后深度异常 |

总588Jev、21次GPT-6视觉识别、1908原生步、2064.84秒（34.4分钟）；DeepSeek0。GPT仅返回视觉物体框/身份，仍为最多开局/预抓取/停滞各1次；Jev选方向，外部规则生成抓点/阶段/幅度。没有系统或环境安装变更。

## 已知失败证据

1. 盘旁碗的前两回合已经抓起并搬运。放置前外部相机分割的源物体中心偏离预测超过65mm，于是停止。只能认定关联检查失败，不能单凭报错断言实际物体位移65mm。第三回合官方成功。
2. 奶酪三个回合下降均受阻。init1最后目标z=17.849mm，实际z=42.245mm；要求z增量-12.191mm，但实际仅约+0.013mm。外部图像显示末端贴近低矮包装物。可能是抓点/夹爪接触与工作空间问题，未记录碰撞对或接触力，根因尚待独立诊断。
3. 汤罐init1/2最终官方false，不能因为画面看似在篮内就算成功。init1接收物的可见高度范围约11.8–140.8mm，当前通用放置按高分位表面生成释放高度，不区分容器内底和外边缘；这是流程的潜在局限，不是本次已证明的唯一根因。init3重新分割源物体得到超过35cm的范围，守卫拒绝；属于视觉关联问题。

此前碗专用版盘旁3/3、旧单任务20次80%、通用桌中央3/3均不能替代本轮结果。当前代码可跨类别执行，但不能声称通用成功率已稳定。

## 逐回合

| suite/task | init | success | Jev | GPT视觉 | steps | 秒 |
|---|---:|---|---:|---:|---:|---:|
| libero_spatial/1282 | 1 | False | 59 | 2 | 193 | 201.16 |
| libero_spatial/1282 | 2 | False | 58 | 2 | 190 | 194.88 |
| libero_spatial/1282 | 3 | True | 79 | 2 | 269 | 210.67 |
| libero_object/1066 | 1 | False | 54 | 3 | 162 | 257.85 |
| libero_object/1066 | 2 | False | 48 | 3 | 144 | 255.14 |
| libero_object/1066 | 3 | False | 48 | 3 | 144 | 261.09 |
| libero_object/1043 | 1 | False | 88 | 2 | 296 | 240.36 |
| libero_object/1043 | 2 | False | 88 | 2 | 296 | 202.43 |
| libero_object/1043 | 3 | False | 66 | 2 | 214 | 241.27 |

## 复现与留存

以下逐行执行，最后一行完整命令不用换行；输出目录必须不存在。已按同样启动方式跑满9回合。

```bash
cd /root/yekangjie/project/jev_rsi
/root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python -B code/scripts/run_libero_generic_cross_tasks.py code/runs/NEW-generic-cross-tasks
```

原始产物code/runs/2026-10-02-libero-generic-cross-tasks：manifest/frozen/batch、语义请求响应、SAM掩码、深度、标定、Jev、动作、双视角帧与原生result。3583个清单文件两端SHA256一致。测试进程已正常结束，无后台实验继续。

下一步应分别诊断低矮物体抓取、容器接收表面和抓后关联，避免继续按类别补硬编码。本轮封版；两项连续三次未完成，不追加物理重试。当前主线CIRCLE-1仍存在，有限跨任务验证提供失败范围而非新增泛化主张。

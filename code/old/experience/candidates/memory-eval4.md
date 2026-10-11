# 回合事实总结（待审核，不自动激活）

```json
{
  "id": "memory-eval4",
  "status": "candidate",
  "stages": [
    "approach",
    "close",
    "contact",
    "lift",
    "select"
  ],
  "kinds": [
    "pick_lift"
  ],
  "parameters": {},
  "evidence": [
    "code/runs/memory-eval4-0",
    "code/runs/memory-eval4-1",
    "code/runs/memory-eval4-2",
    "code/runs/memory-eval4-3"
  ]
}
```

本文件只汇总观测到的结果，不根据单次成败推断因果，不写入布局坐标或真值对象答案。
审核时区分感知、身份关联、执行、物理抓取和验证失败；只有跨回合证据支持的经验才可更新共享记忆。

## memory-eval4-0
- 原生成功：True；步数：127；Jev：22
- 实际阶段：approach → contact → close → lift
- 终止事实：native_episode_ended
- 结果SHA256：c5a815435be85c692cefd82a3ba6e5e613071bc6be3034ab1937561d9ea03979

## memory-eval4-1
- 原生成功：True；步数：160；Jev：30
- 实际阶段：approach → contact → close → lift
- 终止事实：native_episode_ended
- 结果SHA256：3716f7af5c65addb2311c59c00a45321cdb1de3f8735be6ae288af32f073af0d

## memory-eval4-2
- 原生成功：False；步数：2；Jev：0
- 实际阶段：select
- 终止事实：controller_stop:unrecoverable observation ambiguity: instruction does not uniquely identify visible candidates
- 结果SHA256：78a010b0737927bc1616139a72a77aa013dd826898c62b562510fb77ed112caf

## memory-eval4-3
- 原生成功：True；步数：161；Jev：29
- 实际阶段：approach → contact → close → lift → contact → close → lift
- 终止事实：native_episode_ended
- 结果SHA256：5d304f2f7dffd158d36362570d81206480d67fa397365bd24fabeeee8618c0cd


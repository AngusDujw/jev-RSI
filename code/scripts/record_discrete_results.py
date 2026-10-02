"""Append completed joint-decision episodes to protocol logs; never alter prior EXP."""
import json,re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[2]
ledger_path=ROOT/'LOGS/jev-discrete-ledger.json'
ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
y,w,_=datetime.now(ZoneInfo('Asia/Shanghai')).isocalendar()
weekly=ROOT/f'LOGS/{y}-W{w:02}.md'
number=max(map(int,re.findall(rf'^### EXP-{y}W{w:02}-(\d+)',weekly.read_text(),re.M)),default=0)+1
for folder in sorted((ROOT/'code/runs').glob('jev-discrete-*-??')):
    if folder.name in ledger or not (folder/'summary.json').exists():continue
    def read(name):
        p=folder/name;return json.loads(p.read_text()) if p.exists() else {}
    result=read('structured_result.json');summary=read('summary.json');cfg=read('protocol.json');prov=read('provenance.json')
    native=result.get('native',{}).get('success');requests=list(folder.glob('decision-*/request.json'));responses=list(folder.glob('decision-*/response.json'))
    phase_counts={};gripper_counts={};stages=[];owners=set();permission=[]
    forbidden={'object_true_position','ground_truth_position','oracle_error','segmentation_id','reward','native_success','object_poses'}
    def scan(v,path=''):
        if isinstance(v,dict):
            for k,x in v.items():
                if k in forbidden:permission.append(path+'.'+k)
                scan(x,path+'.'+k)
        elif isinstance(v,list):
            for i,x in enumerate(v):scan(x,path+f'[{i}]')
    for p in requests:scan(json.loads(p.read_text())['state'])
    for p in responses:
        for key,a in json.loads(p.read_text()).get('answers',{}).items():
            target=phase_counts if key=='phase' else gripper_counts if key.endswith('_gripper') else None
            if target is not None:target[a['choice']]=target.get(a['choice'],0)+1
    for p in sorted(folder.glob('frame-*/command.json')):
        c=json.loads(p.read_text());stages.append(c['stage'])
        for e in c.get('debug',{}).get('state_transitions',[]):owners.add(e['owner'])
    eid=f'EXP-{y}W{w:02}-{number:03}';number+=1
    reason=result.get('status',str(summary.get('errors',summary.get('status'))))
    row=dict(experiment_id=eid,task=cfg['runtime_task'],attempt=int(folder.name[-2:]),variant=cfg.get('controller_settings'),layout=cfg['robodojo_layout_id'],
        frozen_reference=cfg.get('frozen_reference'),native_success=native,reason=reason,steps=result.get('steps',0),jev_requests=len(requests),jev_responses=len(responses),
        phase_choices=phase_counts,gripper_choices=gripper_counts,transition_owners=sorted(owners),forbidden_field_hits=permission,
        stages=list(dict.fromkeys(stages)),wall_seconds=summary['wall_seconds'],commit=prov['commit'],run=str(folder.relative_to(ROOT)),command=prov['command'])
    ledger[folder.name]=row
    block=f'''\n\n### {eid}\n\n- 源意图 (Original Vibe): 每任务最多50次；Jev决定XYZ方向、夹爪开合和阶段，比较非特权视觉处理/输入。
- 假设 (Hypothesis): {row['variant']}输入可支持{row['task']}联合离散决策闭环。
- 是否被驳斥 (Falsified?): {'N' if native is True else 'Crashed' if not result or 'error' in reason or 'exception' in reason else 'Y'}
- 驳斥/支持原因 (Why): {reason}；原生success={native}；None表示未取得评估，不能算成功。
- Agent 动作 (What changed): 本轮第{row['attempt']}次{'冻结验证' if row['frozen_reference'] else '开发'}；候选目标/姿态/幅度由算法提供，Jev独立选择阶段与夹爪；完整版本快照保留。
- 复现信息 (Repro):
  - commit: {row['commit']}
  - seed: layout={row['layout']}/eval_seed0
  - dataset / version: RoboDojo既有官方资产；实际Jev模型见response.json
  - env: 既有robodojo-isaac51 Python3.11/Isaac5.1；本地GroundingDINO/SAM2/OCR；未改驱动
  - hardware: company-server-2 GPU{cfg['gpu']}
  - command: `{' '.join(row['command'])}`
- 关键指标 (Metrics): native={native}；steps={row['steps']}；Jev请求/响应={len(requests)}/{len(responses)}；{row['wall_seconds']:.2f}s；阶段选择={phase_counts}；夹爪={gripper_counts}；阶段owner={sorted(owners)}；禁止字段命中={permission}。GPT-6/DeepSeek闭环0。
- 日志路径 (Artifacts): {row['run']}；[总账](jev-discrete-ledger.json)；配置、RGB-D、Jev、动作、独立审计和原生结果。
- 结论 (Conclusion, 1–3 句): {'该开发回合完成，需冻结验证；不宣称稳定成功率。' if native is True else '该回合未取得成功；保留失败，结合阶段/感知证据修正。'} 字段扫描仅是辅助检查，不等价于信息来源证明。
- 下一步 (Next): 依据具体失败比较输入/处理或冻结成功候选；每任务50次硬上限，原生评估不回流在线策略。
- 关联议题 (Discussion): DISC-2026W39-001
'''
    with weekly.open('a') as f:f.write(block)
ledger_path.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n')
lines=['# Jev夹爪/阶段联合决策开发记录','','开发混版本，不能作为最终冻结成功率。GPU/接口失败也计入每任务50次预算。','', '|任务|尝试|用途|输入/处理|布局|原生成功|步数|Jev请求/响应|终止原因|','|---|---:|---|---|---:|---|---:|---:|---|']
for r in ledger.values():lines.append(f"|{r['task']}|{r['attempt']}|{'冻结验证' if r.get('frozen_reference') else '开发'}|{r['variant']}|{r['layout']}|{r['native_success']}|{r['steps']}|{r['jev_requests']}/{r['jev_responses']}|{r['reason']}|")
(ROOT/'LOGS/jev-discrete-results.md').write_text('\n'.join(lines)+'\n')
print('archived',len(ledger),'completed trials')

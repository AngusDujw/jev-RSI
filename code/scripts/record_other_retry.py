"""Archive completed retry episodes; no simulator/model calls and no trial deletion."""
import json,re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

root=Path(__file__).resolve().parents[2]
ledger_path=root/'LOGS/other-retry-ledger.json'
ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
year,week,_=datetime.now(ZoneInfo('Asia/Shanghai')).isocalendar()
weekly=root/f'LOGS/{year}-W{week:02d}.md'; text=weekly.read_text()
number=max(map(int,re.findall(rf'^### EXP-{year}W{week:02d}-(\d+)',text,re.M)))+1
for folder in sorted((root/'code/runs').glob('other-retry-*-??')):
    key=folder.name
    if key in ledger or not (folder/'summary.json').exists(): continue
    summary=json.loads((folder/'summary.json').read_text());cfg=json.loads((folder/'protocol.json').read_text());prov=json.loads((folder/'provenance.json').read_text())
    result=json.loads((folder/'structured_result.json').read_text()) if (folder/'structured_result.json').exists() else {}
    failure=json.loads((folder/'failure.json').read_text()) if (folder/'failure.json').exists() else {}
    native=result.get('native',{}).get('success');success=native is True
    reason=result.get('status',failure.get('error',summary['status']))
    commands=[json.loads(p.read_text()) for p in sorted(folder.glob('frame-*/command.json'))]
    stages=list(dict.fromkeys(c['stage'] for c in commands))
    eid=f'EXP-{year}W{week:02d}-{number:03d}';number+=1
    row=dict(experiment_id=eid,task=cfg['runtime_task'],attempt=int(key[-2:]),success=success,native_success=native,
        reason=reason,run=str(folder.relative_to(root)),commit=prov['commit'],steps=result.get('steps'),
        actions=result.get('actions'),jev_calls=result.get('jev_calls',summary['decisions']),vision_calls=result.get('vision_calls'),
        wall_seconds=summary['wall_seconds'],stages=stages,command=prov['command'])
    ledger[key]=row
    block=f'''\n\n### {eid}\n\n- 源意图 (Original Vibe): 用户授权其余三个任务各最多新增10次，逐轮修正，看哪个能取得原生成功。\n- 假设 (Hypothesis): 共享多视角/机器人自遮挡处理、姿态与接触参考以及任务经验可完成{row['task']}。\n- 是否被驳斥 (Falsified?): {'N' if success else 'Crashed'}\n- 驳斥/支持原因 (Why): {reason}；native success={native}（None表示评估不可用，仍计入开发失败）。\n- Agent 动作 (What changed): 本任务新增第{row['attempt']}回合；版本与经验快照按本回合保存，不替换失败。原生成败与步数限制未改。\n- 复现信息 (Repro):\n  - commit: {row['commit']}；详情见generated_provenance/experience_snapshot。\n  - seed: layout{cfg['robodojo_layout_id']}/eval_seed0，开发重复布局。\n  - dataset / version: RoboDojo {row['task']}官方既有资产；Jev实际版本见响应，本地GroundingDINO/SAM2。\n  - env: 既有robodojo-isaac51 Python3.11.15/Isaac5.1，未改驱动和依赖。\n  - hardware: company-server-2 GPU{cfg['gpu']}。\n  - command: `{' '.join(row['command'])}`\n- 关键指标 (Metrics): 原生成功={native}；步骤={row['steps']}、动作={row['actions']}、Jev={row['jev_calls']}、本地视觉={row['vision_calls']}、{row['wall_seconds']:.2f}秒。阶段：{stages}。GPT-6/DeepSeek运行时0。\n- 日志路径 (Artifacts): {row['run']}（本地与服务器）；完整图像/深度/命令/Jev/经验/隔离审计/原生结果；[总账](other-retry-ledger.json)。\n- 结论 (Conclusion, 1–3 句): {'取得本开发回合原生成功，仍需固定版本确认，不能称稳定成功率。' if success else '该版本未完成，负结果保留；未宣称经验收益或正式成功率。'}\n- 下一步 (Next): {'冻结成功方案并在剩余预算内确认。' if success else '按具体失败证据迭代，在每任务最多10次预算内继续，达到上限停止。'}\n- 关联议题 (Discussion): DISC-2026W39-001\n'''
    with weekly.open('a') as f:f.write(block)
ledger_path.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n')
print('Archived completed runs:',len(ledger))

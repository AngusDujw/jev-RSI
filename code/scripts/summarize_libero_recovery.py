"""Summarize bounded optimization and append complete, non-replacing EXP records."""
import argparse
import fcntl
import json
from pathlib import Path
import re
import subprocess

p=argparse.ArgumentParser();p.add_argument('--prefix',default='2026-10-03-libero-recovery30-');p.add_argument('--output',required=True,type=Path);p.add_argument('--write-protocol',action='store_true');a=p.parse_args()
repo=Path(__file__).resolve().parents[2]
rows=[]
for root in sorted((repo/'code/runs').glob(a.prefix+'*')):
 if not (root/'batch.json').exists():continue
 manifest=json.loads((root/'manifest.json').read_text())
 for row in json.loads((root/'batch.json').read_text()):
  run=root/f'{row["suite"]}-{row["task"]}-init-{row["init"]}'
  ds=[json.loads(x) for x in (run/'decisions.jsonl').read_text().splitlines()] if (run/'decisions.jsonl').exists() else []
  good=sum(sum(d.get('metrics',{}).get('axis_correct',[])) for d in ds)
  axes=sum(len(d.get('metrics',{}).get('axis_correct',[])) for d in ds)
  row.update(path=str(run.relative_to(repo)),batch=root.name,commit=manifest['commit'],options=manifest['options'],axis_correct=good,axes_evaluated=axes,models=sorted(set(d.get('model','unreturned') for d in ds)))
  rows.append(row)
rows.sort(key=lambda x:x['campaign_attempt'])
assert len(set(r['campaign_attempt'] for r in rows))==len(rows)
assert len(rows)<=30
summary=dict(episodes=len(rows),native_successes=sum(r['result']['success'] for r in rows),complete_successes=sum(r['result']['success'] and r['result'].get('program_finished',False) for r in rows),jev_calls=sum(r['result'].get('jev_calls',0) for r in rows),visual_calls=sum(r['result'].get('semantic_calls',0) for r in rows),native_steps=sum(r['result'].get('native_steps',0) for r in rows),seconds=sum(r['seconds'] for r in rows),rows=rows)
a.output.mkdir(parents=True,exist_ok=True)
(a.output/'campaign.json').write_text(json.dumps(summary,indent=2)+'\n')
ids={}
if a.write_protocol:
 week=repo/'LOGS/2026-W40.md'
 with week.open('a+') as f:
  fcntl.flock(f,fcntl.LOCK_EX);f.seek(0);text=f.read()
  for r in rows:
   marker=f'recovery30-attempt:{r["campaign_attempt"]}'
   if marker in text:
    block=next(b for b in re.split(r'(?=^### EXP-)',text,flags=re.M) if marker in b)
    ids[str(r['campaign_attempt'])]=re.search(r'EXP-2026W40-\d{3}',block).group();continue
   number=max([int(x) for x in re.findall(r'^### EXP-2026W40-(\d{3})',text,re.M)]+[0])+1
   eid=f'EXP-2026W40-{number:03d}';ids[str(r['campaign_attempt'])]=eid
   result=r['result'];error=result.get('error')
   falsified='N' if result['success'] and result.get('program_finished') else 'Crashed' if error and ('matmul' in error or 'broadcast' in error or error=='Setup/no result') else 'Y'
   opts=r['options'];flags=f'--input-organization {opts["input_organization"]} --grasp-algorithm {opts["grasp_algorithm"]} --contact-angle-deg {opts["contact_angle_deg"]} --pad-overlap-mm {opts["pad_overlap_mm"]} --table-margin-mm {opts["table_margin_mm"]} --max-jev-decisions {opts["max_jev_decisions"]}'
   if opts['preserve_source']:flags+=' --preserve-source'
   if opts['allow_retry']:flags+=' --allow-retry'
   command=f'/root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python -B code/scripts/run_libero_recovery_batch.py {flags} --tasks {r["suite"]}:{r["task"]} --inits {r["init"]} --output code/runs/NEW-{r["batch"]}'
   block=f'''\n\n### {eid}\n\n- 源意图 (Original Vibe): 最多30次继续优化可见抓取算法与Jev输入/输出组织；{marker}。\n- 假设 (Hypothesis): {r['batch']}的几何候选与{opts['input_organization']}输入能让Jev自主选择夹爪、候选及阶段并完成任务。\n- 是否被驳斥 (Falsified?): {falsified}\n- 驳斥/支持原因 (Why): native_success={result['success']}，program_finished={result.get('program_finished',False)}；终止原因={error or '正常完成'}。不把预算终止当物理根因。\n- Agent 动作 (What changed): 按manifest冻结源码与配置运行；新回合#{r['campaign_attempt']}、该任务累计#{r['attempt']}，所有setup失败及物理失败均保留，计数不重置。\n- 复现信息 (Repro):\n  - commit: {r['commit']}\n  - seed: 0\n  - dataset / version: LIBERO-Plus {r['suite']}/task{r['task']} 官方init{r['init']}；实际Jev版本{','.join(r['models']) or '未调用'}；视觉gpt-6-astra，最多3次。\n  - env: Python3.10 / MuJoCo2.3.7 / Robosuite1.4.0 / NumPy1.26.4；现有项目venv，无依赖或驱动改动。\n  - hardware: company-server-2，RTX4090 GPU0 EGL、GPU1分割；Jev为远程API。\n  - command: `{command}`\n- 关键指标 (Metrics): {result.get('jev_calls',0)} Jev、{result.get('semantic_calls',0)}视觉、{result.get('native_steps',0)}正式原生步、{r['seconds']:.2f}秒；方向轴正确{r['axis_correct']}/{r['axes_evaluated']}，不含未请求旋转；初始化10步单列。\n- 日志路径 (Artifacts): {r['path']}；code/runs/{r['batch']}/manifest.json；LOGS/2026-10-03-libero-recovery30.md。\n- 结论 (Conclusion, 1–3 句): 本次结果仅支持该冻结候选及初态的判断。策略只用公开语言、可见RGB-D和机器人自身反馈/几何，native success仅终局评价；重复开发初态不能称独立测试。\n- 下一步 (Next): 根据该回合可见证据决定下一候选；达到完整成功后固定版本测新初态；新增总数最多30。\n- 关联议题 (Discussion): DISC-2026W39-001\n'''
   f.write(block);f.flush();text+=block
 (a.output/'exp-ids.json').write_text(json.dumps(ids,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k!='rows'}))
for r in rows:print(r['campaign_attempt'],r['batch'],r['init'],r['result']['success'],r['result'].get('error'),f"axes {r['axis_correct']}/{r['axes_evaluated']}")

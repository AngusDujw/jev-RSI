"""Include completed episode results even when the parent batch was interrupted.

Infrastructure failures stay in the attempts/EXP ledger and are explicitly
separate from physical outcomes; no imputation of a missing return code.
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
from pathlib import Path
import re
from libero_failure import classify


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('roots', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--write-protocol', action='store_true')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    rows = []
    for root in args.roots:
        root = root.resolve()
        manifest = json.loads((root/'manifest.json').read_text())
        for name, expected in manifest['source_sha256'].items():
            assert hashlib.sha256((root/'frozen'/name).read_bytes()).hexdigest() == expected
        ledger = repo/'code/runs'/f'{manifest["campaign"]}-ledger.jsonl'
        reservations = {Path(r['output']).name: r for r in
            (json.loads(line) for line in ledger.read_text().splitlines())}
        batch = {Path(r['output']).name: r for r in
            json.loads((root/'batch.json').read_text())} if (root/'batch.json').exists() else {}
        for path in sorted(root.glob('*/result.json')):
            episode = path.parent
            result = json.loads(path.read_text())
            reserve = reservations[episode.name]
            summary = json.loads((episode/'summary.json').read_text())
            events = [json.loads(s) for s in (episode/'events.jsonl').read_text().splitlines()
                if s.strip()]
            batch_row = batch.get(episode.name, {})
            category = classify(result, batch_row, events)
            rows.append(dict(reserve, path=str(episode.relative_to(repo)),
                result=result, category=category, commit=manifest['commit'],
                purpose=manifest.get('purpose', 'evaluation'),
                transport=manifest.get('transport', {}),
                runner_termination=batch_row.get('runner_termination'),
                batch_row_present=episode.name in batch,
                returncode=batch.get(episode.name, {}).get('returncode'),
                policy_wall_seconds=summary['wall_seconds']))
    assert len({r['path'] for r in rows}) == len(rows)
    report = dict(reservations_with_result=len(rows),
        infrastructure_failures=sum(r['category']=='infrastructure' for r in rows),
        interrupted_episodes=sum(r['category']=='interrupted' for r in rows),
        physical_or_policy_episodes=sum(r['category']=='physical_or_policy' for r in rows),
        complete_successes=sum(r['result']['success'] and
            r['result'].get('program_finished', False) for r in rows),
        native_steps=sum(r['result'].get('native_steps', 0) for r in rows),
        jev_calls=sum(r['result'].get('jev_calls', 0) for r in rows), rows=rows)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'campaign.json').write_text(json.dumps(report, indent=2)+'\n')
    ids = {}
    if args.write_protocol:
        today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
        year, week, _ = today.isocalendar()
        week_id = f'{year}-W{week:02d}'
        id_prefix = f'EXP-{year}W{week:02d}-'
        log = repo/'LOGS'/f'{week_id}.md'
        with log.open('a+') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX); stream.seek(0); text = stream.read()
            for row in rows:
                marker = 'validation-episode:'+row['path']
                if marker in text:
                    block = next(b for b in re.split(r'(?=^### EXP-)',text,flags=re.M) if marker in b)
                    ids[row['path']] = re.search(id_prefix+r'\d{3}', block).group()
                    continue
                number = max([int(x) for x in re.findall(r'^### '+id_prefix+r'(\d{3})', text, re.M)]+[0])+1
                eid = id_prefix+f'{number:03d}'; ids[row['path']] = eid
                result = row['result']; good = result['success'] and result.get('program_finished',False)
                falsified = 'Crashed' if row['category'] in ('infrastructure','interrupted') else 'N' if good else 'Y'
                root = str(Path(row['path']).parent)
                command = f'{SIM_PYTHON} -B code/scripts/run_libero_frozen_validation.py --frozen-from {root}/frozen --inits {row["init"]} --tasks {row["suite"]}:{row["task"]} --campaign 2026-10-04-libero-verify20-repro-{row["task"]}-{row["init"]} --output code/runs/2026-10-04-libero-verify20-repro-{row["task"]}-{row["init"]}'
                for role in ['jev', 'vision']:
                    if row['transport'].get(role+'_proxy'):
                        command += ' --'+role+'-proxy '+row['transport'][role+'_proxy']
                command += ' --purpose '+row['purpose']
                conclusion = ('本回合native与program均完成；它是冻结系统的一次结果，不能单独证明总体成功率。' if good
                    else '基础设施断连保留为Crashed，不作为控制算法失败率；没有隐去或重跑。' if row['category']=='infrastructure'
                    else '为停止故障队列而中断，保留Crashed与实际退出码，不把未结束控制归为算法失败。' if row['category']=='interrupted'
                    else '完整任务未成功，按负结果保留；需要依据可见证据分析控制或感知原因。')
                block = f'''

### {eid}

- 源意图 (Original Vibe): 冻结系统验证与五任务对应；{marker}；purpose={row['purpose']}。
- 假设 (Hypothesis): 冻结策略在声明的官方初态可完成任务，基础设施可用，Jev保持夹爪与阶段所有权。
- 是否被驳斥 (Falsified?): {falsified}
- 驳斥/支持原因 (Why): native_success={result['success']}，program_finished={result.get('program_finished',False)}，error={result.get('error')}；类别={row['category']}；runner_termination={row['runner_termination']}。
- Agent 动作 (What changed): 保持全部策略源码SHA与配置；保存原始请求/结果和累计attempt={row['attempt']}。缺失父批returncode保留null，基础设施及人工中断单列。
- 复现信息 (Repro):
  - commit: {row['commit']}
  - seed: 0
  - dataset / version: LIBERO-Plus {row['suite']}/task{row['task']}，官方init{row['init']}，purpose={row['purpose']}。
  - env: Python3.10 / MuJoCo2.3.7 / Robosuite1.4.0，现有venv；未改依赖或驱动。
  - hardware: company-server-2，RTX4090 GPU0 EGL、GPU1分割；模型远程API。
  - command: `{command}`
- 关键指标 (Metrics): Jev请求尝试={result.get('jev_calls',0)}，正式原生步={result.get('native_steps',0)}，语义请求尝试={result.get('semantic_calls',0)}，策略墙时={row['policy_wall_seconds']:.2f}s；DeepSeek={result.get('deepseek_calls',0)}；实际exit={row['returncode']}。初始化10步单列，失败请求不假定已收到响应或免费。
- 日志路径 (Artifacts): {row['path']}；{root}/manifest.json；LOGS/2026-10-05-libero-resumed.md。
- 结论 (Conclusion, 1–3 句): {conclusion}
- 下一步 (Next): 首个基础设施错误停止队列；连续3次Crashed按AGENTS§10升级。修复/验证链路并获恢复授权后，在原任务预算内继续，不重置或重跑失败。
- 关联议题 (Discussion): DISC-2026W39-001
'''
                stream.write(block); stream.flush(); text += block
        (args.output/'exp-ids.json').write_text(json.dumps(ids, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'}))


SIM_PYTHON = '/root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python'
if __name__ == '__main__':
    main()

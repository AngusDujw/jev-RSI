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
            network = any(s in str(result.get('error', '')) for s in
                ['Name or service not known', 'Temporary failure in name resolution',
                 'Connection refused', 'Network is unreachable'])
            category = 'infrastructure' if network else 'physical_or_policy'
            rows.append(dict(reserve, path=str(episode.relative_to(repo)),
                result=result, category=category, commit=manifest['commit'],
                batch_row_present=episode.name in batch,
                returncode=batch.get(episode.name, {}).get('returncode'),
                policy_wall_seconds=summary['wall_seconds']))
    assert len({r['path'] for r in rows}) == len(rows)
    report = dict(reservations_with_result=len(rows),
        infrastructure_failures=sum(r['category']=='infrastructure' for r in rows),
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
                falsified = 'Crashed' if row['category']=='infrastructure' else 'N' if good else 'Y'
                root = str(Path(row['path']).parent)
                command = f'{SIM_PYTHON} -B code/scripts/run_libero_frozen_validation.py --frozen-from {root}/frozen --inits {row["init"]} --tasks {row["suite"]}:{row["task"]} --campaign 2026-10-04-libero-verify20-repro-{row["task"]}-{row["init"]} --output code/runs/2026-10-04-libero-verify20-repro-{row["task"]}-{row["init"]}'
                block = f'''\n\n### {eid}\n\n- 源意图 (Original Vibe): 冻结奶酪配置检验20新初态并扩展五个高成功任务族；{marker}。\n- 假设 (Hypothesis): 冻结策略在未参与开发的官方初态可完成任务，且基础设施可用。\n- 是否被驳斥 (Falsified?): {falsified}\n- 驳斥/支持原因 (Why): native_success={result['success']}，program_finished={result.get('program_finished',False)}，error={result.get('error')}；类别={row['category']}。0控制步的DNS故障不能估计物理任务成功率。\n- Agent 动作 (What changed): 保持全部策略源码SHA与配置；保存原始请求/结果和累计attempt={row['attempt']}。中断父批未写入的最后结果另行汇总，缺失returncode保留null。\n- 复现信息 (Repro):\n  - commit: {row['commit']}\n  - seed: 0\n  - dataset / version: LIBERO-Plus {row['suite']}/task{row['task']}，官方init{row['init']}。\n  - env: Python3.10 / MuJoCo2.3.7 / Robosuite1.4.0，现有venv；未改依赖或驱动。\n  - hardware: company-server-2，RTX4090 GPU0 EGL、GPU1分割；模型远程API。\n  - command: `{command}`\n- 关键指标 (Metrics): Jev={result.get('jev_calls',0)}，正式原生步={result.get('native_steps',0)}，语义调用尝试={result.get('semantic_calls',0)}，策略墙时={row['policy_wall_seconds']:.2f}s；DeepSeek={result.get('deepseek_calls',0)}。初始化10步单列，网络失败不算模型已返回。\n- 日志路径 (Artifacts): {row['path']}；{root}/manifest.json；LOGS/2026-10-04-libero-verify20-top5.md。\n- 结论 (Conclusion, 1–3 句): 该回合完整记录保留。基础设施失败按Crashed记账，不隐去、重跑或当作控制算法的正负证据。\n- 下一步 (Next): 首个网络故障应立即中断后续队列；按AGENTS§10升级，获得许可且联网预检通过后恢复有界验证。\n- 关联议题 (Discussion): DISC-2026W39-001\n'''
                stream.write(block); stream.flush(); text += block
        (args.output/'exp-ids.json').write_text(json.dumps(ids, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'}))


SIM_PYTHON = '/root/yekangjie/project/embodied-jev/.venv-libero-plus/bin/python'
if __name__ == '__main__':
    main()

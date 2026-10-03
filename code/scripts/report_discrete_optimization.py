"""Offline campaign report; native outcomes never flow into the controller."""
import collections
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]


def main():
    name = '2026-10-04-robodojo-opt30'
    journal = ROOT / 'code/runs' / (name + '.jsonl')
    rows = [json.loads(line) for line in journal.read_text().splitlines()] if journal.exists() else []
    records = []
    for row in rows:
        if row['event'] != 'reserved':
            continue
        folder = ROOT / 'code/runs' / f"jev-discrete-{row['task']}-{row['attempt']:02d}"
        result = folder / 'structured_result.json'
        config = folder / 'protocol.json'
        requests = sorted(folder.glob('decision-*/request.json'))
        stages = collections.Counter()
        non_ascii = []
        input_tokens = output_tokens = 0
        for path in requests:
            data = json.loads(path.read_text())
            stages[data['state']['stage']] += 1
            if not json.dumps(data, ensure_ascii=False).isascii():
                non_ascii.append(str(path.relative_to(ROOT)))
            response = path.with_name('response.json')
            if response.exists():
                usage = json.loads(response.read_text()).get('usage', {})
                input_tokens += usage.get('input_tokens', 0)
                output_tokens += usage.get('output_tokens', 0)
        data = json.loads(result.read_text()) if result.exists() else {}
        cfg = json.loads(config.read_text()) if config.exists() else {}
        records.append(dict(**row, run=str(folder.relative_to(ROOT)),
                            organization=cfg.get('controller_settings', {}).get('input_organization'),
                            controller=cfg.get('generated_controller'), status=data.get('status', 'running'),
                            native_success=data.get('native', {}).get('success'), steps=data.get('steps'),
                            requests=len(requests), stages=dict(stages), non_ascii_requests=non_ascii,
                            input_tokens=input_tokens, output_tokens=output_tokens))
    output = ROOT / 'LOGS/robodojo-opt30-results.json'
    output.write_text(json.dumps(dict(limit=30, used=len(records), trials=records), ensure_ascii=False, indent=2)+'\n')
    lines = ['# RoboDojo 30试次优化进展', '',
             '开发混版本；英文校验、程序阶段推进与独立native成功分别记录。接口错误计入试次。', '',
             '|本轮|任务|累计序号|输入|native成功|步数|Jev请求|终止原因|',
             '|---:|---|---:|---|---|---:|---:|---|']
    for r in records:
        lines.append(f"|{r['trial']}|{r['task']}|{r['attempt']}|{r['organization']}|{r['native_success']}|{r['steps']}|{r['requests']}|{r['status']}|")
    lines += ['', f"本轮已预留 {len(records)}/30 试次。非ASCII请求 {sum(len(r['non_ascii_requests']) for r in records)}。", '',
              '每回合原始目录及阶段请求数量见JSON；全部request/response、RGB-D、动作、版本与原生结果保留。']
    (ROOT / 'LOGS/robodojo-opt30-results.md').write_text('\n'.join(lines)+'\n')
    print('Campaign trials:', len(records), '; non-ASCII:', sum(len(r['non_ascii_requests']) for r in records))


if __name__ == '__main__':
    main()

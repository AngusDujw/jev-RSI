"""Offline campaign report; native outcomes never flow into the controller."""
import collections
import hashlib
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
        payload_digests=[]
        forbidden_hits=[]
        forbidden={'object_true_position','ground_truth_position','oracle_error','segmentation_id','reward','native_success','object_poses'}
        def scan(value,path='$'):
            if isinstance(value,dict):
                for key,child in value.items():
                    if key in forbidden:forbidden_hits.append(path+'.'+key)
                    scan(child,path+'.'+key)
            elif isinstance(value,list):
                for i,child in enumerate(value):scan(child,path+'['+str(i)+']')
        for path in requests:
            data = json.loads(path.read_text())
            stages[data['state']['stage']] += 1
            scan(data['state'])
            payload_digests.append(hashlib.sha256(json.dumps(dict(state=data['state'],questions=data['questions']),sort_keys=True).encode()).hexdigest())
            if not json.dumps(data, ensure_ascii=False).isascii():
                non_ascii.append(str(path.relative_to(ROOT)))
            response = path.with_name('response.json')
            if response.exists():
                usage = json.loads(response.read_text()).get('usage', {})
                input_tokens += usage.get('input_tokens', 0)
                output_tokens += usage.get('output_tokens', 0)
        audit=folder/'input_contract_audit.jsonl'
        audited=[json.loads(line)['sha256'] for line in audit.read_text().splitlines()] if audit.exists() else []
        audit_missing=list((collections.Counter(payload_digests)-collections.Counter(audited)).elements())
        ownership_violations=[];transition_count=0
        for path in sorted(folder.glob('frame-*/command.json')):
            command=json.loads(path.read_text());debug=command.get('debug',{});choices=debug.get('jev_choices',{})
            for event in debug.get('state_transitions',[]):
                transition_count+=1
                if event.get('owner')!='Jev' or choices.get('phase') not in ('advance','retry'):ownership_violations.append(str(path)+':phase')
            for arm,action in command.get('arms',{}).items():
                grip=choices.get(arm+'_gripper')
                if grip in ('open','close') and action['gripper_opening']!=float(grip=='open'):ownership_violations.append(str(path)+':gripper')
                for axis,delta in zip('xyz',action['delta_xyz_m']):
                    if abs(delta)>1e-10:
                        direction=choices.get(arm+'_'+axis)
                        if direction!=('positive' if delta>0 else 'negative'):ownership_violations.append(str(path)+':direction')
        data = json.loads(result.read_text()) if result.exists() else {}
        cfg = json.loads(config.read_text()) if config.exists() else {}
        records.append(dict(**row, run=str(folder.relative_to(ROOT)),
                            organization=cfg.get('controller_settings', {}).get('input_organization'),
                            controller=cfg.get('generated_controller'),frozen_reference=cfg.get('frozen_reference'), status=data.get('status', 'running'),
                            native_success=data.get('native', {}).get('success'), steps=data.get('steps'),
                            requests=len(requests), stages=dict(stages), non_ascii_requests=non_ascii,
                            input_tokens=input_tokens, output_tokens=output_tokens,
                            audit_missing=audit_missing,forbidden_field_hits=forbidden_hits,
                            ownership_violations=ownership_violations,transition_count=transition_count,
                            runtime_deepseek_calls=data.get('deepseek_calls'),runtime_gpt6_forbidden=cfg.get('forbid_runtime_gpt6'),
                            runtime_perception=cfg.get('runtime_perception')))
    output = ROOT / 'LOGS/robodojo-opt30-results.json'
    tasks={}
    for task in sorted({r['task'] for r in records}):
        subset=[r for r in records if r['task']==task];finished=[r for r in subset if r['status']!='running'];frozen=[r for r in finished if r['frozen_reference']]
        tasks[task]=dict(reserved=len(subset),completed=len(finished),mixed_development_successes=sum(r['native_success'] is True for r in finished),frozen_successes=sum(r['native_success'] is True for r in frozen),frozen_trials=len(frozen))
    output.write_text(json.dumps(dict(limit=30, used=len(records),tasks=tasks, trials=records), ensure_ascii=False, indent=2)+'\n')
    lines = ['# RoboDojo 30试次优化进展', '',
             '开发混版本；英文校验、程序阶段推进与独立native成功分别记录。接口错误计入试次。', '',
             '|本轮|任务|累计序号|输入|native成功|步数|Jev请求|终止原因|',
             '|---:|---|---:|---|---|---:|---:|---|']
    for r in records:
        lines.append(f"|{r['trial']}|{r['task']}|{r['attempt']}|{r['organization']}|{r['native_success']}|{r['steps']}|{r['requests']}|{r['status']}|")
    lines += ['', '|任务|完成试次|开发混版本成功|冻结验证成功/次数|', '|---|---:|---:|---:|']
    for task,row in tasks.items():lines.append(f"|{task}|{row['completed']}|{row['mixed_development_successes']}|{row['frozen_successes']}/{row['frozen_trials']}|")
    lines += ['', f"本轮已预留 {len(records)}/30 试次。非ASCII请求 {sum(len(r['non_ascii_requests']) for r in records)}。", '',
              f"请求边界审计漏项 {sum(len(r['audit_missing']) for r in records)}；辅助禁止字段命中 {sum(len(r['forbidden_field_hits']) for r in records)}；方向/夹爪/阶段所有权违反 {sum(len(r['ownership_violations']) for r in records)}。字段扫描仅辅助，不替代来源审阅。", '',
              '每回合原始目录及阶段请求数量见JSON；全部request/response、RGB-D、动作、版本与原生结果保留。']
    (ROOT / 'LOGS/robodojo-opt30-results.md').write_text('\n'.join(lines)+'\n')
    print('Campaign trials:', len(records), '; non-ASCII:', sum(len(r['non_ascii_requests']) for r in records))


if __name__ == '__main__':
    main()

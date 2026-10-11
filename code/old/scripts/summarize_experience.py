"""Distill factual run outcomes to candidate Markdown; never activate memories."""
import argparse,json,hashlib
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runs',nargs='+',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); rows=[]
    for root in a.runs:
        result_path=root/'structured_result.json'
        result=json.loads(result_path.read_text())
        stages=[]
        for path in sorted(root.glob('frame-*/command.json')):
            stage=json.loads(path.read_text())['stage']
            if not stages or stage!=stages[-1]:stages.append(stage)
        rows.append(dict(run=str(root),success=result['native']['success'],reason=result['status'],
            stages=stages,jev_calls=result['jev_calls'],steps=result['steps'],
            result_sha256=hashlib.sha256(result_path.read_bytes()).hexdigest()))
    meta=dict(id=a.output.stem,status='candidate',stages=sorted({s for r in rows for s in r['stages']}),
        kinds=['pick_lift'],parameters={},evidence=[r['run'] for r in rows])
    lines=['# 回合事实总结（待审核，不自动激活）','', '```json',json.dumps(meta,ensure_ascii=False,indent=2),'```','',
        '本文件只汇总观测到的结果，不根据单次成败推断因果，不写入布局坐标或真值对象答案。',
        '审核时区分感知、身份关联、执行、物理抓取和验证失败；只有跨回合证据支持的经验才可更新共享记忆。','']
    for r in rows:
        lines.extend([f"## {Path(r['run']).name}",f"- 原生成功：{r['success']}；步数：{r['steps']}；Jev：{r['jev_calls']}",
            '- 实际阶段：'+' → '.join(r['stages']),'- 终止事实：'+r['reason'],
            '- 结果SHA256：'+r['result_sha256'],''])
    a.output.parent.mkdir(parents=True,exist_ok=True)
    if a.output.exists():raise FileExistsError('Do not overwrite an existing experience summary')
    a.output.write_text('\n'.join(lines)+'\n')

if __name__=='__main__':main()

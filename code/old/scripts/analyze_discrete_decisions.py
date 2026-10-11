"""Input-relative consistency, not ground-truth accuracy or causal ablation."""
import json,collections
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
groups=collections.defaultdict(lambda:dict(axes=0,correct=0,moving_axes=0,moving_correct=0,requests=0,advances=0,advances_outside_waypoint=0))
trials=[]
for run in sorted((ROOT/'code/runs').glob('jev-discrete-*-??')):
    if not (run/'summary.json').exists():continue
    cfg=json.loads((run/'protocol.json').read_text());variant=cfg['controller_settings']['input_variant']
    for q in sorted(run.glob('decision-*/request.json')):
        rp=q.parent/'response.json'
        if not rp.exists():continue
        state=json.loads(q.read_text())['state'];answers=json.loads(rp.read_text()).get('answers',{})
        group=groups[(cfg['runtime_task'],variant,state['stage'])];group['requests']+=1
        dz=state.get('constraints',{}).get('dead_zone_m');errors={}
        if dz is None:continue  # Select-only projected requests contain no motion coordinates.
        for arm,g in state.get('geometry',{}).items():errors[arm]=g['target_minus_grasp_m']
        for arm,g in state.get('relations',{}).items():errors[arm]=[g[a].get('target_minus_current_grasp_mm',g[a].get('signed_distance_mm'))/1000 for a in 'xyz']
        for arm,values in errors.items():
            for axis,e in zip('xyz',values):
                key=arm+'_'+axis
                if key not in answers:continue
                expected='hold' if abs(e)<=dz else 'positive' if e>0 else 'negative';correct=answers[key]['choice']==expected
                group['axes']+=1;group['correct']+=correct
                if expected!='hold':group['moving_axes']+=1;group['moving_correct']+=correct
        if answers.get('phase',{}).get('choice')=='advance' and errors:
            group['advances']+=1
            current=state.get('phase_evidence',{}).get('current_contact_error_m')
            values=current if current is not None else [e for v in errors.values() for e in v]
            # A diagnostic flag only: orientation/contact/phase contracts can add requirements.
            group['advances_outside_waypoint']+=any(abs(e)>dz+1e-7 for e in values)
    trials.append(run.name)
rows=[dict(task=k[0],variant=k[1],stage=k[2],**v) for k,v in sorted(groups.items())]
result=dict(interpretation='Consistency with disclosed estimated waypoint errors, NOT physical truth accuracy; versions and trajectories differ across encodings, so no causal ranking.',trials=trials,rows=rows)
(ROOT/'LOGS/jev-discrete-direction-consistency.json').write_text(json.dumps(result,indent=2)+'\n')
lines=['# 联合决策中的方向与阶段诊断','','参照为输入中披露的视觉估计航点误差，不是仿真真值准确率。版本/轨迹不同，不能把编码分组当严格消融。Jev的原始回答计入，即使随后因阶段转换/死区/姿态安全门没有执行平移。','', '|任务|输入|阶段|原始方向一致|应运动轴一致|有航点的advance|advance时尚在航点死区外|','|---|---|---|---:|---:|---:|---:|']
for r in rows:
    lines.append(f"|{r['task']}|{r['variant']}|{r['stage']}|{r['correct']}/{r['axes']}|{r['moving_correct']}/{r['moving_axes']}|{r['advances']}|{r['advances_outside_waypoint']}|")
(ROOT/'LOGS/jev-discrete-direction-consistency.md').write_text('\n'.join(lines)+'\n')
print('analyzed',len(trials),'trials',sum(r['requests'] for r in rows),'responses')

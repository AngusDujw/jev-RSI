"""Build an offline, source-backed viewer of ten recorded Jev workflows."""
from pathlib import Path
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'code/reports/libero-ten-workflows'
VIDEOS = ROOT / 'code/runs/2026-10-15-libero-ten-success-videos'

# Editorial explanations of final implementations, not verbatim GPT plans.
METHODS = {
1098: dict(family='关节机构操作', aim='辨认中层把手，正面夹持并外拉抽屉。',
 steps=['固定图像区域内筛选中性金属连通域，RGB-D 重建三根把手并按高度排序。', '拟合可见柜面，结合自身指垫包络构造柜外接近、对齐与接触目标。', 'Jev 决定闭爪和外拉；以可见伸出、自身拉动位移及连续受阻构成有界转段证据。', 'Jev 选择松爪和验证；原生成功只在结束后评价。'],
 prior='固定把手 ROI、金属颜色/尺寸阈值、三把手布局及柜体朝向先验；不等于任意视角通用识别。',
 files=['libero_goal_drawer_vision.py','libero_goal_drawer_control.py'], evidence=['selected-handle.json','own-pad-contact-offset.json']),
1144: dict(family='抓取与放置', aim='抓住碗，搬到炉面并释放退离。',
 steps=['GroundingDINO/SAM 根据公开名称定位碗；炉面使用预设公开图像区域。', 'RGB-D 重建可见物体边界与支撑面，依据自身夹爪计算抓取位姿。', '按接近、对齐、下降、闭爪、抬升、搬运、下降、释放、退离推进；用鲜 RGB-D 检查持有。', '到位、夹爪执行时间、持有/受阻证据整理为阶段合同，Jev 选方向及推进。'],
 prior='炉面接收区域预先写定；物体名称、几何阈值、阶段合同与步长规则由程序提供。', files=['libero_goal_local_vision.py','libero_jev_supervisor.py'],evidence=['initial-geometry.json','pregrasp-geometry.json','stalled-geometry.json']),
1163: dict(family='抓取与放置', aim='抓起酒瓶并放到可见柜顶。',
 steps=['公开名称定位酒瓶，柜顶使用预设图像区域，RGB-D 测量当前可见几何。', '自身指垫与可见瓶体计算多组抓取候选，Jev 在 select 阶段选择候选。', '试抬后以相机/动作历史验证持有；遮挡时保留初始可见外观并以新鲜观测跟踪。', '搬运到柜顶；根据可见支撑、释放和退离证据提供推进/恢复选项。'],
 prior='柜顶固定 ROI；瓶体/支撑面的可见边界与初始外观记忆不等于完整物理形状。',files=['libero_goal_local_vision.py','libero_jev_recovery.py'],evidence=['initial-geometry.json','candidates-00.json','source-appearance.json']),
1202: dict(family='组合任务 · 尚未稳定', aim='先部分打开抽屉，再抓碗放入抽屉内部。',
 steps=['开柜前用本地检测保存碗的公开可见位置/外观；测量抽屉把手和柜面。', '根据可见碗尺寸构造部分开柜目标，Jev 完成夹持外拉、松爪与让开开口。', '重新用 RGB-D 定位开口和碗，按自身侧向指垫几何生成抓取候选，Jev 选候选并试抬。', '把碗搬到可见抽屉内部；依据新鲜图像的包含/侵入证据开放一次有界释放试验，由 Jev 决定释放退离。'],
 prior='固定把手 ROI、柜体布局、侧向抓取与释放规则；可见最低点不冒充物理底部。该开发回合成功，但后续初态失败。',files=['libero_goal_drawer_vision.py','libero_goal_drawer_control.py','libero_jev_recovery.py'],evidence=['selected-handle.json','initial-geometry.json','candidates-00.json','source-appearance.json']),
1252: dict(family='抓取与放置', aim='抓起碗，搬到柜顶并释放。',
 steps=['本地检测/分割碗；柜顶使用公开图像中的预设区域。', '用标定 RGB-D 测量碗和柜顶，结合自身夹爪包络给出抓取与搬运高度。', '按固定九阶段组织目标、误差、夹爪要求、持有与到位证据。', '下降受阻时刷新可见几何，Jev 决定继续、重观测、释放与退离。'],
 prior='预设柜顶 ROI 与九阶段策略；接触/受阻门不直接证明官方任务成功。',files=['libero_goal_local_vision.py','libero_jev_supervisor.py'],evidence=['initial-geometry.json','pregrasp-geometry.json','stalled-geometry.json']),
1296: dict(family='桌面接触推移', aim='让盘子沿桌面滑动到炉灶前方，不抬盘。',
 steps=['以红色环、形状/高度阈值定位盘子；明亮炉壳区域确定可见炉面位置。', 'RGB-D 计算盘面高度、中心、炉前目标和两段桌面路线；自身夹爪包络确定接触点。', 'Jev 先选择闭爪形成紧凑推头；第二段采用近侧盘沿闭爪接触试验，保持桌面高度滑动。', '以鲜图像更新盘的位置与炉前关系，形成各段目标误差；Jev 选择推进、开爪、退离与验证。'],
 prior='红环颜色、图像裁剪、形状阈值和炉灶布局先验；固定两段路线规则，不是任意盘子通用推理。',files=['libero_goal_plate_vision.py','libero_push_control.py'],evidence=['goal-plate-visible-plan.json','push-geometry.json','push-geometry-segment-2.json','after-push-geometry-segment-1.json']),
1335: dict(family='抓取与放置', aim='将奶酪盒放入碗中。',
 steps=['根据公开名称检测奶酪盒与碗，排除场景级大框和相互重叠的候选。', '对唯一紧凑候选允许受限的低置信度检测门；SAM/RGB-D 测量可见宽度、底部范围与碗口。', '结合自身指垫计算抓取候选，由 Jev 选择并完成试抬；以新鲜观测核查持有。', '搬运、下降到可见接收区域，由 Jev 选择释放和退离。'],
 prior='任务名称、紧凑候选置信门、抓取候选和接收规则预先定义；可见几何存在遮挡误差。',files=['libero_goal_local_vision.py','libero_jev_recovery.py'],evidence=['initial-geometry.json','candidates-00.json','pregrasp-geometry.json']),
1383: dict(family='旋转接触操作', aim='抓住炉灶旋钮上的拨片并转动。',
 steps=['定位明亮炉壳，在其上方限定区域筛选暗色控制件连通域。', 'RGB-D 重建顶端拨片点，用主轴拟合估计角度；结合自体夹爪生成悬停、接触目标。', 'Jev 选择靠近、对齐、接触、闭爪、转腕、松爪及验证。', '释放后重新测可见拨片角度变化，区别于仅用腕部转角作为转动成功证据。'],
 prior='炉壳/拨片相对图像区域、暗色与尺寸阈值、转动目标与阶段图由程序定义。',files=['libero_goal_knob_vision.py','libero_goal_knob_control.py'],evidence=['visible-control-initial.json','contact-plan.json','visible-control-after.json']),
1423: dict(family='抓取与放置', aim='把碗放到盘上。',
 steps=['公开名称分别检测碗和盘，排除源物体重叠候选，分割后用 RGB-D 拟合接收表面。', '计算抓取与搬运目标，并提供九阶段合同和按轴误差。', '下降时用公开支撑面与动作受阻证据处理接触，不继续盲目向下压。', '由 Jev 选择释放与短距离退离；程序提供释放时序及完成证据。'],
 prior='公开名称、支撑/受阻判据、短退离规则是固定策略；不代表 Jev 自己发现操作策略。',files=['libero_goal_local_vision.py','libero_jev_supervisor.py'],evidence=['initial-geometry.json','stalled-geometry.json','pregrasp-geometry.json']),
1458: dict(family='带姿态的抓取放置', aim='抓住酒瓶并沿斜架承托方向放入酒架。',
 steps=['本地检测酒瓶；酒架使用预设公开图像区域并作可见分割。', '标定 RGB-D 重建架面点，在中心条带拟合承托斜线，用可见瓶体尺寸计算接收姿态和位置。', 'Jev 选抓取候选，完成试抬、搬运与接收姿态对齐；程序提供各旋转轴误差。', '下降时提供可见接触/预计落差候选，Jev 决定释放退离，再以新鲜图像检查瓶子与架面的可见关系。'],
 prior='酒架 ROI 固定、斜面斜率范围和条带拟合规则预先定义；不能称为 GPT 每次在线找酒架。',files=['libero_goal_local_vision.py','libero_goal_rack_geometry.py','libero_jev_recovery.py'],evidence=['visible-rack-fit.json','initial-geometry.json']),
}


def load(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/'assets').mkdir(exist_ok=True)
    records = []
    for video in load(VIDEOS/'manifest.json'):
        gid = video['goal']
        run = ROOT/'code/runs'/Path(video['source_run']).name
        ep = run/'episode'
        result = load(ep/'result.json')
        assert result['success'] is True and result['program_finished'] is True
        branches = {}
        for line in (ep/'branches.jsonl').read_text().splitlines():
            if line.strip():
                branch = json.loads(line)
                branches.setdefault(branch.get('decision_id'), []).append(branch)
        decisions = []
        stages = {}
        for req in sorted(ep.glob('decision-*/request.json')):
            resp = req.with_name('response.json')
            if not resp.is_file():
                raise ValueError(f'Missing response: {req}')
            request, response = load(req), load(resp)
            state = request['state']
            stage = state.get('stage', state.get('operation'))
            assert stage
            contract = state.get('stage_contract', state.get('phase_contract', state.get('operation_contract')))
            if stage not in stages:
                stages[stage] = dict(name=stage, contract=contract, count=0, first=len(decisions))
            stages[stage]['count'] += 1
            decisions.append(dict(id=req.parent.name, stage=stage, request=request, response=response,
                                  execution=branches.get(req.parent.name, []),
                                  request_sha256=digest(req), response_sha256=digest(resp),
                                  source='../../runs/'+run.name+'/episode/'+req.parent.name+'/'))
        assert len(decisions) == result['jev_calls'], (gid, len(decisions), result['jev_calls'])
        frames = video['frames']
        shots = []
        for i in sorted({0, len(frames)//3, 2*len(frames)//3, len(frames)-1}):
            source = ep/Path(frames[i]['path']).name
            target = OUT/'assets'/f'{gid}-{source.name}'
            shutil.copyfile(source, target)
            shots.append(dict(src='assets/'+target.name, tick=frames[i]['tick'], original=source.name))
        evidence = []
        names = list(METHODS[gid]['evidence'])
        if gid == 1458:
            names += sorted(p.name for p in ep.glob('rack-contact-*.json'))[-1:]
        for name in names:
            p = ep/name
            if p.is_file():
                evidence.append(dict(name=name, data=load(p), sha256=digest(p)))
        manifest = load(run/'manifest.json')
        records.append(dict(id=gid, title=video['title'], method=METHODS[gid],
                            source_run=run.name, result=result, decisions=decisions,
                            stages=list(stages.values()), evidence=evidence, shots=shots,
                            commit=manifest.get('reservation', {}).get('policy_commit', manifest.get('git_commit')),
                            init=manifest.get('reservation', {}).get('init'),
                            video='../../runs/'+VIDEOS.name+'/'+video['video'],
                            duration=video['duration_s'],
                            sources=manifest.get('policy_source_sha256', {})))
    text = json.dumps(records, ensure_ascii=False, separators=(',', ':'))
    # Keep data out of executable HTML; escape script delimiters defensively.
    (OUT/'data.js').write_text('window.CASES='+text.replace('<', '\\u003c')+';\n')
    print(json.dumps(dict(tasks=len(records), decisions=sum(len(r['decisions']) for r in records),
                          bytes=len(text.encode()), output=str(OUT)), ensure_ascii=False))


if __name__ == '__main__':
    main()

"""Offline playback of recorded sensor images and decisions; no model/robot calls."""
import argparse
import base64
import json
from pathlib import Path


PAGE = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Jev 仿真回放</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#111820;color:#e7eef4;font:16px system-ui,sans-serif}
main{max-width:1380px;margin:auto;padding:28px}h1{font-size:28px;margin:8px 0}p{color:#b3c3d0;line-height:1.6}
.badge{color:#ffce81}.views{display:grid;grid-template-columns:1fr 1fr;gap:16px}.view{background:#1c2834;border-radius:10px;overflow:hidden}
.view b{display:block;padding:10px 16px}img{width:100%;display:block;aspect-ratio:4/3;object-fit:contain}
.controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:18px 0}
button,select{background:#263b4d;border:1px solid #456179;border-radius:6px;color:#fff;padding:10px 16px;cursor:pointer}
button:hover{background:#3b556a}button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid #79c7ff}
#timeline{width:100%;accent-color:#79c7ff}.panel{background:#1c2834;border-radius:10px;padding:18px;margin-top:18px}
#facts{display:flex;gap:8px;flex-wrap:wrap}.fact{padding:6px 10px;background:#293745;border-radius:5px;font-size:14px}
.yes{color:#88e5b4}.no{color:#ffa899}.unknown{color:#bdc6ce}pre{white-space:pre-wrap;word-break:break-word;font-size:13px}
#status{font-size:19px;margin:14px 0}#jumps button{font-size:14px;padding:7px 12px}.small{font-size:13px}
@media(max-width:720px){main{padding:14px}.views{grid-template-columns:1fr}h1{font-size:23px}}
</style><main><span class="badge" id="badge"></span>
<h1>机械臂抓放：逐步观测回放</h1><p id="summary"></p>
<p class="small">这是运行时保存的原始观测帧，不是重新仿真或连续录像。每帧显示该次动作执行前的状态；下一帧体现动作结果。默认每帧停留 0.4 秒，可暂停、拖动及逐帧查看；播放时间不代表 API 耗时。</p>
<div class="views"><div class="view"><b>顶部相机</b><img id="top" alt="顶部相机的实际保存帧"></div><div class="view"><b>腕部相机</b><img id="wrist" alt="腕部相机的实际保存帧"></div></div>
<div class="controls"><button id="play">播放</button><button id="prev">上一帧</button><button id="next">下一帧</button><label>速度 <select id="speed"><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option></select></label><span id="counter"></span></div>
<input id="timeline" type="range" min="0" value="0" aria-label="观测帧序号">
<div id="jumps" class="controls"></div><div class="panel"><div id="status" aria-live="polite"></div><div id="facts"></div><p id="numbers"></p><details><summary>该帧的模型选择与记录</summary><pre id="detail"></pre></details></div>
<p class="small">离线单文件；不连接机器人、不请求模型、不向外发送记录。原始记录目录：<span id="run"></span></p></main>
<script id="recording" type="application/json">__RECORDING__</script><script>
const data=JSON.parse(document.getElementById('recording').textContent),frames=data.frames;
const $=id=>document.getElementById(id),names={align:'对齐',descend:'下降',grasp:'闭爪',lift:'抬升',carry:'搬运',lower:'降低',release:'释放',retreat:'撤离'};
let index=0,timer=null;
$('badge').textContent=(data.summary.plan_source==='operator_file_NOT_GPT6'?'人工阶段计划 + 真实 Jev':'GPT‑6 高层规划 + Jev 低层决策')+' · '+(data.summary.policy_success&&data.summary.evaluation?.physical_success?'抓放通过':'未通过抓放验收');
$('summary').textContent=`${data.name} | GPT ${data.summary.gpt_calls} 次，Jev ${data.summary.jev_calls} 次 | NoSlip: ${data.physics?.noslip_iterations??'未记录'} | 结果：${data.summary.status}`;
$('run').textContent=data.name;$('timeline').max=frames.length-1;
function pause(){clearTimeout(timer);timer=null;$('play').textContent='播放'}
function render(){const f=frames[index];$('top').src=f.top;$('wrist').src=f.wrist;$('timeline').value=index;
 $('counter').textContent=`第 ${f.step} 步 · ${index+1}/${frames.length} 帧`;
 $('status').textContent=f.event==='invariant_replan'?`${names[f.stage]||f.stage}：保持条件未确认（不满足或不可见），停止并请求重规划`:`${names[f.stage]||f.stage||'停止'} · ${f.decision?.transition||'无新决策'} / ${f.decision?.action||'保持'}`;
 $('facts').replaceChildren();for(const [k,v] of Object.entries(f.evidence?.facts||{})){const e=document.createElement('span');e.className='fact '+(v===true?'yes':v===false?'no':'unknown');e.textContent=k+': '+(v===null?'未知':v);$('facts').append(e)}
 const e=f.evidence||{},o=e.objects||{};$('numbers').textContent=`夹爪开度：${e.robot?.aperture??'无记录'}（0 闭合，1 全开） | ${data.object_label} 可见表面：${JSON.stringify(o[data.object_label]?.position_m??null)} | ${data.destination_label} 可见表面：${JSON.stringify(o[data.destination_label]?.position_m??null)}`;
 $('detail').textContent=JSON.stringify({step:f.step,event:f.event,decision:f.decision,answers:f.answers,robot:e.robot,facts:e.facts},null,2);
}
function tick(){if(index===frames.length-1){pause();return}timer=setTimeout(()=>{index++;render();tick()},400/Number($('speed').value))}
$('play').onclick=()=>{if(timer){pause();return}if(index===frames.length-1)index=0;render();$('play').textContent='暂停';tick()};
$('prev').onclick=()=>{pause();index=Math.max(0,index-1);render()};$('next').onclick=()=>{pause();index=Math.min(frames.length-1,index+1);render()};
$('timeline').oninput=()=>{pause();index=Number($('timeline').value);render()};
const seen=new Set();frames.forEach((f,i)=>{const key=f.event==='invariant_replan'?'failure':f.stage;if(!key||seen.has(key))return;seen.add(key);const b=document.createElement('button');b.textContent=key==='failure'?'失去保持条件':names[key]||key;b.onclick=()=>{pause();index=i;render()};$('jumps').append(b)});
document.addEventListener('keydown',e=>{if(e.target.matches('input,select,button'))return;if(e.key==='ArrowRight')$('next').click();if(e.key==='ArrowLeft')$('prev').click()});render();
</script></html>'''


def build(run, output):
    run=Path(run)
    events=[json.loads(line) for line in (run/'events.jsonl').read_text().splitlines()]
    summary=json.loads((run/'summary.json').read_text())
    physics=json.loads((run/'config.json').read_text()).get('sim',{}) if (run/'config.json').exists() else {}
    plan=next((e['plan'] for e in events if e['kind']=='plan'),{})
    decisions={e['step']:e for e in events if e['kind']=='decision'}
    invariants={e['evidence']['sequence']-1:e for e in events if e['kind']=='invariant_replan'}
    frames=[]; last=None
    for path in sorted(run.glob('[0-9][0-9][0-9][0-9]-top.jpg')):
        step=int(path.stem.split('-')[0]); wrist=run/f'{step:04d}-wrist.jpg'
        if not wrist.exists(): raise ValueError(f'Missing wrist frame at step {step}')
        event=decisions.get(step) or invariants.get(step)
        if event: last=event
        row={'step':step,'event':event['kind'] if event else 'no_new_decision',
             'stage':last.get('stage') if last else None,'decision':event.get('decision') if event else None,
             'answers':event.get('answers') if event else None,'evidence':last.get('evidence') if last else None}
        if isinstance(row['stage'],dict):row['stage']=row['stage']['id']
        for name,p in [('top',path),('wrist',wrist)]:
            row[name]='data:image/jpeg;base64,'+base64.b64encode(p.read_bytes()).decode()
        frames.append(row)
    if not frames:raise ValueError('No saved camera frames; run with --save-frames')
    payload=json.dumps({'name':run.name,'summary':summary,'physics':physics,'frames':frames,'object_label':plan.get('object_label','red block'),'destination_label':plan.get('destination_label','blue tray')},ensure_ascii=False).replace('<','\\u003c')
    with Path(output).open('x') as file:file.write(PAGE.replace('__RECORDING__',payload))
    return {'frames':len(frames),'output':str(output),'bytes':Path(output).stat().st_size}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run');p.add_argument('--output',required=True)
    p.add_argument('--video',help='Optional WebM of sampled observations (not continuous physics)')
    p.add_argument('--ffmpeg',default='ffmpeg')
    args=p.parse_args();print(json.dumps(build(args.run,args.output)))
    if args.video: export_video(args.run,args.video,args.ffmpeg)


def export_video(run,output,ffmpeg):
    import io
    import subprocess
    from PIL import Image,ImageDraw
    if Path(output).exists():raise FileExistsError(output)
    paths=sorted(Path(run).glob('[0-9][0-9][0-9][0-9]-top.jpg'))
    if not paths:raise ValueError('No saved camera frames')
    events=[json.loads(line) for line in (Path(run)/'events.jsonl').read_text().splitlines()]
    summary=json.loads((Path(run)/'summary.json').read_text())
    source='Operator plan + real Jev' if summary.get('plan_source')=='operator_file_NOT_GPT6' else 'GPT-6 plan + real Jev'
    config_path=Path(run)/'config.json'
    if config_path.exists():
        source+=' | NoSlip='+str(json.loads(config_path.read_text()).get('sim',{}).get('noslip_iterations',0))
    states={e['step']:e['stage'] for e in events if e['kind']=='decision'}
    states.update({e['evidence']['sequence']-1:'INVARIANT UNCONFIRMED - STOP / REPLAN' for e in events if e['kind']=='invariant_replan'})
    command=[ffmpeg,'-hide_banner','-loglevel','error','-f','image2pipe','-framerate','2.5','-vcodec','mjpeg','-i','pipe:0','-c:v','libvpx','-b:v','1400k','-pix_fmt','yuv420p','-n',str(output)]
    with subprocess.Popen(command,stdin=subprocess.PIPE) as proc:
        stage=''
        try:
            for path in paths:
                step=int(path.stem.split('-')[0]);stage=states.get(step,stage)
                with Image.open(path) as top,Image.open(path.with_name(f'{step:04d}-wrist.jpg')) as wrist:
                    canvas=Image.new('RGB',(1280,540),'#111820');canvas.paste(top,(0,60));canvas.paste(wrist,(640,60))
                draw=ImageDraw.Draw(canvas)
                draw.text((16,8),f'Step {step:03d} | {stage} | {source}',fill='white')
                draw.text((16,36),'TOP CAMERA',fill='white');draw.text((656,36),'WRIST CAMERA',fill='white')
                buffer=io.BytesIO();canvas.save(buffer,format='JPEG',quality=95);proc.stdin.write(buffer.getvalue())
        finally:proc.stdin.close()
        if proc.wait():raise RuntimeError('FFmpeg export failed')
    print(json.dumps({'video':str(output),'observation_frames':len(paths),'playback_seconds':len(paths)/2.5}))


if __name__=='__main__':main()

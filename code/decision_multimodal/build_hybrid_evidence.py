"""Build a static evidence page from actual archived calls, without API access."""
import argparse
import json
from pathlib import Path
import shutil


HTML=r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>视觉推进 · 10月18日实验记录</title>
<style>
:root{--ink:#17272a;--paper:#f3f1e9;--accent:#007c80;--line:#c9d1cc}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.7 Georgia,"Noto Serif CJK SC",serif}header{background:var(--ink);color:var(--paper);padding:35px max(6vw,20px)}header small{letter-spacing:.2em;color:#76d7ce}h1{font-size:clamp(30px,5vw,58px);line-height:1.2;margin:18px 0}header p{max-width:800px;color:#c0d1cc}main{max-width:1280px;margin:auto;padding:35px 5vw}h2{font-size:29px;font-weight:500;border-top:2px solid var(--ink);padding-top:20px;margin-top:45px}.intro{display:grid;grid-template-columns:1fr 1fr;gap:24px}.metric{border-left:5px solid var(--accent);padding:15px 25px;background:#fffefa}.metric b{font-size:38px;display:block}.note{color:#506565;font-size:14px}table{border-collapse:collapse;width:100%;margin:20px 0}td,th{border-bottom:1px solid var(--line);text-align:left;padding:12px 8px}th{font-size:14px;color:#506565}button{cursor:pointer;border:1px solid var(--line);background:transparent;color:var(--ink);font:inherit;padding:10px 15px;margin:0 8px 12px 0}button.active{background:var(--ink);color:white;border-color:var(--ink)}.io{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:22px}.panel{background:#fffefa;padding:20px;border:1px solid var(--line);min-width:0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.65 monospace;max-height:600px;overflow:auto}img{max-width:100%;display:block}#rgb{max-height:600px;margin:auto}a{color:var(--accent)}summary{cursor:pointer;font-weight:bold}details{margin:15px 0}.flow{border:1px solid var(--line);padding:20px;margin:25px 0}.tag{font:12px monospace;background:#e0e9e2;padding:4px 8px}footer{margin:50px 0;font-size:13px;color:#506565}@media(max-width:760px){.intro,.io{grid-template-columns:1fr}table{font-size:13px}td,th{padding:8px 4px}main{padding:20px}pre{max-height:450px}}
</style><header><small>ROBOT CONTROL / EVIDENCE NOTE 2026·10·18</small><h1>把视觉判断，接进控制闭环。</h1><p>实际运行存档：图像关系判断、粗接近、数值精调。这里展示真实提示词与回答；完整任务和视觉子测试分别计数。</p></header><main>
<div class="intro"><section class="metric"><span>两个完整搬碗任务</span><b>6 / 6</b>原生成功与程序完成均通过。<div class="note">仅两个相同外观碗任务；混合输入，不是纯图像控制。</div></section><section class="metric"><span>视觉实际贡献</span><b>38 次方向选择</b>粗接近每例推进约79–94毫米。<div class="note">视觉调用不接收XYZ误差；底层步长仍由原控制器缩放。</div></section></div>
<table><thead><tr><th>任务</th><th>固定初态</th><th>原生 / 程序</th><th>视觉X / 文本调用</th></tr></thead><tbody><tr><td>碗 → 炉灶 · 1144</td><td>5 / 6 / 7</td><td>3/3 · 3/3</td><td>18 / 269</td></tr><tr><td>碗 → 柜顶 · 1252</td><td>4 / 5 / 6</td><td>3/3 · 3/3</td><td>20 / 333</td></tr></tbody></table>
<h2>一次实际调用，分三种角色看</h2><p class="note">来源：1144 / init5，原始请求0000、0001、0012。显示中的图像base64缩写为说明；原始JSON可下载。</p><nav id="tabs"></nav><div class="flow" id="explain"></div><div class="io"><section class="panel"><span class="tag">ACTUAL INPUT</span><div id="imagebox"><img id="rgb" alt="实际发送给视觉模型的当前腕图"></div><pre id="input"></pre><a id="download">下载完整请求JSON</a></section><section class="panel"><span class="tag">ACTUAL OUTPUT</span><pre id="output"></pre></section></div>
<h2>规划模型实际收到什么</h2><p>本机Pro GPT-6.1 Sol / high。此轮保留原任务操作序列，规划模型给两种输入阶段的任务目标；执行器只编入当前阶段goal，规划原文保留在下方。</p><details><summary>展开完整规划提示词</summary><pre id="plannerprompt"></pre></details><details><summary>展开规划原始JSON</summary><pre id="plannerplan"></pre></details>
<h2>纯图像停止：让通过范围可见</h2><div class="io"><section><img src="band.png" alt="实际发送的腕图，固定中央青色色带表示可接受区域"><p class="note">色带固定在图像中心，不依赖源物三维位置，也不是TCP标记。原图±16px的评价范围保持不变；不向模型发送这个数值。</p></section><section><h3>水平居中：6/6</h3><p>76次真实图像回答，六例均由模型选择HOLD后通过。旧的“精确中心线”版本为5/6。</p><p>任务问题改为：碗轮廓的中心在色带左侧、色带内，还是右侧？图像分类经固定公开映射变成动作。</p><p class="note">这是单轴原生视觉子测试，不计作完整搬碗任务。垂直方向的独立结果见结果报告。</p><a href="report.md">完整结果报告</a></section></div><footer>全部内部提示词与经验使用英文。经验仅收集，不输入模型。保留所有失败版本，不以重复抽样替代失败。</footer></main>
<script>
fetch('data.json').then(r=>r.json()).then(d=>{const names=['视觉：粗X关系','文本：粗阶段Y/Z','文本：精细XYZ'];const descriptions=['只看当前腕图，输出above/center/below；由固定公开腕部方向映射成X方向。当前X误差不在请求里。','不接收图像，不问X；保留Y/Z误差与aligned布尔，以及原阶段、夹爪和切换问题。','进入精细区域后，恢复XYZ误差与aligned布尔；不接收图像，继续原完整任务阶段。'];const tab=document.getElementById('tabs');names.forEach((name,i)=>{const b=document.createElement('button');b.textContent=name;b.onclick=()=>show(i);tab.appendChild(b)});function show(i){[...tab.children].forEach((b,k)=>b.classList.toggle('active',k===i));const s=d.steps[i],r=structuredClone(s.request);const images=[];for(const m of r.input)for(const p of m.content){if(p.type==='input_image'){images.push(p.image_url);p.image_url='[inline PNG base64; see actual image above or download raw request]'}}document.getElementById('imagebox').hidden=!images.length;if(images.length)document.getElementById('rgb').src=images[0];document.getElementById('input').textContent=JSON.stringify(r,null,2);document.getElementById('output').textContent=JSON.stringify(s.response,null,2);document.getElementById('explain').textContent=descriptions[i];const a=document.getElementById('download');a.href=s.filename;a.download=s.filename}document.getElementById('plannerprompt').textContent=d.planner.prompt;document.getElementById('plannerplan').textContent=JSON.stringify(d.planner.plan,null,2);show(0)}).catch(e=>document.getElementById('explain').textContent='证据加载失败：'+e);
</script></html>'''


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--preparation',type=Path,required=True);p.add_argument('--band',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args();args.output.mkdir(exist_ok=True,parents=True)
    steps=[]
    for name in ('visual','coarse-motor','fine-motor'):
        req=args.source/(name+'-request.json');response=args.source/(name+'-response.json')
        steps.append(dict(request=json.loads(req.read_text()),response=json.loads(response.read_text()),filename=req.name))
        shutil.copyfile(req,args.output/req.name)
    data=dict(steps=steps,planner=dict(prompt=(args.preparation/'task-plan-prompt.txt').read_text(),
        plan=json.loads((args.preparation/'task-plan/plan.json').read_text())))
    (args.output/'data.json').write_text(json.dumps(data,ensure_ascii=False))
    (args.output/'index.html').write_text(HTML)
    shutil.copyfile(args.band,args.output/'band.png')
    shutil.copyfile(Path(__file__).with_name('LIBERO_HYBRID_RESULTS.md'),args.output/'report.md')
    print(args.output/'index.html')


if __name__=='__main__':main()

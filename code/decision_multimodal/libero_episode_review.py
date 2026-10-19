"""Build a portable review of actual model inputs and a measured rollout GIF."""
import argparse
import html
import json
from pathlib import Path


def build(root):
    from PIL import Image,ImageDraw
    records=[]
    for path in sorted((root/'evidence').glob('*-request.json')):
        reply=root/'decision-api'/path.name[:4]/'response.json'
        summary=root/'decision-api'/path.name[:4]/'request-summary.json'
        records.append(dict(request=json.loads(path.read_text()),
            observation=json.loads(summary.read_text()) if summary.exists() else {},
            response=json.loads(reply.read_text()) if reply.exists() else None))
    manifest=json.loads((root/'manifest.json').read_text()) if (root/'manifest.json').exists() else {}
    overview=manifest.get('overview_camera')
    frames=[]
    action_file=root/'execution.jsonl'
    actions=[json.loads(s) for s in action_file.read_text().splitlines()] if action_file.exists() else []
    for path in sorted(root.glob('*-agentview-input.png')):
        tick=int(path.name.split('-')[0]);other=root/f'{tick:04d}-robot0_eye_in_hand-input.png'
        if not other.exists():continue
        extra=root/f'{tick:04d}-{overview}-input.png' if overview else None
        width=1152 if extra is not None and extra.exists() else 768
        frame=Image.new('RGB',(width,430),'#13222c');draw=ImageDraw.Draw(frame)
        frame.paste(Image.open(path).convert('RGB').resize((384,384)),(0,46))
        frame.paste(Image.open(other).convert('RGB').resize((384,384)),(384,46))
        if width==1152:frame.paste(Image.open(extra).convert('RGB').resize((384,384)),(768,46))
        # Choices apply *after* this observation; label them honestly.
        following=next((a for a in actions if a['native_steps']>tick),None)
        draw.text((8,5),f'Actual observation: physical step {tick}; fixed agentview | moving wrist'+(' | fixed '+overview if width==1152 else ''),fill='white')
        if following:
            c=following['choices'];label=' '.join(k+':'+v[0] for k,v in c.items())
            draw.text((8,23),f'Next decision {following["decision"]}, stage {following["stage"]}: '+label,fill='white')
        frames.append(frame.quantize(colors=128))
    if frames:
        frames[0].save(root/'rollout.gif',save_all=True,append_images=frames[1:],duration=180,loop=0)
    result=json.loads((root/'result.json').read_text()) if (root/'result.json').exists() else {'status':'running'}
    data=json.dumps(records).replace('<','\\u003c')
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Actual robot episode evidence</title>
<style>body{font:16px system-ui;background:#13222c;color:#eef4f4;margin:32px;max-width:1500px}img{max-width:48%;vertical-align:top;margin:4px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#20333f;padding:16px}select{padding:10px}a{color:#70dce1}@media(max-width:700px){body{margin:16px}img{max-width:100%}pre{font-size:12px}}</style>
<h1>Actual robot episode evidence</h1><p>Historical demonstrations and previous views are labelled in their exact input order. No re-created model answers. The evaluator below is a report to the user and is never model input. GIF: one actual observation per decision, accelerated playback, not constant physics-time sampling.</p>'''
    page+='<pre>'+html.escape(json.dumps(result,indent=2))+'</pre><a href="rollout.gif">Actual observed rollout GIF</a><br><img style="max-width:100%" src="rollout.gif">'
    page+='<p><a href="manifest.json">Run configuration and source hashes</a> · <a href="execution.jsonl">Actual commands and measured motion</a> · <a href="perception.jsonl">Current sensor-feature audit</a> · <a href="protocols/">Protocol revisions actually used</a></p><h2>Exact request and original response</h2><label for="turn">Select API call </label><select id="turn"></select><div id="view"></div><script>const rows='+data+''';const select=document.getElementById('turn'),view=document.getElementById('view');rows.forEach((r,i)=>{const o=document.createElement('option');o.value=i;o.textContent='API call '+i+' | physical step '+r.observation.native_tick;select.append(o)});function pre(x){const p=document.createElement('pre');p.textContent=typeof x==='string'?x:JSON.stringify(x,null,2);view.append(p)}function show(){view.replaceChildren();const r=rows[+select.value];if(!r)return;pre({observation:r.observation});for(const p of r.request.input[0].content){if(p.type==='input_text')pre(p.text);else{const im=document.createElement('img');im.src='evidence/'+p.image_file;im.alt='Actual image supplied in this model request';im.loading='lazy';view.append(im)}}pre({questions:r.request.questions});pre({original_response:r.response})}select.onchange=show;show();</script></html>'''
    (root/'review.html').write_text(page)
    print(json.dumps(dict(review=str(root/'review.html'),actual_observations=len(frames),exact_requests=len(records))))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('episode',type=Path);build(p.parse_args().episode)

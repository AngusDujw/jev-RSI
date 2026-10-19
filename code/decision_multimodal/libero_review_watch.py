"""Refresh review pages over existing assets; never call a model or the simulator."""
import argparse
import html
import json
from pathlib import Path
import time

from libero_campaign_status import status
from libero_episode_review import build


def watch(campaigns, site):
    site.mkdir(parents=True,exist_ok=True);seen={}
    while True:
        rows=[];summaries=[]
        discovered={p.parent for base in {p.parent for p in campaigns} for p in base.glob('iteration-v*/campaign.json')}
        for campaign in sorted(set(campaigns)|discovered):
            try:
                report=status(campaign);summaries.append(report)
                cfg=json.loads((campaign/'campaign.json').read_text())
                for case,progress in zip(cfg['cases'],report['cases']):
                    if not case.get('record_evidence'):continue
                    root=Path(case['output'])
                    if not (root/'evidence').exists():continue
                    name=campaign.name+'-'+case['name'];link=site/name
                    if not link.exists():link.symlink_to(root,target_is_directory=True)
                    fingerprint=(progress['actions']//5,progress['result'] is not None)
                    if seen.get(name)!=fingerprint:
                        build(root);seen[name]=fingerprint
                    result=progress['result']
                    phase='running' if result is None else 'success' if result.get('success') else 'failed' if result.get('native_evaluated') else 'interrupted'
                    mode='Actor-selected surface XYZ + RGB orientation' if case.get('actor_attention') else 'RGB + current surface XYZ coordinates'
                    rows.append('<tr><td>'+html.escape(campaign.name)+(' (extended 1200-step development)' if case.get('horizon',600)>600 else '')+'</td><td><a href="'+name+'/review.html">'+html.escape(case['name'])+'</a></td><td>'+mode+'</td><td>'+phase+'</td><td>'+str(progress['stage'])+'</td><td>'+str(progress['physical_steps'])+'</td><td>'+str(progress['responses'])+'</td></tr>')
            except (OSError,ValueError) as error:
                print(json.dumps(dict(campaign=str(campaign),review_retry=type(error).__name__)),flush=True)
        stamp=time.strftime('%Y-%m-%d %H:%M:%S %z')
        page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Robot decision experiments</title><style>body{background:#13222c;color:#eef4f4;font:16px system-ui;margin:32px;max-width:1280px}a{color:#70dce1}table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:12px;border-bottom:1px solid #3b535e}th{color:#a8c6ce}.scroll{overflow-x:auto}small{color:#a8c6ce}</style><h1>Robot decision experiments</h1><p>Knob + bottle-on-rack. Actual recorded model inputs, images, original answers and robot execution.</p>'''
        page+='<small>Updated '+stamp+'. Reload to refresh. Stage changes and gripper commands are not task success.</small>'
        page+='<h2>Recorded episodes</h2><div class="scroll"><table><thead><tr><th>Iteration</th><th>Episode / exact evidence</th><th>Input assistance</th><th>Outcome</th><th>Stage</th><th>Physics steps</th><th>API answers</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'
        page+='<h2>Planner originals</h2><p><a href="planner-v2/prompt.txt">First request</a> · <a href="planner-v2/plan.json">First plan</a> · <a href="planner-review/prompt.txt">Follow-up request</a> · <a href="planner-review/plan.json">Follow-up plan and question contracts</a> · <a href="planner-affordance/prompt.txt">Grasp-region review request</a> · <a href="planner-affordance/plan.json">Grasp-region review output</a></p><p><a href="active-protocol.json">Live v7 protocol</a> (each episode retains its actual revisions) · <a href="camera-audit/own-geometry-depth.json">Own-robot camera check</a> · <a href="status.json">All cases and terminal outcomes</a></p><p>Planner: local Pro, GPT-6.1 Sol high. Actor: du, GPT-6 Luna, Decisions API. Cross-run experience files are not injected; current-episode history is supplied. Camera-derived positioning assistance is disclosed above. Desired orientation corrections are not computed.</p></html>'
        part=site/'index.part';part.write_text(page);part.replace(site/'index.html')
        (site/'status.json').write_text(json.dumps(summaries,indent=2))
        time.sleep(30)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--campaigns',nargs='+',type=Path,required=True);p.add_argument('--site',type=Path,required=True)
    a=p.parse_args();watch(a.campaigns,a.site)

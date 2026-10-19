"""Read-only native progress: actions and terminal results, not bridge heartbeat."""
import argparse
import json
from pathlib import Path
import time


def status(root):
    cfg=json.loads((root/'campaign.json').read_text());rows=[]
    for case in cfg['cases']:
        out=Path(case['output']);p=out/'execution.jsonl'
        actions=[json.loads(s) for s in p.read_text().splitlines() if s.strip()] if p.exists() else []
        result=json.loads((out/'result.json').read_text()) if (out/'result.json').exists() else None
        last=actions[-1] if actions else None
        ratios=[]
        for row in actions:
            a=row['commanded_translation_mm'];b=row['measured_translation_mm']
            norm=sum(v*v for v in a)
            if norm>1:ratios.append(sum(v*w for v,w in zip(a,b))/norm)
        rows.append(dict(name=case['name'],actions=len(actions),
            responses=len(list((out/'decision-api').glob('*/response.json'))),
            physical_steps=last['native_steps'] if last else 0,
            stage=last['stage'] if last else None,
            close_commands=sum(a['choices']['gripper']=='close' for a in actions),
            rotation_commands=sum(any(a['choices'][v]!='hold' for v in ('rx','ry','rz')) for a in actions),
            median_execution_ratio=round(sorted(ratios)[len(ratios)//2],3) if ratios else None,
            last_action_age_seconds=round(time.time()-p.stat().st_mtime,1) if p.exists() else None,
            result=result))
    return dict(campaign=str(root),finished=sum(r['result'] is not None for r in rows),
        native_evaluated=sum(bool((r['result'] or {}).get('native_evaluated')) for r in rows),
        native_success=sum(bool((r['result'] or {}).get('success')) for r in rows),cases=rows)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('campaign',type=Path)
    print(json.dumps(status(p.parse_args().campaign),indent=2))

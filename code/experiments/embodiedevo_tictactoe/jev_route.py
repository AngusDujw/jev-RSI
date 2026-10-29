"""Workspace CLI: select one prepared branch, then submit through original env.py."""
import argparse
import json
import os
from pathlib import Path
import urllib.request
import uuid
import env as native
from jev_protocol import admissible, english, VERSION

def main():
    p=argparse.ArgumentParser(); p.add_argument('plan',type=Path)
    p.add_argument('--endpoint',default=os.environ.get('JEV_ROUTER_URL','http://127.0.0.1:7934/route'))
    a=p.parse_args(); root=Path(os.environ.get('EMBODIEDEVO_WORKSPACE',Path.cwd())).resolve()
    plan_path=a.plan.resolve(); plan_path.relative_to(root)
    plan=json.loads(plan_path.read_text()); english(plan)
    status=native.request({'op':'status'})
    state=plan['state']
    if state.get('current_execution') != status['executions_used']:
        raise ValueError('Plan is stale: inspect current native observations before routing')
    if plan.get('observation') != status['observation']:
        raise ValueError('Plan observation does not match native current observation')
    for key in ('terminated','truncated','success','native_steps_remaining','executions_remaining'):
        state[key]=status[key]
    branches=plan.get('branches',{})
    if set(branches)-{'act','wait'}:raise ValueError('Unknown branch')
    state['available_branches']=list(branches)
    ident=uuid.uuid4().hex; folder=root/'scratch'/'jev-routing'/ident; folder.mkdir(parents=True)
    # Freeze candidate files before model selection; never accept generated source from Jev.
    snapshots={}
    for key,spec in branches.items():
        snapshots[key]=native.source_snapshot(root,spec['entry'],spec.get('includes',[]))
    (folder/'plan.json').write_text(json.dumps(plan,indent=2))
    (folder/'candidate-sources.json').write_text(json.dumps(snapshots,indent=2))
    req=urllib.request.Request(a.endpoint,data=json.dumps(state).encode(),headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=75) as r: result=json.load(r)
    except Exception as exc:
        record={'protocol':VERSION,'route':'observe','reason':'Jev transport failure','error_type':type(exc).__name__,'executed':False}
        (folder/'result.json').write_text(json.dumps(record,indent=2)); print(json.dumps(record)); return 0
    (folder/'jev-response.json').write_text(json.dumps(result,indent=2))
    choice=result['raw']['answers']['route']['choice']
    record={'protocol':VERSION,'request_id':result['request_id'],'jev_choice':choice,
            'usage':result['raw'].get('usage'),'executed':False}
    if choice not in admissible(state):
        record.update(route='observe',reason='Rejected incompatible Jev choice; visual planner must inspect')
    elif choice in ('observe','stop'):
        record.update(route=choice,reason='Returned to coding planner')
    else:
        latest=native.request({'op':'status'})
        if latest['executions_used'] != status['executions_used'] or latest['closed']:
            raise RuntimeError('Session changed during route selection; do not execute stale branch')
        # Original server handles all validation, termination, source evidence and budgets.
        feedback=native.request({'op':'exec','files':snapshots[choice]})
        record.update(route=choice,executed=True,feedback=feedback)
    (folder/'result.json').write_text(json.dumps(record,indent=2))
    print(json.dumps(record,indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())

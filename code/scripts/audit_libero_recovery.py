"""Audit actual Jev responses, recorded actions, recovery edges and input boundary."""
import argparse
import collections
import json
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--output',type=Path);a=p.parse_args()
allowed={'task','operation','next_operation','operation_contract','position_m','target_position_m','target_minus_current_mm','axis_hold_tolerance_mm','arrival_tolerance_mm','required_rotation_world_rad','gripper','completion_evidence','holding_evidence','allowed_transitions','selected_candidate','candidates','failed_candidates','grasp_attempts','recent_actions','blocked_action_count','phase_decisions','information_sources','local_decision_summary','evidence_interpretation'}
forbidden={'reward','success','object_poses','object_id','object_ids','goal_predicates','true_state','scene_layout','bddl','task_id','init_state'}

def walk(obj):
 if isinstance(obj,dict):
  assert not set(obj)&forbidden,set(obj)&forbidden
  for v in obj.values():walk(v)
 elif isinstance(obj,list):
  for v in obj:walk(v)

rows=[]
for rp in sorted(a.root.glob('**/result.json')):
 q=rp.parent
 if not (q/'protocol.json').exists() or not json.loads((q/'protocol.json').read_text()).get('recovery_supervisor'):continue
 ds=[json.loads(x) for x in (q/'decisions.jsonl').read_text().splitlines()] if (q/'decisions.jsonl').exists() else []
 decisions={d['decision_id']:d for d in ds}
 requests={}
 for d in ds:
  request=json.loads((q/d['decision_id']/'request.json').read_text());state=request['state'];assert set(state)<=allowed,set(state)-allowed;walk(state)
  assert not any('\u4e00'<=c<='\u9fff' for c in json.dumps(request,ensure_ascii=False)),q/d['decision_id']
  requests[d['decision_id']]=state
  if 'answers' in d:
   actual=json.loads((q/d['decision_id']/'response.json').read_text())['answers'];assert actual==d['answers']
   for k in ['gripper','transition']:assert actual[k]['choice']==d[k]
   if 'candidate' in actual:assert actual['candidate']['choice']==d['candidate']
   else:assert d['candidate']=='not_requested'
 branches=[json.loads(x) for x in (q/'branches.jsonl').read_text().splitlines()] if (q/'branches.jsonl').exists() else []
 prev=-1
 for b in branches:
  d=decisions[b['decision_id']];assert d['gripper']==b['selected_gripper'];assert d['transition']==b['selected_transition']
  expected=prev if d['gripper']=='keep' else -1 if d['gripper']=='open' else 1;assert expected==b['executed_gripper'];prev=expected
  assert all(v*s>=-1e-12 for v,s in zip(b['delta'],d['signs']))
 events=[json.loads(x) for x in (q/'events.jsonl').read_text().splitlines()]
 edges=[e for e in events if e.get('kind')=='phase_transition']
 for e in edges:
  d=decisions[e['decision_id']];s=requests[e['decision_id']];assert d['stage']==e['from_stage'];assert d['transition']==e['selected_transition']
  assert e['to_stage']==(s['next_operation'] if d['transition']=='advance' else 'recover_up')
 violations=[d['decision_id'] for d in ds if 'transition' in d and d['transition'] in ['advance','retry'] and not requests[d['decision_id']]['allowed_transitions'][d['transition']]]
 rows.append(dict(path=str(q),result=json.loads(rp.read_text()),decisions=len(ds),executed=len(branches),phase_edges=len(edges),contract_violations=violations,transition_choices=dict(collections.Counter(d.get('transition') for d in ds))))
result=dict(episodes=len(rows),audit='Actual Jev responses match gripper/actions/graph edges; signs preserved; all request text English; recursive forbidden keys absent. Input provenance additionally requires frozen-source review.',rows=rows)
text=json.dumps(result,indent=2)
if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(text+'\n')
print(text)

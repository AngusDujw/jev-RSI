"""Audit recorded ownership and model input allowlist, without simulation access."""
import argparse,json,collections,hashlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--output',type=Path);a=p.parse_args()
base_keys={'task','stage','next_phase','phase_contract','position_m','target_position_m','error_m','hold_tolerance_m','arrival_tolerance_m','gripper_qpos_m','last_gripper_command','current_phase_gripper_ticks','phase_native_ticks','phase_decisions','holding_evidence','geometry_source','source_label','destination_label','recovery_remaining','last_progress_m','stalls','error_mm','axis_relations','max_error_mm','phase_goal_distance_mm','recent_actions','gripper_aperture_mm','feedback_note','measurement_status','decision_protocol','rotation_control','rotation_error_rad','required_rotation_world_rad','rotation_relations','rotation_tolerance_rad','orientation_arrived','observation_age_native_steps','translation_axes','gripper','information_sources','carry_hover_replans'}
drawer_keys={'task','stage','next_stage','stage_contract','public_entity_slots','translation_axes','required_rotation_world_rad','gripper','completion_evidence','recent_actions','allowed_transitions','information_sources'}
forbidden={'reward','success','object_poses','object_id','object_ids','goal_predicates','true_state','scene_layout','bddl','task_id','init_state'}
def check_forbidden(value):
 if isinstance(value,dict):
  assert not set(value)&forbidden,set(value)&forbidden
  for child in value.values():check_forbidden(child)
 elif isinstance(value,list):
  for child in value:check_forbidden(child)
results=[]
for result_path in sorted(a.root.glob('**/result.json')):
 q=result_path.parent
 if not (q/'decisions.jsonl').exists():continue
 protocol=json.loads((q/'protocol.json').read_text()) if (q/'protocol.json').exists() else {}
 combined=bool(protocol.get('drawer_bowl_continuation'))
 rows=[json.loads(l) for l in (q/'decisions.jsonl').read_text().splitlines()];ds={r['decision_id']:r for r in rows}
 if combined:
  rows=[r for r in rows if r['stage'].startswith('0:open_drawer:')]
  ds={r['decision_id']:r for r in rows}
 if not rows or not all('transition' in r or 'error' in r for r in rows):continue
 branches=[json.loads(l) for l in (q/'branches.jsonl').read_text().splitlines()] if (q/'branches.jsonl').exists() else []
 if combined:branches=[b for b in branches if b['stage'].startswith('0:open_drawer:')]
 prev=-1
 for b in branches:
  d=ds[b['decision_id']];assert d['gripper']==b['selected_gripper'];assert d['transition']==b['selected_transition']
  expected=prev if d['gripper']=='keep' else -1 if d['gripper']=='open' else 1
  assert expected==b['executed_gripper'];prev=expected
  assert all(x*s>=-1e-12 for x,s in zip(b['delta'],d['signs']))
 events=[json.loads(l) for l in (q/'events.jsonl').read_text().splitlines()]
 edges=[e for e in events if e.get('kind')=='phase_transition']
 if combined:edges=[e for e in edges if e['from_stage'].startswith('0:open_drawer:')]
 for e in edges:assert ds[e['decision_id']]['transition']=='advance' and ds[e['decision_id']]['stage']==e['from_stage']
 for r in rows:
  request=json.load(open(q/r['decision_id']/'request.json'));allowed=drawer_keys if combined else base_keys;assert set(request['state'])<=allowed,set(request['state'])-allowed
  check_forbidden(request)
  assert json.dumps(request,ensure_ascii=False).isascii()
  if 'answers' in r:
   actual=json.load(open(q/r['decision_id']/'response.json'))['answers'];assert actual==r['answers'];assert set(actual)==set(request['questions'])
   assert all(actual[k]['choice']==r[k] for k in ['gripper','transition'])
   signs=dict(negative=-1,hold=0,positive=1)
   assert [signs[actual[k]['choice']] for k in 'xyz']==r['signs']
   assert [signs[actual[k]['choice']] if k in actual else 0 for k in ['rx','ry','rz']]==r['rotation_signs']
 out=dict(path=str(q),result=json.load(open(result_path)),decisions=len(rows),executed_decisions=len(branches),transitions=len(edges),gripper_choices=dict(collections.Counter(r.get('gripper') for r in rows)),transition_choices=dict(collections.Counter(r.get('transition') for r in rows)))
 results.append(out)
report=json.dumps(dict(episodes=len(results),audit='actual Jev responses match recorded directions/gripper/transitions and executed actions/phase edges; request text ASCII; root fields allowlisted and recursive forbidden keys absent; code/source review still required for provenance',rows=results),indent=2)
if a.output:a.output.write_text(report+'\n')
print(report)

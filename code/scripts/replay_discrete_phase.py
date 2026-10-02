"""Model-only diagnostic on a saved permitted observation; no simulator calls."""
import argparse,json,sys,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--run',required=True);args=p.parse_args()
run=Path(args.run);cfg=json.loads((run/'protocol.json').read_text())
sys.path.insert(0,cfg['existing_root']+'/controller/src')
from realman_jev.api import API
out=run.parent/(run.name+'-phase-replay');out.mkdir(exist_ok=False)
api=API(json.loads(Path(cfg['api_config']).read_text())['jev'],lambda e:print(json.dumps(e),flush=True),'jev')
source=json.loads((run/'decision-0000/request.json').read_text());s=source['state'];plan=s['phase_evidence'].get('candidate_plan');ids=[]
if plan:ids=[plan['source']]
compact=dict(instruction=s['instruction'],current_stage=s['stage'],candidate_next_stage=s['next_stage_candidate'],candidate_plan=plan,
    visible_objects=s['visibility'],perception_error=s['perception_error'],selected_ids=ids,
    purpose='Only decide whether object selection is complete and robot may BEGIN approach. Object need not be grasped or lifted yet. Do not assess full task success.')
variants=[('full_specific',s),('compact_specific',compact)]
try:
 for name,state in variants:
  questions=dict(phase=dict(type='choice',instructions='Decide whether to finish SELECT and begin APPROACH. Selection is complete if an instruction-relevant source and a feasible candidate plan are available from observed RGB-D. This phase requires NO robot movement, grasp, lift, or task success. Lack of grasp/lift evidence is irrelevant at SELECT.',
      criteria=dict(advance='A source and a usable candidate plan are available: begin approaching it.',reobserve='A source or usable plan is missing or ambiguous: obtain another observation.')))
  payload=dict(model=api.cfg['model'],state=state,questions=questions)
  (out/(name+'-request.json')).write_text(json.dumps(payload,indent=2))
  start=time.monotonic();response=api.post('/systemone',payload)
  (out/(name+'-response.json')).write_text(json.dumps(response,indent=2));print(name,response.get('answers'),time.monotonic()-start,flush=True)
finally:api.close()
